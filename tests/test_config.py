"""Tests for lib/config.py — config parsing, command parsing, and model resolution."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest
import yaml

from lib.config import (
    deep_merge,
    detect_api_provider,
    main,
    normalize_arg_name,
    parse_args,
    parse_command,
    parse_invocation,
    resolve_config,
    resolve_commit_trailer,
)


# --- deep_merge ---


def test_deep_merge_basic():
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    assert deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99, "z": 100}}
    result = deep_merge(base, override)
    assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}


def test_deep_merge_new_keys():
    base = {"a": 1}
    override = {"b": {"nested": True}}
    assert deep_merge(base, override) == {"a": 1, "b": {"nested": True}}


def test_deep_merge_empty_override():
    base = {"a": 1, "b": {"c": 2}}
    assert deep_merge(base, {}) == base


def test_deep_merge_empty_base():
    override = {"a": 1}
    assert deep_merge({}, override) == {"a": 1}


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"x": 1}}
    override = {"a": {"x": 2}}
    deep_merge(base, override)
    assert base == {"a": {"x": 1}}


# --- detect_api_provider ---


def test_detect_api_provider_anthropic():
    assert detect_api_provider("anthropic/claude-sonnet-4-5") == "anthropic"


def test_detect_api_provider_openai():
    assert detect_api_provider("openai/gpt-5-nano") == "openai"


def test_detect_api_provider_gemini():
    assert detect_api_provider("gemini/gemini-2.5-flash") == "gemini"


def test_detect_api_provider_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        detect_api_provider("mistral/mixtral-8x7b")


# --- parse_command ---

KNOWN_MODES = {"resolve", "design", "review"}


def test_parse_command_resolve():
    assert parse_command("resolve", KNOWN_MODES) == ("resolve", "")


def test_parse_command_resolve_with_model():
    assert parse_command("resolve-claude-large", KNOWN_MODES) == ("resolve", "claude-large")


def test_parse_command_design():
    assert parse_command("design", KNOWN_MODES) == ("design", "")


def test_parse_command_design_with_model():
    assert parse_command("design-claude-large", KNOWN_MODES) == ("design", "claude-large")


def test_parse_command_review():
    assert parse_command("review", KNOWN_MODES) == ("review", "")


def test_parse_command_review_with_model():
    assert parse_command("review-claude-large", KNOWN_MODES) == ("review", "claude-large")


def test_parse_command_multi_segment_model():
    """Model aliases with hyphens should be preserved."""
    assert parse_command("resolve-gpt-large", KNOWN_MODES) == ("resolve", "gpt-large")


def test_parse_command_bare_agent_errors():
    """Empty command string (bare /agent) should raise ValueError."""
    with pytest.raises(ValueError, match="Bare /agent is not supported"):
        parse_command("", KNOWN_MODES)


def test_parse_command_unknown_mode():
    with pytest.raises(ValueError, match="Unknown mode"):
        parse_command("frobnicate", KNOWN_MODES)


def test_parse_command_unknown_mode_with_model():
    """Even with a model suffix, an unknown verb is an error."""
    with pytest.raises(ValueError, match="Unknown mode"):
        parse_command("frobnicate-claude-large", KNOWN_MODES)


def test_parse_command_case_insensitive_mode():
    """Commands should be case-insensitive."""
    assert parse_command("Resolve", KNOWN_MODES) == ("resolve", "")
    assert parse_command("RESOLVE", KNOWN_MODES) == ("resolve", "")
    assert parse_command("Design", KNOWN_MODES) == ("design", "")
    assert parse_command("DESIGN", KNOWN_MODES) == ("design", "")


def test_parse_command_case_insensitive_model():
    """Model aliases should be normalized to lowercase."""
    assert parse_command("resolve-Claude-Large", KNOWN_MODES) == ("resolve", "claude-large")
    assert parse_command("resolve-CLAUDE-LARGE", KNOWN_MODES) == ("resolve", "claude-large")
    assert parse_command("design-OpenAI-Small", KNOWN_MODES) == ("design", "openai-small")


def test_parse_command_case_insensitive_mixed():
    """Mixed case in both mode and model should work."""
    assert parse_command("Resolve-Claude-Large", KNOWN_MODES) == ("resolve", "claude-large")
    assert parse_command("DESIGN-openai-SMALL", KNOWN_MODES) == ("design", "openai-small")


# --- normalize_arg_name ---


def test_normalize_arg_name_spaces():
    """Spaces should be converted to underscores."""
    assert normalize_arg_name("max iterations") == "max_iterations"
    assert normalize_arg_name("extra files") == "extra_files"


def test_normalize_arg_name_dashes():
    """Dashes should be converted to underscores."""
    assert normalize_arg_name("max-iterations") == "max_iterations"
    assert normalize_arg_name("extra-files") == "extra_files"


def test_normalize_arg_name_mixed():
    """Mixed separators should all become underscores."""
    assert normalize_arg_name("max-iterations count") == "max_iterations_count"


def test_normalize_arg_name_case():
    """Names should be lowercased."""
    assert normalize_arg_name("Max_Iterations") == "max_iterations"
    assert normalize_arg_name("CONTEXT") == "context"


def test_normalize_arg_name_whitespace():
    """Leading/trailing whitespace should be stripped."""
    assert normalize_arg_name("  max iterations  ") == "max_iterations"


# --- parse_args ---


def test_parse_args_empty():
    """Empty list should return empty dict."""
    assert parse_args([]) == {}


def test_parse_args_max_iterations():
    """max_iterations should be parsed as int."""
    assert parse_args(["max iterations = 75"]) == {"max_iterations": 75}
    assert parse_args(["max-iterations = 100"]) == {"max_iterations": 100}
    assert parse_args(["max_iterations=50"]) == {"max_iterations": 50}


def test_parse_args_branch():
    """branch should be parsed as str."""
    assert parse_args(["branch = design/gemini"]) == {"branch": "design/gemini"}
    assert parse_args(["branch = my-feature"]) == {"branch": "my-feature"}


def test_parse_args_target_branch_backcompat():
    """target_branch is still accepted as a BACKCOMPAT alias for branch."""
    assert parse_args(["target_branch = design/gemini"]) == {"target_branch": "design/gemini"}
    assert parse_args(["target branch = my-feature"]) == {"target_branch": "my-feature"}


def test_parse_args_extra_files():
    """extra_files should be parsed as list (various normalized name forms)."""
    assert parse_args(["extra_files = file1.txt file2.txt"]) == {"extra_files": ["file1.txt", "file2.txt"]}
    assert parse_args(["extra files = README.md"]) == {"extra_files": ["README.md"]}
    assert parse_args(["extra-files = a.txt b.txt c.txt"]) == {"extra_files": ["a.txt", "b.txt", "c.txt"]}


def test_parse_args_multiple():
    """Multiple args should all be parsed."""
    result = parse_args([
        "max iterations = 75",
        "extra_files = file1.txt file2.txt",
    ])
    assert result == {
        "max_iterations": 75,
        "extra_files": ["file1.txt", "file2.txt"],
    }


def test_parse_args_skip_empty_lines():
    """Empty lines should be skipped."""
    result = parse_args([
        "",
        "max iterations = 75",
        "",
        "extra_files = file.txt",
        "",
    ])
    assert result == {
        "max_iterations": 75,
        "extra_files": ["file.txt"],
    }


def test_parse_args_skip_comments():
    """Lines starting with # should be skipped."""
    result = parse_args([
        "# This is a comment",
        "max iterations = 75",
        "# Another comment",
    ])
    assert result == {"max_iterations": 75}


