"""Every hook this project deploys must RETURN. All of them, driven for real.

WHY THIS FILE IS ABOUT THE CLASS AND NOT ABOUT NAMED SCRIPTS. The same bug has
been found in five files in four days, each written by somebody who believed
they had guarded against it:

  * session_record.py guarded with `sys.stdin.isatty()`     (2026-08-14)
  * board-guard.py    guarded with isatty AND a size cap    (2026-08-14)
  * question_hook.py  guarded with nothing at all           (2026-08-15)
  * session_registry.py  `sys.stdin.read()`, no guard       (2026-08-15)
  * session_mail.py      `sys.stdin.read()`, no guard       (2026-08-15)

They fire on SessionStart, SessionEnd, Stop, UserPromptSubmit, Notification and
PostToolUse -- on nearly every turn of every session on this machine.

============================================================================
THE FIRST VERSION OF THIS FILE DID NOT TEST ANY OF THE THREE HOOKS IT SHIPPED
WITH, AND THE REASON IS THE WHOLE LESSON.
============================================================================

It gated every behavioural test on a helper, `reads_stdin(src)`, that searched
the syntax tree for `sys.stdin`. The fix for those three hooks REMOVED
`sys.stdin` from all three files -- that is what routing through `hookio`
means. So at the moment they were fixed they dropped out of their own sweep,
and the only script left being exercised was `session_record.py`, fixed the
previous day in a different commit.

The reviewer proved it rather than arguing it: it put the original hang back
into `question_hook.py` spelled `os.read(0, ...)` instead of `sys.stdin`, and
this file returned `Ran 7 tests / OK`.

**THE GATE WAS THE BUG. A test that only examines hooks exhibiting the symptom
stops examining them the moment they are cured.** So there is no gate here now.
The property is not "every hook that reads stdin returns" -- it is EVERY HOOK
RETURNS, and a hook that never opens stdin satisfies it trivially and costs a
few milliseconds to prove. Nothing in this file asks whether a script reads
stdin before deciding to test it.

WHY IT DRIVES `main()` AND NOT A NAMED HELPER. The old harness called
`getattr(m, '_read_stdin', None) or getattr(m, '_read_payload')`. Against the
pre-fix tree no such function existed, so the child died on AttributeError in
about twenty milliseconds and the `assertTrue(returned)` that exists to detect
hanging PASSED for three hooks that provably hang. The file was red without the
fix, but red on "this module has no function of that name" -- never once on "it
blocked". A test that has never observed the failure it is named for is not
evidence. So these run the actual deployed command line, and the only thing
asserted is the thing that matters: did the process come back, inside the
timeout it is deployed with.

WHY THAT IS SAFE TO DO. Running the real hooks against the real tree would
write into the live session registry, post real notices onto the bus, and
touch the vault -- a test that pollutes production state is a bug this project
has already had. So `_sandbox()` copies the scripts into a temp root. Every
one of these hooks derives its root and its state files from `__file__`
(SESSIONS_FILE, MAIL_FILE, QUESTION_FILE, STAMP, WATERMARK, NOTE, BRIEF_DIR),
so a copy relocates all of it. That claim is not taken on trust:
`test_NOTHING_IN_THE_LIVE_TREE_IS_WRITTEN_BY_A_FULL_SWEEP` stamps the mtime and
size of the real state files, runs a full sweep, and asserts every one
unchanged. The version of that test which merely checked the sandbox PATH was
asserting a proxy -- a statement about a string -- for the property it named.
"""
import ast
import collections
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "claude-settings.json.template"
DEPLOYED = [ROOT / ".claude" / "settings.json",
            ROOT / "Jarvis Visual" / ".claude" / "settings.json"]

# The named list the discovery is pinned against by EQUALITY, not by ">= 4".
# The old vacuity guard was `assertGreaterEqual(len(...), 4)`, which let six
# hooks silently become four -- and that is exactly what a tokeniser bug does:
# it drops hooks, it does not empty the list. A count floor cannot see a drop;
# an equality pin can. This list is a DECISION. Adding a hook means adding it
# here in the same commit, and that is the point: the addition is reviewed.
EXPECTED_HOOK_SCRIPTS = (
    "vault-tools/board-guard.py",
    "vault-tools/brief-check.py",
    "vault-tools/session_record.py",
    "voice-line/question_hook.py",
    "voice-line/session_mail.py",
    "voice-line/session_registry.py",
)

# The fraction of a hook's DEPLOYED timeout a bounded read may consume. Not a
# round number picked here: it is the adversary's own prescription, and the
# reason is that returning before the axe falls is not the property -- a hook
# that finishes at 9.9s of a 10s timeout is killed in production by any cold
# import or loaded machine, while a gate that only asks "did it come back"
# stays green through it.
MARGIN = 0.6

# The invocation set, pinned the same way the script set is, and for the same
# reason: a bare `10` is a magic number sitting beside a named list it could
# have been derived from. Adding a hook -- or a new MODE of an existing hook --
# means adding it here, in the same commit, where somebody reviews it.
#
# IT CARRIES THE TIMEOUT, AND EVERY CONFIG IS HELD TO THE WHOLE LIST -- see
# `test_EVERY_config_wires_the_WHOLE_set_not_just_the_union`. Both halves of
# that are findings, not taste:
#
#   * THE REVIEWER DELETED THE ENTIRE `Notification` GROUP -- `question_hook.py
#     notify`, which is SERGE'S PERMISSION BANNER -- from a deployed
#     settings.json and the whole file stayed green. Nothing compared a config
#     against this list: the script set was unchanged (question_hook is still
#     wired for stop and clear) and `every_invocation()` is a UNION the
#     template kept filling. So the banner could stop being wired on every
#     session and the gate would say nothing. That is the original failure of
#     this file wearing new clothes: the thing stops being wired and drops out
#     of its own test.
#   * THE TIMEOUT IS HERE BECAUSE A *LOOSER* DEPLOYED TIMEOUT WAS INVISIBLE.
#     `every_invocation()` deliberately keeps the SMALLEST timeout across
#     configs so drift makes the sweep stricter -- which is right for the
#     sweep, and precisely why nothing could see a deployed file being
#     loosened. The 20-vs-15 skew Serge ruled on at 08:03 today was found by
#     hand, not by this suite.
#   * AND IT CARRIES THE EVENT AND THE MATCHER, WHICH IS THE REVIEWER'S SECOND
#     PASS AND THE REASON THE CLASS WAS STILL OPEN. The first version of this
#     pin was a bag of (script, argv, timeout): `hook_invocations` iterated
#     `cfg["hooks"].values()` and THREW THE EVENT KEY AWAY, and never read the
#     matcher at all. So MOVING the `notify` group from `Notification` to
#     `SessionEnd` -- same script, same argv, same timeout, no banner ever
#     again -- was indistinguishable from wiring it correctly, and so was
#     narrowing board-guard's matcher from `Edit|Write|NotebookEdit|Bash` to
#     `Edit` alone. Deleting the group was red; moving it was green. WHEN a
#     hook fires is not a detail of the wiring, it IS the wiring.
#   * AND IT CARRIES THE INTERPRETER TOKENS. `_run` launches `sys.executable`
#     whatever the config says, so a deployed `python3` rewritten to a path
#     that does not exist is invisible to the behavioural sweep AS WELL as to
#     the pin -- the sweep would keep passing while every hook on the machine
#     died at the harness. Nothing else in this file can see that.
EXPECTED_WIRING = (
    # event, matcher, interpreter tokens, script, argv, timeout
    ("Notification", None, ("python3",),
     "voice-line/question_hook.py", ("notify",), 10),
    ("PostToolUse", "Edit|Write|NotebookEdit|Bash", ("python3",),
     "vault-tools/board-guard.py", (), 15),
    ("SessionEnd", None, ("python3",),
     "voice-line/session_registry.py", ("end",), 15),
    ("SessionStart", None, ("python3",),
     "vault-tools/brief-check.py", (), 15),
    ("SessionStart", None, ("python3",),
     "voice-line/session_mail.py", ("opened",), 15),
    ("SessionStart", None, ("python3",),
     "voice-line/session_registry.py", ("start",), 15),
    ("Stop", None, ("python3",),
     "vault-tools/session_record.py", (), 15),
    ("Stop", None, ("python3",),
     "voice-line/question_hook.py", ("stop",), 15),
    ("UserPromptSubmit", None, ("python3",),
     "voice-line/question_hook.py", ("clear",), 10),
    ("UserPromptSubmit", None, ("python3",),
     "voice-line/session_mail.py", ("deliver",), 10),
)

# What the SWEEP needs: one run per distinct (script, argv). Derived from the
# reviewed list above rather than typed a second time, because two hand-kept
# lists of the same facts drift, and the drift would land in the gate.
EXPECTED_INVOCATIONS = tuple(sorted(
    {(rel, argv, t) for _e, _m, _i, rel, argv, t in EXPECTED_WIRING}))

# The hook type Claude Code will actually execute. Pinned because `"type":
# "command"` rewritten to anything else silently unwires the hook while every
# other field still reads correctly.
EXPECTED_KIND = "command"

# Gitignored files that only exist once a hook has RUN against this tree. They
# are how `test_a_DEPLOYED_config_cannot_simply_VANISH` tells "never installed"
# from "deleted", and getting that right is the whole difficulty of the
# adversary's finding: `all_configs()` skips a file that is not there, so
# deleting ONE hook group was red 1 and deleting the WHOLE FILE was green --
# strictly weaker against the strictly worse fault. Requiring the deployed
# files outright would be wrong the other way: a fresh clone has not run
# install.sh yet, and every agent injection round works on a `git archive`
# copy that by definition has neither file. So the question is not "should
# these exist" but "has this tree ever had working hooks", and these answer it.
HOOK_STATE_MARKERS = (
    "voice-line/.sessions.jsonl",
    "voice-line/.session-mail.jsonl",
    "voice-line/.board-guard.json",
    "Jarvis Visual/transcripts/.terminal-watermarks.json",
)

