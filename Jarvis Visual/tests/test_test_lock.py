#!/usr/bin/env python3
"""ONE SUITE AT A TIME — the gate must not be red for someone else's reason.

The red that started this (2026-08-09): `test_see_page` timed out waiting on
headless Chrome while another session ran its own suite.  It passed alone and
the whole suite was green on a clean re-run, so the failure said nothing at
all about the change under test.  That is the worst thing a gate can do — it
spends a session's afternoon on a defect that was never there.

What is tested here is the LOCK ITSELF, cut out of run-tests.sh and run with a
harmless body, because running the real suite twice to test it would take
minutes and would itself be the contention it is trying to prevent.

The properties, and each one is a decision that could have gone the other way:

  1. Two runs SERIALISE — the second waits, it does not run alongside.
  2. The second run WAITS, it does not refuse.  A session that did nothing
     wrong must still be able to prove its own change; the gate is the one
     thing that must always be available.
  3. The wait is BOUNDED, and the fallback is to RUN, not to die.  A lock held
     by a dead run must never block the gate forever.
  4. A lock whose owner is gone is cleared immediately, not waited out.
  5. The lock is released on ANY exit — pass, fail, or interrupt.
"""

import os
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

# ⚠ THE SUITE THAT RUNS THIS FILE HAS ALREADY TAKEN THE LOCK, and it tells its
# children so via JARVIS_TESTS_LOCKED -- which is exactly the inheritance being
# tested. Left alone, every "fresh session" in this file would inherit it and
# skip locking, and five tests failed inside the suite while passing standalone.
# So the variable is cleared here: each test decides for itself whether its
# subprocess is a fresh run or a nested one.
os.environ.pop("JARVIS_TESTS_LOCKED", None)

SH = Path(__file__).resolve().parent.parent / "tests" / "run-tests.sh"
SRC = SH.read_text()

START = "# ONE SUITE AT A TIME ON THIS MACHINE"
END = '  [ "$waited" != "0" ] && echo "" >&2\nfi'


def block() -> str:
    i = SRC.find(START)
    assert i != -1, "the test lock is gone from run-tests.sh"
    j = SRC.find(END, i)
    assert j != -1, "the test lock block never ends"
    return SRC[i:j + len(END)]


# The real script's budget is ten minutes. These tests use a SHORT one by
# default, deliberately: with the production value, a fault that breaks the
# release path turns this file into a ten-minute hang instead of a red line.
# A test suite that hangs on a defect is barely better than one that misses
# it -- the person running it learns nothing and waits for it anyway.
TEST_WAIT = "20"


def script(body: str, lock_dir: str, wait: str = TEST_WAIT) -> str:
    """The real lock wrapped around a harmless body."""
    return textwrap.dedent(f"""
        set -uo pipefail
        TMPDIR="{lock_dir}"
        LOCK_WAIT="{wait}"
    """) + block() + "\n" + body


def run(body: str, lock_dir: str, wait: str = TEST_WAIT, **kw):
    return subprocess.run(["bash", "-c", script(body, lock_dir, wait)],
                          capture_output=True, text=True, **kw)


