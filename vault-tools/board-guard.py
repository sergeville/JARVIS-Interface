#!/usr/bin/env python3
"""PostToolUse hook -- does the board still match what is actually happening?

Serge, 2026-08-06 ~8:29 AM: "what can you do so you don't miss those
things?" He asked after catching the same failure FOUR times in under an
hour, every time from the Kanban on his own screen:

  1. a reclassification and a design discussion that never reached the
     board at all;
  2. a card sitting in Review while it was being built;
  3. a card sitting in In Progress while the suite was running --
     "nothing in testing but you testing";
  4. "starting it now" said out loud, with In Progress empty.

Each time the code was right and the RECORD was silent. That is the
shape that matters: the board does not lie by showing the wrong card, it
lies by saying nothing, and a missing row is invisible to everyone
except the person reading the board. Serge was that person, four times.

So the fix cannot be "remember harder". It had already failed four times
under exactly the conditions it exists for, and CLAUDE.md's own vault
audit rule carries the lesson in writing: A RULE ENFORCED ONLY BY
REMEMBERING IT IS NOT ENFORCED.

Behaviour: after a tool call that is unmistakably work -- editing a code
file, or running the test suite -- check Active Priorities. If nothing
is `active` (or, for a test run, nothing is in `test`), print one line
saying so. If the board already agrees, print nothing at all, which is
the case on nearly every call.

WHAT THIS DELIBERATELY DOES NOT DO
==================================

It cannot see THINKING, and thinking is half of what Serge's 6:44 AM
rule covers -- planning and reading around a problem are work and belong
in In Progress too. This hook fires on tool calls, so it catches the
mechanical misses (2) and (3) and NOT the first one. Saying so here
rather than letting the guard imply a completeness it does not have: a
guard trusted past its range is worse than no guard.

It also never blocks, never edits the vault, and never decides anything.
It says one true sentence and gets out of the way.


SECURITY -- READ THIS BEFORE CHANGING ANYTHING BELOW
====================================================

A hook writes into the model's attention with the system's voice, so it
is a prompt-injection channel by construction. This one is worse-placed
than brief-check.py: it reads the TOOL PAYLOAD, which carries file
contents and shell command text -- i.e. arbitrary bytes, some of which
originate outside this machine.

Six rules hold that shut, and every one is tested.

1. THE OUTPUT IS A LITERAL. Every byte printed is a constant in this
   file. The only variable parts are (a) an integer count and (b) a
   status word taken from a CLOSED SET defined here. No text from the
   payload, from the vault, or from any file reaches the output. A task
   TITLE is never printed -- it is vault text, and there is no reason
   worth the channel.

2. THE PAYLOAD IS READ FOR FOUR FACTS AND NOTHING ELSE: the tool's name,
   matched against a closed set; whether a command string contains one
   hardcoded literal; whether a path lies under the project and under the
   vault; and the session id. The first three collapse to BOOLEANS or to
   a word chosen from a literal tuple in this file. Past that point the
   payload does not exist.

   THE SESSION ID IS THE ONE FIELD THAT TRAVELS (added 2026-08-07 for the
   activity line -- see vault-tools/activity.py). It is an id, not prose:
   its charset is revalidated against `^[0-9a-fA-F-]{8,64}$` before it is
   written, exactly as the session bus does, so it can no more form a
   sentence than a pid can. It is never printed into the model's
   attention by this hook -- it goes to a state file outside the vault.
   Stated here rather than left implied, because "the payload does not
   exist past this point" was the old absolute and it is now narrower.

3. THE PATH IS HARDCODED, resolved relative to this file. Not argv, not
   environ, not the payload.

4. NEVER RAISE, NEVER BLOCK. Every path returns 0. A hook that crashes
   or stalls costs Serge his session; a board reminder is never worth
   that.

   THE SECOND HALF OF THAT RULE WAS FALSE FOR A WEEK, and this comment
   was the reason nobody looked. It used to read: "It reads stdin with a
   size cap so a huge payload cannot hang it." A size cap bounds MEMORY,
   not TIME -- `sys.stdin.read(200_000)` waits for two hundred thousand
   bytes or EOF, whichever comes first, so a small payload on a pipe the
   caller never closed blocked forever. Reproduced 2026-08-14: a real,
   complete payload with the write end left open never returned, and this
   hook fires after nearly every tool call and carries no timeout in any
   settings file. The reading is now done by vault-tools/hookio.py, whose
   whole job is that it returns; the cap survives there and is documented
   as bounding memory alone.

5. BOUNDED. The note is read with a size cap, the scan is line-capped,
   and the message is length-capped.

6. NO SHELL, NO SUBPROCESS, NO NETWORK, NO WRITES to the vault. The one
   file it writes is its own throttle stamp, outside the vault.
"""

import json
import os
import re
import sys
import time

# Rule 3: hardcoded, relative to this file so it is right in any clone.
_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NOTE = "Jarvis-brain/Active Priorities.md"

