"""Tests for the permission request lifecycle in voice-web-server.py.

Serge, 2026-08-06: "sometimes you pop up, there's the approve button...
and it disappears on me. Why? Because I'm typing something and I press
enter, whoop, it disappears." Then the part that matters most: "maybe
that's the reason sometimes I think you're doing something, you're not,
you're waiting for me and I don't know you're waiting for me."

He was right, and the first diagnosis given to him was too kind. The
request was not being DENIED when a turn was interrupted -- it was
ceasing to exist. `ask_permission()` awaits inside the turn, so
cancelling the turn cancelled the await, and PermissionResultDeny was
never returned either. No approval, no denial, no completion, no log
line: the work was abandoned in silence.

What these guard, in order of how much they matter:

  * an interrupt ANSWERS every pending request rather than dropping it,
    so there is always a definite result;
  * the answer is never ALLOW. The one thing that must never happen is
    an accidental grant, because that is consent Serge did not give;
  * Jarvis is told WHICH kind of no it was, since "he refused" and "he
    never saw it" call for opposite behaviour from me;
  * every page is told too, with a reason, so the box cannot simply
    vanish and leave him guessing.

The real module is imported by path and driven for real; nothing here
touches a brain, a socket or the vault.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
spec = importlib.util.spec_from_file_location(
    "vws", f"{ROOT}/Jarvis Visual/voice-web-server.py")
vws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vws)

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name}\n    got:  {got!r}\n    want: {want!r}")


def ok(name, cond):
    check(name, bool(cond), True)


class FakeWS:
    """Collects what the page would have been sent."""

    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


def fresh():
    """A VoiceWeb with nothing real behind it.

    __init__ builds a Brain and an httpx client, neither of which is
    needed or wanted here, so the object is made without running it --
    the methods under test only touch `approvals`, `gen` and `turn_lock`.
    """
    vw = vws.VoiceWeb.__new__(vws.VoiceWeb)
    vw.gen = 0
    vw.turn_lock = asyncio.Lock()
    vw.approvals = {}
    vw._approval_seq = 0
    return vw


def run(coro):
    return asyncio.run(coro)


def with_page(fn):
    """Run fn with one fake page connected, and hand back what it saw."""
    async def go():
        ws = FakeWS()
        vws.WS_CLIENTS.add(ws)
        try:
            return await fn(ws)
        finally:
            vws.WS_CLIENTS.discard(ws)
    return run(go())


# ------------------------------------------------- the interrupt case

def test_interrupt():
    async def go(ws):
        vw = fresh()
        task = asyncio.create_task(
            vw.ask_permission("Bash", {"command": "rm -rf /tmp/x"}, None))
        await asyncio.sleep(0)          # let it register and push
        pending = list(vw.approvals.values())
        await vw.interrupt()
        result = await asyncio.wait_for(task, 2)
        return vw, pending, result, ws.sent
    return with_page(go)


vw, pending, result, sent = test_interrupt()

ok("the request was registered before the interrupt", len(pending) == 1)
ok("an interrupt RESOLVES the request instead of dropping it",
   isinstance(result, vws.PermissionResultDeny))
# THE ONE THING THAT MUST NEVER HAPPEN. An interrupt granting permission
# would be consent Serge never gave.
ok("an interrupt never ALLOWS", not isinstance(result, vws.PermissionResultAllow))
ok("the pending record is cleared", vw.approvals == {})

msg = result.message
ok("Jarvis is told it did NOT run", "NOT RUN" in msg)
# "He refused" and "he never saw it" call for opposite behaviour: one is a
# decision to respect, the other is a question still owed an answer.
ok("Jarvis is told this was not a refusal", "did not refuse" in msg.lower())
ok("Jarvis is told to say so and ask again",
   "tell him" in msg.lower() and "ask again" in msg.lower())

done = [m for m in sent if m.get("type") == "approval_done"]
ok("the page is told the request is over", len(done) == 1)
check("the page is told WHY", done[0].get("reason"), "interrupted")
ok("the page is told what was cancelled",
   done[0].get("tool") == "Bash" and "rm -rf" in (done[0].get("detail") or ""))


# ------------------------------------------------- the normal cases

def test_answer(allow):
    async def go(ws):
        vw = fresh()
        task = asyncio.create_task(
            vw.ask_permission("Edit", {"file_path": "/tmp/a.py"}, None))
        await asyncio.sleep(0)
        aid = next(iter(vw.approvals))
        vw.resolve_approval(aid, allow)
        result = await asyncio.wait_for(task, 2)
        return result, ws.sent
    return with_page(go)


res, sent = test_answer(True)
ok("a click on APPROVE still allows", isinstance(res, vws.PermissionResultAllow))
check("an answered request says so",
      [m for m in sent if m.get("type") == "approval_done"][0].get("reason"),
      "answered")

res, sent = test_answer(False)
ok("a click on DENY still denies", isinstance(res, vws.PermissionResultDeny))
# A real refusal must NOT tell Jarvis to ask again -- that would turn every
# "no" into a negotiation.
ok("a real refusal does not invite a retry", "ask again" not in res.message.lower())
ok("a real refusal is not labelled NOT RUN", "NOT RUN" not in res.message)


def test_timeout():
    async def go(ws):
        vw = fresh()
        old = vws.APPROVAL_TIMEOUT_S
        vws.APPROVAL_TIMEOUT_S = 0.01
        try:
            result = await vw.ask_permission("Bash", {"command": "ls"}, None)
        finally:
            vws.APPROVAL_TIMEOUT_S = old
        return result, ws.sent
    return with_page(go)


res, sent = test_timeout()
ok("a timeout still denies", isinstance(res, vws.PermissionResultDeny))
ok("a timeout tells Jarvis it never ran", "NOT RUN" in res.message)
ok("a timeout says Serge may not have seen it", "may never have seen" in res.message)
check("the page is told it expired",
      [m for m in sent if m.get("type") == "approval_done"][0].get("reason"),
      "timeout")


# ------------------------------------------------- interrupt with nothing pending

def test_idle_interrupt():
    async def go(ws):
        vw = fresh()
        await vw.interrupt()            # must not raise with an empty dict
        return vw.gen
    return with_page(go)


check("an interrupt with nothing pending still bumps gen", test_idle_interrupt(), 1)


def test_two_pending():
    async def go(ws):
        vw = fresh()
        a = asyncio.create_task(vw.ask_permission("Bash", {"command": "one"}, None))
        b = asyncio.create_task(vw.ask_permission("Bash", {"command": "two"}, None))
        await asyncio.sleep(0)
        await vw.interrupt()
        ra, rb = await asyncio.wait_for(asyncio.gather(a, b), 2)
        return ra, rb, vw.approvals
    return with_page(go)


ra, rb, left = test_two_pending()
# One interrupt, several requests: leaving any of them unanswered rebuilds
# the original bug for that one.
ok("EVERY pending request is answered, not just the first",
   isinstance(ra, vws.PermissionResultDeny) and isinstance(rb, vws.PermissionResultDeny))
ok("nothing is left pending", left == {})

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
