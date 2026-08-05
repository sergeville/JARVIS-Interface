"""Mic capture and transcription.

Hold-to-talk: the input stream exists ONLY while the key is held (plus
a 0.18s tail so the last word survives), so room audio and music never
leak into the transcriber between holds. Audio goes to the local
whisper server as 16kHz mono WAV on the OpenAI-style route.

OpenMic is the legacy always-listening mode behind --open-mic:
webrtcvad endpointing, utterances with under 240ms of actual speech
are discarded, and the caller gates it while the mouth is speaking.
"""

import asyncio
import io
import re
import wave
from collections import deque

import httpx
import numpy as np
import sounddevice as sd

WHISPER_URL = "http://127.0.0.1:2022/v1/audio/transcriptions"
SAMPLE_RATE = 16000
TAIL_SECONDS = 0.18

# Vocabulary hint: biases decoding toward the words that actually recur
# here, so "Kokoro" stops coming back as "cocoa". Costs no extra time.
VOCAB_PROMPT = (
    "Jarvis, Serge, Kokoro, Whisper, Obsidian, the vault, VAULT-INDEX, "
    "daily notes, Active Priorities, Session Board, Claude, Claude Code, "
    "Anthropic, the voice line, push-to-talk, latency, transcript."
)

# [SIGHS], [BLANK_AUDIO] and friends -- whisper's non-speech markers
_NON_SPEECH = re.compile(r"\[[^\]]*\]")


def clean_transcript(text: str) -> str:
    return " ".join(_NON_SPEECH.sub(" ", text).split())


def _to_wav(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


async def transcribe_wav(wav: bytes) -> str:
    async with httpx.AsyncClient(timeout=60.0) as http:
        r = await http.post(
            WHISPER_URL,
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={
                "response_format": "json",
                "temperature": "0.0",
                "prompt": VOCAB_PROMPT,
            },
        )
        r.raise_for_status()
        return clean_transcript(r.json().get("text", ""))


class Ears:
    """Push-to-talk capture: open on key press, closed on release."""

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def open_mic(self) -> None:
        if self._stream is not None:
            return
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            callback=self._on_audio,
        )
        self._stream.start()

    def _on_audio(self, indata, frames, time_info, status) -> None:
        self._frames.append(indata[:, 0].copy())

    def _close_mic(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    def abort(self) -> None:
        """Tap shorter than the threshold: discard, no transcription."""
        self._close_mic()
        self._frames = []

    async def finish(self) -> str:
        """Key released: keep the tail, fully close the mic, transcribe."""
        await asyncio.sleep(TAIL_SECONDS)
        self._close_mic()
        frames, self._frames = self._frames, []
        if not frames:
            return ""
        try:
            return await transcribe_wav(_to_wav(np.concatenate(frames)))
        except Exception as e:
            print(f"\r[ears] transcription failed: {e}", flush=True)
            return ""


FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480
MIN_SPEECH_MS = 240
SILENCE_END_MS = 900
PRE_ROLL_FRAMES = 10  # ~300ms so the utterance start isn't clipped


class OpenMic:
    """Legacy open-mic mode (--open-mic): VAD-endpointed utterances."""

    async def utterances(self, gate):
        """Async generator of transcribed utterances.

        `gate()` returning False (mouth speaking) drops audio and
        resets endpointing -- the half-duplex guarantee.
        """
        import webrtcvad

        vad = webrtcvad.Vad(2)
        q: asyncio.Queue[bytes] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def cb(indata, frames, time_info, status):
            loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=FRAME_SAMPLES, callback=cb,
        )
        stream.start()
        pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_FRAMES)
        voiced: list[bytes] = []
        in_speech = False
        speech_ms = silence_ms = 0
        try:
            while True:
                frame = await q.get()
                if not gate():
                    pre_roll.clear()
                    voiced = []
                    in_speech = False
                    speech_ms = silence_ms = 0
                    continue
                if len(frame) != FRAME_SAMPLES * 2:
                    continue
                is_speech = vad.is_speech(frame, SAMPLE_RATE)
                if not in_speech:
                    pre_roll.append(frame)
                    if is_speech:
                        in_speech = True
                        voiced = list(pre_roll)
                        pre_roll.clear()
                        speech_ms, silence_ms = FRAME_MS, 0
                    continue
                voiced.append(frame)
                if is_speech:
                    speech_ms += FRAME_MS
                    silence_ms = 0
                else:
                    silence_ms += FRAME_MS
                if silence_ms >= SILENCE_END_MS:
                    utterance, voiced = voiced, []
                    in_speech = False
                    had_speech = speech_ms >= MIN_SPEECH_MS
                    speech_ms = silence_ms = 0
                    if not had_speech:
                        continue  # too little actual speech: discard
                    audio = np.frombuffer(b"".join(utterance), dtype=np.int16)
                    try:
                        text = await transcribe_wav(_to_wav(audio))
                    except Exception as e:
                        print(f"\r[ears] transcription failed: {e}", flush=True)
                        continue
                    if text:
                        yield text
        finally:
            stream.stop()
            stream.close()
