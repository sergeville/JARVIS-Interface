#!/usr/bin/env python3
"""A DENY asks Serge why, and his answer reaches Jarvis.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_why.py

WHY THIS EXISTS, in his own words (2026-08-07 ~9:54 PM, after an evening of
denials that each ended with him being asked the same question by voice):

    "The deny did not work as it should. When I press the deny, there should
    be an inbox asking me why, and either me entering the reason or saying
    the reason with my voice. That's what I'm always waiting for."

And the rule underneath it, from the same conversation: "You have to know
why. If I don't say why, you just wait until I tell you why."

THE DEFECT THIS GUARDS IS NOT A MISSING FEATURE -- IT IS A HALF-WIRED ONE.
`clean_reason()` and `resolve_approval(..., reason)` already existed. What did
not exist was any path that CARRIED a reason: the HTTP route never read the
field, and `ask_permission` popped the request off `self.approvals` without
ever looking at what had been written to it. A reason could be stored and was
guaranteed to be thrown away one line later. So every test here drives the
real call chain end to end; none of them assert that a line of source exists.

That distinction is this project's oldest lesson, in its eighth costume: a
guard that proves a line EXISTS never proves it RUNS.
"""

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "voice-web-server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("voice_web_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["voice_web_server"] = mod
    spec.loader.exec_module(mod)
    return mod


srv = load_server()


def make_vw():
    """A VoiceWeb built without touching the real Brain."""
    vw = object.__new__(srv.VoiceWeb)
    vw.approvals = {}
    vw._approval_seq = 0
    vw.denied = None
    vw.reinstated = None
    return vw


class FakeRequest:
    """The one thing the routes touch: an awaitable .json()."""

    def __init__(self, body, raise_it=False):
        self._body = body
        self._raise = raise_it

    async def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._body


def body_of(response):
    return json.loads(response.body.decode())


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# THE WIRE: his reason has to survive the trip from the button to the request
# ---------------------------------------------------------------------------

class TestTheReasonReachesThePendingRequest(unittest.TestCase):
    """resolve_approval already stored it. Nothing ever PUT it there."""

    def setUp(self):
        self.vw = make_vw()
        srv.VW = self.vw
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        self.fut = loop.create_future()
        self.vw.approvals[1] = {"id": 1, "tool": "Bash",
                                "detail": "ls", "future": self.fut}

    def test_the_route_carries_his_words_onto_the_request(self):
        # THE BUG, stated as a test: approval_reply used to call
        # resolve_approval with two arguments. The reason field on the POST
        # was read by nothing at all, so the box could send it forever and it
        # would land nowhere.
        r = run(srv.approval_reply(FakeRequest(
            {"id": 1, "allow": False, "reason": "wrong file"})))
        self.assertTrue(body_of(r)["ok"])
        self.assertEqual(self.vw.approvals[1]["reason"], "wrong file")

    def test_the_reason_is_cleaned_on_the_way_in(self):
        # Not re-testing clean_reason (test_denial.py owns that) -- testing
        # that this path actually PASSES THROUGH it rather than storing raw.
        run(srv.approval_reply(FakeRequest(
            {"id": 1, "allow": False, "reason": "  spaced  "})))
        self.assertEqual(self.vw.approvals[1]["reason"], "spaced")

    def test_no_reason_field_at_all_still_answers(self):
        # Every page older than tonight sends exactly this. A deny that failed
        # because it carried no explanation would break the one button on this
        # HUD that must always work.
        r = run(srv.approval_reply(FakeRequest({"id": 1, "allow": False})))
        self.assertTrue(body_of(r)["ok"])
        self.assertIsNone(self.vw.approvals[1]["reason"])
        self.assertFalse(self.fut.result())

    def test_a_reason_does_not_change_the_verdict(self):
        # The verdict is the future's result and the reason rides beside it.
        # If ever the two were merged, an explained deny could read as allow.
        run(srv.approval_reply(FakeRequest(
            {"id": 1, "allow": True, "reason": "go ahead"})))
        self.assertTrue(self.fut.result())

    def test_a_reason_on_an_unknown_id_grants_nothing(self):
        r = run(srv.approval_reply(FakeRequest(
            {"id": 99, "allow": True, "reason": "please"})))
        self.assertFalse(body_of(r)["ok"])
        self.assertFalse(self.fut.done())

    def test_a_junk_reason_is_dropped_not_fatal(self):
        # The field is free text from a browser; a number or a dict must not
        # take down the permission answer.
        for junk in (42, {"a": 1}, ["x"], True):
            with self.subTest(junk=junk):
                vw = make_vw()
                srv.VW = vw
                loop = asyncio.new_event_loop()
                self.addCleanup(loop.close)
                fut = loop.create_future()
                vw.approvals[1] = {"id": 1, "tool": "Bash",
                                   "detail": "ls", "future": fut}
                r = run(srv.approval_reply(FakeRequest(
                    {"id": 1, "allow": False, "reason": junk})))
                self.assertTrue(body_of(r)["ok"])
                self.assertIsNone(vw.approvals[1]["reason"])


