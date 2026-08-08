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
