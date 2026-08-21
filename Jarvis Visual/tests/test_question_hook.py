"""`voice-line/question_hook.py` end to end. The file that did not exist.

WHY THIS FILE EXISTS. Both agents that audited `69fb519` independently asked
for it, and the adversary showed why with an injection: make `main()` throw its
payload away --

    data = _read_stdin() or {}   ->   data = {}

-- and the ENTIRE suite stayed green. `_read_stdin` becomes dead code in the
one file whose unguarded read started that whole run of fixes. `grep -rn
question_hook` over this directory returned six hits before this file: five
settings-wiring assertions and one line of prose. Nothing anywhere drove it.

What that injection costs is visible on Serge's own screen, which is the point:
the `stop` path never finds `transcript_path`, so the waiting-question banner is
blank every turn, and the `notify` path never sees `"permission"` in the
message, so every permission prompt degrades to the generic "Jarvis is waiting
for you at the terminal." The hook keeps exiting 0 throughout. It fails to
NOTHING and it looks installed -- the shape this project has now been bitten by
five times.

So these tests assert THE PAYLOAD REACHED THE WORK, never merely that the hook
returned. `test_hooks_never_block.py` owns "it comes back"; this file owns "it
did the job it came back from".

Everything runs against a throwaway copy of the tree. `QUESTION_FILE` is
`Path(__file__).resolve().parent / ".voice_question"`, so a copy relocates the
hook's only piece of state and nothing here can touch the live banner.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK_REL = "voice-line/question_hook.py"


def _sandbox():
    """A private copy of the script tree; the hook's state lands inside it."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-qhook-"))
    for d in ("vault-tools", "voice-line"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
        for f in (ROOT / d).glob("*.py"):
            shutil.copy2(f, tmp / d / f.name)
    return tmp


def _load_module(box):
    spec = importlib.util.spec_from_file_location(
        "question_hook_under_test", str(box / HOOK_REL))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Sandboxed(unittest.TestCase):

    def setUp(self):
        self.box = _sandbox()
        self.banner = self.box / "voice-line" / ".voice_question"

    def tearDown(self):
        shutil.rmtree(self.box, ignore_errors=True)

    def run_hook(self, mode, payload, close=True, timeout=20):
        """Drive the REAL deployed command line and return its exit code.

        A subprocess, not an in-process call: the deployed thing is
        `python3 .../question_hook.py <mode>` with a payload on stdin, and an
        in-process call cannot observe the exit code the harness actually
        reads, nor a hang.
        """
        r, w = os.pipe()
        try:
            if payload is not None:
                os.write(w, json.dumps(payload).encode())
            if close:
                os.close(w)
            p = subprocess.Popen(
                [sys.executable, str(self.box / HOOK_REL), mode],
                stdin=r, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(self.box))
            try:
                p.communicate(timeout=timeout)
                return p.returncode
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
                self.fail(f"question_hook.py {mode} never returned")
        finally:
            os.close(r)
            if not close:
                os.close(w)

    def transcript(self, *assistant_texts, sidechain_last=None):
        """A JSONL session transcript of the shape the Stop hook is handed."""
        path = self.box / "transcript.jsonl"
        lines = []
        for t in assistant_texts:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": t}]}}))
        if sidechain_last is not None:
            lines.append(json.dumps({
                "type": "assistant", "isSidechain": True,
                "message": {"content": [{"type": "text",
                                         "text": sidechain_last}]}}))
        path.write_text("\n".join(lines) + "\n")
        return str(path)


class TestThePayloadReachesTheWork(_Sandboxed):
    """The injection that killed the old gate: `data = {}` must go RED here."""

    def test_notify_writes_THE_PERMISSION_MESSAGE_from_the_payload(self):
        # THE ASSERTION THAT KILLS `data = {}`. The generic fallback line is
        # also written on this path when the payload is empty, so asserting
        # merely "the file exists" would pass with the payload thrown away.
        # It has to be the message that came in.
        rc = self.run_hook("notify", {
            "message": "Claude needs your permission to use Bash"})
        self.assertEqual(rc, 0)
        self.assertEqual(self.banner.read_text(),
                         "Jarvis needs your permission to use Bash")

    def test_stop_writes_THE_QUESTION_from_the_transcript_in_the_payload(self):
        path = self.transcript("Everything is green. Shall I push it?")
        rc = self.run_hook("stop", {"transcript_path": path})
        self.assertEqual(rc, 0)
        self.assertEqual(self.banner.read_text(), "Shall I push it?")

    def test_an_UNCLOSED_writer_still_delivers_the_payload_to_the_work(self):
        # The two properties together, which is where the real bug lived: it is
        # not enough to return, and not enough to read -- it has to read and
        # then do the job, on a pipe the caller never closed.
        rc = self.run_hook("notify", {
            "message": "Claude needs your permission to use Write"},
            close=False)
        self.assertEqual(rc, 0)
        self.assertEqual(self.banner.read_text(),
                         "Jarvis needs your permission to use Write")


class TestTheThreeModes(_Sandboxed):

    def test_clear_removes_the_banner(self):
        self.banner.write_text("an old question?")
        self.assertEqual(self.run_hook("clear", {}), 0)
        self.assertFalse(self.banner.exists())

    def test_stop_clears_the_banner_when_the_reply_asks_nothing(self):
        self.banner.write_text("a stale question?")
        path = self.transcript("All done. Pushed and verified.")
        self.run_hook("stop", {"transcript_path": path})
        self.assertFalse(self.banner.exists())

    def test_stop_with_no_transcript_path_clears_rather_than_crashes(self):
        self.banner.write_text("a stale question?")
        self.assertEqual(self.run_hook("stop", {}), 0)
        self.assertFalse(self.banner.exists())

    def test_stop_with_a_transcript_path_that_does_not_exist_still_exits_0(self):
        self.assertEqual(
            self.run_hook("stop", {"transcript_path": "/nope/none.jsonl"}), 0)

    def test_notify_writes_the_generic_line_only_when_nothing_is_pending(self):
        self.assertEqual(self.run_hook("notify", {"message": "idle"}), 0)
        self.assertEqual(self.banner.read_text(),
                         "Jarvis is waiting for you at the terminal.")

    def test_a_generic_nudge_NEVER_CLOBBERS_a_real_pending_question(self):
        # The hook's own docstring promises this and nothing tested it. It is
        # the difference between the banner telling Serge what was asked and
        # the banner telling him only that something was.
        self.banner.write_text("Shall I push it?")
        self.run_hook("notify", {"message": "Claude is waiting for input"})
        self.assertEqual(self.banner.read_text(), "Shall I push it?")

    def test_a_permission_prompt_DOES_replace_a_pending_question(self):
        # The other side of the same rule: a permission prompt is more urgent
        # than the question it interrupts, so it is the one thing allowed to
        # overwrite. Pinned so the guard above cannot be widened by accident.
        self.banner.write_text("Shall I push it?")
        self.run_hook("notify", {"message": "Claude needs your permission"})
        self.assertEqual(self.banner.read_text(),
                         "Jarvis needs your permission")

    def test_an_unknown_mode_does_nothing_and_exits_0(self):
        self.banner.write_text("Shall I push it?")
        self.assertEqual(self.run_hook("wat", {"message": "x"}), 0)
        self.assertEqual(self.banner.read_text(), "Shall I push it?")

    def test_no_mode_at_all_exits_0(self):
        # argv[1] is absent when a settings file wires the hook with no verb.
        p = subprocess.run([sys.executable, str(self.box / HOOK_REL)],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=20)
        self.assertEqual(p.returncode, 0)


class TestGarbageNeverBreaksTheSession(_Sandboxed):
    """`main()` is wrapped and the exit code is always 0 -- a hook that can
    kill a session costs far more than the banner is worth."""

    def test_a_non_object_payload_exits_0_and_writes_nothing_specific(self):
        for raw in (b"null", b"[1,2,3]", b'"hi"', b"5", b"not json at all"):
            with self.subTest(payload=raw):
                self.banner.unlink(missing_ok=True)
                r, w = os.pipe()
                os.write(w, raw)
                os.close(w)
                p = subprocess.Popen(
                    [sys.executable, str(self.box / HOOK_REL), "notify"],
                    stdin=r, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p.communicate(timeout=20)
                os.close(r)
                self.assertEqual(p.returncode, 0)

    def test_a_transcript_of_pure_garbage_exits_0(self):
        path = self.box / "junk.jsonl"
        path.write_text("{{{not json\n\n[]\nnull\n")
        self.assertEqual(
            self.run_hook("stop", {"transcript_path": str(path)}), 0)


class TestTheParsing(unittest.TestCase):
    """The pure functions, driven from a sandboxed copy so that importing the
    module can never point `QUESTION_FILE` at the live banner."""

    @classmethod
    def setUpClass(cls):
        cls.box = _sandbox()
        cls.m = _load_module(cls.box)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.box, ignore_errors=True)

    def test_a_reply_ending_in_a_statement_has_no_question(self):
        self.assertIsNone(self.m.trailing_question("All done. Pushed."))

    def test_it_takes_AT_MOST_the_last_two_question_sentences(self):
        got = self.m.trailing_question(
            "First? Second? Third? Fourth?")
        self.assertEqual(got, "Third? Fourth?")

    def test_it_stops_at_the_first_non_question_walking_backwards(self):
        got = self.m.trailing_question("Is it green? I pushed it. Shall I tag?")
        self.assertEqual(got, "Shall I tag?")

    def test_a_trailing_closer_after_the_mark_still_counts(self):
        # "(Shall I push it?)" ends in ')', not '?'.
        self.assertEqual(self.m.trailing_question("(Shall I push it?)"),
                         "(Shall I push it?)")

    def test_a_fenced_code_block_is_stripped_before_the_question_is_found(self):
        # ASSERTION CORRECTED WHILE WRITING IT, AND SAID OUT LOUD because
        # changing a test to agree with the code is the move that must never
        # happen unwatched. My first version asserted the result was exactly
        # "Shall I ship it?" and it came back "Here it is: Shall I ship it?".
        # THE CODE IS RIGHT AND I WAS WRONG: `_SENTENCE_END` splits on . ! ? …
        # and "Here it is:" ends in a colon, so it is genuinely the same
        # sentence. The property this test is named for -- the fence never
        # reaches the banner -- is what is asserted now, instead of a
        # transcription of one particular output.
        got = self.m.trailing_question(
            "Here it is:\n```\nnot a question?\n```\nShall I ship it?")
        self.assertNotIn("not a question", got)
        self.assertTrue(got.endswith("Shall I ship it?"), got)

    def test_a_fence_is_stripped_across_a_real_sentence_boundary_too(self):
        # The same property where the sentence split is unambiguous, so the
        # test above cannot be the only evidence for it.
        got = self.m.trailing_question(
            "Here it is.\n```\nnot a question?\n```\nShall I ship it?")
        self.assertEqual(got, "Shall I ship it?")

    def test_a_very_long_question_is_truncated_with_an_ellipsis(self):
        got = self.m.trailing_question("Shall I " + "x" * 400 + "?")
        self.assertEqual(len(got), 298)
        self.assertTrue(got.endswith("…"))

    def test_the_last_assistant_message_wins(self):
        box = Path(self.box)
        p = box / "t.jsonl"
        p.write_text("\n".join(json.dumps(
            {"type": "assistant",
             "message": {"content": [{"type": "text", "text": t}]}})
            for t in ("first", "second", "third")) + "\n")
        self.assertEqual(self.m.last_assistant_text(str(p)), "third")

    def test_SUBAGENT_sidechain_chatter_is_skipped(self):
        # A subagent's last word must never become Serge's banner -- the
        # verdict is relayed by the session, not shouted by the agent.
        box = Path(self.box)
        p = box / "s.jsonl"
        p.write_text("\n".join([
            json.dumps({"type": "assistant",
                        "message": {"content": [{"type": "text",
                                                 "text": "the real reply"}]}}),
            json.dumps({"type": "assistant", "isSidechain": True,
                        "message": {"content": [{"type": "text",
                                                 "text": "agent noise?"}]}}),
        ]) + "\n")
        self.assertEqual(self.m.last_assistant_text(str(p)), "the real reply")

    def test_a_user_turn_is_not_mistaken_for_an_assistant_one(self):
        box = Path(self.box)
        p = box / "u.jsonl"
        p.write_text("\n".join([
            json.dumps({"type": "assistant",
                        "message": {"content": [{"type": "text",
                                                 "text": "mine"}]}}),
            json.dumps({"type": "user",
                        "message": {"content": [{"type": "text",
                                                 "text": "yours?"}]}}),
        ]) + "\n")
        self.assertEqual(self.m.last_assistant_text(str(p)), "mine")

    def test_a_string_content_block_is_read_as_well_as_a_list(self):
        box = Path(self.box)
        p = box / "str.jsonl"
        p.write_text(json.dumps(
            {"type": "assistant", "message": {"content": "plain string"}}) + "\n")
        self.assertEqual(self.m.last_assistant_text(str(p)), "plain string")


if __name__ == "__main__":
    unittest.main(verbosity=2)
