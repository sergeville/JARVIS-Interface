#!/usr/bin/env python3
"""A denial stops the work, says so, and can be undone.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_denial.py

WHY THIS EXISTS, and it was found the only way it could be. Serge pressed
DENY on 2026-08-07 ~9:10 PM purely to see what would happen, and the answer
was NOTHING: the tool call came back with one sentence, the turn carried on,
the page stayed calm, the board and the vault recorded not a word, and the
work he had just stopped had no owner. His words: "so what happened to the...
whatever you were doing, maybe we were doing something that is important and
we stopped. So, something has to happen. Somebody has to do something about
it."

And then the shape, also his: "I want the task that I did a denial for [to
glow] in red... maybe I have a button to wake you up and continue what you
were doing. So I pop up again, say, deny or approve again. If I say yes, then
I revert the denied to approve."

THE ONE THING THAT CANNOT BE BUILT AS ASKED, stated at the boundary rather
than glossed: a deny has already been handed to the brain and cannot be
un-answered. So "revert" is a ONE-USE PASS keyed to the exact tool and the
exact arguments he looked at. That is the entire safety property of this
change, and most of the tests below exist to hold it:

    * the pass matches by FINGERPRINT, never by tool name (which would be a
      standing yes for every future Bash) and never by approval id (which
      recycles across restarts and would match a different question);
    * it is CONSUMED on use, in the same call that checks it, so it cannot be
      spent twice;
    * a mismatch BURNS it, because his "continue" answered the request in
      front of him -- a different request is a new question;
    * and nothing free-text from the page is ever compared against it.
"""

import asyncio
import importlib.util
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
    """A VoiceWeb built without touching the real Brain."""
    vw = object.__new__(srv.VoiceWeb)
    vw.approvals = {}
    vw._approval_seq = 0
    vw.denied = None
    vw.reinstated = None
    return vw


# ---------------------------------------------------------------------------
# THE FINGERPRINT -- what "the same request" means
# ---------------------------------------------------------------------------

class TestTheFingerprint(unittest.TestCase):
    def setUp(self):
        self.fp = srv.VoiceWeb.request_fingerprint

    def test_the_same_request_fingerprints_the_same(self):
        self.assertEqual(self.fp("Bash", {"command": "ls -la"}),
                         self.fp("Bash", {"command": "ls -la"}))

    def test_key_order_does_not_change_it(self):
        # The SDK rebuilds these dicts; an order-sensitive key would make the
        # pass fail at random, which reads to Serge as the button not working.
        self.assertEqual(
            self.fp("Bash", {"command": "ls", "description": "list"}),
            self.fp("Bash", {"description": "list", "command": "ls"}))

    def test_a_different_argument_is_a_different_request(self):
        self.assertNotEqual(self.fp("Bash", {"command": "ls"}),
                            self.fp("Bash", {"command": "rm -rf /"}))

    def test_a_different_tool_is_a_different_request(self):
        self.assertNotEqual(self.fp("Bash", {"command": "ls"}),
                            self.fp("Write", {"command": "ls"}))

    def test_an_unserialisable_input_still_fingerprints_rather_than_raising(self):
        # A crash inside the permission callback is a hung turn. Falling back
        # to repr is worse identity than json and infinitely better than
        # dying -- and it still differs between different objects.
        class Weird:
            def __repr__(self): return "<weird A>"

        class Weirder:
            def __repr__(self): return "<weird B>"
        a = self.fp("Bash", {"x": Weird()})
        b = self.fp("Bash", {"x": Weirder()})
        self.assertIsInstance(a, str)
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------------------
# THE ONE-USE PASS
# ---------------------------------------------------------------------------

