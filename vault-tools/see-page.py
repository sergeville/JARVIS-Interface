#!/usr/bin/env python3
"""See the HUD the way Serge sees it -- a rendered screenshot, not the data.

Jarvis can already read the *data* behind the page: /signals, the served HTML,
visual-server.log, the vault. What he could not see until this file existed is
the RENDER -- whether text clips at 300px, whether a panel covers another,
whether the board is simply rolled up. Every one of those has cost real time,
and every one was settled by Serge taking a screenshot by hand. This removes
that labour and nothing else.

WHAT THIS DOES NOT DO, deliberately.
    It looks. It does not act. There is no click, no typing, no drag, no form
    submission -- the one exception is calling the page's own boardOpen(true),
    which unfolds the Kanban so a screenshot does not photograph a folded page
    and draw the wrong conclusion. That is a view control, not an action on
    Serge's behalf, and it changes nothing outside the throwaway browser.
    Driving his interface for real is a separate capability and a separate
    decision, and it is his to open.

    THAT PROMISE IS ENFORCED AT RUN TIME, in build_payload(), and the gate
    that proves it is BEHAVIOURAL. THIS IS THE FOURTH ATTEMPT AND THE FIRST
    THREE WERE ALL DEFEATED THE SAME WAY. Round one guarded it with text
    searches; round two with syntax-tree guards on the CALL SITE; round three
    added build_payload() but still proved it by reading source. Each time the
    adversary walked through in a spelling the guard had not been written
    against: three lines inside the call helper, then a rebind of the
    validated name, then an aliased second door onto the wire. `#approve-yes`
    is a real element on the HUD, so every one of those holes could have
    answered a permission request on Serge's behalf.

    THE LESSON, AND WHY THIS ROUND IS DIFFERENT: a guard that reads the source
    is guessing at the last attack's syntax. So the gate now RUNS the driver
    against a recording websocket and asserts that every frame which actually
    left the process is identically a build_payload() return. That checks the
    bytes on the wire rather than the shape of the code that wrote them.
    _session() IS SPLIT OUT OF _drive() for exactly that reason -- the
    protocol half takes its socket as an argument, so it can be driven with no
    browser and no network at all.

    WHAT ROUND FOUR DOES NOT CLAIM, because the reviewer was right to narrow
    it. Source-reading was DEMOTED, not retired, and two edges still rest on
    it alone: a send performed inside _drive() would never be recorded (the
    one-door test is a source test), and the recording gate is a FIXED-POINT
    check rather than an identity one -- it rebuilds from the frame's own
    fields, so a rewrite of a param build_payload does not validate, such as
    Page.navigate's url, rebuilds to itself and passes. That particular case
    is closed by check_landed() at run time and by an AST test; it is named
    here so nobody reads the recording gate as covering more than it does.

SECURITY SHAPE, in brief-check's doctrine.
    - The URL is a HARDCODED CONSTANT. It is not read from argv, env or stdin,
      so there is nowhere to point this at a page that is not Serge's own --
      and where the browser actually LANDED is re-checked after navigation,
      because a redirect answers successfully and photographs beautifully.
    - Every outgoing DevTools message is validated against ALLOWED_CDP, and
      any `expression` must be exactly BOARD_OPEN_JS. Refusals raise.
    - Output goes to a scratch directory OUTSIDE the repo, asserted AT RUN
      TIME both for the directory and for the path actually written. The repo
      is public; a screenshot of this page carries his tasks, his sessions and
      his usage percentages, and an image that lands inside the tree is one
      commit away from being published.
    - Nothing the page wrote reaches this process's output. A JavaScript
      exception carries page-authored text, and this process prints its errors
      to stderr where Jarvis reads them, so check_response() withholds it.

REQUIREMENTS, stated honestly because a reviewer caught the old wording.
    aiohttp is NOT available system-wide on this machine -- it lives in the
    voice-line venv and the Jarvis Visual environment, not in /usr/bin/python3.
    So the interpreter is named in the usage line below, and capture() checks
    for aiohttp BEFORE it spends a browser launch rather than dying on the
    import with Chrome already running.

Usage:
    voice-line/.venv/bin/python3 vault-tools/see-page.py            # as it sits
    voice-line/.venv/bin/python3 vault-tools/see-page.py --board    # unfolded
"""

