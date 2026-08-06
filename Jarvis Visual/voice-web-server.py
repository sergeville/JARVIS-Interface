"""JARVIS in the browser: voice + visual server.

Serves the ring page, mirrors the voice line's signal files on
/signals (so the ring still follows the Terminal voice line), and runs
a full browser voice channel on the /voice WebSocket: the page sends a
WAV of what Serge said (or a typed line), this server transcribes it
with the local whisper, streams the reply from the same warm Claude
brain the voice line uses, synthesizes each chunk with Kokoro, and
ships the audio back for the page to play.

Run from the voice-line project so its environment applies:
    cd ~/Documents/Jarvis/voice-line && uv run python \
        "../Jarvis Visual/voice-web-server.py"
(run-visual.sh does exactly this)
"""

import asyncio
import base64
import io
import json
import os
import platform
import re
import socket
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
from aiohttp import WSMsgType, web

# The project root, derived from this file's own location rather than written
# in. Nothing about it can be supplied by a caller -- not argv, not the
# environment, not stdin -- so it is exactly as trustworthy as a literal was,
# and it is correct in any clone. realpath because macOS hands back
# symlink-resolved paths (/tmp -> /private/tmp) and these values get compared
# against cwds that arrive already resolved.
JARVIS_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VOICE_LINE = os.path.join(JARVIS_ROOT, "voice-line")
sys.path.insert(0, VOICE_LINE)

from claude_agent_sdk import (                  # noqa: E402
    PermissionResultAllow, PermissionResultDeny)

from brain import Brain, WARMUP_PROMPT          # noqa: E402
# The registry lives in voice-line/ beside the hook that writes it, so the
# writer, this reader and `jarvis.sh sessions` can never disagree about the
# record's shape. Liveness is decided there, from the process table.
import session_registry                        # noqa: E402
# The session notice bus, same folder and same reason. Read-only here: this
# server never POSTS a notice, it only shows them, so nothing on the page can
# become a way for one session to speak to another.
import session_mail                            # noqa: E402
from ears import VOCAB_PROMPT, clean_transcript  # noqa: E402
# "as voice_signals": the /signals route handler below owns the bare name
import signals as voice_signals                 # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = HERE / "jarvis.html"
STATE_FILE = Path(VOICE_LINE) / ".voice_state"
WAVEFORM_FILE = Path(VOICE_LINE) / ".voice_waveform"
HEARTBEAT_FILE = Path(VOICE_LINE) / ".voice_heartbeat"
TRANSCRIPT_FILE = Path(VOICE_LINE) / ".voice_transcript"
INBOX_DIR = Path(VOICE_LINE) / ".voice_inbox.d"
QUESTION_FILE = Path(VOICE_LINE) / ".voice_question"
# Claude plan usage, published by ~/.claude/statusline-command.sh on every
# status-line render (Serge, 2026-08-04). That payload is the ONLY place the
# plan percentages and reset clocks exist -- OTel, ccusage and the raw session
# logs give tokens and cost but never the percentages. The writer is atomic
# (temp file then mv), so a partial read is not possible; a missing file just
# means no Claude Code terminal has rendered a status line yet.
USAGE_FILE = Path(VOICE_LINE) / ".usage.json"
# Stack events -- append-only, one JSON object per line (Serge, 2026-08-05:
# "when I restart, is there something that tells you the system is restarting?
# ... I want you to know everything").
#
# It lives OUTSIDE this process on purpose. A restart kills the server and the
# brain with it, so anything held in memory dies exactly when the interesting
# thing happens. On disk, the record outlives the event it describes -- which
# is what lets a brand-new brain read its own birth certificate at boot and
# know it was just restarted, when, and whether Serge did it or something died.
#
# Three writers, and they do NOT overlap: jarvis.sh writes what only it can see
# (a stop beginning, a stop verified clean, a start), this server writes its own
# birth and its brain events, and the stack sampler writes anything that changes
# state without announcing itself. That third one is the catch-all -- a crash
# tells nobody, but it still shows up in the next 3-second sample.
EVENTS_FILE = Path(VOICE_LINE) / ".stack-events.jsonl"
EVENTS_KEEP = 200        # lines retained after a trim
EVENTS_TRIM_AT = 400     # trim once the file grows past this
PRIORITIES_FILE = Path(JARVIS_ROOT) / "Jarvis-brain" / "Active Priorities.md"
HEARTBEAT_STALE_S = 15.0

UPLOADS_DIR = HERE / "uploads"      # images pasted/dropped on the page

_TASK_CACHE: dict = {"mtime": None, "tasks": []}


def read_tasks() -> list[dict]:
    """Open tasks from Active Priorities, for the page's task card.

    Entry shape in the note (see the note's own legend):
        - [ ] **Title** (project)
          - status: active
          - owner: voice line
          ...
    The vault note is the single source of truth; this only mirrors it.
    """
    try:
        mtime = PRIORITIES_FILE.stat().st_mtime
        if mtime == _TASK_CACHE["mtime"]:
            return _TASK_CACHE["tasks"]
        text = PRIORITIES_FILE.read_text()
    except Exception:
        return _TASK_CACHE["tasks"]
    tasks: list[dict] = []
    task: dict | None = None
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("### ") and "Open Tasks" not in stripped:
            break                    # done: reached Completed Tasks
        if stripped.startswith("- [ ] **"):
            title = stripped[len("- [ ] **"):]
            title, _, rest = title.partition("**")
            project = rest.strip().strip("()")
            task = {"title": title.strip(), "project": project,
                    "status": "open", "owner": "unassigned",
                    "priority": "", "updated": "", "note": ""}
            tasks.append(task)
        elif stripped.startswith("- [x] **"):
            # A completed task used to only CLOSE the open one above it, so
            # the board's DONE column could never show anything. Serge,
            # 2026-08-06: "it's okay that you treat as a finish, but it should
            # be a time to live before it does disappear, so the user would
            # see it done. Maybe the next day it's disappeared."
            #
            # So it now becomes a task in its own right -- and it STILL closes
            # the previous one, which is what the 2026-08-05 bleed fix was
            # actually for: a "- status: done" line under a finished entry
            # must never attach itself to the last open task.
            title = stripped[len("- [x] **"):]
            title, _, rest = title.partition("**")
            task = {"title": title.strip(),
                    "project": rest.strip().strip("()"),
                    "status": "done", "owner": "unassigned",
                    "priority": "", "updated": "", "note": "",
                    "_closed": True}
            tasks.append(task)
        elif stripped.startswith("- [x] "):
            # A checked line that is not a task entry still closes the open
            # task above it, for the same bleed reason.
            task = None
        elif task is not None and stripped.startswith("- ") and ":" in stripped:
            key, _, value = stripped[2:].partition(":")
            key = key.strip().lower()
            if key in task:
                # Strip wikilink brackets: the card shows plain text.
                task[key] = value.strip().replace("[[", "").replace("]]", "")
    tasks = _expire_done(tasks)
    _TASK_CACHE.update(mtime=mtime, tasks=tasks)
    return tasks


def _expire_done(tasks: list[dict]) -> list[dict]:
    """Drop finished tasks once their day is over.

    Serge's shape, 2026-08-06: a closed task stays on the board for the rest
    of the day it was closed and is gone at the next day's rollover -- long
    enough to see it land, short enough that DONE never becomes an archive.
    No arithmetic on his side: "maybe the next day it's disappeared."

    A finished task with NO `updated` stamp is dropped rather than kept. That
    is deliberate and it is what keeps the condensed one-line entries under
    Completed Tasks off the board: an item with no date cannot be shown to be
    recent, and defaulting an undated item to *visible* would slowly fill the
    column with everything ever finished.
    """
    today = time.strftime("%Y-%m-%d")
    kept = []
    for t in tasks:
        if t.pop("_closed", False):
            t["status"] = "done"     # the checkbox outranks a stale field
            if t.get("updated", "")[:10] != today:
                continue
        kept.append(t)
    return kept


VAULT_DIR = Path(JARVIS_ROOT) / "Jarvis-brain"
_GRAPH_CACHE: dict = {"ts": 0.0, "data": {"nodes": [], "edges": []}}
GRAPH_RESCAN_S = 10.0
_WIKILINK_RE = re.compile(r"\[\[([^\]\[]+)\]\]")


