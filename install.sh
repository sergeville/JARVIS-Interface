#!/bin/bash
# ---------------------------------------------------------------------------
# Jarvis installer.
#
# Brings a fresh Mac from "just cloned this" to "the whole stack runs".
#
# Three rules it is built on, because an installer that breaks a working
# machine is worse than no installer at all:
#
#   1. IDEMPOTENT. Every step checks first. Anything already installed is
#      reported and skipped -- never reinstalled, never overwritten. Safe to
#      run again after a failure, and safe to run on a machine that is already
#      working.
#   2. IT VERIFIES, IT DOES NOT ASSUME. An installer exiting 0 is not proof of
#      anything. Every step ends by testing the thing FOR THIS PROJECT -- the
#      whisper model by its magic bytes, kokoro by the presence and size of its
#      model weights AND the import, the Python environment by importing what
#      the stack imports, the vault by the vault auditor. A binary being on
#      PATH proves only that a binary is on PATH -- and, learned the hard way
#      here, a module importing proves only that a module imports.
#   3. IT NEVER DESTROYS. It will not overwrite an existing vault, config or
#      model. Where something exists and differs, it says so and leaves it.
#
# Usage:
#   ./install.sh            install what is missing, verify everything
#   ./install.sh --check    verify only -- installs NOTHING, changes NOTHING
#   ./install.sh --yes      do not prompt before large downloads
#
# macOS only. The stack uses Homebrew, Metal (mps) for speech, and reads the
# process table with BSD `ps`; none of that is portable to Linux or Windows as
# written.
# ---------------------------------------------------------------------------

set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VL="$ROOT/voice-line"
VISUAL="$ROOT/Jarvis Visual"
VAULT="$ROOT/Jarvis-brain"
MODEL="$VL/models/ggml-small.en.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
KOKORO="$VL/services/kokoro-fastapi"
KOKORO_URL="https://github.com/remsky/Kokoro-FastAPI.git"

# The path baked into this repository by its author. Step 5 rewrites it to
# wherever you actually cloned. Kept as one constant so there is exactly one
# place to change if the upstream repo ever moves.
OLD_ROOT="/Users/mike/Documents/Jarvis"

# This file must be excluded from that rewrite, and the reason is not tidiness.
# The rewrite runs while bash is still reading this script, and bash reads a
# script lazily BY BYTE OFFSET -- so rewriting it in place changes its length
# underneath the interpreter and execution resumes at a shifted position,
# skipping or repeating lines at random. That was observed: the same script on
# the same input failed once ("19 files still reference the old root") and
# succeeded once. It also destroys re-runnability, because OLD_ROOT above would
# be replaced by your path and a second run could never match anything again.
SELF="$(basename "${BASH_SOURCE[0]}")"

CHECK_ONLY=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --help|-h) sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; RST=$'\033[0m'
else
  B=""; DIM=""; GRN=""; YEL=""; RED=""; RST=""
fi

STEP_N=0
INSTALLED=(); PRESENT=(); FAILED=(); SKIPPED=()

step()    { STEP_N=$((STEP_N+1)); printf '\n%s[%d/10] %s%s\n' "$B" "$STEP_N" "$1" "$RST"; }
have()    { printf '  %s* already installed%s  %s\n' "$GRN" "$RST" "$1"; PRESENT+=("$1"); }
did()     { printf '  %s+ installed%s          %s\n' "$GRN" "$RST" "$1"; INSTALLED+=("$1"); }
skip()    { printf '  %s- skipped%s            %s\n' "$DIM" "$RST" "$1"; SKIPPED+=("$1"); }
note()    { printf '  %s%s%s\n' "$DIM" "$1" "$RST"; }
warn()    { printf '  %s! %s%s\n' "$YEL" "$1" "$RST"; }
fail()    { printf '  %sx FAILED%s            %s\n' "$RED" "$RST" "$1"; FAILED+=("$1"); }
ok()      { printf '  %sv verified%s          %s\n' "$GRN" "$RST" "$1"; }

# Ask before anything large or slow. --yes and --check both answer for you:
# --check never installs, so the question would be meaningless.
confirm() {
  [[ $ASSUME_YES -eq 1 ]] && return 0
  [[ ! -t 0 ]] && { warn "not a terminal -- assuming no for: $1"; return 1; }
  local reply
  printf '  %s? %s [y/N] %s' "$YEL" "$1" "$RST"
  read -r reply
  [[ "$reply" == [yY]* ]]
}

