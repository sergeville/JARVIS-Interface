"""Signal bus for the visualizer: tiny files in the project root.

The contract is just files -- anything can watch them. Writes must
NEVER crash the voice line, so every write is wrapped. One file is
deliberately absent here: `.voice_alert` belongs to OTHER processes
that want the visualizer's attention; the voice line never writes it.
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Permanent conversation record (per Serge, 2026-08-03): every channel
# appends its exchanges here, one markdown file per day.
TRANSCRIPTS_DIR = ROOT.parent / "Jarvis Visual" / "transcripts"

STATE_FILE = ROOT / ".voice_state"          # idle | listening | thinking | speaking
WAVEFORM_FILE = ROOT / ".voice_waveform"    # {"ts": float, "samples": [64 floats]}
LOADING_PID_FILE = ROOT / ".voice_loading_pid"
HEARTBEAT_FILE = ROOT / ".voice_heartbeat"  # unix timestamp, rewritten every few seconds
TRANSCRIPT_FILE = ROOT / ".voice_transcript"  # JSON list of last {"who","text"} turns
INBOX_DIR = ROOT / ".voice_inbox.d"         # one file per line typed in the browser page
QUESTION_FILE = ROOT / ".voice_question"    # trailing question of the last turn; the page's waiting banner

_WAVEFORM_MIN_INTERVAL = 1.0 / 15.0         # at most 15 writes per second
_last_waveform_ts = 0.0


def set_state(state: str) -> None:
    try:
        STATE_FILE.write_text(state)
    except Exception:
        pass


def write_waveform(samples) -> None:
    """Write one waveform frame (64 floats), throttled to 15 Hz.

    Self-heal rule: every waveform write also re-writes state to
    "speaking". This only runs while audio is audibly playing, so any
    stray process that stomps the state file gets corrected within
    about 70ms.
    """
    global _last_waveform_ts
    now = time.time()
    if now - _last_waveform_ts < _WAVEFORM_MIN_INTERVAL:
        return
    _last_waveform_ts = now
    try:
        WAVEFORM_FILE.write_text(
            json.dumps({"ts": now, "samples": [float(s) for s in samples]})
        )
    except Exception:
        pass
    set_state("speaking")


def beat() -> None:
    """Prove the voice line is alive: timestamp, rewritten on a timer.
    Watchers treat a stale (or missing) file as 'voice line is down'."""
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except Exception:
        pass


def heartbeat_stopped() -> None:
    try:
        HEARTBEAT_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def log_transcript(role: str, text: str) -> None:
    """Append one exchange line to today's transcript file. The page's
    activity log is 30 lines and dies on reload; this is the permanent
    record (per Serge, 2026-08-03). Shared by every channel."""
    text = " ".join(text.split())
    if not text:
        return
    try:
        TRANSCRIPTS_DIR.mkdir(exist_ok=True)
        day = time.strftime("%Y-%m-%d")
        stamp = time.strftime("%H:%M:%S")
        with open(TRANSCRIPTS_DIR / f"{day}.md", "a") as f:
            f.write(f"- **{stamp} {role}:** {text}\n")
    except Exception as e:
        print(f"transcript write failed: {e}", file=sys.stderr, flush=True)


_transcript: list = []


def transcript_add(who: str, text: str) -> None:
    """Append one line ('you' or 'jarvis') to the shared transcript file
    so the browser page can mirror the conversation."""
    _transcript.append({"who": who, "text": text})
    del _transcript[:-20]
    try:
        TRANSCRIPT_FILE.write_text(json.dumps(_transcript))
    except Exception:
        pass


def question_from_reply(reply: str) -> None:
    """End of a completed turn: if the reply ends on a question, post it
    for the page's waiting banner; otherwise clear any pending one.
    (Terminal Claude Code sessions get the same behavior from the
    question_hook.py Stop hook instead.)"""
    try:
        from question_hook import trailing_question
        question = trailing_question(reply or "")
        if question:
            QUESTION_FILE.write_text(question)
        else:
            QUESTION_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def clear_question() -> None:
    """Serge is engaging (new turn, or hanging up): nothing pending."""
    try:
        QUESTION_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def drain_inbox() -> list:
    """Collect (and delete) messages the browser page dropped for us."""
    msgs = []
    try:
        for f in sorted(INBOX_DIR.glob("*.txt")):
            try:
                msgs.append(f.read_text().strip())
                f.unlink()
            except Exception:
                pass
    except Exception:
        pass
    return [m for m in msgs if m]


def loading_started() -> None:
    try:
        LOADING_PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


def loading_finished() -> None:
    try:
        LOADING_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
