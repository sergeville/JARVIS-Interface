#!/usr/bin/env python3
"""The suite runner itself is code, and nothing tested it.

Serge, 2026-08-08: the suite went red once and green four times on an
unchanged tree, and the red run could not be chased -- 43 files scroll past
and the summary is one line saying the change is not accepted. This file
guards the fix: a red run must NAME the files that failed.

WHY IT RUNS THE REAL SCRIPT INSTEAD OF READING IT. Every guard on this
project that read source instead of running it has been walked past, several
times in one week. So each test here builds a throwaway tree -- a `tests/`
folder with planted passing and failing files, and a fake venv python beside
it where the runner expects one -- and executes `run-tests.sh` for real.
The live tests are never run by these tests; the copy is what runs.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run-tests.sh")


def build_tree(py_files, js_files):
    """A disposable copy of the runner with planted test files.

    py_files / js_files: {filename: exit_code}. Returns the tests dir.
    The layout mirrors the real one because the runner resolves its python
    as ../../voice-line/.venv/bin/python3 from its own location -- a flat
    temp dir would fail for a reason that has nothing to do with the test.
    """
    root = tempfile.mkdtemp()
    tests = os.path.join(root, "Jarvis Visual", "tests")
    os.makedirs(tests)
    venv = os.path.join(root, "voice-line", ".venv", "bin")
    os.makedirs(venv)

    # A stand-in python that just runs the file it is handed as a shell
    # script. The planted "tests" are therefore trivial and their exit code
    # is whatever we planted -- the runner cannot tell the difference, which
    # is the point: we are testing the runner, not python.
    shim = os.path.join(venv, "python3")
    with open(shim, "w") as f:
        f.write('#!/bin/sh\nexec /bin/sh "$1"\n')
    os.chmod(shim, 0o755)

    shutil.copy(RUNNER, os.path.join(tests, "run-tests.sh"))
    os.chmod(os.path.join(tests, "run-tests.sh"), 0o755)

    for name, code in py_files.items():
        with open(os.path.join(tests, name), "w") as f:
            f.write("echo ran %s\nexit %d\n" % (name, code))
    for name, code in js_files.items():
        with open(os.path.join(tests, name), "w") as f:
            f.write("console.log('ran %s'); process.exit(%d);\n" % (name, code))
    return root, tests


def run(tests):
    p = subprocess.run(
        [os.path.join(tests, "run-tests.sh")],
        capture_output=True, text=True,
    )
    return p.returncode, p.stdout + p.stderr


class TestARedRunNamesTheFiles(unittest.TestCase):

    def test_a_failing_python_file_is_named(self):
        root, tests = build_tree(
            {"test_good.py": 0, "test_bad.py": 1}, {})
        try:
            code, out = run(tests)
            self.assertEqual(code, 1)
            self.assertIn("test_bad.py", out.split("file(s) failed:")[1])
        finally:
            shutil.rmtree(root)

    def test_a_failing_js_file_is_named(self):
        root, tests = build_tree({}, {"test_good.js": 0, "test_bad.js": 1})
        try:
            code, out = run(tests)
            self.assertEqual(code, 1)
            self.assertIn("test_bad.js", out.split("file(s) failed:")[1])
        finally:
            shutil.rmtree(root)

    def test_the_passing_files_are_NOT_named(self):
        """The list is useless if it names everything -- assert the negative."""
        root, tests = build_tree(
            {"test_good.py": 0, "test_bad.py": 1},
            {"test_fine.js": 0})
        try:
            code, out = run(tests)
            summary = out.split("file(s) failed:")[1]
            self.assertIn("test_bad.py", summary)
            self.assertNotIn("test_good.py", summary)
            self.assertNotIn("test_fine.js", summary)
        finally:
            shutil.rmtree(root)

    def test_every_failure_is_listed_not_just_the_first(self):
        """The original bug's shape: stopping at the first is the same blind
        spot, one file smaller."""
        root, tests = build_tree(
            {"test_a.py": 1, "test_b.py": 1}, {"test_c.js": 1})
        try:
            code, out = run(tests)
            summary = out.split("file(s) failed:")[1]
            for name in ("test_a.py", "test_b.py", "test_c.js"):
                self.assertIn(name, summary)
            self.assertIn("3 file(s) failed:", out)
        finally:
            shutil.rmtree(root)

    def test_the_count_and_the_names_agree(self):
        """A count that does not match the list is decoration, and this
        project has already been caught trusting a printed number nobody
        checked."""
        root, tests = build_tree({"test_a.py": 1, "test_ok.py": 0},
                                 {"test_c.js": 1})
        try:
            code, out = run(tests)
            head, summary = out.split("file(s) failed:")
            declared = int(head.strip().split()[-1])
            # REPOINTED 2026-08-21, DISCLOSED, AND STRICTLY STRONGER.
            #
            # This used to take EVERYTHING after "file(s) failed:" as the
            # name list, which was true only because nothing followed it.
            # The runner now replays each failing file's output below the
            # summary -- the fix for a red whose reason did not survive a
            # `tail` -- so an unbounded parse counts the replay as names and
            # this test failed for a reason that has nothing to do with its
            # property. The property is unchanged and still right: the count
            # must match the names. The parse now BOUNDS itself to the name
            # block, which ends at the first blank line, and it additionally
            # asserts every line it counted really is a test filename --
            # something the old version never checked.
            listed = []
            for ln in summary.splitlines():
                if not ln.strip():
                    if listed:
                        break          # end of the name block
                    continue           # the blank right after the colon
                listed.append(ln.strip())
            self.assertEqual(declared, len(listed))
            for name in listed:
                self.assertTrue(name.startswith("test_"), name)
                self.assertTrue(name.endswith((".py", ".js")), name)
        finally:
            shutil.rmtree(root)

    def test_a_green_run_says_nothing_about_failures(self):
        """Silence on success, or the summary becomes noise nobody reads."""
        root, tests = build_tree({"test_a.py": 0}, {"test_b.js": 0})
        try:
            code, out = run(tests)
            self.assertEqual(code, 0)
            self.assertIn("All tests passed.", out)
            self.assertNotIn("file(s) failed:", out)
            self.assertNotIn("TESTS FAILED", out)
        finally:
            shutil.rmtree(root)

    def test_a_red_run_still_exits_1(self):
        """The gate is the exit code; the names are a courtesy on top of it.
        Losing the exit code to gain a nicer message would be a real
        regression, so it is pinned separately."""
        root, tests = build_tree({"test_bad.py": 1}, {})
        try:
            code, _ = run(tests)
            self.assertEqual(code, 1)
        finally:
            shutil.rmtree(root)

    def test_a_failure_does_not_stop_the_remaining_files(self):
        """A run that aborts on the first red tells you less, not more."""
        root, tests = build_tree({"test_a.py": 1, "test_z.py": 0}, {})
        try:
            code, out = run(tests)
            self.assertIn("ran test_z.py", out)
        finally:
            shutil.rmtree(root)



class TestARedRunKEEPSItsOutput(unittest.TestCase):
    """Naming the file was only half the job.

    Serge carded this on 2026-08-14 after a red arrived twice in one day with
    its output gone -- and it happened AGAIN on 2026-08-21, costing a manual
    re-run per failing file. The runner was never silent; the problem is that
    40 files of output scroll, so the only sane way to read this script is
    through `tail`, and a tail cuts exactly the part that matters.

    So the reason must survive a tail: each file's output is tee'd to its own
    log, and a red replays the tail of every failing file AFTER the summary.
    These run the REAL script, for the reason the module docstring gives.
    """

    def _run_with_reason(self, py=None, js=None):
        py = py or {}
        js = js or {}
        root, tests = build_tree(py, js)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return run(tests)

    def test_a_failing_python_test_still_exits_1(self):
        """THE SAFETY PROPERTY, and it is the one a careless tee destroys.

        `cmd | tee` reports TEE's exit code, not the test's, unless pipefail
        is set. Without this the whole suite would report success forever --
        strictly worse than the problem being fixed.
        """
        code, _out = self._run_with_reason(py={"test_bad.py": 1})
        self.assertEqual(code, 1)

    def test_a_failing_js_test_still_exits_1(self):
        code, _out = self._run_with_reason(js={"test_bad.js": 1})
        self.assertEqual(code, 1)

    def test_an_all_green_run_still_exits_0(self):
        code, _out = self._run_with_reason(
            py={"test_ok.py": 0}, js={"test_ok.js": 0})
        self.assertEqual(code, 0)

    def test_THE_REASON_SURVIVES_A_TAIL(self):
        """The whole point. The failing file's own output must appear in the
        LAST lines of the run, after the summary -- because that is what an
        operator's `tail` keeps."""
        # THE FILES THAT RUN AFTER IT ARE THE POINT, and my own injection
        # round is what exposed their absence. With the failing file last,
        # its reason is the last thing printed anyway, so this test passed
        # WITH THE REPLAY DELETED -- vacuous, in the test carrying the
        # headline property. The real suite is 40 files; a failure in the
        # middle is buried by everything after it. So: noisy files that sort
        # AFTER the failing one, and enough of them to push it out of any
        # tail an operator would take.
        root, tests = build_tree({}, {})
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with open(os.path.join(tests, "test_aaa_noisy.py"), "w") as f:
            for i in range(200):
                f.write("echo noise %d\n" % i)
            f.write("echo THE-DISTINCTIVE-REASON\n")
            f.write("exit 1\n")
        for later in ("test_mmm_after.py", "test_zzz_after.py"):
            with open(os.path.join(tests, later), "w") as f:
                for i in range(120):
                    f.write("echo later noise %d\n" % i)
                f.write("exit 0\n")
        code, out = run(tests)
        self.assertEqual(code, 1)
        tail = "\n".join(out.splitlines()[-25:])
        self.assertIn("THE-DISTINCTIVE-REASON", tail,
                      "the failing file's reason did not survive a tail")

    def test_the_replay_comes_AFTER_the_summary(self):
        """Ordering is the property, not merely presence. Before the summary
        it scrolls away with everything else."""
        code, out = self._run_with_reason(py={"test_bad.py": 1})
        self.assertEqual(code, 1)
        self.assertLess(out.index("file(s) failed"), out.index("what actually failed"))

    def test_it_names_where_the_FULL_log_is(self):
        """The replay is bounded so one noisy failure cannot bury the others,
        so the untruncated log has to be findable."""
        code, out = self._run_with_reason(py={"test_bad.py": 1})
        self.assertIn("full log:", out)
        self.assertIn("all logs for this run:", out)

    def test_a_log_is_written_for_EVERY_file_not_only_the_failures(self):
        """A green run that later turns red is diagnosed from the green
        run's logs; keeping only failures throws that away."""
        root, tests = build_tree({"test_ok.py": 0, "test_bad.py": 1},
                                 {"test_ok.js": 0})
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        code, out = run(tests)
        logdir = out.split("all logs for this run:")[1].strip().splitlines()[0]
        self.addCleanup(shutil.rmtree, logdir, ignore_errors=True)
        for name in ("test_ok.py.log", "test_bad.py.log", "test_ok.js.log"):
            self.assertTrue(os.path.isfile(os.path.join(logdir, name)), name)

    def test_the_logs_are_BOUNDED_so_the_gate_cannot_eat_the_disk(self):
        """This machine filled its volume on 2026-08-15 and lost an
        afternoon to it. A gate that quietly accumulates output in TMPDIR is
        the same failure on a slower fuse -- and a gate that eats the disk is
        a gate that gets switched off.
        """
        root, tests = build_tree({"test_ok.py": 0}, {})
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        env = dict(os.environ, TMPDIR=tmp)
        for _ in range(26):
            subprocess.run([os.path.join(tests, "run-tests.sh")],
                           capture_output=True, text=True, env=env)
        kept = os.listdir(os.path.join(tmp, "jarvis-test-logs"))
        self.assertLessEqual(len(kept), 22,
                             f"log dirs are unbounded: {len(kept)} kept")
        self.assertGreaterEqual(len(kept), 5,
                                "pruning ate everything, including this run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
