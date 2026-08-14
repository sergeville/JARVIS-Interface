#!/usr/bin/env bash
# jarvis -- one command for the whole Jarvis stack.
#
#   ./jarvis.sh status     what is up, what is down. Touches nothing.
#   ./jarvis.sh start      start whatever is missing. Safe to run twice.
#   ./jarvis.sh stop       stop the stack, and prove it stopped.
#   ./jarvis.sh restart    stop, verify the stop, then start.
#
# Flags:
#   --keep-speech   leave whisper + Kokoro running on stop (they are slow
#                   to start; keep them if Jarvis is coming back shortly)
#   --dry-run       stop/restart only: list what would be stopped, kill nothing
#   --help          this text
#
# Exit codes:  0 success   1 something failed   2 bad usage   3 refused
#
# ---------------------------------------------------------------------------
# THE STACK (four things, in stop order)
#
#   browser Jarvis   the `uv` wrapper + voice-web-server.py, holds port 8765
#   brain            the Claude SDK subprocess the server spawns
#   terminal line    voice-line/main.py, only when Serge is running it
#   speech servers   whisper-server (2022) and Kokoro (8880)
#
# ---------------------------------------------------------------------------
# THE THREE LESSONS THIS SCRIPT EXISTS TO ENCODE
#
# 1. SIGTERM does not stop voice-web-server or its `uv` wrapper. They drop
#    port 8765 the instant they are signalled, so a port check reports "down"
#    while both are still alive and sleeping -- a false all-clear that left an
#    orphaned server pair running (2026-08-03). They need KILL. Everything
#    else in the stack does exit on a plain TERM. So: TERM, wait, force what
#    survives, then verify by port AND by HTTP rather than assuming.
#
# 2. pgrep will not match processes in the tree it is called from. Run from
#    inside the stack it returns nothing, every group prints a confident
#    "not running", and the stop kills nothing (2026-08-04). So process
#    matching goes through `ps -A -o pid=,command=`, never pgrep.
#
# 3. Jarvis never stops himself, or his parents. (Serge, 2026-08-04, locked:
#    "leave the stop for me to use the terminal, you cannot kill yourself or
#    stop yourself at all... or even your parents.") The brain runs as a
#    descendant of voice-web-server.py, so the server is Jarvis's own parent.
#    Every killing verb runs a PRE-FLIGHT ancestry check and refuses -- having
#    killed nothing -- if any target is in this script's own ancestor chain.
#
#    A detached killer used to work around this: write the un-killable PIDs to
#    a temp script, nohup it, let it kill them ~2s after this script exited,
#    and log the verdict to a file since nobody was left on the line to read
#    it. Serge rejected it -- a detached killer is still Jarvis stopping
#    Jarvis, laundered through a second process. DO NOT REINTRODUCE IT in any
#    form: nohup, at, launchd, trap-on-EXIT, or a background subshell.
#
# It never touches Claude Code terminal sessions. The brain is matched on the
# SDK's bundled path inside voice-line/.venv, which no terminal session shares.
set -u

# Located from this script's own path, so a clone needs no editing. The
# wrappers exec us as "$(dirname "$0")/jarvis.sh", so $0 is always a real
# path to this file however it was invoked. Note the process patterns below
# (P_SERVER, P_KOKORO, ...) are relative fragments and deliberately do NOT
# derive from these -- matching `ps` output must not depend on where the
# project lives.
JV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VL="$(cd "$JV/.." && pwd)/voice-line"
LOG="$JV/visual-server.log"
LOGS="$VL/logs"
SELF="$JV/jarvis.sh"

VERB=""
KEEP_SPEECH=0
DRY_RUN=0

# Full text (the header comment above) only on --help, on stdout.
help_full() { awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; }

# The one-screen usage, on stderr, for every misuse. A verb is REQUIRED:
# running this script bare must never do anything, least of all guess.
usage() {
  {
    [ -n "${1:-}" ] && echo "$(basename "$0"): $1" && echo ""
    echo "usage: $(basename "$0") <status|sessions|start|stop|restart> [--keep-speech] [--dry-run]"
    echo ""
    echo "  status    what is up, what is down. Touches nothing."
    echo "  sessions  which Jarvis sessions are actually running. Touches nothing."
    echo "  start     start whatever is missing. Safe to run twice."
    echo "  stop      stop the stack, and prove it stopped."
    echo "  restart   stop, verify the stop, then start."
    echo ""
    echo "try '$(basename "$0") --help' for the full description."
  } >&2
  exit 2
}

