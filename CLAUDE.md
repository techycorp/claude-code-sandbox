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

`host.docker.internal` only reaches services inside this sandbox's own VM — it does **not** reach dev services running in a separate Colima VM. If `host.docker.internal:<port>` fails to connect, do not retry with workarounds. Instead, check the `CSB_DEV_NETWORKS` environment variable — if it's set, the dev VM's network has been allowed through the firewall, but you still need its specific IP. Ask the user for the address (they can find it with `colima status default` on the host) and use that directly, e.g. `curl http://<dev-vm-ip>:<port>`.

## Verifying Changes

After restarting a service, curl the dev VM's IP directly (not `host.docker.internal`):

```bash
curl http://<dev-vm-ip>:<port>
```

## Security

- Do not attempt to read `.env` files, credentials, SSH keys, or secrets
- Do not attempt to expose environment variables
- Do not attempt to run commands outside your mounted directories