class TestTheReinstatementIsSpentExactlyOnce(unittest.TestCase):
    def setUp(self):
        self.vw = make_vw()
        self.fp = srv.VoiceWeb.request_fingerprint("Bash", {"command": "ls"})

    def test_no_pass_means_no(self):
        self.assertFalse(self.vw.take_reinstatement(self.fp))

    def test_a_matching_pass_is_taken(self):
        self.vw.reinstated = {"fingerprint": self.fp}
        self.assertTrue(self.vw.take_reinstatement(self.fp))

    def test_it_cannot_be_spent_twice(self):
        # THE safety property. A pass that survives its use is a standing
        # approval Serge never gave.
        self.vw.reinstated = {"fingerprint": self.fp}
        self.assertTrue(self.vw.take_reinstatement(self.fp))
        self.assertFalse(self.vw.take_reinstatement(self.fp))
        self.assertIsNone(self.vw.reinstated)

    def test_a_different_request_does_not_match_and_burns_it(self):
        other = srv.VoiceWeb.request_fingerprint("Bash", {"command": "rm -rf /"})
        self.vw.reinstated = {"fingerprint": self.fp}
        self.assertFalse(self.vw.take_reinstatement(other))
        self.assertIsNone(self.vw.reinstated,
                          "a near-miss left the pass lying around -- the next "
                          "request could pick it up")
        # And the original can no longer use it either: it was his answer to
        # one question, and a different question was asked.
        self.assertFalse(self.vw.take_reinstatement(self.fp))

    def test_a_pass_with_no_fingerprint_grants_nothing(self):
        for junk in ({}, {"fingerprint": None}, {"fingerprint": ""},
                     {"tool": "Bash"}):
            self.vw.reinstated = junk
            self.assertFalse(self.vw.take_reinstatement(self.fp))


# ---------------------------------------------------------------------------
# ask_permission: the deny path and the reinstated path
# ---------------------------------------------------------------------------

class FakeFuture:
    pass


# One stand-in browser. Registered in WS_CLIENTS for the length of a helper
# call, so the broadcast loops have somebody to broadcast to.
FAKE_CLIENT = object()


def run_ask(vw, tool="Bash", tool_input=None, answer=False):
    """Drive the real ask_permission() with the popup answered for us."""
    tool_input = {"command": "ls -la"} if tool_input is None else tool_input
    sent = []

    async def fake_send(ws, msg):
        sent.append(msg)

    vw.safe_send = fake_send
    srv.WS_CLIENTS.add(FAKE_CLIENT)   # see the note in post_denial()

    async def go():
        async def answer_soon():
            # Let ask_permission register the request, then answer it.
            for _ in range(100):
                await asyncio.sleep(0)
                if vw.approvals:
                    break
            for a in list(vw.approvals.values()):
                if not a["future"].done():
                    a["future"].set_result(answer)
        task = asyncio.ensure_future(answer_soon())
        try:
            return await vw.ask_permission(tool, tool_input, None)
        finally:
            await task
    try:
        return asyncio.run(go()), sent
    finally:
        srv.WS_CLIENTS.discard(FAKE_CLIENT)