# ---------------------------------------------------------------------------
# THE HAND-OFF: ask_permission must READ it before discarding the request
# ---------------------------------------------------------------------------

class TestTheDenialMessageCarriesHisReason(unittest.IsolatedAsyncioTestCase):
    """The half that was structurally impossible before this change.

    ask_permission pops the request in its `finally`. Whatever
    resolve_approval wrote is on that popped dict and nowhere else, so
    reading self.approvals afterwards can only ever find nothing.
    """

    async def _deny_with(self, reason):
        vw = make_vw()
        srv.VW = vw
        srv.WS_CLIENTS = set()

        async def answer():
            # Wait until the request is really registered, then answer it the
            # way the button does -- through the route, not by hand.
            for _ in range(200):
                if vw.approvals:
                    break
                await asyncio.sleep(0.001)
            aid = next(iter(vw.approvals))
            body = {"id": aid, "allow": False}
            if reason is not None:
                body["reason"] = reason
            await srv.approval_reply(FakeRequest(body))

        task = asyncio.create_task(answer())
        result = await vw.ask_permission("Bash", {"command": "ls"}, None)
        await task
        return vw, result

    async def test_his_words_are_in_the_message_handed_to_the_brain(self):
        vw, result = await self._deny_with("that file is not yours to touch")
        self.assertIn("that file is not yours to touch", result.message)

    async def test_a_given_reason_forbids_asking_him_again(self):
        # THE WHOLE POINT, and the thing he was angry about tonight: he
        # answers, and is asked the same question back.
        _, result = await self._deny_with("wrong branch")
        self.assertIn("Do NOT ask him why", result.message)

    async def test_no_reason_means_ask_and_then_wait(self):
        # His rule: "If I don't say why, you just wait until I tell you why."
        _, result = await self._deny_with(None)
        self.assertIn("Ask him why", result.message)
        self.assertIn("WAIT", result.message)
        self.assertNotIn("Do NOT ask him why", result.message)

    async def test_the_two_cases_are_genuinely_different_messages(self):
        _, with_why = await self._deny_with("because")
        _, without = await self._deny_with(None)
        self.assertNotEqual(with_why.message, without.message)

    async def test_his_words_are_delimited_rather_than_loose_in_the_prompt(self):
        # His reason is free text arriving from a page field. It is his own
        # voice and it is allowed to steer me -- but it must be legible AS a
        # quotation, not blended into the server's own framing.
        _, result = await self._deny_with("stop and do the tests first")
        self.assertIn("<<<stop and do the tests first>>>", result.message)

    async def test_the_refusal_record_keeps_the_reason(self):
        # The red card and the one-use pass hang off vw.denied. A reason that
        # lived only in the message would be gone the moment I answered him.
        vw, _ = await self._deny_with("not now")
        self.assertEqual(vw.denied["reason"], "not now")

    async def test_a_denial_with_no_reason_records_None_not_the_string(self):
        vw, _ = await self._deny_with(None)
        self.assertIsNone(vw.denied["reason"])

    async def test_the_stop_instruction_survives_in_both_cases(self):
        # The reason is an ADDITION. If explaining a refusal quietly dropped
        # "STOP HERE", an explained deny would be weaker than a silent one.
        for reason in ("because", None):
            with self.subTest(reason=reason):
                _, result = await self._deny_with(reason)
                self.assertIn("STOP HERE", result.message)

    async def test_an_approval_is_unaffected_by_the_new_field(self):
        vw = make_vw()
        srv.VW = vw
        srv.WS_CLIENTS = set()

        async def answer():
            for _ in range(200):
                if vw.approvals:
                    break
                await asyncio.sleep(0.001)
            aid = next(iter(vw.approvals))
            await srv.approval_reply(FakeRequest(
                {"id": aid, "allow": True, "reason": "fine by me"}))

        task = asyncio.create_task(answer())
        result = await vw.ask_permission("Bash", {"command": "ls"}, None)
        await task
        self.assertIsInstance(result, srv.PermissionResultAllow)
        self.assertIsNone(vw.denied)