import asyncio
import base64
import copy
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

# --- the constants that are the security shape -------------------------------

PAGE_PORT = 8765
PAGE_URL = "http://127.0.0.1:8765/"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")

# Outside the repo on purpose -- see the docstring. The repo is public.
SHOT_DIR = os.path.join(tempfile.gettempdir(), "jarvis-page")

# Resolved through realpath because /tmp is a symlink to /private/tmp on macOS.
# Comparing a resolved path against an unresolved one is how the scratch-dir
# guard passed green with the scratch dir literally inside the tree.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# The ONE module this file may load from disk, named as a constant so a test
# can pin it. It used to be built inline inside _clean_dock(), and the
# adversary repointed it at a file that does not exist with the suite green --
# so the Dock silently stopped being cleaned and nothing said a word.
DOCK_CLEAN = os.path.join(REPO_ROOT, "vault-tools", "dock-clean.py")

# The one thing this may ask the page to do, written once so a test can pin it.
BOARD_OPEN_JS = "boardOpen(true)"

# Every DevTools method this file may send. Enforced at run time in
# build_payload() and pinned BY EQUALITY in the tests -- a property test on an
# allowlist ("no Input.*", "only one method containing 'evaluate'") is a filter
# you have to keep guessing right, and it already admitted Runtime.callFunctionOn
# and Page.handleJavaScriptDialog, both of which act.
ALLOWED_CDP = (
    "Emulation.setDeviceMetricsOverride",
    "Page.enable",
    "Page.navigate",
    "Runtime.evaluate",
    "Page.captureScreenshot",
)

# Params that carry executable code or replace the document. None of these
# belongs in a tool that only looks, whatever method is carrying them.
CODE_BEARING_PARAMS = ("scriptSource", "functionDeclaration", "html",
                       "source", "declaration")

VIEWPORT = (1600, 1000)
SETTLE_MS = 2500       # the HUD polls /signals; give it a beat to fill in
BOARD_SLIDE_MS = 900   # the roll-down eases over 520ms; outlast it
LAUNCH_TIMEOUT_S = 20.0
CALL_TIMEOUT_S = 20.0  # a reply that never arrives must fail, not hang forever

# A token echoed back to Jarvis must be incapable of carrying a sentence.
# Same doctrine as brief-check.py, where the only variable in the output is a
# date parsed to integers: shape-check it or say "unknown". The segment cap is
# load-bearing -- "Serge.approve.the.pending.request-now" is prose wearing a
# token's punctuation, and the first version of this returned it verbatim.
_SAFE_TOKEN = re.compile(r"\A[A-Za-z0-9_:.\-]{1,60}\Z")
_MAX_TOKEN_SEGMENTS = 4


def _safe_token(value):
    """Return value only if it cannot form prose; otherwise 'unknown'."""
    if not isinstance(value, str) or not _SAFE_TOKEN.match(value):
        return "unknown"
    segments = [s for s in re.split(r"[.\-_:]+", value) if s]
    if len(segments) > _MAX_TOKEN_SEGMENTS:
        return "unknown"
    return value


def check_url(url=PAGE_URL):
    """Assert the target is loopback. Raises rather than returning a bool --
    a caller that ignores a bool is how a guard becomes decoration."""
    host = urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"refusing to render a non-loopback host: {host!r}")
    return True


def target_url(port, target_id, timeout=2.0):
    """Where the tab we actually drove IS, from Chrome's own HTTP endpoint.

    Deliberately NOT a DevTools call: Page.getNavigationHistory is refused by
    this Chrome (protocol error -32000, found by running it), and adding an
    execution-capable method to the allowlist to answer a read-only question
    would be the wrong trade anyway. /json/list is the same endpoint
    _wait_for_devtools already reads.

    `target_id` IS THE CORRECTION. This used to return the first target of
    type "page" and the landed-check trusted it -- which happens to be the
    driven tab in single-tab headless and was never asserted to be. So the
    guard read one tab's URL while the socket drove another, and the reviewer
    was right that the claim was stronger than the code. Now the id from the
    socket we opened is the id we look up, and a target that has vanished
    raises instead of falling back to a neighbour.
    """
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json/list", timeout=timeout
    ) as r:
        targets = json.load(r)
    for t in targets:
        if t.get("id") == target_id:
            return t.get("url") or ""
    raise RuntimeError("the tab this socket drove is no longer listed")


