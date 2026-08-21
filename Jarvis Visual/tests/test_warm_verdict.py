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

import json
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


def run(page: str, brain: str, signals: str = ""):
    """Run the real block with the machine's answers stubbed.

    `signals` is the body the /signals feed returns -- "" meaning the feed is
    unreachable, which is the ordinary case in a test and must keep the block
    silent rather than guessing. Added 2026-08-21 with the blocked-on-Serge
    branch: the block now ASKS the server whether he is the thing it is
    waiting for, so the stub has to be able to answer.

    Returns (exit_code, stdout+stderr, events_written).
    """
    harness = f"""
set -u
LOG=/dev/null
VL="$VLDIR"
EVENTS_WRITTEN=""
page_code() {{ echo "{page}"; }}
find_others() {{ echo "{brain}"; }}
log_event() {{ echo "EVENT|$1|$2|$3" >>"$EVFILE"; }}
# A stubbed feed, so no test here ever touches the running server.
curl() {{ cat "$SIGFILE"; }}
P_BRAIN="claude_agent_sdk/_bundled/claude"
verdict() {{
{block()}
}}
verdict
"""
    import tempfile, os
    with tempfile.NamedTemporaryFile("w+", suffix=".ev", delete=False) as ev:
        evpath = ev.name
    with tempfile.NamedTemporaryFile("w+", suffix=".sig", delete=False) as sg:
        sg.write(signals)
        sigpath = sg.name
    try:
        p = subprocess.run(
            ["bash", "-c", harness],
            capture_output=True, text=True,
            env={**os.environ, "EVFILE": evpath, "SIGFILE": sigpath,
                 "VLDIR": str(SH.resolve().parent.parent / "voice-line")},
        )
        events = Path(evpath).read_text()
    finally:
        os.unlink(evpath)
        os.unlink(sigpath)
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



class TheStartSaysWhenSergeIsTheBlOCKER(unittest.TestCase):
    """"Nothing is wrong" is FALSE when the thing it is waiting for is him.

    Found on Serge's own post-reboot start, 2026-08-15 08:50. The script
    printed "still warming ... nothing is wrong and nothing needs
    restarting" while `/signals` carried approval #1 UNANSWERED -- and it
    still did eight minutes later. The brain was not slow; it was blocked on
    him, and the server already knew. Nobody was reading it.

    It is the same failure as the expired-approval card built the same
    morning, one layer up: a request waiting on Serge that nothing surfaces
    is a request that dies of silence. It matters MORE here, because after a
    reboot with no restored tab there may be no page open to show him a
    popup at all -- this script is the only thing that speaks.

    THE HONESTY RULE THESE HOLD: the script may only say "nothing is wrong"
    when it has ASKED and been told nothing is pending. An unreachable or
    unreadable feed is not evidence of calm.
    """

    LIVE = ("200", "4242")

    def test_a_PENDING_APPROVAL_is_named_instead_of_nothing_is_wrong(self):
        code, out, ev = run(*self.LIVE, signals=json.dumps(
            {"approval": {"id": 1, "tool": "Bash", "detail": "Get pid and time"}}))
        self.assertEqual(code, 0)
        self.assertIn("waiting on you", out.lower())
        self.assertNotIn("nothing is wrong", out.lower())

    def test_it_says_WHAT_is_waiting_so_he_can_recognise_it(self):
        code, out, ev = run(*self.LIVE, signals=json.dumps(
            {"approval": {"id": 1, "tool": "Bash", "detail": "Get pid and time"}}))
        self.assertIn("Bash", out)
        self.assertIn("Get pid and time", out)

    def test_it_points_him_at_the_page_where_the_card_is(self):
        code, out, ev = run(*self.LIVE, signals=json.dumps(
            {"approval": {"id": 1, "tool": "Bash", "detail": "x"}}))
        self.assertIn("127.0.0.1:8765", out)

    def test_an_EXPIRED_request_is_reported_differently_from_a_refusal(self):
        """They are not the same event and the words must not blur them --
        the same rule the card on the page follows."""
        _c, expired, _e = run(*self.LIVE, signals=json.dumps(
            {"denial": {"id": 9, "tool": "Bash", "detail": "run the suite",
                        "expired": True}}))
        _c, refused, _e = run(*self.LIVE, signals=json.dumps(
            {"denial": {"id": 9, "tool": "Bash", "detail": "run the suite",
                        "expired": False}}))
        self.assertIn("ran out of time", expired.lower())
        self.assertNotIn("ran out of time", refused.lower())
        self.assertIn("refusal", refused.lower())

    def test_a_PENDING_APPROVAL_OUTRANKS_a_stale_refusal(self):
        """A live question beats a settled one. Both present must report the
        one he can act on right now."""
        code, out, ev = run(*self.LIVE, signals=json.dumps({
            "approval": {"id": 2, "tool": "Edit", "detail": "the live file"},
            "denial": {"id": 1, "tool": "Bash", "detail": "old thing",
                       "expired": True}}))
        self.assertIn("waiting on you", out.lower())
        self.assertNotIn("ran out of time", out.lower())

    def test_NOTHING_PENDING_still_says_nothing_is_wrong(self):
        """The other half, and without it the branch could simply always
        shout -- which would be the same lie pointed the other way."""
        code, out, ev = run(*self.LIVE, signals=json.dumps({"stack": {}}))
        self.assertEqual(code, 0)
        self.assertIn("nothing needs restarting", out.lower())
        self.assertNotIn("waiting on you", out.lower())

    def test_AN_UNREADABLE_FEED_NEVER_INVENTS_A_BLOCKER(self):
        """A server that cannot be reached or parsed tells us nothing. It
        must fall through to the ordinary message rather than manufacture a
        request Serge never made."""
        for body in ("", "not json", "null", "[]", '{"approval": null}'):
            code, out, ev = run(*self.LIVE, signals=body)
            self.assertEqual(code, 0, body)
            self.assertIn("nothing needs restarting", out.lower(), body)

    def test_IT_WRITES_NO_EVENT_because_the_server_owns_that_record(self):
        """The script is relaying, not judging. An event here would be this
        script guessing about a state it does not own -- the exact fault the
        class above exists for."""
        code, out, ev = run(*self.LIVE, signals=json.dumps(
            {"approval": {"id": 1, "tool": "Bash", "detail": "x"}}))
        self.assertEqual(ev.strip(), "")

    def test_a_DEAD_page_is_still_a_failure_even_with_a_pending_approval(self):
        """The blocked-on-Serge branch sits INSIDE the healthy-stack case.
        A dead server must not be excused by a stale pending request."""
        code, out, ev = run("000", "", signals=json.dumps(
            {"approval": {"id": 1, "tool": "Bash", "detail": "x"}}))
        self.assertEqual(code, 1)
        self.assertIn("did not warm in time", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
