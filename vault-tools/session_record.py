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
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
    except (ValueError, OSError):
        return None
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError, OSError):
        return None
    p = payload.get("transcript_path")
    return Path(p) if p else None


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
