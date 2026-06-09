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
        assert is_blocked(["podman", "exec", "app", "env"])

    def test_exec_with_printenv(self):
        assert is_blocked(["podman", "exec", "app", "printenv"])

    def test_exec_with_sh(self):
        assert is_blocked(["podman", "exec", "app", "sh"])

    def test_exec_with_bash(self):
        assert is_blocked(["podman", "exec", "app", "bash"])

    def test_exec_with_bin_sh(self):
        assert is_blocked(["podman", "exec", "app", "/bin/sh"])

    def test_exec_with_bin_bash(self):
        assert is_blocked(["podman", "exec", "app", "/bin/bash"])

    def test_secret_command(self):
        assert is_blocked(["podman", "secret", "ls"])

    def test_docker_secret(self):
        assert is_blocked(["docker", "secret", "inspect", "mykey"])

    def test_exec_rails_not_blocked(self):
        assert not is_blocked(["podman", "exec", "app", "bundle", "exec", "rails", "db:migrate"])

    def test_compose_up_not_blocked(self):
        assert not is_blocked(["podman", "compose", "up", "-d"])

    def test_ps_not_blocked(self):
        assert not is_blocked(["podman", "ps"])


# ---------------------------------------------------------------------------
# is_allowed — exact prefix matching
# ---------------------------------------------------------------------------

class TestIsAllowedExact:
    def test_exact_match(self):
        assert is_allowed(["podman", "ps"], ["podman ps"])

    def test_prefix_match_with_flags(self):
        assert is_allowed(["podman", "compose", "up", "-d"], ["podman compose up"])

    def test_no_match(self):
        assert not is_allowed(["podman", "exec", "app", "env"], ["podman compose up"])

    def test_empty_allowed(self):
        assert not is_allowed(["podman", "ps"], [])

    def test_multiple_patterns_first_matches(self):
        assert is_allowed(["podman", "ps"], ["podman ps", "podman images"])

    def test_multiple_patterns_second_matches(self):
        assert is_allowed(["podman", "images"], ["podman ps", "podman images"])

    def test_partial_word_no_match(self):
        assert not is_allowed(["podman", "ps", "-a"], ["podman p"])

    def test_compose_down(self):
        assert is_allowed(["podman", "compose", "down"], ["podman compose down"])

    def test_docker_compose_up(self):
        assert is_allowed(["docker", "compose", "up", "-d"], ["docker compose up"])


# ---------------------------------------------------------------------------
# is_allowed — wildcard matching
# ---------------------------------------------------------------------------

class TestIsAllowedWildcard:
    def test_wildcard_container_name(self):
        assert is_allowed(
            ["podman", "exec", "mordor_app", "bundle", "exec", "rails", "db:migrate"],
            ["podman exec * bundle exec rails"]
        )

    def test_wildcard_different_container(self):
        assert is_allowed(
            ["podman", "exec", "moria_app", "bundle", "exec", "rails", "db:create"],
            ["podman exec * bundle exec rails"]
        )

    def test_wildcard_rspec(self):
        assert is_allowed(
            ["podman", "exec", "mordor_app", "bundle", "exec", "rspec", "spec/models/"],
            ["podman exec * bundle exec rspec"]
        )

    def test_wildcard_does_not_match_wrong_command(self):
        assert not is_allowed(
            ["podman", "exec", "mordor_app", "bundle", "exec", "rake"],
            ["podman exec * bundle exec rails"]
        )

    def test_wildcard_does_not_match_env(self):
        assert not is_allowed(
            ["podman", "exec", "mordor_app", "env"],
            ["podman exec * bundle exec rails"]
        )

    def test_wildcard_multiple_tasks(self):
        assert is_allowed(
            ["podman", "exec", "mordor_app", "bundle", "exec", "rails", "db:create", "db:migrate"],
            ["podman exec * bundle exec rails"]
        )

    def test_wildcard_docker(self):
        assert is_allowed(
            ["docker", "exec", "my_app", "bundle", "exec", "rails", "console"],
            ["docker exec * bundle exec rails"]
        )


# ---------------------------------------------------------------------------
# translate_cwd
# ---------------------------------------------------------------------------

class TestTranslateCwd:
    def workspace_map(self):
        return {
            "/workspaces/techycorp": "/Users/venky/src/techycorp",
            "/workspaces/foo": "/Users/venky/src/foo",
        }

    def test_exact_workspace_root(self):
        assert translate_cwd("/workspaces/techycorp", self.workspace_map()) == "/Users/venky/src/techycorp"

    def test_subdir(self):
        assert translate_cwd("/workspaces/techycorp/mordor", self.workspace_map()) == "/Users/venky/src/techycorp/mordor"

    def test_deep_subdir(self):
        assert translate_cwd("/workspaces/techycorp/mordor/app/models", self.workspace_map()) == "/Users/venky/src/techycorp/mordor/app/models"

    def test_second_workspace(self):
        assert translate_cwd("/workspaces/foo/bar", self.workspace_map()) == "/Users/venky/src/foo/bar"

    def test_unknown_path_returns_none(self):
        assert translate_cwd("/workspaces/unknown/path", self.workspace_map()) is None

    def test_non_workspace_path_returns_none(self):
        assert translate_cwd("/home/node/.claude", self.workspace_map()) is None

    def test_partial_name_no_match(self):
        assert translate_cwd("/workspaces/tech/something", self.workspace_map()) is None
