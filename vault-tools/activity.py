"""What each live Jarvis session is doing right now, in five words.

SERGE ASKED FOR THIS, 2026-08-07 ~7:56 AM: "I like to be in sync all the
time. So when I watch something, or even you when you watch something, or
another like the terminal watch something, we see what's happening live in
sync."

THE GAP IT CLOSES. A card moves columns only when a session REMEMBERS to
move it, so the board trails the real work by minutes -- and every miss so
far was caught by Serge's own eyes, four times in one hour on 2026-08-06 and
twice more the next morning. The session registry answers WHO is alive. The
board guard notices when the board and the work disagree. Neither answers
"what is that session doing at this moment", which is the question he is
actually asking.

WHAT IT DELIBERATELY DOES NOT DO: it does not move a card. Which column a
task belongs in is judgment -- is this thinking, or proving, or genuinely
blocked on Serge -- and a card in the WRONG column reads as fact while a
late one reads as late. So the machine writes the FACTS beside the board and
the human keeps the JUDGMENT. A card reading `test` while its session is
plainly editing code then becomes a contradiction Serge can SEE, live,
instead of one he has to catch.

-----------------------------------------------------------------------
THE SECURITY RULE, and it decides the whole shape of this file
-----------------------------------------------------------------------
The natural writer for this is board-guard.py's PostToolUse hook, which
already sees every tool call. That hook was built to collapse the payload to
two booleans BEFORE anything else happens, precisely so no byte of file
content or command text can reach a model's attention (its rule 2).

Whatever is written here is read by the server, rendered onto the page, and
-- crucially -- can be read back into ANOTHER session's context. That is a
channel for arbitrary text to travel between sessions, which is exactly what
the session bus was designed never to allow, and why the bus has no
free-text field anywhere.

So:

  * THE VOCABULARY IS CLOSED. A word written here is one of the literals in
    WORDS below or nothing is written at all. Nothing is ever quoted from a
    payload, a path, a command, or a file.
  * THE ONLY OTHER FIELDS ARE A UUID-SHAPED SESSION ID AND TWO NUMBERS.
    The id's charset cannot form a sentence -- the same guard, and the same
    reason, as session_mail.valid_sid.
  * IT LIVES OUTSIDE THE VAULT, beside the other state files, so no note
    can be corrupted and no vault audit can be tripped by it.
  * IT NEVER RAISES. It runs inside a hook on every tool call; a crash
    would cost Serge his session, and knowing what a session is doing is
    never worth that.
  * IT IS BOUNDED. One line per session, capped, oldest dropped.

Deliberately NOT recorded: which file, which command, which task. Detail is
given up on purpose. A weaker signal that cannot carry a sentence beats a
richer one that can.
"""

import json
import os
import re
import time

_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Beside .sessions.jsonl and .board-guard.json -- never in the vault.
FILE = os.path.join(_ROOT, "voice-line", ".activity.json")

# THE CLOSED VOCABULARY. Five words. A sixth needs a code change and a test,
# which is the point: the set cannot grow at run time from anything a tool
# call contains.
WORDS = (
    "editing code",
    "running the suite",
    "running a command",
    "writing the vault",
    "reading",
)

# Bounds. More sessions than this is not a state worth rendering.
MAX_ROWS = 12
MAX_BYTES = 20_000

# Same shape as the bus's: hex and dashes only, so it cannot form a
# sentence even if something upstream is compromised.
SID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def valid_sid(sid) -> bool:
    return isinstance(sid, str) and bool(SID_RE.match(sid))


def read(path: str | None = None) -> dict:
    """Everything currently recorded, revalidated on the way in.

    The file is re-checked rather than trusted: it sits on disk where any
    process can write it, and this data reaches a rendered page. Same
    doctrine as the bus's reader -- validate at the boundary you control,
    every time, not once at the point of writing.
    """
    p = path or FILE
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.loads(fh.read(MAX_BYTES))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for sid, row in list(raw.items())[:MAX_ROWS]:
        if not valid_sid(sid) or not isinstance(row, dict):
            continue
        word = row.get("word")
        ts = row.get("ts")
        pid = row.get("pid")
        if word not in WORDS:
            continue
        if not isinstance(ts, (int, float)) or ts <= 0:
            continue
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            continue
        out[sid] = {"word": word, "ts": float(ts), "pid": pid}
    return out


def write(sid: str, word: str, pid: int, now: float | None = None,
          path: str | None = None) -> bool:
    """Record one session's current activity. Returns whether it was written.

    NEVER RAISES. Every failure is a silent False: this runs inside a hook
    on every tool call, and the whole feature is worth less than one of
    Serge's sessions.
    """
    try:
        if not valid_sid(sid) or word not in WORDS:
            return False
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return False
        rows = read(path)
        rows[sid] = {"word": word, "ts": float(now or time.time()), "pid": pid}
        # Oldest out first, so a long-running machine cannot grow this file.
        if len(rows) > MAX_ROWS:
            for dead in sorted(rows, key=lambda k: rows[k]["ts"])[:-MAX_ROWS]:
                rows.pop(dead, None)
        p = path or FILE
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
        os.replace(tmp, p)          # atomic: a reader never sees half a file
        return True
    except Exception:
        return False