def test_parse_args_skip_lines_without_equals():
    """Lines without = should be skipped."""
    result = parse_args([
        "max iterations = 75",
        "some random text",
        "extra_files = file.txt",
    ])
    assert result == {
        "max_iterations": 75,
        "extra_files": ["file.txt"],
    }


def test_parse_args_unknown_arg():
    """Unknown args should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown argument"):
        parse_args(["unknown_arg = value"])


def test_parse_args_invalid_int():
    """Non-integer value for int arg should raise ValueError."""
    with pytest.raises(ValueError, match="must be an integer"):
        parse_args(["max iterations = not_a_number"])


def test_parse_args_empty_name():
    """Lines with empty name after = should be skipped."""
    result = parse_args(["= value", "max iterations = 75"])
    assert result == {"max_iterations": 75}


def test_parse_args_empty_value():
    """Lines with empty value after = should be skipped."""
    result = parse_args(["max iterations =", "extra_files = file.txt"])
    assert result == {"extra_files": ["file.txt"]}


def test_parse_args_whitespace_only_name():
    """Lines with whitespace-only name should be skipped."""
    result = parse_args(["   = value", "max iterations = 75"])
    assert result == {"max_iterations": 75}


def test_parse_args_whitespace_only_value():
    """Lines with whitespace-only value should be skipped."""
    result = parse_args(["max iterations =   ", "extra_files = file.txt"])
    assert result == {"extra_files": ["file.txt"]}




def test_parse_args_skip_empty_name_or_value():
    """Lines with '=' but empty name or empty value are silently skipped."""
    # Empty name: "= value" — normalize_arg_name("") → "" → skip
    assert parse_args(["= some_value"]) == {}
    # Empty value: "name =" — value.strip() == "" → skip
    assert parse_args(["max_iterations ="]) == {}
    # Both empty
    assert parse_args(["="]) == {}
# --- parse_invocation ---


def test_parse_invocation_simple():
    """Simple command without args."""
    assert parse_invocation("/agent resolve", KNOWN_MODES) == ("resolve", "", {})
    assert parse_invocation("/agent design", KNOWN_MODES) == ("design", "", {})


def test_parse_invocation_with_model():
    """Command with model alias."""
    assert parse_invocation("/agent resolve claude-large", KNOWN_MODES) == ("resolve", "claude-large", {})
    assert parse_invocation("/agent-resolve-claude-large", KNOWN_MODES) == ("resolve", "claude-large", {})


def test_parse_invocation_with_args():
    """Command with args on subsequent lines."""
    comment = "/agent resolve\nmax iterations = 75"
    assert parse_invocation(comment, KNOWN_MODES) == ("resolve", "", {"max_iterations": 75})


def test_parse_invocation_with_model_and_args():
    """Command with model and args."""
    comment = "/agent resolve claude-large\nmax iterations = 100\nextra_files = file.txt"
    mode, alias, args = parse_invocation(comment, KNOWN_MODES)
    assert mode == "resolve"
    assert alias == "claude-large"
    assert args == {"max_iterations": 100, "extra_files": ["file.txt"]}


def test_parse_invocation_dash_syntax():
    """Dash syntax should work with args."""
    comment = "/agent-design-claude-small\nextra_files = a.txt b.txt"
    mode, alias, args = parse_invocation(comment, KNOWN_MODES)
    assert mode == "design"
    assert alias == "claude-small"
    assert args == {"extra_files": ["a.txt", "b.txt"]}


def test_parse_invocation_space_syntax():
    """Space syntax should work with args."""
    comment = "/agent design claude small\nmax iterations = 50"
    mode, alias, args = parse_invocation(comment, KNOWN_MODES)
    assert mode == "design"
    assert alias == "claude-small"
    assert args == {"max_iterations": 50}


def test_parse_invocation_case_insensitive():
    """Command should be case-insensitive."""
    comment = "/agent RESOLVE Claude-Large\nmax iterations = 75"
    mode, alias, args = parse_invocation(comment, KNOWN_MODES)
    assert mode == "resolve"
    assert alias == "claude-large"
    assert args == {"max_iterations": 75}


def test_parse_invocation_bare_agent():
    """Bare /agent should raise ValueError."""
    with pytest.raises(ValueError, match="Bare /agent is not supported"):
        parse_invocation("/agent", KNOWN_MODES)


def test_parse_invocation_unknown_mode():
    """Unknown mode should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown mode"):
        parse_invocation("/agent frobnicate", KNOWN_MODES)


