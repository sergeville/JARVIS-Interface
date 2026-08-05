#!/usr/bin/env python3
"""Tests for the stack event log -- log_event(), read_events(), diff_stack().

Run:  ./tests/run-tests.sh          (from Jarvis Visual/)
   or  python3 tests/test_stack_events.py

Why this file exists: Serge, 2026-08-05 -- "when I restart, is there something
that tells you the system is restarting? ... I want you to know everything."
The HUD's STACK block is present-tense only, so a restart showed up as nothing
but a PID that quietly changed, and the brain that came back had no memory that
it had been replaced. The event log is what carries that across the restart.

The whole design rests on two things being true, so both are tested hard:
  - the file survives what it describes (the server dies; the record does not);
  - the sampler's diff reports transitions and nothing else -- a logger that
    cries every 3 seconds is one nobody reads.

Everything runs against a temp file. The real .stack-events.jsonl is never
read or written here.
"""

import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "voice-web-server.py"


def load_server():
    """Import voice-web-server.py by path (its name isn't a valid module name)."""
    spec = importlib.util.spec_from_file_location("vws", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vws = load_server()


def comp(label, state, pids=(), port=None, since=None):
    """One component as sample_stack() builds it."""
    return {"label": label, "state": state, "pids": list(pids),
            "port": port, "since": since}


class TestDiffStack(unittest.TestCase):
    """The sampler's transition detector. Pure function, no files, no clock."""

    def test_first_sample_is_silent(self):
        # prev is None at boot. One row per component here would bury the real
        # events under a wall of noise at every single start.
        cur = [comp("browser Jarvis", "up", ["100"]),
               comp("brain", "up", ["200"])]
        self.assertEqual(vws.diff_stack(None, cur), [])

    def test_no_change_emits_nothing(self):
        cur = [comp("brain", "up", ["200"])]
        self.assertEqual(vws.diff_stack(list(cur), cur), [])

    def test_component_coming_up(self):
        prev = [comp("brain", "down")]
        cur = [comp("brain", "up", ["200"])]
        self.assertEqual(vws.diff_stack(prev, cur),
                         [("up", "brain", "came up")])

    def test_component_going_down_is_red(self):
        prev = [comp("browser Jarvis", "up", ["100"])]
        cur = [comp("browser Jarvis", "down")]
        self.assertEqual(vws.diff_stack(prev, cur),
                         [("down", "browser Jarvis", "went down")])

    def test_optional_component_standing_down_is_amber(self):
        # The terminal line is off by choice. Serge read a plain "not running"
        # as a failure once already -- "off" must never be reported as "down".
        prev = [comp("terminal line", "up", ["300"])]
        cur = [comp("terminal line", "off")]
        kind, label, detail = vws.diff_stack(prev, cur)[0]
        self.assertEqual(kind, "off")
        self.assertEqual(detail, "stood down")

    def test_pid_change_while_up_is_a_restart(self):
        # The case the whole feature exists for: a brain rebuild replaces the
        # process between two samples and never reads as "down" in between.
        prev = [comp("brain", "up", ["200"])]
        cur = [comp("brain", "up", ["201"])]
        kind, label, detail = vws.diff_stack(prev, cur)[0]
        self.assertEqual((kind, label), ("up", "brain"))
        self.assertIn("restarted", detail)
        self.assertIn("200", detail)
        self.assertIn("201", detail)

    def test_multi_pid_component_stable_is_silent(self):
        # browser Jarvis matches the uv wrapper AND the server it spawns.
        prev = [comp("browser Jarvis", "up", ["100", "104"])]
        cur = [comp("browser Jarvis", "up", ["100", "104"])]
        self.assertEqual(vws.diff_stack(prev, cur), [])

    def test_several_components_change_at_once(self):
        prev = [comp("browser Jarvis", "up", ["100"]), comp("brain", "up", ["200"]),
                comp("whisper", "up", ["300"])]
        cur = [comp("browser Jarvis", "down"), comp("brain", "down"),
               comp("whisper", "up", ["300"])]
        out = vws.diff_stack(prev, cur)
        self.assertEqual(len(out), 2)
        self.assertEqual({e[1] for e in out}, {"browser Jarvis", "brain"})

    def test_unknown_component_is_skipped_not_crashed(self):
        # A component added mid-run has nothing to compare against.
        prev = [comp("brain", "up", ["200"])]
        cur = [comp("brain", "up", ["200"]), comp("new thing", "up", ["999"])]
        self.assertEqual(vws.diff_stack(prev, cur), [])

    def test_state_change_wins_over_pid_change(self):
        # Both changed; "went down" is the event worth reporting, once.
        prev = [comp("brain", "up", ["200"])]
        cur = [comp("brain", "down", [])]
        out = vws.diff_stack(prev, cur)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "down")


