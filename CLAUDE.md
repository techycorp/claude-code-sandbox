# Claude Code Sandbox

You are running inside a secure sandbox. Read this before doing anything.

## Filesystem

Your workspaces are mounted at `/workspaces/<name>`. Work only within these directories.

The path `/workspaces/<name>` inside this container maps directly to the corresponding directory on the host machine. You do not need to know the host path — the proxy handles translation automatically.

## Running Docker/Podman Commands

`podman` and `docker` commands are proxied to the host machine. The proxy automatically translates your current working directory to the correct host path.

**Always `cd` into the project directory before running compose commands:**

```bash
cd /workspaces/techycorp/mordor
podman compose up -d
```

```bash
cd /workspaces/techycorp/moria
podman compose up -d
```

Only whitelisted subcommands are permitted. If a command is rejected, the proxy will tell you — do not attempt workarounds.

## Reaching Host Services

`localhost` inside this container refers to the container itself, not the host machine. To reach services running on the host (local dev servers, databases, etc.), use `host.containers.internal`:

- `curl http://host.containers.internal:3000` — Rails app (mordor)
- `curl http://host.containers.internal:3001` — Next.js app (moria)
- `psql -h host.containers.internal -p 5433` — Postgres

## Verifying Changes

After restarting a service, verify with:

```bash
curl http://host.containers.internal:<port>
```

## Security

- Do not attempt to read `.env` files, credentials, SSH keys, or secrets
- Do not attempt to expose environment variables
- Do not attempt to run commands outside your workspace