def test_parse_invocation_custom_prefix():
    """Custom command_prefix replaces 'agent' in the expected slash command."""
    assert parse_invocation("/dogfood resolve", KNOWN_MODES, "dogfood") == ("resolve", "", {})
    assert parse_invocation("/dogfood-resolve-claude-large", KNOWN_MODES, "dogfood") == ("resolve", "claude-large", {})


def test_parse_invocation_custom_prefix_with_args():
    """Custom prefix with inline args on subsequent lines."""
    comment = "/dogfood-resolve\nmax iterations = 75"
    assert parse_invocation(comment, KNOWN_MODES, "dogfood") == ("resolve", "", {"max_iterations": 75})


def test_parse_invocation_bare_custom_prefix():
    """Bare /dogfood raises ValueError naming the custom prefix."""
    with pytest.raises(ValueError, match="Bare /dogfood"):
        parse_invocation("/dogfood", KNOWN_MODES, "dogfood")


def test_parse_invocation_wrong_prefix():
    """Comment using the wrong prefix raises 'Invalid command format'."""
    with pytest.raises(ValueError, match="Invalid command format"):
        parse_invocation("/agent resolve", KNOWN_MODES, "dogfood")


# --- resolve_config ---


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp dir with base config files including modes."""
    base = tmp_path / "base"
    base.mkdir()
    config = {
        "default_model": "claude-small",
        "models": {
            "claude-small": {"id": "anthropic/claude-sonnet-4-5"},
            "claude-large": {"id": "anthropic/claude-opus-4-5"},
            "gpt-small": {"id": "openai/gpt-5.1-codex-mini"},
        },
        "modes": {
            "resolve": {
                "action": "pr",
                "default_model": "claude-small",
            },
            "design": {
                "action": "comment",
                "default_model": "claude-small",
                "extra_instructions": "Focus on scalability.",
            },
            "review": {
                "action": "review",
                "default_model": "claude-small",
            },
            "design_agentic": {
                "action": "design",
                "default_model": "claude-small",
                "max_iterations": 10,
                "extra_instructions": "You are exploring this issue.",
                "extra_files": ["README.md", "AGENTS.md"],
            },
        },
        "agent": {
            "max_iterations": 50,
            "pr_type": "ready",
        },
    }
    (base / "remote-dev-bot.yaml").write_text(yaml.dump(config))
    return tmp_path, str(base / "remote-dev-bot.yaml")


def test_resolve_config_resolve_default_model(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["mode"] == "resolve"
    assert result["action"] == "pr"
    assert result["alias"] == "claude-small"
    assert result["model"] == "anthropic/claude-sonnet-4-5"


def test_resolve_config_resolve_explicit_model(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve-claude-large")
    assert result["mode"] == "resolve"
    assert result["alias"] == "claude-large"
    assert result["model"] == "anthropic/claude-opus-4-5"


def test_resolve_config_design_mode(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "design")
    assert result["mode"] == "design"
    assert result["action"] == "comment"
    assert result["alias"] == "claude-small"
    assert "extra_instructions" in result
    assert "scalability" in result["extra_instructions"]


def test_resolve_config_design_with_model(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "design-claude-large")
    assert result["mode"] == "design"
    assert result["alias"] == "claude-large"
    assert result["model"] == "anthropic/claude-opus-4-5"


def test_resolve_config_review_mode(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "review")
    assert result["mode"] == "review"
    assert result["action"] == "review"
    assert result["alias"] == "claude-small"
    assert result["model"] == "anthropic/claude-sonnet-4-5"


def test_resolve_config_review_with_model(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "review-claude-large")
    assert result["mode"] == "review"
    assert result["alias"] == "claude-large"


def test_resolve_config_design_agentic_mode(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "design_agentic")
    assert result["mode"] == "design_agentic"
    assert result["action"] == "design"
    assert result["alias"] == "claude-small"
    assert result["model"] == "anthropic/claude-sonnet-4-5"
    assert "extra_instructions" in result
    assert "exploring" in result["extra_instructions"]
    assert "extra_files" in result
    assert result["extra_files"] == ["README.md", "AGENTS.md"]
    assert "design_max_iterations" in result
    assert result["design_max_iterations"] == 10


def test_resolve_config_design_agentic_with_model(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "design_agentic-claude-large")
    assert result["mode"] == "design_agentic"
    assert result["alias"] == "claude-large"
    assert result["model"] == "anthropic/claude-opus-4-5"


def test_resolve_config_unknown_model(config_dir):
    tmp_path, base_path = config_dir
    with pytest.raises(KeyError, match="Unknown model alias"):
        resolve_config(base_path, "nonexistent.yaml", "resolve-does-not-exist")


def test_resolve_config_bare_agent_errors(config_dir):
    tmp_path, base_path = config_dir
    with pytest.raises(ValueError, match="Bare /agent is not supported"):
        resolve_config(base_path, "nonexistent.yaml", "")


def test_resolve_config_unknown_mode(config_dir):
    tmp_path, base_path = config_dir
    with pytest.raises(ValueError, match="Unknown mode"):
        resolve_config(base_path, "nonexistent.yaml", "frobnicate")


def test_resolve_config_override_wins(config_dir):
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    override = {
        "default_model": "gpt-small",
        "modes": {
            "resolve": {"default_model": "gpt-small"},
        },
        "agent": {"max_iterations": 10},
    }
    with open(override_path, "w") as f:
        yaml.dump(override, f)

    result = resolve_config(base_path, override_path, "resolve")
    assert result["alias"] == "gpt-small"
    assert result["model"] == "openai/gpt-5.1-codex-mini"
    assert result["max_iterations"] == 10
    assert result["has_override"] is True


def test_resolve_config_mode_default_model_differs():
    """Each mode can have its own default model."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m1",
                "models": {
                    "m1": {"id": "anthropic/test-1"},
                    "m2": {"id": "anthropic/test-2"},
                },
                "modes": {
                    "resolve": {"action": "pr", "default_model": "m1"},
                    "design": {"action": "comment", "default_model": "m2"},
                },
            },
            f,
        )
        path = f.name
    try:
        r1 = resolve_config(path, "nonexistent.yaml", "resolve")
        r2 = resolve_config(path, "nonexistent.yaml", "design")
        assert r1["alias"] == "m1"
        assert r2["alias"] == "m2"
    finally:
        os.unlink(path)


