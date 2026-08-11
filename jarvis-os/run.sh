#!/usr/bin/env bash
# Serve the JARVIS OS skeleton for a look.
#
# Static files only, on its own port -- this is NOT part of the voice stack,
# it starts nothing else and it kills nothing, ever. ES modules cannot load
# over file:// in Chrome, which is the whole reason this script exists.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PORT="${1:-8090}"
echo "JARVIS OS skeleton at http://127.0.0.1:${PORT}/  (Ctrl-C stops this server and nothing else)"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
