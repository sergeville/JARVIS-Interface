#!/usr/bin/env bash
# restartJarvis -- thin wrapper. The real script is now jarvis.sh.
#
# Superseded 2026-08-04: stopJarvis.sh and restartJarvis.sh were merged into
# one verb-based script (`./jarvis.sh status|start|stop|restart`). This name is
# kept because Serge's muscle memory and several vault notes point at it.
#
# The bug this merge fixed: the old restartJarvis.sh handed the stop to
# stopJarvis.sh and then swallowed its exit code with `|| true`. Once the
# ancestry refusal landed, that became a live trap -- a restart run from
# inside the Jarvis stack would be refused, ignore the refusal, and launch a
# second server on top of the live one. That is the orphaned-pair incident,
# rebuilt. `jarvis.sh restart` now aborts unless the stop verifies clean.
#
#   ./restartJarvis.sh [--dry-run] [--help]
exec "$(dirname "$0")/jarvis.sh" restart "$@"
