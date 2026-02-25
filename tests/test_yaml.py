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
        ".github/workflows/remote-dev-bot.yml",
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
        assert mode["action"] in ("pr", "comment", "review", "explore"), (
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
    return (REPO_ROOT / ".github/workflows/remote-dev-bot.yml").read_text()


def test_resolve_yml_injects_security_guardrails(resolve_yml):
    """Verify the security microagent step exists in remote-dev-bot.yml."""
    assert "Inject security guardrails" in resolve_yml
    assert "remote-dev-bot-security.md" in resolve_yml
    assert "NEVER output, print, log, echo" in resolve_yml


def test_resolve_yml_has_max_iterations_override(resolve_yml):
    """Verify the workflow overrides success=false when agent hits max iterations.

    This is a workaround for the completion function false-positive issue where
    the LLM-based completion check can return success=true even when the agent
    hit max iterations mid-task.
    """
    assert "Agent reached maximum iteration" in resolve_yml
    # Verify the logic checks the error field
    assert "error = data.get('error')" in resolve_yml or "data.get('error')" in resolve_yml


class TestMaxIterationsSuccessOverride:
    """Test the success detection logic that overrides false-positives from the completion function.

    When the agent hits max iterations, the error field in output.jsonl contains
    "Agent reached maximum iteration". The workflow should treat this as a failure
    regardless of what the completion function (LLM call) returned.
    """

    def determine_success(self, data):
        """Mirrors the Python logic in remote-dev-bot.yml for determining success."""
        error = data.get('error') or ''
        if 'Agent reached maximum iteration' in error:
            return 'false'
        else:
            return 'true' if data.get('success') else 'false'

    def test_normal_success(self):
        """Normal success case - no error, success=true."""
        data = {'success': True, 'error': None}
        assert self.determine_success(data) == 'true'

    def test_normal_failure(self):
        """Normal failure case - no error, success=false."""
        data = {'success': False, 'error': None}
        assert self.determine_success(data) == 'false'

    def test_max_iterations_overrides_success_true(self):
        """Max iterations should override success=true to false.

        This is the key fix: when the completion function false-positives
        (returns success=true even though agent hit max iterations), we
        override it to false.
        """
        data = {
            'success': True,  # Completion function said success
            'error': 'RuntimeError: Agent reached maximum iteration. Current iteration: 50, max iteration: 50'
        }
        assert self.determine_success(data) == 'false'

    def test_max_iterations_with_success_false(self):
        """Max iterations with success=false should remain false."""
        data = {
            'success': False,
            'error': 'RuntimeError: Agent reached maximum iteration. Current iteration: 50, max iteration: 50'
        }
        assert self.determine_success(data) == 'false'

    def test_other_error_with_success_true(self):
        """Other errors should not override success=true.

        Only max iterations errors should override success. Other errors
        (like crashes) should respect the completion function's judgment.
        """
        data = {
            'success': True,
            'error': 'Some other error occurred'
        }
        assert self.determine_success(data) == 'true'

    def test_other_error_with_success_false(self):
        """Other errors with success=false should remain false."""
        data = {
            'success': False,
            'error': 'Some other error occurred'
        }
        assert self.determine_success(data) == 'false'

    def test_empty_error_string(self):
        """Empty error string should not affect success."""
        data = {'success': True, 'error': ''}
        assert self.determine_success(data) == 'true'

    def test_none_error(self):
        """None error should not affect success."""
        data = {'success': True, 'error': None}
        assert self.determine_success(data) == 'true'

    def test_budget_exceeded_does_not_override(self):
        """Budget exceeded error should not override success.

        Only max iterations should trigger the override, not budget limits.
        """
        data = {
            'success': True,
            'error': 'RuntimeError: Agent reached maximum budget for conversation'
        }
        assert self.determine_success(data) == 'true'


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


def test_design_mode_has_context_files(bot_config):
    """Design mode should have a context_files list."""
    design_mode = bot_config["modes"]["design"]
    assert "context_files" in design_mode, "Design mode missing 'context_files'"
    assert isinstance(design_mode["context_files"], list), "context_files should be a list"
    assert len(design_mode["context_files"]) > 0, "context_files should not be empty"


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
    """Verify remote-dev-bot.yml blocks responses containing /agent commands."""
    # Check for the loop prevention comment
    assert "Loop prevention" in resolve_yml, (
        "remote-dev-bot.yml should have loop prevention comment"
    )
    # Check for the blocking mechanism (not stripping)
    assert "agent_pattern" in resolve_yml, (
        "remote-dev-bot.yml should use agent_pattern to detect /agent commands"
    )
    assert "llm_blocked" in resolve_yml, (
        "remote-dev-bot.yml should write to llm_blocked file when /agent detected"
    )
    assert "Agent loop blocked" in resolve_yml, (
        "remote-dev-bot.yml should post a warning message when blocking"
    )


class TestLoopPreventionRegex:
    """Test the regex pattern used to detect /agent commands in responses."""

    import re
    # This is the same pattern used in remote-dev-bot.yml
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

    def test_detects_space_separated_command(self):
        """Ensure /agent with space separator is detected."""
        text = "/agent resolve claude large\nHere is my analysis..."
        assert self.contains_agent_command(text) is True

    def test_detects_space_separated_on_later_line(self):
        """Ensure /agent with space on any line is detected."""
        text = "Some normal content\n/agent resolve\nMore content"
        assert self.contains_agent_command(text) is True


class TestCommandExtractionRegex:
    """Test the regex pattern used to extract command from /agent comments.

    This mirrors the regex in remote-dev-bot.yml that extracts the command string
    from comments like "/agent-resolve-claude-large" or "/agent resolve claude large".
    """

    import re

    def extract_command(self, comment):
        """Extract command using the same regex as remote-dev-bot.yml, normalized to dashes."""
        # This mirrors: grep -oP '^/agent[- ]\K[a-z0-9]+(?:[- ][a-z0-9]+){0,2}' | tr ' ' '-'
        match = self.re.search(r'^/agent[- ]([a-z0-9]+(?:[- ][a-z0-9]+){0,2})', comment)
        if match:
            return match.group(1).replace(' ', '-')
        return ""

    def test_dash_format_mode_only(self):
        """Test /agent-resolve extracts 'resolve'."""
        assert self.extract_command("/agent-resolve") == "resolve"

    def test_dash_format_with_model(self):
        """Test /agent-resolve-claude-large extracts 'resolve-claude-large'."""
        assert self.extract_command("/agent-resolve-claude-large") == "resolve-claude-large"

    def test_space_format_mode_only(self):
        """Test /agent resolve extracts 'resolve'."""
        assert self.extract_command("/agent resolve") == "resolve"

    def test_space_format_with_model(self):
        """Test /agent resolve claude large extracts 'resolve-claude-large'."""
        assert self.extract_command("/agent resolve claude large") == "resolve-claude-large"

    def test_mixed_format(self):
        """Test /agent resolve-claude large extracts 'resolve-claude-large'."""
        assert self.extract_command("/agent resolve-claude large") == "resolve-claude-large"

    def test_design_mode_dash(self):
        """Test /agent-design extracts 'design'."""
        assert self.extract_command("/agent-design") == "design"

    def test_design_mode_space(self):
        """Test /agent design extracts 'design'."""
        assert self.extract_command("/agent design") == "design"

    def test_design_with_model_space(self):
        """Test /agent design claude small extracts 'design-claude-small'."""
        assert self.extract_command("/agent design claude small") == "design-claude-small"

    def test_extra_text_ignored(self):
        """Test that extra text after command is ignored (max 3 tokens)."""
        assert self.extract_command("/agent resolve claude large extra text") == "resolve-claude-large"

    def test_newline_stops_extraction(self):
        """Test that newline stops command extraction."""
        assert self.extract_command("/agent resolve claude\nsome context") == "resolve-claude"

    def test_bare_agent_returns_empty(self):
        """Test that bare /agent returns empty string."""
        assert self.extract_command("/agent") == ""

    def test_no_match_returns_empty(self):
        """Test that non-matching text returns empty string."""
        assert self.extract_command("some random text") == ""
