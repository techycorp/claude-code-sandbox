#!/usr/bin/env python3
import os
import platform
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

MACOS = platform.system() == "Darwin"
COLIMA_INSTANCE = "csb"
COLIMA_SOCKET = Path.home() / ".colima" / COLIMA_INSTANCE / "docker.sock"
COLIMA_YAML = Path.home() / ".colima" / COLIMA_INSTANCE / "colima.yaml"

PULSE_PORT = 4713
CONFIG_PATH = Path.home() / ".config" / "claude-code-sandbox" / "config.toml"
SETTINGS_JSON = Path.home() / ".claude" / "settings.json"
SESSION_DIR = Path.home() / ".local" / "share" / "claude-code-sandbox" / "claude"
PROXY_PORT = 9876
_daemon_dir = Path(__file__).parent
DAEMON = _daemon_dir / "csb-daemon.py" if (_daemon_dir / "csb-daemon.py").exists() else _daemon_dir / "csb-daemon"
SANDBOX_CLAUDE_MD = Path(__file__).parent / "CLAUDE.md"

# agent-vault brokering. Enabled per-machine by installing the agent-vault binary
# and logging in; the host mints a short-lived vault session each launch and drops
# it here for the container's `cc` wrapper. No config entry — presence is opt-in.
AGENT_VAULT_VAULT = "default"
AGENT_VAULT_TTL = 28800  # 8h; re-minted on each csb launch
AV_TOKEN_FILE = SESSION_DIR / ".av-token"
AV_CA_SCRIPT = "/usr/local/bin/install-agent-vault-ca.sh"
AV_NOTE_START = "<!-- csb-agent-vault-start -->"
AV_NOTE_END = "<!-- csb-agent-vault-end -->"
AV_NOTE = """## Brokered egress

Some hosts are reached through a credential-injecting proxy. For those hosts do
NOT supply your own credentials — no `-u user:pass`, no `Authorization` header,
no API key in a header or query string. Make the plain request to the real URL
and the proxy injects the correct auth. Supplying your own is unnecessary and
can conflict with the injected credentials."""


