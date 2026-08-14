#!/usr/bin/env bash
# The Discord line -- start / stop / status / logs.
#
# Runs bot.py on the voice-line venv (the claude_agent_sdk already lives
# there; a notification bridge does not earn a second venv). The bot is
# a background daemon: nohup, log to bot.log, pid in .bot.pid.
#
# The never-stop-yourself rule applies here exactly as it does to the
# voice stack: a shell whose ancestor IS the bot (i.e., Jarvis asked from
# inside Discord) must refuse to stop it and say what it left alone.
# Stopping the line belongs to a human terminal.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/../voice-line/.venv/bin/python3"
PIDFILE="$HERE/.bot.pid"
LOG="$HERE/bot.log"

alive() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

refuse_if_inside() {
  # Walk this shell's own ancestry; if the bot is up the chain, this
  # command was issued from inside the Discord line and must not fire.
  [ -f "$PIDFILE" ] || return 0
  local bot p
  bot="$(cat "$PIDFILE")"
  p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    if [ "$p" = "$bot" ]; then
      echo "REFUSED: this command is running inside the Discord line (pid $bot)." >&2
      echo "Left alone: the bot, its brain, and this shell. Stop it from your own terminal:" >&2
      echo "  ./discord-line/run.sh stop" >&2
      exit 1
    fi
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
}

case "${1:-}" in
  start)
    if alive; then
      echo "already running (pid $(cat "$PIDFILE"))"
      exit 0
    fi
    [ -x "$PY" ] || { echo "venv python not found: $PY" >&2; exit 1; }
    # Preflight through the module itself so a missing token or a
    # placeholder config fails HERE, with its own instruction, instead
    # of dying silently in the log.
    (cd "$HERE" && "$PY" -c "import discord_api; discord_api.load_token(); discord_api.load_config()") || exit 1
    nohup "$PY" "$HERE/bot.py" >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1
    if alive; then
      echo "started (pid $(cat "$PIDFILE")) -- logs: ./discord-line/run.sh logs"
    else
      echo "FAILED to start -- last log lines:" >&2
      tail -n 20 "$LOG" >&2
      exit 1
    fi
    ;;
  stop)
    refuse_if_inside
    if ! alive; then
      echo "not running"
      exit 0
    fi
    pid="$(cat "$PIDFILE")"
    kill "$pid" 2>/dev/null
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "did not stop on TERM; still running (pid $pid)" >&2
      exit 1
    fi
    rm -f "$PIDFILE"
    echo "stopped"
    ;;
  status)
    if alive; then
      echo "running (pid $(cat "$PIDFILE"))"
    else
      echo "not running"
      exit 1
    fi
    ;;
  logs)
    tail -n 50 -f "$LOG"
    ;;
  *)
    echo "usage: $0 start|stop|status|logs" >&2
    exit 2
    ;;
esac