def test_resolve_config_extra_files_for_design(config_dir):
    """Design mode should include extra_files when configured."""
    tmp_path, base_path = config_dir
    # Add extra_files to the config
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["modes"]["design"]["extra_files"] = ["README.md", "AGENTS.md"]
    with open(base_path, "w") as f:
        yaml.dump(config, f)

    result = resolve_config(base_path, "nonexistent.yaml", "design")
    assert "extra_files" in result
    assert result["extra_files"] == ["README.md", "AGENTS.md"]


def test_resolve_config_no_extra_files_for_resolve(config_dir):
    """Resolve mode should not have extra_files."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert "extra_files" not in result


def test_resolve_config_no_extra_instructions_for_resolve(config_dir):
    """Resolve mode should not have extra_instructions."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert "extra_instructions" not in result


def test_resolve_config_agent_defaults():
    """When base config has no agent section, defaults kick in."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m",
                "models": {"m": {"id": "anthropic/test"}},
                "modes": {"resolve": {"action": "pr"}},
            },
            f,
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["max_iterations"] == 50
        assert result["pr_type"] == "ready"
        assert result["on_failure"] == "comment"
        assert result["target_branch"] == "main"
        assert result["assign_issue"] is True
        assert result["assign_pr"] is True
        assert "oh_version" not in result
    finally:
        os.unlink(path)


def test_resolve_config_openhands_key_backcompat():
    """Config using openhands: key (old name) still works — BACKCOMPAT."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m",
                "models": {"m": {"id": "anthropic/test"}},
                "modes": {"resolve": {"action": "pr"}},
                "openhands": {"max_iterations": 42, "pr_type": "draft"},
            },
            f,
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["max_iterations"] == 42
        assert result["pr_type"] == "draft"
    finally:
        os.unlink(path)


def test_resolve_config_on_failure_default(config_dir):
    """on_failure defaults to 'comment'."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["on_failure"] == "comment"


def test_resolve_config_on_failure_draft(config_dir):
    """on_failure: draft is parsed and returned."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["on_failure"] = "draft"
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["on_failure"] == "draft"


def test_resolve_config_on_failure_invalid(config_dir):
    """on_failure with an unrecognised value raises ValueError."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["on_failure"] = "silently_explode"
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    with pytest.raises(ValueError, match="on_failure"):
        resolve_config(base_path, "nonexistent.yaml", "resolve")


def test_resolve_config_on_failure_via_override(config_dir):
    """on_failure can be overridden at the override layer."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    with open(override_path, "w") as f:
        yaml.dump({"agent": {"on_failure": "draft"}}, f)
    result = resolve_config(base_path, override_path, "resolve")
    assert result["on_failure"] == "draft"