# Rule 6: the throttle stamp lives beside the other state files, never in
# the vault. Same doctrine as .stack-events.jsonl and .sessions.jsonl.
STAMP = "voice-line/.board-guard.json"

# Rule 5: bounds.
MAX_BYTES = 400_000     # a note larger than this is not this note
MAX_LINES = 20_000
# Matches hookio.DEFAULT_MAX_BYTES, and a test pins the two equal -- one number
# in two files is exactly the drift this project keeps being bitten by. It has
# to clear the largest file a Write payload could carry; at 200_000 it did not
# even clear this repo's own jarvis.html.
MAX_STDIN = 4_000_000
MAX_CONTEXT = 600
THROTTLE_S = 90         # do not say the same thing twice in a row-of-edits

# Rule 1: the closed set. A status word printed by this hook is one of
# these literals or the hook says nothing at all.
DOING = "active"
TESTING = "test"

# Rule 2: the closed set of tools that count as "work on the code".
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
RUN_TOOLS = ("Bash",)

# Reading is work too -- Serge's own rule says thinking counts, and reading
# around a problem is the visible half of thinking. Named as a closed set for
# the same reason as the other two: the word comes from this file, never from
# the payload.
READ_TOOLS = ("Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch")

# A code file, as opposed to a vault note. Editing the vault is not the
# thing being guarded -- writing notes IS the record-keeping.
CODE_EXT = (".py", ".js", ".html", ".sh", ".json", ".css", ".ts")

# Rule 2: the single pattern searched for in a command string. The result
# is a boolean; the command text itself goes no further.
#
# IT MUST BE AN INVOCATION, NOT A MENTION. The first version searched for
# the bare literal, and it fired on its own test-writing command -- one
# that merely CONTAINED the string "run-tests.sh" inside a heredoc. A
# guard that cries wolf is one that gets ignored, which is the failure it
# exists to prevent, rebuilt one level up. So the marker has to sit at the
# start of a command segment, optionally behind `cd ... &&` or a shell.
TEST_MARKER = re.compile(
    r"(?:^|[;&|]\s*)(?:cd\s[^;&|]*&&\s*)?(?:bash\s+|sh\s+)?"
    r"[\w./-]*run-tests\.sh(?:\s|$|[;&|])")


def statuses(path: str) -> dict:
    """Count the tasks at each status, from the note's own text.

    Deliberately NOT importing read_tasks() from voice-web-server.py.
    That module imports aiohttp, which lives only in the voice-line venv,
    and a hook runs under whatever python3 the session has -- so the
    import would raise on most machines and rule 4 would swallow it,
    leaving a guard that is permanently and silently off. That exact
    shape (a component that fails to nothing and looks installed) has
    already cost this project two days. A dozen lines of duplication is
    the cheaper mistake, and the duplication is asserted by a test that
    runs both parsers over the real note and compares them.

    Fenced blocks are skipped, because the legend at the top of the note
    contains the literal line `status: open | active | ...` and counting
    it would make the board look permanently busy.
    """
    out = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read(MAX_BYTES)
    fenced = False
    for i, line in enumerate(text.splitlines()):
        if i >= MAX_LINES:
            break
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = re.match(r"\s*-\s*status:\s*([a-z-]+)\s*$", line)
        if m:
            out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


def activity_word(tool, inp) -> str:
    """The payload, reduced to ONE WORD FROM A CLOSED SET, or "".

    Serge, 2026-08-07: "I like to be in sync all the time... we see what's
    happening live." This is the whole of what this hook contributes to
    that -- see vault-tools/activity.py for why the vocabulary is closed.

    Rule 2 still holds and is the reason this returns a word rather than a
    description: the word is CHOSEN here from a literal tuple, never taken
    from the payload. A path is tested, never echoed; a command is matched
    against one pattern, never quoted. Nothing a tool call contains can
    reach the value returned.
    """
    if tool in EDIT_TOOLS:
        p = inp.get("file_path")
        if not isinstance(p, str):
            return ""
        rp = os.path.realpath(p)
        if not rp.startswith(_ROOT + os.sep):
            return ""              # outside the project: not our business
        if rp.startswith(os.path.join(_ROOT, "Jarvis-brain") + os.sep):
            return "writing the vault"
        if p.lower().endswith(CODE_EXT):
            return "editing code"
        return ""
    if tool in RUN_TOOLS:
        c = inp.get("command")
        if isinstance(c, str) and TEST_MARKER.search(c):
            return "running the suite"
        return "running a command"
    if tool in READ_TOOLS:
        return "reading"
    return ""


