#!/usr/bin/env python3
"""Tests for read_sessions() enumerating from the PROCESS TABLE.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  .venv python tests/test_registry_inversion.py

Separate from test_session_registry.py on purpose: that file guards the
writer, the fold and the liveness rules -- the record. This one guards a
single decision about the resolver, which is WHERE THE LIST COMES FROM.

The bug it exists to prevent, in full, because it is subtle and it shipped:

    The first read_sessions() walked the log and used `ps` only to filter
    it. Every one of its 90 tests passed. And on 2026-08-05 at 12:50 PM
    `jarvis.sh sessions` printed "no Jarvis sessions running" while two
    were alive -- because the hooks had been installed at 11:55 and both
    sessions predated them, so neither had a start record, so neither could
    ever appear. Serge caught it from the page: "I thought that Jarvis had
    more than one session."

A registry that can only see sessions which cooperated at boot is the
hand-signed Session Board rebuilt in code. So the process table decides who
exists and the log only supplies the name -- and a session with no record
is listed as `unregistered`, never dropped. Every test below is a way that
inversion could quietly be undone.
"""

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "voice-line"))
import session_registry as sr           # noqa: E402  (path set above)

ROOT = str(Path(__file__).resolve().parents[2])
CLAUDE = "/Users/mike/.local/bin/claude --permission-mode auto"
BRAIN = ("/Users/mike/Documents/Jarvis/voice-line/.venv/lib/python3.12/"
         "site-packages/claude_agent_sdk/_bundled/claude --output-format x")
SERVER = "/usr/bin/python3 /Users/mike/Documents/Jarvis/Jarvis Visual/voice-web-server.py"


def proc(pid, ppid, cmd, started):
    return {"ppid": ppid, "started": started, "cmd": cmd}


class InversionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"reg-inv-{os.getpid()}"
        self.tmp.mkdir(exist_ok=True)
        self.log = self.tmp / "sessions.jsonl"
        self.log.write_text("")
        self.now = time.time()
        sr._CWD_CACHE.clear()

    def tearDown(self):
        sr._CWD_CACHE.clear()

    def write(self, *records):
        import json
        self.log.write_text("".join(json.dumps(r) + "\n" for r in records))

    def cwd(self, pid, started, path):
        """Pin a pid's cwd so the resolver never shells out to lsof."""
        sr._CWD_CACHE[(pid, started)] = path

    def read(self, table):
        return sr.read_sessions(path=self.log, table=table)

    # -- the whole point -------------------------------------------------

    def test_live_claude_with_no_record_is_still_listed(self):
        """THE REGRESSION. An empty log and one live claude must yield one
        row -- the old resolver yielded zero, which is the reported bug."""
        t = {900: proc(900, 1, CLAUDE, self.now - 60)}
        self.cwd(900, self.now - 60, ROOT)
        rows = self.read(t)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["unregistered"])
        self.assertEqual(rows[0]["pid"], 900)

    def test_unregistered_row_still_knows_its_channel_and_model(self):
        """Unregistered must not mean unidentified: the ancestry and the
        command line still answer, which is what makes the row useful."""
        t = {
            500: proc(500, 1, SERVER, self.now - 300),
            901: proc(901, 500, BRAIN + " --model claude-opus-5", self.now - 60),
        }
        self.cwd(901, self.now - 60, ROOT)
        row = self.read(t)[0]
        self.assertEqual(row["channel"], "voice line")
        self.assertEqual(row["model"], "claude-opus-5")

    def test_registered_session_is_named_not_marked_unregistered(self):
        self.write({"ts": self.now - 100, "event": "start",
                    "session_id": "abc123", "pid": 902,
                    "pid_started": self.now - 100, "channel": "voice line",
                    "cwd": ROOT, "model": "claude-opus-5",
                    "transcript_path": str(self.tmp / "t.jsonl")})
        t = {902: proc(902, 1, CLAUDE, self.now - 100)}
        rows = self.read(t)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["unregistered"])
        self.assertEqual(rows[0]["session_id"], "abc123")

    def test_both_kinds_appear_together(self):
        """The exact shape of Serge's machine at 12:50 PM: one registered
        voice brain, one unregistered terminal. Both must be listed."""
        self.write({"ts": self.now - 100, "event": "start",
                    "session_id": "abc123", "pid": 902,
                    "pid_started": self.now - 100, "channel": "voice line",
                    "cwd": ROOT, "model": "claude-opus-5"})
        t = {902: proc(902, 1, CLAUDE, self.now - 100),
             903: proc(903, 1, CLAUDE, self.now - 50)}
        self.cwd(903, self.now - 50, ROOT)
        rows = self.read(t)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["unregistered"] for r in rows}, {True, False})

    # -- what must NOT be listed -----------------------------------------

    def test_a_dead_registered_session_is_gone(self):
        """The log remembers it; the process table does not. ps wins."""
        self.write({"ts": self.now - 100, "event": "start",
                    "session_id": "dead", "pid": 904,
                    "pid_started": self.now - 100, "channel": "terminal"})
        self.assertEqual(self.read({}), [])

    def test_non_claude_processes_are_never_listed(self):
        t = {905: proc(905, 1, "/usr/bin/vim notes.txt", self.now - 10),
             906: proc(906, 1, "grep -r claude .", self.now - 10)}
        self.assertEqual(self.read(t), [])

    def test_a_claude_outside_the_jarvis_folder_is_excluded(self):
        t = {907: proc(907, 1, CLAUDE, self.now - 10)}
        self.cwd(907, self.now - 10, "/Users/mike/Dev/Synapse")
        self.assertEqual(self.read(t), [])

    def test_an_unreadable_cwd_is_included_not_dropped(self):
        """Over-report, never under-report. A row Serge can dismiss beats a
        session he never learns about -- that is the failure being fixed."""
        t = {908: proc(908, 1, CLAUDE, self.now - 10)}
        self.cwd(908, self.now - 10, "")
        rows = self.read(t)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["unregistered"])

    def test_a_recycled_pid_is_not_mistaken_for_the_old_session(self):
        """Same pid, different start time: the record must not be reused.
        It is still a live claude, so it appears -- as unregistered."""
        self.write({"ts": self.now - 900, "event": "start",
                    "session_id": "old", "pid": 909,
                    "pid_started": self.now - 900, "channel": "terminal"})
        t = {909: proc(909, 1, CLAUDE, self.now - 5)}     # started far later
        self.cwd(909, self.now - 5, ROOT)
        row = self.read(t)[0]
        self.assertTrue(row["unregistered"])
        self.assertEqual(row["session_id"], "")

    # -- shape of the rows -----------------------------------------------

    def test_newest_first(self):
        t = {910: proc(910, 1, CLAUDE, self.now - 500),
             911: proc(911, 1, CLAUDE, self.now - 10)}
        for pid, ago in ((910, 500), (911, 10)):
            self.cwd(pid, self.now - ago, ROOT)
        self.assertEqual([r["pid"] for r in self.read(t)], [911, 910])

    def test_age_is_measured_from_the_process_start(self):
        t = {912: proc(912, 1, CLAUDE, self.now - 120)}
        self.cwd(912, self.now - 120, ROOT)
        self.assertAlmostEqual(self.read(t)[0]["age"], 120, delta=5)

    def test_last_activity_comes_from_the_transcript_mtime(self):
        tr = self.tmp / "live.jsonl"
        tr.write_text("{}\n")
        self.write({"ts": self.now - 100, "event": "start",
                    "session_id": "withlog", "pid": 913,
                    "pid_started": self.now - 100, "channel": "terminal",
                    "transcript_path": str(tr)})
        t = {913: proc(913, 1, CLAUDE, self.now - 100)}
        self.assertAlmostEqual(self.read(t)[0]["last_activity"],
                               tr.stat().st_mtime, delta=1)

    def test_missing_transcript_gives_null_activity_not_an_exception(self):
        t = {914: proc(914, 1, CLAUDE, self.now - 10)}
        self.cwd(914, self.now - 10, ROOT)
        self.assertIsNone(self.read(t)[0]["last_activity"])

    def test_a_missing_log_file_still_lists_live_processes(self):
        """The registry must survive its own file being absent -- otherwise
        a first run, or a cleared log, reports an empty machine."""
        gone = self.tmp / "nope.jsonl"
        t = {915: proc(915, 1, CLAUDE, self.now - 10)}
        self.cwd(915, self.now - 10, ROOT)
        rows = sr.read_sessions(path=gone, table=t)
        self.assertEqual(len(rows), 1)

    def test_a_garbage_log_line_costs_one_row_not_the_panel(self):
        self.log.write_text("{not json at all\n")
        t = {916: proc(916, 1, CLAUDE, self.now - 10)}
        self.cwd(916, self.now - 10, ROOT)
        self.assertEqual(len(sr.read_sessions(path=self.log, table=t)), 1)

    # -- the cwd cache ----------------------------------------------------

    def test_cwd_cache_is_keyed_on_start_time_not_pid_alone(self):
        """A recycled pid must not inherit the dead process's directory."""
        self.cwd(917, 111.0, "/somewhere/old")
        self.cwd(917, 222.0, ROOT)
        self.assertEqual(sr.cwd_of(917, 111.0), "/somewhere/old")
        self.assertEqual(sr.cwd_of(917, 222.0), ROOT)

    def test_in_jarvis_accepts_subfolders_and_rejects_lookalikes(self):
        self.assertTrue(sr.in_jarvis(ROOT))
        self.assertTrue(sr.in_jarvis(os.path.join(ROOT, "Jarvis Visual")))
        self.assertFalse(sr.in_jarvis(ROOT + "-other"))
        self.assertTrue(sr.in_jarvis(""))


if __name__ == "__main__":
    unittest.main(verbosity=1)
