#!/usr/bin/env python3
"""THE VERDICT WHEN THE WARM WAIT RUNS OUT.

Serge's own start, 2026-08-09 1:52 PM: the server was up 8 seconds in, the
brain warmed at 14:00:39, and in between -- at 2m12s, exactly the script's
60x2s budget -- `jarvis.sh start` announced "brain did not warm in time" and
wrote a `down` event.  The start had not failed.  He was told it had, and a
FALSE FAILURE went into the append-only event log, which is the one record
every session reads at boot and which nothing can retract.

So the property under test is not "the timeout is long enough" -- no timeout
is, and raising it only moves the wrong answer later.  It is:

    WHEN THE WAIT RUNS OUT, THE SCRIPT ASKS THE MACHINE, AND ONLY A DEAD
    SERVER EARNS THE WORD "FAILED" OR AN EVENT IN THE LOG.

The real block is CUT OUT OF jarvis.sh and executed with stubbed page_code,
find_others and log_event.  Nothing here paraphrases the script: if the block
is edited, this test runs the edit.
"""

import re
import subprocess
import unittest
from pathlib import Path

SH = Path(__file__).resolve().parent.parent / "jarvis.sh"
SRC = SH.read_text()

# The decision block: from the comment that names the lesson to the end of
# do_start.  Anchored on both ends so a rename fails loudly rather than
# silently testing half of it.
START = "  # THE WAIT RUNNING OUT IS NOT A FAILURE"
END = "  return 1\n}"


def block() -> str:
    i = SRC.find(START)
    assert i != -1, "the warm-verdict block is gone from jarvis.sh"
    j = SRC.find(END, i)
    assert j != -1, "the warm-verdict block never ends"
    return SRC[i:j + len(END) - 1]      # drop do_start's closing brace


def run(page: str, brain: str):
    """Run the real block with the machine's answers stubbed.

    Returns (exit_code, stdout+stderr, events_written).
    """
    harness = f"""
set -u
LOG=/dev/null
EVENTS_WRITTEN=""
page_code() {{ echo "{page}"; }}
find_others() {{ echo "{brain}"; }}
log_event() {{ echo "EVENT|$1|$2|$3" >>"$EVFILE"; }}
P_BRAIN="claude_agent_sdk/_bundled/claude"
verdict() {{
{block()}
}}
verdict
"""
    import tempfile, os
    with tempfile.NamedTemporaryFile("w+", suffix=".ev", delete=False) as ev:
        evpath = ev.name
    try:
        p = subprocess.run(
            ["bash", "-c", harness],
            capture_output=True, text=True,
            env={**os.environ, "EVFILE": evpath},
        )
        events = Path(evpath).read_text()
    finally:
        os.unlink(evpath)
    return p.returncode, p.stdout + p.stderr, events


class TheVerdictAsksTheMachine(unittest.TestCase):

    def test_a_live_page_and_a_live_brain_is_STILL_WARMING_not_failure(self):
        code, out, events = run("200", "81111")
        self.assertEqual(code, 0, "a healthy stack was reported as a failure")
        self.assertIn("still warming", out.lower())
        self.assertNotIn("did not warm in time", out)
        self.assertNotIn("failed", out.lower())

    def test_and_it_writes_NO_EVENT_AT_ALL(self):
        # The heart of it.  The server logs its own "brain warm" line when it
        # gets there; this script guessing in the meantime is what put a lie
        # into a log that cannot be retracted.
        _, _, events = run("200", "81111")
        self.assertEqual(events, "",
                         "a still-warming stack wrote to the append-only log: " + events)

    def test_a_dead_page_IS_a_failure_and_says_so(self):
        code, out, events = run("000", "")
        self.assertEqual(code, 1)
        self.assertIn("did not warm in time", out)
        self.assertIn("EVENT|down|stack|", events)

    def test_a_page_that_answers_with_the_wrong_code_is_a_failure(self):
        # 500 is a half-dead server, not a warming one.  Only 200 counts.
        code, _, events = run("500", "81111")
        self.assertEqual(code, 1)
        self.assertIn("EVENT|down|stack|", events)

    def test_a_live_page_with_NO_brain_is_a_failure(self):
        # The page can answer while the brain never came up at all -- that is
        # exactly the case the original message was written for, and it must
        # still be caught.
        code, _, events = run("200", "")
        self.assertEqual(code, 1)
        self.assertIn("EVENT|down|stack|", events)

    def test_the_failure_event_carries_the_EVIDENCE_it_judged_on(self):
        # A bare "start failed" sent a future session hunting.  The reading
        # that produced the verdict travels with it.
        _, _, events = run("404", "")
        self.assertIn("page 404", events)
        self.assertIn("brain none", events)

    def test_the_still_warming_message_tells_him_it_needs_nothing(self):
        # He restarted the stack by hand after the false failure.  The point
        # of the message is that he should not have to.
        _, out, _ = run("200", "81111")
        self.assertIn("nothing needs restarting", out.lower())

    def test_the_block_asks_the_machine_rather_than_trusting_the_loop(self):
        b = block()
        self.assertIn("page_code", b, "the verdict no longer asks whether the page answers")
        self.assertIn('find_others "$P_BRAIN"', b,
                      "the verdict no longer asks whether the brain exists")


if __name__ == "__main__":
    unittest.main(verbosity=2)