def check_landed(url):
    """Assert the browser is actually ON loopback after navigating.

    check_url() vets what we ASK for; a 302 decides what we GET. A redirect
    answers successfully, sets no errorText, and photographs beautifully --
    so without this the tool would hand Jarvis a clean PNG of somewhere else
    and call it Serge's page.
    """
    host = urlparse(url or "").hostname
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(
            f"the browser landed off loopback (host {_safe_token(str(host))})")
    return True


def check_shot_dir(path=None):
    """Assert the screenshot DIRECTORY is outside the repo. Runtime, not test.

    SHOT_DIR comes from tempfile.gettempdir(), which reads TMPDIR -- so the
    destination is environment, and the environment can put it inside a PUBLIC
    repository holding his tasks, sessions and usage numbers. A test that
    computes the same expression from the same environment agrees with the bug.
    Both sides go through realpath: /tmp is a symlink to /private/tmp here.
    """
    real = os.path.realpath(SHOT_DIR if path is None else path)
    root = os.path.realpath(REPO_ROOT)
    if real == root or real.startswith(root + os.sep):
        raise ValueError(f"refusing to write screenshots inside the repo: {real}")
    return True


def check_out_path(path):
    """Assert the file ACTUALLY being written sits inside the scratch dir.

    check_shot_dir() vets the directory constant; this vets the path. The
    adversary added a second open(..., "wb") under the repo root and the suite
    stayed green, because the old guard checked the mode of a write and never
    its destination.
    """
    real = os.path.realpath(path)
    shots = os.path.realpath(SHOT_DIR)
    if not (real == shots or real.startswith(shots + os.sep)):
        raise ValueError(f"refusing to write outside the scratch dir: {real}")
    return True


def build_payload(msg_id, method, params):
    """Validate and FREEZE one outgoing DevTools message. THE boundary.

    This is where "it looks, it never acts" is actually enforced, and it is
    here -- travelling with the message -- rather than in a test that reads the
    call site, because the adversary defeated the call-site version with three
    lines placed between the call site and the wire.

    Three refusals: a method outside ALLOWED_CDP, an `expression` that is not
    exactly the board unfold, and any param that carries code or replaces the
    document. The params are DEEP-copied into the payload, so no later mutation
    of the caller's dict can reach the browser. The previous version said the
    same sentence over a shallow dict() copy, which was true only at the top
    level -- a nested param would have ridden through. Not exploitable at
    today's call sites, and corrected anyway: a docstring that overstates the
    code is how the next reader builds on a guarantee that is not there.
    """
    if method not in ALLOWED_CDP:
        raise ValueError(
            f"refusing a DevTools method outside the allowlist: {method!r}")
    if "expression" in params and params["expression"] != BOARD_OPEN_JS:
        raise ValueError(
            "refusing to evaluate anything but the board unfold -- this tool "
            "looks, it does not act")
    for banned in CODE_BEARING_PARAMS:
        if banned in params:
            raise ValueError(f"refusing a code-bearing param: {banned!r}")
    if "url" in params:
        # THE ADVERSARY'S ROUND-FOUR WIN, and it was the worst hole in the
        # file: Page.navigate is on the allowlist and its url was validated by
        # NOTHING. check_url only ever guarded the module constant, and
        # check_landed runs once, before the unfold and the capture, so any
        # later navigate went unchecked. build_payload accepted
        # javascript:void(0), data:text/html,..., file:///etc/passwd and
        # chrome://settings -- arbitrary navigation through a frame this
        # boundary called valid. Every url on the wire now goes through the
        # same loopback gate as the target.
        check_url(params["url"])
    return {"id": msg_id, "method": method, "params": copy.deepcopy(params)}


