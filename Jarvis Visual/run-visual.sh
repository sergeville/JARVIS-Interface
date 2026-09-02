#!/usr/bin/env bash
# JARVIS browser voice + visual launcher: starts the voice-web server
# if it's not already up, then opens the ring in the default browser.
# The server runs inside the voice-line project's environment.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
# The voice line is this folder's sibling. Derived, not hard-coded: a home
# path went stale when the project moved (2026-09-02) and nothing said so.
# And it FAILS OUT LOUD when the sibling is missing: `cd ""` is a no-op in
# bash, so an empty VL would start the server in whatever folder this was
# launched from and the only symptom would be "did not come up".
VL="$(cd "$HERE/../voice-line" 2>/dev/null && pwd)" || {
  echo "voice-line folder not found at $HERE/../voice-line -- it must sit beside this folder" >&2
  exit 1
}
URL="http://127.0.0.1:8765/"

if ! curl -s -m 2 -o /dev/null "$URL"; then
  (cd "$VL" && nohup uv run python "$HERE/voice-web-server.py" \
    >>"$HERE/visual-server.log" 2>&1 &)
  for _ in $(seq 1 40); do
    curl -s -m 1 -o /dev/null "$URL" && break
    sleep 0.5
  done
fi

if ! curl -s -m 2 -o /dev/null "$URL"; then
  echo "voice-web server did not come up -- check $HERE/visual-server.log" >&2
  exit 1
fi

open "$URL"
