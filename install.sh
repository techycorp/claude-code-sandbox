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

# Colima's csb profile auto-activates itself as the Docker context on
# startup, stealing it from whatever was active (e.g. 'default'). Restore
# it on exit regardless of how this script finishes.
ORIGINAL_CONTEXT="$(docker context show 2>/dev/null || true)"
restore_context() {
    if [ -n "$ORIGINAL_CONTEXT" ]; then
        docker context use "$ORIGINAL_CONTEXT" &>/dev/null || true
    fi
}
trap restore_context EXIT
command -v python3 &>/dev/null || error "Python 3.11+ is required."
python3 -c "import tomllib" 2>/dev/null || error "Python 3.11+ is required (tomllib missing)."
python3 -c "import yaml" 2>/dev/null || pip install pyyaml -q || error "Failed to install pyyaml. Run: pip install pyyaml"

info "Building container image..."
ACA_SAFETY_NET_REF="${ACA_SAFETY_NET_REF:-master}"
ACA_SAFETY_NET_SHA="$(git ls-remote https://github.com/techycorp/aca-safety-net "$ACA_SAFETY_NET_REF" | cut -f1 | head -n1)"
[ -n "$ACA_SAFETY_NET_SHA" ] || error "Could not resolve aca-safety-net ref '$ACA_SAFETY_NET_REF'."
BUILD_ARGS=(--build-arg "ACA_SAFETY_NET_REF=$ACA_SAFETY_NET_REF" --build-arg "ACA_SAFETY_NET_SHA=$ACA_SAFETY_NET_SHA")
# Pass the resolved version so a new release busts the cached npm layer.
CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-$(npm view @anthropic-ai/claude-code version 2>/dev/null)}"
[ -n "$CLAUDE_CODE_VERSION" ] || error "Could not resolve latest claude-code version (is npm available / online?)."
BUILD_ARGS+=(--build-arg "CLAUDE_CODE_VERSION=$CLAUDE_CODE_VERSION")
info "Building with Claude Code $CLAUDE_CODE_VERSION"
if [[ "$(uname)" == "Darwin" ]]; then
    CSB_SOCKET="$HOME/.colima/csb/docker.sock"
    if [ ! -S "$CSB_SOCKET" ]; then
        echo ""
        echo -e "${RED}error:${NC} Colima 'csb' instance not found."
        echo ""
        echo "    Create it with your workspace directories and session storage mounted, then re-run install:"
        echo ""
        echo "    colima start csb --vm-type vz --network-address --cpu 4 --memory 4 --disk 20 --activate=false \\"
        echo "      --mount ~/.local/share/claude-code-sandbox:w \\"
        echo "      --mount ~/src/my-project:w \\"
        echo "      --mount ~/src/another-project:w"
        echo ""
        exit 1
    fi
    DOCKER_HOST="unix://$CSB_SOCKET" docker build "${BUILD_ARGS[@]}" -f "$REPO_DIR/Containerfile" -t "$IMAGE" "$REPO_DIR"
else
    docker build "${BUILD_ARGS[@]}" -f "$REPO_DIR/Containerfile" -t "$IMAGE" "$REPO_DIR"
fi

info "Removing existing sandbox container..."
if [[ "$(uname)" == "Darwin" ]]; then
    DOCKER_HOST="unix://$HOME/.colima/csb/docker.sock" docker rm -f claude-sandbox 2>/dev/null || true
else
    docker rm -f claude-sandbox 2>/dev/null || true
fi

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

# Extra CIDRs to allow through the sandbox's default-deny firewall, on top of
# the host network that's already allowed. Use this for external networks the
# sandbox would otherwise be blocked from reaching *through the Mac* — e.g. a
# Tailscale tailnet, a VPN subnet, or a LAN device. This only opens the
# firewall; it does not create a route, so it can't reach other Colima VMs
# (macOS blocks VM-to-VM). Applied live on every `csb` launch.
# dev_networks = ["100.64.0.0/10"]

# hostname:ip pairs to add to /etc/hosts inside the sandbox. Use this when an
# app needs a specific product domain (for TLS, cookies, CORS, or OAuth) —
# point it at the Mac gateway (192.168.5.2, what host.docker.internal resolves
# to), which forwards to your dev containers. Don't point it at a dev VM's
# vmnet IP — macOS blocks VM-to-VM, so that path won't connect.
# Applied live on every `csb` launch — no rebuild or container recreate needed.
# dev_hosts = ["myapp.local:192.168.5.2"]

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

  # Wildcards are supported — * matches any single token (e.g. container name).
  # Enumerate exact safe subcommands rather than leaving an interpreter's
  # prefix open — see "The Whitelist Is the Ultimate Authority" in the README.
  # "docker exec * bundle exec rails db:migrate",
  # "docker exec * bundle exec rspec",
  # "docker exec * yarn add",
]

# Secrets injected into `docker compose up` by the host-side proxy, fetched at
# run time and never written to disk or exposed to the sandbox. One table per
# secret. `env` is the variable the compose file interpolates (${env}). A
# configured secret that can't be resolved aborts `compose up` loudly — compose
# never starts without it. Sources:
#   "command"  — run any shell command; its stdout (trimmed) is the secret. The
#      portable backend (pass, vault, a plain file) and the one to use on a host
#      without an OS keystore, e.g. headless Linux.
#   "keychain" — host OS keystore. macOS: store once with
#      `security add-generic-password -s <service> -T /usr/bin/security -w`.
#      Linux: install secret-tool (libsecret), then
#      `secret-tool store --label=csb service <service>`.
#   "infisical" — needs key/project_id/infisical_env; auth config below.
# [[proxy.compose_secrets]]
# env = "GOOGLE_MAPS_API_KEY"
# source = "command"
# command = "pass show csb/google-maps"
#
# [[proxy.compose_secrets]]
# env = "RESEND_API_KEY"
# source = "keychain"
# service = "csb-dev-resend"
#
# [[proxy.compose_secrets]]
# env = "STRIPE_KEY"
# source = "infisical"
# key = "STRIPE_KEY"
# project_id = "your-project-id"
# infisical_env = "dev"
#
# Auth for source="infisical": the daemon reads Universal Auth client id/secret
# from the host keystore (macOS `security` / Linux secret-tool, as under
# "keychain" above) and mints a short-lived token per fetch (nothing persisted).
# Create a read-only machine identity scoped to the project's dev env, then store
# its creds under these service names, e.g. on macOS
# `security add-generic-password -s csb-infisical-client-id -T /usr/bin/security -w`
# (and -client-secret), or on Linux `secret-tool store --label=csb service csb-infisical-client-id`.
# [proxy.infisical]
# client_id_service = "csb-infisical-client-id"
# client_secret_service = "csb-infisical-client-secret"
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

info "Done! Run 'csb' to start a secure Claude Code session."
