#!/usr/bin/env bash
# Run every test in Jarvis Visual/tests/.
#
# Serge's standing rule (2026-08-05): every code change gets a test, and the
# tests passing is the gate before a change is accepted. Run this before
# saying anything works.
#
# Uses the voice-line venv, which is where the server's own dependencies
# (aiohttp) live -- the tests import voice-web-server.py for real rather than
# copying its logic, so they can never drift from the code they guard.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(cd "$HERE/../.." && pwd)/voice-line/.venv/bin/python3"

[ -x "$PY" ] || { echo "venv python not found: $PY" >&2; exit 1; }

# ONE SUITE AT A TIME ON THIS MACHINE (Serge's go, 2026-08-09).
#
# The red that started this: `test_see_page` timed out waiting on headless
# Chrome while another session was running its own suite. It passed alone and
# the whole suite was green on a clean re-run -- so the failure said nothing
# about the change under test, which is the worst thing a gate can do. It is
# not the same as the 2026-08-08 flake (that one was a note read race, fixed
# in the test); this one is CONTENTION, and no amount of care inside a test
# can fix two processes wanting one browser.
#
# So a second run WAITS rather than racing. Deliberate choices:
#   * It waits, it does not refuse. Refusing would mean a session that did
#     nothing wrong cannot prove its own change, and the gate is the one
#     thing that must always be available.
#   * The wait is BOUNDED. A lock held by a dead run must not block the gate
#     forever -- if it cannot be taken in LOCK_WAIT seconds, we say who holds
#     it and run anyway, because a suite that refuses to run is worse than a
#     suite that risks one flaky file.
#   * The lock records the holder's PID and start time, so the message names
#     something Serge can look up rather than "somebody else".
#   * It is released on ANY exit -- pass, fail, or interrupt -- via trap.
#   * A NESTED RUN INHERITS THE LOCK INSTEAD OF WAITING FOR ITS OWN PARENT.
#     Found by running it, not by reading it: `test_runner.py` invokes this
#     very script, so the child sat waiting out the full budget for a lock
#     its own parent was holding -- the suite went from two minutes to ten
#     and the gate looked hung. A lock that deadlocks the thing it protects
#     is worse than the contention it was written for.
LOCK="${TMPDIR:-/tmp}/jarvis-visual-tests.lock"
LOCK_WAIT="${LOCK_WAIT:-600}"
have_lock=0
if [ "${JARVIS_TESTS_LOCKED:-}" = "1" ]; then
  # A run inside a run. The outer one already serialised us.
  LOCK_WAIT=0
  skip_lock=1
else
  skip_lock=0
fi
export JARVIS_TESTS_LOCKED=1

lock_holder() { cat "$LOCK/holder" 2>/dev/null || echo "unknown"; }

release_lock() {
  [ "$have_lock" = "1" ] || return 0
  rm -f "$LOCK/holder" 2>/dev/null || true
  rmdir "$LOCK" 2>/dev/null || true
}
trap release_lock EXIT INT TERM

# mkdir is the atomic primitive here: it either creates the directory or it
# does not, with no window between checking and taking. A file test followed
# by a touch is the classic version of this that races.
waited=0
while [ "$skip_lock" = "0" ] && ! mkdir "$LOCK" 2>/dev/null; do
  # A lock whose owning process is gone is stale -- take it rather than
  # waiting out the full budget for a run that ended in a kill.
  holder_pid=$(cut -d' ' -f1 "$LOCK/holder" 2>/dev/null || echo "")
  if [ -n "$holder_pid" ] && ! kill -0 "$holder_pid" 2>/dev/null; then
    echo "clearing a stale test lock from pid $holder_pid" >&2
    rm -f "$LOCK/holder" 2>/dev/null || true
    rmdir "$LOCK" 2>/dev/null || true
    continue
  fi
  if [ "$waited" -ge "$LOCK_WAIT" ]; then
    echo "another suite has been running for over ${LOCK_WAIT}s ($(lock_holder))." >&2
    echo "running anyway -- headless-Chrome tests may be flaky." >&2
    break
  fi
  [ "$waited" = "0" ] && printf 'another suite is running (%s) -- waiting' "$(lock_holder)" >&2
  printf '.' >&2
  sleep 2
  waited=$((waited + 2))
done
if [ "$skip_lock" = "0" ] && [ -d "$LOCK" ] && [ ! -f "$LOCK/holder" ]; then
  have_lock=1
  printf '%s %s\n' "$$" "$(date '+%H:%M:%S')" >"$LOCK/holder"
  [ "$waited" != "0" ] && echo "" >&2