for arg in "$@"; do
  case "$arg" in
    status|sessions|start|stop|restart)
      [ -n "$VERB" ] && usage "two verbs given: '$VERB' and '$arg' -- pick one"
      VERB="$arg" ;;
    -k|--keep-speech) KEEP_SPEECH=1 ;;
    -n|--dry-run)     DRY_RUN=1 ;;
    -h|--help)        help_full; exit 0 ;;
    *) usage "unknown argument: '$arg'" ;;
  esac
done
[ -z "$VERB" ] && usage "no verb given"

# --------------------------------------------------------------------------
# finding things
# --------------------------------------------------------------------------

# This script's own PID plus every ancestor, newline-separated.
own_chain() {
  local p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    echo "$p"
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
}
OWN_CHAIN="|$(own_chain | tr '\n' '|')"
is_own() { case "$OWN_CHAIN" in *"|$1|"*) return 0 ;; *) return 1 ;; esac; }

# All PIDs matching a pattern. Deliberately NOT pgrep -- see lesson 2.
find_pids() {
  ps -A -o pid=,command= 2>/dev/null \
    | grep -F "$1" \
    | grep -v "grep" \
    | grep -v -F "$SELF" \
    | awk '{print $1}' \
    | tr '\n' ' '
}

# Matches that are not our own ancestors.
find_others() {
  local out="" p
  for p in $(find_pids "$1"); do is_own "$p" || out="$out $p"; done
  echo "${out# }"
}

port_free() { ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
alive()     { curl -s -m 2 -o /dev/null "$1"; }
# curl PRINTS 000 itself when nothing is listening, AND exits 7. This used to
# end in `|| echo 000`, so both fired and the function returned "000000" --
# which every caller, comparing against the string "000", read as a live page.
# On 2026-08-04 that locked Serge out: `start` said "already up" and started
# nothing, `stop` failed its own verify after a clean stop, `restart` aborted,
# and `status` printed "answering" next to "8765 free". Take curl's word; it
# already reports the failure. (A check that can only fail closed is no check.)
page_code() {
  local c
  c=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/ 2>/dev/null)
  [ -z "$c" ] && c=000
  echo "$c"
}

P_SERVER="voice-web-server.py"
P_BRAIN="claude_agent_sdk/_bundled/claude"
P_LINE="voice-line/main.py"
P_WHISPER="whisper-server"
P_KOKORO="api.src.main:app"

# Groups this run would stop, in kill order. Server before brain: the
# server's self-heal can rebuild a brain that dies under it, but only while a
# turn is in flight. Kill the server and the brain is orphaned, never replaced.
kill_groups() {
  echo "browser Jarvis|$P_SERVER"
  echo "brain|$P_BRAIN"
  echo "terminal line|$P_LINE"
  if [ "$KEEP_SPEECH" -eq 0 ]; then
    echo "whisper|$P_WHISPER"
    echo "kokoro|$P_KOKORO"
  fi
}

# --------------------------------------------------------------------------
# the ancestry refusal -- lesson 3
#
# Runs BEFORE anything is killed. An earlier version checked per group, as
# each group was reached, so a run from inside the stack killed whisper and
# Kokoro -- nobody's ancestors -- and only then hit the server and refused.
# A half-stopped stack is strictly worse than not trying.
# --------------------------------------------------------------------------
# Every Claude Code session in our own ancestor chain, if any. A session that
# LAUNCHED the stack is the stack's parent, not its child, so the ancestor test
# below never fires there -- and a stop from that session would cheerfully kill
# a live browser Jarvis mid-conversation. Serge's rule is that Jarvis does not
# stop Jarvis; this reads it by its spirit. A stop from Serge's own Terminal has
# no claude in its chain and is unaffected.
own_claude() {
  local p out=""
  for p in $(own_chain); do
    case "$(ps -o command= -p "$p" 2>/dev/null)" in
      *claude*) out="$out