def test_resolve_config_target_branch_default(config_dir):
    """target_branch defaults to 'main'."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["target_branch"] == "main"


def test_resolve_config_branch_key(config_dir):
    """branch key in agent: sets target_branch."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    with open(override_path, "w") as f:
        yaml.dump({"agent": {"branch": "dev"}}, f)
    result = resolve_config(base_path, override_path, "resolve")
    assert result["target_branch"] == "dev"


def test_resolve_config_target_branch_override_backcompat(config_dir):
    """target_branch key in agent: still works — BACKCOMPAT."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    with open(override_path, "w") as f:
        yaml.dump({"agent": {"target_branch": "master"}}, f)
    result = resolve_config(base_path, override_path, "resolve")
    assert result["target_branch"] == "master"


def test_resolve_config_assign_issue_default(config_dir):
    """assign_issue defaults to True."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["assign_issue"] is True


def test_resolve_config_assign_issue_false(config_dir):
    """assign_issue can be set to False."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["assign_issue"] = False
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["assign_issue"] is False


def test_resolve_config_assign_issue_via_override(config_dir):
    """assign_issue can be overridden at the override layer."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    with open(override_path, "w") as f:
        yaml.dump({"agent": {"assign_issue": False}}, f)
    result = resolve_config(base_path, override_path, "resolve")
    assert result["assign_issue"] is False


def test_resolve_config_assign_pr_default(config_dir):
    """assign_pr defaults to True."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["assign_pr"] is True


def test_resolve_config_assign_pr_false(config_dir):
    """assign_pr can be set to False."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["assign_pr"] = False
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["assign_pr"] is False


def test_resolve_config_assign_pr_via_override(config_dir):
    """assign_pr can be overridden at the override layer."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    with open(override_path, "w") as f:
        yaml.dump({"agent": {"assign_pr": False}}, f)
    result = resolve_config(base_path, override_path, "resolve")
    assert result["assign_pr"] is False


def test_resolve_config_malformed_yaml(tmp_path):
    """Malformed YAML should raise an error."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(": this is not valid yaml\n  - broken:\nindent")
    with pytest.raises(yaml.YAMLError):
        resolve_config(str(bad_yaml), "nonexistent.yaml", "resolve")


def test_resolve_config_case_insensitive(config_dir):
    """Commands should be case-insensitive in resolve_config."""
    tmp_path, base_path = config_dir
    # Test uppercase mode
    result = resolve_config(base_path, "nonexistent.yaml", "RESOLVE")
    assert result["mode"] == "resolve"
    assert result["alias"] == "claude-small"

    # Test mixed case mode and model
    result = resolve_config(base_path, "nonexistent.yaml", "Resolve-Claude-Small")
    assert result["mode"] == "resolve"
    assert result["alias"] == "claude-small"
    assert result["model"] == "anthropic/claude-sonnet-4-5"

    # Test all uppercase
    result = resolve_config(base_path, "nonexistent.yaml", "DESIGN-CLAUDE-SMALL")
    assert result["mode"] == "design"
    assert result["alias"] == "claude-small"


# --- resolve_commit_trailer ---


def test_resolve_commit_trailer_basic():
    """Basic template substitution."""
    result = resolve_commit_trailer(
        "Model: {model_alias} ({model_id})",
        "claude-large",
        "anthropic/claude-opus-4-5",
    )
    assert result == "Model: claude-large (anthropic/claude-opus-4-5)"


def test_resolve_commit_trailer_empty_template():
    """Empty template returns empty string."""
    assert resolve_commit_trailer("", "alias", "model") == ""
    assert resolve_commit_trailer(None, "alias", "model") == ""


def test_resolve_commit_trailer_partial_template():
    """Template with only some variables."""
    result = resolve_commit_trailer("Model: {model_alias}", "claude-small", "anthropic/claude-sonnet-4-5")
    assert result == "Model: claude-small"


def test_resolve_commit_trailer_no_variables():
    """Template with no variables."""
    result = resolve_commit_trailer("Static trailer", "alias", "model")
    assert result == "Static trailer"


# --- commit_trailer in resolve_config ---


def test_resolve_config_commit_trailer_default(config_dir):
    """Config without commit_trailer returns empty string."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert "commit_trailer" in result
    assert result["commit_trailer"] == ""


def test_resolve_config_commit_trailer_with_template():
    """Config with commit_trailer template resolves variables."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m1",
                "models": {"m1": {"id": "anthropic/test-model"}},
                "modes": {"resolve": {"action": "pr"}},
                "agent": {"commit_trailer": "Model: {model_alias} ({model_id})"},
            },
            f,
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["commit_trailer"] == "Model: m1 (anthropic/test-model)"
    finally:
        os.unlink(path)


