"""TTS queue and playback: sentences in, audio out the speakers.

Kokoro (local, port 8880) synthesizes one sentence at a time to raw
PCM int16 24kHz mono. Playback is block-by-block so an interrupt cuts
the audio within ~45ms, and every block feeds the visualizer's signal
bus. Interrupt = clear the queue + stop playback now.
"""

import asyncio
import threading

import httpx
import numpy as np
import sounddevice as sd

import signals

KOKORO_URL = "http://127.0.0.1:8880/v1/audio/speech"
KOKORO_VOICE = "bm_lewis"
SAMPLE_RATE = 24000
BLOCK_FRAMES = 1024  # ~43ms per block at 24kHz
WAVEFORM_POINTS = 64


def _downsample(block: np.ndarray) -> list[float]:
    if block.size == 0:
        return [0.0] * WAVEFORM_POINTS
    idx = np.linspace(0, block.size - 1, WAVEFORM_POINTS).astype(int)
    return np.abs(block[idx]).astype(float).tolist()


class Mouth:
    """A cancellable queue of sentences headed for the speakers."""

    def __init__(self, ducker=None) -> None:
        self._queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self._gen = 0                      # bumped on interrupt; stale items are skipped
        self._cancel = threading.Event()   # aborts the currently-playing audio
        self._idle = asyncio.Event()
        self._idle.set()
        self._ducker = ducker
        self._http = httpx.AsyncClient(timeout=60.0)
        self._worker_task: asyncio.Task | None = None
        self._inflight: set[asyncio.Task] = set()  # synthesis in progress
        self._out: sd.OutputStream | None = None   # persistent, only the playback thread touches it
        self.turn_done = True  # main.py holds this False while the brain is mid-turn

    def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    def speak(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        self._idle.clear()
        self._queue.put_nowait((self._gen, sentence))

    def interrupt(self) -> None:
        """Clear the queue, cancel in-flight synthesis, stop playback now."""
        self._gen += 1
        try:
            while True:
                self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        for task in list(self._inflight):
            task.cancel()
        self._cancel.set()

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def close(self) -> None:
        self.interrupt()
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._out is not None:
            try:
                self._out.abort()
                self._out.close()
            except Exception:
                pass
            self._out = None
        await self._http.aclose()

    def _spawn_synth(self, sentence: str) -> asyncio.Task:
        task = asyncio.create_task(self._synthesize(sentence))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return task

    async def _await_synth(self, task: asyncio.Task) -> bytes | None:
        try:
            return await task
        except asyncio.CancelledError:
            # If the cancel was aimed at the worker itself (close()),
            # let it through; an interrupt() only cancelled the child.
            if asyncio.current_task().cancelling():
                raise
            return None

    async def _worker(self) -> None:
        prefetched: tuple[int, asyncio.Task] | None = None
        while True:
            if prefetched is not None:
                (gen, task), prefetched = prefetched, None
            else:
                gen, sentence = await self._queue.get()
                if gen != self._gen:
                    self._settle(busy=False)
                    continue
                task = self._spawn_synth(sentence)
            duck: asyncio.Task | None = None
            if self._ducker is not None:
                # Duck while Kokoro synthesizes: the osascript round
                # trips (0.1-0.5s) hide behind synthesis instead of
                # delaying the first audio block.
                duck = asyncio.create_task(self._ducker.speaking_started())
            try:
                pcm = await self._await_synth(task)
            except asyncio.CancelledError:
                if duck is not None:
                    duck.cancel()
                raise
            if pcm is None or gen != self._gen:
                if duck is not None:
                    await duck
                    self._ducker.speaking_stopped()
                self._settle(busy=prefetched is not None)
                continue
            # Back-to-back playback: synthesize the NEXT chunk (one at
            # a time, never in parallel) while this one plays.
            if not self._queue.empty():
                next_gen, next_sentence = self._queue.get_nowait()
                if next_gen == self._gen:
                    prefetched = (next_gen, self._spawn_synth(next_sentence))
            # The previous playback (the only thing _cancel can point
            # at) has already returned -- this worker is serial -- so
            # clearing it here can't un-cancel anything in flight.
            self._cancel.clear()
            if duck is not None:
                await duck
            await asyncio.to_thread(self._play_pcm, pcm)
            if self._ducker is not None:
                self._ducker.speaking_stopped()
            self._settle(busy=prefetched is not None)

    def _settle(self, busy: bool) -> None:
        """Nothing queued and nothing prefetched: mark idle. Mid-turn
        silence (a tool running) is honest 'thinking'; after the turn
        it's 'idle'."""
        if busy or not self._queue.empty():
            return
        self._idle.set()
        signals.set_state("idle" if self.turn_done else "thinking")

    async def _synthesize(self, sentence: str) -> bytes | None:
        try:
            r = await self._http.post(KOKORO_URL, json={
                "model": "kokoro",
                "input": sentence,
                "voice": KOKORO_VOICE,
                "response_format": "pcm",
                "speed": 1.0,
            })
            r.raise_for_status()
            return r.content
        except Exception as e:
            print(f"\r[mouth] TTS failed: {e}", flush=True)
            return None

    def _play_pcm(self, pcm: bytes) -> None:
        """Blocking playback in a thread; checks the cancel flag every block.

        The output stream is persistent and stays running between
        chunks and turns -- per-chunk open/drain is what puts audible
        gaps between sentences. Interrupt aborts it (dropping buffered
        audio now); the next chunk restarts it.
        """
        data = np.frombuffer(pcm, dtype=np.int16)
        if data.size == 0:
            return
        try:
            if self._out is None:
                self._out = sd.OutputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                    blocksize=BLOCK_FRAMES,
                )
                self._out.start()
            elif self._out.stopped:
                self._out.start()
        except Exception as e:
            print(f"\r[mouth] audio device failed: {e}", flush=True)
            self._out = None
            return
        signals.set_state("speaking")  # first audio block of the chunk
        for i in range(0, data.size, BLOCK_FRAMES):
            if self._cancel.is_set():
                self._out.abort()  # drop buffered audio immediately
                return
            block = data[i:i + BLOCK_FRAMES]
            self._out.write(np.ascontiguousarray(block.reshape(-1, 1)))
            signals.write_waveform(_downsample(block))