def load_config():
    if not CONFIG_PATH.exists():
        print(f"Error: config not found at {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def ensure_colima():
    if not MACOS:
        return
    if COLIMA_SOCKET.exists():
        return
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    print("Error: Colima 'csb' instance not found.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Create it with your directories and session storage mounted, then re-run install:", file=sys.stderr)
    print("", file=sys.stderr)
    print("    colima start csb --vm-type vz --network-address --cpu 4 --memory 4 --disk 20 --activate=false \\", file=sys.stderr)
    print("      --mount ~/.local/share/claude-code-sandbox:w \\", file=sys.stderr)
    print("      --mount ~/src:w", file=sys.stderr)
    print("", file=sys.stderr)
    print("Then run: ./install.sh", file=sys.stderr)
    sys.exit(1)


def docker_env():
    env = os.environ.copy()
    if MACOS:
        env["DOCKER_HOST"] = f"unix://{COLIMA_SOCKET}"
    return env


def get_colima_mounts():
    if not COLIMA_YAML.exists():
        return []
    import yaml
    with open(COLIMA_YAML) as f:
        config = yaml.safe_load(f)
    mounts = config.get("mounts") or []
    return [Path(m["location"]).expanduser().resolve() for m in mounts]


def get_linux_mounts(config):
    paths = config.get("mounts", {}).get("paths", [])
    return [Path(p).expanduser().resolve() for p in paths]


def get_dev_networks(config):
    """User-specified CIDRs to allow through the sandbox's default-deny firewall
    (e.g. a Tailscale tailnet, VPN subnet, or LAN reachable through the Mac).
    Opens the firewall only — it can't reach other Colima VMs, since macOS
    blocks VM-to-VM. Set explicitly in config.toml; never auto-detected."""
    return config.get("dev_networks", [])


def get_dev_hosts(config):
    """User-specified hostname:ip pairs to add to /etc/hosts inside the
    container, for apps that need a specific product domain. Point them at the
    Mac gateway (what host.docker.internal resolves to), which forwards to the
    dev containers — not a dev VM's vmnet IP, which macOS blocks VM-to-VM."""
    return config.get("dev_hosts", [])


def mint_agent_vault_token():
    """Host-side (Mac or Linux): if agent-vault is set up here, mint a short-lived
    vault session and write it to the session dir for the container's `cc` wrapper.
    Returns True when brokering is enabled. The durable login stays on the host;
    only this ephemeral token enters the sandbox. Installed-but-unmintable is a
    hard error, never a silent downgrade to unbrokered egress."""
    if not shutil.which("agent-vault"):
        AV_TOKEN_FILE.unlink(missing_ok=True)
        return False
    result = subprocess.run(
        ["agent-vault", "vault", "token", "--vault", AGENT_VAULT_VAULT, "--ttl", str(AGENT_VAULT_TTL)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Error: agent-vault is installed but minting a session failed:\n{result.stderr.strip()}", file=sys.stderr)
        print("Fix: run `agent-vault auth login` and ensure a vault named 'default' exists,", file=sys.stderr)
        print("or remove the agent-vault binary to disable brokering.", file=sys.stderr)
        sys.exit(1)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    AV_TOKEN_FILE.write_text(result.stdout.strip() + "\n")
    AV_TOKEN_FILE.chmod(0o600)
    return True


def inject_broker_note():
    """Append a managed note to the mounted CLAUDE.md telling the agent not to
    send its own credentials to brokered hosts. Runs after sync_settings() has
    refreshed the file from the repo, so it stays absent when brokering is off
    (the file is re-copied clean each launch) and never accumulates."""
    md = SESSION_DIR / "CLAUDE.md"
    text = md.read_text() if md.exists() else ""
    if AV_NOTE_START in text:  # defensive: drop any prior block before re-adding
        head, _, rest = text.partition(AV_NOTE_START)
        _, _, tail = rest.partition(AV_NOTE_END)
        text = head.rstrip() + tail
    block = f"{AV_NOTE_START}\n{AV_NOTE}\n{AV_NOTE_END}\n"
    md.write_text(text.rstrip() + "\n\n" + block)


def install_agent_vault_ca(name, env):
    """Fetch the broker's MITM CA on the host and trust it inside the container,
    so the agent's TLS to upstreams (re-signed by the proxy) validates."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pem") as tf:
        fetched = subprocess.run(["agent-vault", "ca", "fetch", "-o", tf.name], capture_output=True, text=True)
        if fetched.returncode != 0:
            print(f"[csb] warning: could not fetch agent-vault CA: {fetched.stderr.strip()}", file=sys.stderr)
            return
        cert = Path(tf.name).read_text()
    result = subprocess.run(
        ["docker", "exec", "-i", "-u", "root", name, AV_CA_SCRIPT],
        input=cert, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[csb] warning: failed to install agent-vault CA: {result.stderr.strip()}", file=sys.stderr)


HOSTS_MARKER_START = "# csb-managed-start"
HOSTS_MARKER_END = "# csb-managed-end"


def wait_for_container(name, env, attempts=60):
    """Wait for the entrypoint's own perms/firewall setup to finish (signaled
    via a marker file) before we apply our own config on top of it — otherwise
    the entrypoint's firewall run can finish after ours and silently undo it."""
    for _ in range(attempts):
        result = subprocess.run(
            ["docker", "exec", name, "test", "-f", "/tmp/csb-entrypoint-ready"],
            env=env, capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    print(f"Error: container {name} did not become ready", file=sys.stderr)
    sys.exit(1)


def apply_firewall(name, env, dev_networks_env, attempts=5):
    for attempt in range(attempts):
        result = subprocess.run(
            ["docker", "exec", "-e", f"CSB_DEV_NETWORKS={dev_networks_env}", name,
             "sudo", "/usr/local/bin/init-firewall.sh"],
            env=env, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    print(f"[csb] warning: failed to apply firewall rules: {result.stderr.strip()}", file=sys.stderr)


def apply_dev_hosts(name, env, dev_hosts):
    current = subprocess.run(["docker", "exec", name, "cat", "/etc/hosts"], env=env, capture_output=True, text=True)
    lines = current.stdout.splitlines() if current.returncode == 0 else []

    if HOSTS_MARKER_START in lines and HOSTS_MARKER_END in lines:
        start = lines.index(HOSTS_MARKER_START)
        end = lines.index(HOSTS_MARKER_END)
        lines = lines[:start] + lines[end + 1:]

    if dev_hosts:
        lines.append(HOSTS_MARKER_START)
        for entry in dev_hosts:
            host, _, ip = entry.rpartition(":")
            lines.append(f"{ip} {host}")
        lines.append(HOSTS_MARKER_END)

    new_hosts = "\n".join(lines) + "\n"
    result = subprocess.run(
        ["docker", "exec", "-i", "-u", "root", name, "sh", "-c", "cat > /etc/hosts"],
        input=new_hosts, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[csb] warning: failed to update /etc/hosts: {result.stderr.strip()}", file=sys.stderr)


def apply_dynamic_config(name, env, dev_networks_env, dev_hosts):
    wait_for_container(name, env)
    apply_firewall(name, env, dev_networks_env)
    apply_dev_hosts(name, env, dev_hosts)


def start_daemon():
    import socket
    proc = subprocess.Popen([sys.executable, str(DAEMON)])
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=0.1):
                return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    print("Error: csb-daemon failed to start", file=sys.stderr)
    sys.exit(1)


def start_pulseaudio():
    if not shutil.which("pulseaudio"):
        print("[csb] pulseaudio not found — voice mode unavailable (brew install pulseaudio)", file=sys.stderr)
        return None
    proc = subprocess.Popen([
        "pulseaudio",
        "--load=module-native-protocol-tcp auth-anonymous=1",
        "--exit-idle-time=-1",
        "--daemonize=no",
        "--log-target=stderr",
    ], stderr=subprocess.DEVNULL)
    time.sleep(1)
    return proc


def sync_settings():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    if SANDBOX_CLAUDE_MD.exists():
        shutil.copy2(SANDBOX_CLAUDE_MD, SESSION_DIR / "CLAUDE.md")
    if SETTINGS_JSON.exists():
        shutil.copy2(SETTINGS_JSON, SESSION_DIR / "settings.json")


def main():
    config = load_config()
    image = config.get("image", "claude-code-sandbox:latest")

    ensure_colima()
    sync_settings()

    # Build mounts: workspace dirs at same path, session dir at ~/.claude
    if MACOS:
        mount_paths = get_colima_mounts()
    else:
        mount_paths = get_linux_mounts(config)

    # Exclude session dir from workspace mounts (handled separately)
    session_dir_resolved = SESSION_DIR.resolve()
    workspace_mounts = [p for p in mount_paths if not str(p).startswith(str(session_dir_resolved.parent.parent))]

    if not workspace_mounts and not MACOS:
        print("Error: no mounts defined. Add a [mounts] section to config.toml.", file=sys.stderr)
        sys.exit(1)

    mounts = []
    for path in workspace_mounts:
        mounts += ["-v", f"{path}:{path}"]

    mounts += ["-v", f"{SESSION_DIR}:/home/node/.claude"]

    csb_mounts_env = ":".join(str(p) for p in workspace_mounts)
    csb_dev_networks_env = ":".join(get_dev_networks(config))
    dev_hosts = get_dev_hosts(config)
    agent_vault = mint_agent_vault_token()
    if agent_vault:
        inject_broker_note()

    daemon = start_daemon()
    pulse = start_pulseaudio()

    env = docker_env()
    container_name = "claude-sandbox"
    existing = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Status}}"],
        capture_output=True, text=True, env=env
    ).stdout.strip()

    try:
        if not existing:
            # Forward terminal-identity env vars so the CLI inside the container
            # can detect iTerm2 (or similar) image-paste support, same as it
            # would outside the sandbox.
            term_vars = [
                "TERM_PROGRAM", "TERM_PROGRAM_VERSION",
                "LC_TERMINAL", "LC_TERMINAL_VERSION",
                "ITERM_SESSION_ID", "COLORTERM",
            ]
            term_env_flags = []
            for var in term_vars:
                if var in os.environ:
                    term_env_flags += ["-e", f"{var}={os.environ[var]}"]

            create_cmd = [
                "docker", "create", "-it",
                "--name", container_name,
                "--cap-add=NET_ADMIN",
                "--cap-add=NET_RAW",
                *mounts,
                "-e", f"CSB_MOUNTS={csb_mounts_env}",
                "-e", f"CSB_PROXY_HOST=host.docker.internal",
                "-e", f"CSB_PROXY_PORT={PROXY_PORT}",
                "-e", f"PULSE_SERVER=tcp:host.docker.internal:{PULSE_PORT}",
                *term_env_flags,
                image,
            ]
            subprocess.run(create_cmd, env=env, check=True)

        subprocess.run(["docker", "start", container_name], env=env, check=True, capture_output=True)
        apply_dynamic_config(container_name, env, csb_dev_networks_env, dev_hosts)
        if agent_vault:
            install_agent_vault_ca(container_name, env)

        result = subprocess.run(["docker", "attach", container_name], env=env)
        sys.exit(result.returncode)
    finally:
        daemon.terminate()
        daemon.wait()
        if pulse:
            pulse.terminate()
            pulse.wait()


if __name__ == "__main__":
    main()
