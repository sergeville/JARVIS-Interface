#!/usr/bin/env bash
# stopJarvis -- thin wrapper. The real script is now jarvis.sh.
#
# Superseded 2026-08-04: stopJarvis.sh and restartJarvis.sh were merged into
# one verb-based script (`./jarvis.sh status|start|stop|restart`) so that the
# stack has a single source of truth for how it is stopped and started. This
# name is kept because Serge's muscle memory and several vault notes point at
# it. All flags pass straight through.
#
#   ./stopJarvis.sh [--keep-speech] [--dry-run] [--help]
exec "$(dirname "$0")/jarvis.sh" stop "$@"
