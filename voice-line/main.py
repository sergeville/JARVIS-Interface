"""voice-line: hold-to-talk voice conversations with Jarvis.

Launch with ./run-voice-line.sh (it brings up the two local servers),
or directly: uv run python main.py [--open-mic]

Half-duplex by construction: the mic only exists while the talk key is
held, and pressing the key (or typing) while the assistant is speaking
interrupts playback immediately.
"""

import argparse
import asyncio
import os
import re
import string
import sys
import termios
import tty
from pathlib import Path

import httpx

import signals
from brain import Brain, WARMUP_PROMPT
from ducking import Ducker
from ears import Ears, OpenMic
from mouth import Mouth
from ptt import TAP_SECONDS, HoldToTalk, PTT_KEY_NAME

QUIT_PHRASES = {"goodbye", "end voice mode", "hang up"}

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"
_ESCAPE_SEQ = re.compile(r"\x1b(?:\[[0-9;?]*[A-Za-z~]|O[A-Za-z])")
_GUTTER = re.compile(r"^\s*(?:[│┃|>]+\s?)*")


def is_quit(text: str) -> bool:
    return text.lower().strip().strip(string.punctuation + " ") in QUIT_PHRASES


class Console:
    """Typed input as a first-class turn, on a raw terminal.

    cbreak + kernel echo off, with our own tiny line editor, because
    canonical mode cannot host paste-aware input. Bracketed pastes are
    assembled invisibly into ONE message no matter their shape; a long
    paste echoes as a character count instead of the text.
    """

    def __init__(self, loop, typed_queue, on_keystroke) -> None:
        self._loop = loop
        self._queue = typed_queue
        self._on_keystroke = on_keystroke
        self._fd = sys.stdin.fileno()
        self._saved = None
        self._buffer = ""
        self._pending = ""
        self._paste: str | None = None

    def start(self) -> None:
        self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)  # keeps ISIG, so Ctrl-C still works
        sys.stdout.write("\x1b[?2004h")  # bracketed paste on
        sys.stdout.flush()
        self._loop.add_reader(self._fd, self._readable)

    def stop(self) -> None:
        try:
            self._loop.remove_reader(self._fd)
        except Exception:
            pass
        sys.stdout.write("\x1b[?2004l")
        sys.stdout.flush()
        if self._saved is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    def _readable(self) -> None:
        try:
            data = os.read(self._fd, 65536).decode(errors="ignore")
        except OSError:
            return
        if not data:
            return
        self._pending += data
        self._process()

    def _process(self) -> None:
        while self._pending:
            if self._paste is not None:
                end = self._pending.find(PASTE_END)
                if end < 0:
                    # hold back a possible partial end-marker straddling reads
                    keep = len(self._pending) - (len(PASTE_END) - 1)
                    self._paste += self._pending[:max(keep, 0)]
                    self._pending = self._pending[max(keep, 0):]
                    return
                self._paste += self._pending[:end]
                self._pending = self._pending[end + len(PASTE_END):]
                self._finish_paste()
                continue
            if self._pending.startswith("\x1b"):
                if self._pending.startswith(PASTE_START):
                    self._paste = ""
                    self._pending = self._pending[len(PASTE_START):]
                    continue
                m = _ESCAPE_SEQ.match(self._pending)
                if m:
                    self._pending = self._pending[m.end():]  # swallow arrows etc.
                    continue
                if len(self._pending) < len(PASTE_START):
                    return  # incomplete sequence: wait for more bytes
                self._pending = self._pending[1:]
                continue
            ch = self._pending[0]
            self._pending = self._pending[1:]
            self._handle_char(ch)

    def _handle_char(self, ch: str) -> None:
        self._on_keystroke()
        if ch in ("\r", "\n"):
            line, self._buffer = self._buffer, ""
            sys.stdout.write("\r\n")
            sys.stdout.flush()
            if line.strip():
                self._queue.put_nowait(line.strip())
        elif ch in ("\x7f", "\x08"):  # backspace
            if self._buffer:
                self._buffer = self._buffer[:-1]
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif ch == "\x15":  # Ctrl-U: clear the line
            sys.stdout.write("\b \b" * len(self._buffer))
            sys.stdout.flush()
            self._buffer = ""
        elif ch.isprintable():
            self._buffer += ch
            sys.stdout.write(ch)
            sys.stdout.flush()

    def _finish_paste(self) -> None:
        content, self._paste = self._scrub(self._paste or ""), None
        self._on_keystroke()
        if not content:
            return
        echo = f"[paste: {len(content)} chars]" if len(content) > 120 else content
        sys.stdout.write(echo)
        sys.stdout.flush()
        self._buffer += content

    @staticmethod
    def _scrub(text: str) -> str:
        """One message out of any paste shape: gutter glyphs and hard
        wraps removed, newlines collapsed."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [_GUTTER.sub("", ln).rstrip() for ln in text.split("\n")]
        return re.sub(r"\s+", " ", " ".join(ln for ln in lines if ln)).strip()


class VoiceLine:
    def __init__(self, open_mic: bool) -> None:
        self.open_mic_mode = open_mic
        self.ducker = Ducker()
        self.mouth = Mouth(self.ducker)
        self.ears = Ears()
        self.brain = Brain()
        self.speech_q: asyncio.Queue[str] = asyncio.Queue()
        self.typed_q: asyncio.Queue[str] = asyncio.Queue()
        self.turn_task: asyncio.Task | None = None
        self._turn_interrupted = False
        self.console: Console | None = None
        self.ptt: HoldToTalk | None = None
        self.loop = None

    # ---- interruption ----

    def interrupt_current(self) -> None:
        """Stop playback now; abort the in-flight brain turn if any."""
        self.mouth.interrupt()
        if self.turn_task is not None and not self.turn_task.done():
            self._turn_interrupted = True
            asyncio.create_task(self.brain.interrupt())

    def _keystroke(self) -> None:
        if self.mouth.speaking:
            self.interrupt_current()

    # ---- hold-to-talk callbacks (run on the loop) ----

    def ptt_pressed(self) -> None:
        self.interrupt_current()
        self.ears.open_mic()
        signals.set_state("listening")

    def ptt_released(self, held_for: float) -> None:
        if held_for < TAP_SECONDS:
            self.ears.abort()  # a tap is interrupt-only, not a turn
            signals.set_state("idle")
            return
        signals.set_state("thinking")
        asyncio.create_task(self._collect_speech())

    async def _collect_speech(self) -> None:
        text = await self.ears.finish()
        if text:
            self.speech_q.put_nowait(text)
        else:
            signals.set_state("idle")

    # ---- turns ----

    async def start_turn(self, prompt: str) -> None:
        if self.turn_task is not None and not self.turn_task.done():
            self.mouth.interrupt()
            await self.brain.interrupt()
            try:
                await asyncio.wait_for(self.turn_task, timeout=10)
            except Exception:
                self.turn_task.cancel()
        self.turn_task = asyncio.create_task(self._run_turn(prompt))

    async def _attempt(self, prompt: str) -> tuple[int, str]:
        """Stream one brain attempt to the mouth; return (chunks
        shipped, full reply text)."""
        shipped = 0
        parts: list[str] = []
        async for chunk in self.brain.stream(prompt):
            print(f"  {chunk}", flush=True)
            signals.transcript_add("jarvis", chunk)
            self.mouth.speak(chunk)
            parts.append(chunk)
            shipped += 1
        return shipped, " ".join(parts)

    async def _run_turn(self, prompt: str) -> None:
        self.mouth.turn_done = False
        self._turn_interrupted = False
        signals.set_state("thinking")
        try:
            shipped, reply = await self._attempt(prompt)
            if shipped == 0 and not self._turn_interrupted:
                # Zero chunks with no interrupt means a dead brain (a
                # stale overnight login answers "Not logged in", which
                # never streams as speakable text). Rebuild and give
                # the same turn one more shot -- mirrors the self-heal
                # in voice-web-server.py.
                print("\r[brain] empty turn -- rebuilding brain, retrying",
                      flush=True)
                self.mouth.speak("One moment -- restarting my brain.")
                await self.brain.close()
                self.brain = Brain()
                await self.brain.connect()
                if not self._turn_interrupted:
                    shipped, reply = await self._attempt(prompt)
                    if shipped == 0 and not self._turn_interrupted:
                        self.mouth.speak("I heard you, but the brain gave"
                                         " me nothing -- even after a"
                                         " restart.")
            if shipped > 0 and not self._turn_interrupted:
                signals.question_from_reply(reply)
            if reply:
                signals.log_transcript("Jarvis", reply)
        except Exception as e:
            print(f"\r[brain] turn failed: {e}", flush=True)
            self.mouth.speak("Sorry, that turn failed on me.")
        finally:
            self.mouth.turn_done = True
            await self.mouth.wait_idle()
            if not self.ears.recording:
                signals.set_state("idle")

    async def handle_input(self, text: str, source: str) -> None:
        print(f"\r[{source}] {text}", flush=True)
        signals.transcript_add("you", text)
        signals.log_transcript("Serge", text)
        signals.clear_question()
        if is_quit(text):
            self.mouth.turn_done = True
            self.mouth.speak("Goodbye.")
            await self.mouth.wait_idle()
            raise SystemExit(0)
        await self.start_turn(text)

    # ---- lifecycle ----

    async def _check_servers(self) -> None:
        checks = [
            ("whisper (port 2022)", "http://127.0.0.1:2022/"),
            ("kokoro (port 8880)", "http://127.0.0.1:8880/v1/models"),
        ]
        async with httpx.AsyncClient(timeout=3.0) as http:
            for name, url in checks:
                try:
                    await http.get(url)
                except Exception:
                    sys.exit(
                        f"{name} is not answering -- launch with ./run-voice-line.sh"
                    )

    async def _open_mic_loop(self) -> None:
        open_mic = OpenMic()
        gate = lambda: not self.mouth.speaking
        signals.set_state("listening")
        async for text in open_mic.utterances(gate):
            self.speech_q.put_nowait(text)

    async def _heartbeat_loop(self) -> None:
        while True:
            signals.beat()
            await asyncio.sleep(5)

    async def _inbox_loop(self) -> None:
        """Lines typed into the browser page arrive here as turns."""
        while True:
            for text in signals.drain_inbox():
                self.typed_q.put_nowait(text)
            await asyncio.sleep(0.5)

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        inbox_task = asyncio.create_task(self._inbox_loop())
        signals.set_state("idle")
        await self._check_servers()
        self.mouth.start()
        print("connecting to Claude...", flush=True)
        await self.brain.connect()
        # Hide the first-turn prompt-cache toll behind a spoken greeting.
        await self.start_turn(WARMUP_PROMPT)

        if self.open_mic_mode:
            open_mic_task = asyncio.create_task(self._open_mic_loop())
            print("voice line ready -- open mic (VAD). Type anytime; say or type"
                  " 'goodbye' to end.", flush=True)
        else:
            open_mic_task = None
            self.ptt = HoldToTalk(self.loop, self.ptt_pressed, self.ptt_released)
            self.ptt.start()
            print(f"voice line ready -- hold {PTT_KEY_NAME} to talk, tap it to"
                  " interrupt, or just type. Say or type 'goodbye' to end.",
                  flush=True)

        self.console = Console(self.loop, self.typed_q, self._keystroke)
        self.console.start()

        speech_f: asyncio.Task | None = None
        typed_f: asyncio.Task | None = None
        try:
            while True:
                # Race speech against typing; unfinished futures stay
                # alive across iterations (hard-won rule -- recreating
                # them every loop drops queued turns).
                if speech_f is None:
                    speech_f = asyncio.create_task(self.speech_q.get())
                if typed_f is None:
                    typed_f = asyncio.create_task(self.typed_q.get())
                done, _ = await asyncio.wait(
                    {speech_f, typed_f}, return_when=asyncio.FIRST_COMPLETED
                )
                if speech_f in done:
                    text, speech_f = speech_f.result(), None
                    await self.handle_input(text, "voice")
                if typed_f in done:
                    text, typed_f = typed_f.result(), None
                    await self.handle_input(text, "typed")
        finally:
            for f in (speech_f, typed_f, open_mic_task, heartbeat_task,
                      inbox_task):
                if f is not None:
                    f.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.console is not None:
            self.console.stop()
        if self.ptt is not None:
            self.ptt.stop()
        if self.ears.recording:
            self.ears.abort()
        await self.mouth.close()
        await self.ducker.shutdown()
        await self.brain.close()
        signals.set_state("idle")
        signals.loading_finished()
        signals.heartbeat_stopped()


def main() -> None:
    parser = argparse.ArgumentParser(description="voice-line: talk to Jarvis")
    parser.add_argument("--open-mic", action="store_true",
                        help="legacy VAD open-mic mode instead of hold-to-talk")
    args = parser.parse_args()
    try:
        asyncio.run(VoiceLine(open_mic=args.open_mic).run())
    except KeyboardInterrupt:
        print("\nvoice line closed.")
    except SystemExit as e:
        if e.code == 0:
            print("\nvoice line closed.")
        else:
            raise
    except BaseException:
        # Crashes must leave a trace: the launcher restarts us, and
        # without this file there is nothing to diagnose afterwards.
        import datetime
        import traceback
        log = Path(__file__).resolve().parent / "logs" / "voice-line.log"
        try:
            log.parent.mkdir(exist_ok=True)
            with log.open("a") as f:
                f.write(f"\n--- crash at {datetime.datetime.now().isoformat()} ---\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
