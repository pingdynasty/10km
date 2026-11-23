#!/usr/bin/env bash
# Install agent harnesses for the user, in ~/.local (the home volume), with each
# vendor's own installer:
#   docker/install-agent.sh [claude] [kiro] [codex]
# The names are the presets in tenkm/presets.py. A harness already on PATH is left
# alone. container-start runs it for AGENT; the image itself ships no harness, so
# each is downloaded under its own licence by whoever runs the container.
set -euo pipefail

for agent in "$@"; do  # check every name before installing any
  case "$agent" in
    claude|kiro|codex) ;;
    *) echo "install-agent: unknown agent: $agent (known: claude kiro codex)" >&2; exit 1 ;;
  esac
done

install_claude() {  # the native installer (checks the download's checksum)
  curl -fsSL https://claude.ai/install.sh | bash
}

install_kiro() {
  curl -fsSL https://cli.kiro.dev/install | bash
}

install_codex() {
  npm install -g --prefix "$HOME/.local" @openai/codex
}

command_of() {
  case "$1" in
    claude) echo claude ;;
    kiro) echo kiro-cli ;;
    codex) echo codex ;;
  esac
}

for agent in "$@"; do
  if command -v "$(command_of "$agent")" >/dev/null; then
    echo "install-agent: $agent is installed"
  else
    echo "install-agent: installing $agent in $HOME/.local"
    "install_$agent"
  fi
done
