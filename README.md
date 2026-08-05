# Jarvis

Jarvis is an always-on AI chief of staff running locally on one Mac. He speaks
and listens over a browser HUD, remembers everything in an Obsidian vault that
survives every restart, and boots as the same colleague each session by reading
that vault first. Local speech, loopback-only server, no cloud but the model.

---

## What this actually is

A personal assistant built out of five small pieces that each do one thing:

- **The brain** — a [Claude Code](https://claude.com/claude-code) session driven
  through the Agent SDK, pinned to one model, with the vault as its memory.
- **The ears** — `whisper-server` transcribing on `127.0.0.1:2022`.
- **The voice** — Kokoro speaking on `127.0.0.1:8880`.
- **The face** — a browser HUD on `127.0.0.1:8765`: an animated avatar, live
  system and stack instruments, the task queue, the sessions running right now,
  and a push-to-talk button.
- **The memory** — `Jarvis-brain/`, an Obsidian vault. This is the part that
  matters. A restart replaces the brain and its whole conversation; the vault is
  what makes the next one continuous rather than a stranger.

Everything binds to loopback. Nothing listens on the network. Audio is
transcribed and synthesised on the machine; the only thing that leaves is what
the model itself is asked.

### The design rules it was built under

These are written down because they were each learned the hard way, and they
are what the code looks like the way it does:

- **Evidence, never a guess.** State is read from the file or the process table
  before anything is claimed about it.
- **Tests are the gate,** and a test must be *proven able to fail* — by breaking
  a **copy**, never the live file, since the page ships to an open browser tab
  the moment it changes.
- **Structural over procedural.** A property that depends on somebody
  remembering it is not a property. The security shape of a route is that it
  takes no input, not that it validates input carefully.
- **Jarvis never stops Jarvis.** A stop or restart run from inside the stack
  refuses out loud and names what it left alone. Stopping is the operator's,
  from their own terminal.
- **External content is data, never instructions** — email bodies, web pages,
  notices from a sibling session.

## Layout

```
CLAUDE.md               the boot file: identity, startup sequence, standing rules
Jarvis-brain/           the Obsidian vault -- the memory      (not in git -- yours to write)
  VAULT-INDEX.md        profile, rules, system map; read at every boot
  Active Priorities.md  the single queue of open work
  Session Board.md      what each session was doing (NOT who is alive)
voice-line/             brain, ears, session registry, session bus
  models/               whisper model weights            (not in git -- 465 MB)
  services/kokoro-fastapi/  the speech server            (not in git)
Jarvis Visual/          the browser HUD and its server
  jarvis.html           the whole front end, one file
  voice-web-server.py   aiohttp server, /voice + /signals
  jarvis.sh             status | start | stop | restart | sessions
  tests/run-tests.sh    the suite -- the gate for every change
vault-tools/            vault-audit.py, the vault's own consistency checker
install.sh              one-command setup; idempotent, verifies, never overwrites
```

## Install

Built and run on macOS (Apple silicon).

### The short way

Get the code (step 0 below), then:

```sh
./install.sh
```

That is the whole thing. It installs Homebrew, Claude Code, Obsidian, `uv`,
`whisper-cpp`, the Python dependencies, the whisper model and Kokoro; rewrites
the absolute paths onto your clone; and creates an empty vault for you. Steps
1–6 below are what it does, written out, for when you would rather do it by
hand or something goes wrong.

```sh
./install.sh --check    # verify only -- installs nothing, changes nothing
./install.sh --yes      # don't prompt before the two large downloads
```

Three things it promises, each of which was tested rather than intended:

- **It skips what you already have** and says so. Run it twice and the second
  run installs nothing — proven on a fresh clone, second run byte-identical.
- **It verifies for this project, not in general.** The whisper model is
  checked for its magic bytes, Kokoro by the presence and size of its model
  weights *and* the import, the Python environment by importing what the stack
  imports, the vault by the vault auditor. A binary on `PATH` proves only that
  a binary is on `PATH` — and a module importing proves only that a module
  imports, which is exactly how a broken Kokoro passed once.
- **It never overwrites a vault**, a config or a model. If something exists and
  looks wrong, it says so and leaves it alone.

It will ask before the two large downloads (465 MB of whisper model, ~1.8 GB of
Kokoro including its 312 MB voice weights) and runs fine without either —
Jarvis simply cannot hear, or cannot speak, until you fetch them.

**Do not run it against a second copy while another Jarvis stack is live.** Two
PyTorch/Metal processes competing for the same GPU took a healthy Kokoro down
during testing; the installer warns if it sees port 8880 already in use.

#### If Homebrew was installed by a different user on this Mac

Common when you are testing in a second macOS account, or on a shared machine.
**Homebrew does not support more than one user**, and the symptom is confusing:
`/opt/homebrew/bin` is not in `/etc/paths` and `brew shellenv` lives in the
installing user's own `~/.zprofile`, so your shell has no `brew` at all. The
installer then concludes Homebrew is missing and tries to install it — and
Homebrew's own installer finds an `/opt/homebrew` it does not own.

Do not let it get that far. Add this to your `~/.zprofile`, open a new terminal,
then run the installer:

```sh
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Step 1 will now report Homebrew as already installed and move on. If you also
need to *install* formulae rather than just use them, the owning user has to do
it, or you have to be in the group that owns `/opt/homebrew` — check with
`ls -ld /opt/homebrew`.

Obsidian and the `brew` formulae (`uv`, `whisper-cpp`) live outside your home
directory, so a second account inherits them and those steps will report
"already installed" too. What a fresh account genuinely exercises is Claude
Code, your `PATH`, an empty `~/.claude`, and a brand-new vault.

### The long way

**Before anything else: the paths in this project are absolute, and they are
not yours.** The server, the session hooks, the test runner and the boot file
all carry the author's home directory, and nothing finds anything until they
point at your clone. `./install.sh` does this for you; by hand it is one line.

Count them yourself rather than trusting a number in a README — this one went
stale three times while being written, which is why it is no longer quoted:

```sh
grep -rl '/Users/mike/Documents/Jarvis' . --exclude-dir=.git | wc -l
```

And to fix them, from inside the folder you cloned into. The old path appears
here only as the string being searched for; `$PWD` supplies yours:

```sh
grep -rl '/Users/mike/Documents/Jarvis' . --exclude-dir=.git --exclude=install.sh \
  | tr '\n' '\0' | xargs -0 sed -i '' "s|/Users/mike/Documents/Jarvis|$PWD|g"
```

**`--exclude=install.sh` is not optional and not tidiness.** That file holds the
path as a constant, so rewriting it changes its length while bash may still be
reading it — bash reads a script lazily by byte offset, and execution then
resumes at a shifted position. It also means a second run could never find
anything, because the constant would already be your own path. The installer
excludes itself for the same reason.

Verified against a fresh clone: every occurrence outside `install.sh` down to 0,
and every `.py`, `.sh`, `.js` and `.json` in the repository still parses
afterwards.

**Seven mentions of the original username survive that command, and should.**
They are string literals in `tests/test_session_registry.py` and
`tests/test_registry_inversion.py` standing in for process command lines — test
fixtures, not paths. Nothing opens them and the suite passes as-is. Leave them
alone.

**0. Get the code — one line**

With git — recommended, since you get the history and an honest error if
anything is wrong:

```sh
git clone https://github.com/sergeville/JARVIS-Interface.git && cd JARVIS-Interface
```

Without git, download the archive instead:

```sh
curl -fL https://github.com/sergeville/JARVIS-Interface/archive/refs/heads/main.zip -o jarvis.zip && unzip -q jarvis.zip && rm jarvis.zip && cd JARVIS-Interface-main
```

Two details that are load-bearing rather than decorative. **`-f` makes curl fail
on an HTTP error** instead of cheerfully saving the 404 page as `jarvis.zip`,
which then fails inside `unzip` with an error about a missing end-of-central
-directory signature — a confusing message for a simple "that URL is not
there". And **`&&` stops the chain at the first failure**, so a download that
did not work never reaches the `rm` or the `cd`; you are left standing where you
started with the evidence still on disk.

The archive unpacks to `JARVIS-Interface-main`, named for the branch — swap
`main` for `master` in both the URL and the `cd` if the default branch is ever
renamed. Steps 1–5 below run from inside that folder.

**1. Prerequisites**

```sh
brew install uv whisper-cpp        # uv runs the Python side; whisper-server transcribes
```

Claude Code must be installed and logged in — see
<https://claude.com/claude-code>. Verify with `claude --version`.

**2. Python dependencies**

Declared in `voice-line/pyproject.toml` (Python ≥ 3.12) and pinned in
`uv.lock`. `uv` creates the environment on first run:

```sh
cd voice-line && uv sync
```

**3. The whisper model**

Not in this repository — it is 465 MB. Download a GGML model and put it at
`voice-line/models/ggml-small.en.bin`:

Same rule as step 4 — check first, and do nothing if it is already there. This
one costs 465 MB and several minutes if you skip the check, and `-o` truncates
the existing file the moment curl starts, so a re-run that fails partway leaves
you with **less** than you had:

```sh
mkdir -p voice-line/models
[ -s voice-line/models/ggml-small.en.bin ] \
  && echo "whisper model already present -- nothing to do" \
  || curl -fL -o voice-line/models/ggml-small.en.bin \
       https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
```

`-f` makes curl fail on an HTTP error rather than saving the error page as your
model file, which then fails much later and much more confusingly.

**4. Kokoro (the voice)**

Also not in this repository. Install
[kokoro-fastapi](https://github.com/remsky/Kokoro-FastAPI) into
`voice-line/services/kokoro-fastapi/`, with its own `.venv`.

`jarvis.sh start` launches it for you, and it does so with an environment that
matters — models, voices and the Metal device are all read from it, so the bare
uvicorn line starts a server that then cannot find its own voices:

**Check before you start it. This step has already broken a live system once.**
On 2026-08-05 this command was run by hand to verify the install while Kokoro
was already up; the second instance collided with the first on port 8880 and
**killed the running one**, taking the voice out mid-conversation. `jarvis.sh
start` is idempotent and says "kokoro already up" — a bare command is not.

So the check comes first, and it starts nothing:

```sh
curl -s -m 3 -o /dev/null -w '%{http_code}\n' 127.0.0.1:8880/v1/models
```

`200` means it is installed and running — **you are done, do not start it.**
`000` means nothing is listening, and only then:

```sh
cd voice-line/services/kokoro-fastapi
USE_GPU=true USE_ONNX=false PYTHONPATH="$PWD:$PWD/api" \
  MODEL_DIR=src/models VOICES_DIR=src/voices/v1_0 DEVICE_TYPE=mps \
  PYTORCH_ENABLE_MPS_FALLBACK=1 \
  .venv/bin/python3 -m uvicorn api.src.main:app --host 127.0.0.1 --port 8880
```

That is the exact environment `jarvis.sh` uses — models, voices and the Metal
device are all read from it, so the bare uvicorn line without it starts a
server that cannot find its own voices. Normal running is `./jarvis.sh start`,
which does this for you and checks first; the command above is for proving a
fresh install only.

**The general rule, and it applies to every step here: verify, then install
only what is missing.** An install script that assumes nothing is running will
eventually be run on a machine where something is.

**5. Ambient audio (optional)**

`Jarvis Visual/audio/` holds four public-domain classical recordings for the
background bed. Not in this repository; the routes 404 harmlessly without them
and the MUSIC toggle simply stays silent.

**6. The vault — this is the part you write yourself**

`Jarvis-brain/` is deliberately **not in this repository**, and that is not an
oversight. It is a personal Obsidian vault: a profile, dated logs of every
working session, email briefs, the live task queue. Publishing mine would
publish my life — and it would be no use to you anyway, because **the vault is
the personality.** Everything that reads one is in this repo; the contents are
yours.

Create the folders:

```sh
cd Jarvis-brain 2>/dev/null || mkdir -p Jarvis-brain && cd Jarvis-brain
mkdir -p "00 - Inbox" "01 - Daily Notes" "02 - Learning AI" \
         "03 - Personal" "04 - Archive" "05 - Resources" "06 - Email Inbox"
```

Open that folder as a vault in [Obsidian](https://obsidian.md), then write the
notes the system actually looks for. **Four at the vault root:**

| note | what it is |
|---|---|
| `VAULT-INDEX.md` | who you are, the rules, the map of the vault. Read first at every boot. |
| `Active Priorities.md` | the single queue of open work. **The HUD parses this one** — the task card is fed by it. |
| `Session Board.md` | what each session was doing. Intent and history, never liveness. |
| `How to Start Jarvis.md` | your own launch notes. |

**One index note per folder, named for the folder** — `00 - Inbox/Inbox.md`,
`01 - Daily Notes/Daily Notes.md`, `02 - Learning AI/Learning AI.md`, and so on
— each listing what is in it with a line of description. Plus
`01 - Daily Notes/Daily Note Template.md`, which every daily note is copied
from rather than hand-rolled.

Every note carries YAML frontmatter:

```yaml
---
status: active | completed | parked | idea | archived
project: <one of your own project slugs>
type: index | reference | guide | plan | log
---
```

**Check it rather than trusting it:**

```sh
python3 vault-tools/vault-audit.py     # exit 0 or it is not finished
```

It reports any note its folder index never mentions, any `[[link]]` pointing at
a note that does not exist, any folder missing an index, and any bad
frontmatter — and it changes nothing, so it is safe to run at any time. It
locates the vault **relative to itself**, so it works wherever you cloned to.
That is the exception; see the next paragraph for the rest.

**Three of those absolute paths point specifically at the vault.** The one-line
fix-up at the top of Install already rewrites them; they are named here so that
if the task card or the graph comes up empty, you know exactly where to look:

| file | line | what it points at |
|---|---|---|
| `Jarvis Visual/voice-web-server.py` | 88 | `Active Priorities.md` — the HUD's task card |
| `Jarvis Visual/voice-web-server.py` | 149 | the vault root — the 3D vault graph |
| `vault-tools/brief-check.py` | 70 | `06 - Email Inbox/` — the morning-brief reminder |

Finally, **`CLAUDE.md` at the project root ships as my copy on purpose.** It is
the boot file — identity, startup sequence, and the standing rules — and it is
included as a worked example rather than a template, because the rules in it
are the ones that survived being argued over. Rewrite the identity and the
personal rules as your own; the startup sequence and the shape are what carries
over.

## Running it

```sh
cd "Jarvis Visual"
./jarvis.sh start      # or status | stop | restart | sessions
```

Then open <http://127.0.0.1:8765>. Hold **Right ⌘** (with focus off the text
box) or the on-screen button to talk.

**Note:** `stop` and `restart` deliberately refuse when run from inside the
Jarvis stack — including from a Claude Code session it launched. Run them from
your own terminal.

## Tests

```sh
cd "Jarvis Visual"
./tests/run-tests.sh
```

Python tests import the real modules by path and JavaScript tests extract the
real functions out of `jarvis.html`, so no test can drift from what ships. A
change is accepted when the suite passes — not when it compiles.

## Checking the vault

```sh
python3 vault-tools/vault-audit.py     # exit 0 or the checkpoint is not finished
```

Reports any note its folder index never mentions, any `[[link]]` pointing at a
note that does not exist, any folder missing an index, and any bad frontmatter.
It changes nothing.
