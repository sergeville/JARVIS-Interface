#!/usr/bin/env python3
"""The gate on vault-tools/disk-watch.py.

The load-bearing test in this file is TestItCannotDelete. Serge's ruling on
2026-08-15 was ALERT ONLY, and the reason he gave was fear of losing
something that should not have gone. A promise like that kept only by nobody
adding the code later is not a promise -- so it is asserted against this
file's own syntax tree, and the assertion is about the CLASS (any delete
call, any spelling) rather than about the three functions that exist today.

That is the lesson this project learned the hard way on 08-14 and 08-15:
a guard aimed at the instance leaves the class open, and the class is what
comes back.
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "vault-tools", "disk-watch.py")


def load():
    spec = importlib.util.spec_from_file_location("disk_watch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dw = load()
GIB = 1024 ** 3


class TestItCannotDelete(unittest.TestCase):
    """ALERT ONLY, asserted rather than remembered."""

    FORBIDDEN_ATTRS = {
        ("os", "remove"), ("os", "unlink"), ("os", "rmdir"), ("os", "removedirs"),
        ("shutil", "rmtree"), ("pathlib", "unlink"),
    }
    FORBIDDEN_NAMES = {"remove", "unlink", "rmtree", "rmdir", "removedirs"}

    def setUp(self):
        with open(SCRIPT) as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def test_it_calls_no_deleting_function_by_any_spelling(self):
        """os.remove, shutil.rmtree, a bare unlink, or Path(x).unlink()."""
        bad = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in self.FORBIDDEN_NAMES:
                bad.append(f"line {node.lineno}: .{f.attr}()")
            if isinstance(f, ast.Name) and f.id in self.FORBIDDEN_NAMES:
                bad.append(f"line {node.lineno}: {f.id}()")
        self.assertEqual(bad, [], f"disk-watch.py must never delete: {bad}")

    def test_it_shells_out_to_no_removing_command(self):
        """A subprocess is the obvious way around the check above."""
        removers = {"rm", "rmdir", "srm", "trash", "shred", "unlink"}
        bad = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in node.args:
                if isinstance(arg, ast.List) and arg.elts:
                    first = arg.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        if os.path.basename(first.value) in removers:
                            bad.append(f"line {node.lineno}: {first.value}")
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    words = arg.value.split()
                    if words and os.path.basename(words[0]) in removers:
                        bad.append(f"line {node.lineno}: {arg.value[:40]}")
        self.assertEqual(bad, [], f"disk-watch.py must never shell out to a remover: {bad}")

    def test_it_opens_nothing_for_writing_except_its_own_two_files(self):
        """A truncating open() is a delete wearing a different hat."""
        allowed = {"path", "tmp", "path + \".tmp\""}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = None
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                if mode and ("w" in mode or "a" in mode):
                    target = ast.unparse(node.args[0])
                    self.assertIn(
                        target, allowed,
                        f"line {node.lineno}: writes to {target}, which is not its state or event file")

    def test_the_delete_check_is_not_vacuous(self):
        """Prove the check above can actually fail -- a guard nobody has seen
        go red is a guard nobody has tested."""
        tree = ast.parse("import shutil\nshutil.rmtree('/')\n")
        found = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in self.FORBIDDEN_NAMES]
        self.assertTrue(found, "the matcher cannot see an obvious rmtree")


class TestTheDecision(unittest.TestCase):
    """decide() is pure, so every case is reachable without faking a disk."""

    def test_a_healthy_disk_says_nothing(self):
        self.assertIsNone(dw.decide(free=100 * GIB, dropped=0, covered=900))

    def test_below_the_floor_alarms(self):
        alarm = dw.decide(free=10 * GIB, dropped=0, covered=900)
        self.assertEqual(alarm["kind"], "floor")

    def test_exactly_at_the_floor_is_not_below_it(self):
        self.assertIsNone(dw.decide(free=dw.FLOOR_BYTES, dropped=0, covered=900))

    def test_one_byte_under_the_floor_alarms(self):
        self.assertEqual(dw.decide(free=dw.FLOOR_BYTES - 1, dropped=0, covered=900)["kind"], "floor")

    def test_a_fast_drain_alarms_even_on_a_roomy_disk(self):
        """THE CHROME CASE. 130 GB free -- a floor check sees nothing wrong."""
        alarm = dw.decide(free=130 * GIB, dropped=6 * GIB, covered=600)
        self.assertEqual(alarm["kind"], "drain")

    def test_exactly_the_drain_threshold_alarms(self):
        self.assertEqual(dw.decide(free=130 * GIB, dropped=dw.DRAIN_BYTES, covered=600)["kind"], "drain")

    def test_a_drain_just_under_the_threshold_is_quiet(self):
        self.assertIsNone(dw.decide(free=130 * GIB, dropped=dw.DRAIN_BYTES - 1, covered=600))

    def test_a_drain_with_no_history_covered_is_never_trusted(self):
        """covered == 0 means fewer than two samples. A huge 'drop' computed
        from nothing must not alarm."""
        self.assertIsNone(dw.decide(free=130 * GIB, dropped=99 * GIB, covered=0))

    def test_freeing_space_never_alarms(self):
        self.assertIsNone(dw.decide(free=130 * GIB, dropped=-20 * GIB, covered=900))

    def test_the_floor_outranks_the_drain_when_both_fire(self):
        alarm = dw.decide(free=1 * GIB, dropped=50 * GIB, covered=900)
        self.assertEqual(alarm["kind"], "floor")

    def test_the_alarm_says_how_much_and_how_long(self):
        alarm = dw.decide(free=130 * GIB, dropped=6 * GIB, covered=600)
        self.assertIn("6.0 GB", alarm["headline"])
        self.assertIn("10 min", alarm["headline"])


class TestTheWindow(unittest.TestCase):

    def test_it_measures_against_the_OLDEST_sample_in_the_window(self):
        """A slow steady bleed must accumulate. Measured against the previous
        sample only, five separate 1 GB drops look like five quiet ticks."""
        now = 1000.0
        samples = [[now - 800 + i * 100, (100 - i) * GIB] for i in range(9)]
        dropped, covered = dw.drop_over_window(samples, now, window=900)
        self.assertEqual(dropped, 8 * GIB)
        self.assertAlmostEqual(covered, 800)

    def test_samples_older_than_the_window_are_ignored(self):
        now = 1000.0
        samples = [[0.0, 500 * GIB], [now - 60, 100 * GIB], [now, 99 * GIB]]
        dropped, _ = dw.drop_over_window(samples, now, window=900)
        self.assertEqual(dropped, 1 * GIB)

    def test_a_single_sample_is_not_evidence(self):
        self.assertEqual(dw.drop_over_window([[1000.0, 5 * GIB]], 1000.0), (0, 0.0))

    def test_no_samples_at_all_is_not_evidence(self):
        self.assertEqual(dw.drop_over_window([], 1000.0), (0, 0.0))

    def test_old_samples_are_pruned_but_the_day_is_kept(self):
        now = 1000000.0
        samples = [[now - 200000, 1], [now - 100, 2]]
        kept = dw.prune(samples, now)
        self.assertEqual(kept, [[now - 100, 2]])


class TestTheCooldown(unittest.TestCase):

    def alarm(self, kind, severity):
        return {"kind": kind, "severity": severity, "headline": "", "detail": ""}

    def test_a_first_alarm_always_speaks(self):
        self.assertTrue(dw.should_alert(self.alarm("drain", 6 * GIB), {}, 1000.0))

    def test_a_repeat_inside_the_cooldown_stays_quiet(self):
        last = {"kind": "drain", "ts": 1000.0, "severity": 6 * GIB}
        self.assertFalse(dw.should_alert(self.alarm("drain", 6 * GIB), last, 1100.0))

    def test_it_speaks_again_once_the_cooldown_expires(self):
        last = {"kind": "drain", "ts": 1000.0, "severity": 6 * GIB}
        self.assertTrue(dw.should_alert(self.alarm("drain", 6 * GIB), last, 1000.0 + dw.COOLDOWN))

    def test_a_different_condition_always_speaks(self):
        last = {"kind": "drain", "ts": 1000.0, "severity": 6 * GIB}
        self.assertTrue(dw.should_alert(self.alarm("floor", 5 * GIB), last, 1001.0))

    def test_a_drain_getting_materially_worse_speaks_inside_the_cooldown(self):
        last = {"kind": "drain", "ts": 1000.0, "severity": 6 * GIB}
        self.assertTrue(dw.should_alert(self.alarm("drain", 12 * GIB), last, 1001.0))

    def test_a_FLOOR_getting_worse_means_LESS_space_not_more(self):
        """The direction trap: for a floor alarm severity is free space, so
        worse is SMALLER. Compared the same way as a drain, a disk falling
        from 15 GB to 5 GB would read as recovering and stay silent."""
        last = {"kind": "floor", "ts": 1000.0, "severity": 15 * GIB}
        self.assertTrue(dw.should_alert(self.alarm("floor", 5 * GIB), last, 1001.0))

    def test_a_floor_alarm_recovering_slightly_stays_quiet(self):
        last = {"kind": "floor", "ts": 1000.0, "severity": 15 * GIB}
        self.assertFalse(dw.should_alert(self.alarm("floor", 16 * GIB), last, 1001.0))

    def test_a_corrupt_severity_in_the_state_file_speaks_rather_than_crashes(self):
        last = {"kind": "drain", "ts": 1000.0, "severity": "lots"}
        self.assertTrue(dw.should_alert(self.alarm("drain", 6 * GIB), last, 1001.0))


class TestTheStateFile(unittest.TestCase):
    """It runs unattended. A watcher that dies on its own state file is a
    watcher that is silently off, which is worse than no watcher at all."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "state.json")

    def test_a_missing_state_file_is_a_fresh_start(self):
        self.assertEqual(dw.load_state(self.path), {})

    def test_a_corrupt_state_file_is_a_fresh_start(self):
        with open(self.path, "w") as fh:
            fh.write("{not json at all")
        self.assertEqual(dw.load_state(self.path), {})

    def test_a_state_file_holding_a_LIST_is_a_fresh_start(self):
        with open(self.path, "w") as fh:
            json.dump([1, 2, 3], fh)
        self.assertEqual(dw.load_state(self.path), {})

    def test_an_unreadable_state_file_is_a_fresh_start(self):
        with open(self.path, "w") as fh:
            fh.write("{}")
        os.chmod(self.path, 0o000)
        try:
            self.assertEqual(dw.load_state(self.path), {})
        finally:
            os.chmod(self.path, 0o600)

    def test_a_round_trip_survives(self):
        dw.save_state({"samples": [[1.0, 2]]}, self.path)
        self.assertEqual(dw.load_state(self.path), {"samples": [[1.0, 2]]})

    def test_the_write_is_atomic_so_a_kill_never_leaves_half_a_file(self):
        dw.save_state({"samples": []}, self.path)
        self.assertFalse(os.path.exists(self.path + ".tmp"))