# Every spelling of a blocking read on fd 0 that this project could plausibly
# reach for. `sys.stdin` is NOT the only one -- the reviewer's first injection
# reproduced the original hang with `os.read(0, ...)` and this file did not
# notice. A hook using any of these must route through the shared reader.
_ROOT_MARKER = "{{JARVIS_ROOT}}"


def _script_rel(tok):
    """The repo-relative path this token names, or None if it names no script.

    Deliberately NOT existence-based: a hook wired to a script that is missing
    must come out RED at `test_every_hook_script_exists`, not vanish from the
    sweep. Existence-filtering here would make a broken wiring invisible, which
    is the same class of mistake as the gate this file was rewritten to remove.

    THE ABSOLUTE ARM COMPARES RESOLVED PATHS, NOT STRING PREFIXES, and that is
    not fussiness -- it is a bug my own injection round caught in this very
    function. The first version asked `tok.startswith(str(ROOT) + "/")`. `ROOT`
    is `.resolve()`d, so under any symlinked path the two spellings differ and
    EVERY hook in the deployed settings files silently fails to be discovered.
    On macOS that is not exotic: `/var` is a symlink to `/private/var`, which
    is where `mktemp -d` puts things, so the injection harness's own baseline
    went red and would have made all seventeen results meaningless. A real
    Jarvis under a symlinked home, an external volume, or `/tmp` would have hit
    it for real, and the failure mode is the silent one: the behavioural sweep
    quietly covers template hooks only.
    """
    tok = tok.strip()
    if tok.startswith(_ROOT_MARKER + "/"):
        return tok[len(_ROOT_MARKER) + 1:] or None
    if not os.path.isabs(tok):
        return None
    try:
        rel = os.path.relpath(os.path.realpath(tok), os.path.realpath(ROOT))
    except (OSError, ValueError):
        return None
    # `..` anywhere means it is not under the repo at all -- /usr/bin/python3
    # is an absolute token too, and must not be mistaken for a hook script.
    if rel.startswith("..") or rel == ".":
        return None
    return rel


# One wired hook, whole. The first version of this was a bare
# (rel, argv, timeout) triple and the two fields it did not have -- `event` and
# `matcher` -- are the two that decide WHEN the hook fires, which is the only
# thing that decides whether Serge gets his permission banner.
Wired = collections.namedtuple("Wired", "event matcher kind interp rel argv timeout")


def hook_invocations(cfg):
    """A `Wired` for every hook command in a config.

    THREE THINGS THE FIRST VERSION GOT WRONG, ALL PROVEN BY THE REVIEWER:

    1. It used `str.split()`. Every hook under `Jarvis Visual/` must be quoted
       because that directory name contains a space -- and `Jarvis Visual/`
       holds one of this repo's two deployed settings files, so that is not a
       hypothetical shape, it is the next one anybody writes. `.split()`
       shredded `"{{JARVIS_ROOT}}/Jarvis Visual/tools/x.py"` into two tokens,
       neither of which matched, and the hook disappeared in silence.
       `shlex.split` is what a shell actually does.
    2. It required `.endswith(".py")`, while the file's own title claimed
       EVERY deployed hook. A `bash .../hang-hook.sh` was excluded outright.
    3. It read the template only. A hook hand-added to a deployed
       `.claude/settings.json` and never put back into the template was
       structurally invisible, because a rendered file contains no
       `{{JARVIS_ROOT}}`. This repo hand-edits those files -- the live
       `session_record.py` timeout drift (deployed 20, template 15) is exactly
       that, and it is still open.
    4. IT DISCARDED THE EVENT KEY AND NEVER READ THE MATCHER -- the reviewer's
       second pass. `.values()` throws away the one field that says when the
       hook fires. Everything downstream inherited the blindness, so a hook
       moved to a different event, or a matcher narrowed from four tools to
       one, compared EQUAL to correct wiring.
    """
    out = []
    for event, groups in (cfg.get("hooks") or {}).items():
        for g in groups or []:
            for h in (g.get("hooks") or []):
                cmd = str(h.get("command", ""))
                try:
                    toks = shlex.split(cmd)
                except ValueError:
                    toks = cmd.split()
                rel = None
                idx = 0
                for i, tok in enumerate(toks):
                    r = _script_rel(tok)
                    if r is not None:
                        rel, idx = r, i
                        break
                if rel is None:
                    continue
                out.append(Wired(event, g.get("matcher"), h.get("type"),
                                 tuple(toks[:idx]), rel, tuple(toks[idx + 1:]),
                                 h.get("timeout")))
    return out


def _triples(cfg):
    """(rel, argv, timeout) for each wired hook -- what the SYNTHETIC-config
    discovery tests below are about. They exist to pin the tokeniser, not the
    event routing, so they compare the three fields the tokeniser produces and
    leave the event and matcher to the per-config equality test."""
    return [(w.rel, w.argv, w.timeout) for w in hook_invocations(cfg)]


def all_configs():
    """Every settings source that can wire a hook: the template AND both
    deployed files. Missing deployed files are skipped, not fatal -- they only
    exist after install.sh has run -- but the template is always present."""
    cfgs = []
    for p in [TEMPLATE] + DEPLOYED:
        if p.is_file():
            try:
                cfgs.append((p, json.loads(p.read_text())))
            except ValueError:
                cfgs.append((p, {}))
    return cfgs


def discovered_scripts():
    """The union of hook scripts across every config, sorted."""
    seen = set()
    for _p, cfg in all_configs():
        for w in hook_invocations(cfg):
            seen.add(w.rel)
    return sorted(seen)


def every_invocation():
    """(label, rel, argv, timeout) for every hook command in every config.

    De-duplicated on (rel, argv) because the two deployed files wire the same
    ten commands: running each twice proves nothing and doubles the runtime.
    The timeout kept is the SMALLEST seen for that invocation, which is the
    real contract -- the drift between deployed 20 and template 15 must make
    the test stricter, never more forgiving.
    """
    best = {}
    for p, cfg in all_configs():
        for w in hook_invocations(cfg):
            key = (w.rel, tuple(w.argv))
            prev = best.get(key)
            t = w.timeout if w.timeout is not None else None
            if prev is None:
                best[key] = t
            elif t is not None and (prev is None or t < prev):
                best[key] = t
    return sorted((f"{rel} {' '.join(argv)}".strip(), rel, list(argv), t)
                  for (rel, argv), t in best.items())


def blocking_stdin_spellings(src):
    """Every raw blocking read on fd 0 in this source, by AST, never substring.

    By the syntax tree because both the hooks and this project's tests quote
    the old broken calls while explaining them -- a guard a docstring can trip
    is a guard that gets weakened until it stops tripping.

    `sys.stdin` is only one spelling. The reviewer reproduced the exact
    original hang with `os.read(0, ...)`, which the first version of this file
    was blind to, and `open("/dev/stdin")`, `input()` and `fileinput` are all
    the same hang wearing different clothes.
    """
    found = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    for n in ast.walk(tree):
        # sys.stdin.read() / sys.stdin.readline() / sys.stdin.readlines()
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Attribute)
                    and f.attr in ("read", "read1", "readline", "readlines")
                    and isinstance(f.value, ast.Attribute)
                    and f.value.attr == "stdin"):
                found.append("sys.stdin." + f.attr)
            # sys.stdin.buffer.read() / .read1() -- RED-PEN FINDING 3 from the
            # voice line, and it was right twice over. `"buffer"` used to sit
            # in the tuple above, where it could NEVER match: `.buffer` is an
            # attribute access, never the `func` of a Call. So the code read as
            # if it had been thought about while catching nothing -- and this
            # is the exact spelling the 08-14 adversary named as sailing
            # through, one file over.
            if (isinstance(f, ast.Attribute)
                    and f.attr in ("read", "read1", "readline", "readlines")
                    and isinstance(f.value, ast.Attribute)
                    and f.value.attr == "buffer"
                    and isinstance(f.value.value, ast.Attribute)
                    and f.value.value.attr == "stdin"):
                found.append("sys.stdin.buffer." + f.attr)
            # json.load(sys.stdin) / json.loads(sys.stdin.read())
            if (isinstance(f, ast.Attribute) and f.attr in ("load", "loads")
                    and any(isinstance(a, ast.Attribute) and a.attr == "stdin"
                            for a in n.args)):
                found.append("json.load(sys.stdin)")
            # os.read(0, ...) -- THE ONE THAT PROVED THE OLD GATE HOLLOW
            if (isinstance(f, ast.Attribute) and f.attr == "read"
                    and isinstance(f.value, ast.Name) and f.value.id == "os"
                    and n.args and isinstance(n.args[0], ast.Constant)
                    and n.args[0].value == 0):
                found.append("os.read(0, ...)")
            # open("/dev/stdin") and open(0)
            if isinstance(f, ast.Name) and f.id == "open" and n.args:
                a0 = n.args[0]
                if isinstance(a0, ast.Constant) and a0.value in (0, "/dev/stdin"):
                    found.append(f"open({a0.value!r})")
            # bare input()
            if isinstance(f, ast.Name) and f.id == "input":
                found.append("input()")
        # import fileinput -- reads stdin when argv is empty
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "fileinput":
                    found.append("import fileinput")
        if isinstance(n, ast.ImportFrom) and n.module == "fileinput":
            found.append("from fileinput import ...")
        # from sys import stdin
        if isinstance(n, ast.ImportFrom) and n.module == "sys":
            for a in n.names:
                if a.name == "stdin":
                    found.append("from sys import stdin")
    return found


