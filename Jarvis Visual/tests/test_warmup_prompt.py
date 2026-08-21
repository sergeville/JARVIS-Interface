#!/usr/bin/env python3
"""The warmup prompt has to name every source the boot sequence reads.

WHY THIS FILE EXISTS (2026-08-21, ~16:55, found by Serge from his own
screen). The voice line came up, ran its warmup turn, and reported the vault
empty -- no daily notes, no priorities, nothing to resume. All of that was
true, and all of it was useless: a session forty minutes earlier had worked
out the whole vault-merge plan, and the record of it was sitting in
`Jarvis Visual/transcripts/2026-08-21.md` the entire time. Serge had to
SCREENSHOT HIS OWN PAGE and hand it back to me to recover the thread.

The fault was not the boot rule -- CLAUDE.md step 4 has said "read the tail
of today's transcript" for weeks. The fault was that WARMUP_PROMPT, which is
what a voice session actually obeys on turn one, enumerated four reads and
the transcript was not among them. A rule stated in a file the prompt
overrides is not enforced.

So this test guards the PROMPT, not the doctrine: every read the boot
sequence depends on must be named in the string that gets sent. Adding a
source to CLAUDE.md and forgetting the prompt is the exact mistake that cost
the thread, and it is silent -- the session comes up cheerful and blind.
"""

import os
import sys
import unittest

ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "voice-line"))


def warmup_text():
    """The literal WARMUP_PROMPT string, read from the source.

    Read as TEXT rather than imported: brain.py pulls in the voice stack's
    dependencies, and this assertion is about a string constant. A test that
    needs a venv to check a literal is a test that gets skipped.
    """
    path = os.path.join(ROOT, "voice-line", "brain.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("WARMUP_PROMPT = (")
    end = src.index("\n)", start)
    return src[start:end]


class WarmupPromptNamesEverySource(unittest.TestCase):

    def test_prompt_exists_and_is_one_literal(self):
        text = warmup_text()
        self.assertIn("startup sequence", text)
        self.assertNotIn("don't use tools", text.lower())

    def test_names_the_voice_transcript(self):
        """THE REGRESSION. Without the fix this line is absent and the
        session boots with no memory of the conversation it is resuming."""
        text = warmup_text().lower()
        self.assertIn("transcript", text,
                      "WARMUP_PROMPT never tells the session to read the "
                      "voice transcript -- it will boot blind to whatever "
                      "was said before the restart, which is precisely the "
                      "2026-08-21 failure this test exists for.")
        self.assertIn("jarvis visual/transcripts", text,
                      "the prompt mentions a transcript but does not say "
                      "WHERE it is; a session that has to go looking is a "
                      "session that reads the vault instead and reports it "
                      "empty.")

    def test_transcript_read_is_a_tail_not_a_full_read(self):
        """A day of raw conversation does not fit a context window. The boot
        rule says tail for that reason, and a prompt that says 'read the
        transcript' unqualified invites the whole file."""
        text = warmup_text().lower()
        self.assertTrue("last 40 lines" in text or "tail" in text,
                        "the transcript read must be bounded to the tail")

    def test_falls_back_to_yesterday(self):
        """At 00:05 today's transcript does not exist yet. Without the
        fallback the session silently reads nothing and, again, reports the
        vault empty.

        SCOPED TO THE TRANSCRIPT CLAUSE ON PURPOSE. A bare `assertIn
        ("yesterday", text)` passes on the UNFIXED prompt, because the
        daily-note line already says "today's daily note and yesterday's".
        Caught by injecting the revert and watching this test stay green
        while the two beside it went red -- a test whose name claims a
        property it does not check is worse than no test, because it is
        counted in the green."""
        text = warmup_text().lower()
        i = text.index("transcript")
        window = text[max(0, i - 200):i + 200]
        self.assertIn("yesterday", window,
                      "the transcript read has no yesterday-fallback near "
                      "it; the only 'yesterday' in the prompt belongs to "
                      "the daily-note line")

    def test_still_names_the_other_four_sources(self):
        """Adding the transcript must not have displaced anything. Each of
        these was in the prompt before the fix and answers a question the
        others cannot."""
        text = warmup_text()
        for needle in ("VAULT-INDEX.md", "daily note", "Active Priorities.md",
                       ".stack-events.jsonl", "Session Board.md"):
            self.assertIn(needle, text,
                          f"WARMUP_PROMPT no longer names {needle}")


class TranscriptFolderIsWhereThePromptSaysItIs(unittest.TestCase):

    def test_the_named_path_is_real(self):
        """A prompt that names a path that does not exist sends the session
        hunting. This is the cheap check that the string and the disk agree."""
        self.assertTrue(
            os.path.isdir(os.path.join(ROOT, "Jarvis Visual", "transcripts")),
            "WARMUP_PROMPT points at Jarvis Visual/transcripts, which is "
            "not a directory")


if __name__ == "__main__":
    unittest.main()
