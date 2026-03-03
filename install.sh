#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/azamat1ch/yt-summary/main"

if [ "$1" = "--global" ]; then
  SKILL_DIR="$HOME/.claude/skills/summarize-youtube"
else
  SKILL_DIR=".claude/skills/summarize-youtube"
fi

echo "Installing summarize-youtube skill..."

mkdir -p "$SKILL_DIR/scripts"

curl -sSL "$REPO/SKILL.md" -o "$SKILL_DIR/SKILL.md"
curl -sSL "$REPO/scripts/prepare.py" -o "$SKILL_DIR/scripts/prepare.py"
chmod +x "$SKILL_DIR/scripts/prepare.py"

echo ""
echo "  Installed to $SKILL_DIR"
echo "  Restart Claude Code, then type /summarize-youtube to get started."
echo ""
echo "  Requires Python 3.10+. Dependencies auto-install on first run."
if [ "$1" != "--global" ]; then
  echo "  Use --global to install to ~/.claude/skills/ instead."
fi