def test_resolve_config_commit_trailer_override():
    """Override config can change commit_trailer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as base_f:
        yaml.dump(
            {
                "default_model": "m1",
                "models": {"m1": {"id": "anthropic/test-model"}},
                "modes": {"resolve": {"action": "pr"}},
                "agent": {"commit_trailer": "Base trailer: {model_alias}"},
            },
            base_f,
        )
        base_path = base_f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as override_f:
        yaml.dump(
            {
                "agent": {"commit_trailer": "Override trailer: {model_id}"},
            },
            override_f,
        )
        override_path = override_f.name

    try:
        result = resolve_config(base_path, override_path, "resolve")
        assert result["commit_trailer"] == "Override trailer: anthropic/test-model"
    finally:
        os.unlink(base_path)
        os.unlink(override_path)


def test_resolve_config_commit_trailer_disable_via_override():
    """Override config can disable commit_trailer by setting empty string."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as base_f:
        yaml.dump(
            {
                "default_model": "m1",
                "models": {"m1": {"id": "anthropic/test-model"}},
                "modes": {"resolve": {"action": "pr"}},
                "agent": {"commit_trailer": "Base trailer: {model_alias}"},
            },
            base_f,
        )
        base_path = base_f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as override_f:
        yaml.dump(
            {
                "agent": {"commit_trailer": ""},
            },
            override_f,
        )
        override_path = override_f.name

    try:
        result = resolve_config(base_path, override_path, "resolve")
        assert result["commit_trailer"] == ""
    finally:
        os.unlink(base_path)
        os.unlink(override_path)


def test_resolve_config_commit_trailer_openhands_key_backcompat():
    """Commit trailer can still be set under openhands: key — BACKCOMPAT."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m1",
                "models": {"m1": {"id": "anthropic/test-model"}},
                "modes": {"resolve": {"action": "pr"}},
                "openhands": {"commit_trailer": "Old key: {model_alias}"},
            },
            f,
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["commit_trailer"] == "Old key: m1"
    finally:
        os.unlink(path)


# --- three-layer config (local_path) ---


def test_resolve_config_local_wins_over_override(config_dir):
    """local_path layer wins over override_path."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    local_path = str(tmp_path / "local.yaml")

    with open(override_path, "w") as f:
        yaml.dump({"agent": {"max_iterations": 10}}, f)
    with open(local_path, "w") as f:
        yaml.dump({"agent": {"max_iterations": 99}}, f)

    result = resolve_config(base_path, override_path, "resolve", local_path=local_path)
    assert result["max_iterations"] == 99


def test_resolve_config_local_preserves_base_and_override(config_dir):
    """local_path only replaces what it specifies; base and override values survive."""
    tmp_path, base_path = config_dir
    local_path = str(tmp_path / "local.yaml")

    with open(local_path, "w") as f:
        yaml.dump({"agent": {"max_iterations": 5}}, f)

    result = resolve_config(base_path, "nonexistent.yaml", "resolve", local_path=local_path)
    assert result["max_iterations"] == 5
    assert result["pr_type"] == "ready"       # preserved from base


def test_resolve_config_local_missing_is_noop(config_dir):
    """Absent local_path file is silently ignored."""
    tmp_path, base_path = config_dir
    result_without = resolve_config(base_path, "nonexistent.yaml", "resolve")
    result_with = resolve_config(
        base_path, "nonexistent.yaml", "resolve", local_path="definitely_not_there.yaml"
    )
    assert result_without["max_iterations"] == result_with["max_iterations"]
    assert result_without["model"] == result_with["model"]
    assert "oh_version" not in result_with


def test_resolve_config_local_none_is_noop(config_dir):
    """local_path=None (default) behaves identically to no local file."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", local_path=None)
    assert result["mode"] == "resolve"


def test_resolve_config_local_extra_files_appends_to_base(config_dir):
    """local_path extra_files are appended to base extra_files, not replacing them."""
    tmp_path, base_path = config_dir
    # Add extra_files to base
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["modes"]["design"]["extra_files"] = ["README.md", "AGENTS.md"]
    with open(base_path, "w") as f:
        yaml.dump(config, f)

    local_path = str(tmp_path / "local.yaml")
    with open(local_path, "w") as f:
        yaml.dump({"modes": {"design": {"extra_files": ["README.md", "lib/config.py"]}}}, f)

    result = resolve_config(base_path, "nonexistent.yaml", "design", local_path=local_path)
    # README.md deduplicated, AGENTS.md from base preserved, lib/config.py added
    assert result["extra_files"] == ["README.md", "AGENTS.md", "lib/config.py"]


# --- resolve_config: timeout_minutes ---


def test_resolve_config_timeout_hardcoded_default(config_dir):
    """timeout_minutes falls back to hardcoded default (120) when not in yaml or per-invocation."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["timeout_minutes"] == 120


def test_resolve_config_timeout_yaml_default(config_dir):
    """timeout_minutes from yaml config is used when no per-invocation override."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["timeout_minutes"] = 90
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["timeout_minutes"] == 90


def test_resolve_config_timeout_per_invocation_overrides_yaml(config_dir):
    """Per-invocation timeout_minutes overrides the yaml default."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["timeout_minutes"] = 90
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", timeout_minutes=240)
    assert result["timeout_minutes"] == 240


def test_resolve_config_timeout_per_invocation_no_yaml(config_dir):
    """Per-invocation timeout works even without yaml default."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", timeout_minutes=30)
    assert result["timeout_minutes"] == 30


def test_resolve_config_timeout_with_model(config_dir):
    """Per-invocation timeout works alongside model alias."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve-claude-large", timeout_minutes=90)
    assert result["timeout_minutes"] == 90
    assert result["alias"] == "claude-large"


# --- resolve_config with args ---