def routes_through_hookio(src):
    """Does this script actually CALL the shared reader? By AST, not substring.

    `assertIn("hookio", src)` was the old check, in a change whose entire
    subject was substrings standing in for behaviour: a script mentioning
    `hookio` only in a comment passed it. This asks for a real call to
    `read_json_stdin`.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "read_json_stdin":
                return True
            if isinstance(f, ast.Name) and f.id == "read_json_stdin":
                return True
    return False


# --------------------------------------------------------------- the sandbox
def _sandbox():
    """A throwaway copy of the script tree.

    Every hook here derives its root and its state files from `__file__`, so
    running the copy relocates the session registry, the mail bus, the question
    file, the board-guard stamp, the transcripts and the vault paths into the
    temp dir. Nothing this file runs can touch the live tree.

    ONE PER RUN, NOT ONE PER FILE, and the reason is not tidiness. These cases
    execute concurrently (see `_sweep`), and the hooks append to their own
    state files -- a shared sandbox would have them racing each other on
    `.sessions.jsonl` and `.session-mail.jsonl`. The race would not usually
    fail the assertion, which is worse than if it did: an intermittent test is
    how this project lost a whole afternoon to `test_see_page`. The whole tree
    is 260 KB, so a private copy costs less than the flake would.
    """
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-hooks-"))
    for d in ("vault-tools", "voice-line"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
        for f in (ROOT / d).glob("*.py"):
            shutil.copy2(f, tmp / d / f.name)
    # The directories the hooks expect to find under their root. Empty is
    # fine: what is under test is that they RETURN, not that they succeed.
    (tmp / "Jarvis-brain" / "06 - Email Inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "Jarvis Visual" / "transcripts").mkdir(parents=True, exist_ok=True)
    (tmp / "Jarvis-brain" / "Active Priorities.md").write_text(
        "# Active Priorities\n\n### Open Tasks\n")
    return tmp


def _sweep(payload, close_writer):
    """Run EVERY deployed invocation under one stdin condition, concurrently.

    Serially this file cost 92 seconds -- ten invocations times a 5s budget,
    twice over. A gate that slow is a gate somebody starts skipping, and the
    runs are independent subprocesses with private sandboxes, so there is no
    reason to pay it. Wall-clock is now the slowest single hook, not the sum.

    Returns {label: Ran}. The configured timeout travels with the result so
    the callers can assert a MARGIN against the hook's own deployed contract
    rather than against a number written here.
    """
    from concurrent.futures import ThreadPoolExecutor
    work = every_invocation()

    def one(item):
        label, rel, argv, timeout = item
        box = _sandbox()
        try:
            r = _run(box, rel, argv, payload, close_writer, _deadline(timeout))
            return label, r._replace(timeout=timeout)
        finally:
            shutil.rmtree(box, ignore_errors=True)

    with ThreadPoolExecutor(max_workers=min(8, len(work) or 1)) as pool:
        return dict(pool.map(one, work))


# What one deployed invocation actually did. `rc` and `stderr` are here
# because leaving them out is how this file spent a day claiming to be a gate
# while testing nothing -- see `_assert_the_hook_ACTUALLY_RAN`.
Ran = collections.namedtuple("Ran", "returned elapsed timeout rc stderr")

# The signatures of a child that never got as far as running the hook. The
# test-adversary proved all three read as a clean pass while `_run` returned
# only "did communicate() come back":
#   * no script at the path        -> "can't open file", rc 2
#   * a hook that crashes          -> "Traceback", rc 1
#   * a .sh hook launched under python3 -> "SyntaxError", rc 1
# Matched on stderr as well as on rc, because rc alone cannot see a crash that
# something downstream swallows into an exit 0.
_DID_NOT_RUN = ("can't open file", "Traceback", "SyntaxError",
                "ModuleNotFoundError", "No such file or directory")


def _run(box, rel, argv, payload, close_writer, timeout):
    """A `Ran` for the real deployed command line, in a subprocess.

    A subprocess because a parent that blocks cannot report that it blocked --
    which is why every in-process test of these hooks passed while all six real
    invocations hung.

    The kill deadline is the hook's OWN CONFIGURED TIMEOUT, not a number picked
    here. That is the actual deployed contract: past it the harness kills the
    hook anyway, so a hook that needs longer is broken whatever this file says.

    IT RETURNS THE EXIT CODE AND STDERR, AND THAT IS THE POINT OF THIS
    FUNCTION'S LAST REVISION. It used to discard both and hand back only
    `True` -- so "the process came back" was satisfied by a process that never
    ran the hook at all. The test-adversary proved it three ways in one
    sitting: with no script copied into the sandbox the whole file returned
    `Ran 25 tests / OK` in 0.4s against 21s for a real run, and every hook
    exiting 2 -- which is the harness's actual BLOCKING code, in a file called
    test_hooks_never_block -- was equally invisible. That is verbatim the flaw
    this file's own docstring condemns at the top: a child that dies in twenty
    milliseconds satisfies an `assertTrue(returned)`. The mechanism changed
    from a named helper to a real subprocess and carried the flaw across.
    """
    script = box / rel
    cmd = [sys.executable, str(script)] + list(argv)
    r, w = os.pipe()
    writer = None
    try:
        started = time.monotonic()
        p = subprocess.Popen(cmd, stdin=r, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=str(box))

        # THE PAYLOAD GOES IN ON A THREAD, AFTER THE CHILD IS UP -- RED-PEN
        # FINDING 7, and the adversary named it before that. Writing first, as
        # this did, works only while the payload is smaller than the 64 KB
        # pipe buffer, because nothing is reading the other end yet. The first
        # person to add the obvious "an oversized payload is refused" case
        # would have deadlocked THE TEST PROCESS -- inside the one file whose
        # whole subject is processes that never return. Four lines is cheaper
        # than that joke landing on somebody.
        def _feed():
            try:
                if payload is not None:
                    os.write(w, payload)
            except OSError:
                pass
            finally:
                if close_writer:
                    try:
                        os.close(w)
                    except OSError:
                        pass

        writer = threading.Thread(target=_feed, daemon=True)
        writer.start()
        try:
            _out, err = p.communicate(timeout=timeout)
            return Ran(True, time.monotonic() - started, timeout,
                       p.returncode, (err or b"").decode(errors="replace"))
        except subprocess.TimeoutExpired:
            p.kill()
            _out, err = p.communicate()
            return Ran(False, time.monotonic() - started, timeout,
                       p.returncode, (err or b"").decode(errors="replace"))
    finally:
        if writer is not None:
            writer.join(timeout=1.0)
        os.close(r)
        if not close_writer:
            try:
                os.close(w)
            except OSError:
                pass


# The floor under a missing `timeout` key. A hook with no timeout in its config
# is a separate defect with its own assertion; this only keeps the runner from
# waiting forever while that assertion is the one reporting it.
FALLBACK_TIMEOUT = 15


def _deadline(t):
    return FALLBACK_TIMEOUT if t is None else t


class TestDiscovery(unittest.TestCase):

    def test_the_discovered_set_is_EXACTLY_the_named_list(self):
        # Equality, not a count floor. `assertGreaterEqual(len(...), 4)` let
        # six become four in silence, and dropping hooks is precisely what a
        # tokeniser bug does.
        self.assertEqual(discovered_scripts(), sorted(EXPECTED_HOOK_SCRIPTS))

    def test_every_hook_script_exists(self):
        for rel in discovered_scripts():
            with self.subTest(hook=rel):
                self.assertTrue((ROOT / rel).is_file(),
                                f"a settings file wires {rel}, which is not here")

    def test_the_config_sweep_ACTUALLY_READS_the_deployed_files(self):
        # My own injection round found this one too. `all_configs()` narrowed
        # to `[TEMPLATE]` and NOTHING went red: the template wires the same six
        # scripts, so `discovered_scripts()` was unchanged, and the
        # template-vs-deployed test below reads DEPLOYED directly rather than
        # through `all_configs`. So the file would have gone back to testing
        # the template alone -- the exact blindness the rewrite was for -- with
        # a full green suite. What runs is the deployed file; what is tested
        # has to be the deployed file.
        srcs = {p for p, _cfg in all_configs()}
        self.assertIn(TEMPLATE, srcs)
        for p in DEPLOYED:
            if p.is_file():
                self.assertIn(
                    p, srcs,
                    f"{p} exists on this machine and the sweep is not reading "
                    "it -- the timeouts and hooks actually in force are "
                    "outside the gate")

    def test_a_DEPLOYED_config_cannot_simply_VANISH(self):
        """THE TEST-ADVERSARY'S P1, and it is the ugliest shape there is: the
        gate was STRICTLY WEAKER AGAINST THE STRICTLY WORSE FAULT.

        Reproduced by it and again by me, on the live tree. Delete ONE hook
        group from one deployed settings.json -> RED 1. Delete BOTH ENTIRE
        DEPLOYED FILES -> `Ran 33 tests / OK`. `all_configs()` is
        `if p.is_file()`, so a config that is not there is not checked, and
        every per-config test simply has nothing to say. No hook is wired
        anywhere on the machine and the suite calls it green. That is commit
        `b0a6e46` -- the installer reporting "already configured" while
        delivering nothing -- reproduced inside the test written to prevent it.

        WHY THIS IS NOT JUST `assertTrue(p.is_file())`, which is what the
        finding asked for. Both deployed files are gitignored: they exist only
        after `install.sh` has run. A bare existence assertion would go red on
        every fresh clone, and -- far worse for this project's actual practice
        -- on every `git archive` sandbox, which is how both agents run their
        injection rounds. A gate that is red in every sandbox poisons every
        baseline and gets switched off within a day.

        So the question asked here is not "should these exist" but "HAS THIS
        TREE EVER HAD WORKING HOOKS". The state files in `HOOK_STATE_MARKERS`
        are written BY the hooks and are gitignored, so a clone and a sandbox
        have none of them and are correctly silent, while any tree where a
        hook has ever fired must still be wired. On this machine that is the
        deletion case exactly, and it is red.
        """
        ran_here = [m for m in HOOK_STATE_MARKERS if (ROOT / m).exists()]
        if not ran_here:
            self.skipTest("no hook has ever run against this tree -- a fresh "
                          "clone or a sandbox, where the deployed configs are "
                          "legitimately absent")
        for p in DEPLOYED:
            with self.subTest(settings=str(p.relative_to(ROOT))):
                self.assertTrue(
                    p.is_file(),
                    f"{p.relative_to(ROOT)} is GONE, and hooks have run "
                    f"against this tree ({', '.join(ran_here)} exist). Every "
                    "per-config check in this file is `if p.is_file()`, so a "
                    "deleted config is not a failure, it is silence -- one "
                    "group deleted is red and the whole file deleted was "
                    "green. Run ./install.sh")

    def test_the_template_and_both_deployed_files_wire_the_same_scripts(self):
        # The template is not the deployment. A hook hand-added to a deployed
        # file and never put back in the template was invisible to the old
        # discovery; this makes that drift red instead of silent.
        tmpl = {w.rel for w in hook_invocations(json.loads(TEMPLATE.read_text()))}
        for p in DEPLOYED:
            if not p.is_file():
                continue
            with self.subTest(settings=str(p.relative_to(ROOT))):
                got = {w.rel for w in hook_invocations(json.loads(p.read_text()))}
                self.assertEqual(got, tmpl)

    def test_discovery_survives_a_QUOTED_path_containing_a_space(self):
        # The shape every hook under `Jarvis Visual/` is forced into, and the
        # one that silently vanished. Proven against a synthetic config so it
        # does not depend on anybody having written such a hook yet.
        cfg = {"hooks": {"Stop": [{"hooks": [
            {"command": f'python3 "{_ROOT_MARKER}/Jarvis Visual/tools/newhook.py" stop',
             "timeout": 15}]}]}}
        self.assertEqual(_triples(cfg),
                         [("Jarvis Visual/tools/newhook.py", ("stop",), 15)])

    def test_discovery_is_not_limited_to_dot_py(self):
        # The title says EVERY deployed hook. `.endswith(".py")` said otherwise.
        cfg = {"hooks": {"Stop": [{"hooks": [
            {"command": f"bash {_ROOT_MARKER}/vault-tools/hang-hook.sh",
             "timeout": 15}]}]}}
        self.assertEqual(_triples(cfg),
                         [("vault-tools/hang-hook.sh", (), 15)])

    def test_discovery_reads_an_absolute_path_as_written_in_a_deployed_file(self):
        # A rendered settings.json carries no {{JARVIS_ROOT}} at all.
        cfg = {"hooks": {"Stop": [{"hooks": [
            {"command": f"python3 {ROOT}/voice-line/question_hook.py notify",
             "timeout": 10}]}]}}
        self.assertEqual(_triples(cfg),
                         [("voice-line/question_hook.py", ("notify",), 10)])

    def test_an_absolute_path_reached_THROUGH_A_SYMLINK_still_resolves(self):
        # THE REGRESSION TEST FOR THE BUG MY OWN INJECTION ROUND FOUND.
        # `_script_rel` used to compare string prefixes against a resolved
        # ROOT, so any symlink in the path made every deployed hook invisible
        # -- silently, which is the worst way for a discovery test to fail.
        # `/var` -> `/private/var` on macOS is exactly this shape and it is
        # what turned the harness's own baseline red.
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-symlink-"))
        try:
            link = tmp / "jarvis"
            os.symlink(ROOT, link)
            cfg = {"hooks": {"Stop": [{"hooks": [
                {"command": f"python3 {link}/voice-line/question_hook.py stop",
                 "timeout": 15}]}]}}
            self.assertEqual(_triples(cfg),
                             [("voice-line/question_hook.py", ("stop",), 15)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_an_absolute_path_OUTSIDE_the_repo_is_not_mistaken_for_a_hook(self):
        # The other side of resolving: `/usr/bin/python3` is an absolute token
        # too. Widening the match must not start treating the interpreter as
        # the script.
        cfg = {"hooks": {"Stop": [{"hooks": [
            {"command": f"/usr/bin/python3 {ROOT}/vault-tools/board-guard.py",
             "timeout": 15}]}]}}
        self.assertEqual(_triples(cfg),
                         [("vault-tools/board-guard.py", (), 15)])

    def test_every_hook_carries_a_timeout_in_every_config(self):
        for p, cfg in all_configs():
            for w in hook_invocations(cfg):
                with self.subTest(settings=p.name, hook=w.rel):
                    self.assertIsNotNone(
                        w.timeout, f"{w.rel} is deployed with nothing bounding it")


class TestNothingHereIsUNTRACKED(unittest.TestCase):
    """A file the suite depends on that git does not have is not shipped.

    THIS IS THE CLASS THE REVIEWER CLOSED ONE FILE OVER, ONE DAY EARLIER, and
    it reopened immediately: `vault-tools/render_settings.py` was untracked
    while `install.sh` shelled out to it, so on a fresh clone the installer
    exited 1 having written no settings at all -- with the whole suite green,
    because `.is_file()` is satisfied by an untracked file forever. The remedy
    was written that same night in `test_board_guard.py` and then not applied
    here, and `test_question_hook.py` was untracked when it was written today.

    So it is asserted rather than remembered, for the hook scripts AND for the
    test files that guard them.
    """

    def _tracked(self, path):
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=str(ROOT), capture_output=True)
        return r.returncode == 0

    def test_every_deployed_hook_script_is_tracked_by_git(self):
        for rel in discovered_scripts():
            if not (ROOT / rel).is_file():
                continue
            with self.subTest(hook=rel):
                self.assertTrue(
                    self._tracked(ROOT / rel),
                    f"{rel} is wired as a hook and is NOT tracked -- a fresh "
                    "clone gets a settings file pointing at a missing script")

    def test_every_test_file_in_this_directory_is_tracked_by_git(self):
        here = Path(__file__).resolve().parent
        for f in sorted(here.glob("test_*.py")) + sorted(here.glob("test_*.js")):
            with self.subTest(test=f.name):
                self.assertTrue(
                    self._tracked(f),
                    f"{f.name} is untracked -- it does not exist on a fresh "
                    "clone, so the gate it provides ships to nobody")

    def test_the_shared_reader_and_the_template_are_tracked(self):
        for p in (ROOT / "vault-tools" / "hookio.py", TEMPLATE):
            with self.subTest(path=p.name):
                self.assertTrue(self._tracked(p), f"{p} is untracked")


class TestNoRawBlockingRead(unittest.TestCase):
    """THE STATIC CHECKS IN THIS CLASS ARE NOT THE GATE. Say it plainly.

    RED-PEN FINDING 4 from the voice line: `test_a_hook_that_takes_a_payload_
    uses_the_shared_reader_for_real` skips any script that does not contain the
    word "hookio" -- so a hook that reads stdin by hand and never names the
    module is passed over by it, which is EXACTLY the shape all three hooks in
    `69fb519` had before they were fixed. And no AST net catches every spelling
    of a blocking read; `sys.stdin.buffer.read()` walked past this one until
    finding 3, and an alias (`_s = sys.stdin; _s.read()`) still does.

    So these are a fast, readable tripwire that names the bug when it takes its
    usual shape. **`TestEveryDeployedHookReturns` is the gate**, because a hook
    that reads fd 0 by any spelling at all HANGS, and the sweep runs it. A
    static check that oversells itself is how the last version of this file got
    trusted; this one is allowed to be partial as long as it says so.
    """

    def test_no_hook_makes_a_raw_blocking_stdin_call_by_ANY_spelling(self):
        for rel in discovered_scripts():
            path = ROOT / rel
            if not path.is_file() or path.suffix != ".py":
                continue
            with self.subTest(hook=rel):
                self.assertEqual(
                    blocking_stdin_spellings(path.read_text()), [],
                    f"{rel} reads fd 0 directly -- this is the bug five files "
                    "have now had, and os.read(0, ...) is the spelling that "
                    "proved the previous version of this test hollow")

    def test_a_hook_that_takes_a_payload_uses_the_shared_reader_for_real(self):
        # Not `assertIn("hookio", src)` -- that passes on a comment. A hook is
        # allowed to read no stdin at all (brief-check.py deliberately does
        # not); what it may not do is read it by hand.
        for rel in discovered_scripts():
            path = ROOT / rel
            if not path.is_file() or path.suffix != ".py":
                continue
            src = path.read_text()
            if "hookio" not in src:
                continue          # claims no payload; the test above binds it
            with self.subTest(hook=rel):
                self.assertTrue(
                    routes_through_hookio(src),
                    f"{rel} names hookio but never calls read_json_stdin")


class TestEveryDeployedHookReturns(unittest.TestCase):
    """No gate. Every discovered invocation, whether or not it reads stdin.

    A hook that never opens stdin passes these in milliseconds, and that is the
    point: the previous version decided what to test by looking for the
    symptom, so curing the symptom removed the test.
    """

    PAYLOAD = json.dumps({
        "session_id": "abcdef12",
        "transcript_path": "/tmp/does-not-exist.jsonl",
        "tool_name": "Read",
        "hook_event_name": "Stop",
    }).encode()

    def _swept(self, payload, close_writer):
        """`_sweep`, with the vacuity check its own name has always promised.

        THE HOLE THIS CLOSES. `test_the_sweep_actually_covers_every_deployed_
        invocation` says in its docstring: "Without it a `_sweep` that quietly
        returned nothing would make every test below pass by testing zero
        hooks." It does not check that. Red-pen findings 5 and 6 moved it off
        `_sweep` and onto `every_invocation()` for speed, and in doing so
        deleted the guard it is named for. Two measurements, kept separate
        because merging them is a mistake this file already made once (see
        `test_an_EMPTY_sweep_is_REFUSED`): the TEST-ADVERSARY injected
        `work = []` against the 25-test revision and got `Ran 25 tests in
        0.190s / OK`; I repeated it against the 30-test revision and got
        `Ran 30 tests in 0.218s / OK`. Both against 21 seconds for a real run,
        and nothing anywhere said so.

        PINNED AGAINST `EXPECTED_INVOCATIONS`, NOT AGAINST `every_invocation()`,
        and that is the whole design. `_sweep` BUILDS its work from
        `every_invocation()`, so checking one against the other compares a
        function with itself: break the function and both sides move together.
        That is exactly the criticism the adversary made of my own injection 13
        -- it mutated the function the asserting test reads, so it proved
        nothing about the claim on its label. The named tuple is a reviewed
        decision that cannot move by accident, which is what makes it evidence.
        """
        results = _sweep(payload, close_writer)
        expected = {f"{rel} {' '.join(argv)}".strip()
                    for rel, argv, _t in EXPECTED_INVOCATIONS}
        self.assertEqual(
            set(results), expected,
            "the sweep did not run the invocations this file pins. An EMPTY "
            "or short sweep makes every assertion below vacuous -- they "
            "iterate over the results, so zero results is zero assertions and "
            "a green suite that measured nothing")
        return results

    def _assert_the_hook_ACTUALLY_RAN(self, label, r):
        """`returned` is not evidence. Called by FOUR of the five sweeps, and
        deliberately NOT first.

        Both of those numbers were wrong in the first draft -- it claimed all
        five, and claimed to run first -- so they are stated exactly here. It
        runs in the four sweeps that iterate results; `assertTrue(returned)`
        precedes it in each, because a killed child carries rc -9 and would
        otherwise mask the one message this file exists to print (see the
        comment in the SILENT test).

        THE FIFTH SWEEP DOES NOT CALL IT, AND THAT IS A KNOWN GAP, NOT A
        DESIGN. `test_NOTHING_IN_THE_LIVE_TREE_IS_WRITTEN_BY_A_FULL_SWEEP`
        discards its results, so under the adversary's empty-sandbox proof it
        still passes -- a hook that never ran writes nothing to the live tree
        either. That is the one test this file calls "the only test here that
        can fail for the reason it exists", so the gap is carded rather than
        papered over.

        THE HOLE THIS CLOSES, proven by the test-adversary against the version
        that had only `assertTrue(returned)`:

          * copy no hook scripts into the sandbox -> every child dies on
            "can't open file" in ~20ms -> `Ran 25 tests / OK` in 0.4s
          * make every hook `sys.exit(2)` with stderr -- the harness's actual
            BLOCKING code -> `Ran 25 tests / OK` in 0.5s
          * wire a `.sh` hook, which `_run` launches under python3 -> it dies
            on a SyntaxError in 20ms -> every behavioural test passes

        All three are a process that came back without running the hook, which
        is the exact substitution the top of this file was rewritten to end:
        the previous version failed on "this module has no function of that
        name" and never once on "it blocked". A gate that cannot tell a hook
        that ran from a hook that never started is not measuring the property
        it is named for.

        WHAT WAS MEASURED, AND WHAT WAS NOT -- the first draft of this
        paragraph overstated both halves and the reviewer was right to say so.
        All TEN DEPLOYED INVOCATIONS were driven before this assertion was
        written: every one exited 0 with empty stderr. That is a measurement of
        ten invocations under this class's payload, and it is the whole basis
        for `assertEqual(r.rc, 0)`.

        It is NOT a design guarantee about the six scripts, which is what the
        first draft claimed. Five of them do carry a blanket guard
        (`board-guard.py:369`, `brief-check.py:141`, `question_hook.py:145`,
        `session_mail.py:735`, `session_registry.py:609`). `session_record.py`
        does NOT: its `main()` calls `record(path)` unguarded, so it exits 0
        here because this class's payload names a transcript that does not
        exist, not because it cannot fail. Nor is stderr unused by the six as
        written -- `session_mail.py` and `session_registry.py` both write to it
        on paths these invocations do not reach. `board-guard.py:381` and
        `brief-check.py:153` emit `hookSpecificOutput` on STDOUT, which is why
        stdout is not asserted on.

        stderr is matched on crash signatures, NOT asserted empty, so that an
        unrelated DeprecationWarning from some future interpreter cannot turn
        this suite red -- an intermittent gate is what this file spends its
        `_sandbox` docstring forbidding.
        """
        self.assertEqual(
            r.rc, 0,
            f"{label} exited {r.rc}, not 0. A hook that exits non-zero has not "
            "run to completion -- and exit 2 is the harness's BLOCKING code, "
            "which is the one thing this file is named after")
        for sig in _DID_NOT_RUN:
            self.assertNotIn(
                sig, r.stderr,
                f"{label} never ran the hook -- its stderr carries {sig!r}. "
                "The process came back, which is not the same thing, and "
                "'it came back' is precisely what used to be asserted here")

    def test_NOTHING_IN_THE_LIVE_TREE_IS_WRITTEN_BY_A_FULL_SWEEP(self):
        """RED-PEN FINDING 1, and it was the right call: the old version of
        this test asserted the sandbox PATH was not inside ROOT. That is a
        statement about a string, and it is the same proxy-for-property
        substitution this whole file exists to condemn.

        The docstring's claim is that nothing here can touch the live tree.
        That rests on every hook deriving every path from `__file__` -- true
        today, and false the first time one resolves something from `cwd`, an
        env var, or an absolute constant. It is not hypothetical: on 08-14 a
        fixture wrote a dead pid into the live `voice-line/.activity.json`,
        which the HUD reads and which drops its oldest row at 12, so a suite
        run could evict a genuinely live session from Serge's screen.

        So this stamps the real state files and runs the real sweep against
        them. It is the only test here that can fail for the reason it exists.
        """
        # THE LIST WAS WRONG IN BOTH DIRECTIONS (reviewer, 2026-08-15; both
        # halves reproduced). Fixed 2026-08-21.
        #
        # DROPPED -- Active Priorities.md. NO HOOK WRITES IT. board-guard.py
        # only READS it, so the file changes whenever any session moves a
        # card, and this test then blamed the sandbox for something no hook
        # did. It fired on exactly that at 09:52 on 08-15, and a test that
        # cries wolf at honest work is worse than no test: it teaches the
        # next person to ignore a red.
        #
        # ADDED -- the terminal transcript. session_record.py appends to it
        # on EVERY Stop hook, which is the most frequent write any hook in
        # this repo performs. It was unwatched while .terminal-watermarks
        # -- written by the same flow -- was watched, so the list held the
        # bookkeeping and missed the payload.
        #
        # The rule the list now follows, so the next addition is decidable
        # rather than a matter of taste: WATCH WHAT A HOOK WRITES, and
        # nothing else. A file a hook merely reads cannot be evidence of
        # containment, because anything else on the machine may change it.
        today = __import__("datetime").date.today().isoformat()
        watched = [
            ROOT / "voice-line" / ".sessions.jsonl",
            ROOT / "voice-line" / ".session-mail.jsonl",
            ROOT / "voice-line" / ".activity.json",
            ROOT / "voice-line" / ".voice_question",
            ROOT / "voice-line" / ".board-guard.json",
            ROOT / "Jarvis Visual" / "transcripts" / ".terminal-watermarks.json",
            ROOT / "Jarvis Visual" / "transcripts" / f"{today}-terminal.md",
            ROOT / "Jarvis Visual" / "transcripts" / f"{today}.md",
        ]

        def stamp():
            out = {}
            for p in watched:
                try:
                    st = p.stat()
                    out[str(p)] = (st.st_mtime_ns, st.st_size)
                except FileNotFoundError:
                    out[str(p)] = None
            return out

        before = stamp()
        self._swept(self.PAYLOAD, True)
        after = stamp()
        for key in before:
            with self.subTest(state=Path(key).name):
                self.assertEqual(
                    before[key], after[key],
                    f"a hook sweep modified the LIVE {Path(key).name} -- the "
                    "sandbox is not containing it, and a test that writes "
                    "production state is a bug this project has already had")

    def test_the_sweep_actually_covers_every_deployed_invocation(self):
        # The vacuity guard for the behavioural half. Without it a `_sweep`
        # that quietly returned nothing would make every test below pass by
        # testing zero hooks -- precisely how the previous version of this file
        # failed, one level up.
        #
        # RED-PEN FINDINGS 5 AND 6, both right. It used to run a FULL sweep --
        # ten sandboxes, ten subprocesses -- purely to count keys, so the one
        # test whose job is to say "the sweep was not empty" went red for
        # reasons that had nothing to do with emptiness, and cost a fifth fan
        # out in a file that went concurrent because 92 seconds is a gate
        # people skip. And it compared against a bare `10`, a magic number
        # sitting beside a named list it could have been derived from.
        self.assertEqual(
            sorted((rel, tuple(argv)) for _l, rel, argv, _t in every_invocation()),
            sorted((rel, argv) for rel, argv, _t in EXPECTED_INVOCATIONS))

    def test_EVERY_config_wires_the_WHOLE_set_not_just_the_union(self):
        """THE REVIEWER'S P1, and the one hole a green 16/16 round missed.

        Every other check here is against a UNION across the template and both
        deployed files, or against the script set alone. Neither can see a
        whole invocation group deleted from a deployed config while the
        template still names it and the script stays wired for its other modes.
        The REVIEWER found it by reading, and checked it IN MEMORY rather than
        by running anything: with the `Notification` group removed, the script
        sets still matched and the union still equalled `EXPECTED_INVOCATIONS`.
        It reported no test count and never claimed one. I then ran it, which
        is a different act and belongs to a different name: deleting that group
        from BOTH deployed files left the file at `Ran 25 tests / OK`.

        What that costs is not abstract and it is not a test-only concern:
        `notify` is the hook that writes Serge's permission banner. Unwired, he
        gets no banner on any session -- which is exactly the signal that
        failed to reach him at 08:45 today, when the brain sat blocked on an
        unanswered approval with no page open to render it. The failure mode
        this closes sits directly beside the one that already bit him once.

        Held per config, by EQUALITY, on the WHOLE wiring. A config is the
        thing that actually runs; the union is a convenience for the sweep.

        AND `event` AND `matcher` ARE IN THE COMPARISON -- the reviewer's
        second pass, and the reason its first version did not close the class
        it was named for. It pinned (script, argv, timeout), so it caught the
        `Notification` group being DELETED and not the same group being MOVED:
        put `question_hook.py notify` on `SessionEnd` instead and every field
        it compared was identical. Serge's permission banner would never fire
        again and this test -- the one written to prevent exactly that -- would
        be green. Narrowing board-guard's matcher to `Edit` was equally
        invisible, and that is the guard that watches Write and Bash.
        """
        expected = sorted(EXPECTED_WIRING)
        for p, cfg in all_configs():
            with self.subTest(settings=str(p.relative_to(ROOT))):
                wired = hook_invocations(cfg)
                got = sorted((w.event, w.matcher, w.interp, w.rel, w.argv,
                              w.timeout) for w in wired)
                self.assertEqual(
                    got, expected,
                    f"{p.relative_to(ROOT)} does not wire the reviewed set. A "
                    "group deleted -- or MOVED to another event -- is "
                    "invisible to every other test in this file: the script "
                    "set does not move and the invocation check is a union "
                    "the template keeps filling")
                for w in wired:
                    self.assertEqual(
                        w.kind, EXPECTED_KIND,
                        f"{w.rel} is wired as {w.kind!r} in "
                        f"{p.relative_to(ROOT)} -- Claude Code runs 'command' "
                        "hooks, so any other type is a hook that never fires "
                        "while every other field still reads correctly")

    def test_a_SILENT_stdin_returns_every_hook_WELL_INSIDE_its_timeout(self):
        # RED-PEN FINDING 2, and it is the one that mattered most: the kill
        # deadline WAS the hook's deployed timeout exactly, so a hook returning
        # at 9.9s under a 10s timeout passed here and is killed in production
        # by any startup jitter, cold import or loaded machine. A margin was
        # applied to the fast path and none at all to the slow one -- the very
        # path this file was rewritten for. The adversary's prescription said
        # 0.6 of the deployed timeout; that is what is asserted now.
        for label, r in self._swept(None, False).items():
            returned, elapsed, timeout = r.returned, r.elapsed, r.timeout
            budget = MARGIN * _deadline(timeout)
            with self.subTest(hook=label):
                # THE HANG ASSERTION GOES FIRST, and the order is deliberate.
                # A killed child carries rc -9, so putting the ran-clean check
                # above this would replace the one message this whole file
                # exists to print -- "it hangs every turn it fires" -- with
                # "exited -9, not 0". The best diagnosis must win the race to
                # report.
                self.assertTrue(
                    returned,
                    f"{label} never returned on a silent stdin within its "
                    "deployed timeout -- it hangs every turn it fires")
                self._assert_the_hook_ACTUALLY_RAN(label, r)
                self.assertLess(
                    elapsed, budget,
                    f"{label} took {elapsed:.2f}s of its {_deadline(timeout)}s "
                    f"deployed timeout. Returning before the axe falls is not "
                    "enough -- it has to leave room for a cold start on a "
                    "loaded machine, or production kills it and this stays green")

    def test_a_COMPLETE_payload_on_a_pipe_NOBODY_CLOSES_returns_every_hook(self):
        # The half `isatty` could never have caught, and the half the first fix
        # for session_record.py got wrong: read/json.load run to EOF, so a
        # perfectly good payload hangs just as hard if the writer holds on.
        for label, r in self._swept(self.PAYLOAD, False).items():
            returned, elapsed = r.returned, r.elapsed
            with self.subTest(hook=label):
                self.assertTrue(
                    returned,
                    f"{label} never returned on a COMPLETE payload whose "
                    "writer stayed open")
                self._assert_the_hook_ACTUALLY_RAN(label, r)
                # AND IT MUST RETURN AT ONCE, NOT AT THE DEADLINE. My own
                # injection round found this hole: I removed hookio's
                # early return on a complete value, so every read sat out the
                # whole budget -- and every test still passed, because a
                # CLOSED writer sends EOF and finishes fast regardless. This
                # is the only case that can tell the difference, and it is
                # exactly the case the module exists for: `raw_decode` answers
                # "is there a whole value at the front yet", so a complete
                # payload must not wait on a close that may never come. Five
                # seconds on every hook of every turn, invisible to a gate
                # that only asks whether it came back.
                self.assertLess(
                    elapsed, 3.0,
                    f"{label} took {elapsed:.2f}s on a COMPLETE payload -- it "
                    "is waiting out the budget instead of returning as soon "
                    "as the value has arrived")

    def test_an_ORDINARY_hook_call_returns_every_hook_promptly(self):
        for label, r in self._swept(self.PAYLOAD, True).items():
            returned, elapsed = r.returned, r.elapsed
            with self.subTest(hook=label):
                self.assertTrue(returned, f"{label} hung on a normal payload")
                self._assert_the_hook_ACTUALLY_RAN(label, r)
                # The ordinary path must be FAST, not merely bounded. Without
                # this, a hook that always sat out the full budget would pass
                # every test above while costing five seconds of every turn.
                self.assertLess(
                    elapsed, 3.0,
                    f"{label} took {elapsed:.2f}s on an ordinary closed "
                    "payload -- the budget is a ceiling for a silent pipe, "
                    "not the cost of a normal call")

    def test_a_HALF_written_payload_on_an_open_pipe_still_returns(self):
        # The shape that is neither silent nor complete: a writer that started
        # and stopped. `raw_decode` must never spin on it.
        for label, r in self._swept(b'{"session_id": "abc', False).items():
            with self.subTest(hook=label):
                self.assertTrue(r.returned,
                                f"{label} hung on a half-written payload")
                self._assert_the_hook_ACTUALLY_RAN(label, r)


class TestASweepCanTellARanHookFromADeadOne(unittest.TestCase):
    """The gate on the gate. Without these, `_run` can go back to returning a
    bare `True` and every test above passes while measuring nothing.

    This class exists because the test-adversary demonstrated exactly that:
    with the sandbox copying no hook scripts, the whole file returned
    `Ran 25 tests / OK` in 0.4 seconds against 21 for a real run, and nothing
    anywhere said so. Each case below is one of its three proofs, turned into
    an assertion instead of a report.
    """

    def _one(self, body, argv=(), payload=b"{}", name="probe.py"):
        box = Path(tempfile.mkdtemp(prefix="jarvis-ranprobe-"))
        try:
            (box / name).write_text(body)
            return _run(box, name, argv, payload, True, 15)
        finally:
            shutil.rmtree(box, ignore_errors=True)

    def test_a_hook_that_exits_0_silently_is_reported_as_having_RUN(self):
        # The control. Without it the three below could pass by `_run`
        # rejecting everything, which is a gate that has stopped discriminating.
        r = self._one("import sys\nsys.exit(0)\n")
        self.assertTrue(r.returned)
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.stderr, "")

    def test_a_MISSING_script_is_NOT_reported_as_a_clean_run(self):
        # The adversary's proof (b): neuter `_sandbox`'s copy loop and every
        # child dies on "can't open file" in ~20ms, `returned=True`, all five
        # behavioural tests green. `returned` is not evidence.
        box = Path(tempfile.mkdtemp(prefix="jarvis-ranprobe-"))
        try:
            r = _run(box, "not-copied-at-all.py", (), b"{}", True, 15)
        finally:
            shutil.rmtree(box, ignore_errors=True)
        self.assertTrue(r.returned, "the interpreter itself did come back -- "
                                    "which is the whole trap")
        self.assertNotEqual(r.rc, 0)
        self.assertTrue(any(s in r.stderr for s in _DID_NOT_RUN), r.stderr)

    def test_a_hook_that_EXITS_2_is_NOT_reported_as_a_clean_run(self):
        # The adversary's proof (a). Exit 2 is the harness's BLOCKING code:
        # stderr is fed back to the model and the tool call is refused. A file
        # called test_hooks_never_block could not see it.
        r = self._one("import sys\n"
                      "print('hook refused', file=sys.stderr)\n"
                      "sys.exit(2)\n")
        self.assertTrue(r.returned)
        self.assertEqual(r.rc, 2)

    def test_a_hook_that_CRASHES_is_NOT_reported_as_a_clean_run(self):
        # "Fails to nothing and looks installed" -- the shape this project has
        # now been bitten by five times.
        r = self._one("raise RuntimeError('boom')\n")
        self.assertTrue(r.returned)
        self.assertNotEqual(r.rc, 0)
        self.assertIn("Traceback", r.stderr)

    def test_an_EMPTY_sweep_is_REFUSED_rather_than_passing_vacuously(self):
        """The guard on the vacuity guard, and it is why `_swept` exists.

        Proven red before it was accepted. MY OWN measurement, named as mine
        because the first draft of this file attributed it to the adversary:
        with `work = []` injected into `_sweep`, the 30-test revision returned
        `Ran 30 tests in 0.218s / OK`. The adversary's independent run of the
        same injection, one revision earlier, was `Ran 25 tests in 0.190s`. Every
        behavioural test ITERATES over the sweep, so zero results is zero
        assertions and a green suite that measured nothing -- the same shape as
        the original bug, one level up.

        Driven by substituting `_sweep` rather than by running one, because the
        property is about what the callers do with an empty result, and paying
        a real 21-second fan-out to prove it would be the very cost that made
        somebody move this check off the sweep in the first place.
        """
        case = TestEveryDeployedHookReturns(
            "test_an_ORDINARY_hook_call_returns_every_hook_promptly")
        real = globals()["_sweep"]
        try:
            for bad, why in (({}, "an EMPTY sweep"),
                             ({"vault-tools/board-guard.py": Ran(True, 0.0, 15, 0, "")},
                              "a SHORT sweep")):
                globals()["_sweep"] = lambda *_a, **_k: bad
                with self.subTest(sweep=why):
                    with self.assertRaises(AssertionError):
                        case._swept(b"{}", True)
        finally:
            globals()["_sweep"] = real

    def test_the_coverage_pin_does_NOT_move_with_a_broken_every_invocation(self):
        # The adversary's criticism of my own injection 13: it mutated the
        # function the asserting test reads, so both sides moved together and
        # it proved nothing. `_swept` is pinned against EXPECTED_INVOCATIONS --
        # a reviewed decision -- precisely so a bug in `every_invocation()`
        # cannot hide itself.
        #
        # BY THE SYNTAX TREE, NOT BY SUBSTRING, and I earned that the hard way:
        # the first version of this test grepped `_swept`'s source, and
        # `_swept`'s own docstring NAMES `every_invocation()` while explaining
        # why it does not call it. So the prose tripped the guard and the file
        # went red on a correct implementation. That is verbatim the mistake
        # `blocking_stdin_spellings` documents at the top of this file -- "a
        # guard a docstring can trip is a guard that gets weakened until it
        # stops tripping" -- committed inside the change that quotes it.
        tree = ast.parse(Path(__file__).read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_swept")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        self.assertIn("EXPECTED_INVOCATIONS", names,
                      "_swept must pin against the reviewed named list")
        self.assertNotIn(
            "every_invocation", called,
            "_swept CALLS every_invocation(), which is the function _sweep "
            "builds its work from -- that compares a function with itself and "
            "cannot fail for the reason it exists")

    # The five sweeping tests, and the ONE that is exempt from the ran-check.
    # Named here rather than inferred, because an exemption nobody had to write
    # down is an exemption that spreads.
    _SWEEPERS = (
        "test_NOTHING_IN_THE_LIVE_TREE_IS_WRITTEN_BY_A_FULL_SWEEP",
        "test_a_SILENT_stdin_returns_every_hook_WELL_INSIDE_its_timeout",
        "test_a_COMPLETE_payload_on_a_pipe_NOBODY_CLOSES_returns_every_hook",
        "test_an_ORDINARY_hook_call_returns_every_hook_promptly",
        "test_a_HALF_written_payload_on_an_open_pipe_still_returns",
    )
    _EXEMPT_FROM_THE_RAN_CHECK = (
        # It discards its results -- it stamps the live state files instead --
        # so there is nothing for the ran-check to look at. Documented as a
        # known gap in `_assert_the_hook_ACTUALLY_RAN` rather than papered over.
        "test_NOTHING_IN_THE_LIVE_TREE_IS_WRITTEN_BY_A_FULL_SWEEP",
    )

    def test_every_sweeping_test_USES_the_two_helpers_that_make_it_a_gate(self):
        """THE TEST-ADVERSARY'S SECOND P1, in its own words: "You wrote an AST
        check that `_swept` must not call `every_invocation()` and no check
        that anything calls `_swept`. That is the same shape as the finding it
        was written for, one level out."

        It proved it by deletion rather than by argument. Everything the last
        revision added is removable and the file stays green at 33 tests:

          | delete all 4 `self._assert_the_hook_ACTUALLY_RAN` calls | OK 21.0s |
          | revert all 5 `self._swept(` back to `_sweep(`           | OK 20.9s |
          | both, plus `_sweep`'s `work = []`                       | OK 0.19s |

        That last line is the VERBATIM PRE-FIX STATE -- reachable, green, and
        measuring nothing -- because the seven tests guarding those helpers
        drive them DIRECTLY, with hand-built `Ran` tuples and a monkeypatched
        `_sweep`. They prove the helpers can discriminate. Nothing required
        anybody to call them. A gate whose guards are optional is decoration.

        So the callers are pinned by the syntax tree: a sweeping test must go
        through `_swept` (the vacuity check) and, unless it is named exempt
        above, through `_assert_the_hook_ACTUALLY_RAN` (the did-it-really-run
        check). By AST and not by substring for the reason this file keeps
        relearning -- prose naming a helper trips a grep, and this very
        docstring names both of them.
        """
        tree = ast.parse(Path(__file__).read_text())
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef)
                   and n.name == "TestEveryDeployedHookReturns")
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

        def calls(fn):
            return {n.func.attr for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

        # The set is pinned too: a sweeping test DELETED is the same loss as a
        # sweeping test weakened, and equality is what sees a drop.
        # `test_`-prefixed only: `_swept` itself calls `_sweep`, which is its
        # whole job, and the first run of this check duly flagged the helper it
        # exists to protect.
        sweeping = {name for name, fn in methods.items()
                    if name.startswith("test_")
                    and {"_sweep", "_swept"} & (
                        calls(fn) | {n.id for n in ast.walk(fn)
                                     if isinstance(n, ast.Name)})}
        self.assertEqual(
            sweeping, set(self._SWEEPERS),
            "the set of tests that run a sweep has changed -- add it to "
            "_SWEEPERS so its use of the two helpers is pinned, or say why "
            "it is gone")

        for name in self._SWEEPERS:
            fn = methods[name]
            with self.subTest(test=name):
                made = calls(fn)
                self.assertIn(
                    "_swept", made,
                    f"{name} calls _sweep directly, bypassing the vacuity "
                    "check -- an empty sweep makes it pass while testing zero "
                    "hooks, and that is the exact state this file shipped in")
                self.assertNotIn(
                    "_sweep", made,
                    f"{name} calls _sweep as well as _swept")
                if name in self._EXEMPT_FROM_THE_RAN_CHECK:
                    continue
                self.assertIn(
                    "_assert_the_hook_ACTUALLY_RAN", made,
                    f"{name} never checks that the hooks actually RAN -- "
                    "'the process came back' is satisfied by a child that "
                    "died in 20ms without opening the script")

    def test_the_shared_assertion_REJECTS_each_of_those_and_ACCEPTS_a_real_run(self):
        # The helper is what the five behavioural tests actually call, so it is
        # the thing that has to discriminate -- pinning `_run` alone would
        # leave the tests free to ignore what it returns.
        check = TestEveryDeployedHookReturns(
            "test_an_ORDINARY_hook_call_returns_every_hook_promptly"
        )._assert_the_hook_ACTUALLY_RAN
        check("a real hook", Ran(True, 0.02, 15, 0, ""))
        for bad in (Ran(True, 0.02, 15, 2, "hook refused"),
                    Ran(True, 0.02, 15, 1, "Traceback (most recent call last)"),
                    Ran(True, 0.02, 15, 2,
                        "can't open file '/x/y.py': [Errno 2] No such file")):
            with self.subTest(rc=bad.rc):
                with self.assertRaises(AssertionError):
                    check("a hook that never ran", bad)


class TestTheSharedReaderItself(unittest.TestCase):
    """`hookio.py` has no test file of its own; these are the two properties
    the hooks depend on that were only ever covered by another file's fixture."""

    def _hookio(self):
        import importlib.util as u
        spec = u.spec_from_file_location(
            "hookio_under_test", str(ROOT / "vault-tools" / "hookio.py"))
        m = u.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_the_shared_reader_ITSELF_is_inside_the_raw_read_sweep(self):
        """RED-PEN FINDING 8, and the lesson had already been learned one file
        over. `discovered_scripts()` returns hook scripts, so `hookio.py` --
        the single file every hook's boundedness now depends on -- sat outside
        the AST scan entirely. The 08-14 adversary made this exact finding
        against `test_board_guard.py`, it was closed there by scanning hookio
        too, and the rewrite re-opened it.

        The assertion has to differ in kind, because hookio legitimately reads
        a stream: what it may not do is touch `sys.stdin` directly (it takes
        the stream as an argument so a test can hand it one) or read without a
        deadline. "Not looked at" is not an option.
        """
        src = (ROOT / "vault-tools" / "hookio.py").read_text()
        tree = ast.parse(src)

        direct = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute) and n.attr == "stdin"
                  and isinstance(n.value, ast.Name) and n.value.id == "sys"
                  and not isinstance(getattr(n, "ctx", None), ast.Store)]
        # One reference is legitimate and load-bearing: `stream = sys.stdin if
        # stream is None else stream`, the default. More than that means the
        # module reached past its own argument.
        self.assertLessEqual(
            len(direct), 1,
            "hookio.py touches sys.stdin more than once -- it takes a stream "
            "so that it can be driven; reaching past that is how it stops "
            "being testable")

        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn(
            "select", called,
            "hookio.py no longer bounds its wait with select() -- a read with "
            "no deadline is the bug this whole module exists to end")
        self.assertIn("monotonic", called,
                      "hookio.py no longer measures a deadline at all")

    def test_a_stream_exposing_only_read_is_accepted(self):
        # The AttributeError branch added by 69fb519. Its ONLY coverage was
        # incidental -- session_registry.py's own FakeIn stub -- so giving that
        # stub an isatty() would have silently removed the last thing holding
        # this branch, and the hook would have stopped recording again.
        hookio = self._hookio()

        class OnlyRead:
            def read(self, *a):
                return '{"session_id": "abcdef12"}'

        self.assertEqual(hookio.read_json_stdin(stream=OnlyRead()),
                         {"session_id": "abcdef12"})

    def test_a_non_object_payload_comes_back_as_None(self):
        # What lets the hooks drop their `isinstance(payload, dict)` guards.
        hookio = self._hookio()

        class Fixed:
            def __init__(self, text):
                self.text = text

            def read(self, *a):
                return self.text

        for raw in ("null", "[1,2,3]", '"hi"', "5"):
            with self.subTest(payload=raw):
                self.assertIsNone(hookio.read_json_stdin(stream=Fixed(raw)))

    def test_the_budget_is_bounded_by_the_smallest_configured_timeout(self):
        hookio = self._hookio()
        timeouts = [w.timeout for _p, cfg in all_configs()
                    for w in hook_invocations(cfg) if w.timeout is not None]
        self.assertTrue(timeouts, "the hooks lost their configured timeouts")
        # A band, not a floor and not a ceiling: a floor alone permitted a
        # budget leaving the hook 0.1s to work, a ceiling alone permitted one
        # that races a real caller.
        self.assertGreaterEqual(hookio.DEFAULT_BUDGET, 0.3 * min(timeouts))
        self.assertLessEqual(hookio.DEFAULT_BUDGET, 0.6 * min(timeouts))

    def test_the_recorders_budget_clears_every_configured_timeout(self):
        """session_record.py's own ceiling, read from the CONFIGS.

        Its comment named 8.0 for days while the code said 5.0, and named a
        20-vs-15 timeout skew that Serge settled on 2026-08-15. Nothing was
        broken -- 5.0 clears every bound the paragraph names -- but a number
        in prose the code does not have is how the next person picks the
        wrong ceiling with confidence. The comment now says a test checks
        this rather than trusting the paragraph; THIS IS THAT TEST, and
        without it the sentence would be the same fault one level out.
        """
        import importlib.util as u
        spec = u.spec_from_file_location(
            "session_record_budget", str(ROOT / "vault-tools" / "session_record.py"))
        sr = u.module_from_spec(spec)
        spec.loader.exec_module(sr)
        hookio = self._hookio()
        timeouts = [w.timeout for _p, cfg in all_configs()
                    for w in hook_invocations(cfg) if w.timeout is not None]
        self.assertTrue(timeouts, "the hooks lost their configured timeouts")
        self.assertLess(sr.STDIN_BUDGET, min(timeouts),
                        "the recorder waits longer than its own hook is allowed to live")
        self.assertEqual(sr.STDIN_BUDGET, hookio.DEFAULT_BUDGET,
                         "the recorder and the shared reader disagree about the budget")

    def test_this_hooks_timeout_is_THE_SAME_in_every_config(self):
        """The skew Serge ruled on must not silently come back.

        It was 20 in both deployed files and 15 in the template, and it had
        to be found by hand. A disagreement between what SHIPS and what RUNS
        is invisible to anything that reads only one of them.
        """
        seen = {}
        for path, cfg in all_configs():
            for w in hook_invocations(cfg):
                if "session_record.py" in w.rel:
                    seen[str(path)] = w.timeout
        self.assertTrue(seen, "the recorder is not wired anywhere")
        self.assertEqual(len(set(seen.values())), 1,
                         f"the recorder's timeout disagrees across configs: {seen}")

    # ---- the reader is TOTAL, and says what it swallowed ------------------

    def test_a_stream_with_NEITHER_isatty_NOR_read_returns_None(self):
        """Reproduced on the live tree 2026-08-21: it raised AttributeError.

        Both specific branches let such an object through to `json.load`,
        which needs a `.read` nobody had checked for. Every hook in this repo
        calls this on nearly every turn, so an exception here is not a hook
        failing -- it is Serge's turn failing on a path he never asked about.
        """
        hookio = self._hookio()

        class Neither:
            pass

        self.assertIsNone(hookio.read_json_stdin(stream=Neither(), budget=0.2))

    def test_a_stream_whose_read_RAISES_returns_None(self):
        """The fallback caught only (ValueError, TypeError, OSError), so a
        RuntimeError from a caller's own stream propagated straight out."""
        hookio = self._hookio()

        class Boom:
            def isatty(self):
                return False

            def read(self, *a):
                raise RuntimeError("boom")

        self.assertIsNone(hookio.read_json_stdin(stream=Boom(), budget=0.2))

    def test_WHAT_IT_SWALLOWED_IS_RECORDED_not_dropped_on_the_floor(self):
        """The dangerous half of making a function total.

        `except Exception` returning None is indistinguishable from a module
        that has quietly stopped working -- the exact silent-failure shape
        this project keeps hunting. So the swallow is observable, and this is
        what makes the breadth defensible rather than merely convenient.
        """
        hookio = self._hookio()

        class Boom:
            def isatty(self):
                return False

            def read(self, *a):
                raise RuntimeError("a very specific boom")

        hookio.read_json_stdin(stream=Boom(), budget=0.2)
        self.assertIsNotNone(hookio.LAST_ERROR)
        self.assertIn("RuntimeError", hookio.LAST_ERROR)
        self.assertIn("a very specific boom", hookio.LAST_ERROR)

    def test_a_SUCCESSFUL_read_leaves_no_stale_error_behind(self):
        """Otherwise the record is worse than useless: a healthy hook would
        look like a broken one for the rest of the process."""
        import io
        hookio = self._hookio()

        class Boom:
            def isatty(self):
                return False

            def read(self, *a):
                raise RuntimeError("boom")

        hookio.read_json_stdin(stream=Boom(), budget=0.2)
        self.assertIsNotNone(hookio.LAST_ERROR)
        got = hookio.read_json_stdin(stream=io.StringIO('{"session_id": "abc"}'),
                                     budget=0.2)
        self.assertEqual(got, {"session_id": "abc"})
        self.assertIsNone(hookio.LAST_ERROR)

    def _pipe_read(self, payload, budget=1.0):
        """Drive the real reader over a REAL pipe whose writer stays open.

        The writer is deliberately never closed: that is the condition the
        whole module exists for, and an in-memory stream cannot reproduce it
        because it always reaches EOF.
        """
        import os as _os
        import time as _time
        hookio = self._hookio()
        r, w = _os.pipe()
        self.addCleanup(lambda: _os.close(w))
        _os.write(w, payload)
        t = _time.monotonic()
        got = hookio.read_json_stdin(stream=_os.fdopen(r, "rb"), budget=budget)
        return got, _time.monotonic() - t

    def test_A_BOM_DOES_NOT_BURN_THE_WHOLE_BUDGET(self):
        """A payload behind a byte order mark parsed as nothing, forever.

        `lstrip()` does not remove U+FEFF, so `raw_decode` raised, which this
        module reports as _INCOMPLETE, which means "keep reading" -- and a
        permanently malformed payload was therefore waited on for the ENTIRE
        budget and then dropped. On a hook deployed with a 10s timeout that
        is half its life spent on something that could never have worked.
        Measured at exactly 1.00s of a 1.0s budget before the fix.
        """
        got, took = self._pipe_read('\ufeff{"session_id": "abcdef12"}'.encode())
        self.assertEqual(got, {"session_id": "abcdef12"})
        self.assertLess(took, 0.3, "a BOM still costs the whole budget")

    def test_a_BOM_with_whitespace_around_it_is_also_read(self):
        got, took = self._pipe_read('\ufeff  \n {"a": 1}'.encode())
        self.assertEqual(got, {"a": 1})
        self.assertLess(took, 0.3)

    def test_A_TRUNCATED_PAYLOAD_STILL_WAITS_and_that_is_CORRECT(self):
        """THE OTHER HALF, and it is the one that must NOT be 'fixed'.

        A genuine prefix may be completed by the next chunk, so waiting is
        right and the budget is the designed cost of it. Without this test
        the obvious over-fix -- treat any unparseable buffer as final --
        would look like an improvement and would silently drop real payloads
        split across reads. The card that raised the BOM named both cases;
        only one of them was a bug.
        """
        got, took = self._pipe_read(b'{"session_id": "abc', budget=0.5)
        self.assertIsNone(got)
        self.assertGreaterEqual(took, 0.4, "it gave up on a real prefix too early")

    def test_a_payload_split_across_writes_still_arrives(self):
        """The concrete reason the truncated case waits."""
        import os as _os, threading as _th, time as _time
        hookio = self._hookio()
        r, w = _os.pipe()
        self.addCleanup(lambda: _os.close(w))
        _os.write(w, b'{"session_id": ')
        _th.Timer(0.15, lambda: _os.write(w, b'"late"}')).start()
        got = hookio.read_json_stdin(stream=_os.fdopen(r, "rb"), budget=2.0)
        self.assertEqual(got, {"session_id": "late"})

    def test_a_MULTI_BYTE_CHARACTER_split_across_reads_still_arrives(self):
        """A UTF-8 character straddling a read boundary is not corruption.

        `os.read` returns whatever has arrived, so a payload carrying any
        non-ASCII text -- an accent, a dash, an emoji in a session's `doing`
        line -- can be delivered with a character cut in half. The decoder
        answers _INCOMPLETE for that, meaning "keep reading", and the next
        chunk completes it. Treating it as final instead silently drops a
        perfectly good payload, and the failure is invisible: the hook exits
        0 and simply records nothing.

        MY OWN INJECTION ROUND FOUND THIS UNTESTED. Changing that branch to
        `return None` left the whole suite green, in the file whose subject
        is exactly this. Serge's own name carries no multi-byte character,
        which is probably why nobody wrote it.
        """
        import os as _os, threading as _th
        hookio = self._hookio()
        # ensure_ascii=False, or json.dumps escapes the very character this
        # test is about into "\\u2014" and there is no multi-byte byte to
        # split. My first version did exactly that and errored looking for
        # bytes that were not there.
        blob = json.dumps({"doing": "reading Jarvis-brain — the café note"},
                          ensure_ascii=False)
        raw = blob.encode("utf-8")
        # Cut mid-character: find the em dash and split inside its bytes.
        dash = "—".encode("utf-8")
        cut = raw.index(dash) + 1          # one byte into a three-byte char
        r, w = _os.pipe()
        self.addCleanup(lambda: _os.close(w))
        _os.write(w, raw[:cut])
        _th.Timer(0.15, lambda: _os.write(w, raw[cut:])).start()
        got = hookio.read_json_stdin(stream=_os.fdopen(r, "rb"), budget=2.0)
        self.assertEqual(got, json.loads(blob),
                         "a character split across reads was dropped")

    def test_MAKING_IT_TOTAL_DID_NOT_MAKE_IT_DEAF(self):
        """The obvious wrong fix is a wrapper that returns None for
        everything. A real payload must still arrive, through the ordinary
        path, unchanged."""
        import io
        hookio = self._hookio()
        payload = {"session_id": "abc", "transcript_path": "/tmp/x.jsonl"}
        got = hookio.read_json_stdin(stream=io.StringIO(json.dumps(payload)),
                                     budget=0.5)
        self.assertEqual(got, payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