def scan_vault_graph() -> dict:
    """Nodes and wikilink edges for the page's 3D vault graph.

    One node per markdown note; an edge per resolved [[wikilink]]
    (alias and heading parts stripped, matched to note names
    case-insensitively, Obsidian-style). Rescans at most every
    GRAPH_RESCAN_S; the vault is small, so a scan is a few ms.
    """
    now = time.monotonic()
    if now - _GRAPH_CACHE["ts"] < GRAPH_RESCAN_S:
        return _GRAPH_CACHE["data"]
    _GRAPH_CACHE["ts"] = now
    try:
        notes = [p for p in VAULT_DIR.rglob("*.md")
                 if not any(part.startswith(".") for part in
                            p.relative_to(VAULT_DIR).parts)]
        by_name = {p.stem.lower(): i for i, p in enumerate(notes)}
        nodes = [{"id": p.stem,
                  "folder": (p.relative_to(VAULT_DIR).parts[0]
                             if len(p.relative_to(VAULT_DIR).parts) > 1
                             else ""),
                  "links": 0}
                 for p in notes]
        edges: set[tuple[int, int]] = set()
        for i, p in enumerate(notes):
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            for m in _WIKILINK_RE.finditer(text):
                target = m.group(1).split("|")[0].split("#")[0].strip()
                j = by_name.get(target.lower())
                if j is not None and j != i:
                    edges.add((min(i, j), max(i, j)))
        for i, j in edges:
            nodes[i]["links"] += 1
            nodes[j]["links"] += 1
        _GRAPH_CACHE["data"] = {"nodes": nodes,
                                "edges": [list(e) for e in sorted(edges)]}
    except Exception as e:
        print(f"vault graph scan failed: {e}", flush=True)
    return _GRAPH_CACHE["data"]


def terminal_alive() -> bool:
    try:
        return (time.time() - float(HEARTBEAT_FILE.read_text())
                < HEARTBEAT_STALE_S)
    except Exception:
        return False


# ---- real Mac numbers for the page's SYS MONITOR panel ----------------
# Sampled on a background timer; /signals polls at 15 Hz and must only ever
# read this cache, never spawn a process.
#
# Serge, 2026-08-05: "the CPU, the MEM, I think it does not refresh fast
# enough." He was right and it was the sample rate, not the drawing -- this
# slept 2.0 s between samples, so the panel could be two seconds behind the
# machine and the sparkline would have drawn half as much history per minute.
# One second is the floor worth having: each sample shells out to ps -A,
# vm_stat and netstat, and going below a second buys smoothness Serge cannot
# see while spending real CPU on measuring CPU.
STATS_EVERY_S = 1.0
_STATS: dict = {
    "cpu": 0.0, "mem": 0.0, "net_kbs": 0.0, "uptime_s": 0, "procs": 0,
    "os": "macOS " + (platform.mac_ver()[0] or "?"),
    # Stamped on every sample so the page can tell a NEW reading from the same
    # one polled again. Without it the sparkline cannot distinguish "the CPU
    # held steady for a second" from "we polled the same sample fifteen times".
    "at": 0.0,
}
NCPU = os.cpu_count() or 1


