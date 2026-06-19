import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "claude-code-sandbox" / "config.toml"

BLOCKED = [
    lambda args: "exec" in args and any(x in args for x in ["env", "printenv", "sh", "bash", "/bin/sh", "/bin/bash"]),
    lambda args: "secret" in args,
]


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def load_allowed():
    return load_config().get("proxy", {}).get("allowed_commands", [])


def translate_cwd(cwd: str) -> str:
    # Container paths match host paths — no translation needed
    return cwd if cwd else None


def is_blocked(args):
    return any(check(args) for check in BLOCKED)


def is_allowed(args, allowed):
    full_command = " ".join(args)
    for pattern in allowed:
        if "*" not in pattern:
            if full_command == pattern or full_command.startswith(pattern + " "):
                return True
        else:
            parts = pattern.split("*")
            pos = 0
            matched = True
            for i, part in enumerate(parts):
                if i == 0:
                    if not full_command.startswith(part):
                        matched = False
                        break
                    pos = len(part)
                elif i == len(parts) - 1:
                    idx = full_command.find(part, pos)
                    if idx == -1:
                        matched = False
                        break
                    pos = idx + len(part)
                else:
                    idx = full_command.find(part, pos)
                    if idx == -1:
                        matched = False
                        break
                    pos = idx + len(part)
            if matched:
                return True
    return False
