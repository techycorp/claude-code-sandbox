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
command -v podman &>/dev/null || error "Podman is not installed. See https://podman.io/getting-started/installation"
command -v python3 &>/dev/null || error "Python 3.11+ is required."
python3 -c "import tomllib" 2>/dev/null || error "Python 3.11+ is required (tomllib missing)."

info "Building container image..."
podman build -t "$IMAGE" "$REPO_DIR"

info "Installing csb and csb-daemon to $BIN_DIR..."
mkdir -p "$BIN_DIR"
cp "$REPO_DIR/csb" "$BIN_DIR/csb"
cp "$REPO_DIR/csb-daemon" "$BIN_DIR/csb-daemon"
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

# Add your workspaces here. Each will be mounted at /workspaces/<name> inside the container.
[workspaces]
# my-project = "~/src/my-project"

# Podman/Docker commands the sandbox is allowed to run on the host.
[proxy]
allowed_commands = [
  "podman ps",
  "podman images",
  "podman logs",
  "podman build",
  "podman pull",
  "podman compose up",
  "podman compose down",
  "podman compose restart",
  "podman compose logs",
  "podman compose ps",
  "podman volume ls",
  "podman volume inspect",
  "podman volume prune",
  "podman system prune",
  "podman system df",
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
  # "podman exec * bundle exec rails",
  # "podman exec * bundle exec rspec",
  # "podman exec * bundle exec rake",
  # "docker exec * bundle exec rails",
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