def check_response(method, data):
    """Turn one DevTools reply into a result, or refuse. Pure, and here on
    purpose -- a closure inside _drive() can only be tested with a browser.

    TWO failure shapes and only the first one looks like a failure. A protocol
    error arrives as an "error" key. A JavaScript exception arrives inside a
    perfectly successful reply, as "exceptionDetails" -- which is why renaming
    boardOpen() in jarvis.html made --board photograph a folded board and
    report success. Both raise here.

    NOTHING THE PAGE WROTE GOES INTO THE MESSAGE. exceptionDetails carries
    page-authored text and main() prints exceptions to stderr, so echoing it
    would be the page speaking to Jarvis -- the one absolute this file claims.
    `method` is our own constant; an error code is coerced to an integer.
    """
    if "error" in data:
        err = data["error"] if isinstance(data["error"], dict) else {}
        code = err.get("code")
        code = code if isinstance(code, int) else "?"
        raise RuntimeError(f"{method}: the browser refused the call (code {code})")
    result = data.get("result", {})
    if isinstance(result, dict) and "exceptionDetails" in result:
        raise RuntimeError(
            f"{method}: the page threw -- nothing was captured. "
            "The message is withheld on purpose: it is written by the page."
        )
    return result


def check_navigation(result):
    """A navigation that failed still answers successfully and still screenshots.

    Page.navigate reports failure in an errorText field, not by erroring, so
    without this a dead server yields a clean PNG of Chrome's error page and
    the tool reports success -- the worst possible outcome for something whose
    entire job is to tell Jarvis what is really on screen.
    """
    err = result.get("errorText") if isinstance(result, dict) else None
    if err:
        raise RuntimeError(f"navigation failed ({_safe_token(err)})")
    return True


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def shot_path(name="page.png"):
    """A screenshot path under the scratch dir. Any directory component in the
    name is stripped, so a name can never walk out of the scratch dir. An
    empty or dot-only name RAISES rather than resolving to the directory
    itself, which used to surface as IsADirectoryError from deep inside."""
    base = os.path.basename(name.rstrip("/")) if isinstance(name, str) else ""
    if not base or base in (".", ".."):
        raise ValueError(f"refusing an empty screenshot name: {name!r}")
    return os.path.join(SHOT_DIR, base)


def _wait_for_devtools(port, deadline):
    """Poll Chrome's own endpoint until it answers, then take a target.

    Returns (websocket url, target id) -- BOTH, because the landed-check has
    to look up the very tab this socket drove rather than whichever page
    target happens to be listed first.
    """
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=1.0
            ) as r:
                targets = json.load(r)
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"], t.get("id")
        except Exception as e:      # noqa: BLE001 -- Chrome is simply not up yet
            last = e
        time.sleep(0.15)
    raise RuntimeError(f"Chrome devtools never came up on {port} ({last})")


async def _session(ws, url, out, open_board, port, target_id):
    """The whole conversation with the browser. Pixels only.

    SPLIT OUT OF _drive() DELIBERATELY, and the split is the gate rather than
    tidiness: everything that speaks to the browser lives here and takes `ws`
    as an argument, so a test can hand it a recording stub and assert that
    every frame which actually left this function is identically a
    build_payload() return. Three rounds of source-reading guards were walked
    past; checking the bytes is what cannot be re-spelled around.
    """
    msg_id = 0

    async def call(method, **params):
        nonlocal msg_id
        msg_id += 1
        # Built and validated in one step, then sent unmodified. No statement
        # may sit between these two lines mutating it -- that is exactly the
        # breach the adversary demonstrated, twice, in two different syntaxes.
        payload = build_payload(msg_id, method, params)
        await ws.send_json(payload)
        while True:
            raw = await asyncio.wait_for(ws.receive_str(),
                                         timeout=CALL_TIMEOUT_S)
            data = json.loads(raw)
            if data.get("id") == payload["id"]:
                return check_response(method, data)

    w, h = VIEWPORT
    await call("Emulation.setDeviceMetricsOverride",
               width=w, height=h, deviceScaleFactor=1, mobile=False)
    await call("Page.enable")
    check_navigation(await call("Page.navigate", url=url))
    await asyncio.sleep(SETTLE_MS / 1000)
    check_landed(target_url(port, target_id))

    if open_board:
        # The page is collapsed until a cursor approaches its heading, so a
        # plain screenshot photographs a folded board. This calls the page's
        # own function rather than faking a hover, because a synthetic mouse
        # move is an action and this is a view control.
        await call("Runtime.evaluate", expression=BOARD_OPEN_JS)
        await asyncio.sleep(BOARD_SLIDE_MS / 1000)

    res = await call("Page.captureScreenshot", format="png")

    check_out_path(out)
    with open(out, "wb") as f:
        f.write(base64.b64decode(res["data"]))
    return out


