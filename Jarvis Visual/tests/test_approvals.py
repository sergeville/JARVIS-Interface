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

What these guard, in order of how much they matter (doctrine INVERTED
2026-08-06 on Serge's 10:04 AM rule -- "it cannot be cancelled"):

  * a pending request SURVIVES every interrupt; the only exits are his
    APPROVE/DENY click and the half-hour time-to-live he set at 11:05;
  * a held interrupt is SAID to the page, never silently swallowed;
  * an answer is never ALLOW by anything but his own click -- an
    accidental grant is consent Serge did not give;
  * a timeout is a deny that tells Jarvis he may never have seen it,
    since "he refused" and "he never saw it" call for opposite behaviour.

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
    # The denial build (2026-08-07) put these on __init__ and ask_permission
    # reads both before anything else -- a stand-in without them dies before
    # the request is even registered.
    vw.denied = None
    vw.reinstated = None
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
#
# INVERTED 2026-08-06 on Serge's 10:04 AM rule: "The only way it can be
# de-active is by me doing an approval or pressing denied or approved.
# It cannot be cancelled." The previous doctrine (7b507a4) answered a
# pending request with a deny on interrupt; his rule outranks it. Now the
# request SURVIVES every interrupt and only his click or the half-hour
# time-to-live ends it.

def test_interrupt():
    async def go(ws):
        vw = fresh()
        task = asyncio.create_task(
            vw.ask_permission("Bash", {"command": "rm -rf /tmp/x"}, None))
        await asyncio.sleep(0)          # let it register and push
        pending = list(vw.approvals.values())
        gen_before = vw.gen
        await vw.interrupt()
        await asyncio.sleep(0)
        survived = not task.done()
        still_pending = vw.approval_pending()
        gen_after = vw.gen
        # Then his click resolves it, proving the popup was still live.
        vw.resolve_approval(pending[0]["id"], False)
        result = await asyncio.wait_for(task, 2)
        return survived, still_pending, gen_before, gen_after, result, ws.sent
    return with_page(go)


survived, still_pending, gen_before, gen_after, result, sent = test_interrupt()

ok("an interrupt does NOT end a pending approval", survived)
ok("the request is still pending after the interrupt", still_pending)
# Bumping gen would mark the turn the approval belongs to as stale --
# a quieter way of killing the same request.
check("a held interrupt leaves gen alone", gen_after, gen_before)
held = [m for m in sent if m.get("type") == "held"]
ok("the page is TOLD the interrupt was held, not silently ignored",
   len(held) >= 1)
ok("his click still resolves it afterwards",
   isinstance(result, vws.PermissionResultDeny))

done = [m for m in sent if m.get("type") == "approval_done"]
ok("the request ends as ANSWERED, never as interrupted",
   len(done) == 1 and done[0].get("reason") == "answered")


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
        await asyncio.sleep(0)
        both_live = not a.done() and not b.done()
        for aid in list(vw.approvals):
            vw.resolve_approval(aid, False)
        await asyncio.wait_for(asyncio.gather(a, b), 2)
        return both_live, vw.approvals
    return with_page(go)


both_live, left = test_two_pending()
# One interrupt, several requests: every one of them survives it.
ok("EVERY pending request survives the interrupt, not just the first",
   both_live)
ok("his clicks then clear them all", left == {})

# ------------------------------------------------- the brink case
# Adversary finding: a request that registers between interrupt()'s top
# guard and the brain teardown must still be held -- the re-check on the
# brink catches it, undoes the gen bump, and never touches the brain.

def test_brink_arrival():
    async def go(ws):
        vw = fresh()
        await vw.turn_lock.acquire()        # a turn is in flight
        calls = {"n": 0}
        real = vws.VoiceWeb.approval_pending

        def racy(self):
            calls["n"] += 1
            if calls["n"] == 1:
                return False                # top guard: nothing yet
            return real(self)               # brink: the truth

        class Brain:
            hit = False
            async def interrupt(self):
                Brain.hit = True

        vw.brain = Brain()
        vws.VoiceWeb.approval_pending = racy
        try:
            fut = asyncio.get_running_loop().create_future()
            vw.approvals[1] = {"id": 1, "future": fut}  # arrives "late"
            await vw.interrupt()
        finally:
            vws.VoiceWeb.approval_pending = real
        return vw.gen, Brain.hit, fut.done(), ws.sent
    return with_page(go)


gen, brain_hit, fut_done, sent = test_brink_arrival()
check("a brink arrival leaves gen net unchanged", gen, 0)
ok("the brain is never torn down over a brink arrival", not brain_hit)
ok("the late request is untouched", not fut_done)
ok("the brink hold is said to the page",
   any(m.get("type") == "held" for m in sent))

# The timeout is HIS number -- half an hour, set 2026-08-06 ~11:05 AM
# ("if it's more than half an hour, then it just cancels itself").
check("the time-to-live is thirty minutes", vws.APPROVAL_TIMEOUT_S, 1800.0)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
