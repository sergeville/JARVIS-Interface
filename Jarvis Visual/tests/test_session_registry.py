"""Tests for voice-line/session_registry.py.

Imported by path from the real module, so these can never drift from the
code they guard. Every file write lands in a temp dir -- the real
.sessions.jsonl is never touched.

The load-bearing property under test is the one the whole design rests on:
liveness comes from the process table, NOT from SessionEnd. A session that
was killed never wrote an end line, and it must still read as dead.
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# The project root, from this test file's own location. Tests must not carry
# the author's home directory any more than the code they guard does.
ROOT = str(Path(__file__).resolve().parents[2])
SR_PATH = f"{ROOT}/voice-line/session_registry.py"
spec = importlib.util.spec_from_file_location("session_registry", SR_PATH)
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name}\n    got:  {got!r}\n    want: {want!r}")


def ok(name, cond):
    check(name, bool(cond), True)


# ---------------------------------------------------------------- is_claude

ok("claude binary is a session", sr.is_claude("/Users/testuser/.local/bin/claude"))
ok("claude with args", sr.is_claude("claude --model claude-opus-5"))
ok("node running claude", sr.is_claude("node /Users/testuser/.local/share/claude/cli.js"))
ok("grep for claude is NOT a session", not sr.is_claude("grep claude foo.txt"))
ok("empty is not a session", not sr.is_claude(""))
ok("a path merely containing the word is not a session",
   not sr.is_claude("/usr/bin/python3 /Users/testuser/claude-helper.py"))

# ------------------------------------------------------------ model_from_cmd

check("model from --model", sr.model_from_cmd("claude --model claude-opus-5"),
      "claude-opus-5")
check("model from --model=", sr.model_from_cmd("claude --model=claude-opus-5"),
      "claude-opus-5")
check("no model flag", sr.model_from_cmd("claude -p hello"), "")
check("--model with nothing after it", sr.model_from_cmd("claude --model"), "")

# ------------------------------------------------------------------ classify

check("voice brain classified by its server ancestor",
      sr.classify(["claude --model claude-opus-5",
                   "python3 voice-web-server.py"], sr.JARVIS_ROOT),
      "voice line")
check("terminal line classified by main.py",
      sr.classify(["claude", "uv run voice-line/main.py"], sr.JARVIS_ROOT),
      "terminal line")
check("terminal at the Jarvis root",
      sr.classify(["claude", "-zsh"], sr.JARVIS_ROOT), "terminal (Jarvis root)")
check("terminal in Jarvis Visual",
      sr.classify(["claude", "-zsh"], sr.JARVIS_ROOT + "/Jarvis Visual"),
      "terminal (Jarvis Visual)")
check("unknown cwd falls back to plain terminal",
      sr.classify(["claude", "-zsh"], "/tmp/somewhere"), "terminal")
check("no cwd at all still classifies", sr.classify(["claude"], ""), "terminal")

# THE PROBE FINDING: hook payloads arrive symlink-resolved. If classify
# compared raw strings, a resolved path would miss its own folder.
sym = tempfile.mkdtemp()
link = os.path.join(sym, "jarvis-link")
os.symlink(sr.JARVIS_ROOT, link)
check("symlinked cwd still resolves to the Jarvis root",
      sr.classify(["claude", "-zsh"], link), "terminal (Jarvis root)")

# The ancestor chain WINS over cwd -- the brain and a terminal share a cwd,
# which is exactly why cwd alone cannot tell them apart.
check("server ancestor beats a terminal-looking cwd",
      sr.classify(["claude", "python3 voice-web-server.py"],
                  sr.JARVIS_ROOT + "/Jarvis Visual"),
      "voice line")

# ------------------------------------------------------- ancestor resolution

TABLE = {
    100: {"ppid": 1, "started": 1000.0, "cmd": "/sbin/launchd"},
    200: {"ppid": 100, "started": 2000.0, "cmd": "python3 voice-web-server.py"},
    300: {"ppid": 200, "started": 3000.0,
          "cmd": "/Users/testuser/.local/bin/claude --model claude-opus-5"},
    400: {"ppid": 300, "started": 4000.0, "cmd": "/bin/bash -c hook"},
    500: {"ppid": 400, "started": 5000.0, "cmd": "python3 session_registry.py start"},
}

check("owning session walks up past the shell",
      sr.owning_session(500, TABLE)["pid"], 300)
check("owning session of the session itself is itself",
      sr.owning_session(300, TABLE)["pid"], 300)
check("no claude anywhere above -> None", sr.owning_session(200, TABLE), None)
check("unknown pid -> None", sr.owning_session(999, TABLE), None)
check("chain reaches the server",
      any("voice-web-server.py" in r["cmd"]
          for r in sr.ancestor_chain(500, TABLE)), True)

# A cycle in a malformed table must not hang the hook.
CYCLE = {1: {"ppid": 2, "started": 1.0, "cmd": "a"},
         2: {"ppid": 1, "started": 1.0, "cmd": "b"}}
check("a cycle terminates instead of hanging", len(sr.ancestor_chain(1, CYCLE)), 2)

# ------------------------------------------------------------ channel_chain
# Found in LIVE USE, not by reasoning: a terminal session launched from inside
# a Jarvis-spawned shell has the voice server somewhere up its chain, and a
# walk to init misfiles it as "voice line". The first claude ABOVE the session
# is the boundary of what belongs to it.

NESTED = {
    100: {"ppid": 1, "started": 1000.0, "cmd": "/sbin/launchd"},
    200: {"ppid": 100, "started": 2000.0, "cmd": "python3 voice-web-server.py"},
    300: {"ppid": 200, "started": 3000.0, "cmd": "/usr/local/bin/claude"},   # the brain
    400: {"ppid": 300, "started": 4000.0, "cmd": "/bin/bash -c work"},
    500: {"ppid": 400, "started": 5000.0, "cmd": "claude --model claude-opus-5"},  # nested terminal
    600: {"ppid": 500, "started": 6000.0, "cmd": "python3 session_registry.py start"},
}

check("the brain's own chain reaches its server",
      sr.classify(sr.channel_chain(400, NESTED), sr.JARVIS_ROOT), "voice line")
check("a session nested INSIDE the brain is not the voice line",
      sr.classify(sr.channel_chain(600, NESTED), sr.JARVIS_ROOT),
      "terminal (Jarvis root)")
ok("the nested chain stops before the brain",
   not any("voice-web-server" in c for c in sr.channel_chain(600, NESTED)))
ok("the brain's chain does include its server",
   any("voice-web-server" in c for c in sr.channel_chain(400, NESTED)))
check("a chain with no claude at all still yields something",
      len(sr.channel_chain(200, NESTED)) > 0, True)

# -------------------------------------------------------------- build_record

payload = {"session_id": "abc", "transcript_path": "/tmp/t.jsonl",
           "cwd": sr.JARVIS_ROOT, "source": "startup", "model": None}
rec = sr.build_record("start", payload, TABLE[300] | {"pid": 300},
                      [r["cmd"] for r in sr.ancestor_chain(500, TABLE)], 123.0)
check("record keeps the session id", rec["session_id"], "abc")
check("record keeps the pid", rec["pid"], 300)
check("record keeps the pid start time", rec["pid_started"], 3000.0)
check("record classifies as the voice line", rec["channel"], "voice line")
check("record takes the model from the COMMAND LINE, not the null payload",
      rec["model"], "claude-opus-5")
check("record keeps the source", rec["source"], "startup")
check("record stamps the time", rec["ts"], 123.0)

# A payload missing everything must still produce a record rather than raise.
bare = sr.build_record("start", {}, None, [], 1.0)
check("empty payload still yields a record", bare["session_id"], "")
check("empty payload has no pid", bare["pid"], None)

# ------------------------------------------------------------ fold_sessions

def line(**kw):
    base = {"ts": 1.0, "event": "start", "session_id": "s1", "pid": 300,
            "pid_started": 3000.0, "channel": "voice line", "model": "m",
            "transcript_path": "/tmp/t", "cwd": "/c", "source": "startup"}
    base.update(kw)
    return json.dumps(base)


folded = sr.fold_sessions([line(), line(session_id="s2", pid=301)])
check("two sessions fold to two rows", len(folded), 2)

folded = sr.fold_sessions([line(ts=1.0), line(ts=2.0, pid=999)])
check("a repeated start updates rather than duplicating", len(folded), 1)
check("the later start wins", folded["s1"]["pid"], 999)

folded = sr.fold_sessions([line(), line(event="end", ts=9.0, reason="clear")])
check("an end marks the row ended", folded["s1"]["ended"], True)
check("an end keeps the reason", folded["s1"]["reason"], "clear")

folded = sr.fold_sessions([line(), line(event="end", ts=9.0),
                           line(ts=10.0, source="resume")])
check("a resume revives the row", folded["s1"]["ended"], False)

folded = sr.fold_sessions([line(), "{ not json", "", "   ",
                           json.dumps(["a list"]), json.dumps({"no": "id"}),
                           line(session_id="s2")])
check("garbage costs one row, not the panel", len(folded), 2)
check("no lines at all -> nothing", sr.fold_sessions([]), {})

# ----------------------------------------------------------------- is_live

LIVE = {300: {"ppid": 1, "started": 3000.0, "cmd": "claude --model x"}}

ok("a live pid reads live", sr.is_live({"pid": 300, "pid_started": 3000.0}, LIVE))
ok("a missing pid reads dead",
   not sr.is_live({"pid": 301, "pid_started": 3000.0}, LIVE))
ok("no pid at all reads dead", not sr.is_live({"pid": None}, LIVE))
ok("a non-integer pid reads dead", not sr.is_live({"pid": "300"}, LIVE))

# THE PID-REUSE GUARD. Same pid, different start time = a different process.
ok("a recycled pid reads dead",
   not sr.is_live({"pid": 300, "pid_started": 111.0}, LIVE))
ok("a start time within tolerance still reads live",
   sr.is_live({"pid": 300, "pid_started": 3001.0}, LIVE))
ok("a start time outside tolerance reads dead",
   not sr.is_live({"pid": 300, "pid_started": 3010.0}, LIVE))

# The pid is alive but is no longer a claude -- recycled by something else.
ok("a pid recycled by a non-claude reads dead",
   not sr.is_live({"pid": 300, "pid_started": 3000.0},
                  {300: {"ppid": 1, "started": 3000.0, "cmd": "/usr/bin/vim"}}))

# A record with no recorded start time cannot use the guard, but must not
# crash -- it falls back to "the pid exists and is a claude".
ok("a record with no start time still resolves",
   sr.is_live({"pid": 300, "pid_started": None}, LIVE))

# --------------------------------------------------------- read_sessions

tmp = Path(tempfile.mkdtemp())
log = tmp / ".sessions.jsonl"

# THE CASE THE WHOLE DESIGN EXISTS FOR: a session that was KILLED. It wrote
# a start line and never got to write an end line. The board would still be
# showing it. The registry must call it dead, from the process table alone.
log.write_text("\n".join([
    line(session_id="alive", pid=300, pid_started=3000.0, ts=100.0),
    line(session_id="killed", pid=777, pid_started=7000.0, ts=50.0),
]) + "\n")
rows = sr.read_sessions(path=log, table=LIVE)
check("only the live session is returned", [r["session_id"] for r in rows],
      ["alive"])

# A session that ended CLEANLY and whose process is gone is also absent.
log.write_text("\n".join([
    line(session_id="alive", pid=300, pid_started=3000.0, ts=100.0),
    line(session_id="gone", pid=888, pid_started=8000.0, ts=50.0),
    line(session_id="gone", event="end", ts=60.0),
]) + "\n")
check("a cleanly ended session is gone too",
      [r["session_id"] for r in sr.read_sessions(path=log, table=LIVE)],
      ["alive"])

# And the inverse, which is the subtle one: a row marked ended whose PROCESS
# IS STILL ALIVE reads LIVE. `ps` decides, not the end line -- otherwise a
# spurious SessionEnd would hide a running session.
log.write_text(line(session_id="alive", pid=300, pid_started=3000.0, ts=1.0)
               + "\n" + line(session_id="alive", event="end", ts=2.0) + "\n")
check("ps overrules a stale end line",
      [r["session_id"] for r in sr.read_sessions(path=log, table=LIVE)],
      ["alive"])

# Newest first.
TWO = {300: {"ppid": 1, "started": 3000.0, "cmd": "claude"},
       301: {"ppid": 1, "started": 3000.0, "cmd": "claude"}}
log.write_text("\n".join([
    line(session_id="old", pid=300, pid_started=3000.0, ts=10.0),
    line(session_id="new", pid=301, pid_started=3000.0, ts=20.0),
]) + "\n")
check("newest session first",
      [r["session_id"] for r in sr.read_sessions(path=log, table=TWO)],
      ["new", "old"])

# last_activity comes from the transcript's own mtime.
tr = tmp / "transcript.jsonl"
tr.write_text("{}\n")
log.write_text(line(session_id="alive", pid=300, pid_started=3000.0,
                    transcript_path=str(tr)) + "\n")
rows = sr.read_sessions(path=log, table=LIVE)
ok("last activity read from the transcript mtime",
   abs(rows[0]["last_activity"] - tr.stat().st_mtime) < 0.01)

log.write_text(line(session_id="alive", pid=300, pid_started=3000.0,
                    transcript_path="/nope/missing.jsonl") + "\n")
check("a missing transcript costs the field, not the row",
      sr.read_sessions(path=log, table=LIVE)[0]["last_activity"], None)

# These two INVERTED on 2026-08-05 (~1:15 PM), and the inversion is the fix,
# not a concession to it. They asserted that a missing or empty log reads as
# no sessions -- while LIVE holds a live claude. That is exactly the bug
# Serge caught from the page: `jarvis.sh sessions` said "no Jarvis sessions
# running" with two alive, because the hooks were installed at 11:55 and both
# sessions predated them. read_sessions() now enumerates the process table
# and uses the log only to NAME what it finds, so a live session with no
# record is listed as `unregistered` rather than dropped. The old assertion
# and the new one cannot both guard this function; see
# tests/test_registry_inversion.py for the full set.
_missing = sr.read_sessions(path=tmp / "nope.jsonl", table=LIVE)
check("a missing log file still lists a live session", len(_missing), 1)
check("...and marks it unregistered", _missing[0]["unregistered"], True)
(tmp / "empty.jsonl").write_text("")
_empty = sr.read_sessions(path=tmp / "empty.jsonl", table=LIVE)
check("an empty log still lists a live session", len(_empty), 1)
check("a log with no matching record cannot hide a running Jarvis",
      _empty[0]["pid"], 300)

# ------------------------------------------------------------ append_record

f = tmp / "append.jsonl"
sr.append_record({"ts": 1.0, "event": "start", "session_id": "a"}, path=f)
sr.append_record({"ts": 2.0, "event": "end", "session_id": "a"}, path=f)
check("both records land", len(f.read_text().splitlines()), 2)
check("the log round-trips through the reader",
      sr.fold_sessions(f.read_text().splitlines())["a"]["ended"], True)

# Append-only survival: the file outlives whatever wrote it, which is the
# whole reason it is a file and not server state.
before = f.read_text()
sr.append_record({"ts": 3.0, "event": "start", "session_id": "b"}, path=f)
ok("earlier lines are never rewritten", f.read_text().startswith(before))

# Trim keeps the NEWEST.
big = tmp / "big.jsonl"
for i in range(sr.TRIM_AT + 5):
    sr.append_record({"ts": float(i), "event": "start",
                      "session_id": f"s{i}"}, path=big)
kept = big.read_text().splitlines()
# Trim fires once the file passes TRIM_AT and cuts back to KEEP, so the file
# is bounded by TRIM_AT -- not pinned to exactly KEEP. Asserting KEEP was the
# TEST being wrong, not the code.
ok("trim keeps the file bounded", sr.KEEP <= len(kept) <= sr.TRIM_AT)
check("trim keeps the newest line",
      json.loads(kept[-1])["session_id"], f"s{sr.TRIM_AT + 4}")

# The logger must never raise -- an unwritable path is silently survived.
try:
    sr.append_record({"ts": 1.0}, path=Path("/nope/nowhere/x.jsonl"))
    ok("append never raises", True)
except Exception:
    ok("append never raises", False)

# -------------------------------------------------------------- the hook

# main() must always exit 0 on the hook paths, whatever it is handed.
class FakeIn:
    def __init__(self, text): self.text = text
    def read(self): return self.text


real_stdin, real_file = sys.stdin, sr.SESSIONS_FILE
sr.SESSIONS_FILE = tmp / "hook.jsonl"
for label, body in [("valid payload", json.dumps({"session_id": "h1"})),
                    ("empty stdin", ""),
                    ("garbage stdin", "{{{not json"),
                    ("a JSON list", "[1,2,3]"),
                    ("a JSON string", '"hello"')]:
    sys.stdin = FakeIn(body)
    check(f"hook exits 0 on {label}", sr.main(["session_registry.py", "start"]), 0)
sys.stdin = FakeIn(json.dumps({"session_id": "h1"}))
check("hook exits 0 on end", sr.main(["session_registry.py", "end"]), 0)
check("hook exits 0 on an unknown mode", sr.main(["session_registry.py", "wat"]), 0)
check("hook exits 0 with no mode at all", sr.main(["session_registry.py"]), 0)
sys.stdin = real_stdin

written = sr.fold_sessions((tmp / "hook.jsonl").read_text().splitlines())
ok("the valid hook run recorded a real session", "h1" in written)
ok("the hook recorded this test process's own claude ancestor, or none "
   "without crashing", "pid" in written["h1"])
sr.SESSIONS_FILE = real_file

# ---------------------------------------------------------- process table

table = sr.process_table()
ok("the real process table is non-empty", len(table) > 10)
ok("this very process is in it", os.getpid() in table)
me = table[os.getpid()]
ok("this process has a start time", isinstance(me["started"], float))
ok("a start time is in the past, not the future", me["started"] <= time.time() + 2)
ok("commands with spaces survive the parse",
   all(isinstance(r["cmd"], str) for r in table.values()))
# The pgrep blind spot (2026-08-04): ps -A must see this session's own
# ancestors, which is the whole reason pgrep was abandoned.
ok("ps -A sees this process's own parent", me["ppid"] in table or me["ppid"] == 1)

# ------------------------------------------- the server's caching wrapper
# Imported by path, like test_uploads.py, so this guards the code that
# actually ships on /signals rather than a copy of it.

SERVER = Path(__file__).resolve().parent.parent / "voice-web-server.py"
sspec = importlib.util.spec_from_file_location("voice_web_server", SERVER)
vws = importlib.util.module_from_spec(sspec)
sys.modules["voice_web_server"] = vws
sspec.loader.exec_module(vws)

calls = {"n": 0}


def fake_read(*a, **kw):
    calls["n"] += 1
    return [{"session_id": "x", "pid": 1}]


real_read = vws.session_registry.read_sessions
vws.session_registry.read_sessions = fake_read
vws._SESSION_CACHE.update(at=0.0, rows=[])

first = vws.read_sessions()
check("the wrapper returns the registry's rows", first[0]["session_id"], "x")
for _ in range(30):
    vws.read_sessions()
check("30 polls inside the TTL cost ONE process-table read", calls["n"], 1)

# /signals is polled at 15 Hz; without the TTL this would shell out to `ps`
# fifteen times a second.
vws._SESSION_CACHE.update(at=time.time() - vws.SESSION_TTL_S - 1)
vws.read_sessions()
check("the cache expires after the TTL", calls["n"], 2)

# THE REASON THIS IS A TTL AND NOT A FILE-IDENTITY CACHE: a session can die
# with nothing written to the file. Same file, different answer.
vws._SESSION_CACHE.update(at=time.time() - vws.SESSION_TTL_S - 1)
vws.session_registry.read_sessions = lambda *a, **kw: []
check("a session that died without writing a line disappears",
      vws.read_sessions(), [])

# A broken registry must cost the strip, never the whole /signals payload --
# the page polls this 15 times a second and every other panel rides with it.
def boom(*a, **kw):
    raise RuntimeError("registry exploded")


vws._SESSION_CACHE.update(at=0.0, rows=[])
vws.session_registry.read_sessions = boom
check("a raising registry returns [] instead of breaking /signals",
      vws.read_sessions(), [])
vws.session_registry.read_sessions = real_read

# ------------------------------------------- the two settings files must agree
#
# Claude Code loads project settings from the SESSION'S OWN cwd, so a terminal
# launched from `Jarvis Visual/` reads that folder's settings.json and nothing
# else. When only the root file carried the registry hooks, every session
# started from there went unregistered -- and `jarvis.sh sessions` answered
# "how many Jarvises are running" with a confident falsehood, which is the
# exact failure the registry exists to end. Both files are documented launch
# points (see How to Start Jarvis), so both must carry the hooks, and this
# test is what stops the pair drifting apart silently again.

# Since 2026-08-05 both files are RENDERED from one template by install.sh, so
# they can no longer drift -- that is now structural rather than something a
# test has to prove. What this test guards moved with it: the TEMPLATE is the
# source of truth and is always present, while the rendered files exist only
# after install.sh has run and are checked as well whenever they do.
TEMPLATE = f"{ROOT}/templates/claude-settings.json.template"
SETTINGS = {w: p for w, p in {
    "root": f"{ROOT}/.claude/settings.json",
    "Jarvis Visual": f"{ROOT}/Jarvis Visual/.claude/settings.json",
}.items() if Path(p).is_file()}


def registry_cmd(root_token):
    """The two hook commands, spelled against whichever root applies."""
    return {
        "SessionStart": f"python3 {root_token}/voice-line/session_registry.py start",
        "SessionEnd": f"python3 {root_token}/voice-line/session_registry.py end",
    }


REGISTRY_CMD = registry_cmd(ROOT)


def hook_commands(cfg, event):
    return [h.get("command")
            for group in cfg.get("hooks", {}).get(event, [])
            for h in group.get("hooks", [])]


# The template must exist and carry the hooks -- without it install.sh cannot
# produce a settings.json at all, and no session would ever register.
check("the settings template exists", Path(TEMPLATE).is_file(), True)
_tpl_text = Path(TEMPLATE).read_text()
check("the template still has its placeholder", "{{JARVIS_ROOT}}" in _tpl_text, True)
check("the template carries no absolute home directory", "/Users/" in _tpl_text, False)
_tpl = json.loads(_tpl_text.replace("{{JARVIS_ROOT}}", "/x"))
for event, cmd in registry_cmd("/x").items():
    check(f"the template carries the {event} hook",
          cmd in hook_commands(_tpl, event), True)

# And whatever has actually been rendered on this machine must agree with it.
for where, path in SETTINGS.items():
    cfg = json.loads(Path(path).read_text())
    for event, cmd in REGISTRY_CMD.items():
        check(f"{where} settings.json carries the {event} hook",
              cmd in hook_commands(cfg, event), True)

# The hooks must invoke the SAME registry -- two copies pointing at different
# writers would fill two different files and each would look complete alone.
if len(SETTINGS) == 2:
    for event in REGISTRY_CMD:
        cmds = [hook_commands(json.loads(Path(p).read_text()), event)
                for p in SETTINGS.values()]
        check(f"both files run the identical {event} command", cmds[0], cmds[1])

# The registry hooks were ADDED alongside the question_hook ones, never in
# place of them -- losing those costs the page's permission card.
for where, path in SETTINGS.items():
    cfg = json.loads(Path(path).read_text())
    for event in ("Stop", "UserPromptSubmit", "Notification"):
        check(f"{where} still carries its {event} question hook",
              any("question_hook.py" in (c or "")
                  for c in hook_commands(cfg, event)), True)

# ------------------------------------------------------------------- report

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
