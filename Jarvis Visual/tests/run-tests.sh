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
PY="/Users/mike/Documents/Jarvis/voice-line/.venv/bin/python3"

[ -x "$PY" ] || { echo "venv python not found: $PY" >&2; exit 1; }

fail=0
for t in "$HERE"/test_*.py; do
  [ -e "$t" ] || continue
  echo "=== $(basename "$t")"
  "$PY" "$t" || fail=1
done

# Page tests (2026-08-05). jarvis.html is code too -- the compact task list and
# the events strip are real logic, and "node --check" only proves it parses.
# These extract the real functions from the page and run them against a DOM
# stub, so they cannot drift from what ships.
for t in "$HERE"/test_*.js; do
  [ -e "$t" ] || continue
  echo "=== $(basename "$t")"
  node "$t" || fail=1
done

if [ "$fail" -ne 0 ]; then
  echo
  echo "TESTS FAILED -- the change is not accepted." >&2
  exit 1
fi
echo
echo "All tests passed."
