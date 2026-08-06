#!/usr/bin/env python3
"""Tests for POST /approval-reply -- the permission answer that rides HTTP.

Serge, 2026-08-06 ~6:20 PM: "stuck in an endless loop... I click on approve,
always come back."

THE BUG, and why the route exists rather than a retry queue. The permission
popup is DRAWN from /signals -- plain polling, which survives a server restart
because every poll is a fresh request. The ANSWER went over the websocket,
which does not survive one: it closes, and the page only reconnects two
seconds later. The fresh brain asks for its first permission about ONE second
after coming up. So the first approval of every restart was sent into a dead
socket; `catch(e){}` ate the failure; the box hid as though answered; the next
poll saw it still pending and drew it again.

The evidence, from the machine: `approval #1 requested` at 18:19:45 with no
answer line ever, while the request sat in /signals -- and it only cleared
when Serge restarted the whole stack at 18:21:58.

So the answer now rides the same channel as the question. These tests hold the
properties that make that safe, not merely that a route exists.
"""

import ast
import asyncio
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.dirname(os.path.dirname(HERE)))
SERVER = os.path.join(ROOT, "Jarvis Visual", "voice-web-server.py")


def source():
    with open(SERVER, encoding="utf-8") as f:
        return f.read()


def tree():
    return ast.parse(source())


def func_def(name):
    for node in ast.walk(tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name}() is missing from voice-web-server.py")


class FakeRequest:
    """Just enough aiohttp Request for the handler: a JSON body, or a broken one."""

    def __init__(self, body, raises=False):
        self._body, self._raises = body, raises

    async def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._body


class FakeFuture:
    def __init__(self, done=False):
        self._done, self.result_value = done, None

    def done(self):
        return self._done

    def set_result(self, v):
        self._done, self.result_value = True, v


class TestTheRouteIsWiredAndAdvertised(unittest.TestCase):
    """A route the page cannot discover is a route the page will not use."""

    def test_the_route_is_registered_as_a_post(self):
        posts = []
        for node in ast.walk(tree()):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "post"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                posts.append(node.args[0].value)
        self.assertIn("/approval-reply", posts,
                      "the handler exists but nothing routes to it")

    def test_signals_advertises_the_capability(self):
        # Version skew, both directions: a NEW page against an OLD server must
        # keep using the websocket rather than POST into a 404 -- which would
        # look exactly like the endless loop this fixes.
        self.assertIn('"approval_http": True', source())

    def test_signals_carries_a_generation_marker(self):
        """The centrepiece of the id-reuse fix, and it had NO server-side test.

        Proven by injection: deleting the boot_id line left all 44 tests green
        while the page's mismatch drop went permanently dead -- the guard
        against answering a question Serge never read simply stopped existing,
        silently. Same fault class the approval_http flag was already guarded
        for; the newer flag was not.
        """
        self.assertIn('"boot_id": BOOT_ID', source())

    def test_the_generation_marker_is_stable_and_process_specific(self):
        import importlib.util as iu, re
        # Stable within the process: read it twice from the loaded module.
        spec = iu.spec_from_file_location("vws_boot", SERVER)
        m = iu.module_from_spec(spec)
        sys.modules["vws_boot"] = m
        spec.loader.exec_module(m)
        self.assertEqual(m.BOOT_ID, m.BOOT_ID)
        self.assertTrue(m.BOOT_ID, "an empty marker disables the drop")
        # Shaped pid-epoch, so two processes cannot collide except on a pid
        # reused inside one second.
        self.assertRegex(m.BOOT_ID, r"\A\d+-\d+\Z")
        self.assertTrue(m.BOOT_ID.startswith(f"{os.getpid()}-"))

    def test_the_marker_is_evaluated_once_at_module_scope(self):
        # If it were computed per request it would differ between polls and
        # drop every queued answer -- fail-closed turned into fail-always.
        t = tree()
        assigns = [n for n in ast.walk(t)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(x, ast.Name) and x.id == "BOOT_ID"
                           for x in n.targets)]
        self.assertEqual(len(assigns), 1, "BOOT_ID must be assigned once")
        module_level = [n for n in t.body
                        if isinstance(n, ast.Assign)
                        and any(isinstance(x, ast.Name) and x.id == "BOOT_ID"
                                for x in n.targets)]
        self.assertEqual(len(module_level), 1,
                         "BOOT_ID must live at module scope, not per request")

    def test_the_handler_never_raises_at_the_caller(self):
        # A permission button that fails with a 500 is a button that fails
        # silently from where Serge is sitting.
        fn = func_def("approval_reply")
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        self.assertTrue(returns)
        for r in returns:
            self.assertTrue(
                isinstance(r.value, ast.Call)
                and isinstance(r.value.func, ast.Attribute)
                and r.value.func.attr == "json_response",
                "every exit must be a json_response, never a raise")


class TestTheHandlerAnswersOrRefusesOutLoud(unittest.TestCase):

    def setUp(self):
        spec = importlib.util.spec_from_file_location("vws", SERVER)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["vws"] = self.mod
        spec.loader.exec_module(self.mod)
        self.vw = self.mod.VW
        self.vw.approvals = {}

    def call(self, body, raises=False):
        r = asyncio.run(self.mod.approval_reply(FakeRequest(body, raises)))
        import json as _json
        return r.status, _json.loads(r.body.decode())

    def test_a_real_approval_is_allowed(self):
        fut = FakeFuture()
        self.vw.approvals[7] = {"future": fut}
        status, d = self.call({"id": 7, "allow": True})
        self.assertEqual(status, 200)
        self.assertTrue(d["ok"])
        self.assertIs(fut.result_value, True)

    def test_a_real_approval_is_denied(self):
        fut = FakeFuture()
        self.vw.approvals[8] = {"future": fut}
        _, d = self.call({"id": 8, "allow": False})
        self.assertTrue(d["ok"])
        self.assertIs(fut.result_value, False)

    def test_a_missing_allow_is_a_denial_not_a_crash(self):
        fut = FakeFuture()
        self.vw.approvals[9] = {"future": fut}
        _, d = self.call({"id": 9})
        self.assertTrue(d["ok"])
        self.assertIs(fut.result_value, False)

    def test_an_unknown_id_grants_nothing_and_says_so(self):
        # THE PROPERTY THAT MATTERS MOST. A stale tab, or anything else on
        # loopback, must not be able to answer a request by guessing a number
        # -- and must be TOLD it answered nothing, or it will believe it did.
        status, d = self.call({"id": 999999, "allow": True})
        self.assertEqual(status, 200)
        self.assertFalse(d["ok"])
        self.assertEqual(self.vw.approvals, {})

    def test_a_second_answer_cannot_flip_the_first(self):
        fut = FakeFuture()
        self.vw.approvals[4] = {"future": fut}
        self.call({"id": 4, "allow": False})
        self.call({"id": 4, "allow": True})
        self.assertIs(fut.result_value, False, "a deny was flipped to an allow")

    def test_a_non_integer_id_is_refused_without_raising(self):
        for bad in ("7", None, 1.5, [], {}, "'; drop", True, False):
            _, d = self.call({"id": bad, "allow": True})
            self.assertFalse(d["ok"], f"accepted id {bad!r}")

    def test_a_body_that_is_not_json_is_refused_without_raising(self):
        _, d = self.call(None, raises=True)
        self.assertFalse(d["ok"])

    def test_an_empty_body_is_refused_without_raising(self):
        _, d = self.call({})
        self.assertFalse(d["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
