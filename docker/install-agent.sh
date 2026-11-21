#!/usr/bin/env bash
# Install agent harnesses into the image, system-wide, so a new image brings new
# versions (the home directory is a volume):
#   docker/install-agent.sh [claude] [kiro] [codex]
# The names are the presets in tenkm/presets.py. No names: install none.
set -euo pipefail

CLAUDE_KEY_FINGERPRINT=31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE

apt_install() {
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$@"
}

install_claude() {  # the signed apt repository, stable channel
  apt_install ca-certificates curl gnupg
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o /etc/apt/keyrings/claude-code.asc
  fingerprint=$(gpg --show-keys --with-colons /etc/apt/keyrings/claude-code.asc \
                | awk -F: '/^fpr/ { print $10; exit }')
  if [ "$fingerprint" != "$CLAUDE_KEY_FINGERPRINT" ]; then
    echo "install-agent: unexpected Claude Code key fingerprint: $fingerprint" >&2
    exit 1
  fi
  echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" \
    > /etc/apt/sources.list.d/claude-code.list
  apt_install claude-code
}

install_kiro() {  # its installer writes to ~/.local/bin: give it a home in /opt
  apt_install ca-certificates curl unzip
  mkdir -p /opt/kiro-cli
  HOME=/opt/kiro-cli bash -c 'curl -fsSL https://cli.kiro.dev/install | bash'
  ln -sf /opt/kiro-cli/.local/bin/kiro-cli /usr/local/bin/kiro-cli
}

install_codex() {
  apt_install ca-certificates nodejs npm
  npm install -g @openai/codex
}

for agent in "$@"; do  # check every name before installing any
  case "$agent" in
    claude|kiro|codex) ;;
    *) echo "install-agent: unknown agent: $agent (known: claude kiro codex)" >&2; exit 1 ;;
  esac
done
for agent in "$@"; do
  case "$agent" in
    claude) install_claude ;;
    kiro) install_kiro ;;
    codex) install_codex ;;
  esac
done
rm -rf /var/lib/apt/lists/*