def test_resolve_config_args_max_iterations(config_dir):
    """args can override max_iterations."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", args={"max_iterations": 75})
    assert result["max_iterations"] == 75


def test_resolve_config_args_extra_files_no_mode_config(config_dir):
    """args extra_files used as-is when mode has no extra_files."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "design", args={"extra_files": ["custom.txt"]})
    assert result["extra_files"] == ["custom.txt"]


def test_resolve_config_args_extra_files_appends_to_mode_config(config_dir):
    """args extra_files should append to mode's extra_files, not replace."""
    tmp_path, base_path = config_dir
    # Add extra_files to design mode
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["modes"]["design"]["extra_files"] = ["README.md", "AGENTS.md"]
    with open(base_path, "w") as f:
        yaml.dump(config, f)

    result = resolve_config(base_path, "nonexistent.yaml", "design", args={"extra_files": ["custom.txt"]})
    assert result["extra_files"] == ["README.md", "AGENTS.md", "custom.txt"]


def test_resolve_config_args_branch(config_dir):
    """args can override branch (target branch)."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", args={"branch": "design/gemini"})
    assert result["target_branch"] == "design/gemini"
    assert result["target_branch_explicit"] is True


def test_resolve_config_args_target_branch_backcompat(config_dir):
    """args target_branch is accepted as BACKCOMPAT alias for branch."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", args={"target_branch": "design/gemini"})
    assert result["target_branch"] == "design/gemini"
    assert result["target_branch_explicit"] is True


def test_resolve_config_args_empty_dict(config_dir):
    """Empty args dict should not change anything."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", args={})
    assert result["max_iterations"] == 50  # default from config


def test_resolve_config_args_none(config_dir):
    """None args should not change anything."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve", args=None)
    assert result["max_iterations"] == 50  # default from config


# --- main() — CLI entry point and GITHUB_OUTPUT writing ---


