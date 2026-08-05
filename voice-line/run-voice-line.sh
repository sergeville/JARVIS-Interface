#!/usr/bin/env bash
# voice-line launcher: brings up the two local servers if they're not
# already listening, then runs the voice line in the FOREGROUND of this
# terminal. Never daemonize the voice line itself -- mic permission
# comes from the hosting terminal, and nobody wants a 24/7 open mic.
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

alive() { curl -s -m 2 -o /dev/null "$1"; }

WHISPER_URL="http://127.0.0.1:2022/"
KOKORO_URL="http://127.0.0.1:8880/v1/models"

if ! alive "$WHISPER_URL"; then
  echo "starting whisper-server (port 2022)..."
  nohup whisper-server --host 127.0.0.1 --port 2022 \
    -m "$ROOT/models/ggml-small.en.bin" \
    --inference-path /v1/audio/transcriptions \
    -t 4 >>"$LOGS/whisper.log" 2>&1 &
fi

if ! alive "$KOKORO_URL"; then
  echo "starting kokoro (port 8880)..."
  K="$ROOT/services/kokoro-fastapi"
  (cd "$K" && USE_GPU=true USE_ONNX=false PYTHONPATH="$K:$K/api" \
    MODEL_DIR=src/models VOICES_DIR=src/voices/v1_0 DEVICE_TYPE=mps \
    PYTORCH_ENABLE_MPS_FALLBACK=1 \
    nohup .venv/bin/python3 -m uvicorn api.src.main:app --host 127.0.0.1 --port 8880 \
    >>"$LOGS/kokoro.log" 2>&1 &)
fi

printf "waiting for servers"
for _ in $(seq 1 60); do
  if alive "$WHISPER_URL" && alive "$KOKORO_URL"; then
    break
  fi
  printf "."
  sleep 1
done
echo ""

if ! alive "$WHISPER_URL" || ! alive "$KOKORO_URL"; then
  echo "servers did not come up -- check $LOGS/whisper.log and $LOGS/kokoro.log" >&2
  exit 1
fi

cd "$ROOT"
# Watchdog: restart the voice line if it crashes (still inside this
# terminal, so mic permission survives). Clean exits and Ctrl-C stop it.
while true; do
  uv run python main.py "$@"
  code=$?
  if [ "$code" -eq 0 ] || [ "$code" -eq 130 ]; then
    exit "$code"
  fi
  echo "voice line died (exit $code) -- see logs/voice-line.log; restarting in 2s..." | tee -a "$LOGS/voice-line.log"
  sleep 2
done
