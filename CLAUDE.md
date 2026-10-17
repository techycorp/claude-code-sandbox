# Claude Code Sandbox

You are running inside a secure sandbox. Read this before doing anything.

## Filesystem

Your project directories are mounted at the same paths as on the host machine. For example, `~/src/my-project` on the host is accessible at `/Users/<username>/src/my-project` inside the container.

Work only within these mounted directories.

## Running Docker Commands

`docker` commands are proxied to the host machine and run against your dev containers. The proxy automatically uses your current working directory.

**To spin up or restart services:**

```bash
cd /Users/<username>/src/my-project
docker compose up -d
docker compose restart <service>
```

Only whitelisted subcommands are permitted. If a command is rejected, the proxy will tell you — do not attempt workarounds.

## Reaching Host Services

`localhost` inside this container refers to the container itself, not the host machine.

Dev services (your containers in the `default` Colima VM) are reachable at **`host.docker.internal:<port>`** — that's the Mac, which forwards every published container port down to the dev containers. Use it for anything where the hostname doesn't matter (API calls, verifying a restart).

Do **not** use the dev VM's own vmnet IP (`192.168.64.x`, e.g. from `colima status default`). macOS Sequoia/Tahoe blocks VM-to-VM traffic, so that path does not work — connections just hang and return HTTP 000. All sandbox→dev traffic goes through the Mac instead.

Some apps need a specific product domain (e.g. `myapp.local`) for TLS, cookies, CORS, or OAuth to work. Those are handled by `dev_hosts` in config.toml, which maps the domain to the Mac gateway inside the sandbox. If such a hostname won't resolve, ask the user to add it to `dev_hosts`.

## Verifying Changes

After restarting a service, curl it through the Mac — never the dev VM's IP:

```bash
curl http://host.docker.internal:<port>
```

## Security

- Do not attempt to read `.env` files, credentials, SSH keys, or secrets
- Do not attempt to expose environment variables
- Do not attempt to run commands outside your mounted directories