class TestTheDenyPath(unittest.TestCase):
    def setUp(self):
        self.vw = make_vw()

    def test_a_deny_records_the_refusal_for_the_page_to_draw(self):
        # Before this change a deny left NO trace anywhere. This is the trace.
        res, _ = run_ask(self.vw, answer=False)
        self.assertIsInstance(res, srv.PermissionResultDeny)
        self.assertIsNotNone(self.vw.denied)
        self.assertEqual(self.vw.denied["tool"], "Bash")
        self.assertEqual(
            self.vw.denied["fingerprint"],
            srv.VoiceWeb.request_fingerprint("Bash", {"command": "ls -la"}))

    def test_a_deny_pushes_the_red_card_to_the_page(self):
        _, sent = run_ask(self.vw, answer=False)
        kinds = [m.get("type") for m in sent]
        self.assertIn("denial", kinds,
                      "he denied and the page was never told -- which is the "
                      "entire defect this change exists for")

    def test_the_message_back_to_jarvis_orders_him_to_stop(self):
        # The old message ("do not retry without asking him") left him free to
        # quietly start something else, and that is what he did.
        res, _ = run_ask(self.vw, answer=False)
        msg = res.message.lower()
        self.assertIn("stop here", msg)
        self.assertIn("why", msg)
        for phrase in ("route around", "something else"):
            self.assertIn(phrase, msg)

    def test_an_approval_records_no_refusal(self):
        res, _ = run_ask(self.vw, answer=True)
        self.assertIsInstance(res, srv.PermissionResultAllow)
        self.assertIsNone(self.vw.denied)

    def test_a_reinstated_request_is_allowed_without_asking_him_again(self):
        vw = self.vw
        tool_input = {"command": "ls -la"}
        vw.reinstated = {
            "fingerprint": srv.VoiceWeb.request_fingerprint("Bash", tool_input)}
        sent = []

        async def fake_send(ws, msg):
            sent.append(msg)
        vw.safe_send = fake_send
        res = asyncio.run(vw.ask_permission("Bash", tool_input, None))
        self.assertIsInstance(res, srv.PermissionResultAllow)
        self.assertEqual(vw.approvals, {},
                         "it opened a fresh popup for a request he had "
                         "already said continue to")
        self.assertIsNone(vw.reinstated, "the pass was not spent")

    def test_a_pass_does_not_let_a_DIFFERENT_request_through(self):
        # The attack this shape exists to refuse: a standing yes.
        vw = self.vw
        vw.reinstated = {
            "fingerprint": srv.VoiceWeb.request_fingerprint(
                "Bash", {"command": "ls -la"})}
        res, _ = run_ask(vw, tool_input={"command": "rm -rf /"}, answer=False)
        self.assertIsInstance(res, srv.PermissionResultDeny,
                              "a pass for one command approved another")


# ---------------------------------------------------------------------------
# HIS PRESS MUST LAND -- the route that turns a button into a verdict
# ---------------------------------------------------------------------------

class TestHisAnswerActuallyResolves(unittest.TestCase):
    """Found LIVE 2026-08-07 ~10:00 PM, with Serge stuck behind it. Every
    APPROVE and DENY press crashed resolve_approval (NameError: clean_reason
    -- called, never written), so the future never resolved, the brain never
    heard the verdict, /signals kept serving the pending request, and the page
    redrew the same popup forever. The warmup itself sat behind that popup, so
    every restart ended in "brain did not warm in time".

    Every other test in this file answers the future DIRECTLY, which is why
    the suite was green while the live button was broken: nothing drove the
    one method the button actually calls. These do.
    """

    def _press(self, allow, reason=None):
        vw = make_vw()
        out = {}

        async def go():
            fut = asyncio.get_running_loop().create_future()
            vw.approvals[1] = {"id": 1, "tool": "Bash", "detail": "ls",
                               "future": fut}
            vw.resolve_approval(1, allow, reason)
            out["done"] = fut.done()
            out["verdict"] = fut.result() if fut.done() else None
        asyncio.run(go())
        return vw, out

    def test_an_approve_press_resolves_the_request(self):
        _, out = self._press(True)
        self.assertTrue(out["done"], "his APPROVE never reached the brain")
        self.assertTrue(out["verdict"])

    def test_a_deny_press_resolves_the_request(self):
        _, out = self._press(False)
        self.assertTrue(out["done"], "his DENY never reached the brain")
        self.assertFalse(out["verdict"])

    def test_a_press_with_no_reason_is_todays_page_and_must_land(self):
        # The page sends no reason yet -- None is EVERY live press today.
        vw, out = self._press(True, reason=None)
        self.assertTrue(out["done"])
        self.assertIsNone(vw.approvals[1]["reason"])

    def test_his_reason_rides_with_the_answer(self):
        vw, out = self._press(False, reason="  wrong file \x00 ")
        self.assertTrue(out["done"])
        self.assertEqual(vw.approvals[1]["reason"], "wrong file")


