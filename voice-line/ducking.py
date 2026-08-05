"""Spotify ducking: lower Spotify while the assistant speaks.

macOS implementation via AppleScript. Presence is checked through
System Events because a bare `tell application "Spotify"` would LAUNCH
the app -- we never do that. Restore is debounced 1.2s so back-to-back
sentence chunks don't yo-yo the volume.
"""

import asyncio

DUCK_FLOOR = 30
DUCK_FACTOR = 0.6
RESTORE_DEBOUNCE_S = 1.2


async def _osascript(script: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        if proc.returncode != 0:
            return None
        return out.decode().strip()
    except Exception:
        return None


class Ducker:
    def __init__(self) -> None:
        self._original_volume: int | None = None
        self._restore_task: asyncio.Task | None = None

    async def speaking_started(self) -> None:
        if self._restore_task is not None:
            self._restore_task.cancel()
            self._restore_task = None
        if self._original_volume is not None:
            return  # already ducked
        running = await _osascript(
            'tell application "System Events" to (name of processes) contains "Spotify"'
        )
        if running != "true":
            return
        state = await _osascript('tell application "Spotify" to player state as string')
        if state != "playing":
            return
        vol_text = await _osascript('tell application "Spotify" to get sound volume')
        try:
            volume = int(vol_text)
        except (TypeError, ValueError):
            return
        if volume <= DUCK_FLOOR:
            return
        ducked = max(DUCK_FLOOR, int(volume * DUCK_FACTOR))
        if await _osascript(
            f'tell application "Spotify" to set sound volume to {ducked}'
        ) is not None:
            self._original_volume = volume

    def speaking_stopped(self) -> None:
        if self._original_volume is None:
            return
        if self._restore_task is not None:
            self._restore_task.cancel()
        self._restore_task = asyncio.create_task(self._restore_later())

    async def _restore_later(self) -> None:
        await asyncio.sleep(RESTORE_DEBOUNCE_S)
        await self._restore_now()
        self._restore_task = None

    async def _restore_now(self) -> None:
        if self._original_volume is not None:
            await _osascript(
                f'tell application "Spotify" to set sound volume to {self._original_volume}'
            )
            self._original_volume = None

    async def shutdown(self) -> None:
        if self._restore_task is not None:
            self._restore_task.cancel()
            self._restore_task = None
        await self._restore_now()
