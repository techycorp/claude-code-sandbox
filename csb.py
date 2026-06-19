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
    print("    colima start csb --cpu 4 --memory 4 --disk 20 \\", file=sys.stderr)
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
    """User-specified CIDRs (e.g. another Colima VM's vmnet network) to allow
    through the sandbox's firewall. Set explicitly in config.toml — not
    auto-detected, since guessing which VM is "the dev one" is unreliable."""
    return config.get("dev_networks", [])


def get_dev_hosts(config):
    """User-specified hostname:ip pairs to add to /etc/hosts inside the
    container, e.g. for app-specific domains that resolve to a dev VM."""
    return config.get("dev_hosts", [])


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