class TestCleanReason(unittest.TestCase):
    """His WHY, made storable: his words trimmed and bounded, or None."""

    def test_no_reason_stays_none(self):
        for junk in (None, 0, True, [], {}, b"bytes"):
            self.assertIsNone(srv.clean_reason(junk), junk)

    def test_whitespace_only_is_no_reason(self):
        self.assertIsNone(srv.clean_reason("   \n\t  "))

    def test_his_words_come_back_trimmed(self):
        self.assertEqual(srv.clean_reason("  wrong file  "), "wrong file")

    def test_control_characters_are_stripped(self):
        self.assertEqual(srv.clean_reason("why\x00\x08 not\x1b"), "why not")

    def test_a_runaway_paste_is_bounded(self):
        self.assertEqual(len(srv.clean_reason("x" * 5000)), 500)


# ---------------------------------------------------------------------------
# THE SECOND POPUP'S ROUTE
# ---------------------------------------------------------------------------

class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def post_denial(vw, body):
    old = getattr(srv, "VW", None)
    srv.VW = vw
    sent = []

    async def fake_send(ws, msg):
        sent.append(msg)
    vw.safe_send = fake_send
    # A PAGE HAS TO BE CONNECTED OR THE BROADCAST IS UNMEASURABLE. Both the
    # deny push and this route loop over WS_CLIENTS, so with the set empty the
    # loop body never runs and `sent` stays empty whether the code sends or
    # not -- a test that cannot tell the two apart. Found 2026-08-07: two
    # tests here failed against correct code for exactly that reason.
    srv.WS_CLIENTS.add(FAKE_CLIENT)
    try:
        resp = asyncio.run(srv.denial_reply(FakeRequest(body)))
    finally:
        srv.WS_CLIENTS.discard(FAKE_CLIENT)
        srv.VW = old
    import json as _json
    return _json.loads(resp.text), sent


class TestTheSecondPopupsAnswer(unittest.TestCase):
    def setUp(self):
        self.vw = make_vw()
        self.fp = srv.VoiceWeb.request_fingerprint("Bash", {"command": "ls"})
        self.vw.denied = {"id": 7, "tool": "Bash", "detail": "ls",
                          "fingerprint": self.fp, "at": 0, "boot_id": "x"}

    def test_continue_mints_a_pass_for_that_exact_request(self):
        out, _ = post_denial(self.vw, {"id": 7, "answer": "continue"})
        self.assertTrue(out["ok"])
        self.assertEqual(self.vw.reinstated["fingerprint"], self.fp)
        self.assertIsNone(self.vw.denied, "the card would stay up forever")

    def test_leave_mints_nothing(self):
        out, _ = post_denial(self.vw, {"id": 7, "answer": "leave"})
        self.assertTrue(out["ok"])
        self.assertIsNone(self.vw.reinstated)
        self.assertIsNone(self.vw.denied)

    def test_either_answer_tells_every_page_the_card_is_settled(self):
        for answer in ("continue", "leave"):
            self.setUp()
            _, sent = post_denial(self.vw, {"id": 7, "answer": answer})
            self.assertEqual([m["type"] for m in sent], ["denial_done"])

    def test_an_answer_for_a_different_refusal_grants_nothing(self):
        # A stale tab answering yesterday's question must not approve today's.
        out, _ = post_denial(self.vw, {"id": 99, "answer": "continue"})
        self.assertFalse(out["ok"])
        self.assertIsNone(self.vw.reinstated)
        self.assertIsNotNone(self.vw.denied, "it cleared the live refusal")

    def test_an_answer_with_no_refusal_open_grants_nothing(self):
        self.vw.denied = None
        out, _ = post_denial(self.vw, {"id": 7, "answer": "continue"})
        self.assertFalse(out["ok"])
        self.assertIsNone(self.vw.reinstated)

    def test_the_vocabulary_is_closed(self):
        # Nothing free-text from the page reaches this server. Anything that
        # is not one of the two words is refused outright.
        for junk in ("approve", "allow", "CONTINUE", "", None, 1, True,
                     {"x": 1}, ["continue"]):
            self.setUp()
            out, _ = post_denial(self.vw, {"id": 7, "answer": junk})
            self.assertFalse(out["ok"], junk)
            self.assertIsNone(self.vw.reinstated, junk)

    def test_a_bool_id_is_a_caller_error_not_an_id(self):
        # Bools are ints in Python; True would otherwise be read as id 1.
        for bad in (True, False, "7", 7.0, None):
            self.setUp()
            out, _ = post_denial(self.vw, {"id": bad, "answer": "continue"})
            self.assertFalse(out["ok"], bad)
            self.assertIsNone(self.vw.reinstated, bad)

    def test_a_body_that_is_not_json_is_refused_rather_than_raising(self):
        out, _ = post_denial(self.vw, ValueError("not json"))
        self.assertFalse(out["ok"])
        self.assertIsNone(self.vw.reinstated)

    def test_the_route_is_actually_registered(self):
        # A handler nobody can reach is the same bug as no handler. Same
        # wiring doctrine as the approve button's own tests.
        self.assertIn('web.post("/denial-reply", denial_reply)', SRC)


