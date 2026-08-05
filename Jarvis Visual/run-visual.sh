#!/usr/bin/env bash
# JARVIS browser voice + visual launcher: starts the voice-web server
# if it's not already up, then opens the ring in the default browser.
# The server runs inside the voice-line project's environment.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
VL="$HOME/Documents/Jarvis/voice-line"
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
