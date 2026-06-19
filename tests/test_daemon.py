import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from daemon_logic import is_allowed, is_blocked, translate_cwd


# ---------------------------------------------------------------------------
# is_blocked
# ---------------------------------------------------------------------------

class TestIsBlocked:
    def test_exec_with_env(self):
        assert is_blocked(["docker", "exec", "app", "env"])

    def test_exec_with_printenv(self):
        assert is_blocked(["docker", "exec", "app", "printenv"])

    def test_exec_with_sh(self):
        assert is_blocked(["docker", "exec", "app", "sh"])

    def test_exec_with_bash(self):
        assert is_blocked(["docker", "exec", "app", "bash"])

    def test_exec_with_bin_sh(self):
        assert is_blocked(["docker", "exec", "app", "/bin/sh"])

    def test_exec_with_bin_bash(self):
        assert is_blocked(["docker", "exec", "app", "/bin/bash"])

    def test_secret_command(self):
        assert is_blocked(["docker", "secret", "ls"])

    def test_exec_rails_not_blocked(self):
        assert not is_blocked(["docker", "exec", "app", "bundle", "exec", "rails", "db:migrate"])

    def test_compose_up_not_blocked(self):
        assert not is_blocked(["docker", "compose", "up", "-d"])

    def test_ps_not_blocked(self):
        assert not is_blocked(["docker", "ps"])


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