fi

# WHICH FILES FAILED, not just THAT something did (2026-08-08, Serge's go).
# The suite went red once and green four times on an unchanged tree, and the
# red run was undiagnosable: 43 files scroll past and the only summary is one
# line saying the change is not accepted. The failing file's own output IS in
# the log, but you have to have kept the whole log to find it -- and a tail,
# which is what anyone actually runs, cuts exactly the part that matters.
# Collecting the names costs nothing and makes the next red name itself.
#
# AND THE RUNNER KEEPS THE OUTPUT ITSELF (2026-08-14, carded; built
# 2026-08-21). Naming the file was half the job. Twice in one day a red
# arrived and its output was gone -- not because the runner did not print it,
# but because the operator piped this script through `tail` to see the
# summary, which is the only sane way to read 40 files of output, and that
# pipe throws away the one part that matters. It happened again on 2026-08-21
# and cost a manual re-run per failing file.
#
# THE FIX IS NOT "PRINT MORE". A red already prints everything; the problem is
# that it scrolls. So each file's output is TEE'd to its own log, and a red
# replays the tail of every failing file AT THE BOTTOM, after the summary --
# where a `tail` can still see it. Capture stops depending on remembering.
#
# TWO MECHANISMS GUARD THE EXIT CODE, AND EITHER ONE ALONE IS ENOUGH --
# said plainly because the first version of this comment claimed `pipefail`
# was load-bearing, and an injection round proved that false the same hour.
# `run_one` returns `${PIPESTATUS[0]}`, which is the TEST's status by
# definition and does not depend on `pipefail`; and `pipefail` (set at the
# top) makes a bare `$?` after the pipeline the test's status too. Removing
# either leaves the gate correct; removing BOTH makes every test appear to
# pass, which is strictly worse than the problem this block fixes. Keep both,
# and do not let a future tidy-up delete one believing the other is
# decoration -- they are belt and braces, and this comment is the record that
# neither is the whole answer.
LOGDIR="${TMPDIR:-/tmp}/jarvis-test-logs/$(date '+%Y%m%d-%H%M%S')-$$"
mkdir -p "$LOGDIR"

# BOUNDED, because an unbounded pile of logs in TMPDIR is how this machine
# filled its disk on 2026-08-15. Keep the most recent runs and drop the rest;
# a gate that slowly eats the volume is a gate that gets switched off.
ls -1dt "${TMPDIR:-/tmp}"/jarvis-test-logs/*/ 2>/dev/null | tail -n +21 | while read -r old_dir; do
  rm -rf "$old_dir" 2>/dev/null || true
done

fail=0
failed=()
run_one() {
  local name="$1"; shift
  echo "=== $name"
  "$@" 2>&1 | tee "$LOGDIR/$name.log"
  return "${PIPESTATUS[0]}"
}

for t in "$HERE"/test_*.py; do
  [ -e "$t" ] || continue
  run_one "$(basename "$t")" "$PY" "$t" || { fail=1; failed+=("$(basename "$t")"); }
done

# Page tests (2026-08-05). jarvis.html is code too -- the compact task list and
# the events strip are real logic, and "node --check" only proves it parses.
# These extract the real functions from the page and run them against a DOM
# stub, so they cannot drift from what ships.
for t in "$HERE"/test_*.js; do
  [ -e "$t" ] || continue
  run_one "$(basename "$t")" node "$t" || { fail=1; failed+=("$(basename "$t")"); }
done

if [ "$fail" -ne 0 ]; then
  echo
  # The count and the names, both. A count alone is the same decoration as
  # the printed file total this project has already been caught trusting;
  # the names are the thing you act on.
  echo "TESTS FAILED -- the change is not accepted." >&2
  echo "${#failed[@]} file(s) failed:" >&2
  for f in "${failed[@]}"; do echo "  $f" >&2; done
  # THE REPLAY, and it goes LAST on purpose: this is the part a `tail` keeps.
  # Bounded per file so one catastrophically noisy failure cannot bury the
  # others -- the full output is in the log named above each block.
  echo >&2
  echo "---- what actually failed ----" >&2
  for f in "${failed[@]}"; do
    echo >&2
    echo "---- $f (full log: $LOGDIR/$f.log)" >&2
    tail -n 40 "$LOGDIR/$f.log" >&2 2>/dev/null || echo "  (no log captured)" >&2
  done
  echo >&2
  echo "all logs for this run: $LOGDIR" >&2
  exit 1
fi
echo
echo "All tests passed."
