#!/usr/bin/env python3
"""Move a task on the board in one command.

Serge, 2026-08-06: he caught the board disagreeing with reality four
times in under an hour. The guard (vault-tools/board-guard.py) makes
those misses visible; this makes them cheap to fix.

That pairing is the whole point and neither half works alone. Moving a
card used to mean hand-editing a markdown block -- finding the right
task among a dozen, changing three lines without disturbing the prose
around them. That friction is exactly why it got skipped under pressure,
and A NAG YOU CANNOT CHEAPLY SATISFY BECOMES NOISE, which is the failure
being fixed rebuilt one level up.

    python3 vault-tools/task.py list
    python3 vault-tools/task.py move <part of title> <status> ["note"]
    python3 vault-tools/task.py add "<title>" [P1|P2|P3] ["note"]

Statuses are the six board columns: open, active, review, test,
waiting-on-serge, done.


WHY THE WRITE IS SURGICAL
=========================

Other sessions edit this note. A whole-file rewrite from a stale copy
silently eats their work -- the same doctrine as every append-only log
in this project. So:

  * only the `status:`, `updated:` and `note:` lines of ONE task change;
    every other byte of the file, including all the prose, is passed
    through untouched;
  * the file's mtime is captured before the edit and re-checked before
    the write, and a change means ABORT rather than overwrite;
  * the write is atomic (temp file + os.replace), so a crash mid-write
    cannot leave Serge with half a note.

It refuses rather than guesses: an ambiguous title match names the
candidates and changes nothing.
"""

import os
import re
import sys
import tempfile
from datetime import datetime


class TaskError(Exception):
    """A refusal, with the reason Serge or a caller should be told.

    The core functions RAISE this; only the CLI turns it into an exit.
    That split exists because there is a second caller now -- the HUD's
    approve button (`POST /task-move` in voice-web-server.py) -- and a
    `sys.exit()` inside a request handler would raise SystemExit through
    aiohttp and take a piece of the server with it. One writer, two
    front doors: the CLI and the route must never be able to disagree
    about what a move does, which is the same reason the session
    registry keeps its writer, resolver and CLI in one file.
    """

_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NOTE = os.path.join(_ROOT, "Jarvis-brain", "Active Priorities.md")

# The six board columns, and nothing else. A status the board has never
# heard of lands in To Do, so a typo here would silently park a task in
# the wrong column rather than fail -- which is why this is a closed set
# checked up front.
STATUSES = ("open", "active", "review", "test", "waiting-on-serge", "done")

TASK_RE = re.compile(r"^- \[([ x])\] \*\*(.+?)\*\*")


# Moving a card into one of these means a session has picked the work up,
# so the owner field is stamped from the running session. `open` is the
# opposite move -- back to the backlog, held by nobody -- so it clears the
# field. `done` and `waiting-on-serge` deliberately LEAVE THE OWNER ALONE:
# on a finished card the owner is the record of who did it, and clearing it
# would throw that away at the exact moment it becomes history.
OWNED = ("active", "review", "test")


def owner_label():
    """"channel (pid N)" for the session running this, or None.

    None means the answer is not knowable -- the HUD's approve button is
    the live case, since the server is not a Claude Code session. A caller
    that gets None must leave the owner field untouched rather than write
    "unassigned" over a real name: a WRONG owner reads as fact, while a
    missing one reads as unknown, and the whole reason this field is being
    stamped is that a field nobody writes is decoration.

    The server case is a RULE, not a topology: whoami() stops walking at
    the web server, so the approve button gets None even if the stack was
    launched from a session's own terminal. See session_registry's
    SERVER_MARKERS -- an unbounded walk stamped the LAUNCHING session onto
    a card it never touched, which is the wrong-owner failure this whole
    field exists to prevent.

    NEVER RAISES. This runs inside `move`, between reading the note and
    writing it, and a card move is not worth a traceback: an identity we
    cannot compute is exactly the None case, not an error. (Found
    2026-08-07 -- the test asserting this was named "survives a registry
    that raises" while asserting that it DIED.)

    The channel is vetted against the same closed vocabulary the session
    bus uses, because this value is f-strung into a note Serge reads.
    Today classify() returns only literals, so this is defence in depth --
    but the bus and the board must not disagree about whether the
    registry's output is trusted, and only one of them renders.
    """
    try:
        sys.path.insert(0, os.path.join(_ROOT, "voice-line"))
        import session_registry as reg
        who = reg.whoami()
        if not who:
            return None
        channel, pid = who
        import session_mail as mail
        if channel not in mail.CHANNELS:
            return None
        # `isinstance(True, int)` is True in Python, so a bool would sail
        # through an int check and render as "pid True". The same trap was
        # already paid for once on this project, in the approval-reply id
        # guard -- so it is spelled out here rather than rediscovered.
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        return f"{channel} (pid {pid})"
    except Exception:
        return None


