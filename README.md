# claude-code-sandbox

A secure sandbox for running [Claude Code](https://claude.ai/code) with `--dangerously-skip-permissions`.

Claude Code in autonomous mode is powerful but risky — it can read secrets, exfiltrate data, and execute destructive commands. This project runs it inside a rootless Podman container with:

- **Filesystem isolation** — Claude Code only sees the directories you explicitly mount
- **Network firewall** — blocks all outbound traffic except Anthropic API, GitHub, npm, DNS, and SSH
- **[aca-safety-net](https://github.com/techycorp/aca-safety-net)** — a fast Rust hook that blocks secrets access, dangerous commands, and environment variable exposure at the Claude Code layer
- **Host container proxy** — lets the agent restart and manage your local Docker/Podman services through a configurable whitelist
- **Voice mode** — microphone access via PulseAudio passthrough
- **Session persistence** — conversation history survives container restarts and image rebuilds

## Relationship to the Official Anthropic Devcontainer

Anthropic publishes an [official devcontainer](https://github.com/anthropics/claude-code/tree/main/.devcontainer) for running Claude Code securely. This project is heavily inspired by it and shares the same core security model:

- Same base image (`node:20`)
- Same network firewall (`init-firewall.sh`) with the same whitelist
- Same non-root user (`node`)
- Same approach to running `--dangerously-skip-permissions` safely

**What this adds:**

- **Host container proxy** — the agent can restart and manage your local Docker/Podman services through a configurable whitelist. The official devcontainer has no mechanism for this.
- **[aca-safety-net](https://github.com/techycorp/aca-safety-net)** — a Rust-based Claude Code hook for static analysis of dangerous commands, secrets access, and env exposure. Complements the network firewall with a second enforcement layer.
- **Standalone CLI (`csb`)** — runs without VS Code or the devcontainer toolchain. Works from any terminal.
- **Workspace config** — define multiple project directories in a TOML config, all mounted into a single container session.
- **Voice mode** — PulseAudio passthrough so `/voice` works inside the container.
- **Session persistence** — Claude session data stored on the host, survives rebuilds.

If you use VS Code and don't need the host container proxy, the official devcontainer may be simpler to set up.

## Requirements

- [Podman](https://podman.io/getting-started/installation)
- Python 3.11+
- [PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/) (optional, for voice mode) — `brew install pulseaudio` on macOS

## Platform Support

- **macOS** — fully supported
- **Linux** — supported. Podman is native (no VM), PulseAudio works natively. Note: `--cap-add=NET_ADMIN` for iptables inside the container requires unprivileged user namespaces to be enabled (`/proc/sys/kernel/unprivileged_userns_clone` must be `1`).

## Installation

```bash
git clone https://github.com/techycorp/claude-code-sandbox
cd claude-code-sandbox
./install.sh
```

This will:
1. Build the container image
2. Install `csb` and `csb-daemon` to `~/.local/bin/`
3. Create a starter config at `~/.config/claude-code-sandbox/config.toml`

Add to your shell config (`~/.zshrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Configuration

Edit `~/.config/claude-code-sandbox/config.toml`:

```toml
image = "claude-code-sandbox:latest"

# Directories mounted at /workspaces/<name> inside the container
[workspaces]
my-project = "~/src/my-project"
another-project = "~/src/another-project"

# Host podman/docker commands the agent is allowed to run
[proxy]
allowed_commands = [
  "podman compose up",
  "podman compose down",
  "podman compose restart",
  "podman compose logs",
  "podman compose ps",
  "podman ps",
  "podman logs",
  "podman volume ls",
  "podman volume prune",
  "podman system df",
  "docker compose up",
  "docker compose down",
  "docker compose restart",
  "docker compose logs",
  "docker compose ps",
  "docker ps",
  "docker logs",

  # Wildcards are supported — * matches any single token
  # "podman exec * bundle exec rails",
  # "podman exec * bin/rails",
]
```

### Wildcard Support

`allowed_commands` entries support `*` as a wildcard matching any single token. This is useful for `exec` commands where the container name varies:

```toml
"podman exec * bundle exec rails",   # matches any container
"podman exec * bin/rake",
```

This is safe because only the container name is wildcarded — the command after it is still exact. The proxy's blocklist independently blocks `exec` with `env`, `sh`, `bash`, etc. regardless of the whitelist.

### How the Proxy Works

When the agent runs `podman compose up` from inside `/workspaces/my-project`, the proxy:
1. Receives the command and the container path (`/workspaces/my-project`)
2. Translates it to the host path (`~/src/my-project`)
3. Runs `podman compose up` on the host from that directory

So `cd /workspaces/techycorp/mordor && podman compose up -d` works as expected.

## Claude Code Hooks (aca-safety-net)

`aca-safety-net` is installed inside the container but you must wire it up in your `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Read|Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "aca-safety-net",
            "timeout": 1
          }
        ]
      }
    ]
  }
}
```

Your `~/.claude/settings.json` is synced into the container on each `csb` launch.

See [aca-safety-net](https://github.com/techycorp/aca-safety-net) for configuration options including custom rules, paranoid mode, and audit logging.

## Usage

```bash
csb
```

This drops you into a zsh shell inside the secure container. All your configured workspaces are available under `/workspaces/`. From there:

```bash
cd /workspaces/my-project
claude --dangerously-skip-permissions
```

### Authentication

Claude Code uses your Claude.ai account (OAuth). On first launch, run `claude` inside the container and follow the login prompt. Your session persists across restarts.

### Session Persistence

Session data is stored at `~/.local/share/claude-code-sandbox/claude/` on the host and mounted into the container. Rebuilding the image does not lose your session.

## Voice Mode

Voice mode requires PulseAudio for audio passthrough from your Mac/Linux machine into the container.

**macOS setup:**
```bash
brew install pulseaudio
```

`csb` automatically starts a PulseAudio TCP server before launching the container. Inside the container, use `/voice` as normal.

**Note:** While `csb` is running, PulseAudio takes over the host audio device. This means voice mode on the host (`claude` outside the sandbox) will not work simultaneously. Stop `csb` or kill PulseAudio (`pulseaudio --kill`) to restore host voice mode.

## Reaching Host Services

Inside the container, `localhost` refers to the container itself. To reach services running on your host machine, use `host.containers.internal`:

```bash
curl http://host.containers.internal:3000   # Rails app
curl http://host.containers.internal:3001   # Next.js app
psql -h host.containers.internal -p 5433    # Postgres
```

## What's Blocked

**Network:** All outbound connections are blocked by default. Only these are allowed:
- `api.anthropic.com` — Claude API
- GitHub IP ranges — git operations
- `registry.npmjs.org` — npm
- DNS (port 53)
- SSH (port 22)

**Claude Code hooks (via aca-safety-net):**
- Reading `.env`, SSH keys, credentials, API tokens
- `printenv`, `export`, `history`, env-exposing commands
- `rm -rf` outside the working directory
- Destructive git operations (`reset --hard`, `push -f` to main, etc.)
- Cloud CLI secret exposure (AWS, GCloud, Heroku)
- Editing dependency files without approval

**Host container proxy:**
- Only `podman` and `docker` commands are permitted
- Only subcommands matching `allowed_commands` are executed
- `exec` with `env`, `sh`, `bash`, `printenv` is always blocked regardless of whitelist

## Security Notes

The container does **not** protect against:
- Malicious code reading or deleting files within your mounted workspaces
- Exfiltration via whitelisted channels (e.g. encoding data in a GitHub commit)
- `podman exec * <command>` wildcards — only wildcard the container name, keep the command explicit

For full isolation, mount only the directories Claude Code needs access to.

## Rebuilding the Image

After pulling updates:

```bash
cd claude-code-sandbox
./install.sh
```

Session data, config, and Claude authentication are preserved across rebuilds.
