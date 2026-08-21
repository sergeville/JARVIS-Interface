#!/usr/bin/env python3
"""Watch the boot drive and SAY SOMETHING before it fills. It never deletes.

WHY THIS EXISTS
---------------
On 2026-08-15 Chrome's component updater refetched a 2.3 GB model into
$TMPDIR over and over. The disk was never close to full -- it was DRAINING,
fast, and nobody noticed until Serge did. A floor alone would not have caught
it. So this watcher asks two questions, not one:

  1. FLOOR    -- is free space below the floor right now?
  2. VELOCITY -- how much has been lost over the recent window?

The velocity question is the one that would have caught the Chrome loop.

ALERT ONLY -- SERGE'S RULING, 2026-08-15 ~9:15 AM
-------------------------------------------------
His words: "for now, alert only... I like to see, learn a bit what's happening
before doing a big action like that. Delete, I'm always scared of doing
something that should not be deleted."

So this program HAS NO DELETE PATH AT ALL. Not a guarded one, not a
--force one, not a dry-run one. That is asserted by a test that reads this
file's own syntax tree and refuses any call to os.remove, os.unlink,
shutil.rmtree, or a subprocess whose argv starts with rm. Adding an
auto-clean is not a code change, it is a NEW DECISION FROM SERGE.

It also names the biggest thing it can see under a few known temp roots, so
the alert says WHERE the space went and Serge decides what happens to it.
Naming is not touching: it stats, it never opens, moves or removes.

HOW IT REPORTS
--------------
Two channels, because they answer different questions:
  - a macOS notification, so he sees it while doing something else;
  - a line on voice-line/.stack-events.jsonl, so the HUD and any future
    Jarvis session reading the log can see it happened and when.

A COOLDOWN, because an alert that fires every five minutes is an alert
nobody reads. Once a condition alerts, that same condition stays quiet for
COOLDOWN seconds unless it gets materially worse.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

GIB = 1024 ** 3

# --- the dials -------------------------------------------------------------
# Set against this machine: a 460 GiB disk sitting at ~130 GiB free. The
# Chrome loop drained ~2.3 GB in roughly four minutes, so a 5 GiB drop over a
# 15-minute window catches that shape with room to spare while an ordinary
# build, download or Xcode install stays under it.
FLOOR_BYTES = 20 * GIB          # "not much left"
DRAIN_BYTES = 5 * GIB           # "going down fast"
DRAIN_WINDOW = 15 * 60          # ...measured over this many seconds
COOLDOWN = 60 * 60              # don't repeat the same alert inside an hour
WORSE_BY = 5 * GIB              # ...unless it got this much worse
HISTORY_KEEP = 24 * 60 * 60     # keep a day of samples, so we can learn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def state_home():
    """Where this program may keep its state and write its log.

    IT RUNS IN TWO PLACES AND THEY HAVE DIFFERENT RIGHTS. Run by hand from
    the repo it can write into `voice-line/` like everything else. Run by
    launchd from a copy in ~/Library, it CANNOT: a launch agent has no
    Documents-folder access on macOS, and reading a file there fails with
    'Operation not permitted' before a single line executes. That is not a
    hypothesis -- it is how the first install of this watcher failed, on
    2026-08-15, with launchd reporting exit 2 every five minutes.

    So the home is PROBED, never assumed: the repo's voice-line/ if this
    process can actually write there, otherwise the directory this script is
    sitting in. An override is honoured first so the tests never touch
    either. The probe is the point -- asking "may I?" instead of asserting
    "I may" is exactly what the deployed copy needs and the hand-run copy
    does not.
    """
    override = os.environ.get("JARVIS_DISK_WATCH_HOME")
    if override:
        return override
    repo = os.path.join(ROOT, "voice-line")
    if os.path.isdir(repo) and os.access(repo, os.W_OK):
        return repo
    return os.path.dirname(os.path.abspath(__file__))


STATE = os.path.join(state_home(), ".disk-watch.json")
# The stack event log is the HUD's, and it lives in the repo. A deployed copy
# under launchd cannot reach it, so it writes its own log beside its state and
# the notification carries the alert. Said plainly rather than left as a
# channel that silently does nothing.
EVENTS = os.path.join(state_home(), ".stack-events.jsonl")


def free_bytes(path: str = "/") -> int:
    """Space available to an ordinary user -- the number df calls Avail."""
    return shutil.disk_usage(path).free


def human(n: int) -> str:
    """Bytes as something a person reads. Signed, because drops matter."""
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit, size in (("TB", 1024 ** 4), ("GB", GIB), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= size:
            return f"{sign}{n / size:.1f} {unit}"
    return f"{sign}{n} B"


def load_state(path: str = STATE) -> dict:
    """Never raises. A corrupt or missing state file is a fresh start, not a
    crash -- this runs unattended and a watcher that dies on its own state
    file is a watcher that is silently off."""
    try:
        with open(path) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_state(state: dict, path: str = STATE) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, path)


def prune(samples: list, now: float, keep: float = HISTORY_KEEP) -> list:
    return [s for s in samples if now - s[0] <= keep]


def drop_over_window(samples: list, now: float, window: float = DRAIN_WINDOW) -> tuple:
    """How much free space was lost across the window.

    Returns (dropped_bytes, seconds_covered). Compares against the OLDEST
    sample still inside the window -- not the previous sample -- so a slow
    steady bleed accumulates instead of looking like nothing on each tick.

    Positive means space was LOST. Fewer than two samples in the window is
    not evidence of anything, so it reports a zero drop over zero seconds
    rather than guessing.
    """
    inside = [s for s in samples if now - s[0] <= window]
    if len(inside) < 2:
        return 0, 0.0
    oldest = min(inside, key=lambda s: s[0])
    newest = max(inside, key=lambda s: s[0])
    return oldest[1] - newest[1], newest[0] - oldest[0]


def biggest_under(roots: list, limit: int = 3) -> list:
    """Name the largest entries under some temp roots, so the alert can say
    where the space went.

    STATS ONLY. It never opens, moves or removes anything, and an unreadable
    root is skipped rather than raised -- this is decoration on an alert, and
    it must never be the reason the alert fails to fire.
    """
    found = []
    for root in roots:
        try:
            entries = os.scandir(root)
        except Exception:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file():
                        size = entry.stat().st_size
                    else:
                        size = _dir_size(entry.path)
                except Exception:
                    continue
                found.append((size, entry.path))
    found.sort(reverse=True)
    return found[:limit]


def _dir_size(path: str, budget: float = 2.0) -> int:
    """Bounded directory walk. Gives up and reports what it has when the
    budget runs out -- a watcher must not spend minutes measuring a deep tree
    on a machine that is already in trouble."""
    deadline = time.monotonic() + budget
    total = 0
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            break
        try:
            entries = os.scandir(stack.pop())
        except Exception:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        stack.append(entry.path)
                    else:
                        total += entry.stat().st_size
                except Exception:
                    continue
    return total


def decide(free: int, dropped: int, covered: float,
           floor: int = FLOOR_BYTES, drain: int = DRAIN_BYTES) -> dict | None:
    """The whole judgement, as a pure function of numbers.

    Pure on purpose: the decision is the part worth testing exhaustively, and
    a test should not have to fake a disk to reach it. Returns None for "all
    fine" or a dict naming the condition.

    FLOOR outranks DRAIN when both fire -- running out is worse news than
    heading that way, and one alert is read where two are ignored.
    """
    if free < floor:
        return {
            "kind": "floor",
            "headline": f"Disk is low: {human(free)} free",
            "detail": f"below the {human(floor)} floor",
            "severity": free,
        }
    if covered > 0 and dropped >= drain:
        mins = max(1, round(covered / 60))
        return {
            "kind": "drain",
            "headline": f"Disk is draining: {human(dropped)} gone in {mins} min",
            "detail": f"{human(free)} free now",
            "severity": dropped,
        }
    return None


def should_alert(alarm: dict, last: dict, now: float,
                 cooldown: float = COOLDOWN, worse_by: int = WORSE_BY) -> bool:
    """Quiet on a repeat, loud when it gets materially worse.

    'Worse' is direction-aware, and it has to be: for a floor alarm severity
    is FREE SPACE and smaller is worse; for a drain alarm it is BYTES LOST
    and bigger is worse. Comparing them the same way would make a floor alarm
    that is getting worse look like one that is recovering.
    """
    if last.get("kind") != alarm["kind"]:
        return True
    if now - last.get("ts", 0) >= cooldown:
        return True
    before, after = last.get("severity"), alarm["severity"]
    if not isinstance(before, (int, float)):
        return True
    if alarm["kind"] == "floor":
        return after <= before - worse_by
    return after >= before + worse_by


HUD = "http://127.0.0.1:8765/disk-alert"


def tell_the_hud(detail: str, url: str = HUD, timeout: float = 4.0) -> bool:
    """Put the alert on the JARVIS page, which is the channel we own.

    THE PRIMARY CHANNEL, and macOS notifications are the fallback rather than
    the other way round. Learned on 2026-08-15: `osascript` exits 0 whether or
    not a banner ever reaches the screen, so a notification cannot report its
    own delivery -- Serge saw nothing while this program said "delivered".
    A 200 from the HUD is a real acknowledgement: the alert is on the event
    log, and every session and the page itself can see it.

    Returns whether the alert was ACKNOWLEDGED. Never raises -- a watcher
    that dies because a server is down is a watcher that is silently off.
    """
    try:
        import urllib.request
        payload = json.dumps({"detail": detail}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode() or "{}")
            return body.get("ok") is True
    except Exception:
        return False


def notify(title: str, message: str) -> bool:
    """macOS notification -- the FALLBACK channel, and an unreliable one.

    It returns whether osascript exited cleanly, which is NOT whether anything
    appeared on screen: macOS drops the banner silently when the sending app
    has no notification permission, and there is no way to ask from here. So
    this must never be treated as proof that Serge was told. It is a second
    throw at the problem, nothing more.

    WHY "NO WAY TO ASK FROM HERE" IS LITERAL, established 2026-08-21 when
    Serge asked to be shown rather than told. `check=True` only raises on a
    NON-ZERO EXIT, and osascript exits 0 once it has POSTED the request --
    drawing the banner is a later decision macOS makes and never reports
    back. So True here means "asked", never "seen". Both places the setting
    actually lives are closed to this process:
        ~/Library/Group Containers/group.com.apple.usernoted/db2/db
            -> sqlite3: "authorization denied"
        defaults read com.apple.ncprefs apps
            -> empty
    Reading either needs Full Disk Access. **THAT IS SETTLED AND THE ANSWER
    IS NO** -- Serge ruled it out on 2026-08-21 and ruled out explaining how
    to grant it, because a written procedure is a thing a future session can
    quote at him on a bad day. So this function does not get to know, ever,
    and nothing here may be redesigned around it knowing. That is a
    constraint on the design, not a gap in it.
    THE CHEAP CHECK IS HIS, ON HIS OWN SCREEN, and it takes seconds:
        System Settings -> Notifications -> Script Editor
    (Script Editor, because a `display notification` from a script is
    attributed to it -- which is also why running one puts a blank Script
    Editor window on his desktop. Do not reach for osascript to diagnose
    anything; it litters his screen and it told me nothing I needed.)

    NONE OF THE ABOVE IS LOAD-BEARING, and that is the design. This is the
    THIRD channel of three, and the two above it are the ones the alert
    actually rests on: tell_the_hud() is acknowledged, so we know it landed,
    and log_event() is durable and survives a restart. The amber disk line
    Serge saw with his own eyes on 2026-08-15 came through the HUD. If this
    banner never draws again, the alert still reaches him twice.

    Never raises: losing one channel must not cost the others.
    """
    try:
        script = (
            'display notification {} with title {}'.format(
                json.dumps(message), json.dumps(title))
        )
        subprocess.run(["osascript", "-e", script],
                       check=True, capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def log_event(detail: str, path: str = EVENTS) -> bool:
    """Append to the stack event log the HUD and every booting session read.

    Same contract as notify(): never raises. An append-only line is the
    durable half of the alert -- the notification is gone the moment it is
    dismissed, this is still here tomorrow.
    """
    try:
        line = json.dumps({"ts": time.time(), "kind": "warn",
                           "label": "disk", "detail": detail})
        with open(path, "a") as fh:
            fh.write(line + "\n")
        return True
    except Exception:
        return False


def temp_roots() -> list:
    roots = []
    tmp = os.environ.get("TMPDIR")
    if tmp:
        roots.append(tmp)
    roots.append("/tmp")
    return [r for r in roots if os.path.isdir(r)]


def check(now: float | None = None, state_path: str = STATE,
          events_path: str = EVENTS, announce: bool = True) -> dict:
    """One tick. Sample, decide, alert if warranted, remember."""
    now = time.time() if now is None else now
    free = free_bytes("/")

    state = load_state(state_path)
    samples = state.get("samples")
    samples = samples if isinstance(samples, list) else []
    samples = prune(samples, now)
    samples.append([now, free])

    dropped, covered = drop_over_window(samples, now)
    alarm = decide(free, dropped, covered)

    result = {"free": free, "dropped": dropped, "covered": covered,
              "alarm": alarm, "alerted": False}

    if alarm:
        last = state.get("last_alarm")
        last = last if isinstance(last, dict) else {}
        if should_alert(alarm, last, now):
            biggest = biggest_under(temp_roots())
            where = ""
            if biggest:
                size, path = biggest[0]
                where = f" Biggest in temp: {human(size)} at {os.path.basename(path)}."
            detail = f"{alarm['headline']} -- {alarm['detail']}.{where}"
            if announce:
                # Three channels, in order of how much we trust them, and ALL
                # of them are tried: the HUD (acknowledged, so we know), the
                # local log (durable, survives everything), and the macOS
                # banner (free, and may reach him if the permission exists).
                result["hud"] = tell_the_hud(detail)
                result["logged"] = log_event(detail)
                result["notified"] = notify("Jarvis: disk", detail)
            result["alerted"] = True
            result["detail"] = detail
            state["last_alarm"] = {"kind": alarm["kind"], "ts": now,
                                   "severity": alarm["severity"]}

    state["samples"] = samples
    save_state(state, state_path)
    return result


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Watch the disk and say something before it fills. Never deletes.")
    ap.add_argument("--status", action="store_true",
                    help="print what it sees and exit, alerting nobody")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    result = check(announce=not args.status)

    if args.json:
        print(json.dumps(result))
        return 0

    print(f"free: {human(result['free'])}")
    if result["covered"]:
        print(f"change over the last {round(result['covered'] / 60)} min: {human(-result['dropped'])}")
    else:
        print("change: not enough history yet")
    if result["alarm"]:
        print(f"ALARM ({result['alarm']['kind']}): {result['alarm']['headline']}")
        print("alerted" if result["alerted"] else "quiet (cooldown)")
    else:
        print("all fine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
