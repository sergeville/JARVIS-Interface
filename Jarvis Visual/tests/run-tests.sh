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
fail=0
failed=()
for t in "$HERE"/test_*.py; do
  [ -e "$t" ] || continue
  echo "=== $(basename "$t")"
  "$PY" "$t" || { fail=1; failed+=("$(basename "$t")"); }
done

# Page tests (2026-08-05). jarvis.html is code too -- the compact task list and
# the events strip are real logic, and "node --check" only proves it parses.
# These extract the real functions from the page and run them against a DOM
# stub, so they cannot drift from what ships.
for t in "$HERE"/test_*.js; do
  [ -e "$t" ] || continue
  echo "=== $(basename "$t")"
  node "$t" || { fail=1; failed+=("$(basename "$t")"); }
done

if [ "$fail" -ne 0 ]; then
  echo
  # The count and the names, both. A count alone is the same decoration as
  # the printed file total this project has already been caught trusting;
  # the names are the thing you act on.
  echo "TESTS FAILED -- the change is not accepted." >&2
  echo "${#failed[@]} file(s) failed:" >&2
  for f in "${failed[@]}"; do echo "  $f" >&2; done
  exit 1
fi
echo
echo "All tests passed."