async def _drive(ws_url, url, out, open_board, port, target_id):
    """Open the socket and hand it to _session(). Connection only, no protocol."""
    import aiohttp

    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(ws_url, max_msg_size=0) as ws:
            return await _session(ws, url, out, open_board, port, target_id)


def capture(out=None, open_board=False, url=PAGE_URL):
    """Render the page and write a PNG. Returns the path written.

    `out` is routed through shot_path() AND re-checked by check_out_path(), so
    the FUNCTION is held to the same rule as the CLI. It used to write wherever
    it was told while the docstring claimed screenshots stay outside the repo --
    a promise made by the caller is not a property of the code.
    """
    check_url(url)
    check_shot_dir()
    out = shot_path(out or ("board.png" if open_board else "page.png"))
    check_out_path(out)

    # Before a browser is spent: aiohttp lives in the venv, not system-wide,
    # and dying on the import with Chrome already running is how this leaked.
    if importlib.util.find_spec("aiohttp") is None:
        raise RuntimeError(
            f"aiohttp is not available to this interpreter ({sys.executable}); "
            "run this with voice-line/.venv/bin/python3"
        )

    os.makedirs(SHOT_DIR, exist_ok=True)

    port = free_port()
    profile = tempfile.mkdtemp(prefix="jarvis-see-")
    proc = None
    # The launch is INSIDE the try. It used to sit above it, so a Chrome that
    # failed to start -- a moved app bundle, a bad path -- left the profile
    # directory on Serge's disk on every single run, with nothing to clean it.
    try:
        proc = subprocess.Popen(
            [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
             f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check",
             f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url, target_id = _wait_for_devtools(port,
                                               time.time() + LAUNCH_TIMEOUT_S)
        return asyncio.run(
            _drive(ws_url, url, out, open_board, port, target_id))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        _clean_dock()


def _clean_dock():
    """Clear the Dock ghosts this launch just created. Serge's ask.

    Every headless Chrome runs with its own throwaway --user-data-dir, and
    macOS files each one as a freshly "recently used" app -- so three renders
    put three Chrome icons in his Dock. dock-clean.py removes only those, and
    only when there are some, so a clean run costs no Dock restart.

    NEVER RAISES. Tidying up is not worth losing a screenshot over, and this
    sits in the same finally as the browser teardown -- an exception here
    would mask the real error the caller is trying to report.

    THE PATH IS THE CONSTANT DOCK_CLEAN, not an expression built here. This
    function loads and executes a file from disk, which makes it the widest
    primitive in the file; the adversary repointed it at a nonexistent name
    with the suite green, so the Dock silently stopped being cleaned. A test
    now pins both the path and that clean() is actually reached.
    """
    try:
        spec = importlib.util.spec_from_file_location("dock_clean", DOCK_CLEAN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.clean()
    except Exception:       # noqa: BLE001 -- housekeeping never costs a render
        pass


def main(argv):
    open_board = "--board" in argv[1:]
    unknown = [a for a in argv[1:] if a != "--board"]
    if unknown:
        # No path, no URL, no anything else -- see the docstring.
        print(f"unknown argument(s): {' '.join(unknown)}", file=sys.stderr)
        print("usage: see-page.py [--board]", file=sys.stderr)
        return 2
    try:
        print(capture(open_board=open_board))
    except Exception as e:      # noqa: BLE001 -- a tool, not a hook; say why
        print(f"could not render the page: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