$p $(ps -o command= -p "$p" 2>/dev/null | cut -c1-70)" ;;
    esac
  done
  echo "${out}"
}

refuse_if_launched_by_jarvis() {
  local claude_procs
  claude_procs="$(own_claude)"
  [ -z "$(echo "$claude_procs" | sed '/^$/d')" ] && return 0

  echo "REFUSING TO $(echo "$VERB" | tr '[:lower:]' '[:upper:]') -- a Jarvis session is running this script."
  echo ""
  echo "This shell was started by a Claude Code session, so the stack below is"
  echo "this Jarvis's own -- his children rather than his parents, which the"
  echo "ancestor check would have waved through:"
  echo "$claude_procs" | sed '/^$/d' | sort -u -k1,1n | sed 's/^/    /'
  echo ""
  echo "Jarvis does not stop Jarvis (Serge, locked, 2026-08-04). Nothing was"
  echo "killed, no liveness files were cleared -- the stack is untouched."
  echo ""
  echo "Run it from your own Terminal window instead:"
  echo "    cd ~/Documents/Jarvis/Jarvis\\ Visual"
  echo "    ./jarvis.sh $VERB$([ "$KEEP_SPEECH" -eq 1 ] && echo ' --keep-speech')"
  exit 3
}

refuse_if_inside_stack() {
  # Spirit first, letter second: refuse a Jarvis-launched stop before the
  # ancestor test, which only catches the case where we'd kill ourselves.
  refuse_if_launched_by_jarvis

  local found="" g pat p
  while IFS= read -r g; do
    pat="${g#*|}"
    for p in $(find_pids "$pat"); do
      is_own "$p" && found="$found
$p $(ps -o command= -p "$p" 2>/dev/null | cut -c1-70)"
    done
  done <<<"$(kill_groups)"

  [ -z "$found" ] && return 0

  echo "REFUSING TO $(echo "$VERB" | tr '[:lower:]' '[:upper:]') -- this script is running inside the Jarvis stack."
  echo ""
  echo "These processes are our own ancestors. Stopping them would kill the"
  echo "session running this script, so nothing at all was stopped:"
  echo "$found" | sed '/^$/d' | sort -u -k1,1n | sed 's/^/    /'
  echo ""
  echo "Jarvis does not stop himself or his parents (Serge, locked). Nothing"
  echo "was killed, no liveness files were cleared -- the stack is untouched."
  echo ""
  echo "Run it from your own Terminal window instead:"
  echo "    cd ~/Documents/Jarvis/Jarvis\\ Visual"
  echo "    ./jarvis.sh $VERB$([ "$KEEP_SPEECH" -eq 1 ] && echo ' --keep-speech')"
  exit 3
}

# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
report() { # label, pids, extra
  if [ -n "${2// /}" ]; then
    printf '  %-16s UP    %-16s %s\n' "$1" "$2" "${3:-}"
  else
    printf '  %-16s down  %-16s %s\n' "$1" "" "${3:-}"
  fi
}

do_status() {
  echo "Jarvis stack:"
  report "browser Jarvis" "$(find_pids "$P_SERVER")" "port 8765"
  report "brain"          "$(find_pids "$P_BRAIN")"
  report "terminal line"  "$(find_pids "$P_LINE")" "off unless you start it"
  report "whisper"        "$(find_pids "$P_WHISPER")" "port 2022"
  report "kokoro"         "$(find_pids "$P_KOKORO")"  "port 8880"

  echo ""
  echo "ports:"
  local p
  for p in 8765 2022 8880; do
    if port_free "$p"; then printf '  %-5s free\n' "$p"
    else printf '  %-5s held\n' "$p"; fi
  done

  echo ""
  local code
  code=$(page_code)
  if [ "$code" = "000" ]; then
    echo "page http://127.0.0.1:8765/ -- not answering"
  else
    echo "page http://127.0.0.1:8765/ -- answering (http $code)"
  fi

  # Are we standing inside the stack? Then no verb that kills will work here.
  local inside=0 g p
  while IFS= read -r g; do
    for p in $(find_pids "${g#*|}"); do is_own "$p" && inside=1; done
  done <<<"$(kill_groups)"
  if [ "$inside" -eq 1 ]; then
    echo ""
    echo "NOTE: this shell is inside the Jarvis stack, so stop and restart"
    echo "      will refuse here. Use your own Terminal window for those."
  fi
  return 0
}