def load():
    with open(NOTE, "r", encoding="utf-8") as fh:
        return fh.read().splitlines(keepends=True), os.stat(NOTE).st_mtime_ns


def blocks(lines):
    """(title, start, end) for every task, by its checkbox heading.

    A block runs to the next task heading or the next `###` section, so
    Completed Tasks below is never touched by a move.
    """
    out, cur, fenced = [], None, False
    for i, line in enumerate(lines):
        # FENCED BLOCKS ARE NOT TASKS. The legend at the top of the note
        # is a worked example -- `- [ ] **Title** (project)` -- and a
        # first version of this function read it as the first real task.
        # Two consequences, both silent: `add` inserted new tasks INSIDE
        # the code fence, where the server's parser cannot see them, and
        # `move` could match it. Found by a test, not by reading.
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = TASK_RE.match(line)
        if m:
            if cur:
                out.append((cur[0], cur[1], i))
            cur = (m.group(2), i)
        elif line.startswith("### "):
            if cur:
                out.append((cur[0], cur[1], i))
                cur = None
            # STOP at Completed Tasks. Below it every entry is a closed
            # one-liner with no fields, and letting `move` match one would
            # graft status lines onto a historical record -- or move the
            # wrong card, which is the lie this tool exists to prevent.
            if "Completed" in line:
                break
    if cur:
        out.append((cur[0], cur[1], len(lines)))
    return out


def field(lines, start, end, key):
    """Index of the LAST `- key:` line in the block, or None.

    The LAST one on purpose: read_tasks() takes the last value it sees,
    so a block carrying two `note:` lines shows the second. An earlier
    edit of mine changed the first and had no visible effect at all --
    the parser and the editor must agree about which line is real.
    """
    hit = None
    pat = re.compile(r"^\s*-\s*" + re.escape(key) + r":")
    for i in range(start, end):
        if pat.match(lines[i]):
            hit = i
    return hit


