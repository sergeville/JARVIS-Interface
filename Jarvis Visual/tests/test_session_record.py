"""session_record.py -- a typed conversation records itself, like a spoken one.

Serge, 2026-08-07 ~7:20 PM: "so we don't lose anything."

The tests that matter here are not about parsing. They are about the four ways
this tool could quietly do harm, each of which is cheap to introduce and hard
to notice:

  1. Recording the VOICE brain as well, so every spoken turn is written twice.
  2. Guessing which conversation it is in, so one session's words land in
     another session's file -- on a machine that routinely runs several at
     once, this is not a hypothetical.
  3. Writing into the voice line's own daily transcript, which the HUD reads
     as "what was said out loud".
  4. Losing an earlier line to a later run. It is append-only and idempotent,
     and both halves are pinned.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "vault-tools" / "session_record.py"

spec = importlib.util.spec_from_file_location("session_record", SRC)
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


def row(kind, text, uuid, ts="2026-08-07T14:30:00.000Z", entry="cli", **kw):
    d = {"type": kind, "uuid": uuid, "timestamp": ts, "entrypoint": entry,
         "message": {"content": text}}
    d.update(kw)
    return json.dumps(d)


class _ClosedStdin:
    """`sr.main([])` with a stdin that is already at EOF.

    ADVERSARY FINDING 6, and it is about incentives rather than correctness:
    these two tests call main() in-process, so against the runner's inherited
    stdin each one burned the FULL STDIN_BUDGET waiting for a payload that was
    never coming -- three of them, adding ~15s to every suite run. Nothing was
    wrong with the assertions; the cost was pure artifact. But a slow gate is
    the pressure that makes the next person shrink STDIN_BUDGET to speed it up,
    which is the one change that silently drops real turns. Removing the cost
    removes the temptation.
    """
    def __enter__(self):
        self.fh = open(os.devnull)
        self.saved = sys.stdin
        sys.stdin = self.fh
        return self

    def __exit__(self, *exc):
        sys.stdin = self.saved
        self.fh.close()
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.saved = (sr.TRANSCRIPTS, sr.WATERMARK)
        sr.TRANSCRIPTS = self.dir / "transcripts"
        sr.WATERMARK = sr.TRANSCRIPTS / ".terminal-watermarks.json"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.restore)

    def restore(self):
        sr.TRANSCRIPTS, sr.WATERMARK = self.saved

    def log(self, *lines, name="sess"):
        p = self.dir / f"{name}.jsonl"
        p.write_text("\n".join(lines) + "\n")
        return p

    def day(self, d="2026-08-07"):
        f = sr.TRANSCRIPTS / f"{d}-terminal.md"
        return f.read_text() if f.exists() else ""


class WhatItRecords(Base):
    def test_a_typed_turn_lands_in_the_voice_transcript_format(self):
        # Same format on purpose: a second format needs a second reader, and
        # the readers already exist.
        sr.record(self.log(row("user", "hi", "u1"),
                           row("assistant", "At your service.", "a1")))
        self.assertIn("- **10:30:00 Serge:** hi", self.day())
        self.assertIn("- **10:30:00 Jarvis:** At your service.", self.day())

    def test_the_text_blocks_of_a_rich_message_are_kept(self):
        msg = [{"type": "text", "text": "the answer"}]
        sr.record(self.log(row("assistant", msg, "a1")))
        self.assertIn("the answer", self.day())

    def test_tool_traffic_and_thinking_are_dropped(self):
        # This is the CONVERSATION. The tool work is already recorded in the
        # notes it produced and in git; inlining it makes the file unreadable,
        # which is the same as not having one.
        msg = [{"type": "thinking", "thinking": "SECRET REASONING"},
               {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
               {"type": "text", "text": "done"}]
        sr.record(self.log(row("assistant", msg, "a1")))
        got = self.day()
        self.assertIn("done", got)
        for leak in ("SECRET REASONING", "tool_use", "Bash", "ls"):
            self.assertNotIn(leak, got, f"{leak} reached the transcript")

    def test_harness_furniture_is_stripped_from_his_turn(self):
        # Quoting the machine back at him as though he said it is worse than
        # no transcript.
        text = "<system-reminder>boot noise</system-reminder>what's next?"
        sr.record(self.log(row("user", text, "u1")))
        self.assertNotIn("boot noise", self.day())
        self.assertIn("what's next?", self.day())

    def test_a_tag_nobody_has_met_yet_is_still_stripped(self):
        # CAUGHT ON THE FIRST REAL BACKFILL, not by a test: the original strip
        # list named the four blocks it had seen, and seventeen
        # <local-command-caveat> and ten <task-notification> blocks went into
        # the file as things Serge said. A denylist of remembered tags loses
        # to the next tag. So the rule is now shape-based, and this test is
        # the one that keeps it that way -- it uses a tag that does not exist.
        text = ("<invented-block-2099>machine noise</invented-block-2099>"
                "the actual words")
        sr.record(self.log(row("user", text, "u1")))
        got = self.day()
        self.assertNotIn("machine noise", got)
        self.assertNotIn("invented-block", got)
        self.assertIn("the actual words", got)

    def test_a_lone_unpaired_tag_does_not_survive_either(self):
        sr.record(self.log(row("user", "<command-args></command-args>ok", "u1")))
        self.assertNotIn("command-args", self.day())

    def test_a_turn_is_one_line(self):
        # The file is read by TAILING it. A turn spanning forty lines defeats
        # the one thing the format is for.
        sr.record(self.log(row("user", "line one\nline two\n\nline three", "u1")))
        body = [x for x in self.day().splitlines() if x.strip()]
        self.assertEqual(len(body), 1, body)

    def test_a_turn_with_nothing_said_writes_nothing(self):
        msg = [{"type": "tool_use", "name": "Bash", "input": {}}]
        self.assertEqual(sr.record(self.log(row("assistant", msg, "a1"))), 0)


class TheFourHarms(Base):
    def test_the_VOICE_brain_is_never_recorded_here(self):
        # It already writes itself down through signals.log_transcript.
        # Recording it here would double every spoken turn in the same folder.
        n = sr.record(self.log(row("user", "spoken", "u1", entry="sdk-py"),
                               row("assistant", "spoken back", "a1",
                                   entry="sdk-py")))
        self.assertEqual(n, 0)
        self.assertEqual(self.day(), "")

    def test_a_subagent_side_chain_is_not_his_conversation(self):
        n = sr.record(self.log(row("assistant", "agent chatter", "a1",
                                   isSidechain=True)))
        self.assertEqual(n, 0)

    def test_it_never_guesses_which_conversation_it_is_in(self):
        # On a machine running several sessions at once, a fallback to "the
        # newest log" writes one session's words into another's file.
        src = SRC.read_text()
        for guess in ("glob(", "sorted(base", "max(", "getmtime", "st_mtime"):
            start = src.index("def main(")
            self.assertNotIn(guess, src[start:src.index("--all") ] + "",
                             "main() picks a session by guessing")
        with _ClosedStdin():
            self.assertEqual(sr.main([]), 0)  # nothing piped in -> does nothing

    def test_it_does_not_guess_EVEN_WHEN_A_LOG_IS_SITTING_RIGHT_THERE(self):
        # CAUGHT BY INJECTION. The test above passed with a "fall back to the
        # newest .jsonl" fault installed, because it ran in a directory that
        # had none -- so it proved the fallback never FIRED, not that it does
        # not exist. A guard only proves what it looks at.
        import os
        self.log(row("user", "another session's words", "u1"))
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            with _ClosedStdin():
                sr.main([])
        finally:
            os.chdir(cwd)
        self.assertEqual(self.day(), "",
                         "a hook with no session of its own picked one and "
                         "wrote another conversation's words into the record")

    def test_it_writes_beside_the_voice_transcript_never_into_it(self):
        # The HUD reads YYYY-MM-DD.md as the voice conversation. Typed turns
        # in it would be a lie about what was said out loud.
        sr.TRANSCRIPTS.mkdir(parents=True)
        voice = sr.TRANSCRIPTS / "2026-08-07.md"
        voice.write_text("- **09:00:00 Serge:** spoken\n")
        sr.record(self.log(row("user", "typed", "u1")))
        self.assertEqual(voice.read_text(), "- **09:00:00 Serge:** spoken\n",
                         "the voice line's own transcript was written into")
        self.assertIn("typed", self.day())


class AppendOnlyAndIdempotent(Base):
    def test_running_twice_does_not_duplicate_a_day(self):
        log = self.log(row("user", "once", "u1"))
        sr.record(log)
        sr.record(log)
        self.assertEqual(self.day().count("once"), 1)

    def test_a_session_that_grows_appends_only_what_is_new(self):
        log = self.log(row("user", "first", "u1"))
        sr.record(log)
        log.write_text(row("user", "first", "u1") + "\n"
                       + row("assistant", "second", "a1") + "\n")
        added = sr.record(log)
        self.assertEqual(added, 1)
        self.assertEqual(self.day().count("first"), 1)
        self.assertIn("second", self.day())

    def test_an_earlier_line_is_never_rewritten_away(self):
        # The property the voice transcript and the stack event log are both
        # built on: a file only ever appended to cannot lose an earlier line
        # to a later bug.
        sr.record(self.log(row("user", "monday", "u1",
                               ts="2026-08-06T14:00:00.000Z"), name="a"))
        sr.record(self.log(row("user", "tuesday", "u2"), name="b"))
        self.assertIn("monday", self.day("2026-08-06"))
        self.assertIn("tuesday", self.day("2026-08-07"))

    def test_two_sessions_on_one_day_both_survive(self):
        sr.record(self.log(row("user", "from session one", "u1"), name="one"))
        sr.record(self.log(row("user", "from session two", "u2"), name="two"))
        got = self.day()
        self.assertIn("from session one", got)
        self.assertIn("from session two", got)

    def test_the_watermark_actually_advances(self):
        # RECORDED HONESTLY: neutering the watermark entirely does NOT change
        # what gets written -- the already-written-line check catches the
        # duplicates on its own. So the watermark is not the correctness
        # guard, it is the reason a Stop hook firing on every turn does not
        # re-read nine hundred lines each time. That is worth keeping and
        # worth pinning, because a silently dead optimisation is one nobody
        # notices until the file is large.
        log = self.log(row("user", "hi", "u1"))
        sr.record(log)
        marks = json.loads(sr.WATERMARK.read_text())
        self.assertEqual(marks.get("sess"), "u1")

    def test_a_replaced_log_does_not_duplicate_what_is_already_written(self):
        # A watermark naming a uuid the file no longer has means the file was
        # replaced, not advanced. The fallback re-reads from the top, so the
        # written-line check is what stops the day being doubled.
        sr.record(self.log(row("user", "kept", "u1")))
        self.log(row("user", "kept", "zz9"))          # same words, new uuid
        sr.record(self.dir / "sess.jsonl")
        self.assertEqual(self.day().count("kept"), 1)


class ItStaysOutOfGit(unittest.TestCase):
    def test_the_folder_it_writes_to_is_gitignored(self):
        # It writes Serge's verbatim typed conversations into a PUBLIC repo's
        # working tree. This is the check that keeps that safe, and it is
        # asserted rather than assumed.
        import subprocess
        r = subprocess.run(
            ["git", "check-ignore", "-q",
             "Jarvis Visual/transcripts/2026-01-01-terminal.md"],
            cwd=ROOT)
        self.assertEqual(r.returncode, 0,
                         "the terminal transcript is NOT gitignored -- it "
                         "would be published on the next commit")

    def test_the_watermark_lives_with_the_files_it_describes(self):
        self.assertIn("transcripts", str(sr.WATERMARK))


class AHookMustNeverBlock(unittest.TestCase):
    """Harm 5, found 2026-08-14 when the full suite hung for ten minutes.

    `_hook_path()`'s own docblock promises: "A HOOK MUST NEVER BLOCK... If
    nobody is piping anything in, there is no session to record and it says so
    immediately." It kept that promise with `sys.stdin.isatty()`, which catches
    exactly ONE way of nobody piping anything in -- an interactive terminal.

    An inherited pipe that stays open and never delivers is NOT a tty. The
    guard passes, `json.load(sys.stdin)` blocks, and it never returns. This
    hook is wired into EVERY session on this machine, so that is a hang in
    every conversation, not merely in the suite that happened to find it.

    The guard tested a proxy (is it a terminal?) instead of the property it
    promised (is anything actually coming?). These run in a subprocess because
    a parent that blocks cannot un-block itself to report.
    """

    BUDGET = 15.0

    def _hook_path_with_stdin(self, read_fd, budget=0.5):
        """Returns (returncode, stdout) -- or (None, '') if it never returned.

        `budget` overrides STDIN_BUDGET inside the subprocess ON PURPOSE. What
        these tests prove is that every path RETURNS -- boundedness, which is a
        property of the loop and not of the number. Waiting the real 12s to
        prove it would add half a minute to every suite run, and the adversary
        named a slow gate as the thing that makes the next person shrink the
        constant to speed it up. The constant's actual VALUE is pinned
        separately, against the hook's configured timeout, by
        test_the_budget_is_pinned_to_the_configured_hook_timeout.
        """
        code = (
            "import importlib.util as u\n"
            f"s = u.spec_from_file_location('sr', {str(SRC)!r})\n"
            "m = u.module_from_spec(s)\n"
            "s.loader.exec_module(m)\n"
            f"m.STDIN_BUDGET = {budget!r}\n"
            "print(m._hook_path())\n"
        )
        p = subprocess.Popen([sys.executable, "-c", code], stdin=read_fd,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, _ = p.communicate(timeout=self.BUDGET)
            return p.returncode, out.decode()
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            return None, ""

    def test_an_open_stdin_that_never_delivers_does_not_hang(self):
        r, w = os.pipe()  # open, not a tty, and nothing will ever be written
        try:
            rc, out = self._hook_path_with_stdin(r)
        finally:
            os.close(r)
            os.close(w)
        self.assertIsNotNone(
            rc, f"_hook_path() never returned within {self.BUDGET}s on a stdin "
                "that is open but silent -- this hook runs every turn, so that "
                "is a hang in every conversation on the machine")
        self.assertEqual(out.strip(), "None",
                         "nothing was piped in, so there is no session to record")

    def test_a_REAL_hook_payload_is_STILL_READ(self):
        # The test above is satisfied by a "fix" that returns None
        # unconditionally -- which would silently switch session recording off
        # for the whole machine and look perfectly green. This is the half that
        # refuses that fix.
        r, w = os.pipe()
        os.write(w, json.dumps({"transcript_path": "/tmp/a-real-session.jsonl"}).encode())
        os.close(w)  # EOF, exactly as a real hook caller does
        try:
            rc, out = self._hook_path_with_stdin(r)
        finally:
            os.close(r)
        self.assertIsNotNone(rc, "a real hook payload was not read at all")
        self.assertIn("/tmp/a-real-session.jsonl", out,
                      "the payload Claude Code piped in was dropped -- session "
                      "recording is off and every turn is being lost")

    def test_the_isatty_guard_is_not_redundant(self):
        # ADVERSARY FINDING 1, the most damning: deleting the isatty block left
        # the whole suite GREEN, and it is load-bearing. A tty with a line typed
        # and no Ctrl-D is "ready" as far as select is concerned, so without
        # isatty an interactive run falls into a read waiting for an EOF the
        # human has not sent -- the original hang, in the one place a person
        # would actually meet it. Nothing pinned the line until this.
        import pty
        master, slave = pty.openpty()
        os.write(master, b'{"transcript_path": "/tmp/typed.jsonl"}\n')
        try:
            rc, out = self._hook_path_with_stdin(slave)
        finally:
            os.close(slave)
            os.close(master)
        self.assertIsNotNone(
            rc, "a tty with a line typed and no Ctrl-D hung the hook -- the "
                "isatty guard was removed or defeated")
        self.assertEqual(out.strip(), "None",
                         "a terminal is never a hook caller")

    def test_a_COMPLETE_payload_on_a_pipe_that_never_closes_IS_READ(self):
        # BOTH AGENTS CAUGHT THIS INDEPENDENTLY, and my first comment named the
        # wrong cause. The residual was never about PARTIAL writes -- json.load
        # calls read(), which runs to EOF, so a complete and perfectly valid
        # payload hung just as hard when the writer held its end open. The read
        # now stops the moment the bytes parse, so no EOF is required.
        r, w = os.pipe()
        os.write(w, json.dumps({"transcript_path": "/tmp/never-closed.jsonl"}).encode())
        try:                                    # deliberately NOT closing w
            rc, out = self._hook_path_with_stdin(r)
        finally:
            os.close(r)
            os.close(w)
        self.assertIsNotNone(
            rc, "a COMPLETE payload on a pipe the writer never closed still "
                "hangs -- 'A HOOK MUST NEVER BLOCK' is still not true")
        self.assertIn("/tmp/never-closed.jsonl", out,
                      "the payload was there in full and was dropped anyway")

    def test_a_PARTIAL_payload_on_an_open_pipe_is_bounded_not_infinite(self):
        # The genuinely incomplete case cannot be answered -- but it must still
        # END. Bounded and empty-handed beats correct and never returning.
        r, w = os.pipe()
        os.write(w, b'{"transcript_path": "/tmp/half')   # no closing brace
        try:
            rc, out = self._hook_path_with_stdin(r)
        finally:
            os.close(r)
            os.close(w)
        self.assertIsNotNone(rc, "an incomplete payload blocked forever")
        self.assertEqual(out.strip(), "None")

    def test_an_IN_MEMORY_stdin_is_still_read(self):
        # ADVERSARY FINDING 4, a silent regression the first fix introduced:
        # io.UnsupportedOperation subclasses BOTH ValueError and OSError, so a
        # plain `except (ValueError, OSError)` swallowed "this stream has no
        # fileno" and turned a working read into a dropped turn. io.StringIO is
        # exactly how the other hooks in this repo are tested in-process, so the
        # next person to copy that pattern would have got a green test proving
        # nothing.
        code = (
            "import io, sys\n"
            "import importlib.util as u\n"
            f"s = u.spec_from_file_location('sr', {str(SRC)!r})\n"
            "m = u.module_from_spec(s)\n"
            "s.loader.exec_module(m)\n"
            'sys.stdin = io.StringIO(\'{"transcript_path": "/tmp/mem.jsonl"}\')\n'
            "print(m._read_payload())\n"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             timeout=self.BUDGET).stdout.decode()
        self.assertIn("/tmp/mem.jsonl", out,
                      "an in-memory stdin is silently dropped")

    def test_a_payload_that_is_not_an_object_exits_ZERO(self):
        # ADVERSARY FINDING 7, pre-existing and three lines below the fix:
        # json.load happily returns null, a list or a bare string, and then
        # .get raised AttributeError -- an uncaught traceback and a non-zero
        # exit, every turn. A hook that dies loudly every turn is the next long
        # debugging session.
        for payload in ("null", "[]", '"just a string"', "7",
                        '{"transcript_path": 7}', '{"transcript_path": ""}',
                        "{}"):
            with self.subTest(payload=payload):
                r, w = os.pipe()
                os.write(w, payload.encode())
                os.close(w)
                try:
                    rc, out = self._hook_path_with_stdin(r)
                finally:
                    os.close(r)
                self.assertEqual(rc, 0, f"{payload} crashed the hook")
                self.assertEqual(out.strip(), "None", f"{payload} was not refused")

    def test_a_payload_SPLIT_ACROSS_TWO_WRITES_is_reassembled(self):
        # MY OWN INJECTION ROUND CAUGHT THIS, not either agent: replacing
        # `chunks.append(chunk)` with `chunks = [chunk]` -- so only the final
        # read survives and nothing is ever reassembled -- passed the whole
        # suite GREEN. Every other test writes its payload in a single write,
        # so the multi-chunk path they all depend on was never once exercised.
        # A 64KB pipe buffer or a caller that writes a header first is enough
        # to split a real payload.
        r, w = os.pipe()
        blob = json.dumps({"transcript_path": "/tmp/split.jsonl"}).encode()
        head, tail = blob[:12], blob[12:]
        pid = os.fork()
        if pid == 0:
            os.close(r)
            try:
                os.write(w, head)
                __import__("time").sleep(0.3)   # force a second read
                os.write(w, tail)
                os.close(w)
            finally:
                os._exit(0)
        os.close(w)
        try:
            rc, out = self._hook_path_with_stdin(r, budget=4.0)
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        self.assertIsNotNone(rc, "a split payload hung the read")
        self.assertIn("/tmp/split.jsonl", out,
                      "a payload delivered in two chunks was not reassembled")

    def test_a_READ_ERROR_stops_the_loop_instead_of_spinning_out_the_budget(self):
        # SECOND SURVIVOR FROM MY INJECTION ROUND: turning the loop's
        # `except (ValueError, OSError): break` into `pass` also shipped green,
        # because both spellings still return None -- one immediately, the other
        # after busy-spinning on a raising select for the WHOLE budget. With the
        # real 12s constant that is twelve seconds of hot CPU inside a hook that
        # runs every turn, and no test could tell the two apart. This one can:
        # it hands over a stdin whose descriptor is closed, gives a deliberately
        # LARGE budget, and demands a fast answer.
        code = (
            "import os, sys\n"
            "import importlib.util as u\n"
            f"s = u.spec_from_file_location('sr', {str(SRC)!r})\n"
            "m = u.module_from_spec(s)\n"
            "s.loader.exec_module(m)\n"
            "m.STDIN_BUDGET = 10.0\n"
            "os.close(0)\n"                       # every select/read now raises
            "print(m._read_payload())\n"
        )
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           timeout=self.BUDGET)
        elapsed = time.monotonic() - t0
        self.assertEqual(r.stdout.decode().strip(), "None")
        self.assertLess(
            elapsed, 3.0,
            f"a stdin that raises on every read spun for {elapsed:.1f}s of a "
            "10s budget instead of giving up -- that is a hot loop inside a "
            "hook that runs on every turn")

    def test_the_budget_is_pinned_to_the_configured_hook_timeout(self):
        # ADVERSARY FINDING 5: the LATE test only pins ~0.8s, so 5.0 -> 0.8
        # shipped green while racing real callers for real. This pins the
        # constant against something OUTSIDE it -- the timeout the hook is
        # actually deployed with -- so it cannot be satisfied by reading itself.
        # The template is used rather than .claude/settings.json because the
        # live files are gitignored and would not exist in a fresh clone.
        tmpl = json.loads((ROOT / "templates" /
                           "claude-settings.json.template").read_text())
        timeouts = [h.get("timeout") for groups in tmpl.get("hooks", {}).values()
                    for g in groups for h in g.get("hooks", [])
                    if "session_record.py" in h.get("command", "")
                    and h.get("timeout") is not None]
        self.assertTrue(timeouts, "the hook lost its configured timeout")
        ceiling = min(timeouts)
        self.assertLess(sr.STDIN_BUDGET, ceiling,
                        "the budget outlives the timeout that kills the hook, "
                        "so the read is bounded by nothing it controls")
        self.assertGreaterEqual(
            sr.STDIN_BUDGET, 0.6 * ceiling,
            "the budget was shrunk well under the hook's own timeout, which "
            "buys nothing and widens the window where a slow caller's turn is "
            "dropped in silence")

    def test_a_payload_that_arrives_LATE_is_still_read(self):
        # A bounded wait must be long enough for a real caller that is a beat
        # slow. A zero-timeout readiness check would race and drop real work.
        r, w = os.pipe()
        payload = json.dumps({"transcript_path": "/tmp/slow.jsonl"}).encode()
        pid = os.fork()
        if pid == 0:  # child: write after a deliberate delay, then exit hard
            os.close(r)
            try:
                __import__("time").sleep(0.75)
                os.write(w, payload)
                os.close(w)
            finally:
                os._exit(0)
        os.close(w)
        try:
            rc, out = self._hook_path_with_stdin(r, budget=4.0)
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        self.assertIsNotNone(rc, "a slightly slow caller was treated as a hang")
        self.assertIn("/tmp/slow.jsonl", out,
                      "a real payload that arrived 0.75s late was dropped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