# --------------------------------------------------------------------------
# stop
# --------------------------------------------------------------------------

# TERM, wait up to 5s, then KILL whatever ignored it -- lesson 1.
stop_group() {
  local label="$1" pat="$2" pids all
  all=$(find_pids "$pat")
  if [ -z "${all// /}" ]; then
    # The terminal voice line is off unless Serge starts it himself, so a
    # bare "not running" reads as a failure in the middle of a successful
    # restart -- it confused him on 2026-08-04. Say it is a choice.
    if [ "$label" = "terminal line" ]; then
      printf '  %-16s off -- not in use\n' "$label"
    else
      printf '  %-16s not running\n' "$label"
    fi
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %-16s would stop: %s\n' "$label" "$all"
    return 0
  fi

  pids=$(find_others "$pat")
  # Backstop only: the pre-flight check should have caught this already.
  if [ -z "${pids// /}" ]; then
    printf '  %-16s REFUSED -- our own process chain (%s)\n' "$label" "$all" >&2
    return 1
  fi

  printf '  %-16s stopping %s' "$label" "$pids"
  kill $pids 2>/dev/null
  local _
  for _ in $(seq 1 10); do
    pids=$(find_others "$pat")
    [ -z "${pids// /}" ] && { echo " -- stopped"; return 0; }
    printf '.'
    sleep 0.5
  done

  echo " -- ignored TERM, forcing"
  kill -9 $pids 2>/dev/null
  sleep 1
  pids=$(find_pids "$pat")
  if [ -z "${pids// /}" ]; then
    printf '  %-16s stopped (forced)\n' "$label"
    return 0
  fi
  printf '  %-16s STILL ALIVE: %s\n' "$label" "$pids" >&2
  return 1
}

# Stack event log -- shared with voice-web-server.py, which reads it onto the
# HUD and lets a fresh brain read what happened while it did not exist
# (Serge, 2026-08-05). This script writes the events only IT can see: a stop
# is deliberate and the server is dead before it could log a thing.
#
# One `>>` of one short line: O_APPEND is what keeps this from interleaving
# with the server's own writes. Never fails the verb it is reporting on --
# a logger that can abort a stop is worse than no logger.
EVENTS="$VL/.stack-events.jsonl"
log_event() {   # kind label detail
  local ts; ts=$(date +%s)
  printf '{"ts": %s, "kind": "%s", "label": "%s", "detail": "%s"}\n' \
    "$ts" "$1" "$2" "$3" >>"$EVENTS" 2>/dev/null || true
}

do_stop() {
  refuse_if_inside_stack

  [ "$DRY_RUN" -eq 1 ] && echo "dry run -- nothing will be stopped"
  echo "stopping Jarvis..."
  # Logged before the killing starts, so a stop that hangs still leaves a
  # record that it was asked for. Dry runs stop nothing, so they say nothing.
  [ "$DRY_RUN" -eq 0 ] && log_event "off" "stack" "stop requested by Serge"

  local failed=0 g
  while IFS= read -r g; do
    stop_group "${g%%|*}" "${g#*|}" || failed=1
  done <<<"$(kill_groups)"
  [ "$KEEP_SPEECH" -eq 1 ] && echo "  speech servers   left running (--keep-speech)"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "dry run complete -- nothing was stopped"
    return 0
  fi

  # A hard kill leaves the liveness files behind. A stale .voice_state makes
  # a fresh page open mid-"thinking"; a stale .voice_question shows an
  # answered question in the waiting banner. .voice_transcript is left alone
  # on purpose -- it is the page's activity log, and seeing the last exchange
  # on restart is useful, not stale.
  echo "clearing stale state..."
  local cleared="" f
  for f in .voice_state .voice_heartbeat .voice_question .voice_waveform .voice_loading_pid; do
    if [ -e "$VL/$f" ]; then rm -f "$VL/$f" && cleared="$cleared $f"; fi
  done
  [ -n "$cleared" ] && echo " ${cleared# }" || echo "  nothing to clear"

  # Verify: ports released, and the page genuinely refuses to answer.
  echo "verifying..."
  local p code
  for p in 8765 2022 8880; do
    if [ "$KEEP_SPEECH" -eq 1 ] && [ "$p" != "8765" ]; then continue; fi
    if port_free "$p"; then
      printf '  port %-5s released\n' "$p"
    else
      printf '  port %-5s STILL HELD\n' "$p" >&2
      failed=1
    fi
  done
  code=$(page_code)
  if [ "$code" = "000" ]; then
    echo "  page 8765 not answering"
  else
    echo "  page 8765 STILL ANSWERING (http $code)" >&2
    failed=1
  fi

  echo ""
  if [ "$failed" -eq 0 ]; then
    echo "Jarvis is stopped."
    log_event "off" "stack" "stopped clean -- ports released, page silent"
    return 0
  fi
  echo "Jarvis did NOT fully stop -- see the lines above." >&2
  log_event "down" "stack" "stop did NOT complete -- something survived"
  return 1
}