def save(lines, mtime_ns):
    """Atomic, and only if nobody else wrote while we were thinking."""
    if os.stat(NOTE).st_mtime_ns != mtime_ns:
        raise TaskError(
            "REFUSING: Active Priorities changed while this ran -- "
            "another session is editing it. Nothing was written.")
    d = os.path.dirname(NOTE)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".task-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(lines))
        os.replace(tmp, NOTE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_list():
    lines, _ = load()
    for title, s, e in blocks(lines):
        st = field(lines, s, e, "status")
        nt = field(lines, s, e, "note")
        stv = lines[st].split(":", 1)[1].strip() if st else "?"
        ntv = lines[nt].split(":", 1)[1].strip()[:60] if nt else ""
        print(f"{stv:17} {title[:52]:54} {ntv}")
    return 0


def move(needle, status, note, exact=False, only_from=None):
    """Move one task. Returns its title; raises TaskError on any refusal.

    `exact` and `only_from` exist for the HUD button, which is the first
    caller-controlled write this vault has ever taken, and they are the
    two constraints that make it narrow:

      * `exact` matches the whole title rather than a substring. The CLI
        wants "part of title" because a human is typing it and can see
        the refusal; a button sends the exact string it drew, and a
        substring from a page could quietly match a DIFFERENT card.
      * `only_from` refuses unless the task is currently in one of the
        given statuses. So the approve button can move a card out of
        `review` and NOTHING ELSE -- it cannot touch work in flight, and
        a page that is compromised or simply stale cannot reach past the
        column Serge is actually looking at.
    """
    if status not in STATUSES:
        raise TaskError(
            f"unknown status {status!r} -- one of {', '.join(STATUSES)}")
    lines, mtime = load()
    if exact:
        hits = [b for b in blocks(lines) if b[0] == needle]
    else:
        hits = [b for b in blocks(lines) if needle.lower() in b[0].lower()]
    if not hits:
        raise TaskError(f"no task matching {needle!r}")
    if len(hits) > 1:
        # Refuse rather than guess: moving the wrong card is a lie on the
        # board, which is the thing this tool exists to prevent.
        raise TaskError(
            "ambiguous -- matches:\n  " + "\n  ".join(h[0] for h in hits))
    title, s, e = hits[0]

    st = field(lines, s, e, "status")
    if st is None:
        raise TaskError(f"{title!r} has no status line")
    if only_from is not None:
        was = lines[st].split(":", 1)[1].strip()
        if was not in only_from:
            raise TaskError(
                f"{title!r} is {was!r}, not {' or '.join(only_from)} -- "
                "refusing to move it")
    indent = re.match(r"\s*", lines[st]).group(0)
    lines[st] = f"{indent}- status: {status}\n"

    # THE OWNER IS STAMPED, NOT TYPED. Every card on the board read
    # "unassigned" on 2026-08-06 because `add` hardcoded it and `move`
    # never touched it -- the field was decoration, and Serge caught a
    # card running with nobody's name on it. A field a human has to
    # remember to update is the same failure as a nag they cannot cheaply
    # satisfy, one level down.
    ow = field(lines, s, e, "owner")
    if ow is not None:
        if status in OWNED:
            who = owner_label()
            if who:
                lines[ow] = f"{indent}- owner: {who}\n"
        elif status == "open":
            lines[ow] = f"{indent}- owner: unassigned\n"

    up = field(lines, s, e, "updated")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if up is not None:
        lines[up] = f"{indent}- updated: {stamp}\n"

    if note:
        nt = field(lines, s, e, "note")
        if nt is not None:
            lines[nt] = f"{indent}- note: {note}\n"
        else:
            lines.insert(st + 1, f"{indent}- note: {note}\n")

    # The checkbox outranks a stale status field on the HUD, so the two
    # must not be allowed to disagree here either.
    lines[s] = re.sub(r"^- \[.\]", "- [x]" if status == "done" else "- [ ]",
                      lines[s], count=1)

    save(lines, mtime)
    return title


def cmd_move(needle, status, note):
    try:
        title = move(needle, status, note)
    except TaskError as exc:
        sys.exit(str(exc))
    print(f"{title} -> {status}")
    return 0


def cmd_add(title, priority, note):
    if priority not in ("P1", "P2", "P3"):
        sys.exit("priority must be P1, P2 or P3")
    lines, mtime = load()
    bs = blocks(lines)
    if not bs:
        sys.exit("no tasks found -- refusing to guess where to insert")
    at = bs[0][1]          # newest first, above the current top task
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = [
        f"- [ ] **{title}** (learning-ai)\n",
        f"  - status: open\n",
        f"  - owner: unassigned\n",
        f"  - priority: {priority}\n",
        f"  - updated: {stamp}\n",
        f"  - note: {note or 'not started'}\n",
        "\n",
    ]
    lines[at:at] = block
    try:
        save(lines, mtime)
    except TaskError as exc:
        sys.exit(str(exc))
    print(f"added: {title} (open, {priority})")
    return 0


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__.strip().splitlines()[0] + "\n\n" +
                 "  task.py list\n"
                 "  task.py move <part of title> <status> [note]\n"
                 "  task.py add \"<title>\" [P1|P2|P3] [note]")
    verb = argv[1]
    if verb == "list":
        return cmd_list()
    if verb == "move":
        if len(argv) < 4:
            sys.exit("usage: task.py move <part of title> <status> [note]")
        return cmd_move(argv[2], argv[3], argv[4] if len(argv) > 4 else "")
    if verb == "add":
        if len(argv) < 3:
            sys.exit("usage: task.py add \"<title>\" [P1|P2|P3] [note]")
        return cmd_add(argv[2],
                       argv[3] if len(argv) > 3 else "P3",
                       argv[4] if len(argv) > 4 else "")
    sys.exit(f"unknown verb {verb!r} -- list, move or add")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
