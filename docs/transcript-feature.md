# Adding transcripts to another project

**This is the transcript feature written down so it can be built somewhere else from scratch** — on a different machine, in a different project, with or without the rest of this stack. What it produces, why each decision is what it is, the two files to create, the one hook to wire, and the checks that prove it works.

It is self-contained on purpose: **both source files are reproduced in full below**, read off disk rather than retyped, so you do not have to clone this repo to follow it. If you have cloned it, they are `vault-tools/hookio.py` and `vault-tools/session_record.py` and you can copy them straight across.

Written so a Claude Code session can execute it top to bottom, and so a person can read it and understand what they are getting. If you only want to know what the feature does on *this* project, that is the [Transcripts section of the README](../README.md#transcripts) — this file is for building it elsewhere.

---

## What you end up with

A folder of plain Markdown files, one per day per channel:

```
transcripts/
  2026-08-21.md            <- what was said out loud (voice channel)
  2026-08-21-terminal.md   <- what was typed (Claude Code sessions)
  .terminal-watermarks.json
```

Every file is a list of lines in exactly one shape:

```
- **08:19:58 Serge:** Good morning.
- **08:20:08 Jarvis:** Good morning, Serge. Quick state of play: the instrument work is still uncommitted with a third agent round owed.
- **08:20:27 Serge:** Old round.
```

Nobody types a command to get this. It is written automatically, on every turn, by a hook.

## Why it is worth building

The raw material was never missing. Claude Code already writes every session to `~/.claude/projects/<project>/<session-id>.jsonl` — 189 of them by the evening this was first built. But that file is machine-shaped, lives outside the project folder, and no session ever reads it. Before the hook existed, the only readable record of a typed conversation existed because Serge happened to ask for one on the day.

**That asymmetry is the entire bug.** The voice line had never needed to be asked; the keyboard did. A record that depends on somebody remembering is the exact failure this kind of system exists to prevent.

What the transcript buys you concretely: **a new session can read the tail of the file and know what was still open.** Vault notes record what was *decided*. A crashed or compacted session kills what was still *in flight* — the half-finished thought, the question that never got answered — and that is the one thing notes cannot hold, because nobody writes down a question while they are waiting for the answer.

## The four decisions that make it work

**1. One turn is one line.** The file is meant to be read with `tail`. A turn that spans forty lines defeats that, so all whitespace is collapsed and the line is written whole.

**2. Append-only, never rewritten.** Same property as an event log: a file that is only ever appended to cannot lose an earlier line to a later bug. Idempotency comes from a watermark (last uuid written per session) plus a substring duplicate guard — run the hook twice and nothing doubles.

**3. The conversation, not the machinery.** Tool calls, tool results, thinking blocks and subagent side-chains are all deliberately dropped. What is kept is what was said and what was said back. The tool work is already recorded where it belongs — in the files it produced and in the git history. A transcript that inlined it would be unreadable, which is the same as not having one.

**4. One file per day per channel, never merged.** Two writers appending to one file interleave. Keeping the spoken record and the typed record separate also keeps them honest: typed turns appearing in the voice file would be a lie about what was said out loud.

---

## Step 1 — Choose the folder, and gitignore it before you write to it

Pick a `transcripts/` folder inside the project. Then, **before the first line is ever written**, add it to `.gitignore`:

```gitignore
# transcripts/ is VERBATIM, timestamped conversation. It is not code.
transcripts/
```

Do this first and get it right the first time. This folder is a recording of a person — hundreds of kilobytes of it within a week. Ours very nearly shipped to a public repo because it survived an exclusion list built from an inventory that never mentioned it, and GitHub retains history even after a delete.

The watermark file lives **inside** that folder on purpose: it is derived from the folder's contents and is meaningless without them, so the two travel together and neither can be published by accident.

Verify the ignore actually matches before continuing:

```bash
git check-ignore -v transcripts/2026-01-01-terminal.md
```

## Step 2 — Create the bounded stdin reader

**This file is the reason the feature is safe to run on every turn.** A Stop hook that hangs hangs every conversation on the machine. This exact bug shipped twice here, in two different hooks, written months apart, each by an author who believed they had guarded against it — one guarded with `isatty()`, one with a size cap. Both tested a *proxy* instead of the *property* they promised. It surfaced as a ten-minute hang in the test suite.

Create `hookio.py` next to the recorder. Take it as-is; there is nothing project-specific in it.

```python
#!/usr/bin/env python3
"""The one bounded stdin read that every Jarvis hook uses.

WHY THIS MODULE EXISTS. Twice now the same bug has shipped in two different
hooks, written months apart by sessions that each believed they had guarded
against it:

  * `session_record.py` guarded with `sys.stdin.isatty()` and promised in its
    own docblock that a hook must never block. An inherited pipe that is open
    and silent is not a tty, so `json.load` waited forever. Found 2026-08-14
    when the full test suite hung for ten minutes and had to be killed.
  * `board-guard.py` guarded with the SAME isatty check plus a size cap, and
    promised in rule 4 that "it reads stdin with a size cap so a huge payload
    cannot hang it." A size cap bounds MEMORY, not TIME: `read(200_000)` waits
    for two hundred thousand bytes or EOF, whichever comes first, so a small
    payload on a pipe nobody closed blocks exactly as hard. That hook is the
    PostToolUse hook on Edit, Write and Bash -- it fires after nearly every
    tool call -- and it carries no timeout in any settings file.

Both wrote a guard that tested a PROXY -- is this a terminal? is the payload
huge? -- instead of the PROPERTY they promised: is anything actually coming,
and will this call return? Two independent authors reached for the same wrong
proxy, which is the argument for one implementation rather than a third.

WHAT IT DOES. Reads a JSON object from a stream, and RETURNS -- always, on
every path, whatever the caller on the other end does or fails to do.

THE PART THAT IS EASY TO GET WRONG, and did get written wrong twice already:
bounding the wait for the FIRST BYTE is not enough. `json.load` calls `read()`,
which runs to EOF, so a complete and perfectly valid payload still hangs if the
writer holds its end open. The deadline here covers the WHOLE read, and the
read stops as soon as a complete JSON value has ARRIVED -- waiting for a close
that may never come buys nothing.

And "has arrived" has to mean a PREFIX, not the whole buffer. The first version
of this file tested `json.loads(everything_so_far)`, so a perfectly good
payload followed by a single trailing byte -- a stray newline from a wrapper, a
second object, anything -- never parsed, and the read sat out its entire budget
and returned nothing. `raw_decode` answers the question actually being asked:
is there a complete value at the front of this buffer yet?
"""
import io
import json
import os
import select
import sys
import time

# The ceiling on a whole read, first byte to last. It is a ceiling, not a
# delay: a real hook's payload is already waiting, so the read returns at once
# and this costs nothing. Only a silent or slow stdin ever pays it.
#
# Chosen to sit under the SMALLEST timeout any hook in the template is deployed
# with, because that is the real upper bound. It has to be the smallest and not
# this hook's own: the reader is shared, so the next hook to adopt it inherits
# this number. The first version of this constant, in session_record.py, was
# picked against nothing at all; the second was 12.0, picked against the 15s
# Stop hooks while UserPromptSubmit sits at 10s -- caught by a test, not by
# reading.
#
# It is pinned as a BAND, 30%-60% of the smallest timeout, and the band exists
# because the two obvious one-sided pins contradict each other. A floor alone
# ("do not shrink it") permitted 9.9 under a 10s timeout, leaving the hook 0.1s
# to do its actual work. A ceiling alone ("leave room") permitted 0.8, which
# races a real caller. The hook's own work is milliseconds, so the band is
# generous at both ends and still refuses both failures.
DEFAULT_BUDGET = 5.0

# Bounds memory, and ONLY memory. Kept because a hook should not be a way to
# make the machine swap -- but named here so nobody again mistakes it for
# protection against hanging, which is the exact error rule 4 of board-guard.py
# made in writing.
#
# 4MB, and the size is a DECISION with a reason. It was 200_000, which is
# smaller than this repo's own `Jarvis Visual/jarvis.html` (318KB) -- so a
# Write of the project's largest file produced a payload over the cap, and the
# hook dropped it in silence along with the HUD activity record that goes with
# it. Nothing tested that; the old cap was asserted as a VALUE and never as a
# behaviour. `test_the_cap_clears_the_largest_file_a_payload_could_carry` pins
# it against the actual repo rather than against a number typed here.
DEFAULT_MAX_BYTES = 4_000_000

# Parses a complete value off the FRONT of a buffer and reports where it ended,
# which is the question this module needs and `json.loads` cannot answer.
_DECODER = json.JSONDecoder()

# "not a complete value yet" -- distinct from "a complete value that is None",
# which is a real payload shape (`null`) that must be refused, not waited on.
_INCOMPLETE = object()


def read_json_stdin(budget=None, max_bytes=None, stream=None):
    """The JSON object a hook was handed on stdin, or None.

    ALWAYS RETURNS, and returns within `budget`. Not "never blocks" -- that was
    the previous wording and it is the exact promise this codebase has now
    broken twice, so it is worth being literal: this waits, but it waits a
    bounded amount and then gives up.

    None means "there is nothing here to act on", for every reason alike: no
    payload, a terminal, an unreadable stream, a caller that went quiet, bytes
    that are not a JSON object, or a payload over `max_bytes`. That last one is
    the only case where data really was there and is discarded, which is why
    the cap is sized against this repo's largest file rather than guessed.
    """
    # Resolved HERE, not in the signature. A default argument is bound once
    # at definition time, so `hookio.DEFAULT_BUDGET = 0.5` after import had no
    # effect whatever -- which is how a test meant to prove boundedness sat
    # waiting out the real budget and failed. A constant nobody can override
    # is a constant nobody can test around.
    budget = DEFAULT_BUDGET if budget is None else budget
    max_bytes = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    stream = sys.stdin if stream is None else stream
    # A terminal is never a hook caller. This is NOT redundant with the
    # readiness check below: a tty with a line typed and no Ctrl-D is "ready"
    # as far as select is concerned, so dropping it puts an interactive run
    # straight back into a read waiting for an EOF the human has not sent.
    try:
        if stream is None or stream.isatty():
            return None
    except AttributeError:
        # A duck-typed stand-in with only .read() -- which is how
        # session_registry.py's own tests drive their hook, and how this was
        # found. It cannot be a terminal, so carry on rather than treating a
        # missing method as a reason to drop the payload. The `fileno` branch
        # below already had this; the isatty branch did not, and the whole
        # hook silently stopped recording.
        pass
    except (ValueError, OSError):
        return None

    try:
        fd = stream.fileno()
    except (io.UnsupportedOperation, ValueError, OSError, AttributeError):
        # No real descriptor -- an in-memory stream, which is how these hooks
        # get tested in-process. It cannot block, so read it directly.
        # Returning None here instead would turn a working read into a silent
        # drop: io.UnsupportedOperation subclasses BOTH ValueError and OSError,
        # so a plain `except (ValueError, OSError)` swallows it and nothing
        # anywhere reports the loss.
        try:
            return _object_or_none(json.load(stream))
        except (ValueError, TypeError, OSError):
            return None

    deadline = time.monotonic() + budget
    chunks = []
    size = 0
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            if not select.select([fd], [], [], left)[0]:
                break            # nothing is coming
            chunk = os.read(fd, 65536)
        except (ValueError, OSError):
            break                # a stream that raises is a stream to give up on
        if not chunk:
            break                # EOF, the ordinary case
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            return None          # not a hook payload; refuse it rather than parse it
        got = _decode_prefix(b"".join(chunks))
        if got is not _INCOMPLETE:
            return _object_or_none(got)
    got = _decode_prefix(b"".join(chunks))
    return None if got is _INCOMPLETE else _object_or_none(got)


def _decode_prefix(buf):
    """The first complete JSON value at the front of `buf`, or _INCOMPLETE.

    _INCOMPLETE means "keep reading" and is the ONLY thing that keeps the loop
    going, so every other outcome -- malformed, too deep, not yet valid UTF-8
    at a chunk boundary -- has to resolve one way or the other rather than
    spin.
    """
    try:
        text = buf.decode("utf-8")
    except UnicodeDecodeError:
        return _INCOMPLETE       # a multi-byte character split across reads
    try:
        value, _end = _DECODER.raw_decode(text.lstrip())
        return value
    except ValueError:
        return _INCOMPLETE       # not a whole value at the front yet
    except RecursionError:
        # Nesting deeper than the interpreter will parse. This ESCAPED the
        # function before it was caught here, out of the one whose docstring
        # promises it always returns -- and both callers only survived it by
        # wrapping everything in `except Exception`. A contract kept by the
        # caller is not a contract.
        return None


def _object_or_none(data):
    """A hook payload is an object. `null`, a list and a bare string are not.

    Every one of those is valid JSON that `json.load` returns happily, and
    every one of them made `.get` raise AttributeError in the caller -- an
    uncaught traceback and a non-zero exit on every turn, reproduced in
    session_record.py before this existed.
    """
    return data if isinstance(data, dict) else None
```

## Step 3 — Create the recorder

Create `session_record.py` in the same folder. **Three lines are project-specific — change these and nothing else:**

| Line | What to change it to |
|---|---|
| `JARVIS_ROOT = Path(__file__).resolve().parents[1]` | The project root, relative to wherever you put this file. |
| `TRANSCRIPTS = JARVIS_ROOT / "Jarvis Visual" / "transcripts"` | The folder from Step 1. |
| `base.glob("*Jarvis*/*.jsonl")` in `main()` | The pattern matching **your** project's folder under `~/.claude/projects/`. Run `ls ~/.claude/projects/` and use a distinctive fragment of your project's directory name. |

Two more things to adjust for a different household: `"Serge"` and `"Jarvis"` in `turns()` are the two names on every line, and `entrypoint != "cli"` is the filter that keeps the voice brain out. If there is no separate voice channel writing its own transcript, **keep that filter anyway** — see the note under Step 7.

```python
#!/usr/bin/env python3
"""Record a TYPED Jarvis conversation the way the voice line records a spoken one.

Serge, 2026-08-07 ~7:20 PM: "so we don't lose anything."

THE PROBLEM THIS SOLVES IS REMEMBERING, NOT STORAGE. Nothing was ever actually
lost -- Claude Code has been writing every session to
`~/.claude/projects/<project>/<id>.jsonl` all along, 189 of them by the evening
this was written. But that file is machine-shaped, lives outside the Jarvis
folder, and no session ever reads it. The one readable record of a typed
conversation existed because Serge thought to ask for it at 7:15 PM that day
(`JarvisOS 5000 Planning Day -- Conversation Record`). The voice line has never
had to be asked. That asymmetry is the whole bug: a record that depends on
somebody remembering is the failure this system exists to prevent.

WHAT IT WRITES, AND WHY IT LOOKS EXACTLY LIKE THE VOICE TRANSCRIPT: the same
`- **HH:MM:SS Who:** text` line, in the same gitignored `transcripts/` folder,
because a second format would need a second reader -- and the readers already
exist (the HUD's activity log, the idea panel's "what was said", a session
tailing the file at boot).

WHICH SESSIONS: only `entrypoint == "cli"` -- Serge at a keyboard. The voice
brain runs as `sdk-py` and already logs itself through signals.log_transcript;
recording it here would write every spoken turn down twice.

WHAT IT DELIBERATELY DOES NOT KEEP: tool calls, tool results, thinking, and
subagent side-chains. This is the CONVERSATION -- what he said and what was
said back. The tool work is already recorded where it belongs: in the vault
notes it produced and in the git history. A transcript that inlined it would
be unreadable, which is the same as not having one.

Run:  python3 vault-tools/session_record.py            # hook mode, reads stdin
      python3 vault-tools/session_record.py <file.jsonl>
      python3 vault-tools/session_record.py --all      # backfill every session
"""
import json
import os
import re
import sys
import time
from pathlib import Path

# The ceiling on the WHOLE stdin read in _read_payload(), first byte to last.
# It is a ceiling, not a delay: a real hook's payload is already there, so the
# read returns at once and this costs nothing. Only a silent or slow stdin
# ever pays it.
#
# The number is chosen against the hook's own configured timeout, because that
# is the real upper bound and the first version of this constant was picked
# against nothing. Those timeouts DISAGREE -- the deployed .claude/settings.json
# files say 20s and templates/claude-settings.json.template says 15s -- which is
# carded separately as its own defect. It must also clear the SMALLEST timeout
# in the template, 10s, because vault-tools/hookio.py is shared and the next
# hook to adopt it inherits this ceiling. 8.0 sits under all three. Raising it
# is safe only up to the smallest of them; shrinking it widens the window in
# which a genuinely slow caller's turn is dropped in silence.
# Must equal hookio.DEFAULT_BUDGET; a test pins them. Passed explicitly rather
# than left to default so the tests can override it per-run.
STDIN_BUDGET = 5.0

JARVIS_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = JARVIS_ROOT / "Jarvis Visual" / "transcripts"
# The watermark lives INSIDE the gitignored transcripts folder on purpose: it
# is derived from that folder's contents and is meaningless without them, so
# the two travel together and neither can be published by accident.
WATERMARK = TRANSCRIPTS / ".terminal-watermarks.json"

# Serge's own turn carries harness furniture -- reminders, hook context, the
# tool-result payloads of the previous turn. None of it is him talking, and a
# transcript that quotes the machine back at him is worse than no transcript.
#
# THE SHAPE OF THE FIX MATTERS. The first version listed the tags it had seen
# and was wrong within a minute of the first real backfill: seventeen
# `<local-command-caveat>` blocks and ten `<task-notification>` blocks went in
# as things Serge said. A denylist of remembered tags loses to the next tag
# nobody has met yet -- so any XML-ish block is dropped, and what survives is
# prose. He types sentences, not markup.
_STRIP = [
    re.compile(r"<(\w[\w-]*)(\s[^>]*)?>.*?</\1>", re.S),   # any paired block
    re.compile(r"</?\w[\w-]*(\s[^>]*)?/?>"),               # and any stray tag
]


def _clean(text: str) -> str:
    for pat in _STRIP:
        text = pat.sub(" ", text)
    # One turn is one line, exactly like the voice transcript -- the file is
    # read by tailing it, and a turn that spans forty lines defeats that.
    return re.sub(r"\s+", " ", text).strip()


def _text_of(message: dict) -> str:
    """The spoken part of a message -- never the tool traffic around it."""
    content = message.get("content")
    if isinstance(content, str):
        return _clean(content)
    if not isinstance(content, list):
        return ""
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        # tool_use, tool_result and thinking are all deliberately dropped.
        if block.get("type") == "text":
            out.append(str(block.get("text", "")))
    return _clean(" ".join(out))


def _stamp(ts: str) -> tuple[str, str]:
    """(YYYY-MM-DD, HH:MM:SS) in Serge's local time, from an ISO timestamp.

    The transcript is his day, so it is stamped in his clock -- the file is
    named for the day HE had, not the day UTC was having.
    """
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return time.strftime("%Y-%m-%d"), time.strftime("%H:%M:%S")


def turns(path: Path) -> list[tuple[str, str, str, str]]:
    """(uuid, date, clock, line) for every real conversational turn in a log."""
    out = []
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return out
    for line in raw.splitlines():
        try:
            d = json.loads(line)
        except (ValueError, TypeError):
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        # A subagent's conversation is not Serge's conversation. It reports to
        # the session, and what mattered from it is already in the reply.
        if d.get("isSidechain"):
            continue
        # ONLY A TYPED SESSION. The voice brain is `sdk-py` and already writes
        # itself down; recording it here would double every spoken turn.
        if d.get("entrypoint") != "cli":
            continue
        message = d.get("message")
        if not isinstance(message, dict):
            continue
        text = _text_of(message)
        if not text:
            continue
        who = "Serge" if d.get("type") == "user" else "Jarvis"
        day, clock = _stamp(d.get("timestamp", ""))
        out.append((d.get("uuid") or f"{day}{clock}{who}", day, clock,
                    f"- **{clock} {who}:** {text}"))
    return out


def _watermarks() -> dict:
    try:
        data = json.loads(WATERMARK.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(path: Path) -> int:
    """Append this session's new turns to its day's file. Returns lines added.

    APPEND-ONLY AND IDEMPOTENT, in that order. The watermark is the last uuid
    already written for this session, so running twice adds nothing and a
    session interrupted mid-file resumes where it stopped. Nothing is ever
    rewritten: the same property the voice transcript and the stack event log
    are built on -- a file that is only ever appended to cannot lose an
    earlier line to a later bug.
    """
    rows = turns(path)
    if not rows:
        return 0
    marks = _watermarks()
    seen = marks.get(path.stem)
    if seen:
        ids = [r[0] for r in rows]
        if seen in ids:
            rows = rows[ids.index(seen) + 1:]
        # A watermark naming a uuid this file no longer has is a file that was
        # replaced, not advanced. Writing everything again would duplicate the
        # day; writing nothing would lose it. The honest move is to keep going
        # from nothing and let the duplicate guard below sort it out.
    if not rows:
        return 0

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    written = 0
    for day in sorted({r[1] for r in rows}):
        # ONE FILE PER DAY PER CHANNEL. Not merged into the voice line's
        # `YYYY-MM-DD.md`: two writers appending to one file interleave, and
        # the HUD's activity log reads that file as the VOICE conversation --
        # typed turns appearing in it would be a lie about what was said out
        # loud.
        target = TRANSCRIPTS / f"{day}-terminal.md"
        have = ""
        try:
            have = target.read_text(errors="replace")
        except OSError:
            pass
        lines = [r[3] for r in rows if r[1] == day and r[3] not in have]
        if not lines:
            continue
        with target.open("a") as fh:
            fh.write("\n".join(lines) + "\n")
        written += len(lines)

    marks[path.stem] = rows[-1][0]
    try:
        WATERMARK.write_text(json.dumps(marks, indent=1))
    except OSError:
        pass
    return written


def _hook_path() -> Path | None:
    """The transcript Claude Code names on stdin, when run as a hook."""
    # A HOOK MUST NEVER BLOCK. Found while fault-testing this file: run with
    # no argument and no piped input, `json.load(sys.stdin)` simply waits --
    # forever, at a terminal. This runs on EVERY turn, so a hang here is a
    # hang in every conversation on the machine. If nobody is piping anything
    # in, there is no session to record and it says so immediately.
    #
    # 2026-08-14: isatty() ALONE DID NOT KEEP THAT PROMISE, and the gap ran
    # for a week. It catches exactly one way of "nobody is piping anything
    # in" -- an interactive terminal. An inherited pipe that is open and
    # simply never delivers is not a tty, so the guard waved it through and
    # json.load() waited forever. The guard tested a PROXY (is this a
    # terminal?) instead of the PROPERTY it promised (is anything actually
    # coming?). It surfaced as a ten-minute hang in the test suite.
    #
    # The isatty line stays, and it is NOT redundant: a tty with a line typed
    # but no Ctrl-D is "ready" as far as select is concerned, so removing it
    # puts an interactive run straight back into a read that waits for an EOF
    # the human has not sent. `test_the_isatty_guard_is_not_redundant` pins
    # that with a real pty -- it was green under every injection until then.
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
    except (ValueError, OSError):
        return None
    return _payload_path(_read_payload())


def _read_payload():
    """Whatever object the caller piped in, or None -- bounded either way.

    THE FIRST FIX HERE WAS ONLY NEARLY RIGHT, and both review agents caught
    the same edge: guarding with select and then handing the descriptor to
    `json.load` bounds the wait for the FIRST BYTE and nothing after it,
    because `json.load` calls `read()`, which runs to EOF. A COMPLETE, valid
    payload still hung if the writer held its end open.

    That logic now lives in vault-tools/hookio.py and is shared with
    board-guard.py, which had the same bug behind a different wrong proxy --
    two authors reaching for two bad guards is the argument against a third
    copy. Import failure returns None: a hook that cannot read stdin has no
    session to record, and rule "never block, never crash" outranks recording.

    ONE BEHAVIOUR CHANGE THAT CAME WITH THE MOVE, claimed here rather than left
    to be discovered: this now inherits hookio's byte cap, which it did not
    have before. Both agents flagged it as an unclaimed delta. The cap is 4MB
    and a Stop-hook payload is a path and a session id, so nothing real is near
    it -- but it is a cap where there was none, and above it a turn is dropped
    in silence.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hookio
        return hookio.read_json_stdin(budget=STDIN_BUDGET)
    except Exception:
        return None


def _payload_path(payload) -> Path | None:
    """The transcript path out of a hook payload, or None.

    Every one of these guards is a crash the adversary reproduced in the
    shipped code: `json.load` succeeds on `null`, on a list and on a bare
    string, and then `.get` raises AttributeError -- an uncaught traceback and
    a non-zero exit, on every turn. A hook that dies loudly every turn is the
    next long debugging session, so a payload this function cannot read is
    simply not a session to record.
    """
    if not isinstance(payload, dict):
        return None
    p = payload.get("transcript_path")
    if not isinstance(p, str) or not p:
        return None
    return Path(p)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--all":
        # Backfill. The raw logs have been there all along; this is the one
        # command that makes the whole history readable.
        base = Path(os.path.expanduser("~/.claude/projects"))
        total = 0
        for f in sorted(base.glob("*Jarvis*/*.jsonl")):
            total += record(f)
        print(f"{total} line(s) recorded")
        return 0
    path = Path(argv[0]) if argv else _hook_path()
    # A hook that cannot tell which conversation it is in does NOTHING. It
    # must never guess at "the newest session" -- on a machine that routinely
    # runs several at once, that writes one session's words into another's.
    if path is None or not path.exists():
        return 0
    record(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## Step 4 — Wire the Stop hook

Claude Code fires the `Stop` hook after every assistant turn and pipes a JSON object on stdin containing `transcript_path` — the path to that session's own `.jsonl`. That is the whole interface. The hook reads the log it is pointed at, extracts the new turns, and appends them.

In `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/vault-tools/session_record.py",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

**The timeout is load-bearing, and so is its relationship to `hookio.DEFAULT_BUDGET`.** The reader's 5-second ceiling has to sit under the *smallest* timeout any hook in the file is deployed with, because the reader is shared and the next hook to adopt it inherits that number. If you deploy this hook at 15s, 5.0 is comfortable. If you ever deploy a hook using `hookio` at 10s, 5.0 is still fine; below that, re-check.

Use an absolute path. A hook does not run in the directory you think it does.

## Step 5 — Backfill the history you already have

The raw logs have been there all along. This is the one command that makes the whole past readable:

```bash
python3 vault-tools/session_record.py --all
```

Expect a surprise here. Our first real backfill put seventeen `<local-command-caveat>` blocks and ten `<task-notification>` blocks into the file as things Serge had said — harness furniture that arrives inside a user turn. That is why the stripper drops **any** XML-ish block rather than a list of tags somebody remembered: a denylist loses to the next tag nobody has met yet. What survives is prose, because people type sentences, not markup.

Read the first hundred lines of what the backfill produced before you trust it.

## Step 6 — The rule that makes it worth having

Add this to the other Jarvis's boot instructions, in whatever file loads at session start:

> **Read the TAIL of today's transcript at startup** — `tail -40 transcripts/YYYY-MM-DD-terminal.md` (yesterday's if today's does not exist yet).

And the reasoning, which matters more than the command:

> **Why the tail and not the whole file, and not the notes:** the file is append-only, so the end of it IS the live state — the last thing said, in the user's exact words, including **the question of yours he never got to answer.** Notes record what was decided; a restart kills what was still open, and that is the one thing notes cannot hold.
>
> **Do not read the whole file.** A day of raw conversation does not fit in a context window, and the notes are already its digested form. Reach deeper into it only to answer a specific question, never to browse: it is a verbatim recording of a person.

Serge's own words when he worked this out: *"you don't need the whole file, you just need maybe 10 lines, 15 lines... from that, you could always extrapolate what we were doing."*

## Step 7 — Prove it works

Run all six. The first four are the feature; the last two are the ones that catch the failures that actually happened.

1. **It records.** Type a message in a Claude Code session, wait for the reply to finish, then `tail -5 transcripts/$(date +%F)-terminal.md`. Both turns are there, stamped in local time.
2. **It is idempotent.** Run `python3 vault-tools/session_record.py <that-session>.jsonl` twice. The second run adds nothing.
3. **It drops the machinery.** Ask for something that uses several tools. The transcript has the request and the answer, and no tool calls, no results, no thinking.
4. **It stamps the user's day, not UTC's.** Check a turn that happened after 7 PM local. It is filed under the day the user had.
5. **It cannot hang — test this, do not assume it.** Run the hook with an open pipe that never sends anything and never closes:
   ```bash
   python3 -c "import subprocess,time; p=subprocess.Popen(['python3','vault-tools/session_record.py'],stdin=subprocess.PIPE); time.sleep(8); print('exited:', p.poll())"
   ```
   It must have exited. This is the bug that shipped twice; a guard nobody tested is a guard nobody has.
6. **It never guesses which conversation it is in.** Run it with no argument and no stdin. It must do nothing at all. On a machine running several sessions at once, guessing "the newest session" writes one person's words into another's file.

Then run whatever test suite the project has. If there is none, the six checks above are the gate.

---

## The pitfalls, so you do not pay for them twice

Every one of these was found the expensive way here.

- **`json.load(sys.stdin)` with nothing piped in waits forever.** At a terminal, silently. This hook runs on every turn, so a hang here is a hang in every conversation on the machine.
- **`isatty()` alone does not fix it, and the gap ran for a week.** An inherited pipe that is open and simply never delivers is not a tty. The guard tested "is this a terminal?" instead of "is anything actually coming?"
- **Keep the `isatty()` line anyway — it is not redundant.** A tty with a line typed but no Ctrl-D is "ready" as far as `select` is concerned, so removing it puts an interactive run straight back into a read waiting for an EOF the human has not sent.
- **A size cap bounds memory, not time.** `read(200_000)` waits for two hundred thousand bytes *or* EOF, whichever comes first. A small payload on a pipe nobody closed blocks exactly as hard.
- **Bounding the wait for the first byte is not enough.** `json.load` calls `read()`, which runs to EOF — a complete, valid payload still hangs if the writer holds its end open. The deadline has to cover the whole read, and the read has to stop as soon as a complete value has *arrived*.
- **"Has arrived" must mean a prefix, not the whole buffer.** Testing `json.loads(everything_so_far)` means one stray trailing newline from a wrapper makes a perfectly good payload never parse, and the read sits out its entire budget for nothing. `raw_decode` asks the right question.
- **`json.load` succeeds on `null`, on a list, and on a bare string** — and then `.get` raises `AttributeError`. That is an uncaught traceback and a non-zero exit, on every turn.
- **Size the byte cap against your largest real file, not against a round number.** Ours was 200 KB, which is smaller than this repo's own `jarvis.html` (318 KB) — so writing the project's biggest file produced a payload over the cap and the turn was dropped in silence.
- **Resolve constants inside the function, not in the signature.** A default argument binds once at definition time, so setting `hookio.DEFAULT_BUDGET = 0.5` after import does nothing — which is how a test meant to prove boundedness sat waiting out the real budget and failed. A constant nobody can override is a constant nobody can test around.
- **A watermark naming a uuid the file no longer has** means the file was replaced, not advanced. Rewriting everything duplicates the day; writing nothing loses it. Carry on from nothing and let the duplicate guard sort it out.

---

## Optional: the spoken half

If the other Jarvis has a voice channel too, it writes the same line format into the same folder under `YYYY-MM-DD.md` (no `-terminal` suffix), from inside the process rather than from a hook. The whole of it:

```python
def log_transcript(role: str, text: str) -> None:
    """Append one exchange line to today's transcript file."""
    text = " ".join(text.split())
    if not text:
        return
    try:
        TRANSCRIPTS_DIR.mkdir(exist_ok=True)
        day = time.strftime("%Y-%m-%d")
        stamp = time.strftime("%H:%M:%S")
        with open(TRANSCRIPTS_DIR / f"{day}.md", "a") as f:
            f.write(f"- **{stamp} {role}:** {text}\n")
    except Exception as e:
        print(f"transcript write failed: {e}", file=sys.stderr, flush=True)
```

Call it once with the user's text when a turn is transcribed, and once with the reply when the turn completes. Note that it swallows its own failures to stderr — **a transcript must never be able to break the conversation it is recording.** That is the same rule the hook follows: a hook that cannot read stdin has no session to record, and "never block, never crash" outranks recording.

If both channels are running, the `entrypoint != "cli"` filter in `turns()` is what stops the voice brain being written down twice — once by itself, once by the hook.