class TestConfigMain:
    """Tests for main() — the CLI entry point that writes GITHUB_OUTPUT.

    main() uses hardcoded relative paths (.remote-dev-bot/remote-dev-bot.yaml,
    remote-dev-bot.yaml, remote-dev-bot.local.yaml).  When pytest runs from
    the repo root the real remote-dev-bot.yaml is used as the config source,
    giving realistic output values without needing to stub the config layer.
    """

    def _call_main(self, command, tmp_path, timeout_minutes=None):
        """Run main() with command; return GITHUB_OUTPUT file contents."""
        output_file = tmp_path / "github_output"
        argv = ["config.py", command]
        if timeout_minutes is not None:
            argv.extend(["--timeout-minutes", str(timeout_minutes)])
        with patch("sys.argv", argv), patch.dict(
            os.environ, {"GITHUB_OUTPUT": str(output_file)}
        ):
            main()
        return output_file.read_text()

    def test_resolve_writes_all_required_keys(self, tmp_path):
        """Resolve mode writes every key that downstream steps depend on."""
        content = self._call_main("resolve", tmp_path)
        for key in (
            "mode", "action", "model", "alias",
            "max_iterations", "pr_type", "on_failure", "commit_trailer",
            "assign_issue", "assign_pr", "target_branch", "timeout_minutes",
        ):
            assert f"{key}=" in content, f"Missing key in GITHUB_OUTPUT: {key}"
        # oh_version must NOT be written — it's been removed
        assert "oh_version=" not in content

    def test_resolve_mode_and_action_values(self, tmp_path):
        content = self._call_main("resolve", tmp_path)
        assert "mode=resolve\n" in content
        assert "action=pr\n" in content

    def test_resolve_assign_values(self, tmp_path):
        """Resolve mode writes assign_issue and assign_pr as lowercase booleans."""
        content = self._call_main("resolve", tmp_path)
        assert "assign_issue=true\n" in content
        assert "assign_pr=true\n" in content

    def test_resolve_omits_extra_files(self, tmp_path):
        """extra_files is design-only and must not appear in resolve output."""
        content = self._call_main("resolve", tmp_path)
        assert "extra_files=" not in content

    def test_design_includes_extra_files_as_json(self, tmp_path):
        """Design mode writes extra_files as a non-empty JSON array."""
        content = self._call_main("design", tmp_path)
        assert "extra_files=" in content
        for line in content.splitlines():
            if line.startswith("extra_files="):
                files = json.loads(line.split("=", 1)[1])
                assert isinstance(files, list) and len(files) > 0
                break

    def test_design_mode_and_action_values(self, tmp_path):
        content = self._call_main("design", tmp_path)
        assert "mode=design\n" in content
        assert "action=design\n" in content

    def test_review_mode_and_action_values(self, tmp_path):
        content = self._call_main("review", tmp_path)
        assert "mode=review\n" in content
        assert "action=review\n" in content

    def test_invalid_command_exits_one(self, tmp_path):
        with (
            patch("sys.argv", ["config.py", "frobnicate"]),
            patch.dict(os.environ, {"GITHUB_OUTPUT": str(tmp_path / "out")}),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 1

    def test_no_github_output_env_runs_cleanly(self):
        """main() completes without error when GITHUB_OUTPUT is not set."""
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
        with (
            patch("sys.argv", ["config.py", "resolve"]),
            patch.dict(os.environ, env, clear=True),
        ):
            main()  # must not raise

    def test_timeout_minutes_passed_via_argparse(self, tmp_path):
        """--timeout-minutes is a separate argparse flag, not embedded in command."""
        content = self._call_main("resolve-claude-large", tmp_path, timeout_minutes=45)
        assert "timeout_minutes=45\n" in content
        assert "alias=claude-large\n" in content

    def test_timeout_minutes_default_when_not_specified(self, tmp_path):
        """timeout_minutes comes from the config file (60) when not overridden."""
        content = self._call_main("resolve", tmp_path)
        assert "timeout_minutes=60\n" in content

    def test_timeout_minutes_value_when_specified(self, tmp_path):
        """timeout_minutes contains the per-invocation value when specified."""
        content = self._call_main("resolve", tmp_path, timeout_minutes=90)
        assert "timeout_minutes=90\n" in content

    def test_resolve_writes_target_branch(self, tmp_path):
        """target_branch is written to GITHUB_OUTPUT."""
        content = self._call_main("resolve", tmp_path)
        assert "target_branch=" in content

    def _call_main_with_comment(self, comment_body, tmp_path):
        """Run main() with COMMENT_BODY env var; return GITHUB_OUTPUT file contents."""
        output_file = tmp_path / "github_output"
        with patch("sys.argv", ["config.py"]), patch.dict(
            os.environ, {"GITHUB_OUTPUT": str(output_file), "COMMENT_BODY": comment_body}
        ):
            main()
        return output_file.read_text()

    def test_comment_body_simple_command(self, tmp_path):
        """COMMENT_BODY with simple command works."""
        content = self._call_main_with_comment("/agent resolve", tmp_path)
        assert "mode=resolve\n" in content
        assert "action=pr\n" in content

    def test_comment_body_with_model(self, tmp_path):
        """COMMENT_BODY with model alias works."""
        content = self._call_main_with_comment("/agent resolve claude-large", tmp_path)
        assert "mode=resolve\n" in content
        assert "alias=claude-large\n" in content

    def test_comment_body_with_args(self, tmp_path):
        """COMMENT_BODY with args on subsequent lines works."""
        comment = "/agent resolve\nmax iterations = 75"
        content = self._call_main_with_comment(comment, tmp_path)
        assert "mode=resolve\n" in content
        assert "max_iterations=75\n" in content

    def test_comment_body_with_model_and_args(self, tmp_path):
        """COMMENT_BODY with model and args works."""
        comment = "/agent resolve claude-large\nmax iterations = 100"
        content = self._call_main_with_comment(comment, tmp_path)
        assert "mode=resolve\n" in content
        assert "alias=claude-large\n" in content
        assert "max_iterations=100\n" in content

    def test_comment_body_design_with_context_append(self, tmp_path):
        """COMMENT_BODY appends extra_files to mode's existing list."""
        comment = "/agent design\nextra_files = custom.txt"
        content = self._call_main_with_comment(comment, tmp_path)
        assert "mode=design\n" in content
        assert "custom.txt" in content

    def test_comment_body_invalid_command_exits_one(self, tmp_path):
        """Invalid command in COMMENT_BODY exits with code 1."""
        with (
            patch("sys.argv", ["config.py"]),
            patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(tmp_path / "out"),
                "COMMENT_BODY": "/agent frobnicate"
            }),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 1

    def test_comment_body_custom_command_prefix(self, tmp_path):
        """COMMAND_PREFIX env var changes the expected slash command prefix."""
        output_file = tmp_path / "github_output"
        with patch("sys.argv", ["config.py"]), patch.dict(
            os.environ,
            {"GITHUB_OUTPUT": str(output_file), "COMMENT_BODY": "/dogfood resolve", "COMMAND_PREFIX": "dogfood"},
        ):
            main()
        content = output_file.read_text()
        assert "mode=resolve\n" in content
        assert "action=pr\n" in content

    def test_comment_body_with_existing_base_config(self, tmp_path):
        """COMMENT_BODY mode reads base config when it exists (covers main() lines 461-462)."""
        # Write a minimal base config that main() will find at the hardcoded base_path
        base_dir = tmp_path / ".remote-dev-bot"
        base_dir.mkdir()
        base_config = {
            "default_model": "m1",
            "models": {"m1": {"id": "anthropic/test-model"}},
            "modes": {"resolve": {"action": "pr"}},
            "agent": {"max_iterations": 7, "pr_type": "ready"},
        }
        (base_dir / "remote-dev-bot.yaml").write_text(yaml.dump(base_config))

        output_file = tmp_path / "github_output"
        # Run main() with cwd set to tmp_path so the relative paths resolve correctly
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("sys.argv", ["config.py"]), patch.dict(
                os.environ,
                {"GITHUB_OUTPUT": str(output_file), "COMMENT_BODY": "/agent resolve"},
                clear=False,
            ):
                # Remove COMMENT_BODY from real env if it exists to avoid interference
                env = {k: v for k, v in os.environ.items() if k != "COMMENT_BODY"}
                env["GITHUB_OUTPUT"] = str(output_file)
                env["COMMENT_BODY"] = "/agent resolve"
                with patch.dict(os.environ, env, clear=True):
                    main()
        finally:
            os.chdir(old_cwd)

        content = output_file.read_text()
        assert "mode=resolve\n" in content
        # Config was read from our custom base; max_iterations should reflect it
        assert "max_iterations=7\n" in content
        assert "oh_version=" not in content