async def _cmd(*argv: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return out.decode(errors="replace")


async def sample_stats() -> None:
    try:
        mem_total = float(await _cmd("sysctl", "-n", "hw.memsize"))
    except Exception:
        mem_total = 0.0
    m = re.search(r"sec\s*=\s*(\d+)",
                  await _cmd("sysctl", "-n", "kern.boottime"))
    boot_s = float(m.group(1)) if m else 0.0
    last_bytes: int | None = None
    last_t = 0.0
    while True:
        try:
            # One ps call feeds both CPU (%cpu summed over all processes,
            # scaled to the machine) and the process count.
            ps_lines = (await _cmd("ps", "-A", "-o", "%cpu")).splitlines()[1:]
            cpu = sum(float(x) for x in ps_lines if x.strip()) / NCPU
            vm = await _cmd("vm_stat")
            pm = re.search(r"page size of (\d+)", vm)
            page = int(pm.group(1)) if pm else 16384
            pages: dict[str, int] = {}
            for line in vm.splitlines():
                key, _, val = line.partition(":")
                val = val.strip().rstrip(".")
                if val.isdigit():
                    pages[key.strip()] = int(val)
            used = (pages.get("Pages active", 0)
                    + pages.get("Pages wired down", 0)
                    + pages.get("Pages occupied by compressor", 0)) * page
            # Physical interfaces only (en*): loopback and tunnels would
            # double-count the same traffic. netstat repeats an interface
            # per address; the counters are identical, so first row wins.
            seen: set[str] = set()
            total_bytes = 0
            for line in (await _cmd("netstat", "-ib")).splitlines()[1:]:
                f = line.split()
                if len(f) >= 10 and f[0].startswith("en") and f[0] not in seen:
                    try:
                        total_bytes += int(f[6]) + int(f[9])
                        seen.add(f[0])
                    except ValueError:
                        pass
            now = time.monotonic()
            net_kbs = _STATS["net_kbs"]
            if last_bytes is not None and now > last_t:
                net_kbs = max(
                    0.0, (total_bytes - last_bytes) / (now - last_t) / 1024)
            last_bytes, last_t = total_bytes, now
            _STATS.update(
                cpu=round(min(100.0, cpu), 1),
                mem=round(used / mem_total * 100, 1) if mem_total else 0.0,
                net_kbs=round(net_kbs, 1),
                uptime_s=int(time.time() - boot_s) if boot_s else 0,
                procs=len(ps_lines),
                at=time.time(),
            )
        except Exception as e:
            print(f"stats sample failed: {e}", flush=True)
        await asyncio.sleep(STATS_EVERY_S)

# ---- the whole stack, at a glance, for the page's SYS MONITOR -----------
# Serge, 2026-08-04: he wanted everything `./jarvis.sh status` prints -- every
# component with its PID, the three ports, whether the page really answers --
# visible on the page instead of only in a terminal he isn't looking at.
#
# The process patterns are deliberately the SAME strings jarvis.sh matches on
# (its P_SERVER/P_BRAIN/P_LINE/P_WHISPER/P_KOKORO). If one moves, move both --
# a panel that disagrees with the script is worse than no panel.
#
# Sampled on its own slow timer like _STATS; /signals only ever reads the
# cache. Ports are checked by bind, not by shelling out to lsof.
STACK_SPECS = [
    ("browser Jarvis", "voice-web-server.py", 8765),
    ("brain", "claude_agent_sdk/_bundled/claude", None),
    ("terminal line", "voice-line/main.py", None),
    ("whisper", "whisper-server", 2022),
    ("kokoro", "api.src.main:app", 8880),
]
# The terminal voice line is off unless Serge starts it himself, so "down"
# reads as a failure when it is a choice. Named channels get their own word.
STACK_OPTIONAL = {"terminal line"}

_STACK: dict = {"components": [], "ports": {}, "page": "unknown"}


def _port_free(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _lstart_epoch(row: str) -> float | None:
    """Epoch seconds from a `ps -o lstart=` field ("Tue Aug  4 21:00:44 2026").

    macOS ps has no `etimes` keyword (checked, 2026-08-04), so elapsed time is
    computed from the absolute start stamp rather than read off ps directly.

    BOTH field orders are parsed, and that is measured, not defensive: on this
    machine `ps` prints "Tue  4 Aug 07:23:24 2026" -- DAY BEFORE MONTH -- not
    the documented "Tue Aug  4 ...". Assuming one order made this return None
    for every process, so the STACK panel served `since: null` on every row and
    its start times and uptimes silently showed nothing. Found 2026-08-05 while
    building the session registry, whose own parser hit the same trap.

    The slice stays positional -- fields 1..5, after the pid. It CANNOT take
    the last five tokens the way the registry's parser does: this is handed a
    full `pid=,lstart=,command=` row, so the tail is the command line, not the
    date. (Caught while making this fix; the same shape in two files does not
    make them the same problem.)
    """
    parts = row.split()
    if len(parts) < 6:
        return None
    tail = " ".join(parts[1:6])
    for fmt in ("%a %d %b %H:%M:%S %Y", "%a %b %d %H:%M:%S %Y"):
        try:
            return time.mktime(time.strptime(tail, fmt))
        except ValueError:
            continue
    return None


def log_event(kind: str, label: str, detail: str = "",
              path: Path | None = None) -> None:
    """Append one stack event. Never raises -- a logger that can break the
    server it watches is worse than no logger.

    Opened in append mode per call rather than held open: jarvis.sh writes to
    this same file from bash, and O_APPEND on short lines is what keeps the two
    from interleaving. Small and rare enough that the open costs nothing.
    """
    f = path or EVENTS_FILE
    try:
        rec = {"ts": time.time(), "kind": kind, "label": label,
               "detail": detail}
        with f.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        # Trim in place, oldest first. Checked cheaply on every write because
        # the file is tiny; the cost only lands once past the threshold.
        lines = f.read_text().splitlines()
        if len(lines) > EVENTS_TRIM_AT:
            tmp = f.with_suffix(f.suffix + ".tmp")
            tmp.write_text("\n".join(lines[-EVENTS_KEEP:]) + "\n")
            tmp.replace(f)
    except Exception as e:
        print(f"stack event log failed: {e}", flush=True)


_EVENT_CACHE: dict = {"key": None, "events": []}


def read_events(limit: int = 20, path: Path | None = None) -> list[dict]:
    """The most recent events, newest first. Unparseable lines are skipped
    rather than fatal -- a half-written line from a concurrent bash append
    should cost one row, not the panel.
    """
    f = path or EVENTS_FILE
    # /signals is polled at 15 Hz, so this is cached on the file's identity
    # rather than re-read every frame -- same pattern as _TASK_CACHE.
    # Keyed on (mtime_ns, size): an append always changes the size, and a trim
    # rewrites the file, so no real change can slip past both.
    try:
        st = f.stat()
        key = (str(f), st.st_mtime_ns, st.st_size)
    except Exception:
        return []
    if _EVENT_CACHE["key"] == key:
        return _EVENT_CACHE["events"][:limit]
    try:
        lines = f.read_text().splitlines()
    except Exception:
        return []
    out = []
    for line in reversed(lines):
        # Parse to the retention cap, not to `limit`, so one cache entry can
        # serve any caller's limit.
        if len(out) >= EVENTS_KEEP:
            break
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict) and "ts" in rec:
            out.append({"ts": rec.get("ts"), "kind": rec.get("kind", "info"),
                        "label": rec.get("label", ""),
                        "detail": rec.get("detail", "")})
    _EVENT_CACHE.update(key=key, events=out)
    return out[:limit]


_SESSION_CACHE: dict = {"at": 0.0, "rows": []}
SESSION_TTL_S = 3.0


def read_sessions() -> list[dict]:
    """Live Jarvis sessions, newest first, for /signals.

    Cached on a short TTL rather than on the file's identity like
    read_events() and read_tasks(): those change only when the file changes,
    but a session can DIE without anyone writing a line -- that is the whole
    premise -- so the answer goes stale on its own and must be re-derived
    from the process table on a clock. Three seconds matches the stack
    sampler; /signals is polled at 15 Hz, so this must never run per frame.
    """
    now = time.time()
    if now - _SESSION_CACHE["at"] < SESSION_TTL_S:
        return _SESSION_CACHE["rows"]
    try:
        rows = session_registry.read_sessions()
    except Exception as e:
        print(f"session registry read failed: {e}", flush=True)
        rows = []
    _SESSION_CACHE.update(at=now, rows=rows)
    return rows


_MAIL_CACHE: dict = {"key": None, "rows": []}


def read_mail() -> list[dict]:
    """The session bus notices, newest first, for /signals.

    Cached on the file's (mtime_ns, size) -- NOT on a clock like
    read_sessions(). The difference is deliberate and follows the data: this
    file only changes when something is actually written to it, so a stale
    read is impossible, whereas a session can die with nothing written at
    all. Same shape as _TASK_CACHE and the events cache; /signals is polled
    at 15 Hz and this must never re-read per frame.
    """
    try:
        st = os.stat(session_mail.MAIL_FILE)
        key = (st.st_mtime_ns, st.st_size)
    except Exception:
        _MAIL_CACHE.update(key=None, rows=[])
        return []
    if key == _MAIL_CACHE["key"]:
        return _MAIL_CACHE["rows"]
    try:
        rows = session_mail.read_mail(limit=12)
    except Exception as e:
        print(f"session mail read failed: {e}", flush=True)
        rows = []
    _MAIL_CACHE.update(key=key, rows=rows)
    return rows


def diff_stack(prev: list[dict] | None,
               cur: list[dict]) -> list[tuple[str, str, str]]:
    """Events implied by one stack sample following another.

    Returns (kind, label, detail) triples. Pure -- it touches no files and no
    clock, which is the whole reason it lives apart from the sampler.

    prev is None on the very first sample after boot: there is no transition to
    describe yet, and emitting one row per component would bury the real events
    under a wall of noise at every start. So: baseline silently, report changes.
    """
    if prev is None:
        return []
    was = {c["label"]: c for c in prev}
    out = []
    for c in cur:
        label = c["label"]
        old = was.get(label)
        if old is None:
            continue                      # a component added mid-run; nothing to compare
        if old["state"] != c["state"]:
            # "off" is a choice (the terminal line), "down" is a problem --
            # the same three-state doctrine the STACK dots already use.
            detail = {"up": "came up", "off": "stood down",
                      "down": "went down"}.get(c["state"], c["state"])
            out.append((c["state"], label, detail))
        elif (c["state"] == "up" and old.get("pids") and c.get("pids")
              and old["pids"] != c["pids"]):
            # Same component, still up, different process: it was replaced
            # without ever reading as down between two samples. This is what a
            # brain rebuild looks like from the outside.
            out.append(("up", label,
                        f"restarted (pid {','.join(old['pids'])} -> "
                        f"{','.join(c['pids'])})"))
    return out


_STACK_PREV: list[dict] | None = None


async def sample_stack() -> None:
    global _STACK_PREV
    while True:
        try:
            # One ps -A pass feeds every pattern. `ps` (not pgrep) on purpose:
            # pgrep cannot see processes in its own tree, which is exactly the
            # blind spot that made a stop kill nothing on 2026-08-04.
            rows = (await _cmd("ps", "-A", "-o",
                               "pid=,lstart=,command=")).splitlines()
            comps = []
            for label, pat, port in STACK_SPECS:
                matched = [r for r in rows if pat in r and " grep " not in r]
                pids = [r.split(None, 1)[0] for r in matched]
                # Serge, 2026-08-04: start time + how long it has been up, per
                # component -- the youngest row is usually the thing that just
                # broke and got restarted. Oldest match wins: the `uv` wrapper
                # and the server it spawns are one component, and the wrapper
                # is when the component really began.
                starts = [s for s in (_lstart_epoch(r) for r in matched)
                          if s is not None]
                comps.append({
                    "label": label,
                    "pids": pids,
                    "state": ("up" if pids
                              else ("off" if label in STACK_OPTIONAL
                                    else "down")),
                    "port": port,
                    "since": min(starts) if starts else None,
                })
            ports = {str(p): ("free" if _port_free(p) else "held")
                     for p in (8765, 2022, 8880)}
            # No page check here, deliberately. This code IS what serves the
            # page, so any answer it gave would be "yes" by construction --
            # the panel rendering at all is the real proof. The genuine
            # outside-in check stays in jarvis.sh, where it means something.
            for kind, label, detail in diff_stack(_STACK_PREV, comps):
                log_event(kind, label, detail)
            _STACK_PREV = comps
            _STACK.update(components=comps, ports=ports)
        except Exception as e:
            print(f"stack sample failed: {e}", flush=True)
        await asyncio.sleep(3.0)


def read_usage() -> dict | None:
    """Claude plan usage from USAGE_FILE, or None if there is nothing to show.

    Read straight off disk rather than cached: it changes only when a status
    line renders, and the file is tiny.

    `age` is the point of the whole function. The file refreshes only while
    some Claude Code terminal is rendering its status line -- the browser
    brain has none -- so a number here can be minutes or hours old. The page
    shows the age instead of implying the reading is live. A panel that lies
    about freshness is worse than no panel.
    """
    try:
        raw = json.loads(USAGE_FILE.read_text())
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    written = raw.get("written_at")
    # The poller (sample_usage) asks Claude Code directly and needs no
    # terminal, so its plan rows win whenever they are newer than the file's.
    # ctx_pct is per-session and only the status line has it, so it is left
    # alone. `written_at` becomes the newer of the two, since `age` is what
    # the page shows and it must describe the numbers actually drawn.
    poll, poll_at = _USAGE_POLL.get("data"), _USAGE_POLL.get("at")
    # `>=`, not `>`: on an exact tie the poll wins, because it asked Claude
    # Code directly while the file is whatever a terminal last happened to
    # leave behind.
    if poll and poll_at and poll_at >= (written or 0):
        raw = {**raw, **poll, "written_at": poll_at}
        written = poll_at
    if not raw:
        return None
    # All-null means the payload carried no rate limits (it is marked
    # "only present for subscribers after first API response"). Nothing to
    # draw, so say so rather than rendering a row of dashes.
    if not any(raw.get(k, {}).get("pct") is not None
               for k in ("five_hour", "seven_day")) \
            and raw.get("ctx_pct") is None:
        return None
    return {**raw,
            "age": (time.time() - written) if isinstance(written, (int, float))
                   else None}


# --- Usage poller (Serge, 2026-08-04 ~10:36 PM) -----------------------------
# The status-line publisher above only writes while some Claude Code terminal
# is rendering its prompt. The browser brain has none, so the panel can sit
# blank or stale for hours -- which is exactly what Serge hit tonight. This
# poller asks Claude Code itself instead: `claude -p "/usage"` returns the plan
# percentages and reset clocks on demand, with no terminal required.
#
# It costs tokens: each poll spawns a real session against Serge's own limits.
# Five minutes is the deliberate floor -- the numbers move slowly and measuring
# the fuel should not burn it. Do not tighten this without asking him.
#
# `/usage` gives plan percentages only; the context percent is per-session and
# has no meaning here, so ctx_pct still comes from the status-line file.
#
# PAUSED AT BOOT, and that is Serge's explicit call (2026-08-05 ~8:25 AM):
# "so I don't burn token for nothing." The poller does nothing at all until he
# switches it on from the HUD, and the switch is not persisted -- every restart
# comes back paused, which is the safe direction to fail. Turning it on polls
# immediately, then holds the five-minute floor.
USAGE_POLL_S = 300.0
_USAGE_POLL: dict = {"data": None, "at": None}
# Set = running, clear = paused. Created unset, so boot is paused.
_USAGE_RUN = asyncio.Event()

_USAGE_ROW = re.compile(
    r"Current (session|week \(all models\)|week \(([^)]+)\))\s*:\s*"
    r"(\d+)%\s*used(?:\s*·\s*resets\s+([^(\n]+))?", re.I)


def _usage_reset_epoch(phrase: str) -> float | None:
    """'Aug 5 at 10pm' / 'Aug 4 at 10:50pm' -> epoch, or None.

    The year is absent from the phrase, so it is assumed to be the current
    one; a reset always lands within days, so that holds. If the result is
    more than a day in the past, roll to next year (a Dec/Jan boundary).
    """
    s = phrase.strip().rstrip(".")
    for fmt in ("%b %d at %I:%M%p", "%b %d at %I%p", "%b %d %I:%M%p"):
        try:
            t = datetime.strptime(s, fmt)
        except ValueError:
            continue
        now = datetime.now()
        stamp = t.replace(year=now.year)
        if (now - stamp).total_seconds() > 86400:
            stamp = stamp.replace(year=now.year + 1)
        return stamp.timestamp()
    return None


def _parse_usage_output(out: str) -> dict | None:
    """Pull the plan rows out of `claude -p "/usage"` text output."""
    found: dict = {}
    for m in _USAGE_ROW.finditer(out):
        kind, pct, when = m.group(1).lower(), int(m.group(3)), m.group(4)
        row = {"pct": pct,
               "resets_at": _usage_reset_epoch(when) if when else None}
        if kind == "session":
            found["five_hour"] = row
        elif kind == "week (all models)":
            found["seven_day"] = row
    return found or None


async def sample_usage() -> None:
    while True:
        # Paused costs nothing: the task parks here until Serge switches it on.
        await _USAGE_RUN.wait()
        try:
            out = await _cmd("claude", "-p", "/usage")
            parsed = _parse_usage_output(out)
            if parsed:
                _USAGE_POLL.update(data=parsed, at=time.time())
            else:
                print("usage poll: no plan rows in output", flush=True)
        except Exception as e:
            print(f"usage poll failed: {e}", flush=True)
        # Slept in one-second slices rather than one long sleep so a pause
        # takes effect within a second instead of up to five minutes later.
        for _ in range(int(USAGE_POLL_S)):
            if not _USAGE_RUN.is_set():
                break
            await asyncio.sleep(1.0)


async def usage_poll(request: web.Request) -> web.Response:
    """GET reports the switch; POST {"on": bool} flips it.

    Serge's control over what the poller spends. No persistence by design --
    see the comment above USAGE_POLL_S.
    """
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        want = bool(body.get("on"))
        if want != _USAGE_RUN.is_set():
            _USAGE_RUN.set() if want else _USAGE_RUN.clear()
            print(f"usage poll: {'ON -- polling' if want else 'PAUSED'}",
                  flush=True)
    return web.json_response({"on": _USAGE_RUN.is_set()},
                             headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# THE APPROVE BUTTON -- the first thing on this page that WRITES to the vault.
#
# Serge, 2026-08-06 ~9:26 AM: "all the review, you're waiting for me, but how
# do I say I'm done? I approve the review. That's why the list is so long. I
# cannot approve, I cannot say nothing. It stays there."
#
# He is the approver and had no way to approve. Review only ever emptied when
# a session got round to hand-editing the note, so the column grew and the one
# person who could clear it could not reach it.
#
# Everything on this page has been read-only until now, so the shape of this
# route matters more than its size. Four constraints, and they are the build:
#
#   1. A CLOSED VOCABULARY. The page sends an ACTION -- "approve" or "send
#      back" -- never a status. There is no path from the browser to an
#      arbitrary status string, so the table below is the entire set of
#      writes this route can ever perform.
#   2. IT CAN ONLY REACH `review`. `only_from` refuses anything else, so the
#      button cannot touch work in flight, and a stale tab cannot move a card
#      that has since gone somewhere else.
#   3. EXACT TITLE MATCH, not a substring, so a title from the page cannot
#      quietly select a different card. Length-capped before it is used.
#   4. ONE WRITER. The edit goes through vault-tools/task.py -- the same
#      surgical, mtime-guarded, atomic write the CLI and the hook use. A
#      second writer would eventually disagree with the first, and this note
#      is edited by other sessions while the server is running.
TASK_ACTIONS = {
    # action     -> (status, what the note's `note:` line will say)
    "approve":   ("done", "APPROVED by Serge on the board"),
    "send-back": ("active", "sent back by Serge on the board -- not approved"),
}
MAX_TITLE = 200

# THE DRAG, added 2026-08-06 on Serge's "you decide" after he unparked it.
#
# The two verdicts above are a closed table of WRITES. A drag cannot be, because
# its whole point is that he chooses the column -- so the closure moves to the
# STATUS SET instead. This tuple is the entire set of statuses a drag can ever
# write, it is the same six the board draws, and anything else is refused
# before task.py is ever called. The page does not get to invent a status.
#
# What deliberately does NOT carry over from the verdict path: `only_from`.
# A verdict may only touch a card in Review; a drag is Serge moving his own
# work and may start anywhere. That is the actual widening, and it is stated
# here rather than buried, because it is the moment this page stopped being
# able to write two values and started being able to write six.
DRAG_STATUSES = (
    "open", "active", "review", "test", "waiting-on-serge", "done",
)
DRAG_NOTE = "moved by Serge on the board"


def _task_tool():
    """vault-tools/task.py, imported by path so it cannot drift from the CLI."""
    import importlib.util
    path = os.path.join(JARVIS_ROOT, "vault-tools", "task.py")
    spec = importlib.util.spec_from_file_location("_task_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def task_move(request: web.Request) -> web.Response:
    """POST {"title": ..., "action": "approve"|"send-back"} -- Serge's verdict.

    Never raises at the caller: every refusal comes back as ok:false with the
    reason, because a button that fails silently is the exact bug that put
    this whole morning's work on the board.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = body.get("title")
    action = body.get("action")
    if not isinstance(title, str) or not title.strip():
        return web.json_response({"ok": False, "error": "no task named"})
    if len(title) > MAX_TITLE:
        return web.json_response({"ok": False, "error": "title too long"})
    # Two shapes on one route, and the difference is the guard, not the path.
    # A verdict names an ACTION and the server chooses the status; a drag names
    # a STATUS and the server refuses anything outside the board's own six.
    if action == "drag":
        status = body.get("status")
        if status not in DRAG_STATUSES:
            return web.json_response({"ok": False, "error": "unknown column"})
        note, only_from = DRAG_NOTE, None
    elif action in TASK_ACTIONS:
        status, note = TASK_ACTIONS[action]
        only_from = ("review",)
    else:
        return web.json_response({"ok": False, "error": "unknown action"})
    try:
        tool = _task_tool()
        moved = await asyncio.to_thread(
            tool.move, title.strip(), status, note,
            exact=True, only_from=only_from)
    except Exception as exc:
        # TaskError carries the reason Serge should read; anything else is a
        # real fault and must not take the request down with it.
        print(f"task-move refused: {exc}", flush=True)
        return web.json_response({"ok": False, "error": str(exc)[:300]})
    _TASK_CACHE["mtime"] = None      # the note just changed under the cache
    print(f"task-move: {moved!r} -> {status} ({action}, by Serge)", flush=True)
    return web.json_response({"ok": True, "title": moved, "status": status},
                             headers={"Cache-Control": "no-store"})


WHISPER_URL = "http://127.0.0.1:2022/v1/audio/transcriptions"
KOKORO_URL = "http://127.0.0.1:8880/v1/audio/speech"
KOKORO_VOICE = "bm_lewis"
HOST, PORT = "127.0.0.1", 8765


def wav_to_16k(wav_bytes: bytes) -> bytes:
    """Any mono 16-bit WAV in, 16 kHz mono WAV out (whisper's diet)."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if rate != 16000:
        n = int(len(audio) * 16000 / rate)
        audio = np.interp(
            np.linspace(0, len(audio) - 1, n),
            np.arange(len(audio)), audio.astype(np.float32),
        ).astype(np.int16)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.tobytes())
    return out.getvalue()


# Serge, 2026-08-06 ~11:05 AM: "maybe a time to live -- if it's more than
# half an hour, then it just cancels itself." So the ONLY two ways a pending
# approval ends are his click and this expiry. It was 300 s before his
# no-cancel rule; the half hour is his number, set in the same breath.
APPROVAL_TIMEOUT_S = 1800.0


class VoiceWeb:
    def __init__(self) -> None:
        self.brain = Brain(can_use_tool=self.ask_permission)
        self.ready = asyncio.Event()
        self.gen = 0                 # bumped on interrupt; stale turns stop
        self.turn_lock = asyncio.Lock()
        self.http = httpx.AsyncClient(timeout=60.0)
        self.approvals: dict[int, dict] = {}   # id -> pending approval
        self._approval_seq = 0

    # ---- HUD approve button ------------------------------------------
    # The brain calls this when a tool needs permission. The request is
    # pushed to every connected page (and mirrored on /signals); the
    # first APPROVE/DENY click anywhere resolves it. Serge's rule
    # (2026-08-06 10:04 AM): NOTHING else ends it -- no interrupt of any
    # kind -- except the half-hour time-to-live he set himself, which
    # counts as a deny so a turn cannot hang forever.
    async def ask_permission(self, tool_name, tool_input, context):
        self._approval_seq += 1
        aid = self._approval_seq
        if tool_name == "Bash":
            detail = (tool_input.get("description")
                      or tool_input.get("command") or "")
        else:
            detail = tool_input.get("file_path") or json.dumps(
                tool_input, default=str)
        detail = str(detail)[:300]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.approvals[aid] = {"id": aid, "tool": tool_name,
                               "detail": detail, "future": fut}
        print(f"approval #{aid} requested: {tool_name} :: {detail}",
              flush=True)
        msg = {"type": "approval", "id": aid,
               "tool": tool_name, "detail": detail}
        for ws in list(WS_CLIENTS):
            await self.safe_send(ws, msg)
        timed_out = False
        try:
            allowed = await asyncio.wait_for(fut, APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            allowed = False
            timed_out = True
        finally:
            self.approvals.pop(aid, None)
            for ws in list(WS_CLIENTS):
                await self.safe_send(ws, {"type": "approval_done",
                                          "id": aid,
                                          "tool": tool_name,
                                          "detail": detail,
                                          "reason": ("timeout" if timed_out
                                                     else "answered")})
        why = ("timed out" if timed_out
               else "allowed" if allowed else "denied")
        print(f"approval #{aid}: {why}", flush=True)
        if allowed:
            return PermissionResultAllow()
        if timed_out:
            return PermissionResultDeny(
                message="NOT RUN -- the permission request timed out with no "
                        "answer. Serge may never have seen it. Tell him, and "
                        "ask again if it still matters.")
        return PermissionResultDeny(
            message="Serge denied this from the HUD. "
                    "Do not retry without asking him.")

    def approval_pending(self) -> bool:
        """True while any permission request is waiting on Serge.

        Serge, 2026-08-06 ~9:55 AM: "again i press enter key lose the
        approve popup." The sticky notice (7b507a4) told him WHAT died;
        this is the half that stops it dying. While a request is pending,
        a typed or spoken message must NOT interrupt -- the popup stays,
        the message queues on turn_lock, and it runs right after the turn
        the approval belongs to. Since Serge's 10:04 AM rule, NO interrupt
        cancels it either -- interrupt() itself holds while this is true.
        The only exits are his click and the half-hour time-to-live.
        """
        return any(not a["future"].done() for a in self.approvals.values())

    def resolve_approval(self, aid: int, allow: bool) -> None:
        pending = self.approvals.get(aid)
        if pending and not pending["future"].done():
            pending["future"].set_result(bool(allow))

    async def warm_up(self) -> None:
        await self.brain.connect()
        async for _ in self.brain.stream(WARMUP_PROMPT):
            pass                     # pay the cache toll off-speaker
        self.ready.set()
        print("brain warm -- browser voice ready", flush=True)
        log_event("up", "brain", "warm -- browser voice ready")

    async def rebuild_brain(self) -> None:
        """Fresh CLI subprocess. A brain left warm overnight loses its
        login ("Not logged in - Please run /login") and never recovers;
        a new subprocess picks up the machine's valid credentials."""
        old = self.brain
        self.brain = Brain(can_use_tool=self.ask_permission)
        await old.close()
        await self.brain.connect()
        async for _ in self.brain.stream(WARMUP_PROMPT):
            pass
        print("brain rebuilt", flush=True)
        # The one event Jarvis can never remember himself: the conversation
        # this replaces is gone, so the record has to outlive it.
        log_event("down", "brain", "rebuilt -- previous conversation lost")

    async def synth(self, sentence: str) -> bytes | None:
        """Raw PCM from Kokoro, wrapped in a clean WAV header here --
        Kokoro's own streaming WAV headers carry bogus length fields
        that a browser decoder may reject."""
        try:
            r = await self.http.post(KOKORO_URL, json={
                "model": "kokoro", "input": sentence, "voice": KOKORO_VOICE,
                "response_format": "pcm", "speed": 1.0,
            })
            r.raise_for_status()
            out = io.BytesIO()
            with wave.open(out, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(r.content)
            return out.getvalue()
        except Exception as e:
            print(f"kokoro failed: {e}", flush=True)
            return None

    async def transcribe(self, wav_bytes: bytes) -> str:
        r = await self.http.post(
            WHISPER_URL,
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={
                "response_format": "json",
                "temperature": "0.0",
                "prompt": VOCAB_PROMPT,
            },
        )
        r.raise_for_status()
        return clean_transcript(r.json().get("text", ""))

    async def interrupt(self) -> None:
        # THE POPUP CANNOT BE CANCELLED -- ONLY ANSWERED. Serge, 2026-08-06
        # 10:04 AM: "The only way it can be de-active is by me doing an
        # approval or pressing denied or approved. It cannot be cancelled."
        #
        # So while any permission request is pending, EVERY interrupt --
        # button, barge-in, another tab, the terminal -- is held rather than
        # obeyed. Tearing the turn down would cancel the await inside
        # ask_permission() and the request would cease to exist with no
        # answer, no log line and no word to anyone: the silent stall this
        # whole family of fixes exists to end. (The previous build answered
        # pending requests with a deny before tearing down; his rule inverts
        # that -- the request now outlives the interrupt.) The pages are
        # told, so a held interrupt is a stated fact, not a new silence.
        # The one exit that is not his click is the half-hour time-to-live
        # in ask_permission(), and that one arrives as an ANSWERED deny.
        if self.approval_pending():
            print("interrupt held -- approval pending", flush=True)
            for ws in list(WS_CLIENTS):
                await self.safe_send(ws, {"type": "held"})
            return
        self.gen += 1
        if not self.turn_lock.locked():
            return               # nothing in flight -- don't poke the SDK
        # Re-check on the brink (test-adversary finding, 2026-08-06): a
        # request can register between the guard above and this line --
        # the awaits in the held-broadcast path yield the loop. Tearing
        # the brain down now would cancel that request unprotected, so
        # the bump is undone and the interrupt is held after all. The
        # window inside brain.interrupt() itself cannot be closed from
        # here; this shrinks the race to that single await.
        if self.approval_pending():
            self.gen -= 1
            print("interrupt held -- approval pending", flush=True)
            for ws in list(WS_CLIENTS):
                await self.safe_send(ws, {"type": "held"})
            return
        try:
            await self.brain.interrupt()
        except Exception:
            pass

    @staticmethod
    async def safe_send(ws: web.WebSocketResponse, msg: dict) -> bool:
        """Send unless the page has gone away; never raise."""
        try:
            await ws.send_json(msg)
            return True
        except Exception:
            return False

    async def _attempt(self, ws: web.WebSocketResponse, prompt: str,
                       my_gen: int) -> tuple[int, float | None, str]:
        """Stream one reply to the page. Returns (chunks shipped,
        monotonic time of first shipped chunk, full reply text);
        shipped is -1 if the page went away mid-turn."""
        shipped = 0
        first_at = None
        parts: list[str] = []
        async for chunk in self.brain.stream(prompt):
            if my_gen != self.gen:
                break
            audio = await self.synth(chunk)
            if my_gen != self.gen:
                break
            msg = {"type": "say", "text": chunk}
            if audio is not None:
                msg["wav"] = base64.b64encode(audio).decode()
            if not await self.safe_send(ws, msg):
                # Page closed mid-turn: let the brain finish
                # quietly, stop synthesizing for a dead client.
                return -1, first_at, " ".join(parts)
            if first_at is None:
                first_at = time.monotonic()
            parts.append(chunk)
            shipped += 1
        return shipped, first_at, " ".join(parts)

    async def run_turn(self, ws: web.WebSocketResponse, prompt: str,
                       t0: float | None = None, stt_s: float = 0.0) -> None:
        my_gen = self.gen
        if t0 is None:
            t0 = time.monotonic()
        async with self.turn_lock:
            if my_gen != self.gen:
                return               # interrupted while queued
            try:
                voice_signals.log_transcript("Serge", prompt)
                voice_signals.clear_question()   # Serge engaged: nothing pending
                if not await self.safe_send(
                        ws, {"type": "state", "value": "thinking"}):
                    return               # page already gone
                shipped, first_at, reply = await self._attempt(
                    ws, prompt, my_gen)
                if (shipped == 0 and my_gen == self.gen
                        and not self.brain.looks_dead()):
                    # Silence from a HEALTHY brain. This is a long
                    # tool-only turn, not a corpse -- rebuilding here
                    # would throw away Serge's whole conversation to
                    # fix nothing. It happened twice on 2026-08-04 and
                    # he called it: "the brain should not be disrupted
                    # like that at all." Say so and keep the brain.
                    print("empty turn -- brain healthy, keeping it",
                          flush=True)
                    await self.safe_send(ws, {
                        "type": "error",
                        "text": "That turn came back with nothing to say "
                                "-- but I'm still here, and I still "
                                "remember. Try me again."})
                elif shipped == 0 and my_gen == self.gen:
                    # The brain really is broken: no result at all, or a
                    # result flagged as an error (the stale overnight
                    # login answers "Not logged in" and never streams
                    # speakable text). Rebuild and retry the same turn --
                    # and tell the page, so a lost conversation is a
                    # stated fact instead of Serge watching me die.
                    print(f"dead brain ({self.brain.last_error or 'no result'})"
                          " -- rebuilding, retrying", flush=True)
                    await self.safe_send(ws, {
                        "type": "error",
                        "text": "My brain stopped responding, so I'm "
                                "starting a fresh one. I'll lose this "
                                "conversation -- the vault has the rest."})
                    await self.safe_send(
                        ws, {"type": "state", "value": "warming"})
                    await self.rebuild_brain()
                    if my_gen == self.gen:
                        await self.safe_send(
                            ws, {"type": "state", "value": "thinking"})
                        shipped, first_at, reply = await self._attempt(
                            ws, prompt, my_gen)
                        if shipped == 0 and my_gen == self.gen:
                            await self.safe_send(ws, {
                                "type": "error",
                                "text": "I heard you, but the brain gave "
                                        "me nothing -- even after a "
                                        "restart."})
                if shipped > 0 and my_gen == self.gen:
                    # Turn completed uninterrupted: post the trailing
                    # question (or clear) for the page's waiting banner.
                    voice_signals.question_from_reply(reply)
                if reply:
                    voice_signals.log_transcript("Jarvis", reply)
                first_s = (f"{first_at - t0:.2f}s" if first_at is not None
                           else "n/a")
                print(f"turn timing: stt {stt_s:.2f}s, "
                      f"first chunk {first_s}, "
                      f"total {time.monotonic() - t0:.2f}s", flush=True)
            except Exception as e:
                print(f"turn failed: {e}", flush=True)
                await self.safe_send(
                    ws, {"type": "error", "text": "That turn failed on me."})
            finally:
                # A turn must never end silently: a client that misses
                # "done" keeps thinking forever (the 12:05 zombie tabs).
                if my_gen == self.gen:
                    await self.safe_send(ws, {"type": "done"})


VW = VoiceWeb()
WS_CLIENTS: set[web.WebSocketResponse] = set()


async def watch_page(app: web.Application) -> None:
    """Tell every connected page to reload when jarvis.html changes on
    disk -- the page waits for any in-flight turn to finish first."""
    last = PAGE.stat().st_mtime
    while True:
        await asyncio.sleep(1.0)
        try:
            mtime = PAGE.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime != last:
            last = mtime
            print("page changed -- telling browsers to reload", flush=True)
            for ws in list(WS_CLIENTS):
                await VW.safe_send(ws, {"type": "reload"})


async def page(request: web.Request) -> web.Response:
    # Stamp the served copy with its file version so the page can spot
    # on /signals that it has gone stale and reload itself -- a tab that
    # reconnects after a restart never hears the one-shot reload push.
    body = PAGE.read_bytes()
    body = body.replace(b'"__PAGE_VERSION__"',
                        f'"{PAGE.stat().st_mtime}"'.encode(), 1)
    return web.Response(body=body, content_type="text/html",
                        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# AMBIENT MUSIC  (Serge, 2026-08-05 ~1:05 PM, extended to a rotating mix ~1:35)
#
# TO REMOVE THIS ENTIRELY -- Serge asked for the removal route to be written
# down before it was built, because it is the one piece of Jarvis that serves
# files off disk. Three steps, nothing else anywhere depends on them:
#   1. delete this block and the ambient lines in app.add_routes(...)
#   2. in jarvis.html, delete the AMBIENT FILE block in ensureAmbient()
#   3. rm -r "Jarvis Visual/audio"
# The page degrades to silence on its own if the routes are gone -- the fetch
# fails, the catch swallows it, and the MUSIC toggle simply produces nothing.
#
# WHY THIS IS NARROW BY CONSTRUCTION, not by validation:
#   - No handler here takes ANY input. There is no filename parameter, no query
#     string, no path segment -- each route is bound to one constant path at
#     startup. A traversal attack needs somewhere to put "../", and there is
#     nowhere. This is deliberately NOT a static-file handler; adding one would
#     be the actual risk, and it is the thing this shape exists to avoid.
#   - GOING FROM ONE TRACK TO FOUR DID NOT WEAKEN THAT, and that was the whole
#     design question. The obvious move -- one route taking an index or a name
#     -- would have introduced the first piece of caller-controlled input in the
#     file. Instead the track list is a constant, and main() registers one fixed
#     route per entry. Four routes, still zero input. If this ever grows a
#     parameter, that is the moment the risk returns.
#   - GET only, and the whole server is bound to 127.0.0.1 (see HOST above), so
#     nothing off this machine can reach any of it.
#   - Every file 404s rather than raising if it is missing.
#
# All four are PUBLIC DOMAIN recordings, fetched once on Serge's explicit
# approval and stored under the Jarvis folder. Sources are named so the licence
# can be re-checked without trusting this comment:
#   mozart-symphony-40-andante  archive.org  Mozart_Symphony_40
#   holst-jupiter               archive.org  gustav-holst-the-planets-op.-32
#   debussy-clair-de-lune       archive.org  01-debussey-clair-de-lune
#   beethoven-symphony-5        archive.org  BeethovenSymphonyNo.5
AMBIENT_DIR = HERE / "audio"
# ORDERED CALMEST FIRST, and that order is load-bearing (Serge, 2026-08-05
# ~1:50 PM: "start the mix with the calmest track... if the thing is safer").
# The page always plays entry 0 and shuffles only the rest, so switching the
# music on can never open with the Fifth at full tilt -- the first thing he
# hears is always the quietest thing here. Reordering this tuple changes what
# he gets on every switch-on, so it is not a cosmetic list.
AMBIENT_TRACKS = (
    ("/ambient/debussy.mp3",   "debussy-clair-de-lune.mp3",
     "Debussy -- Clair de Lune"),                      # calmest: the opener
    ("/ambient/mozart.mp3",    "mozart-symphony-40-andante.mp3",
     "Mozart -- Symphony No. 40, II. Andante"),
    ("/ambient/holst.mp3",     "holst-jupiter.mp3",
     "Holst -- The Planets: Jupiter"),
    ("/ambient/beethoven.mp3", "beethoven-symphony-5.mp3",
     "Beethoven -- Symphony No. 5"),                   # loudest: never first
)


def _serve_ambient(filename: str):
    """Build a handler bound to ONE constant filename.

    The closure is the security boundary: `filename` comes from the tuple
    above, never from a request, and the returned handler ignores its request
    entirely. One route per track keeps the no-input property that a single
    parameterised route would have thrown away.
    """
    path = AMBIENT_DIR / filename

    async def handler(request: web.Request) -> web.Response:
        try:
            if not path.is_file():
                return web.Response(status=404, text="no ambient file")
            return web.Response(body=path.read_bytes(),
                                content_type="audio/mpeg",
                                headers={"Cache-Control": "max-age=86400"})
        except Exception as e:
            # Music is a nicety. It must never take the page down with it.
            print(f"ambient file failed: {e}", flush=True)
            return web.Response(status=404, text="no ambient file")

    return handler


async def ambient_list(request: web.Request) -> web.Response:
    """The playlist, so the page never hard-codes what the server serves.

    Only tracks actually present on disk are listed -- a half-downloaded set
    degrades to the tracks that made it rather than to a silent gap the page
    cannot explain.
    """
    return web.json_response([
        {"url": url, "title": title}
        for url, fn, title in AMBIENT_TRACKS
        if (AMBIENT_DIR / fn).is_file()
    ])


async def signals(request: web.Request) -> web.Response:
    try:
        state = STATE_FILE.read_text().strip() or "idle"
    except Exception:
        state = "idle"
    waveform = {"ts": 0.0, "samples": []}
    try:
        waveform = json.loads(WAVEFORM_FILE.read_text())
    except Exception:
        pass
    # Terminal voice line liveness: alive iff its heartbeat file is fresh.
    line_alive = terminal_alive()
    transcript = []
    try:
        transcript = json.loads(TRANSCRIPT_FILE.read_text())
    except Exception:
        pass
    # Waiting-for-Serge banner: Jarvis writes the pending question into
    # .voice_question when a turn ends on a question, clears it when the
    # next turn starts. Empty/missing file means nothing pending.
    question = ""
    try:
        question = QUESTION_FILE.read_text().strip()
    except Exception:
        pass
    try:
        page_version = str(PAGE.stat().st_mtime)
    except Exception:
        page_version = ""
    return web.json_response(
        {"state": state, "waveform": waveform, "now": time.time(),
         "line_alive": line_alive, "transcript": transcript,
         "question": question, "tasks": read_tasks(),
         "page_version": page_version,
         "approval": next(
             ({"id": a["id"], "tool": a["tool"], "detail": a["detail"]}
              for a in VW.approvals.values()), None),
         "stack": _STACK,
         "events": read_events(),
         "sessions": read_sessions(),
         "mail": read_mail(),
         "usage": read_usage(),
         "usage_poll": _USAGE_RUN.is_set(),
         # The page ships to an open tab the moment the file changes, but the
         # SERVER only changes on a restart -- so a new page can be talking to
         # an old server for a while. This says "I understand an image riding
         # an audio turn"; without it the page keeps the attachment in its chip
         # rather than sending it into a server that would drop it on the floor.
         "voice_image": True,
         # Same doctrine, one turn later: "I understand a LIST of images."
         # Without it the page sends only the first and says the rest are
         # still waiting, rather than shipping a list an old server would
         # ignore -- which would lose the very images this is meant to keep.
         "multi_image": True,
         # Same doctrine again, and it matters more here than anywhere: this
         # says "I have the /task-move route." Without it the approve buttons
         # do not draw at all, because a button that posts into a 404 would
         # look like Serge approved something and have changed nothing --
         # exactly the silent failure the button exists to end.
         "task_move": True,
         "stats": {**_STATS,
                   "brain": "active" if VW.ready.is_set() else "warming",
                   # Blank until the brain's first turn reports it; the
                   # page shows a placeholder until then.
                   "model": getattr(VW.brain, "model", "") or ""}},
        headers={"Cache-Control": "no-store"})


async def history(request: web.Request) -> web.Response:
    """Today's permanent transcript, replayed for the Activity Log.

    The log used to start empty on every refresh (per Serge, 2026-08-03);
    signals.log_transcript already keeps the full day on disk, so the page
    hydrates from here on load instead of from nothing.
    """
    lines = []
    try:
        day = time.strftime("%Y-%m-%d")
        path = voice_signals.TRANSCRIPTS_DIR / f"{day}.md"
        for raw in path.read_text().splitlines():
            m = re.match(r"^- \*\*\d\d:\d\d:\d\d (\w+):\*\* (.*)$", raw)
            if m:
                who = "you" if m.group(1).lower() == "serge" else "jarvis"
                lines.append({"who": who, "text": m.group(2)})
    except Exception:
        pass
    return web.json_response({"lines": lines[-30:]},
                             headers={"Cache-Control": "no-store"})


async def graph(request: web.Request) -> web.Response:
    return web.json_response(scan_vault_graph(),
                             headers={"Cache-Control": "no-store"})


def save_upload(img: dict) -> Path | None:
    """Save a base64 image off the socket into uploads/, or None.

    Pulled out of the "image" branch on 2026-08-05 so the "audio" branch can
    use it too: Serge drops a file and then TALKS, which used to orphan the
    image because only a typed send ever shipped one. One saver, one naming
    rule, two call sites -- the alternative was a second copy of this that
    would drift.
    """
    if not isinstance(img, dict):
        return None
    try:
        raw = base64.b64decode(img.get("data") or "")
    except Exception:
        raw = b""
    if not raw:
        return None
    name = os.path.basename(img.get("name") or "pasted.png")
    stem, ext = os.path.splitext(name)
    stamp = time.strftime("%Y-%m-%d %H.%M.%S")
    path = UPLOADS_DIR / f"{stamp} {name}"
    n = 2
    while path.exists():
        path = UPLOADS_DIR / f"{stamp} {stem}-{n}{ext}"
        n += 1
    try:
        UPLOADS_DIR.mkdir(exist_ok=True)
        path.write_bytes(raw)
    except OSError as e:
        print(f"upload save failed: {e}", flush=True)
        return None
    print(f"image saved: {path} ({len(raw)} bytes)", flush=True)
    return path


def image_prompt(path: Path, text: str) -> str:
    """The prompt that points the brain at a saved upload."""
    text = (text or "").strip()
    note = (f'(Serge attached an image on the JARVIS page; it is '
            f'saved at "{path}". Open it and look at it before answering.)')
    if text:
        return f"{text} {note}"
    return (f'Serge attached an image on the JARVIS page, saved at '
            f'"{path}". Open it and tell him what you make of it.')


# How many images one turn may carry. The page enforces the same number; this
# is the backstop, because the page is not the only thing that can reach the
# socket and an unbounded list is an unbounded write into uploads/.
MAX_IMAGES = 6


def save_uploads(imgs: list) -> list[Path]:
    """Save every image in a list, in order, skipping the ones that fail.

    Serge, 2026-08-05: "when I add two images back-to-back, it only catches
    the last one." The page held ONE attachment slot and this end took one
    image per turn to match. Both became lists together.

    Order is Serge's order -- he refers to "the first one" and "the second",
    so a saver that reordered or de-duplicated them would break the prompt.
    """
    if not isinstance(imgs, list):
        return []
    out = []
    for img in imgs[:MAX_IMAGES]:
        path = save_upload(img)
        if path is not None:
            out.append(path)
    return out


def images_prompt(paths: list, text: str) -> str:
    """The prompt that points the brain at one or more saved uploads.

    Single-image wording is delegated to image_prompt() unchanged -- one image
    is by far the common case and its phrasing is already proven in daily use.
    """
    if not paths:
        return (text or "").strip()
    if len(paths) == 1:
        return image_prompt(paths[0], text)
    text = (text or "").strip()
    listed = ", ".join(f'"{p}"' for p in paths)
    n = len(paths)
    note = (f'(Serge attached {n} images on the JARVIS page, saved at '
            f'{listed} -- in the order he added them. Open all {n} and look '
            f'at them before answering.)')
    if text:
        return f"{text} {note}"
    return (f'Serge attached {n} images on the JARVIS page, saved at '
            f'{listed} -- in the order he added them. Open all {n} and tell '
            f'him what you make of them.')


async def voice_ws(request: web.Request) -> web.WebSocketResponse:
    # max_msg_size: pasted screenshots ride this socket as base64 (a
    # Retina capture can pass aiohttp's 4 MB default several times over).
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024 * 1024)
    await ws.prepare(request)
    WS_CLIENTS.add(ws)
    if not VW.ready.is_set():
        await ws.send_json({"type": "state", "value": "warming"})
        await VW.ready.wait()
    await ws.send_json({"type": "state", "value": "idle"})

    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            data = json.loads(msg.data)
        except Exception:
            continue
        kind = data.get("type")
        if kind == "interrupt":
            await VW.interrupt()
        elif kind == "approval_reply":
            try:
                VW.resolve_approval(int(data.get("id") or 0),
                                    bool(data.get("allow")))
            except (TypeError, ValueError):
                pass
        elif kind == "text":
            text = (data.get("text") or "").strip()
            if not text:
                continue
            if terminal_alive():
                # One brain: hand typed lines to the terminal voice line
                # instead of running a second session here.
                try:
                    INBOX_DIR.mkdir(exist_ok=True)
                    (INBOX_DIR / f"{time.time_ns()}.txt").write_text(text)
                    await VW.safe_send(ws, {"type": "routed"})
                    continue
                except Exception as e:
                    print(f"inbox route failed: {e}", flush=True)
            if VW.approval_pending():
                # Do NOT interrupt: the popup survives, the message waits
                # its turn on turn_lock. The page is told, so the queueing
                # is a stated fact rather than a new silence.
                await VW.safe_send(ws, {"type": "held"})
            else:
                await VW.interrupt()
            asyncio.create_task(
                VW.run_turn(ws, text, t0=time.monotonic()))
        elif kind == "image":
            # Pasted/dropped on the page: save to uploads/, then run a
            # normal turn pointing the brain at the file. If the
            # terminal line owns the conversation, route the composed
            # prompt to its inbox instead (same rule as typed text).
            # "images" is the list shape; a bare image at the top level is the
            # shape an older page sends, and it still works -- the page reaches
            # an open tab before the server restarts, never the other way, but
            # a stale tab can outlive a restart in the other direction.
            paths = save_uploads(data.get("images") or [data])
            if not paths:
                await VW.safe_send(ws, {
                    "type": "error",
                    "text": "I couldn't save that image."})
                continue
            prompt = images_prompt(paths, data.get("text") or "")
            if terminal_alive():
                try:
                    INBOX_DIR.mkdir(exist_ok=True)
                    (INBOX_DIR / f"{time.time_ns()}.txt").write_text(prompt)
                    await VW.safe_send(ws, {"type": "routed"})
                    continue
                except Exception as e:
                    print(f"inbox route failed: {e}", flush=True)
            if VW.approval_pending():
                await VW.safe_send(ws, {"type": "held"})
            else:
                await VW.interrupt()
            asyncio.create_task(
                VW.run_turn(ws, prompt, t0=time.monotonic()))
        elif kind == "audio":
            t0 = time.monotonic()
            stt_failed = False
            try:
                wav16 = wav_to_16k(base64.b64decode(data.get("wav", "")))
                transcript = await VW.transcribe(wav16)
            except Exception as e:
                # NEVER FAIL SILENTLY HERE (Serge, 2026-08-05 ~2:05 PM).
                # Whisper answered 400 three times today; each one cost him a
                # spoken turn and he saw NOTHING -- the empty transcript went out
                # as an empty `transcript` message and the turn closed with
                # `done`, which the page renders as a return to idle. From his
                # chair that is indistinguishable from Jarvis ignoring him.
                # The log knew; the only person who needed to know did not.
                print(f"transcription failed: {e}", flush=True)
                transcript = ""
                stt_failed = True
            stt_s = time.monotonic() - t0
            await ws.send_json({"type": "transcript", "text": transcript})
            # Say it on the page, not only in the log. `error` is an existing
            # message type the page already renders as a line from Jarvis, so
            # this needs no page change to be visible -- an old tab shows it too.
            if stt_failed:
                await ws.send_json({
                    "type": "error",
                    "text": "I couldn't make out that recording — "
                            "the speech service rejected it. Say it again?",
                })
            # An image can ride a spoken turn (Serge drops a file, then talks).
            # It is saved here and folded into the prompt exactly as a typed
            # image turn would be, so the brain sees one consistent shape.
            imgs = data.get("images")
            if not imgs and data.get("image"):
                imgs = [data["image"]]          # the one-image shape, still valid
            paths = save_uploads(imgs or [])
            prompt = images_prompt(paths, transcript) if paths else transcript
            if prompt:
                asyncio.create_task(
                    VW.run_turn(ws, prompt, t0=t0, stt_s=stt_s))
            else:
                await ws.send_json({"type": "done"})
    WS_CLIENTS.discard(ws)
    return ws


async def on_startup(app: web.Application) -> None:
    app["warmer"] = asyncio.create_task(VW.warm_up())
    app["pagewatch"] = asyncio.create_task(watch_page(app))
    app["stats"] = asyncio.create_task(sample_stats())
    app["stack"] = asyncio.create_task(sample_stack())
    app["usage"] = asyncio.create_task(sample_usage())


def main() -> None:
    app = web.Application()
    app.add_routes([
        web.get("/", page),
        web.get("/signals", signals),
        web.get("/history", history),
        web.get("/graph", graph),
        web.get("/ambient-list", ambient_list),   # remove with the AMBIENT block
        *[web.get(u, _serve_ambient(f)) for u, f, _t in AMBIENT_TRACKS],
        web.get("/usage-poll", usage_poll),
        web.post("/usage-poll", usage_poll),
        web.post("/task-move", task_move),
        web.get("/voice", voice_ws),
    ])
    app.on_startup.append(on_startup)
    print(f"JARVIS voice+visual on http://{HOST}:{PORT}/", flush=True)
    log_event("up", "browser Jarvis", f"server started on port {PORT}")
    web.run_app(app, host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
