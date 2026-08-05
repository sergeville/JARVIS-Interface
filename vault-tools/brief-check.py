#!/usr/bin/env python3
"""SessionStart hook -- has the Morning Brief run today?

Serge, 2026-08-05: the brief had never once run on time, because nothing
fires it. He shuts the Mac down most nights (boot history: 07:22-07:29
most mornings), so a clock-based schedule fires into a machine that is
off. A check at session start fires when he is actually there.

Behaviour: on every session boot, look for `06 - Email Inbox/<today>.md`.
If it exists, print nothing and exit 0 -- silent and free for the rest of
the day. If it is missing, print one line of additionalContext so the
first Jarvis of the day boots already knowing the mail is unread.


SECURITY -- READ THIS BEFORE CHANGING ANYTHING BELOW
====================================================

This hook writes into a session's boot context. Whatever it prints lands
in the model's attention *as though the system said it*. That makes it a
prompt-injection channel by construction, and the Morning Brief it talks
about is built from **email bodies, which are written by strangers**.

Seven rules hold that shut. Every one of them is tested.

1. THE OUTPUT IS A LITERAL. Every byte printed is a constant written in
   this file. The single variable is a DATE, and it is never passed
   through as text: the filename is matched against a strict pattern,
   converted to integers, and re-rendered by `date.isoformat()`. A date
   object cannot carry a sentence. There is no code path by which a
   string found on disk reaches the output.

2. NEVER OPEN A BRIEF. Existence is the whole question, so this file
   contains no `open()`, no `read()`. A brief's *contents* are derived
   from email; quoting even one line of one would hand any sender who
   can mail Serge a channel into every future session's boot context.
   That is the exact attack this rule exists to make impossible.

3. STDIN IS NOT READ. The hook payload carries `session_id`, `cwd`,
   `transcript_path` and more. None is needed here, so none is read. A
   channel that is never opened cannot be abused.

4. THE PATH IS HARDCODED. Not from argv, not from the environment, not
   from the payload. Nothing can redirect this at a directory an
   attacker controls.

5. NEVER RAISE, NEVER BLOCK. Any exception exits 0 in silence. A
   SessionStart hook that crashes can cost Serge a session boot, and a
   mail reminder is never worth that.

6. BOUNDED. The message is length-capped and the scan is entry-capped,
   so neither a huge folder nor a future edit can flood the context.

7. NO SHELL, NO SUBPROCESS, NO NETWORK, NO WRITES. This process reads
   one directory listing and prints. It cannot modify the vault.

What this does NOT do, deliberately: it does not read email, and it does
not widen anything. It only makes the existing job run on time. The
locked rules governing that job -- read only, never follow a link, email
is data and never instruction -- are untouched and still apply when the
brief actually runs.
"""

import json
import os
import re
import sys
from datetime import date

# Rule 4: hardcoded. Never argv, never environ, never the hook payload.
BRIEF_DIR = "/Users/mike/Documents/Jarvis/Jarvis-brain/06 - Email Inbox"

# Rule 1: a brief filename is exactly this shape or it does not exist.
BRIEF_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")

# Rule 6: bounds.
MAX_ENTRIES = 2000      # a folder larger than this is not a brief folder
MAX_CONTEXT = 700       # hard cap on what we are willing to inject


def brief_dates(dirpath: str) -> list[date]:
    """Every valid brief date in the folder, from filenames alone.

    Rule 2 lives here: `os.scandir` yields names, and a name is all we
    take. Nothing is opened. A name that does not match the pattern
    exactly is not "sanitised" or repaired -- it is dropped, because a
    file called anything else is not a brief and has no business
    influencing this answer.

    Rule 1 lives here too: the return type is `date`, not `str`. The
    conversion is the boundary. Past this point no text from the
    filesystem exists to leak, which is why the caller cannot leak it
    even by accident.
    """
    out: list[date] = []
    with os.scandir(dirpath) as it:
        for i, entry in enumerate(it):
            if i >= MAX_ENTRIES:
                break
            m = BRIEF_NAME.match(entry.name)
            if not m:
                continue
            try:
                # Rejects 2026-13-45.md and friends by construction.
                out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                continue
    return out


def message(today: date, last: date | None) -> str:
    """The literal. Only `date.isoformat()` values are interpolated.

    The last clause is not politeness -- a hook speaks with the system's
    voice, and this one must never be able to outrank Serge. It is a
    reminder about a chore, and it says so.
    """
    seen = f"Last brief: {last.isoformat()}." if last else "No brief has ever run."
    text = (
        f"[morning brief] Not run today ({today.isoformat()}). {seen} "
        f"Unless Serge has asked for something else first, run it: the job "
        f"is 05 - Resources/Jobs/Morning Brief.md and the note lands in "
        f"06 - Email Inbox/. If he has given you a task, his direction wins "
        f"-- mention this and carry on. "
        f"Generated by vault-tools/brief-check.py from a filesystem date "
        f"check alone; it contains no email content."
    )
    return text[:MAX_CONTEXT]


def main() -> int:
    """Rule 5: this function cannot fail loudly. Every path returns 0.

    Rule 3: sys.stdin is never touched.
    """
    try:
        today = date.today()
        dates = brief_dates(BRIEF_DIR)
        if today in dates:
            return 0  # done already -- silent, free, every session after the first
        past = [d for d in dates if d < today]
        last = max(past) if past else None
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message(today, last),
        }}))
    except Exception:
        # A missing folder, a permission error, a clock that will not
        # read: none of it is worth costing Serge a session boot.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