# --------------------------------------------------------------------------
# start -- idempotent: starts only what is missing
# --------------------------------------------------------------------------
do_start() {
  log_event "up" "stack" "start requested"
  if ! alive "http://127.0.0.1:2022/"; then
    echo "starting whisper-server (port 2022)..."
    nohup whisper-server --host 127.0.0.1 --port 2022 \
      -m "$VL/models/ggml-small.en.bin" \
      --inference-path /v1/audio/transcriptions \
      -t 4 >>"$LOGS/whisper.log" 2>&1 &
  else
    echo "whisper already up (port 2022)"
  fi

  if ! alive "http://127.0.0.1:8880/v1/models"; then
    echo "starting kokoro (port 8880)..."
    local K="$VL/services/kokoro-fastapi"
    (cd "$K" && USE_GPU=true USE_ONNX=false PYTHONPATH="$K:$K/api" \
      MODEL_DIR=src/models VOICES_DIR=src/voices/v1_0 DEVICE_TYPE=mps \
      PYTORCH_ENABLE_MPS_FALLBACK=1 \
      nohup .venv/bin/python3 -m uvicorn api.src.main:app --host 127.0.0.1 --port 8880 \
      >>"$LOGS/kokoro.log" 2>&1 &)
  else
    echo "kokoro already up (port 8880)"
  fi

  printf "waiting for speech servers"
  local _
  for _ in $(seq 1 60); do
    alive "http://127.0.0.1:2022/" && alive "http://127.0.0.1:8880/v1/models" && break
    printf "."
    sleep 1
  done
  echo ""
  if ! alive "http://127.0.0.1:2022/" || ! alive "http://127.0.0.1:8880/v1/models"; then
    echo "speech servers did not come up -- check $LOGS/whisper.log and $LOGS/kokoro.log" >&2
    return 1
  fi

  # Idempotent: if the page already answers, do not start a second server.
  # Two servers racing for port 8765 is the orphaned-pair failure wearing a
  # different hat.
  if [ "$(page_code)" != "000" ]; then
    echo ""
    echo "browser Jarvis is already up: http://127.0.0.1:8765/"
    echo "(use 'restart' if you want a fresh brain)"
    return 0
  fi

  # Port held but the page silent = a half-dead server. Starting on top of it
  # is exactly the orphan incident; say so instead.
  if ! port_free 8765; then
    echo "port 8765 is held but the page does not answer -- a half-dead server." >&2
    echo "run './jarvis.sh stop' from your own Terminal first." >&2
    return 1
  fi

  local before
  before=$(grep -c "brain warm" "$LOG" 2>/dev/null || echo 0)
  echo "starting browser Jarvis (this warms a fresh brain, ~30s)..."
  # NOTE (2026-08-04, hunted twice -- don't hunt it a third time): this
  # subshell OUTLIVES the script. You will see an idle `bash ./jarvis.sh ...`
  # after the script exits; it is this `( ... )`, not the script, and it stands
  # as the launched service's parent for that service's lifetime, then dies
  # with it. Proof: its cwd is voice-line/ (only the subshell does cd "$VL"),
  # while the script's cwd is Jarvis Visual. Nothing accumulates, nothing
  # leaks. An `exec` "fix" was written and reverted -- an A/B showed both
  # launch forms behave identically, so the launch form is not the cause.
  (cd "$VL" && nohup uv run python "$JV/voice-web-server.py" >>"$LOG" 2>&1 &)

  printf "warming"
  for _ in $(seq 1 60); do
    local now
    now=$(grep -c "brain warm" "$LOG" 2>/dev/null || echo 0)
    [ "$now" -gt "$before" ] && { echo ""; echo "Jarvis is up: http://127.0.0.1:8765/"
      log_event "up" "stack" "Jarvis is up -- brain warm"; return 0; }
    printf "."
    sleep 2
  done
  echo ""
  # THE WAIT RUNNING OUT IS NOT A FAILURE -- ASK THE MACHINE BEFORE SAYING SO.
  # (Serge, 2026-08-09, on his own 1:52 PM start.) The old code declared
  # "brain did not warm in time" and wrote a `down` event the moment this
  # loop ended. That start was FINE: the server was up 8 seconds in and the
  # brain warmed at 14:00:39 -- 7m40s after the request, five and a half
  # minutes after this loop gave up at its two-minute budget. So he was told
  # his stack had failed when it had not, and -- far worse -- a false "start
  # failed" went into the APPEND-ONLY event log, which is the one record
  # every session trusts at boot and which nothing can retract.
  #
  # Raising the budget alone would only move the wrong answer later. The
  # honest question is not "did it warm inside my patience" but "is it
  # alive": a page that answers and a brain process in the table mean it is
  # still warming, and the server writes its own "brain warm" line when it
  # gets there. ONLY A DEAD SERVER EARNS THE WORD FAILED.
  local code brain
  code=$(page_code)
  brain=$(find_others "$P_BRAIN")
  if [ "$code" = "200" ] && [ -n "$brain" ]; then
    echo "still warming after $((60 * 2))s -- the server is up and the brain is alive."
    echo "  page:  http://127.0.0.1:8765/ (answering)"
    echo "  brain: pid $brain"
    echo "It will announce itself in $LOG; nothing is wrong and nothing needs restarting."
    # Deliberately NO event. The server logs "brain warm" itself when it is
    # ready, so the record stays true without this script guessing.
    return 0
  fi
  echo "brain did not warm in time -- check $LOG" >&2
  echo "  page answered: $code   brain pids: ${brain:-none}" >&2
  log_event "down" "stack" "start failed -- page $code, brain ${brain:-none}"
  return 1
}

