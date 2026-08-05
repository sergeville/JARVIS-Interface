#!/bin/zsh
# One-command Jarvis launcher.
#   ./start-jarvis.sh          -> Claude Code session at the Jarvis root
#   ./start-jarvis.sh visual   -> Claude Code session in Jarvis Visual/

if [[ "$1" == "visual" ]]; then
  cd "/Users/mike/Documents/Jarvis/Jarvis Visual" || exit 1
else
  cd "/Users/mike/Documents/Jarvis" || exit 1
fi

exec claude
