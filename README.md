# claude-code-sandbox

A secure sandbox for running [Claude Code](https://claude.ai/code) with `--dangerously-skip-permissions`.

Claude Code in autonomous mode is powerful but risky — it can read secrets, exfiltrate data, and execute destructive commands. This project runs it inside an isolated Docker container with:

- **VM-level filesystem isolation** — Claude Code only sees the directories you explicitly mount into the VM. Sensitive paths like `~/.ssh` and `~/.aws` are invisible even to malicious compose files.
- **Two-VM architecture (macOS)** — sandbox and dev containers run in separate Colima VMs with no shared filesystem
- **Network firewall** — blocks all outbound traffic except Anthropic API, GitHub, npm, DNS, and SSH
- **[aca-safety-net](https://github.com/techycorp/aca-safety-net)** — an opt-in Rust hook that flags secrets access, dangerous commands, and environment variable exposure at the Claude Code layer (a best-effort guardrail you wire into `settings.json`, not a hard boundary)
- **Host container proxy** — lets the agent restart and manage your local Docker services through a configurable whitelist
- **Voice mode** — microphone access via PulseAudio passthrough (macOS)
- **Clipboard image paste** — paste images (e.g. screenshots) into the container with Ctrl+V, same as outside the sandbox (macOS)
- **Session persistence** — conversation history and credentials survive container restarts and image rebuilds

## This Is an Opinionated Workflow

Read this before adopting it — the security model only holds if your setup matches these assumptions.

- **Your dev environment runs in Docker.** The sandbox interacts with your running app services *exclusively* through `docker` commands routed to the host. There is no SSH-into-a-box, no running app processes directly on the host, no non-Docker orchestration. If your services don't run as containers, the host-proxy model gives the agent nothing to talk to.
- **`docker` is the only channel to the app side, and it's allowlist-gated.** The sandbox's `docker` is a [shim](#how-the-proxy-works) that forwards to a host daemon, which runs only the exact subcommands you list in `allowed_commands`. The agent cannot run arbitrary commands against your dev VM — only the docker subcommands you approve. This allowlist is the *entire* boundary on the app side: there is **no denylist underneath it**, so a loose pattern (e.g. a bare `docker exec *`, or any entry whose program can spawn a shell or `eval`) hands the agent everything that container can reach. See [The Whitelist Is the Ultimate Authority](#the-whitelist-is-the-ultimate-authority).
- **The sandbox only sees the directories you mount — and you are responsible for what's in them.** Filesystem isolation means Claude can't reach paths you don't mount. It does **not** scrub the paths you *do* mount: if a mounted source directory contains plaintext secrets (`.env`, `.envrc`, deploy secret files), Claude can read them. The "no secrets on disk" guarantee is yours to uphold by keeping plaintext secrets out of mounted trees (encrypt at rest, or store them outside the mount) — `aca-safety-net` is a pattern-matching guardrail, not a hard boundary.
- **`--dangerously-skip-permissions` is the point.** This exists to run Claude Code fully autonomously. The containment above is what makes that defensible — but it's perimeter containment, not a guarantee about everything the agent does *inside* the perimeter.

If your workflow doesn't run on Docker, or you need finer-grained control of what the agent can do on the app side than a docker-subcommand allowlist provides, this probably isn't the right tool.

## Relationship to the Official Anthropic Devcontainer

Anthropic publishes an [official devcontainer](https://github.com/anthropics/claude-code/tree/main/.devcontainer) for running Claude Code securely. This project is heavily inspired by it and shares the same core security model:

- Same base image (`node:20`)
- Same network firewall (`init-firewall.sh`) — CSB's is descended from theirs, then hardened (resolver-scoped DNS, no blanket SSH egress, fail-closed on init failure)
- Same non-root user (`node`)
- Same approach to running `--dangerously-skip-permissions` safely

**What this adds:**

- **Two-VM isolation (macOS)** — sandbox and dev containers run in separate Colima VMs. Even a full container escape in the sandbox cannot access your dev containers or home directory. The official devcontainer is a single container.
- **Host container proxy** — the agent can restart and manage your local Docker services through a configurable allowlist; the official devcontainer has no mechanism for this. Docker only — the host daemon hard-rejects any non-`docker` command.
- **Standalone CLI (`csb`)** — runs without VS Code or the devcontainer toolchain. Works from any terminal.
- **Voice mode (macOS)** — PulseAudio passthrough so `/voice` works inside the container. The official devcontainer ships no audio stack and passes through no audio device.
- **Session data as plain host files** — `~/.local/share/claude-code-sandbox/claude` is a host bind mount, not a Docker-managed volume. Both projects persist sessions across rebuilds (theirs via named volumes), but CSB's lives as plain files on your Mac — survives `colima delete csb` and `docker volume prune`, and is directly inspectable and backupable.
- **[aca-safety-net](https://github.com/techycorp/aca-safety-net)** — a Rust Claude Code hook for static analysis of dangerous commands and secret access. It's a **best-effort guardrail you opt into** (wire it into `~/.claude/settings.json`; it does nothing until you do), not an enforcement boundary — pattern-matchers are bypassable.

If you use VS Code and don't need the host container proxy, the official devcontainer may be simpler to set up.

## Requirements

- Python 3.11+
- **macOS**: [Colima](https://github.com/abiosoft/colima) + Docker CLI
- **Linux**: [Docker](https://docs.docker.com/engine/install/)
- **Voice mode (macOS only)**: PulseAudio — `brew install pulseaudio`
- **Clipboard image paste (Linux only)**: `wl-clipboard` (Wayland) or `xclip` (X11) on the host — macOS needs nothing extra (`osascript` ships with the OS)

## Platform Support

### macOS — Colima (Two-VM Architecture)

Colima runs Docker inside isolated Linux VMs. This project uses **two separate VMs**:

- **`default`** — your regular dev containers (databases, app servers, etc.)
- **`csb`** — the Claude Code sandbox, restricted to only your project directories

This means a container escape in the sandbox cannot reach your dev containers or any sensitive home directory files. Both VMs have explicit filesystem mounts so `~/.ssh`, `~/.aws`, etc. are invisible to both.

**Install:**
```bash
brew install colima docker docker-compose
mkdir -p ~/.docker/cli-plugins
ln -sfn $(brew --prefix)/opt/docker-compose/bin/docker-compose ~/.docker/cli-plugins/docker-compose
```

**Configure `DOCKER_HOST` for your default Colima instance** (add to `~/.zshrc`):
```bash
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
```

**Start the default VM** for your dev containers:
```bash
colima start
```

**Restrict the default VM's filesystem** by editing `~/.colima/default/colima.yaml`:
```yaml
mounts:
  - location: /absolute/path/to/your/projects
    writable: true
```
Then `colima restart`. This prevents malicious compose files from mounting `~/.ssh` or `~/.aws`.

### Linux — Docker

Docker runs natively on Linux with no VM overhead.

```bash
# Install Docker per your distro's instructions
# https://docs.docker.com/engine/install/
```

## Installation

**macOS only:** Before installing, create the `csb` Colima VM with your session storage and project directories mounted. Mount the parent directory containing your projects — not individual project folders.

```bash
colima start csb --cpu 4 --memory 4 --disk 20 --activate=false \
  --mount ~/.local/share/claude-code-sandbox:w \
  --mount /absolute/path/to/your/projects:w
```

If you skip this, `./install.sh` will print the exact command with a reminder.

Then install:

```bash
git clone https://github.com/techycorp/claude-code-sandbox
cd claude-code-sandbox
./install.sh
```

`just install` runs the same script and is equivalent to `./install.sh` directly.

This will:
1. **Build the container image** into the `csb` Colima VM (macOS) or default Docker (Linux), tagged `claude-code-sandbox:latest`.
2. **Remove the existing `claude-sandbox` container** if one exists, so the next `csb` launch creates a fresh one from the rebuilt image. (Session data and Claude authentication survive — see "Session Persistence" below.)
3. **Install `csb`, `csb-daemon`, and `daemon_logic.py`** to `~/.local/bin/` (the latter is a shared module imported by `csb-daemon`, not run directly).
4. **Copy this repo's `CLAUDE.md`** (the sandbox-specific instructions file, `CLAUDE.md` at the repo root — not your personal `~/.claude/CLAUDE.md`) to `~/.local/share/claude-code-sandbox/claude/CLAUDE.md`. This is the directory mounted into the container at `/home/node/.claude`, so this is what the agent actually reads inside the sandbox.
5. **Create a starter config** at `~/.config/claude-code-sandbox/config.toml` — but only if one doesn't already exist; an existing config is left untouched.

Separately, every time you run `csb` (not just during install), it re-syncs two things into that same session directory:
- This repo's `CLAUDE.md` again (so a `csb` launch always picks up the latest version without needing a full `./install.sh`).
- Your personal `~/.claude/settings.json` (so hooks like `aca-safety-net` registered on your host are mirrored into the container).

Add to your shell config (`~/.zshrc` or `~/.bashrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Configuration

Edit `~/.config/claude-code-sandbox/config.toml`:

```toml
image = "claude-code-sandbox:latest"

# Linux only: directories to mount into the container at the same path.
# On macOS, mounts are read automatically from the Colima 'csb' VM config.
# [mounts]
# paths = ["/home/you/projects"]

# CIDRs to allow through the sandbox's firewall, in addition to the
# container's own host network. Use this to reach services on another
# Colima VM (e.g. 'default') via its vmnet address. See "Reaching Host
# Services" below. Applied live on every `csb` launch — no rebuild or
# container recreate needed.
# dev_networks = ["192.168.64.0/24"]

# hostname:ip pairs to add to /etc/hosts inside the sandbox, e.g. when app
# logic depends on a specific domain that should resolve to a dev VM.
# Applied live on every `csb` launch — no rebuild or container recreate needed.
# dev_hosts = ["myapp.local:192.168.64.3"]

# Docker commands the agent is allowed to run on the host (default Colima VM / Docker)
[proxy]
allowed_commands = [
  "docker compose up",
  "docker compose down",
  "docker compose restart",
  "docker compose logs",
  "docker compose ps",
  "docker ps",
  "docker logs",
  "docker volume ls",
  "docker volume prune",
  "docker system df",

  # Wildcards are supported — * matches any single token (e.g. container name).
  # Enumerate exact safe subcommands rather than leaving an interpreter's
  # prefix open — see "The Whitelist Is the Ultimate Authority" below.
  # "docker exec * bundle exec rails db:migrate",
  # "docker exec * bundle exec rspec",
  # "docker exec * yarn add",
]
```

### Wildcard Support

`allowed_commands` entries support `*` as a wildcard matching any single token:

```toml
"docker exec * bundle exec rails db:migrate",   # matches any container name
"docker exec * bundle exec rspec",
"docker exec * yarn add",
```

Only the container name is wildcarded — every other token must match exactly. Trailing args beyond the pattern (a spec file path, a package name) are still permitted, since they're just arguments to the already-pinned program, not a way to run something else.

### The Whitelist Is the Ultimate Authority

The whitelist guarantees one thing: only the exact program in the pattern's pinned positions can ever execute — nothing can be smuggled into the wildcard's position or inserted ahead of a fixed token. It does **not** know anything about what that program is capable of once it's running. If the program itself has a built-in "execute whatever string you hand me" mode, an open-ended pattern hands that mode straight to the proxy caller.

The clearest example is `bundle exec rails`:

```toml
# DANGEROUS — runner/console/dbconsole are reachable
"docker exec * bundle exec rails"
```

This looks like it only allows safe rails tasks, but `rails runner`, `rails console`, and `rails dbconsole` all match it too — and `runner` in particular evaluates an arbitrary Ruby string passed directly in the command itself:

```bash
docker exec myapp bundle exec rails runner "File.read('/secrets/key')"
```

That's a fundamentally different risk than something like `db:migrate`: `db:migrate` only ever runs code that's *already checked into the trusted repo* (files under `db/migrate/`). `runner` executes a string supplied at call time — the payload never has to touch disk or be part of the repo at all. The proxy call itself becomes the code execution oracle.

**The fix: enumerate the exact subcommands you need instead of leaving the prefix open.**

```toml
# SAFE — only these specific tasks are reachable; runner/console/dbconsole
# never match any pattern, so they're simply not callable through the proxy
"docker exec * bundle exec rails db:migrate",
"docker exec * bundle exec rails db:create",
"docker exec * bundle exec rails db:rollback",
```

This applies to any tool with a similar eval-from-argv escape hatch — `rails runner`/`console`/`dbconsole`, `ruby -e`, `python -c`, `node -e`, and so on. Before whitelisting `<tool> <subcommand>` as an open prefix, check whether that tool has a mode whose entire purpose is "run whatever I'm handed." If it does, enumerate the literal safe invocations instead.

### How the Proxy Works

The `csb-daemon` runs on the Mac host and routes docker commands to the appropriate VM:

- **Sandbox container** (`csb` VM) — where Claude Code runs
- **App containers** (`default` VM) — where your dev services run

When the agent runs `docker compose up` from a project directory, the proxy uses the same path on the host (no translation needed — paths match between container and host) and runs the command against the `default` VM.

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

**`aca-safety-net` is not a foolproof boundary.** It's a pattern-matching PreToolUse hook — it catches recognized dangerous tool calls (`rm -rf /`, obvious env-dumping commands, etc.), but anything it doesn't recognize sails through: a renamed binary, a one-off script, an unusual invocation style. Treat it as a guardrail against honest mistakes, not containment against an adversarial agent.

This matters most for secrets. If a `.env`/`.envrc` file with real credentials sits in a directory mounted into the sandbox, `aca-safety-net` is not a reliable guarantee that it stays unread — there's no pattern-matching layer that can enumerate every possible way to read a file. The actual fix is to not have plaintext secrets on disk in any mounted directory in the first place:

- Keep secret files out of directories mounted into `csb` (e.g. don't put `.env` inside a repo dir that's part of your project mount).
- Prefer injecting secrets into the **app container's environment at start time** (a secrets manager like Infisical/Vault/Doppler/1Password Connect, or a host-only `--env-file` path that `csb` never sees) rather than committing them to a file the sandbox can read at all.

## Usage

```bash
csb
```

This drops you into a zsh shell inside the secure container. Your project directories are mounted at the same paths as on the host. For convenience, symlinks are created in `~` for each mounted directory:

```bash
# If you mounted /home/you/projects, inside the container:
ls ~/projects      # symlink to /home/you/projects
cd ~/projects/my-project
claude --dangerously-skip-permissions
```

### Authentication

Claude Code uses your Claude.ai account (OAuth). On first launch, run `claude` inside the container and follow the login prompt. Your session persists across restarts — the container is kept alive between `csb` sessions.

### Session Persistence

The sandbox container is persistent — exiting `csb` stops it but does not delete it. Session data (conversations, credentials) lives inside the container and is backed by `~/.local/share/claude-code-sandbox/` on the host, which is mounted into the `csb` VM.

Rebuilding the image with `just install` removes the old container and creates a fresh one. Session data on the host survives.

## Voice Mode (macOS)

Voice mode requires PulseAudio for audio passthrough from your Mac into the container.

```bash
brew install pulseaudio
```

`csb` automatically starts a PulseAudio TCP server before launching the container. Inside the container, use `/voice` as normal.

**Note:** While `csb` is running, PulseAudio takes over the host audio device. Voice mode on the host (`claude` outside the sandbox) will not work simultaneously. Run `pulseaudio --kill` to restore host voice mode after exiting `csb`.

## Clipboard Image Paste

The container has no clipboard access on its own. On macOS there's no pasteboard inside a Linux container at all; on Linux, the container has no X11/Wayland session of its own even if `xclip`/`wl-paste` were installed in it — either way, Claude Code's normal Linux clipboard-image path (talking to `xclip`/`wl-paste` directly) can't reach anything real from inside a headless container.

Instead, a stand-in `xclip` shim (`shims/xclip`) intercepts the two specific clipboard lookups Claude Code makes and forwards them to `csb-daemon` on the host, which reads the *host's* real clipboard and relays the PNG bytes back:

- **macOS**: via `osascript` (`the clipboard as «class PNGf»`)
- **Linux**: via `wl-paste --type image/png` (Wayland) or `xclip -selection clipboard -t image/png -o` (X11), whichever the host's display session supports

From inside the container, Ctrl+V works exactly as it does outside the sandbox — copy an image (screenshot, browser, Preview, etc.) and paste it directly into the Claude Code prompt.

This only works in terminals that support image paste in the first place (iTerm2, Warp, Kitty, WezTerm, Ghostty — not Terminal.app).

## Reaching Host Services

Inside the container, `localhost` refers to the container itself, not the host.

`host.docker.internal` only resolves to the **`csb` VM's own** NAT gateway — because `csb` and `default` are separate Colima VMs with separate private networks, it does **not** reach services running in your `default` VM. By default, those services are unreachable from the sandbox.

To reach them (e.g. an app server or database container), do this one-time setup on your Mac (not automated — it's a deliberate manual opt-in):

1. Give the `default` VM a real, host-reachable IP by enabling `network.address: true` in `~/.colima/default/colima.yaml`, then `colima restart default`. (This may prompt for your admin password the first time, to set up the vmnet bridge.)
2. Find its address: `colima status default` (e.g. `address: 192.168.64.3`).
3. Convert that address to a `/24` CIDR by zeroing out the last octet — `192.168.64.3` becomes `192.168.64.0/24` (the `/24` means the first three octets are fixed and the last one can be anything, covering the whole `192.168.64.0`–`192.168.64.255` range the VM's address falls within). Add it to `dev_networks` in `~/.config/claude-code-sandbox/config.toml`:
   ```toml
   dev_networks = ["192.168.64.0/24"]
   ```
4. Re-run `csb`. Both `dev_networks` and `dev_hosts` (below) are applied fresh to the existing sandbox container on every launch — no rebuild, no container recreate needed.
5. From inside the sandbox, reach services by that IP directly:
   ```bash
   curl http://192.168.64.3:3000   # web app
   curl http://192.168.64.3:3001   # frontend app
   psql -h 192.168.64.3 -p 5433    # database
   ```

If your app's logic depends on a specific hostname rather than a raw IP (e.g. cookie/session domains), add it to `dev_hosts` instead — this writes a static `/etc/hosts` entry inside the sandbox:

```toml
dev_hosts = ["myapp.local:192.168.64.3"]
```

```bash
curl http://myapp.local:3000
```

The `default` VM's address can change if the VM is recreated — re-check `colima status default` and update `dev_networks` if connectivity breaks.

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
- Only `docker` commands are permitted
- Only subcommands matching `allowed_commands` are executed — enforcement is a **pure allowlist** (token-prefix match in `daemon_logic.py`); there is no separate denylist
- Anything not matched by a pattern is rejected, including `env`/`sh`/`bash`/`printenv` — but *only* because no pattern admits them, not via an override. A loose pattern (a bare `docker exec *`, or any entry whose pinned program can spawn a shell or eval) re-opens them. See [The Whitelist Is the Ultimate Authority](#the-whitelist-is-the-ultimate-authority).

## Security Model

**What the sandbox cannot do:**
- Access `~/.ssh`, `~/.aws`, or any path outside explicitly mounted directories (VM-level restriction)
- Make arbitrary outbound network connections (firewall)
- Run docker commands not in the whitelist (proxy enforcement)

**What the sandbox can do (accepted tradeoffs):**
- Read, modify, or delete files in your mounted project directories
- Exfiltrate data via whitelisted channels (GitHub commits, npm publishes)
- Spin up app containers via the proxy (controlled by your `allowed_commands`)
- **DNS tunneling via the legitimate resolver.** The firewall scopes DNS egress to the container's actual configured resolver (closing the "query an arbitrary external resolver directly" channel), but it can't stop queries for `<encoded-data>.attacker-domain.com` sent *to* that legitimate resolver — DNS is recursive by design, so it will dutifully chase the query out to whatever nameserver the attacker controls. This is lower-bandwidth and a higher bar than an open resolver, but not zero. Closing it fully would require a domain-filtering DNS proxy that rejects queries for non-whitelisted names, not just IP-based reachability — a meaningfully bigger lift than what's implemented here.
- **Broad GitHub egress.** The firewall allowlists GitHub's entire published IP ranges (web/api/git), since that's what `git`/`gh` need to function. A push to a repo you control, or a public gist, is indistinguishable at the network layer from legitimate use — it's still just HTTPS to a GitHub IP. There's no fix for this short of TLS-intercepting GitHub's own traffic to inspect content, which isn't something this project does.

## Rebuilding the Image

After pulling updates:

```bash
cd claude-code-sandbox
./install.sh
```

This removes the old container, rebuilds the image, and reinstalls `csb`. Session data and Claude authentication are preserved.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 TechyCorp.
