# Voice Line — Cheat Sheet

## Browser mode (the full experience: voice + ring in one window)

    ~/Documents/Jarvis/Jarvis\ Visual/run-visual.sh

Opens http://127.0.0.1:8765/ — hold **Right Command** with the page
focused (or click-hold the button), talk, release; or type in the box.
The ring is Jarvis's face and pulses with his voice. First hold asks
for microphone permission — click Allow, then hold again.

**Pick one channel at a time:** the Terminal voice line below also
listens for Right Command globally, so running both means two answers.

## Terminal mode

    cd ~/Documents/Jarvis/voice-line && ./run-voice-line.sh

Run it in a Terminal window, never as a background service. It starts the two
local servers if they're down (first Kokoro boot takes ~15s), then the voice
line takes the foreground.

**First launch only:**
1. macOS will ask for **Microphone** access for Terminal — allow it.
2. Grant **Input Monitoring** to Terminal: System Settings → Privacy &
   Security → Input Monitoring → enable your terminal app. Relaunch after.

## Controls

| You do | It does |
| --- | --- |
| Hold **Right Command** (anywhere in macOS) | Mic opens — talk |
| Release it | Mic closes, Jarvis answers out loud |
| Tap it (under ¼ second) | Interrupts Jarvis mid-sentence, nothing recorded |
| Hold it while Jarvis talks | Interrupts AND opens the mic for your turn |
| Type in the voice terminal | A real turn — reply is spoken; typing while he talks cuts him off; pastes of any shape land as one message |
| Say or type "goodbye" / "end voice mode" / "hang up" | Ends the session (Ctrl-C works too) |

Legacy always-listening mode: `./run-voice-line.sh --open-mic` (VAD, no key).

## Good to know

- The first greeting takes several seconds — that's the one-time cache warmup
  being hidden behind it. Turns after that are fast.
- Spotify ducks while Jarvis speaks and restores ~1s after he stops. It is
  never launched, only lowered.
- Voice Jarvis reads the vault and edits notes; riskier tool use is
  auto-denied in voice mode — that work belongs in a terminal session.
- Voice: Kokoro `bm_lewis` — one setting in `mouth.py` (`KOKORO_VOICE`).
- Talk key: `PTT_KEY` in `ptt.py`.
- Servers: whisper on port 2022, Kokoro on 8880; logs in
  `~/Documents/Jarvis/voice-line/logs/`.
- Visualizer signal bus: `.voice_state` and `.voice_waveform` in
  `~/Documents/Jarvis/voice-line/`.
- The ring visual: `~/Documents/Jarvis/Jarvis Visual/run-visual.sh` opens
  it at http://127.0.0.1:8765/ — it follows the signal bus (Jarvis's own
  voice), no microphone and no button needed. Keep its tab visible on
  screen: Chrome freezes animation in hidden tabs, so the ring only
  moves while you can see it.
