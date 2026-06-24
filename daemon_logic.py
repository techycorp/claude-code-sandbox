import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "claude-code-sandbox" / "config.toml"


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


def is_allowed(args, allowed):
    """Match args against an allowlist pattern, prefix-style, by token.

    Each non-wildcard pattern token must equal the corresponding arg
    exactly; '*' matches exactly one arbitrary token. The pattern must align
    with a contiguous prefix of args — trailing args beyond the pattern's
    length are fine (e.g. task names like 'db:migrate', package names like
    'leaflet'), but nothing can be inserted ahead of or inside the pattern's
    own tokens.

    This closes the bug where a wildcard's approved suffix could be
    satisfied by an unrelated real command sitting in the wildcard's
    position, with the suffix just riding along as that command's own
    trailing arguments (e.g. "docker exec app zsh -c '...' bundle exec
    rspec" used to pass a "docker exec * bundle exec rspec" allowlist
    entry, even though the command actually executed was `zsh -c '...'`).

    What this does NOT do: vet what a whitelisted program is itself capable
    of once it's running. A pattern like "docker exec * bundle exec rails"
    pins the program to `bundle exec rails`, but any trailing args
    (including `runner "<arbitrary ruby>"`) are still passed through as
    arguments to that already-approved program. Enumerate exact safe
    subcommands in config.toml instead of leaving such prefixes open — see
    the README's "The Whitelist Is the Ultimate Authority" section.
    """
    for pattern in allowed:
        pattern_tokens = pattern.split()
        if len(args) < len(pattern_tokens):
            continue
        if all(p == "*" or p == a for p, a in zip(pattern_tokens, args)):
            return True
    return False
