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

# Resolve the repository before changing directories. The transcript writers
# use this same root to place their files directly in the vault.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT="$ROOT/Jarvis-brain"
LOG="$HOME/Library/Logs/jarvis-vault-backup.log"
mkdir -p "$(dirname "$LOG")"

say() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >> "$LOG"; }

cd "$VAULT" 2>/dev/null || { say "FAIL: no vault at $VAULT"; exit 1; }
[ -d .git ] || { say "FAIL: $VAULT is not a git repo"; exit 1; }

# TRANSCRIPTS LIVE IN THE VAULT. The writers append directly here, so there is
# one canonical copy and the normal vault commit below backs it up. Fail closed
# if the directory is missing: silently omitting the conversation record would
# make a successful backup claim false.
#
# VISIBLE ON PURPOSE. Serge wants the transcript files browsable in Obsidian.
# They are raw records rather than ordinary notes, so vault-audit.py explicitly
# excludes this folder from its index and frontmatter rules.
[ -d "$VAULT/Transcripts" ] || { say "FAIL: no canonical transcripts at
  $VAULT/Transcripts -- refusing to report an incomplete backup"; exit 1; }

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