class TestTheSignalsKey(unittest.TestCase):
    """The card is DRAWN from HTTP, never only from the socket -- the approve
    button had to learn this the hard way, in an endless loop Serge sat in."""

    def test_signals_serves_the_open_refusal(self):
        self.assertIn('"denial":', SRC)

    def test_the_fingerprint_is_never_served_to_the_page(self):
        # It is an internal key. Serving it invites a future edit to compare
        # it against something the page sent.
        i = SRC.index('"denial":')
        served = SRC[i:i + 400]
        self.assertNotIn("fingerprint", served)


class TestThePage(unittest.TestCase):
    """Wiring tests. The handlers live in a page-level script, so these assert
    the connections exist -- a guard that is built and never wired is the bug
    this project keeps rediscovering."""

    def test_the_card_is_drawn_from_the_poll_not_only_the_socket(self):
        self.assertIn("showDenial(d.denial || null)", PAGE_SRC)

    def test_both_buttons_are_wired_to_the_two_answers(self):
        self.assertIn("answerDenial('continue')", PAGE_SRC)
        self.assertIn("answerDenial('leave')", PAGE_SRC)

    def test_the_detail_is_never_rendered_as_markup(self):
        # `detail` is the tool's own arguments, and it reaches the DOM.
        i = PAGE_SRC.index("function showDenial(")
        body = PAGE_SRC[i:i + 1200]
        self.assertIn("denial-detail').textContent", body)
        # COMMENTS OUT FIRST. The line above this function's write says
        # "textContent, never innerHTML" -- so a raw substring search found
        # the word in the prose explaining why it is absent, and reported a
        # correct page as broken. Seventh time on this project's record that
        # grepping source punished the comment describing the decision; the
        # fix is always to strip the prose, never to soften the assertion.
        code = "\n".join(ln.split("//")[0] for ln in body.splitlines())
        self.assertNotIn("innerHTML", code)

    def test_the_card_has_no_dismiss(self):
        # An answer is the only way out. A refusal that can be waved away is
        # the silence being fixed.
        i = PAGE_SRC.index('<div id="denial-box">')
        card = PAGE_SRC[i:PAGE_SRC.index("</div>", PAGE_SRC.index(
            'id="denial-row"'))]
        self.assertNotIn("dismiss", card.lower())
        self.assertNotIn("&#10005;", card)

    def test_the_answer_failing_is_never_swallowed(self):
        i = PAGE_SRC.index("async function answerDenial(")
        body = PAGE_SRC[i:i + 1400]
        self.assertIn("catch", body)
        self.assertIn("did not reach Jarvis", body,
                      "an empty catch here hides his answer failing -- the "
                      "exact bug the approve button shipped twice")

    def test_the_card_is_red_and_not_the_amber_of_a_pending_question(self):
        # Amber on this page means Jarvis is BLOCKED ON HIM. Red means he
        # already answered and stopped something. Painting a refusal amber
        # would say a question is pending when the opposite is true.
        i = PAGE_SRC.index("#denial-box {")
        rule = PAGE_SRC[i:PAGE_SRC.index("}", i)]
        self.assertIn("--bad-rgb", rule)
        self.assertNotIn("--warn", rule)

    def test_the_bad_colour_and_its_rgb_companion_agree(self):
        # A companion that drifts one digit is a bug nobody can see.
        import re
        hexv = re.search(r"--bad:\s*#([0-9a-fA-F]{6})", PAGE_SRC).group(1)
        rgb = re.search(r"--bad-rgb:\s*([0-9]+),\s*([0-9]+),\s*([0-9]+)",
                        PAGE_SRC).groups()
        self.assertEqual([int(hexv[i:i + 2], 16) for i in (0, 2, 4)],
                         [int(v) for v in rgb])