# --------------------------------------------------------------------------
# restart -- stop, VERIFY the stop, then start
#
# The old restartJarvis.sh called the stop and swallowed its exit code with
# `|| true`. With the ancestry refusal in place that is a live trap: a restart
# run from inside the stack gets a refusal, ignores it, and launches a second
# server on top of the live one -- the orphaned pair, rebuilt. So: check it.
# --------------------------------------------------------------------------
do_restart() {
  refuse_if_inside_stack

  # Keep speech up across a restart -- we are only recycling the server, and
  # whisper/Kokoro are the slow two to start.
  KEEP_SPEECH=1
  if ! do_stop; then
    echo "" >&2
    echo "restart ABORTED -- the stop did not complete cleanly." >&2
    echo "Nothing new was started. Fix the stop first (see above), then retry." >&2
    return 1
  fi

  echo ""
  do_start
}

# Which Jarvis sessions are actually running. Read-only, and deliberately so:
# it answers from the registry log plus the live process table, and touches
# neither. Delegates to voice-line/session_registry.py rather than
# reimplementing the liveness rules here -- one source of truth for what
# "alive" means, the same reason the STACK panel copies its process patterns
# from this script instead of inventing its own.
do_sessions() {
  local py="$VL/.venv/bin/python3"
  [ -x "$py" ] || py="python3"
  "$py" "$VL/session_registry.py" --list
}

case "$VERB" in
  status)   do_status ;;
  sessions) do_sessions ;;
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_restart ;;
esac
exit $?
