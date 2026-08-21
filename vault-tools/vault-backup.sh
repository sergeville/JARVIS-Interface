#!/usr/bin/env bash
# Commit and push the Jarvis brain. Run every 15 minutes by launchd.
#
# WHY THIS IS NOT THE OBSIDIAN GIT PLUGIN. Serge's main vault is pushed by
# that plugin (`.obsidian/plugins/obsidian-git/data.json`, autoPushInterval
# 15). Winston checked its commit log on 2026-08-21 and the gaps tell the
# story: 09:52, then nothing until 15:23. The plugin only runs WHILE OBSIDIAN
# HAS THE VAULT OPEN. That is not a backup, it is a backup that agrees to
# work when someone is already looking.
#
# This vault was lost precisely because it existed in one place. So the job
# that protects it must not depend on an app being open, and launchd runs
# whether anyone is at the desk or not.
#
# THE COMMIT GOES THROUGH THE PRE-COMMIT HOOK ON PURPOSE -- no --no-verify
# anywhere in here. `06 - Email Inbox/` is written automatically from real
# Gmail, so the one thing this job must never do is push a credential at
# 15-minute intervals with nobody reading. If the hook refuses, THIS JOB
# FAILS LOUDLY AND STOPS rather than working around it.
set -uo pipefail

# RESOLVED BEFORE ANY `cd`. The first version computed the transcript source
# from $BASH_SOURCE *after* cd'ing into the vault, so the relative path no
# longer resolved -- and because the mirror was guarded by `if [ -d "$SRC" ]`,
# it SKIPPED SILENTLY and the run still logged "backed up". A backup that
# reports success while omitting the thing it was just asked to protect is
# the worst outcome available, so both halves are fixed: paths resolve up
# front, and a missing source is now a failure, not a shrug.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT="$ROOT/Jarvis-brain"
LOG="$HOME/Library/Logs/jarvis-vault-backup.log"
mkdir -p "$(dirname "$LOG")"

say() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >> "$LOG"; }

cd "$VAULT" 2>/dev/null || { say "FAIL: no vault at $VAULT"; exit 1; }
[ -d .git ] || { say "FAIL: $VAULT is not a git repo"; exit 1; }

# MIRROR THE VOICE TRANSCRIPTS IN. (Serge, 2026-08-21 ~17:45.)
#
# They live in `Jarvis Visual/transcripts/`, which is inside the PUBLIC repo's
# tree and gitignored there -- correctly, they are verbatim recordings of a
# person. So they had no backup at all: eight days of conversation existing
# once, on one disk. That is the same shape as the failure that lost this
# whole vault two days ago.
#
# Copied rather than symlinked, deliberately -- a symlink would resolve back
# into the public repo's tree, and this project already reviewed and rejected
# symlinking across that boundary ([[Vault Merge — Winston's Review]]).
#
# --archive --delete keeps the mirror honest: a transcript deleted upstream
# disappears here too, so this never becomes a place stale copies accumulate
# unnoticed. Git history still holds every version that was ever committed.
SRC="$ROOT/Jarvis Visual/transcripts"
[ -d "$SRC" ] || { say "FAIL: no transcript source at $SRC -- refusing to back up
  the vault without it, because a silent skip here looks exactly like success"; exit 1; }
# DOT-FOLDER ON PURPOSE. As plain `transcripts/` the mirror is vault content:
# `vault-audit.py` reported "missing index" and "no frontmatter" on it, and
# Obsidian would index a day of raw conversation as notes. The obvious fix --
# drop a `transcripts.md` index inside -- gets wiped by `--delete` on the next
# run, so it would break itself. A leading dot makes both tools skip it while
# git tracks it exactly the same.
mkdir -p "$VAULT/.transcripts"
rsync -a --delete "$SRC/" "$VAULT/.transcripts/" \
  || { say "FAIL: transcript mirror (rsync)"; exit 1; }

# Nothing to do is the common case and must stay silent, or the log becomes
# 96 lines a day of "no changes" and nobody reads the one line that matters.
if [ -z "$(git status --porcelain)" ]; then
  exit 0
fi

git add -A || { say "FAIL: git add"; exit 1; }

if ! out=$(git -c user.name="Jarvis" -c user.email="villeneuve.serge@gmail.com" \
             commit -m "vault backup: $(date '+%Y-%m-%d %H:%M:%S')" 2>&1); then
  # THE IMPORTANT BRANCH. A refusal here is almost certainly the secret gate,
  # which means something credential-shaped is sitting in the vault RIGHT NOW
  # and every future run will fail too until a human looks.
  say "REFUSED -- commit blocked, vault NOT backed up. Output follows:"
  say "$out"
  exit 1
fi

# pullBeforePush is deliberately absent here, unlike the plugin's config
# (which sets it false and would wedge silently on a non-fast-forward). This
# is a single-machine vault; if a push is ever rejected, that is a real
# divergence and it should be seen, not auto-merged.
if ! out=$(git push origin HEAD 2>&1); then
  say "FAIL: push rejected -- committed locally but NOT off this machine:"
  say "$out"
  exit 1
fi

say "backed up: $(git log --oneline -1)"
