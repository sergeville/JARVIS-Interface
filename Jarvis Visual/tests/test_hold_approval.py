#!/usr/bin/env python3
"""A pending approval survives Serge's Enter key.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_hold_approval.py

Why these exist (Serge, 2026-08-06 ~9:55 AM): "again i press enter key lose
the approve popup." The 7b507a4 fix made a cancelled approval ANSWERED --
a definite deny, a log line, a sticky notice -- but the Enter key still
cancelled it, because a typed message fires an interrupt before it starts.
This build stops the cancellation at the source: while any approval is
pending, a typed or spoken message must NOT interrupt. The popup stays,
the message queues on turn_lock, and it runs after the turn it interrupted
would have finished. Only an explicit interrupt (the button / barge-in tap)
still cancels -- that one is a real order.

The real module is imported by path, so these can never drift from the code
they guard. The websocket handler body is asserted from source (it lives
inside `main()` and cannot be imported alone) -- same wiring-test doctrine
as test_sessions_card.js: a guard that exists but is not wired is the bug.
"""

import asyncio
import importlib.util
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "voice-web-server.py"
PAGE = HERE.parent / "jarvis.html"


def load_server():
    spec = importlib.util.spec_from_file_location("voice_web_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["voice_web_server"] = mod
    spec.loader.exec_module(mod)
    return mod


srv = load_server()
SRC = SERVER.read_text()
PAGE_SRC = PAGE.read_text()


def make_vw():
    """A VoiceWeb constructed without touching the real Brain."""
    vw = object.__new__(srv.VoiceWeb)
    vw.approvals = {}
    vw._approval_seq = 0
    return vw


class TestApprovalPending(unittest.TestCase):
    def test_no_approvals_means_nothing_pending(self):
        self.assertFalse(make_vw().approval_pending())

    def test_unresolved_future_is_pending(self):
        async def run():
            vw = make_vw()
            fut = asyncio.get_running_loop().create_future()
            vw.approvals[1] = {"id": 1, "future": fut}
            return vw.approval_pending()
        self.assertTrue(asyncio.run(run()))

    def test_resolved_future_is_not_pending(self):
        # The record may linger a tick after resolution; a resolved future
        # must not keep holding Serge's messages.
        async def run():
            vw = make_vw()
            fut = asyncio.get_running_loop().create_future()
            fut.set_result(False)
            vw.approvals[1] = {"id": 1, "future": fut}
            return vw.approval_pending()
        self.assertFalse(asyncio.run(run()))

    def test_one_pending_among_resolved_still_pends(self):
        async def run():
            vw = make_vw()
            done = asyncio.get_running_loop().create_future()
            done.set_result(True)
            live = asyncio.get_running_loop().create_future()
            vw.approvals[1] = {"id": 1, "future": done}
            vw.approvals[2] = {"id": 2, "future": live}
            return vw.approval_pending()
        self.assertTrue(asyncio.run(run()))


def branch(kind):
    """The websocket handler branch for one message kind, from source."""
    m = re.search(r'(?:el)?if kind == "%s":(.*?)(?=\n        elif kind|\Z)' % kind,
                  SRC, re.S)
    if not m:
        raise AssertionError(f'no handler branch for kind "{kind}"')
    return m.group(1)


class TestServerWiring(unittest.TestCase):
    def test_text_guards_interrupt_with_pending(self):
        b = branch("text")
        self.assertIn("approval_pending()", b,
                      "the text path lost the pending guard")
        # The interrupt must be the guarded alternative, not unconditional.
        self.assertRegex(b, r"else:\s*\n\s*await VW\.interrupt\(\)",
                         "text: interrupt is not the else-branch of the guard")

    def test_image_guards_interrupt_with_pending(self):
        b = branch("image")
        self.assertIn("approval_pending()", b,
                      "the image path lost the pending guard")
        self.assertRegex(b, r"else:\s*\n\s*await VW\.interrupt\(\)",
                         "image: interrupt is not the else-branch of the guard")

    def test_held_is_said_not_silent(self):
        # Queueing without saying so would rebuild the original silence
        # one layer down: Serge types, nothing happens, nothing explains.
        for kind in ("text", "image"):
            self.assertIn('"held"', branch(kind),
                          f"{kind}: the held notice is gone")

    def test_explicit_interrupt_is_held_while_pending(self):
        # INVERTED 2026-08-06 on Serge's 10:04 AM rule: "The only way it
        # can be de-active is by me doing an approval or pressing denied
        # or approved. It cannot be cancelled." The old assertion said the
        # button must never be held; his rule says the opposite, and the
        # two cannot both guard this file. The guard lives INSIDE
        # interrupt() so every caller -- button, barge-in, another tab,
        # the terminal -- is covered by one gate.
        m = re.search(r"async def interrupt\(self\).*?\n    (?:@|async def|def )",
                      SRC, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("approval_pending()", body,
                      "interrupt() lost the no-cancel guard")
        # The guard must sit BEFORE the gen bump -- bumping gen marks the
        # approval's own turn stale, which cancels it in quieter clothes.
        self.assertLess(body.index("approval_pending()"),
                        body.index("self.gen += 1"),
                        "the guard must run before gen is bumped")

    def test_interrupt_never_answers_pending_approvals(self):
        # The old build resolved every pending future with a deny before
        # tearing down (7b507a4). Under the no-cancel rule that resolve IS
        # the cancellation, so it must be gone.
        m = re.search(r"async def interrupt\(self\).*?\n    (?:@|async def|def )",
                      SRC, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn('set_result', m.group(0),
                         "interrupt() still resolves pending approvals")

    def test_brink_recheck_before_brain_interrupt(self):
        # Test-adversary finding: a request can register between the top
        # guard and the brain teardown (the held-broadcast awaits yield
        # the loop). interrupt() must re-check on the brink and undo its
        # gen bump, or the late arrival is cancelled unprotected.
        m = re.search(r"async def interrupt\(self\).*?\n    (?:@|async def|def )",
                      SRC, re.S)
        body = m.group(0)
        self.assertEqual(body.count("approval_pending()"), 2,
                         "interrupt() lost the brink re-check")
        self.assertIn("self.gen -= 1", body,
                      "the brink hold must undo the gen bump")
        # rindex on both: the comment explaining the re-check names
        # brain.interrupt() in prose, and grepping source must not
        # punish the prose explaining the decision (standing lesson).
        self.assertLess(body.rindex("approval_pending()"),
                        body.rindex("await self.brain.interrupt()"),
                        "the re-check must sit before the brain teardown")

    def test_timeout_is_his_half_hour(self):
        # Adversary finding: only test_approvals guarded the constant, so
        # a lone run of this suite would miss it reverting. His number,
        # 2026-08-06 ~11:05 AM: "more than half an hour, it just cancels
        # itself."
        self.assertEqual(srv.APPROVAL_TIMEOUT_S, 1800.0)

    def test_bogus_approval_reply_cannot_kill_the_socket_loop(self):
        # Adversary finding: int("abc") raises ValueError inside the ws
        # loop; the except is what keeps a malformed reply from costing
        # the connection. Pin that it stays.
        b = branch("approval_reply")
        self.assertIn("except (TypeError, ValueError)", b,
                      "the approval_reply branch lost its bad-id guard")

    def test_held_interrupt_is_said_to_the_page(self):
        # An ignored button with no feedback is a new silence -- the page
        # must be told the interrupt was held.
        m = re.search(r"async def interrupt\(self\).*?\n    (?:@|async def|def )",
                      SRC, re.S)
        self.assertIn('"held"', m.group(0),
                      "a held interrupt says nothing to the page")


class TestPageWiring(unittest.TestCase):
    def test_every_page_interrupt_send_is_guarded(self):
        # The spoken path interrupts from the PAGE (press-to-talk), before
        # the server sees anything -- so the guard must live page-side too.
        # The guard may sit on the line above the send (the press-to-talk
        # site wraps), so judge the send WITH its immediate context, not
        # the send line alone -- a single-line check read a correctly
        # guarded page as broken on the first run of this very test.
        spans = [m.span() for m in
                 re.finditer(r"\{type: 'interrupt'\}", PAGE_SRC)]
        self.assertGreaterEqual(len(spans), 3, "interrupt sends went missing")
        for start, _ in spans:
            context = PAGE_SRC[max(0, start - 200):start]
            self.assertIn("approvalId === null", context,
                          "unguarded page interrupt send near: "
                          + PAGE_SRC[max(0, start - 80):start + 25].strip())

    def test_page_says_held(self):
        self.assertIn("'held'", PAGE_SRC,
                      "the page no longer handles the held message")

    def test_page_restores_popup_from_signals(self):
        # Adversary finding: under a 30-minute time-to-live, a reload
        # mid-approval depends entirely on the /signals restore -- the
        # popup must come back, and a payload with no approval must
        # clear it rather than leave a stale box.
        self.assertIn("showApproval(d.approval || null)", PAGE_SRC,
                      "the page no longer restores the popup from /signals")


if __name__ == "__main__":
    unittest.main(verbosity=2)