class TestEndToEnd(unittest.TestCase):
    """Drive check() against a sandboxed state and event file."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "state.json")
        self.events = os.path.join(self.dir, "events.jsonl")

    def test_a_tick_records_a_sample_and_touches_nothing_else(self):
        before = sorted(os.listdir(self.dir))
        dw.check(state_path=self.state, events_path=self.events, announce=False)
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(before + ["state.json"]))
        state = dw.load_state(self.state)
        self.assertEqual(len(state["samples"]), 1)

    def test_repeated_ticks_accumulate_history(self):
        for _ in range(3):
            dw.check(state_path=self.state, events_path=self.events, announce=False)
        self.assertEqual(len(dw.load_state(self.state)["samples"]), 3)

    def test_a_real_tick_on_this_machine_reports_a_plausible_free_figure(self):
        result = dw.check(state_path=self.state, events_path=self.events, announce=False)
        self.assertGreater(result["free"], 0)
        self.assertLess(result["free"], 500 * 1024 ** 4)

    def test_the_event_log_line_is_valid_jsonl_the_HUD_can_read(self):
        dw.log_event("disk is draining: 6.0 GB gone in 10 min", self.events)
        with open(self.events) as fh:
            lines = fh.read().strip().split("\n")
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["label"], "disk")
        self.assertEqual(rec["kind"], "warn")
        self.assertIn("draining", rec["detail"])

    def test_log_event_never_raises_on_an_unwritable_path(self):
        self.assertFalse(dw.log_event("x", os.path.join(self.dir, "nope", "x.jsonl")))

    def test_notify_never_raises_even_when_osascript_is_unavailable(self):
        real = dw.subprocess.run

        def boom(*a, **k):
            raise OSError("no osascript here")

        dw.subprocess.run = boom
        try:
            self.assertFalse(dw.notify("t", "m"))
        finally:
            dw.subprocess.run = real

    def test_status_mode_alerts_nobody(self):
        """--status is for a human asking. It must never fire a notification
        or write an event line, however bad the numbers look."""
        out = subprocess.run(
            [sys.executable, SCRIPT, "--status", "--json"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0)
        payload = json.loads(out.stdout)
        self.assertFalse(payload["alerted"])

    def test_it_runs_as_a_plain_script_and_exits_0(self):
        out = subprocess.run(
            [sys.executable, SCRIPT, "--status"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("free:", out.stdout)

    def test_it_returns_promptly_with_stdin_left_OPEN(self):
        """The class of bug this project spent two days on: a program that
        reads a silent stdin and never comes back. This one must not read
        stdin at all."""
        r, w = os.pipe()
        try:
            start = time.monotonic()
            out = subprocess.run([sys.executable, SCRIPT, "--status"],
                                 stdin=r, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0)
            self.assertLess(time.monotonic() - start, 30.0)
        finally:
            os.close(r)
            os.close(w)


class TestItNamesWhereTheSpaceWent(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_it_finds_the_biggest_file(self):
        with open(os.path.join(self.dir, "small"), "wb") as fh:
            fh.write(b"x" * 100)
        with open(os.path.join(self.dir, "big"), "wb") as fh:
            fh.write(b"x" * 100000)
        biggest = dw.biggest_under([self.dir], limit=1)
        self.assertEqual(os.path.basename(biggest[0][1]), "big")

    def test_it_measures_a_directory_not_just_a_file(self):
        sub = os.path.join(self.dir, "adir")
        os.makedirs(sub)
        with open(os.path.join(sub, "f"), "wb") as fh:
            fh.write(b"x" * 50000)
        biggest = dw.biggest_under([self.dir], limit=1)
        self.assertEqual(os.path.basename(biggest[0][1]), "adir")
        self.assertGreaterEqual(biggest[0][0], 50000)

    def test_an_unreadable_root_is_skipped_not_raised(self):
        """Decoration on an alert must never be the reason the alert fails."""
        self.assertEqual(dw.biggest_under(["/definitely/not/here"]), [])

    def test_a_symlink_is_never_followed(self):
        """Following a symlink out of temp is how a 'name the biggest thing'
        walk turns into a walk of the whole disk."""
        os.symlink("/", os.path.join(self.dir, "escape"))
        with open(os.path.join(self.dir, "real"), "wb") as fh:
            fh.write(b"x" * 1000)
        names = [os.path.basename(p) for _, p in dw.biggest_under([self.dir], limit=5)]
        self.assertNotIn("escape", names)

    def test_the_scan_is_bounded_in_time(self):
        deep = self.dir
        for i in range(40):
            deep = os.path.join(deep, f"d{i}")
        os.makedirs(deep)
        start = time.monotonic()
        dw.biggest_under([self.dir], limit=1)
        self.assertLess(time.monotonic() - start, 20.0)

    def test_it_leaves_every_file_it_looked_at_exactly_where_it_was(self):
        """The whole point. It names, it does not touch."""
        paths = []
        for name in ("a", "b", "c"):
            p = os.path.join(self.dir, name)
            with open(p, "wb") as fh:
                fh.write(b"x" * 1000)
            paths.append(p)
        before = {p: (os.stat(p).st_size, os.stat(p).st_mtime) for p in paths}
        dw.biggest_under([self.dir], limit=3)
        after = {p: (os.stat(p).st_size, os.stat(p).st_mtime) for p in paths}
        self.assertEqual(before, after)


class TestHuman(unittest.TestCase):

    def test_it_reads_as_a_person_would_say_it(self):
        self.assertEqual(dw.human(0), "0 B")
        self.assertEqual(dw.human(1024), "1.0 KB")
        self.assertEqual(dw.human(5 * GIB), "5.0 GB")

    def test_a_loss_keeps_its_sign(self):
        self.assertEqual(dw.human(-2 * GIB), "-2.0 GB")


class TestItRunsWHERELAUNCHDCANRUNIT(unittest.TestCase):
    """The failure that actually happened, 2026-08-15 ~10:45 AM.

    The first install pointed the launch agent straight at
    vault-tools/disk-watch.py. launchd has no Documents-folder access, so
    every run exited 2 with 'Operation not permitted' -- while the same
    script, run by hand from a shell that DOES have that access, worked
    perfectly. Proven as the author runs it, never as the system runs it:
    the third time this project has met that exact shape in two days.
    """

    def test_the_state_home_is_overridable_so_the_agent_can_be_told_where_to_write(self):
        d = tempfile.mkdtemp()
        old = os.environ.get("JARVIS_DISK_WATCH_HOME")
        os.environ["JARVIS_DISK_WATCH_HOME"] = d
        try:
            self.assertEqual(dw.state_home(), d)
        finally:
            if old is None:
                del os.environ["JARVIS_DISK_WATCH_HOME"]
            else:
                os.environ["JARVIS_DISK_WATCH_HOME"] = old

    def test_with_no_override_it_falls_back_to_a_directory_that_EXISTS(self):
        old = os.environ.pop("JARVIS_DISK_WATCH_HOME", None)
        try:
            self.assertTrue(os.path.isdir(dw.state_home()))
        finally:
            if old is not None:
                os.environ["JARVIS_DISK_WATCH_HOME"] = old

    def test_it_PROBES_for_write_access_rather_than_assuming_it(self):
        """The one line that separates the working copy from the broken one."""
        src = open(SCRIPT).read()
        self.assertIn("os.access(", src)

    def test_the_plist_template_does_NOT_point_into_the_repo(self):
        tpl = os.path.join(ROOT, "templates", "com.jarvis.disk-watch.plist")
        self.assertTrue(os.path.isfile(tpl), "the launch agent template is missing")
        body = open(tpl).read()
        prog = body.split("<key>ProgramArguments</key>", 1)[1].split("</array>", 1)[0]
        self.assertNotIn("{{JARVIS_ROOT}}", prog,
                         "the agent points into Documents, where launchd cannot read")
        self.assertIn("{{WATCH_HOME}}", prog)

    def test_the_plist_template_is_valid_once_rendered(self):
        tpl = os.path.join(ROOT, "templates", "com.jarvis.disk-watch.plist")
        body = open(tpl).read().replace("{{WATCH_HOME}}", "/tmp/x").replace("{{JARVIS_ROOT}}", "/tmp/y")
        d = tempfile.mkdtemp()
        p = os.path.join(d, "t.plist")
        with open(p, "w") as fh:
            fh.write(body)
        out = subprocess.run(["plutil", "-lint", p], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_the_agent_closes_its_own_stdin(self):
        tpl = open(os.path.join(ROOT, "templates", "com.jarvis.disk-watch.plist")).read()
        self.assertIn("StandardInPath", tpl)
        self.assertIn("/dev/null", tpl)

    def test_install_sh_DELIVERS_the_copy_every_run_rather_than_only_creating_it(self):
        """install.sh's own bug, one morning earlier: 'already there' was
        treated as 'nothing to do', so no later change ever arrived. This
        step must decide by CONTENT."""
        body = open(os.path.join(ROOT, "install.sh")).read()
        step = body.split("install_disk_watch()", 1)[1].split("\ninstall_disk_watch", 1)[0]
        self.assertIn("cmp -s", step, "the step must compare content, not existence")
        self.assertIn("bootout", step, "bootstrap refuses a loaded label; the old copy would keep running")

    def test_THE_DEPLOYED_COPY_HAS_NOT_DRIFTED_FROM_THE_REPO(self):
        """A copy is a delivery, never a second source. If one is installed
        on this machine it must be byte-identical -- and if it is not, this
        goes red rather than the two quietly diverging."""
        dest = os.path.expanduser("~/Library/Application Support/Jarvis/disk-watch.py")
        if not os.path.isfile(dest):
            self.skipTest("no deployed copy on this machine")
        with open(SCRIPT, "rb") as a, open(dest, "rb") as b:
            self.assertEqual(a.read(), b.read(),
                             "the deployed watcher has drifted from the repo -- re-run ./install.sh")


class TestTheHUDIsThePrimaryChannel(unittest.TestCase):
    """Serge saw nothing when the notification 'succeeded' (2026-08-15).

    osascript exits 0 whether or not a banner reaches the screen, so the old
    channel could not report its own delivery -- the proxy-for-the-property
    mistake, in the one line that told him it worked. The HUD acknowledges,
    so a 200 means the alert is genuinely somewhere he can see it.
    """

    def serve(self, handler_status=200, body=b'{"ok": true}'):
        """A one-shot local server standing in for the HUD."""
        import http.server, threading
        seen = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                seen["path"] = self.path
                seen["body"] = json.loads(self.rfile.read(n) or b"{}")
                self.send_response(handler_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        self.addCleanup(srv.server_close)
        return f"http://127.0.0.1:{srv.server_port}/disk-alert", seen

    def test_an_acknowledged_post_is_reported_as_delivered(self):
        url, seen = self.serve()
        self.assertTrue(dw.tell_the_hud("disk is draining", url))
        self.assertEqual(seen["body"]["detail"], "disk is draining")

    def test_a_server_that_says_NOT_ok_is_NOT_delivered(self):
        url, _ = self.serve(body=b'{"ok": false, "error": "no"}')
        self.assertFalse(dw.tell_the_hud("x", url))

    def test_a_non_200_is_NOT_delivered(self):
        url, _ = self.serve(handler_status=503, body=b'{"ok": true}')
        self.assertFalse(dw.tell_the_hud("x", url))

    def test_a_HUD_that_is_simply_not_running_returns_false_and_never_raises(self):
        self.assertFalse(dw.tell_the_hud("x", "http://127.0.0.1:9/disk-alert", timeout=1.0))

    def test_the_watcher_does_not_DIE_when_the_HUD_is_down(self):
        """The whole point of a fallback: losing a channel must not lose the
        watcher."""
        d = tempfile.mkdtemp()
        out = subprocess.run(
            [sys.executable, SCRIPT, "--status", "--json"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            env={**os.environ, "JARVIS_DISK_WATCH_HOME": d})
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_the_server_route_exists_and_is_wired(self):
        server = os.path.join(ROOT, "Jarvis Visual", "voice-web-server.py")
        body = open(server).read()
        self.assertIn('web.post("/disk-alert"', body, "the route is not in the table")
        self.assertIn("async def disk_alert", body)

    def test_the_route_REFUSES_anything_that_is_not_loopback(self):
        """It writes to a file every session reads. That is an authority, and
        an authority reachable from the network is a different program."""
        server = os.path.join(ROOT, "Jarvis Visual", "voice-web-server.py")
        body = open(server).read()
        handler = body.split("async def disk_alert", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn('request.remote', handler)
        self.assertIn('"127.0.0.1"', handler)
        self.assertIn("403", handler)

    def test_the_route_cannot_be_told_what_KIND_of_event_to_write(self):
        """A poster that could name its own kind and label could dress itself
        up as the brain, the stack, or anything else on that log."""
        server = os.path.join(ROOT, "Jarvis Visual", "voice-web-server.py")
        body = open(server).read()
        handler = body.split("async def disk_alert", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn('log_event("warn", "disk"', handler)
        self.assertNotIn('body.get("kind")', handler)
        self.assertNotIn('body.get("label")', handler)


class TestNothingHereIsUNTRACKED(unittest.TestCase):
    """08-14 and 08-15 both shipped a file git had never heard of, and the
    full green suite could not see it because the file exists on this
    machine. Asserted, not remembered."""

    def test_the_script_and_this_test_file_are_both_tracked(self):
        for path in (SCRIPT, os.path.abspath(__file__)):
            out = subprocess.run(["git", "ls-files", "--error-unmatch", path],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0,
                             f"{os.path.basename(path)} is UNTRACKED -- a fresh clone would not have it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