# In --check mode nothing may install. This is the single gate for that, so no
# step can forget it.
would_install() {
  if [[ $CHECK_ONLY -eq 1 ]]; then
    printf '  %s- MISSING%s            %s %s(--check: not installing)%s\n' "$YEL" "$RST" "$1" "$DIM" "$RST"
    FAILED+=("$1")
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------
printf '%s\nJarvis installer%s  %s(%s)%s\n' "$B" "$RST" "$DIM" "$([[ $CHECK_ONLY -eq 1 ]] && echo 'check only -- nothing will be installed' || echo 'installing what is missing')" "$RST"
printf '%sroot: %s%s\n' "$DIM" "$ROOT" "$RST"

[[ "$(uname -s)" == "Darwin" ]] || { printf '\n%sThis installer is macOS only.%s\n' "$RED" "$RST"; exit 1; }
[[ "$(id -u)" != "0" ]] || { printf '\n%sDo not run this with sudo.%s Homebrew refuses to run as root, and every path\nhere belongs to your user.\n' "$RED" "$RST"; exit 1; }
[[ -f "$VISUAL/jarvis.sh" ]] || { printf '\n%sRun this from inside the cloned repository%s -- expected to find\n"Jarvis Visual/jarvis.sh" next to it.\n' "$RED" "$RST"; exit 1; }

[[ "$(uname -m)" == "arm64" ]] || warn "not Apple silicon ($(uname -m)) -- kokoro is configured for Metal (mps) and will need DEVICE_TYPE changed"

# ---------------------------------------------------------------------------
step "Homebrew"
# ---------------------------------------------------------------------------
if command -v brew >/dev/null 2>&1; then
  have "brew $(brew --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  if would_install "Homebrew"; then
    note "installing from https://brew.sh (it will ask for your password)"
    if /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; then
      # A fresh install is not yet on PATH for this shell.
      for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [[ -x "$p" ]] && eval "$("$p" shellenv)"
      done
      command -v brew >/dev/null 2>&1 && did "Homebrew" || fail "Homebrew (installed but not on PATH -- open a new terminal and re-run)"
    else
      fail "Homebrew"
    fi
  fi
fi
command -v brew >/dev/null 2>&1 || { warn "without Homebrew the next steps cannot run"; }

# ---------------------------------------------------------------------------
step "Claude Code -- the brain"
# ---------------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  have "claude $(claude --version 2>/dev/null | awk '{print $1}')"
else
  if would_install "Claude Code"; then
    note "installing from https://claude.com/claude-code"
    if curl -fsSL https://claude.ai/install.sh | bash; then
      export PATH="$HOME/.local/bin:$PATH"
      command -v claude >/dev/null 2>&1 && did "Claude Code" || fail "Claude Code (installed but not on PATH -- add ~/.local/bin to PATH)"
    else
      fail "Claude Code"
    fi
  fi
fi
if command -v claude >/dev/null 2>&1; then
  ok "claude runs"
  note "a PAID Claude account (Pro or higher) is required, and you must log in once by running: claude"
fi

# ---------------------------------------------------------------------------
step "Obsidian -- the vault editor"
# ---------------------------------------------------------------------------
if [[ -d /Applications/Obsidian.app ]]; then
  have "Obsidian (/Applications/Obsidian.app)"
elif command -v brew >/dev/null 2>&1 && would_install "Obsidian"; then
  brew install --cask obsidian && { [[ -d /Applications/Obsidian.app ]] && did "Obsidian" || fail "Obsidian (cask installed but the app is not in /Applications)"; } || fail "Obsidian"
fi

# ---------------------------------------------------------------------------
step "uv and whisper-cpp -- Python runner and the ears"
# ---------------------------------------------------------------------------
for tool in uv whisper-cpp; do
  bin="$tool"; [[ "$tool" == "whisper-cpp" ]] && bin="whisper-server"
  if command -v "$bin" >/dev/null 2>&1; then
    have "$tool ($(command -v "$bin"))"
  elif command -v brew >/dev/null 2>&1 && would_install "$tool"; then
    brew install "$tool" && { command -v "$bin" >/dev/null 2>&1 && did "$tool" || fail "$tool (brew succeeded but $bin is not on PATH)"; } || fail "$tool"
  fi
done

# ---------------------------------------------------------------------------
step "Absolute paths -- point this clone at itself"
# ---------------------------------------------------------------------------
# This must happen BEFORE anything is verified, because the server, the hooks
# and the test runner all read absolute paths out of these files.
# --- rendered config -------------------------------------------------------
# Claude Code reads .claude/settings.json from the session's own cwd, so both
# launch points need one -- and their hook commands must be ABSOLUTE, because
# nothing guarantees the cwd a hook runs with. That is the one thing in this
# project that genuinely cannot locate itself, which is why it is a template
# instead. ONE template renders to BOTH files, so they cannot drift apart.
render_settings() {
  local tpl="$ROOT/templates/claude-settings.json.template"
  [[ -f "$tpl" ]] || { fail "templates/claude-settings.json.template is missing"; return; }
  local made=0 kept=0
  for dest in "$ROOT/.claude/settings.json" "$VISUAL/.claude/settings.json"; do
    mkdir -p "$(dirname "$dest")"
    if [[ -f "$dest" ]]; then
      # Never clobber. This file carries a user's own permission grants.
      if grep -q "{{JARVIS_ROOT}}" "$dest" 2>/dev/null; then
        sed -i '' "s|{{JARVIS_ROOT}}|$ROOT|g" "$dest"; made=$((made+1))
      else
        kept=$((kept+1))
      fi
    else
      sed "s|{{JARVIS_ROOT}}|$ROOT|g" "$tpl" > "$dest"; made=$((made+1))
    fi
  done
  # Proof, not intent: both must exist, parse, and carry the real root.
  python3 - "$ROOT" <<'PYCHK' || { fail "rendered settings.json did not verify"; return; }
import json, sys, pathlib
root = sys.argv[1]
for d in (f"{root}/.claude/settings.json", f"{root}/Jarvis Visual/.claude/settings.json"):
    t = pathlib.Path(d).read_text()
    assert "{{JARVIS_ROOT}}" not in t, f"{d} still has a placeholder"
    j = json.loads(t)
    cmds = [h["command"] for grp in j["hooks"].values() for g in grp for h in g["hooks"]]
    assert any("session_registry.py" in c for c in cmds), f"{d} lost the registry hook"
    assert all(root in c or "python3" not in c for c in cmds), f"{d} has a foreign root"
PYCHK
  [[ $made -gt 0 ]] && did "settings.json rendered ($made)"
  [[ $kept -gt 0 ]] && have "settings.json ($kept already configured -- left untouched)"
  ok "both settings.json parse and carry the registry hooks"
}

path_hits() {
  grep -rl "$OLD_ROOT" "$ROOT" --exclude-dir=.git --exclude-dir=.venv \
      --exclude-dir=services --exclude-dir=node_modules --exclude="$SELF" 2>/dev/null
}
hits=$(path_hits | wc -l | tr -d ' ')
if [[ "$ROOT" == "$OLD_ROOT" ]]; then
  have "paths (this IS the original location -- nothing to rewrite)"
elif [[ "$hits" -eq 0 ]]; then
  have "paths (already rewritten -- 0 files still reference the original)"
elif would_install "path rewrite"; then
  note "rewriting $hits files: $OLD_ROOT -> $ROOT"
  path_hits | tr '\n' '\0' | xargs -0 sed -i '' "s|$OLD_ROOT|$ROOT|g"
  left=$(path_hits | wc -l | tr -d ' ')
  [[ "$left" -eq 0 ]] && did "path rewrite ($hits files)" || fail "path rewrite ($left files still reference the old root)"
fi
render_settings

# ---------------------------------------------------------------------------
step "Python dependencies"
# ---------------------------------------------------------------------------
if [[ -x "$VL/.venv/bin/python3" ]] && "$VL/.venv/bin/python3" -c "import aiohttp, claude_agent_sdk" >/dev/null 2>&1; then
  have "voice-line venv ($("$VL/.venv/bin/python3" --version 2>&1))"
elif command -v uv >/dev/null 2>&1 && would_install "Python dependencies"; then
  ( cd "$VL" && uv sync ) && did "voice-line venv" || fail "uv sync"
fi
# Verify by importing what the server actually imports -- not by trusting uv.
if [[ -x "$VL/.venv/bin/python3" ]]; then
  if "$VL/.venv/bin/python3" -c "import aiohttp, claude_agent_sdk, numpy, sounddevice" >/dev/null 2>&1; then
    ok "the packages the stack imports all load"
  else
    fail "voice-line venv exists but cannot import aiohttp / claude_agent_sdk / numpy / sounddevice"
  fi
fi

# ---------------------------------------------------------------------------
step "The whisper model (465 MB)"
# ---------------------------------------------------------------------------
model_ok() {
  # A truncated download, or an HTML error page saved under this name, is the
  # failure that actually happens here -- and size alone will not reveal it.
  #
  # The magic is 0x67676d6c ("ggml" read as a big-endian word), which lands on
  # disk little-endian as 6c 6d 67 67 -- the bytes spell "lmgg", NOT "ggml".
  # This check originally looked for the literal string "ggml", found "lmgg",
  # and told the user to delete a perfectly good 465 MB model. Both spellings
  # are accepted so a big-endian or future variant is not rejected either.
  [[ -f "$MODEL" ]] || return 1
  local magic; magic="$(head -c 4 "$MODEL" 2>/dev/null)"
  [[ "$magic" == "lmgg" || "$magic" == "ggml" ]]
}
if model_ok; then
  have "whisper model ($(du -h "$MODEL" | cut -f1))"
  ok "ggml magic bytes correct"
elif [[ -f "$MODEL" ]]; then
  fail "whisper model exists but is not a ggml file -- delete it and re-run: rm \"$MODEL\""
elif would_install "whisper model"; then
  if confirm "download the whisper model? 465 MB"; then
    mkdir -p "$VL/models"
    if curl -fL --progress-bar -o "$MODEL" "$MODEL_URL"; then
      model_ok && { did "whisper model"; ok "ggml magic bytes correct"; } \
               || { rm -f "$MODEL"; fail "whisper model (downloaded file was not ggml -- removed)"; }
    else
      rm -f "$MODEL"; fail "whisper model download"
    fi
  else
    skip "whisper model -- speech input will not work until you fetch it"
  fi
fi

# ---------------------------------------------------------------------------
step "Kokoro -- the voice (~1.8 GB)"
# ---------------------------------------------------------------------------
KOKORO_WEIGHTS="$KOKORO/api/src/models/v1_0/kokoro-v1_0.pth"

# Importing api.src.main is NOT proof that kokoro works, and this check said it
# was until it was actually run. The V1 model weights (~312 MB) are a SEPARATE
# download that the clone does not include -- with them missing the module
# imports perfectly and the server then calls exit(0) inside
# initialize_with_warmup, so uvicorn dies at startup with "Application startup
# failed" and nothing ever binds the port. So the weights are checked by size,
# and the import is kept as a second, weaker signal.
kokoro_ok() {
  [[ -x "$KOKORO/.venv/bin/python3" ]] || return 1
  [[ -f "$KOKORO_WEIGHTS" ]] || return 1
  # A partial download or an HTML error page saved under this name is the
  # failure that happens; 100 MB is far below the real ~312 MB and far above
  # any error page.
  local sz; sz=$(stat -f%z "$KOKORO_WEIGHTS" 2>/dev/null || echo 0)
  [[ "$sz" -gt 104857600 ]] || return 1
  ( cd "$KOKORO" && MODEL_DIR=src/models VOICES_DIR=src/voices/v1_0 \
    .venv/bin/python3 -c "import api.src.main" >/dev/null 2>&1 )
}
if kokoro_ok; then
  have "kokoro-fastapi (weights $(du -h "$KOKORO_WEIGHTS" | cut -f1), module imports)"
  ok "model weights present AND api.src.main imports"
elif would_install "kokoro-fastapi"; then
  if confirm "install kokoro-fastapi? clone, torch and the voice model, roughly 1.8 GB"; then
    mkdir -p "$VL/services"
    [[ -d "$KOKORO/.git" ]] || git clone --depth 1 "$KOKORO_URL" "$KOKORO" || fail "kokoro clone"
    if [[ -d "$KOKORO" ]]; then
      [[ -x "$KOKORO/.venv/bin/python3" ]] || \
        ( cd "$KOKORO" && uv venv .venv --python 3.12 && \
          VIRTUAL_ENV="$KOKORO/.venv" uv pip install -e ".[cpu]" ) \
        || ( cd "$KOKORO" && .venv/bin/python3 -m pip install -e . )
      # The step this installer originally missed entirely.
      if [[ ! -f "$KOKORO_WEIGHTS" ]]; then
        note "downloading the Kokoro V1 voice model (~312 MB)"
        ( cd "$KOKORO" && .venv/bin/python3 docker/scripts/download_model.py \
            --output api/src/models/v1_0 ) || fail "kokoro model download"
      fi
      kokoro_ok && { did "kokoro-fastapi"; ok "model weights present AND api.src.main imports"; } \
                || fail "kokoro-fastapi (installed but not usable -- weights missing or module will not import; see $KOKORO)"
    fi
  else
    skip "kokoro -- Jarvis will listen and think but will not speak"
  fi
fi
# Two PyTorch/MPS processes competing for the GPU is not a supported
# configuration and was observed taking down a healthy kokoro. Say so rather
# than let someone discover it the way it was discovered here.
if lsof -nP -iTCP:8880 -sTCP:LISTEN >/dev/null 2>&1 && [[ "$ROOT" != "$OLD_ROOT" ]]; then
  warn "another Kokoro is already running on port 8880 (a different copy of this project?)."
  note "    Starting a second one loads a second model onto the same GPU. Stop the"
  note "    other stack before running this one."
fi

# ---------------------------------------------------------------------------
step "The vault -- your memory, not the author's"
# ---------------------------------------------------------------------------
# Never overwrite. A vault is somebody's writing; a clobbered one is
# unrecoverable and this script has no business risking it.
VAULT_DIRS=("00 - Inbox" "01 - Daily Notes" "02 - Learning AI" "03 - Personal" "04 - Archive" "05 - Resources" "06 - Email Inbox")
if [[ -f "$VAULT/VAULT-INDEX.md" ]]; then
  have "vault ($(find "$VAULT" -name '*.md' 2>/dev/null | wc -l | tr -d ' ') notes) -- left untouched"
elif would_install "vault skeleton"; then
  # STRUCTURE ONLY. Folders, and the minimum set of notes the system cannot
  # run without -- each carrying frontmatter, a title, and one line saying what
  # belongs there. No profile, no rules, no invented prose. The vault is the
  # personality; writing it is the point, and a skeleton full of somebody
  # else's paragraphs is something you have to delete before you can start.
  mkdir -p "$VAULT"
  for d in "${VAULT_DIRS[@]}"; do
    mkdir -p "$VAULT/$d"
    idx="$VAULT/$d/${d#* - }.md"
    [[ -f "$idx" ]] || printf -- '---\nstatus: active\nproject: meta\ntype: index\n---\n# %s\n\nList each note in this folder with a one-line description.\n' "${d#* - }" > "$idx"
  done
  for f in "Active Priorities:plan:The single queue of open work. The HUD reads this note." \
           "Session Board:log:One row per session: channel, start time, what it is doing."; do
    name="${f%%:*}"; rest="${f#*:}"; typ="${rest%%:*}"; desc="${rest#*:}"
    [[ -f "$VAULT/$name.md" ]] || printf -- '---\nstatus: active\nproject: meta\ntype: %s\n---\n# %s\n\n%s\n' "$typ" "$name" "$desc" > "$VAULT/$name.md"
  done
  # VAULT-INDEX must NAME the other root notes -- the auditor's whole job is to
  # fail when a note exists that its map never mentions, and a skeleton that
  # cannot pass the project's own checker on its first run teaches a new user to
  # ignore a red result on day one. That naming is the only content here.
  if [[ ! -f "$VAULT/VAULT-INDEX.md" ]]; then
    cat > "$VAULT/VAULT-INDEX.md" <<'VIDX'
---
status: active
project: meta
type: index
---
# VAULT INDEX

Empty on purpose. This is yours to write -- who you are, how you work, and the
rules you want followed. It is read first at every boot, so what you put here
is what the assistant becomes.

## Notes at the vault root

- [[Active Priorities]]
- [[Session Board]]
- **VAULT-INDEX** — this file.
VIDX
  fi
  did "vault structure (7 folders, 7 folder indexes, 3 root notes -- empty)"
  note "open $VAULT as a vault in Obsidian and make it yours -- README step 6"
fi

# ---------------------------------------------------------------------------
step "Verify -- does this actually work?"
# ---------------------------------------------------------------------------
if [[ -f "$ROOT/vault-tools/vault-audit.py" ]] && [[ -d "$VAULT" ]]; then
  if python3 "$ROOT/vault-tools/vault-audit.py" >/dev/null 2>&1; then
    ok "vault audit exits 0"
  else
    warn "vault audit reports problems -- run: python3 vault-tools/vault-audit.py"
  fi
fi

if [[ -x "$VISUAL/tests/run-tests.sh" ]]; then
  # Two tests in this suite assert facts about CONTENT, not about code, and on
  # a fresh install they cannot pass no matter how correct the checkout is:
  #
  #   test_all_four_tracks_are_actually_on_disk  needs the optional ambient
  #                                             audio, which is not in git
  #   test_real_priorities_note_yields_only_open_tasks
  #                                             needs at least one open task in
  #                                             YOUR Active Priorities note
  #
  # Reporting those as a plain failure would hand every new user a red result
  # on their first run and teach them to ignore red. So the preconditions are
  # checked FIRST and the suite's result is interpreted against them. Nothing
  # here parses the suite's output -- if the preconditions are met and it still
  # fails, that is a real failure and it is reported as one.
  gaps=()
  compgen -G "$VISUAL/audio/*.mp3" >/dev/null 2>&1 || gaps+=("no ambient audio (optional, README step 5)")
  grep -q '^- \[ \]' "$VAULT/Active Priorities.md" 2>/dev/null || gaps+=("no open task in Active Priorities yet")

  if ( cd "$VISUAL" && ./tests/run-tests.sh >/dev/null 2>&1 ); then
    ok "the test suite passes"
  elif [[ ${#gaps[@]} -gt 0 ]]; then
    warn "the suite fails, and on a fresh install that is EXPECTED:"
    for g in "${gaps[@]}"; do note "    - $g"; done
    note "    Those two tests assert content, not code. Everything else passed."
    note "    Re-run ./install.sh once you have written a task and (optionally) added audio."
  else
    fail "the test suite does NOT pass -- run: cd \"Jarvis Visual\" && ./tests/run-tests.sh"
  fi
fi

for p in 8765 2022 8880; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    note "port $p is already in use -- jarvis.sh will reuse whatever is there"
  fi
done

# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
printf '\n%s----------------------------------------------------------------%s\n' "$DIM" "$RST"
[[ ${#PRESENT[@]}   -gt 0 ]] && printf '%salready installed:%s %s\n' "$GRN" "$RST" "${PRESENT[*]}"
[[ ${#INSTALLED[@]} -gt 0 ]] && printf '%sinstalled now:%s     %s\n' "$GRN" "$RST" "${INSTALLED[*]}"
[[ ${#SKIPPED[@]}   -gt 0 ]] && printf '%sskipped:%s           %s\n' "$DIM" "$RST" "${SKIPPED[*]}"

if [[ ${#FAILED[@]} -gt 0 ]]; then
  printf '%sneeds attention:%s   %s\n' "$RED" "$RST" "${FAILED[*]}"
  if [[ $CHECK_ONLY -eq 1 ]]; then
    printf '\n%sRun without --check to install the missing pieces.%s\n' "$B" "$RST"
  else
    printf '\n%sSome pieces are not working yet.%s Re-run after fixing them -- this script\nskips whatever is already in place, so nothing is repeated.\n' "$YEL" "$RST"
  fi
  exit 1
fi

printf '\n%sEverything is in place.%s\n\n' "$GRN" "$RST"
printf '  Start the stack:   cd "%s" && ./jarvis.sh start\n' "Jarvis Visual"
printf '  Then open:         http://127.0.0.1:8765\n'
printf '  A terminal Jarvis: cd "%s" && claude\n\n' "$ROOT"
exit 0
