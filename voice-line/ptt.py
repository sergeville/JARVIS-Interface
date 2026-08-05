"""Global hold-to-talk key listener (pynput).

The talk key is Right Command (Serge's pick). Holding it opens the
mic; releasing it closes the mic. Needs macOS Input Monitoring
permission for the hosting terminal app.

Key-repeat filter: the OS fires on_press continuously while a key is
held. Without the held-state flag, every repeat looks like a fresh
press -- and since a fresh press interrupts playback, that bug kills
every reply before it can speak.
"""

import time

from pynput import keyboard

PTT_KEY = keyboard.Key.cmd_r
PTT_KEY_NAME = "Right Command"
TAP_SECONDS = 0.25  # anything shorter is an interrupt-only tap, not a turn


class HoldToTalk:
    """Fires on_press / on_release(held_for) on the asyncio loop."""

    def __init__(self, loop, on_press, on_release) -> None:
        self._loop = loop
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._pressed_at = 0.0
        self._listener = keyboard.Listener(
            on_press=self._press, on_release=self._release
        )

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def _press(self, key) -> None:
        if key != PTT_KEY:
            return
        if self._held:
            return  # OS key-repeat, not a fresh press
        self._held = True
        self._pressed_at = time.monotonic()
        self._loop.call_soon_threadsafe(self._on_press)

    def _release(self, key) -> None:
        if key != PTT_KEY or not self._held:
            return
        self._held = False
        held_for = time.monotonic() - self._pressed_at
        self._loop.call_soon_threadsafe(self._on_release, held_for)