class TestLogAndRead(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.f = Path(self._tmp.name) / ".stack-events.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read_round_trip(self):
        vws.log_event("up", "brain", "warm", path=self.f)
        evs = vws.read_events(path=self.f)
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["kind"], evs[0]["label"], evs[0]["detail"]),
                         ("up", "brain", "warm"))
        self.assertGreater(evs[0]["ts"], 0)

    def test_newest_first(self):
        for i in range(3):
            vws.log_event("up", f"c{i}", "", path=self.f)
        self.assertEqual([e["label"] for e in vws.read_events(path=self.f)],
                         ["c2", "c1", "c0"])

    def test_limit_is_honoured(self):
        for i in range(30):
            vws.log_event("up", f"c{i}", "", path=self.f)
        self.assertEqual(len(vws.read_events(limit=5, path=self.f)), 5)
        self.assertEqual(len(vws.read_events(path=self.f)), 20)  # default

    def test_missing_file_reads_empty(self):
        # Before the first event ever, and on a fresh machine.
        self.assertEqual(vws.read_events(path=self.f), [])

    def test_append_only_survives_a_restart(self):
        # The core promise: a second "process" writing to the same path adds to
        # the history instead of replacing it.
        vws.log_event("off", "stack", "stop requested by Serge", path=self.f)
        vws.log_event("up", "stack", "Jarvis is up -- brain warm", path=self.f)
        evs = vws.read_events(path=self.f)
        self.assertEqual([e["detail"] for e in evs],
                         ["Jarvis is up -- brain warm", "stop requested by Serge"])

    def test_bash_written_line_is_read(self):
        # jarvis.sh writes this exact shape with printf. If the two writers ever
        # disagree on format, this test is what catches it.
        self.f.write_text(
            '{"ts": 1785900000, "kind": "off", "label": "stack", '
            '"detail": "stop requested by Serge"}\n')
        evs = vws.read_events(path=self.f)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["label"], "stack")
        self.assertEqual(evs[0]["ts"], 1785900000)

    def test_garbage_line_costs_one_row_not_the_panel(self):
        # A half-written line from a concurrent bash append must not blank the
        # strip -- the events around it still have to render.
        vws.log_event("up", "brain", "warm", path=self.f)
        with self.f.open("a") as fh:
            fh.write("{not json at all\n\n")
        vws.log_event("down", "brain", "rebuilt", path=self.f)
        evs = vws.read_events(path=self.f)
        self.assertEqual([e["detail"] for e in evs], ["rebuilt", "warm"])

    def test_record_without_ts_is_skipped(self):
        self.f.write_text('{"kind": "up", "label": "brain"}\n'
                          '{"ts": 1785900000, "kind": "up", "label": "ok"}\n')
        evs = vws.read_events(path=self.f)
        self.assertEqual([e["label"] for e in evs], ["ok"])

    def test_trim_keeps_the_newest(self):
        for i in range(vws.EVENTS_TRIM_AT + 5):
            vws.log_event("up", f"c{i}", "", path=self.f)
        lines = self.f.read_text().splitlines()
        self.assertLessEqual(len(lines), vws.EVENTS_TRIM_AT)
        # The newest event must survive the trim -- trimming the wrong end
        # would leave the panel showing ancient history.
        self.assertEqual(json.loads(lines[-1])["label"],
                         f"c{vws.EVENTS_TRIM_AT + 4}")

    def test_logger_never_raises(self):
        # A logger that can break the server it watches is worse than none.
        # A directory that does not exist is the realistic failure.
        bad = Path(self._tmp.name) / "no-such-dir" / "events.jsonl"
        vws.log_event("up", "brain", "warm", path=bad)   # must not raise
        self.assertEqual(vws.read_events(path=bad), [])

    def test_detail_with_quotes_round_trips(self):
        # json.dumps handles it; this guards against anyone "simplifying" the
        # writer into string concatenation later.
        vws.log_event("up", "brain", 'restarted "twice" -- pid 1 -> 2',
                      path=self.f)
        self.assertEqual(vws.read_events(path=self.f)[0]["detail"],
                         'restarted "twice" -- pid 1 -> 2')


