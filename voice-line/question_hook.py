"""Waiting-indicator writer: Claude Code hook -> .voice_question.

Wired into ~/.claude/settings.json for every Jarvis session (terminal
chief-of-staff sessions, the browser brain, the voice line's brain --
they all load user settings). The visual page shows .voice_question as
the "Waiting for your answer" banner via voice-web-server's /signals.

Modes (argv[1]):
  stop    Stop hook. Read the session transcript, take the last
          assistant message; if it ends on a question, write the
          trailing question to .voice_question, else clear it.
  clear   UserPromptSubmit hook. Serge is engaging -- clear the file.
  notify  Notification hook. Permission prompts and idle nudges are
          also "waiting on Serge"; write a line, but never clobber a
          specific pending question with a generic nudge.

A hook must never break the session: everything is wrapped, and the
exit code is always 0.
"""

import json
import os
import re
import sys
from pathlib import Path

QUESTION_FILE = Path(__file__).resolve().parent / ".voice_question"

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_TRAILING_CLOSERS = "\"')]} *_`"


def _clean(text: str) -> str:
    """Markdown to banner-friendly plain text."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_`#]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def trailing_question(text: str) -> str | None:
    """The question the reply ends on, if any (up to two sentences)."""
    text = _clean(text)
    if not text.rstrip(_TRAILING_CLOSERS).endswith("?"):
        return None
    sentences = _SENTENCE_END.split(text)
    tail: list[str] = []
    for sentence in reversed(sentences):
        if sentence.rstrip(_TRAILING_CLOSERS).endswith("?") and len(tail) < 2:
            tail.append(sentence.strip())
        else:
            break
    question = " ".join(reversed(tail)).strip()
    if len(question) > 300:
        question = question[:297].rstrip() + "…"
    return question or None


def last_assistant_text(transcript_path: str) -> str:
    """Final assistant text in a session transcript (JSONL); subagent
    sidechain chatter is skipped."""
    last = ""
    with open(transcript_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text"]
            else:
                texts = []
            joined = "\n".join(t for t in texts if t).strip()
            if joined:
                last = joined
    return last


JARVIS_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _read_stdin():
    """The hook payload, via the shared bounded reader. Never raises, never blocks.

    ALL THREE OF THESE HOOKS HUNG FOREVER before 2026-08-15, and the proof was
    six for six: a silent pipe and a complete payload on a pipe the caller had
    not closed, against every one of them. `sys.stdin.read()` runs to EOF and
    `json.load` calls it, so an inherited descriptor that never delivers -- or
    never closes -- simply stops the hook. These fire on SessionStart,
    SessionEnd, Stop, UserPromptSubmit and Notification, which is to say on
    nearly every turn of every session on the machine.

    Same class as session_record.py and board-guard.py, fixed 2026-08-14, and
    the fourth and fifth and sixth instance of it. vault-tools/hookio.py exists
    because two authors independently reached for the same wrong guard; these
    three reached for none at all.

    Import failure returns None rather than raising: a hook that cannot read
    stdin has nothing to act on, and never-crash outranks the work.
    """
    try:
        sys.path.insert(0, os.path.join(JARVIS_ROOT, "vault-tools"))
        import hookio
        return hookio.read_json_stdin()
    except Exception:
        return None

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = _read_stdin() or {}

    if mode == "clear":
        QUESTION_FILE.unlink(missing_ok=True)

    elif mode == "stop":
        text = ""
        path = data.get("transcript_path", "")
        if path and Path(path).exists():
            text = last_assistant_text(path)
        question = trailing_question(text)
        if question:
            QUESTION_FILE.write_text(question)
        else:
            QUESTION_FILE.unlink(missing_ok=True)

    elif mode == "notify":
        message = str(data.get("message", "") or "")
        if "permission" in message.lower():
            QUESTION_FILE.write_text(message.replace("Claude", "Jarvis"))
        elif not QUESTION_FILE.exists():
            QUESTION_FILE.write_text(
                "Jarvis is waiting for you at the terminal.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