# ---------------------------------------------------------------------------
# AN EXPIRED REQUEST LEAVES THE SAME CARD A REFUSAL DOES
# ---------------------------------------------------------------------------
#
# Serge, 2026-08-21 ~8:50 AM, after watching a request of his own vanish:
# "I like to leave a card on the page. I like that with a button there...
# because I'm not always on a computer waiting for you."
#
# WHAT WAS BROKEN, and it was guaranteed rather than unlucky. `ask_permission`
# recorded the refusal card AFTER the `if timed_out:` return, so the one path
# that fires precisely BECAUSE nobody was at the desk was the one path that
# left no trace: no card, no fingerprint, nothing to press. The work stopped
# and the only way back to it was him remembering what it had been.
#
# THESE ARE DRIVEN THROUGH THE REAL ask_permission WITH A REAL TIMEOUT --
# never by asserting the source contains the word "expired". A grep would
# have passed against the broken version too, because the word was already
# in the file three lines below the bug.


def run_ask_that_expires(vw, tool="Bash", tool_input=None, budget=0.05):
    """Drive ask_permission() and answer NOTHING, so it really times out."""
    tool_input = {"command": "ls -la"} if tool_input is None else tool_input
    sent = []

    async def fake_send(ws, msg):
        sent.append(msg)

    vw.safe_send = fake_send
    srv.WS_CLIENTS.add(FAKE_CLIENT)
    was = srv.APPROVAL_TIMEOUT_S
    srv.APPROVAL_TIMEOUT_S = budget
    try:
        return asyncio.run(vw.ask_permission(tool, tool_input, None)), sent
    finally:
        srv.APPROVAL_TIMEOUT_S = was
        srv.WS_CLIENTS.discard(FAKE_CLIENT)


