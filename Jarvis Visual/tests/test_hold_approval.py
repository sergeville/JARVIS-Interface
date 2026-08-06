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

    def test_explicit_interrupt_stays_unconditional(self):
        # The interrupt button / barge-in tap is a real order and must
        # still cancel -- and 7b507a4 already makes that cancellation an
        # answered one. Guarding THIS path would make Jarvis unstoppable
        # while a popup is up.
        b = branch("interrupt")
        self.assertIn("await VW.interrupt()", b)
        self.assertNotIn("approval_pending", b,
                         "the explicit interrupt must never be held")

    def test_interrupt_still_answers_pending_approvals(self):
        # The two fixes compose: hold stops the accidental kill; when a
        # REAL interrupt does come, every pending future still gets a
        # definite answer before the turn dies.
        m = re.search(r"async def interrupt\(self\).*?async def", SRC, re.S)
        self.assertIsNotNone(m)
        self.assertIn('a["future"].set_result(False)', m.group(0),
                      "interrupt() no longer answers pending approvals")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
