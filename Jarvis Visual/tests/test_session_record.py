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
import pathlib
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
        self.assertEqual(sr.main([]), 0)   # no stdin, no path -> does nothing

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