class TestAnExpiredRequestSurvives(unittest.TestCase):

    def setUp(self):
        self.vw = srv.VoiceWeb.__new__(srv.VoiceWeb)
        self.vw.approvals = {}
        self.vw._approval_seq = 0
        self.vw.denied = None
        self.vw.reinstated = None

    def test_a_request_nobody_answers_really_does_time_out(self):
        # The premise of every test below. If this stops timing out they all
        # become vacuous, so it is asserted rather than assumed.
        res, _ = run_ask_that_expires(self.vw)
        self.assertIn("timed out", getattr(res, "message", ""))

    def test_IT_LEAVES_A_CARD(self):
        # THE WHOLE POINT. Before this change `denied` stayed None here.
        run_ask_that_expires(self.vw)
        self.assertIsNotNone(self.vw.denied)
        self.assertEqual(self.vw.denied["tool"], "Bash")

    def test_the_card_says_it_EXPIRED_rather_than_that_he_stopped_it(self):
        # "You stopped this" is a false statement about a request he was
        # never shown, and a card that misdescribes what happened is worse
        # than no card at all.
        run_ask_that_expires(self.vw)
        self.assertTrue(self.vw.denied["expired"])

    def test_an_ACTUAL_refusal_is_still_marked_as_his_decision(self):
        # The other half of the same property: the flag must DISCRIMINATE.
        # Without this, setting expired=True unconditionally would pass the
        # test above and silently relabel every real deny of his.
        run_ask(self.vw, answer=False)
        self.assertFalse(bool(self.vw.denied.get("expired")))

    def test_the_card_carries_the_fingerprint_so_the_BUTTON_ACTUALLY_WORKS(self):
        # The button mints a one-use pass keyed to this exact request. A card
        # carrying no fingerprint, or the wrong one, is a button that lights
        # up and does nothing -- which is indistinguishable, from his chair,
        # from the bug this change fixes.
        tool_input = {"command": "echo hello", "description": "say hello"}
        run_ask_that_expires(self.vw, tool_input=tool_input)
        want = srv.VoiceWeb.request_fingerprint("Bash", tool_input)
        self.assertEqual(self.vw.denied["fingerprint"], want)

    def test_END_TO_END_the_button_lets_the_SAME_request_through_next_time(self):
        # Expire it, press RUN IT NOW, and ask the identical thing again --
        # it must be allowed WITHOUT a second popup.
        tool_input = {"command": "echo hello", "description": "say hello"}
        run_ask_that_expires(self.vw, tool_input=tool_input)
        aid = self.vw.denied["id"]
        srv.VW = self.vw
        self.vw.safe_send = lambda ws, msg: asyncio.sleep(0)
        resp = asyncio.run(srv.denial_reply(FakeRequest({"id": aid, "answer": "continue"})))
        self.assertIn(b'"ok": true', bytes(resp.body))
        res, sent = run_ask(self.vw, tool_input=tool_input, answer=False)
        self.assertEqual(type(res).__name__, "PermissionResultAllow")
        self.assertEqual(self.vw.approvals, {})

    def test_a_DIFFERENT_request_is_still_asked_about(self):
        # The pass is not a standing yes. Same safety property the deny path
        # has, restated here because this is a new way to mint one.
        run_ask_that_expires(self.vw, tool_input={"command": "echo hello"})
        aid = self.vw.denied["id"]
        srv.VW = self.vw
        self.vw.safe_send = lambda ws, msg: asyncio.sleep(0)
        asyncio.run(srv.denial_reply(FakeRequest({"id": aid, "answer": "continue"})))
        res, _ = run_ask(self.vw, tool_input={"command": "rm -rf /"}, answer=False)
        self.assertEqual(type(res).__name__, "PermissionResultDeny")

    def test_the_page_is_TOLD_about_the_card_over_the_socket_too(self):
        _, sent = run_ask_that_expires(self.vw)
        pushes = [m for m in sent if m.get("type") == "denial"]
        self.assertEqual(len(pushes), 1)
        self.assertTrue(pushes[0]["expired"])

    def test_the_model_is_told_the_button_exists(self):
        # Otherwise I tell Serge the work is lost, while a card offering it
        # back sits on his screen.
        res, _ = run_ask_that_expires(self.vw)
        self.assertIn("RUN IT NOW", res.message)

    def test_the_expiry_is_written_to_the_OPERATOR_LOG(self):
        # NOT decoration, and my own injection round caught this one missing.
        # `visual-server.log` is the forensic record: on 2026-08-21 the only
        # way to answer Serge's "is everything working?" was to read
        # "approval #15: timed out" out of it and count it against the
        # twenty-one that were answered. A silent expiry is an event with no
        # witness, in the exact channel used to prove there was no fault.
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_ask_that_expires(self.vw)
        out = buf.getvalue()
        self.assertIn("expired", out)
        self.assertIn(str(self.vw.denied["id"]), out)

    def test_signals_serves_the_expired_flag_and_it_is_a_real_bool(self):
        run_ask_that_expires(self.vw)
        srv.VW = self.vw
        i = SRC.index('"denial": ({')
        served = SRC[i:i + 400]
        self.assertIn("expired", served)
        # Served as a bool, not as the raw dict value: `.get` on the deny
        # path returns None, and a null in JSON is not what the page tests.
        self.assertIn('bool(VW.denied.get("expired"))', served)
        self.assertNotIn("fingerprint", served)



if __name__ == "__main__":
    unittest.main(verbosity=2)
