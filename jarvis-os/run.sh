#!/usr/bin/env bash
# Serve the JARVIS OS skeleton for a look.
#
# Static files plus ONE read-only proxied feed, on its own port -- this is
# NOT part of the voice stack, it starts nothing else and it kills nothing,
# ever. ES modules cannot load over file:// in Chrome, which is why a server
# exists at all; the proxy exists because the page reads the voice stack's
# live signals feed and a browser refuses that read cross-origin. The
# reasoning, and the option deliberately not taken, are in serve.py's
# docstring.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PORT="${1:-8090}"
exec python3 serve.py "$PORT"