class TheTestLock(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lock = os.path.join(self.tmp, "jarvis-visual-tests.lock")

    def test_a_lone_run_takes_the_lock_and_gives_it_back(self):
        r = run('echo BODY-RAN', self.tmp)
        self.assertIn("BODY-RAN", r.stdout)
        self.assertNotIn("waiting", r.stderr)
        self.assertFalse(os.path.exists(self.lock),
                         "the lock outlived the run that took it")

    def test_TWO_RUNS_SERIALISE_the_second_does_not_run_alongside(self):
        # The first holds the lock for a beat; the second must not start its
        # body until the first has finished.
        first = subprocess.Popen(
            ["bash", "-c", script('echo FIRST-START; sleep 3; echo FIRST-END',
                                  self.tmp)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)                       # let the first take it
        t0 = time.time()
        second = run('echo SECOND-RAN', self.tmp)
        waited = time.time() - t0
        first.wait(timeout=20)
        self.assertIn("SECOND-RAN", second.stdout)
        self.assertGreater(waited, 1.0,
                           "the second run did not wait for the first")
        self.assertIn("another suite is running", second.stderr)

    def test_the_second_run_WAITS_rather_than_refusing(self):
        first = subprocess.Popen(
            ["bash", "-c", script('sleep 2', self.tmp)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.5)
        second = run('echo RAN', self.tmp)
        first.wait(timeout=20)
        self.assertEqual(second.returncode, 0,
                         "a waiting run exited non-zero — the gate refused a "
                         "session that had done nothing wrong")
        self.assertIn("RAN", second.stdout)

    def test_the_wait_is_BOUNDED_and_the_fallback_is_to_RUN(self):
        # A lock held by a LIVE process that simply never lets go. After the
        # budget the run must proceed, loudly, rather than hang forever.
        holder = subprocess.Popen(["sleep", "30"])
        try:
            os.makedirs(self.lock)
            Path(self.lock, "holder").write_text(f"{holder.pid} 12:00:00\n")
            t0 = time.time()
            r = run('echo RAN-ANYWAY', self.tmp, wait="4")
            took = time.time() - t0
            self.assertIn("RAN-ANYWAY", r.stdout)
            self.assertIn("running anyway", r.stderr)
            self.assertIn("may be flaky", r.stderr)
            self.assertLess(took, 20, "the bounded wait was not bounded")
            self.assertGreaterEqual(took, 3, "it did not wait at all")
        finally:
            holder.kill()

    def test_a_lock_whose_OWNER_IS_GONE_is_cleared_at_once(self):
        # The case that would otherwise cost a session the full budget for
        # nothing: a run that was killed and never released.
        dead = subprocess.Popen(["true"])
        dead.wait()
        os.makedirs(self.lock)
        Path(self.lock, "holder").write_text(f"{dead.pid} 12:00:00\n")
        t0 = time.time()
        r = run('echo RAN', self.tmp, wait="20")
        took = time.time() - t0
        self.assertIn("RAN", r.stdout)
        self.assertIn("stale test lock", r.stderr)
        self.assertLess(took, 5, "a dead holder's lock was waited out")

    def test_the_lock_is_released_even_when_the_suite_FAILS(self):
        r = run('echo NOPE; exit 1', self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(self.lock),
                         "a failing suite kept the lock — the next run would wait for nothing")

    def test_the_holder_names_a_PID_Serge_can_look_up(self):
        first = subprocess.Popen(
            ["bash", "-c", script('sleep 3', self.tmp)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        holder = Path(self.lock, "holder").read_text().strip()
        first.wait(timeout=20)
        pid = holder.split()[0]
        self.assertTrue(pid.isdigit(), "the lock does not record a pid: " + holder)
        self.assertRegex(holder, r"\d+ \d\d:\d\d:\d\d",
                         "the lock does not record when it was taken")

    def test_it_takes_the_lock_ATOMICALLY(self):
        # mkdir either creates or fails, with no window between checking and
        # taking. A file test followed by a touch is the racing version, and
        # a lock with a race in it is decoration.
        b = block()
        self.assertIn("mkdir \"$LOCK\"", b,
                      "the lock is no longer taken with mkdir — check for a race")
        self.assertNotIn("[ -d \"$LOCK\" ] && sleep", b)

    def test_A_NESTED_RUN_INHERITS_THE_LOCK_instead_of_deadlocking(self):
        # FOUND BY RUNNING IT, not by reading it. `test_runner.py` invokes
        # run-tests.sh, so with a naive lock the child waited out the full
        # ten-minute budget for a lock its own PARENT was holding: the suite
        # went from two minutes to ten and looked hung. A lock that
        # deadlocks the thing it protects is worse than the contention it
        # was written to prevent.
        env = {**os.environ, "JARVIS_TESTS_LOCKED": "1"}
        t0 = time.time()
        r = subprocess.run(["bash", "-c", script('echo NESTED-RAN', self.tmp)],
                           capture_output=True, text=True, env=env)
        took = time.time() - t0
        self.assertIn("NESTED-RAN", r.stdout)
        self.assertLess(took, 3, "a nested run waited for its own parent")
        self.assertNotIn("another suite is running", r.stderr)

    def test_the_lock_is_ANNOUNCED_to_children_so_they_can_inherit_it(self):
        b = block()
        self.assertIn("export JARVIS_TESTS_LOCKED=1", b,
                      "a nested run has no way to know it is already serialised")

    def test_a_nested_run_does_not_RELEASE_its_parents_lock(self):
        # The other half, and the one that would be silent: if the child
        # cleaned up on exit it would free the lock while the parent was
        # still running, and a third session could walk straight in.
        first = subprocess.Popen(
            ["bash", "-c", script('sleep 3', self.tmp)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        env = {**os.environ, "JARVIS_TESTS_LOCKED": "1"}
        subprocess.run(["bash", "-c", script('true', self.tmp)],
                       capture_output=True, text=True, env=env)
        still_held = os.path.exists(self.lock)
        first.wait(timeout=20)
        self.assertTrue(still_held,
                        "a nested run released the lock its parent was holding")

    def test_it_is_released_on_INTERRUPT_too(self):
        b = block()
        self.assertRegex(b, r"trap release_lock EXIT INT TERM",
                         "an interrupted suite would leave its lock behind")


if __name__ == "__main__":
    unittest.main(verbosity=2)
