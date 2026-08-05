"""Session registry: who is actually running, answered from the machine.

Serge, 2026-08-05: "we want to know every session running or not."

[[Session Board]] is signed by hand at boot. A session that is killed --
by a restart, a brain rebuild, or a crash -- cannot un-sign itself, so
the board is structurally incapable of being right. Measured at the
moment he asked: four active rows, two live Jarvises.

THE DESIGN POINT, and the reason this file is shaped the way it is:

    The hook writes identity. `ps` decides who is alive.

SessionEnd is a nicety, not a source of truth -- a killed session never
fires it, which is exactly the case that breaks the board today. So
liveness is re-derived at READ time, every time, from the process table.
This is the same doctrine as the stack event log: the record has to
outlive the thing it describes.

Three jobs in one file, deliberately -- the writer, the resolver and the
CLI must never disagree about the record's shape:

  hook   `python3 session_registry.py start|end`  (SessionStart/SessionEnd)
  read   read_sessions()  -- imported by Jarvis Visual/voice-web-server.py
  CLI    `python3 session_registry.py --list`     -- used by jarvis.sh sessions

PROBE FINDINGS, 2026-08-05 (verified in a throwaway project, not assumed):
  * SessionStart and SessionEnd BOTH fire for the SDK-spawned voice brain,
    not just for terminal sessions.
  * `model` comes back NULL on the SDK path even though the payload carries
    it for a terminal session -- so the model is read from the process
    command line, never trusted from the hook.
  * `cwd` comes back SYMLINK-RESOLVED (/private/tmp/..., not /tmp/...), so
    every path comparison here goes through realpath or the voice brain
    would be misfiled.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SESSIONS_FILE = Path(__file__).resolve().parent / ".sessions.jsonl"

# The project root, derived from this file's own location rather than written
# in. Nothing about it can be supplied by a caller -- not argv, not the
# environment, not stdin -- so it is exactly as trustworthy as a literal was,
# and it is correct in any clone. realpath because macOS hands back
# symlink-resolved paths (/tmp -> /private/tmp) and these values get compared
# against cwds that arrive already resolved.
JARVIS_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Keep the log bounded the same way the stack event log is: trim on write,
# oldest first. One line per session start/end is far slower-growing than
# stack events, so these are generous.
TRIM_AT = 400
KEEP = 200

# A pid's start time is compared with a tolerance: `ps` reports whole
# seconds and the hook may read it a moment after the process began.
START_TOLERANCE_S = 2.0


# --------------------------------------------------------------------------
# process table
# --------------------------------------------------------------------------

def _parse_lstart(text: str) -> float | None:
    """`ps -o lstart=` -> epoch seconds.

    lstart is exactly five fields: "Wed Aug  5 11:39:12 2026". The LAST five
    tokens are taken rather than a fixed slice, so this parses correctly
    whether it is handed the bare lstart or a line with a pid in front of it.
    (The server's stack sampler slices from the front because it always has
    the pid there; getting that wrong here made every start time read None,
    which would have silently disabled the pid-reuse guard -- caught by the
    tests, which is the point of them.)

    BOTH field orders are accepted, and that is not defensiveness -- it is
    measured. On this machine `ps` prints "Tue  4 Aug 07:23:24 2026"
    (day before month), while the documented/US form is "Tue Aug  4 ...".
    Assuming one gave None for every process, which would have silently
    disabled the pid-reuse guard.
    """
    parts = text.split()
    if len(parts) < 5:
        return None
    tail = " ".join(parts[-5:])
    for fmt in ("%a %d %b %H:%M:%S %Y", "%a %b %d %H:%M:%S %Y"):
        try:
            return time.mktime(time.strptime(tail, fmt))
        except ValueError:
            continue
    return None


def process_table() -> dict[int, dict]:
    """Every live process: pid -> {ppid, started, cmd}.

    Uses `ps -A`, never pgrep. Hard-won lesson (2026-08-04): pgrep does not
    match processes in the tree it is called from, so a pgrep-based reader
    run from inside a Jarvis session is blind to that very session.
    """
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,lstart=,command="],
            capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return {}
    table: dict[int, dict] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        rest = parts[2]
        # lstart is exactly five whitespace-separated fields; the command is
        # whatever follows, and it may itself contain spaces.
        bits = rest.split(None, 5)
        if len(bits) < 6:
            continue
        started = _parse_lstart(" ".join(bits[:5]))
        table[pid] = {"ppid": ppid, "started": started, "cmd": bits[5]}
    return table


def is_claude(cmd: str) -> bool:
    """Is this command line a Claude Code session?

    Deliberately narrow: it must look like the claude binary or a node
    process running it -- not merely any command with the word in it, or
    every `grep claude` would register as a session.
    """
    if not cmd:
        return False
    head = cmd.split()[0]
    base = os.path.basename(head)
    if base == "claude":
        return True
    return base in ("node", "bun") and "/claude" in cmd


def ancestor_chain(pid: int, table: dict[int, dict],
                   limit: int = 40) -> list[dict]:
    """This process and its ancestors, nearest first. Depth-capped so a
    cycle in a malformed table can never hang a hook."""
    chain: list[dict] = []
    seen: set[int] = set()
    cur = pid
    while cur and cur not in seen and len(chain) < limit:
        seen.add(cur)
        rec = table.get(cur)
        if not rec:
            break
        chain.append({"pid": cur, **rec})
        cur = rec["ppid"]
    return chain


def channel_chain(pid: int, table: dict[int, dict]) -> list[str]:
    """The commands that decide this session's CHANNEL: its own, plus the
    ancestors above it, stopping at the next Claude Code session.

    The stop matters, and it was found in live use rather than reasoned out.
    Walking all the way to init means a terminal session launched from inside
    a Jarvis-spawned shell inherits the voice server somewhere up its chain
    and gets misfiled as "voice line". Its real parent is another claude --
    so the first claude above the session is the boundary of what belongs to
    it.
    """
    chain = ancestor_chain(pid, table)
    # Skip down to the owning session, then take everything above it until a
    # second claude appears.
    out: list[str] = []
    started = False
    for rec in chain:
        if not started:
            if is_claude(rec["cmd"]):
                started = True
                out.append(rec["cmd"])
            continue
        if is_claude(rec["cmd"]):
            break
        out.append(rec["cmd"])
    return out or [r["cmd"] for r in chain]


def owning_session(pid: int, table: dict[int, dict]) -> dict | None:
    """The nearest Claude Code process at or above `pid`.

    The hook runs as a child of the session, sometimes with a shell in
    between, so the session's own pid is found by walking up rather than
    assumed to be the parent.
    """
    for rec in ancestor_chain(pid, table):
        if is_claude(rec["cmd"]):
            return rec
    return None


# --------------------------------------------------------------------------
# pure classification -- no files, no clock, so it can be tested hard
# --------------------------------------------------------------------------

def model_from_cmd(cmd: str) -> str:
    """The model a session was launched with, from its own command line.

    The hook payload's `model` is null for the SDK-spawned brain (probed
    2026-08-05), so the command line is the only source that answers for
    every channel. Declared, never inferred -- the same rule that fixed
    the HUD's model badge on 2026-08-04.
    """
    parts = cmd.split()
    for i, part in enumerate(parts):
        if part == "--model" and i + 1 < len(parts):
            return parts[i + 1]
        if part.startswith("--model="):
            return part.split("=", 1)[1]
    return ""


def classify(chain_cmds: list[str], cwd: str = "") -> str:
    """Which channel this session is: voice line, terminal line, or terminal.

    Keyed on the ANCESTOR CHAIN, not on cwd -- the voice brain and a
    terminal session both run with cwd at the Jarvis root, so cwd alone
    cannot tell them apart. The brain is a descendant of the server that
    spawned it, and that is what makes it identifiable.
    """
    for cmd in chain_cmds:
        if "voice-web-server.py" in cmd:
            return "voice line"
        if "voice-line/main.py" in cmd or cmd.endswith("main.py"):
            return "terminal line"
    if cwd:
        real = os.path.realpath(cwd)
        # realpath on both sides: the probe showed hook payloads arrive
        # symlink-resolved, so a raw string compare misses.
        if real == os.path.realpath(os.path.join(JARVIS_ROOT, "Jarvis Visual")):
            return "terminal (Jarvis Visual)"
        if real == os.path.realpath(JARVIS_ROOT):
            return "terminal (Jarvis root)"
    return "terminal"


def build_record(event: str, payload: dict, session: dict | None,
                 chain_cmds: list[str], now: float) -> dict:
    """One registry line. Pure: everything it needs is passed in."""
    cwd = payload.get("cwd") or ""
    cmd = (session or {}).get("cmd", "")
    return {
        "ts": now,
        "event": event,
        "session_id": payload.get("session_id") or "",
        "transcript_path": payload.get("transcript_path") or "",
        "cwd": os.path.realpath(cwd) if cwd else "",
        "pid": (session or {}).get("pid"),
        "pid_started": (session or {}).get("started"),
        "channel": classify(chain_cmds, cwd),
        # From the command line, not the payload -- see model_from_cmd.
        "model": model_from_cmd(cmd),
        "source": payload.get("source") or "",
        "reason": payload.get("reason") or "",
    }


# --------------------------------------------------------------------------
# writer
# --------------------------------------------------------------------------

def append_record(rec: dict, path: Path | None = None) -> None:
    """Append one line, then trim. Never raises -- a hook that can break a
    session is worse than no hook."""
    f = path or SESSIONS_FILE
    try:
        with f.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        lines = f.read_text().splitlines()
        if len(lines) > TRIM_AT:
            tmp = f.with_suffix(f.suffix + ".tmp")
            tmp.write_text("\n".join(lines[-KEEP:]) + "\n")
            tmp.replace(f)
    except Exception:
        pass


# --------------------------------------------------------------------------
# resolver
# --------------------------------------------------------------------------

def fold_sessions(lines: list[str]) -> dict[str, dict]:
    """Fold the append-only log into per-session current state.

    Later lines win, so a resume or a repeated start updates the row rather
    than duplicating it. An `end` marks the row ended -- but that is only a
    hint; liveness is decided by the process table, because a killed
    session never gets to write one.
    """
    out: dict[str, dict] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            # One garbage line costs one row, not the panel.
            continue
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id")
        if not sid:
            continue
        cur = out.setdefault(sid, {"session_id": sid, "ended": False})
        if rec.get("event") == "end":
            cur["ended"] = True
            cur["ended_at"] = rec.get("ts")
            cur["reason"] = rec.get("reason", "")
            continue
        cur.update({k: rec.get(k) for k in
                    ("transcript_path", "cwd", "pid", "pid_started",
                     "channel", "model", "source")})
        cur["started_at"] = rec.get("ts")
        # A fresh start for the same id (a resume) revives the row.
        cur["ended"] = False
    return out


def is_live(row: dict, table: dict[int, dict]) -> bool:
    """Is this session's process still there, and still the SAME process?

    Three tests, and all three matter:
      1. the pid exists at all;
      2. it is still a claude -- a pid can be recycled by anything;
      3. its start time matches what was recorded -- the pid-reuse guard,
         because a recycled pid running a different claude session would
         otherwise read as this one.
    """
    pid = row.get("pid")
    if not isinstance(pid, int):
        return False
    rec = table.get(pid)
    if not rec or not is_claude(rec.get("cmd", "")):
        return False
    want, got = row.get("pid_started"), rec.get("started")
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        if abs(want - got) > START_TOLERANCE_S:
            return False
    return True


_CWD_CACHE: dict[tuple[int, float | None], str] = {}


def cwd_of(pid: int, started: float | None = None) -> str:
    """A live process's working directory, or "" if it cannot be read.

    Only ever called for a live claude that wrote NO registry record, which
    is normally none of them -- so the subprocess cost is paid on the
    exception, not on every poll. Cached on (pid, start time) rather than
    pid alone, so a recycled pid is looked up again instead of inheriting
    the dead process's answer.
    """
    key = (pid, started)
    if key in _CWD_CACHE:
        return _CWD_CACHE[key]
    out = ""
    try:
        res = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                             capture_output=True, text=True, timeout=5).stdout
        for line in res.splitlines():
            if line.startswith("n"):
                out = line[1:].strip()
                break
    except Exception:
        out = ""
    _CWD_CACHE[key] = out
    return out


def in_jarvis(cwd: str) -> bool:
    """Is this session working inside the Jarvis folder?

    An UNKNOWN cwd counts as yes, on purpose. Hiding a real Jarvis is the
    exact failure this registry exists to end -- on 2026-08-05 the CLI
    printed "no Jarvis sessions running" while two were alive -- whereas an
    extra row is visible, labelled and self-correcting. Over-report, never
    under-report.
    """
    if not cwd:
        return True
    real = os.path.realpath(cwd)
    root = os.path.realpath(JARVIS_ROOT)
    return real == root or real.startswith(root + os.sep)


def read_sessions(path: Path | None = None,
                  table: dict[int, dict] | None = None) -> list[dict]:
    """Every Jarvis session alive right now, newest first.

    THE PROCESS TABLE DRIVES THIS LIST; THE LOG ONLY NAMES WHAT IT FINDS.
    That order is load-bearing, and it is the second design of this
    function. The first walked the log and used `ps` merely to filter it --
    which meant a session that never wrote a start record could not appear
    at all. On 2026-08-05 that is exactly what happened: the hooks were
    installed at 11:55, and `jarvis.sh sessions` reported "no Jarvis
    sessions running" while two were. Serge caught it from the page --
    "I thought that Jarvis had more than one session."

    A registry that can only see the sessions which cooperated at boot is
    the hand-signed Session Board rebuilt in code: same trust, same blind
    spot, one less human. So anything alive is listed, and one that never
    announced itself is listed as `unregistered` rather than dropped.

    `table` is injectable so the tests can drive every case without
    spawning real processes.
    """
    f = path or SESSIONS_FILE
    try:
        lines = f.read_text().splitlines()
    except Exception:
        lines = []
    procs = process_table() if table is None else table

    # The log, indexed by the pid it claims -- but only where the process
    # table agrees that process is still the same session (is_live carries
    # the pid-reuse guard).
    by_pid: dict[int, dict] = {}
    for row in fold_sessions(lines).values():
        if is_live(row, procs):
            by_pid[row["pid"]] = row

    now = time.time()
    rows = []
    for pid, rec in procs.items():
        if not is_claude(rec.get("cmd", "")):
            continue
        row = by_pid.get(pid)
        if row is None:
            # Alive, and it never wrote a start record. Everything below is
            # still derivable from the process itself -- the channel from
            # its ancestry, the model from its command line -- so the row is
            # useful even though the hook never ran.
            cwd = cwd_of(pid, rec.get("started"))
            if not in_jarvis(cwd):
                continue          # someone else's project, not a Jarvis
            row = {
                "session_id": "",
                "ended": False,
                "transcript_path": "",
                "cwd": cwd,
                "pid": pid,
                "pid_started": rec.get("started"),
                "channel": classify(channel_chain(pid, procs), cwd),
                "model": model_from_cmd(rec.get("cmd", "")),
                "source": "",
                "started_at": rec.get("started"),
                "unregistered": True,
            }
        else:
            row = dict(row)
            row["unregistered"] = False
        row["age"] = max(0.0, now - (row.get("started_at") or 0))
        # Last activity from the transcript's own mtime: the session writes
        # to it on every turn, so it answers "is this one actually working"
        # without asking the session anything.
        try:
            row["last_activity"] = os.path.getmtime(row["transcript_path"])
        except Exception:
            row["last_activity"] = None
        rows.append(row)
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return rows


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------

def _fmt_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def cmd_list() -> int:
    rows = read_sessions()
    if not rows:
        print("no Jarvis sessions running.")
        return 0
    print(f"{len(rows)} Jarvis session(s) running:")
    for r in rows:
        last = r.get("last_activity")
        idle = f"idle {_fmt_age(time.time() - last)}" if last else "idle --"
        print(f"  {r.get('channel', '?'):<26} pid {r.get('pid'):<8}"
              f" up {_fmt_age(r.get('age', 0)):<10} {idle:<14}"
              f" {(r.get('model') or '?')}")
        print(f"    session {r.get('session_id', '')}  cwd {r.get('cwd', '')}")
    return 0


def main(argv: list[str]) -> int:
    """Always exits 0 on the hook paths. A registry that can kill a session
    would cost far more than the registry is worth."""
    mode = argv[1] if len(argv) > 1 else ""
    if mode == "--list":
        try:
            return cmd_list()
        except Exception as e:
            print(f"session registry unavailable: {e}", file=sys.stderr)
            return 1
    if mode not in ("start", "end"):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            payload = {}
        table = process_table()
        session = owning_session(os.getpid(), table)
        chain = channel_chain(os.getpid(), table)
        append_record(build_record(mode, payload, session, chain, time.time()))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