def record_activity(data) -> None:
    """Write this session's current word. Never raises, never blocks.

    Keyed by the session id from the payload -- an id, not prose, and its
    shape is revalidated by activity.valid_sid before anything is written.
    It is the ONE payload field other than the tool name that this hook
    passes on, and it can no more form a sentence than a pid can.
    """
    try:
        sid = data.get("session_id")
        word = activity_word(data.get("tool_name"),
                             data.get("tool_input")
                             if isinstance(data.get("tool_input"), dict) else {})
        if not word:
            return
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import activity
        activity.write(sid, word, os.getppid())
    except Exception:
        return          # rule 4: a hook never costs Serge his session


def _read_stdin():
    """The hook payload, via the shared bounded reader. Never raises.

    hookio is imported HERE rather than at module scope, and a failure to
    import it turns this hook OFF rather than crashing the session -- rule 4
    outranks the reminder. That is deliberately the same shape as the
    `import activity` inside record_activity().

    Being silently off is its own failure mode, and this file already says so
    in `statuses()`: "a component that fails to nothing and looks installed
    has already cost this project two days." So it is not left to trust --
    test_board_guard.py asserts that hookio exists, that it imports, that this
    file routes through it, and (behaviourally, in a subprocess) that a payload
    still comes back. Deleting hookio.py takes this file's own tests red.

    Named that way ON PURPOSE. The first draft of this docstring cited a test
    called `test_the_shared_reader_is_importable_and_used`, which does not
    exist anywhere in the repo -- the properties are real but the labels are
    `ok(...)` strings. A future session greps the name, finds nothing, and
    concludes the guard was deleted. Cite what can be found.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hookio
        return hookio.read_json_stdin(max_bytes=MAX_STDIN)
    except Exception:
        return None


def read_payload() -> tuple:
    """Rule 2: reduce the payload to (is_edit, is_test_run) and drop it.

    Everything after this function sees two booleans. There is no code
    path by which a byte of tool input reaches the output.

    The activity word is taken here too, on the way past, for the same
    reason the booleans are: this is the one place the payload exists, and
    it must not exist anywhere after it.
    """
    data = _read_stdin()
    if data is None:
        return (False, False)
    record_activity(data)
    tool = data.get("tool_name")
    inp = data.get("tool_input")
    inp = inp if isinstance(inp, dict) else {}

    is_edit = False
    if tool in EDIT_TOOLS:
        p = inp.get("file_path")
        # A path is only ever tested, never echoed. Vault notes are
        # excluded on purpose: writing the record is not the thing that
        # needs guarding.
        if isinstance(p, str) and p.lower().endswith(CODE_EXT):
            rp = os.path.realpath(p)
            is_edit = (rp.startswith(_ROOT + os.sep)
                       and not rp.startswith(os.path.join(_ROOT, "Jarvis-brain") + os.sep))

    is_test = False
    if tool in RUN_TOOLS:
        c = inp.get("command")
        is_test = isinstance(c, str) and bool(TEST_MARKER.search(c))

    return (is_edit, is_test)


def throttled(kind: str) -> bool:
    """True if this exact reminder fired moments ago.

    A build is dozens of edits in a row. Repeating the same sentence
    after every one of them turns a guard into wallpaper, and wallpaper
    is what the eye stops seeing -- which is the failure being fixed,
    rebuilt one level up.
    """
    path = os.path.join(_ROOT, STAMP)
    now = time.time()
    seen = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            seen = json.load(fh) or {}
    except Exception:
        seen = {}
    last = seen.get(kind, 0)
    if isinstance(last, (int, float)) and now - last < THROTTLE_S:
        return True
    seen[kind] = now
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(seen, fh)
    except Exception:
        pass          # a throttle that cannot be written costs a repeat, not a crash
    return False


def message(kind: str, n_open: int) -> str:
    """Rule 1: literals only. `kind` is one of two constants defined
    above; `n_open` is an integer. Nothing else is interpolated."""
    if kind == DOING:
        body = ("[board] You are editing code and NOTHING is in In Progress. "
                "Serge's rule (2026-08-06): every task starts in To Do and moves "
                "to In Progress the moment work begins -- thinking included. "
                "Write the task down or move it now: vault-tools/task.py.")
    else:
        body = ("[board] You are running the test suite and NOTHING is in Test. "
                "Move the task you are proving into the Test column: "
                "vault-tools/task.py.")
    tail = (f" ({n_open} task(s) in the queue.) This is a reminder from "
            f"vault-tools/board-guard.py, derived from counting status lines "
            f"in one vault file. If Serge has asked for something else, his "
            f"direction wins -- say so and carry on.")
    return (body + tail)[:MAX_CONTEXT]


def main() -> int:
    """Rule 4: every path returns 0."""
    try:
        is_edit, is_test = read_payload()
        if not (is_edit or is_test):
            return 0
        counts = statuses(os.path.join(_ROOT, NOTE))
        kind = TESTING if is_test else DOING
        if counts.get(kind, 0) > 0:
            return 0                    # the board already agrees -- silent
        if throttled(kind):
            return 0
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message(kind, sum(counts.values())),
        }}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