class TestEventCache(unittest.TestCase):
    """read_events() is called on every /signals poll -- 15 Hz -- so it caches
    on the file's (mtime_ns, size). The risk of any cache is serving stale
    data, so that is what these test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.f = Path(self._tmp.name) / ".stack-events.jsonl"
        vws._EVENT_CACHE.update(key=None, events=[])

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_new_event_invalidates_the_cache(self):
        vws.log_event("up", "brain", "warm", path=self.f)
        self.assertEqual(len(vws.read_events(path=self.f)), 1)
        vws.log_event("down", "brain", "rebuilt", path=self.f)
        evs = vws.read_events(path=self.f)
        self.assertEqual([e["detail"] for e in evs], ["rebuilt", "warm"])

    def test_cache_serves_any_limit(self):
        # One cache entry, different callers. A limit must never be baked in.
        for i in range(10):
            vws.log_event("up", f"c{i}", "", path=self.f)
        self.assertEqual(len(vws.read_events(limit=3, path=self.f)), 3)
        self.assertEqual(len(vws.read_events(limit=8, path=self.f)), 8)
        self.assertEqual(len(vws.read_events(limit=3, path=self.f)), 3)

    def test_two_files_do_not_share_a_cache_entry(self):
        # The path is part of the key: tests pass one path, the server another.
        other = Path(self._tmp.name) / "other.jsonl"
        vws.log_event("up", "a", "", path=self.f)
        vws.log_event("up", "b", "", path=other)
        self.assertEqual(vws.read_events(path=self.f)[0]["label"], "a")
        self.assertEqual(vws.read_events(path=other)[0]["label"], "b")
        self.assertEqual(vws.read_events(path=self.f)[0]["label"], "a")

    def test_a_trim_invalidates_the_cache(self):
        for i in range(vws.EVENTS_TRIM_AT + 5):
            vws.log_event("up", f"c{i}", "", path=self.f)
        self.assertEqual(vws.read_events(limit=1, path=self.f)[0]["label"],
                         f"c{vws.EVENTS_TRIM_AT + 4}")


class TestLstartEpoch(unittest.TestCase):
    """The STACK panel's start times and uptimes, which were dead.

    Serge asked for per-component start time and uptime on 2026-08-04. They
    silently showed nothing from the day they shipped: _lstart_epoch() parsed
    only "%a %b %d", while `ps` on this machine prints DAY BEFORE MONTH. Every
    row returned None and /signals served `since: null`.

    The lesson these pin: a parser that returns None on every input still
    looks like working code -- nothing raises, nothing logs, the panel just
    renders blank. Only a test that asserts a real value catches it.
    """

    # Exactly the shape sample_stack() feeds it: pid, lstart, command.
    ROW_LOCAL = "  123 Tue  4 Aug 07:23:24 2026     /usr/bin/python3 server.py"
    ROW_US = "  123 Tue Aug  4 07:23:24 2026     /usr/bin/python3 server.py"

    def test_this_machines_day_before_month_order_parses(self):
        self.assertIsNotNone(vws._lstart_epoch(self.ROW_LOCAL))

    def test_documented_month_before_day_order_still_parses(self):
        self.assertIsNotNone(vws._lstart_epoch(self.ROW_US))

    def test_both_orders_mean_the_same_instant(self):
        self.assertEqual(vws._lstart_epoch(self.ROW_LOCAL),
                         vws._lstart_epoch(self.ROW_US))

    def test_the_parsed_instant_is_correct(self):
        got = time.localtime(vws._lstart_epoch(self.ROW_LOCAL))
        self.assertEqual((got.tm_year, got.tm_mon, got.tm_mday,
                          got.tm_hour, got.tm_min, got.tm_sec),
                         (2026, 8, 4, 7, 23, 24))

    def test_the_command_tail_is_not_mistaken_for_the_date(self):
        # The registry's parser takes the LAST five tokens; this one cannot,
        # because the command line sits after the date. A row whose command
        # ends in date-like words must still parse to the real start time.
        row = "  123 Tue  4 Aug 07:23:24 2026     python3 Mon 1 Jan 00:00:00 2020"
        got = time.localtime(vws._lstart_epoch(row))
        self.assertEqual((got.tm_year, got.tm_mon, got.tm_mday), (2026, 8, 4))

    def test_a_real_ps_row_from_this_machine_parses(self):
        # The end-to-end guard: whatever `ps` actually prints here, today,
        # must parse. A fixture can go stale; the live command cannot.
        out = subprocess.run(["ps", "-o", "pid=,lstart=,command=",
                              "-p", str(os.getpid())],
                             capture_output=True, text=True).stdout.strip()
        self.assertIsNotNone(vws._lstart_epoch(out))

    def test_a_start_time_is_in_the_past(self):
        out = subprocess.run(["ps", "-o", "pid=,lstart=,command=",
                              "-p", str(os.getpid())],
                             capture_output=True, text=True).stdout.strip()
        self.assertLessEqual(vws._lstart_epoch(out), time.time() + 2)

    def test_garbage_returns_none_rather_than_raising(self):
        for bad in ("", "   ", "not a row", "123 only four fields here",
                    "123 Xxx 99 Zzz 25:99:99 2026 cmd"):
            self.assertIsNone(vws._lstart_epoch(bad))


class TestStatsSampleRate(unittest.TestCase):
    """Serge, 2026-08-05: "the CPU, the MEM ... it does not refresh fast
    enough." It was the sample rate, not the drawing -- the sampler slept 2.0 s
    between readings. These guard the number itself, because raising it back is
    a one-character edit whose only symptom is a panel that feels sluggish, and
    nothing would fail."""

    def test_the_sampler_reads_at_least_once_a_second(self):
        self.assertLessEqual(vws.STATS_EVERY_S, 1.0)

    def test_the_rate_is_not_so_fast_it_measures_itself(self):
        # Each sample shells out to ps -A, vm_stat and netstat. Below a second
        # we would spend real CPU measuring CPU for smoothness nobody can see.
        self.assertGreaterEqual(vws.STATS_EVERY_S, 0.5)

    def test_the_stats_cache_carries_a_sample_timestamp(self):
        # The page appends to its sparkline history only when `at` changes.
        # Drop this field and /signals' 15 Hz poll turns "the last minute" into
        # the last four seconds -- with no visible symptom.
        self.assertIn("at", vws._STATS)

    def test_the_sparkline_history_covers_a_full_minute_at_this_rate(self):
        page = (HERE.parent / "jarvis.html").read_text()
        m = re.search(r"const SPARK_N\s*=\s*(\d+)", page)
        self.assertIsNotNone(m, "SPARK_N not found in jarvis.html")
        span = int(m.group(1)) * vws.STATS_EVERY_S
        self.assertGreaterEqual(span, 60.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
