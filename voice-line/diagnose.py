"""Voice-line diagnostics: is the key listener alive, and is the mic hot?

Run in the SAME terminal window the voice line runs in (quit the voice
line first with Ctrl-C):

    cd ~/Documents/Jarvis/voice-line && uv run python diagnose.py
"""

import time

print()
print("== 1) Global key listener ==")
from pynput import keyboard  # noqa: E402

events: list[str] = []

def on_press(key):
    events.append(str(key))
    print(f"   saw press:   {key}")

def on_release(key):
    events.append(str(key))
    print(f"   saw release: {key}")

listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()
print("   Press and release the RIGHT COMMAND key a few times, plus any")
print("   letter key once. You have 10 seconds...")
time.sleep(10)
listener.stop()

saw_cmd_r = any("cmd_r" in e for e in events)
if not events:
    print("-> FAIL: zero key events reached this process.")
    print("   Input Monitoring is NOT active for this terminal app.")
    print("   System Settings -> Privacy & Security -> Input Monitoring:")
    print("   add/enable Terminal, quit Terminal fully (Cmd-Q), reopen, retry.")
elif not saw_cmd_r:
    print("-> PARTIAL: the listener works, but no 'cmd_r' event arrived.")
    print("   Whatever the right Command key reports as is in the lines above --")
    print("   tell Jarvis what it says and the talk key gets retargeted.")
else:
    print("-> OK: listener alive and Right Command arrives as Key.cmd_r.")

print()
print("== 2) Microphone ==")
import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402

try:
    device = sd.query_devices(kind="input")
    print(f"   input device: {device['name']}")
    print("   Say something out loud for 2 seconds...")
    rec = sd.rec(int(2 * 16000), samplerate=16000, channels=1, dtype="int16")
    sd.wait()
    peak = int(np.abs(rec).max())
    print(f"   peak level: {peak}")
    if peak < 50:
        print("-> FAIL: the mic recorded silence.")
        print("   Microphone permission is missing for this terminal app")
        print("   (System Settings -> Privacy & Security -> Microphone), or the")
        print("   input device above is not the one you spoke into.")
    else:
        print("-> OK: the mic hears you.")
except Exception as e:
    print(f"-> FAIL: could not open the mic at all: {e}")

print()
print("Done. Show Jarvis this output.")
