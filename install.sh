#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/claude-code-sandbox"
CONFIG_FILE="$CONFIG_DIR/config.toml"
IMAGE="claude-code-sandbox:latest"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}==>${NC} $1"; }
warn()  { echo -e "${YELLOW}warning:${NC} $1"; }
error() { echo -e "${RED}error:${NC} $1" >&2; exit 1; }

info "Checking dependencies..."
command -v docker &>/dev/null || error "Docker is not installed. On macOS install Colima (https://github.com/abiosoft/colima). On Linux install Docker."
command -v python3 &>/dev/null || error "Python 3.11+ is required."
python3 -c "import tomllib" 2>/dev/null || error "Python 3.11+ is required (tomllib missing)."
python3 -c "import yaml" 2>/dev/null || pip install pyyaml -q || error "Failed to install pyyaml. Run: pip install pyyaml"

info "Building container image..."
if [[ "$(uname)" == "Darwin" ]]; then
    CSB_SOCKET="$HOME/.colima/csb/docker.sock"
    if [ ! -S "$CSB_SOCKET" ]; then
        echo ""
        echo -e "${RED}error:${NC} Colima 'csb' instance not found."
        echo ""
        echo "    Create it with your workspace directories and session storage mounted, then re-run install:"
        echo ""
        echo "    colima start csb --cpu 4 --memory 4 --disk 20 \\"
        echo "      --mount ~/.local/share/claude-code-sandbox:w \\"
        echo "      --mount ~/src/my-project:w \\"
        echo "      --mount ~/src/another-project:w"
        echo ""
        exit 1
    fi
    DOCKER_HOST="unix://$CSB_SOCKET" docker build -f "$REPO_DIR/Containerfile" -t "$IMAGE" "$REPO_DIR"
else
    docker build -f "$REPO_DIR/Containerfile" -t "$IMAGE" "$REPO_DIR"
fi

info "Removing existing sandbox container..."
DOCKER_HOST="unix://$HOME/.colima/csb/docker.sock" docker rm -f claude-sandbox 2>/dev/null || true

info "Installing csb and csb-daemon to $BIN_DIR..."
mkdir -p "$BIN_DIR"
cp "$REPO_DIR/csb.py" "$BIN_DIR/csb"
cp "$REPO_DIR/csb-daemon.py" "$BIN_DIR/csb-daemon"
cp "$REPO_DIR/daemon_logic.py" "$BIN_DIR/daemon_logic.py"
chmod +x "$BIN_DIR/csb" "$BIN_DIR/csb-daemon"

info "Syncing CLAUDE.md to session directory..."
SESSION_DIR="$HOME/.local/share/claude-code-sandbox/claude"
mkdir -p "$SESSION_DIR"
cp "$REPO_DIR/CLAUDE.md" "$SESSION_DIR/CLAUDE.md"

if [ ! -f "$CONFIG_FILE" ]; then
    info "Creating starter config at $CONFIG_FILE..."
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_FILE" <<'EOF'
image = "claude-code-sandbox:latest"

# Linux only: directories to mount into the container at the same path.
# On macOS, mounts are read automatically from the Colima 'csb' VM config.
# [mounts]
# paths = ["~/src"]

# CIDRs to allow through the sandbox's firewall, in addition to the
# container's own host network. Use this to reach services on another
# Colima VM (e.g. 'default') via its vmnet address — run
# `colima status default` to find its IP, then list the /24 here.
# Applied live on every `csb` launch — no rebuild or container recreate needed.
# dev_networks = ["192.168.64.0/24"]

# hostname:ip pairs to add to /etc/hosts inside the sandbox, e.g. when app
# logic depends on a specific domain that should resolve to a dev VM.
# Applied live on every `csb` launch — no rebuild or container recreate needed.
# dev_hosts = ["myapp.local:192.168.64.3"]

# Docker commands the sandbox is allowed to run on the host.
[proxy]
allowed_commands = [
  "docker ps",
  "docker images",
  "docker logs",
  "docker build",
  "docker pull",
  "docker compose up",
  "docker compose down",
  "docker compose restart",
  "docker compose logs",
  "docker compose ps",
  "docker volume ls",
  "docker volume inspect",
  "docker volume prune",
  "docker system prune",
  "docker system df",

  # Wildcards are supported — * matches any single token (e.g. container name)
  # "docker exec * bundle exec rails",
  # "docker exec * bundle exec rspec",
  # "docker exec * yarn add",
]
EOF
    warn "Edit $CONFIG_FILE to add your workspaces."
else
    info "Config already exists at $CONFIG_FILE, skipping."
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR is not in your PATH."
    echo "    Add this to your shell config (~/.zshrc or ~/.bashrc):"
    echo ""
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    warn "ANTHROPIC_API_KEY is not set."
    echo "    Add this to your shell config:"
    echo ""
    echo "    export ANTHROPIC_API_KEY=sk-ant-..."
    echo ""
fi

info "Done! Run 'csb' to start a secure Claude Code session."
