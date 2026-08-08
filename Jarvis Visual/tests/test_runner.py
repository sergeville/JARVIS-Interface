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
            listed = [ln.strip() for ln in summary.strip().splitlines()
                      if ln.strip()]
            self.assertEqual(declared, len(listed))
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