# ---------------------------------------------------------------------------
# SPEAKING THE REASON -- transcription that is ONLY transcription
# ---------------------------------------------------------------------------

class TestTheSpokenReasonRoute(unittest.IsolatedAsyncioTestCase):
    """It turns his voice into text for the BOX. It must do nothing else.

    While a permission is pending, a second path into the brain is the one
    thing that must not exist -- so this route's safety is that it has none.
    """

    def setUp(self):
        self.vw = make_vw()
        self.heard = []

        async def fake_transcribe(wav):
            self.heard.append(wav)
            return "because the tests are red"

        self.vw.transcribe = fake_transcribe
        srv.VW = self.vw

    @staticmethod
    def _wav(seconds=0.1):
        import base64
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x01" * int(16000 * seconds))
        return base64.b64encode(buf.getvalue()).decode()

    async def test_it_gives_back_what_he_said(self):
        r = await srv.reason_transcribe(FakeRequest({"audio": self._wav()}))
        d = body_of(r)
        self.assertTrue(d["ok"])
        self.assertEqual(d["text"], "because the tests are red")

    async def test_it_never_touches_the_brain_or_an_approval(self):
        # Proven by state, not by reading the function: a pending request must
        # be exactly as pending afterwards, and no denial may appear.
        loop = asyncio.get_running_loop()
        self.vw.approvals[1] = {"id": 1, "tool": "Bash", "detail": "ls",
                                "future": loop.create_future()}
        await srv.reason_transcribe(FakeRequest({"audio": self._wav()}))
        self.assertFalse(self.vw.approvals[1]["future"].done())
        self.assertIsNone(self.vw.denied)
        self.assertIsNone(self.vw.reinstated)

    async def test_no_audio_is_refused_in_words_he_can_read(self):
        for bad in (None, "", 5, {"a": 1}, []):
            with self.subTest(bad=bad):
                r = await srv.reason_transcribe(FakeRequest({"audio": bad}))
                d = body_of(r)
                self.assertFalse(d["ok"])
                self.assertTrue(d["error"])

    async def test_a_body_that_is_not_json_is_refused_not_fatal(self):
        r = await srv.reason_transcribe(FakeRequest(None, raise_it=True))
        self.assertFalse(body_of(r)["ok"])

    async def test_unreadable_base64_is_refused(self):
        r = await srv.reason_transcribe(FakeRequest({"audio": "!!!not b64!!!"}))
        d = body_of(r)
        self.assertFalse(d["ok"])
        self.assertEqual(self.heard, [])      # never reached whisper

    async def test_an_oversized_post_is_refused_before_it_is_decoded(self):
        # The only caller-supplied blob on this server. Cheaper to refuse than
        # to decode, and the decode never happens.
        #
        # ⚠ THE FIRST VERSION OF THIS TEST PASSED WITH THE CAP DELETED, and
        # the injection round is what found it. It padded with "A" to an odd
        # length, so base64 rejected it as malformed and the route said
        # ok:false for a reason that had nothing to do with size -- the test
        # could not tell "too long" from "unreadable". The payload is now
        # VALID base64, so without the cap it would decode and travel on, and
        # the assertion names the refusal it expects rather than any refusal.
        oversize = "A" * (((srv.MAX_REASON_WAV_B // 4) + 1) * 4)
        self.assertGreater(len(oversize), srv.MAX_REASON_WAV_B)
        r = await srv.reason_transcribe(FakeRequest({"audio": oversize}))
        d = body_of(r)
        self.assertFalse(d["ok"])
        self.assertIn("too long", d["error"])
        self.assertEqual(self.heard, [])

    async def test_a_whisper_failure_answers_rather_than_raising(self):
        # If this raised, aiohttp would answer 500 and the page would show him
        # nothing -- and he would be left with a box that appears broken and
        # no hint that he can simply type instead.
        async def boom(wav):
            raise RuntimeError("whisper is down")

        self.vw.transcribe = boom
        r = await srv.reason_transcribe(FakeRequest({"audio": self._wav()}))
        d = body_of(r)
        self.assertFalse(d["ok"])
        self.assertIn("type it", d["error"])

    async def test_the_route_is_actually_registered(self):
        # A route that exists as a function and is never mounted is a 404 to
        # him, which on this page looks exactly like the feature being broken.
        src = SERVER.read_text()
        self.assertIn('web.post("/reason-transcribe", reason_transcribe)', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
