"""Tests for YAML file validity and structural requirements."""

import os
from pathlib import Path

import pytest
import yaml

from lib.config import KNOWN_PROVIDERS

# Repo root relative to this test file
REPO_ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


# --- YAML files parse without errors ---


@pytest.mark.parametrize(
    "path",
    [
        "remote-dev-bot.yaml",
        ".github/workflows/resolve.yml",
        ".github/workflows/agent.yml",
    ],
)
def test_yaml_parses(path):
    full = REPO_ROOT / path
    if not full.exists():
        pytest.skip(f"{path} not found")
    load_yaml(full)


# --- remote-dev-bot.yaml structural validation ---


@pytest.fixture
def bot_config():
    return load_yaml(REPO_ROOT / "remote-dev-bot.yaml")


def test_config_has_required_keys(bot_config):
    assert "default_model" in bot_config
    assert "models" in bot_config
    assert "modes" in bot_config
    assert "openhands" in bot_config


def test_default_model_exists_in_models(bot_config):
    default = bot_config["default_model"]
    assert default in bot_config["models"], (
        f"default_model '{default}' not in models"
    )


def test_modes_have_action(bot_config):
    for name, mode in bot_config["modes"].items():
        assert "action" in mode, f"Mode '{name}' missing 'action' field"
        assert mode["action"] in ("pr", "comment"), (
            f"Mode '{name}' has unknown action '{mode['action']}'"
        )


def test_mode_default_models_exist(bot_config):
    models = bot_config["models"]
    for name, mode in bot_config["modes"].items():
        if "default_model" in mode:
            assert mode["default_model"] in models, (
                f"Mode '{name}' default_model '{mode['default_model']}' not in models"
            )


def test_every_model_has_id(bot_config):
    for alias, info in bot_config["models"].items():
        assert "id" in info, f"Model alias '{alias}' missing 'id' field"


def test_every_model_id_has_known_provider(bot_config):
    for alias, info in bot_config["models"].items():
        model_id = info["id"]
        assert any(model_id.startswith(p) for p in KNOWN_PROVIDERS), (
            f"Model '{alias}' has id '{model_id}' with unknown provider. "
            f"Expected one of: {KNOWN_PROVIDERS}"
        )


def test_openhands_has_version(bot_config):
    assert "version" in bot_config["openhands"]


def test_openhands_has_max_iterations(bot_config):
    assert "max_iterations" in bot_config["openhands"]
    assert isinstance(bot_config["openhands"]["max_iterations"], int)


# --- Security checks ---


@pytest.fixture
def resolve_yml():
    return (REPO_ROOT / ".github/workflows/resolve.yml").read_text()


def test_resolve_yml_injects_security_guardrails(resolve_yml):
    """Verify the security microagent step exists in resolve.yml."""
    assert "Inject security guardrails" in resolve_yml
    assert "remote-dev-bot-security.md" in resolve_yml
    assert "NEVER output, print, log, echo" in resolve_yml


def test_agent_yml_has_author_association_gate():
    """Verify the shim requires trusted author_association."""
    for path in [
        REPO_ROOT / ".github/workflows/agent.yml",
    ]:
        content = path.read_text()
        assert "author_association" in content
        assert "OWNER" in content
        # Ensure it's a restrictive check, not just a comment
        assert 'fromJson(' in content
        assert 'github.event.comment.author_association' in content


# --- Loop prevention checks ---


def test_design_prompt_has_loop_prevention(bot_config):
    """Verify the design mode prompt instructs LLM not to start with /agent."""
    design_mode = bot_config["modes"]["design"]
    prompt_prefix = design_mode.get("prompt_prefix", "")
    assert "/agent" in prompt_prefix.lower(), (
        "Design mode prompt_prefix should warn against starting with /agent"
    )
    assert "never" in prompt_prefix.lower() or "do not" in prompt_prefix.lower(), (
        "Design mode prompt_prefix should contain prohibition language"
    )


def test_resolve_yml_has_response_validation(resolve_yml):
    """Verify resolve.yml blocks responses containing /agent commands."""
    # Check for the loop prevention comment
    assert "Loop prevention" in resolve_yml, (
        "resolve.yml should have loop prevention comment"
    )
    # Check for the blocking mechanism (not stripping)
    assert "agent_pattern" in resolve_yml, (
        "resolve.yml should use agent_pattern to detect /agent commands"
    )
    assert "llm_blocked" in resolve_yml, (
        "resolve.yml should write to llm_blocked file when /agent detected"
    )
    assert "Agent loop blocked" in resolve_yml, (
        "resolve.yml should post a warning message when blocking"
    )


class TestLoopPreventionRegex:
    """Test the regex pattern used to detect /agent commands in responses."""

    import re
    # This is the same pattern used in resolve.yml
    PATTERN = re.compile(r'^/agent', re.MULTILINE)

    def contains_agent_command(self, text):
        """Returns True if text contains /agent at start of any line."""
        return bool(self.PATTERN.search(text))

    def test_detects_single_agent_command(self):
        text = "/agent-design-claude-large\nHere is my analysis..."
        assert self.contains_agent_command(text) is True

    def test_detects_multiple_agent_commands(self):
        text = "/agent-resolve\n/agent-design\nActual content"
        assert self.contains_agent_command(text) is True

    def test_ignores_agent_in_middle_of_text(self):
        text = "You can use /agent-resolve to trigger the bot."
        assert self.contains_agent_command(text) is False

    def test_ignores_normal_response(self):
        text = "Here is my thoughtful analysis of the issue..."
        assert self.contains_agent_command(text) is False

    def test_detects_agent_with_various_suffixes(self):
        text = "/agent-resolve-claude-large\nContent"
        assert self.contains_agent_command(text) is True

    def test_handles_empty_response(self):
        text = ""
        assert self.contains_agent_command(text) is False

    def test_detects_bare_agent_command(self):
        text = "/agent\nSome content"
        assert self.contains_agent_command(text) is True

    def test_detects_agent_on_later_line(self):
        """Ensure /agent on any line (not just first) is detected."""
        text = "Some normal content\n/agent-resolve\nMore content"
        assert self.contains_agent_command(text) is True

    def test_detects_bypass_attempt(self):
        """Ensure /agent/agent bypass attempt is detected."""
        text = "/agent/agent-resolve\nContent"
        assert self.contains_agent_command(text) is True
