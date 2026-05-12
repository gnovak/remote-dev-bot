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


def test_parse_command_single_word_model():
    """Model aliases with no hyphens (single word) should work."""
    assert parse_command("resolve-bob", KNOWN_MODES) == ("resolve", "bob")


def test_parse_command_many_segment_model():
    """Model aliases with multiple hyphens should be preserved in full."""
    assert parse_command("resolve-bob-very-large", KNOWN_MODES) == ("resolve", "bob-very-large")


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


def test_parse_args_design_rounds():
    """design_rounds should be parsed as int."""
    assert parse_args(["design_rounds = 2"]) == {"design_rounds": 2}
    assert parse_args(["design rounds = 1"]) == {"design_rounds": 1}
    assert parse_args(["design-rounds=2"]) == {"design_rounds": 2}


def test_parse_args_branch():
    """branch should be parsed as str."""
    assert parse_args(["branch = design/gemini"]) == {"branch": "design/gemini"}
    assert parse_args(["branch = my-feature"]) == {"branch": "my-feature"}


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
                "default_model": "claude-small",
            },
            "design": {
                "default_model": "claude-small",
                "extra_instructions": "Focus on scalability.",
            },
            "review": {
                "default_model": "claude-small",
            },
            "design_agentic": {
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
    assert result["alias"] == "claude-small"
    assert result["model"] == "anthropic/claude-sonnet-4-5"
    assert "extra_instructions" in result
    assert "exploring" in result["extra_instructions"]
    assert "extra_files" in result
    assert result["extra_files"] == ["README.md", "AGENTS.md"]
    # design_max_iterations is only set for modes literally named "design";
    # design_agentic uses max_iterations directly.
    assert "design_max_iterations" not in result
    assert result["max_iterations"] == 10


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
                    "resolve": {"default_model": "m1"},
                    "design": {"default_model": "m2"},
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
                "modes": {"resolve": {}},
            },
            f,
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["max_iterations"] == 50
        assert result["pr_type"] == "ready"
        assert result["on_failure"] == "draft"
        assert result["target_branch"] == "main"
        assert result["assign_issue"] is True
        assert result["assign_pr"] is True
        assert "oh_version" not in result
    finally:
        os.unlink(path)


def test_resolve_config_on_failure_default(config_dir):
    """on_failure defaults to 'draft'."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["on_failure"] == "draft"


def test_resolve_config_openhands_key_raises():
    """Config using openhands: key (removed in v0.9) raises ValueError with helpful message."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m",
                "models": {"m": {"id": "anthropic/test"}},
                "modes": {"resolve": {}},
                "openhands": {"max_iterations": 42, "pr_type": "draft"},
            },
            f,
        )
        path = f.name
    try:
        with pytest.raises(ValueError, match="agent:"):
            resolve_config(path, "nonexistent.yaml", "resolve")
    finally:
        os.unlink(path)


def test_resolve_config_context_files_raises():
    """Mode config using context_files: (removed in v0.9) raises ValueError with helpful message."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "default_model": "m",
                "models": {"m": {"id": "anthropic/test"}},
                "modes": {"design": {"context_files": ["README.md"]}},
            },
            f,
        )
        path = f.name
    try:
        with pytest.raises(ValueError, match="extra_files"):
            resolve_config(path, "nonexistent.yaml", "design")
    finally:
        os.unlink(path)


def test_parse_args_target_branch_unknown():
    """target_branch (removed in v0.9) is no longer accepted as an alias for branch."""
    with pytest.raises(ValueError, match="Unknown argument"):
        parse_args(["target_branch = design/gemini"])


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



def test_resolve_config_bash_output_limit_from_yaml(config_dir):
    """bash_output_limit is read from agent: yaml section when not in inline args."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"] = config.get("agent", {})
    config["agent"]["bash_output_limit"] = 4000
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result.get("bash_output_limit") == 4000

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
            "mode", "model", "alias",
            "max_iterations", "pr_type", "on_failure",
            "assign_issue", "assign_pr", "target_branch", "timeout_minutes",
        ):
            assert f"{key}=" in content, f"Missing key in GITHUB_OUTPUT: {key}"
        # these keys must NOT be written — they've been removed
        assert "oh_version=" not in content
        assert "commit_trailer=" not in content

    def test_resolve_mode_value(self, tmp_path):
        content = self._call_main("resolve", tmp_path)
        assert "mode=resolve\n" in content

    def test_resolve_assign_values(self, tmp_path):
        """Resolve mode writes assign_issue and assign_pr as lowercase booleans."""
        content = self._call_main("resolve", tmp_path)
        assert "assign_issue=true\n" in content
        assert "assign_pr=true\n" in content

    def test_resolve_includes_extra_files(self, tmp_path):
        """resolve now has extra_files (AGENTS.md, README.md) for orientation."""
        content = self._call_main("resolve", tmp_path)
        assert "extra_files=" in content

    def test_design_includes_extra_files_as_json(self, tmp_path):
        """Design mode writes extra_files as a non-empty JSON array."""
        content = self._call_main("design", tmp_path)
        assert "extra_files=" in content
        for line in content.splitlines():
            if line.startswith("extra_files="):
                files = json.loads(line.split("=", 1)[1])
                assert isinstance(files, list) and len(files) > 0
                break

    def test_design_mode_value(self, tmp_path):
        content = self._call_main("design", tmp_path)
        assert "mode=design\n" in content

    def test_review_mode_value(self, tmp_path):
        content = self._call_main("review", tmp_path)
        assert "mode=review\n" in content

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

    def test_comment_body_with_existing_base_config(self, tmp_path):
        """COMMENT_BODY mode reads base config when it exists (covers main() lines 461-462)."""
        # Write a minimal base config that main() will find at the hardcoded base_path
        base_dir = tmp_path / ".remote-dev-bot"
        base_dir.mkdir()
        base_config = {
            "default_model": "m1",
            "models": {"m1": {"id": "anthropic/test-model"}},
            "modes": {"resolve": {}},
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


# --- resolve_config: compaction parameters ---


def test_resolve_config_compaction_defaults(config_dir):
    """Compaction parameters default to 0 / 0.8 / 0.5 / 0.5."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["max_context_tokens"] == 0
    assert result["compaction_coverage"] == 0.5
    assert result["compaction_factor"] == 0.5


def test_resolve_config_compaction_from_yaml(config_dir):
    """Compaction parameters are read from agent: yaml section."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["max_context_tokens"] = 100000
    config["agent"]["compaction_coverage"] = 0.6
    config["agent"]["compaction_factor"] = 0.4
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert result["max_context_tokens"] == 100000
    assert result["compaction_coverage"] == 0.6
    assert result["compaction_factor"] == 0.4


def test_resolve_config_compaction_via_override(config_dir):
    """Compaction parameters can be overridden at the override layer."""
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    with open(override_path, "w") as f:
        yaml.dump({"agent": {"max_context_tokens": 50000, "compaction_coverage": 0.7}}, f)
    result = resolve_config(base_path, override_path, "resolve")
    assert result["max_context_tokens"] == 50000
    assert result["compaction_coverage"] == 0.7


def test_resolve_config_compaction_via_args(config_dir):
    """Compaction parameters can be overridden via inline args."""
    tmp_path, base_path = config_dir
    result = resolve_config(
        base_path, "nonexistent.yaml", "resolve",
        args={
            "max_context_tokens": 200000,
            "compaction_coverage": 0.3,
            "compaction_factor": 0.7,
        }
    )
    assert result["max_context_tokens"] == 200000
    assert result["compaction_coverage"] == 0.3
    assert result["compaction_factor"] == 0.7


def test_resolve_config_compaction_coverage_invalid(config_dir):
    """compaction_coverage outside (0, 1] raises ValueError."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["compaction_coverage"] = 0
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    with pytest.raises(ValueError, match="compaction_coverage"):
        resolve_config(base_path, "nonexistent.yaml", "resolve")


def test_resolve_config_compaction_factor_invalid(config_dir):
    """compaction_factor outside (0, 1] raises ValueError."""
    tmp_path, base_path = config_dir
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["agent"]["compaction_factor"] = -0.1
    with open(base_path, "w") as f:
        yaml.dump(config, f)
    with pytest.raises(ValueError, match="compaction_factor"):
        resolve_config(base_path, "nonexistent.yaml", "resolve")


def test_parse_args_compaction_params():
    """Compaction parameters are parsed correctly via parse_args."""
    result = parse_args([
        "max_context_tokens = 100000",
        "compaction_coverage = 0.6",
        "compaction_factor = 0.4",
    ])
    assert result == {
        "max_context_tokens": 100000,
        "compaction_coverage": 0.6,
        "compaction_factor": 0.4,
    }


def test_parse_args_compaction_invalid_float():
    """Non-float value for compaction param raises ValueError."""
    with pytest.raises(ValueError, match="must be a number"):
        parse_args(["compaction_coverage = not_a_number"])


# --- Workshop mode config tests ---


class TestWorkshopConfig:
    """Tests for workshop mode configuration."""

    @pytest.fixture
    def workshop_config_dir(self, tmp_path):
        """Create a temp dir with config that includes workshop mode."""
        config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
                "claude-large": {"id": "anthropic/claude-opus-4-6"},
                "gpt-small": {"id": "openai/gpt-4o-mini"},
                "gemini-small": {"id": "gemini/gemini-2.5-flash"},
            },
            "modes": {
                "resolve": {},
                "workshop": {
                    "default_model": "claude-large",
                    "max_iterations": 15,
                },
            },
            "agent": {
                "max_iterations": 50,
                "pr_type": "ready",
            },
        }
        base_path = str(tmp_path / "base.yaml")
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        return tmp_path, base_path

    def test_workshop_mode_basic(self, workshop_config_dir):
        """Workshop mode is recognized with correct defaults."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        assert result["mode"] == "workshop"
        assert result["alias"] == "claude-large"
        assert result["model"] == "anthropic/claude-opus-4-6"

    def test_workshop_mode_with_model(self, workshop_config_dir):
        """Workshop mode accepts explicit model alias."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "workshop-claude-small")
        assert result["mode"] == "workshop"
        assert result["alias"] == "claude-small"

    def test_workshop_max_iterations(self, workshop_config_dir):
        """Workshop mode uses its own max_iterations."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        assert result["workshop_max_iterations"] == 15

    def test_workshop_max_iterations_override_via_args(self, workshop_config_dir):
        """Inline args override workshop max_iterations."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "workshop",
            args={"max_iterations": 25},
        )
        assert result["workshop_max_iterations"] == 25

    def test_workshop_default_council_includes_design_model(self, workshop_config_dir):
        """Default council (no explicit list) includes all models, including the design model."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        council = result["council_models"]
        aliases = [m["alias"] for m in council]
        # design model is claude-large (default_model for workshop mode)
        # it should now be included — self-review in critic role is valuable
        assert "claude-large" in aliases
        assert "claude-small" in aliases
        assert "gpt-small" in aliases
        assert "gemini-small" in aliases

    def test_workshop_default_council_with_explicit_model(self, workshop_config_dir):
        """Default council includes all models even when user specifies a design model explicitly."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "workshop-claude-small")
        council = result["council_models"]
        aliases = [m["alias"] for m in council]
        # design model is now claude-small (explicitly specified) — still included
        assert "claude-small" in aliases
        assert "claude-large" in aliases

    def test_workshop_explicit_council(self, workshop_config_dir):
        """Explicit council list uses exactly those models."""
        tmp_path, base_path = workshop_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["workshop"]["council"] = ["claude-small", "gpt-small"]
        with open(base_path, "w") as f:
            yaml.dump(config, f)

        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        council = result["council_models"]
        aliases = [m["alias"] for m in council]
        assert aliases == ["claude-small", "gpt-small"]

    def test_workshop_explicit_council_can_include_design_model(self, workshop_config_dir):
        """Explicit council can include the design model (self-review)."""
        tmp_path, base_path = workshop_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["workshop"]["council"] = ["claude-large", "gpt-small"]
        with open(base_path, "w") as f:
            yaml.dump(config, f)

        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        council = result["council_models"]
        aliases = [m["alias"] for m in council]
        assert "claude-large" in aliases  # design model explicitly included

    def test_workshop_council_models_have_id(self, workshop_config_dir):
        """Each council model entry has both alias and id."""
        tmp_path, base_path = workshop_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        for m in result["council_models"]:
            assert "alias" in m
            assert "id" in m
            assert m["id"]  # not empty


# --- review mode council ---


class TestReviewCouncil:
    """Tests for council = true inline arg on review mode."""

    @pytest.fixture
    def review_council_config_dir(self, tmp_path):
        """Create a temp dir with config that includes review mode with council list."""
        config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
                "gpt-small": {"id": "openai/gpt-4o-mini"},
                "gemini-small": {"id": "gemini/gemini-2.5-flash"},
            },
            "modes": {
                "resolve": {},
                "review": {
                    "max_iterations": 10,
                    "council": ["claude-small", "gpt-small", "gemini-small"],
                },
            },
            "agent": {
                "max_iterations": 50,
                "pr_type": "ready",
            },
        }
        base_path = str(tmp_path / "base.yaml")
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        return tmp_path, base_path

    def test_review_without_council_has_no_council_models(self, review_council_config_dir):
        """Without council=true, review mode does not emit council_models."""
        tmp_path, base_path = review_council_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "review")
        assert "council_models" not in result

    def test_review_with_council_true_emits_council_models(self, review_council_config_dir):
        """With council=true, review mode emits council_models."""
        tmp_path, base_path = review_council_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "review",
            args={"council": True},
        )
        assert "council_models" in result

    def test_review_council_uses_explicit_list(self, review_council_config_dir):
        """With council=true, the explicit council list from config is used."""
        tmp_path, base_path = review_council_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "review",
            args={"council": True},
        )
        aliases = [m["alias"] for m in result["council_models"]]
        assert aliases == ["claude-small", "gpt-small", "gemini-small"]

    def test_review_council_defaults_to_all_models_when_no_explicit_list(self, tmp_path):
        """When council=true but no council list in config, falls back to all models."""
        config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
                "gpt-small": {"id": "openai/gpt-4o-mini"},
            },
            "modes": {
                "resolve": {},
                "review": {"max_iterations": 10},
            },
            "agent": {"max_iterations": 50, "pr_type": "ready"},
        }
        base_path = str(tmp_path / "base.yaml")
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(
            base_path, "nonexistent.yaml", "review",
            args={"council": True},
        )
        aliases = [m["alias"] for m in result["council_models"]]
        assert "claude-small" in aliases
        assert "gpt-small" in aliases

    def test_review_council_models_have_id(self, review_council_config_dir):
        """Each council model entry has both alias and id."""
        tmp_path, base_path = review_council_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "review",
            args={"council": True},
        )
        for m in result["council_models"]:
            assert "alias" in m
            assert "id" in m
            assert m["id"]

    def test_review_council_false_does_not_emit_council_models(self, review_council_config_dir):
        """Explicitly setting council=false does not emit council_models."""
        tmp_path, base_path = review_council_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "review",
            args={"council": False},
        )
        assert "council_models" not in result

    def test_council_inline_arg_parsed_from_string(self):
        """council = true is parseable as a bool inline arg."""
        lines = ["council = true"]
        args = parse_args(lines)
        assert args.get("council") is True

    def test_council_inline_arg_false_parsed(self):
        """council = false is parseable as bool False."""
        lines = ["council = false"]
        args = parse_args(lines)
        assert args.get("council") is False



# --- model-level extra_instructions ---


class TestModelExtraInstructions:
    """Tests for model-level extra_instructions on individual model entries."""

    @pytest.fixture
    def config_with_model_extra(self, tmp_path):
        """Config where one model has extra_instructions."""
        config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {
                    "id": "anthropic/claude-sonnet-4-5",
                    "extra_instructions": "Always respond tersely.",
                },
                "gpt-small": {
                    "id": "openai/gpt-5.1-codex-mini",
                },
                "gemini-small": {
                    "id": "gemini/gemini-2.5-flash",
                    "extra_instructions": "Use metric units.",
                },
            },
            "modes": {
                "resolve": {"default_model": "claude-small"},
                "workshop": {
                    "default_model": "claude-small",
                    "council": ["claude-small", "gpt-small", "gemini-small"],
                },
            },
            "agent": {"max_iterations": 50, "pr_type": "ready"},
        }
        base_path = str(tmp_path / "base.yaml")
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        return tmp_path, base_path

    def test_model_extra_instructions_in_result(self, config_with_model_extra):
        """model_extra_instructions is set when the resolved model has extra_instructions."""
        tmp_path, base_path = config_with_model_extra
        result = resolve_config(base_path, "nonexistent.yaml", "resolve")
        assert "model_extra_instructions" in result
        assert "tersely" in result["model_extra_instructions"]

    def test_model_extra_instructions_absent_when_not_configured(self, config_with_model_extra):
        """model_extra_instructions is absent when the resolved model has none."""
        tmp_path, base_path = config_with_model_extra
        result = resolve_config(base_path, "nonexistent.yaml", "resolve-gpt-small")
        assert "model_extra_instructions" not in result

    def test_model_extra_instructions_different_model(self, config_with_model_extra):
        """model_extra_instructions reflects the resolved model's value."""
        tmp_path, base_path = config_with_model_extra
        result = resolve_config(base_path, "nonexistent.yaml", "resolve-gemini-small")
        assert "model_extra_instructions" in result
        assert "metric" in result["model_extra_instructions"]

    def test_council_models_include_model_extra_instructions(self, config_with_model_extra):
        """Council model entries include extra_instructions when configured."""
        tmp_path, base_path = config_with_model_extra
        result = resolve_config(base_path, "nonexistent.yaml", "workshop")
        council = {m["alias"]: m for m in result["council_models"]}
        assert "extra_instructions" in council["claude-small"]
        assert "tersely" in council["claude-small"]["extra_instructions"]
        assert "extra_instructions" in council["gemini-small"]
        assert "metric" in council["gemini-small"]["extra_instructions"]
        # gpt-small has no model extra_instructions
        assert "extra_instructions" not in council["gpt-small"]

    def test_model_extra_instructions_written_to_github_output(self, tmp_path):
        """model_extra_instructions is written to GITHUB_OUTPUT when present."""
        # Write a custom base config with model extra_instructions
        base_dir = tmp_path / ".remote-dev-bot"
        base_dir.mkdir()
        base_config = {
            "default_model": "m1",
            "models": {
                "m1": {"id": "anthropic/test", "extra_instructions": "Be concise."},
            },
            "modes": {"resolve": {}},
            "agent": {"max_iterations": 10, "pr_type": "ready"},
        }
        (base_dir / "remote-dev-bot.yaml").write_text(yaml.dump(base_config))

        output_file = tmp_path / "github_output"
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            env = {k: v for k, v in os.environ.items() if k not in ("COMMENT_BODY",)}
            env["GITHUB_OUTPUT"] = str(output_file)
            env["COMMENT_BODY"] = "/agent resolve"
            with patch("sys.argv", ["config.py"]), patch.dict(os.environ, env, clear=True):
                main()
        finally:
            os.chdir(old_cwd)

        content = output_file.read_text()
        assert "model_extra_instructions=Be concise.\n" in content

    def test_model_extra_instructions_absent_from_github_output_when_not_configured(self, tmp_path):
        """model_extra_instructions is NOT written to GITHUB_OUTPUT when absent."""
        base_dir = tmp_path / ".remote-dev-bot"
        base_dir.mkdir()
        base_config = {
            "default_model": "m1",
            "models": {"m1": {"id": "anthropic/test"}},
            "modes": {"resolve": {}},
            "agent": {"max_iterations": 10, "pr_type": "ready"},
        }
        (base_dir / "remote-dev-bot.yaml").write_text(yaml.dump(base_config))

        output_file = tmp_path / "github_output"
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            env = {k: v for k, v in os.environ.items() if k not in ("COMMENT_BODY",)}
            env["GITHUB_OUTPUT"] = str(output_file)
            env["COMMENT_BODY"] = "/agent resolve"
            with patch("sys.argv", ["config.py"]), patch.dict(os.environ, env, clear=True):
                main()
        finally:
            os.chdir(old_cwd)

        content = output_file.read_text()
        assert "model_extra_instructions=" not in content


# --- resolve_config: delegate mode ---


class TestDelegateConfig:
    """Tests for delegate mode configuration."""

    @pytest.fixture
    def delegate_config_dir(self, tmp_path):
        """Create a temp dir with config that includes delegate mode."""
        config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
                "claude-large": {"id": "anthropic/claude-opus-4-6"},
                "gpt-small": {"id": "openai/gpt-4o-mini"},
                "gemini-small": {"id": "gemini/gemini-2.5-flash"},
            },
            "modes": {
                "resolve": {},
                "delegate": {
                    "default_model": "claude-small",
                    "max_iterations": 15,
                    "council": ["claude-small", "gpt-small", "gemini-small"],
                },
            },
            "agent": {
                "max_iterations": 50,
                "pr_type": "ready",
            },
        }
        base_path = str(tmp_path / "base.yaml")
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        return tmp_path, base_path

    def test_delegate_mode_basic(self, delegate_config_dir):
        """Delegate mode is recognized with correct defaults."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert result["mode"] == "delegate"
        assert result["alias"] == "claude-small"
        assert result["model"] == "anthropic/claude-sonnet-4-20250514"

    def test_delegate_mode_with_model(self, delegate_config_dir):
        """Delegate mode accepts explicit model alias."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate-claude-large")
        assert result["mode"] == "delegate"
        assert result["alias"] == "claude-large"
        assert result["model"] == "anthropic/claude-opus-4-6"

    def test_delegate_max_iterations(self, delegate_config_dir):
        """Delegate mode outputs delegate_max_iterations."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert result["delegate_max_iterations"] == 15

    def test_delegate_max_iterations_override_via_args(self, delegate_config_dir):
        """Inline args override delegate max_iterations."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "delegate",
            args={"max_iterations": 25},
        )
        assert result["delegate_max_iterations"] == 25

    def test_delegate_design_rounds_default(self, delegate_config_dir):
        """Delegate mode defaults design_rounds to 1."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert result["design_rounds"] == 1

    def test_delegate_design_rounds_from_mode_config(self, delegate_config_dir):
        """Delegate mode respects design_rounds set in mode config."""
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["delegate"]["design_rounds"] = 2
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert result["design_rounds"] == 2

    def test_delegate_design_rounds_override_via_args(self, delegate_config_dir):
        """Inline args override delegate design_rounds."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(
            base_path, "nonexistent.yaml", "delegate",
            args={"design_rounds": 2},
        )
        assert result["design_rounds"] == 2

    def test_delegate_design_rounds_arg_beats_mode_config(self, delegate_config_dir):
        """Inline args take precedence over mode config for design_rounds."""
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["delegate"]["design_rounds"] = 2
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(
            base_path, "nonexistent.yaml", "delegate",
            args={"design_rounds": 1},
        )
        assert result["design_rounds"] == 1

    def test_design_rounds_not_emitted_for_non_delegate(self, delegate_config_dir):
        """design_rounds is only emitted in delegate mode."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "resolve")
        assert "design_rounds" not in result

    # --- design_rounds validation ---
    #
    # Only 1 and 2 are defined. Values outside that range must raise
    # ValueError rather than silently getting clamped or ignored:
    # run_delegate's branch is `if design_rounds >= 2`, so a user who
    # types `design_rounds = 3` used to get the same behavior as 2 with
    # no signal that the extra round they asked for doesn't exist.

    def test_delegate_design_rounds_3_rejected(self, delegate_config_dir):
        """design_rounds=3 raises ValueError — no third round is defined."""
        tmp_path, base_path = delegate_config_dir
        with pytest.raises(ValueError, match="design_rounds must be 1 or 2"):
            resolve_config(
                base_path, "nonexistent.yaml", "delegate",
                args={"design_rounds": 3},
            )

    def test_delegate_design_rounds_0_rejected(self, delegate_config_dir):
        """design_rounds=0 raises ValueError — not a valid round count."""
        tmp_path, base_path = delegate_config_dir
        with pytest.raises(ValueError, match="design_rounds must be 1 or 2"):
            resolve_config(
                base_path, "nonexistent.yaml", "delegate",
                args={"design_rounds": 0},
            )

    def test_delegate_design_rounds_negative_rejected(self, delegate_config_dir):
        """Negative design_rounds raises ValueError."""
        tmp_path, base_path = delegate_config_dir
        with pytest.raises(ValueError, match="design_rounds must be 1 or 2"):
            resolve_config(
                base_path, "nonexistent.yaml", "delegate",
                args={"design_rounds": -1},
            )

    def test_delegate_design_rounds_invalid_mode_config_rejected(self, delegate_config_dir):
        """An invalid mode-level design_rounds in YAML also raises ValueError.

        Validation applies to the resolved value regardless of whether it
        came from an inline arg or the merged config — otherwise users
        could silently ship a bad default.
        """
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["delegate"]["design_rounds"] = 5
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        with pytest.raises(ValueError, match="design_rounds must be 1 or 2"):
            resolve_config(base_path, "nonexistent.yaml", "delegate")

    def test_delegate_council_models(self, delegate_config_dir):
        """Delegate mode resolves council models from explicit list."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        council = result["council_models"]
        aliases = [m["alias"] for m in council]
        assert "claude-small" in aliases
        assert "gpt-small" in aliases
        assert "gemini-small" in aliases

    def test_delegate_default_council_all_models(self, delegate_config_dir):
        """Without explicit council, delegate mode defaults to all models."""
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        del config["modes"]["delegate"]["council"]
        with open(base_path, "w") as f:
            yaml.dump(config, f)

        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        council = result["council_models"]
        aliases = [m["alias"] for m in council]
        assert len(aliases) == 4  # all four models
        assert "claude-small" in aliases
        assert "claude-large" in aliases
        assert "gpt-small" in aliases
        assert "gemini-small" in aliases

    def test_delegate_council_models_have_id(self, delegate_config_dir):
        """Each delegate council model entry has both alias and id."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        for m in result["council_models"]:
            assert "alias" in m
            assert "id" in m
            assert m["id"]  # not empty

    def test_delegate_no_workshop_max_iterations(self, delegate_config_dir):
        """Delegate mode does NOT set workshop_max_iterations."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert "workshop_max_iterations" not in result

    # --- delegate max_design_iterations (design/exploration budget) ---
    #
    # Delegate mode has two independent iteration budgets:
    #   - delegate_max_iterations        — code-writing stages (Stage 4, 6)
    #   - delegate_max_design_iterations — design/exploration stages (1, 3a)
    # The design budget falls back to agent.max_iterations when not set
    # at the mode level. Inline arg `max_design_iterations` overrides both.

    def test_delegate_max_design_iterations_falls_back_to_agent(self, delegate_config_dir):
        """Without a mode-level default, design budget falls back to agent.max_iterations."""
        tmp_path, base_path = delegate_config_dir
        # Fixture has agent.max_iterations = 50 and no
        # modes.delegate.max_design_iterations — so the design budget
        # should inherit 50 from the agent section.
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert result["delegate_max_design_iterations"] == 50

    def test_delegate_max_design_iterations_from_mode_config(self, delegate_config_dir):
        """Mode-level max_design_iterations wins over agent.max_iterations."""
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["delegate"]["max_design_iterations"] = 12
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(base_path, "nonexistent.yaml", "delegate")
        assert result["delegate_max_design_iterations"] == 12

    def test_delegate_max_design_iterations_inline_arg_override(self, delegate_config_dir):
        """Inline arg max_design_iterations overrides both mode and agent config."""
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["delegate"]["max_design_iterations"] = 12
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(
            base_path, "nonexistent.yaml", "delegate",
            args={"max_design_iterations": 30},
        )
        assert result["delegate_max_design_iterations"] == 30

    def test_delegate_max_iterations_and_design_iterations_are_independent(self, delegate_config_dir):
        """Bumping max_iterations via inline arg does NOT change max_design_iterations."""
        tmp_path, base_path = delegate_config_dir
        with open(base_path) as f:
            config = yaml.safe_load(f)
        config["modes"]["delegate"]["max_design_iterations"] = 12
        with open(base_path, "w") as f:
            yaml.dump(config, f)
        # User says "give it more iterations" — the common expectation is
        # that this bumps the coding loops, not the design loops.
        result = resolve_config(
            base_path, "nonexistent.yaml", "delegate",
            args={"max_iterations": 100},
        )
        assert result["delegate_max_iterations"] == 100
        assert result["delegate_max_design_iterations"] == 12

    def test_delegate_max_design_iterations_not_emitted_for_non_delegate(self, delegate_config_dir):
        """delegate_max_design_iterations is only emitted in delegate mode."""
        tmp_path, base_path = delegate_config_dir
        result = resolve_config(base_path, "nonexistent.yaml", "resolve")
        assert "delegate_max_design_iterations" not in result


def test_parse_args_max_design_iterations():
    """max_design_iterations should be parsed as int and normalize dashes/spaces."""
    assert parse_args(["max_design_iterations = 20"]) == {"max_design_iterations": 20}
    assert parse_args(["max design iterations = 15"]) == {"max_design_iterations": 15}
    assert parse_args(["max-design-iterations=8"]) == {"max_design_iterations": 8}


# --- resolve_config comprehensive tests ---


class TestResolveConfig:
    """Tests for resolve_config() covering layer ordering, type coercion,
    mode resolution, list merging, and edge cases."""

    def _make_config(self, **overrides):
        """Return a minimal valid config dict, with optional overrides merged in."""
        base = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
                "claude-large": {"id": "anthropic/claude-opus-4-6"},
            },
            "modes": {
                "resolve": {
                    "default_model": "claude-small",
                    "max_iterations": 30,
                    "extra_files": ["AGENTS.md"],
                },
                "design": {
                    "default_model": "claude-small",
                    "max_iterations": 20,
                    "extra_files": ["CONTRIBUTING.md"],
                },
            },
            "agent": {
                "max_iterations": 50,
                "pr_type": "ready",
            },
        }
        base.update(overrides)
        return base

    @pytest.fixture
    def base_config_path(self, tmp_path):
        """Write a minimal base config to a temp file and return its path."""
        config = self._make_config()
        path = str(tmp_path / "remote-dev-bot.yaml")
        with open(path, "w") as f:
            yaml.dump(config, f)
        return path

    @pytest.fixture
    def rdb_base_path(self, tmp_path):
        """Copy the real remote-dev-bot.yaml to a temp dir and return its path."""
        import shutil
        dest = tmp_path / "remote-dev-bot.yaml"
        shutil.copy("remote-dev-bot.yaml", dest)
        return str(dest)

    # ------------------------------------------------------------------ #
    # Layer ordering                                                       #
    # ------------------------------------------------------------------ #

    def test_base_config_loaded(self, base_config_path):
        """When only base config exists, values come from it."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert result["mode"] == "resolve"
        assert result["max_iterations"] == 30
        assert result["alias"] == "claude-small"

    def test_override_shadows_base(self, tmp_path, base_config_path):
        """Override config (target repo) wins over base config."""
        override_config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
                "claude-large": {"id": "anthropic/claude-opus-4-6"},
            },
            "modes": {
                "resolve": {
                    "max_iterations": 99,
                },
            },
            "agent": {
                "max_iterations": 50,
                "pr_type": "draft",
            },
        }
        override_path = str(tmp_path / "override.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        result = resolve_config(base_config_path, override_path, "resolve")
        assert result["max_iterations"] == 99
        assert result["pr_type"] == "draft"

    def test_local_config_shadows_override(self, tmp_path, base_config_path):
        """Local config (third layer) wins over both base and override."""
        override_config = {
            "modes": {
                "resolve": {"max_iterations": 40},
            },
            "agent": {"max_iterations": 40},
        }
        local_config = {
            "modes": {
                "resolve": {"max_iterations": 77},
            },
            "agent": {"max_iterations": 40},
        }
        override_path = str(tmp_path / "override.yaml")
        local_path = str(tmp_path / "local.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        with open(local_path, "w") as f:
            yaml.dump(local_config, f)
        result = resolve_config(
            base_config_path, override_path, "resolve", local_path=local_path
        )
        assert result["max_iterations"] == 77

    def test_inline_args_win_over_all_layers(self, tmp_path, base_config_path):
        """Inline args beat base, override, and local configs."""
        override_config = {
            "modes": {"resolve": {"max_iterations": 40}},
            "agent": {"max_iterations": 40},
        }
        override_path = str(tmp_path / "override.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        result = resolve_config(
            base_config_path, override_path, "resolve",
            args={"max_iterations": 999},
        )
        assert result["max_iterations"] == 999

    def test_has_override_false_when_no_override(self, base_config_path):
        """has_override is False when no override file exists."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert result["has_override"] is False

    def test_has_override_true_when_override_exists(self, tmp_path, base_config_path):
        """has_override is True when override file is present (even if mostly empty)."""
        override_config = {"agent": {"pr_type": "ready"}}
        override_path = str(tmp_path / "override.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        result = resolve_config(base_config_path, override_path, "resolve")
        assert result["has_override"] is True

    # ------------------------------------------------------------------ #
    # Mode resolution                                                      #
    # ------------------------------------------------------------------ #

    def test_resolve_mode(self, base_config_path):
        """'resolve' command string is recognized."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert result["mode"] == "resolve"

    def test_design_mode(self, base_config_path):
        """'design' command string is recognized."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "design")
        assert result["mode"] == "design"

    def test_mode_with_model_alias_in_command(self, base_config_path):
        """Model alias appended to command string is parsed correctly."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve-claude-large"
        )
        assert result["mode"] == "resolve"
        assert result["alias"] == "claude-large"
        assert result["model"] == "anthropic/claude-opus-4-6"

    def test_unknown_mode_raises_value_error(self, base_config_path):
        """An unknown mode name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown mode"):
            resolve_config(base_config_path, "nonexistent.yaml", "frobnicate")

    def test_mode_picks_up_mode_config(self, base_config_path):
        """Mode-specific max_iterations overrides global agent.max_iterations."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        # Base config sets modes.resolve.max_iterations=30 vs agent.max_iterations=50
        assert result["max_iterations"] == 30

    def test_default_model_from_mode(self, base_config_path):
        """Mode's default_model is used when no alias is specified."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert result["alias"] == "claude-small"

    def test_default_model_from_global_when_not_in_mode(self, tmp_path):
        """Global default_model is used when mode has no default_model set."""
        config = self._make_config()
        del config["modes"]["resolve"]["default_model"]
        path = str(tmp_path / "base.yaml")
        with open(path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["alias"] == "claude-small"

    # ------------------------------------------------------------------ #
    # Inline-arg type coercion                                             #
    # ------------------------------------------------------------------ #

    def test_inline_arg_max_iterations_is_int(self, base_config_path):
        """max_iterations inline arg is stored as int (already coerced by parse_args)."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"max_iterations": 75},
        )
        assert result["max_iterations"] == 75
        assert isinstance(result["max_iterations"], int)

    def test_inline_arg_timeout_minutes_is_int(self, base_config_path):
        """timeout_minutes inline arg is stored as int."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"timeout_minutes": 60},
        )
        assert result["timeout_minutes"] == 60
        assert isinstance(result["timeout_minutes"], int)

    def test_inline_arg_status_log_interval(self, base_config_path):
        """status_log_interval inline arg is stored as int."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"status_log_interval": 10},
        )
        assert result["status_log_interval"] == 10
        assert isinstance(result["status_log_interval"], int)

    def test_inline_arg_branch_is_str(self, base_config_path):
        """branch inline arg is stored as a string."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"branch": "my-feature"},
        )
        assert result["target_branch"] == "my-feature"
        assert isinstance(result["target_branch"], str)

    def test_inline_arg_debug_logging_bool(self, base_config_path):
        """debug_logging inline arg is coerced to bool."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"debug_logging": True},
        )
        assert result.get("debug_logging") is True

    # ------------------------------------------------------------------ #
    # List-vs-scalar (extra_files) additive merge                         #
    # ------------------------------------------------------------------ #

    def test_extra_files_base_only(self, base_config_path):
        """extra_files from base config are included in result."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert "AGENTS.md" in result.get("extra_files", [])

    def test_extra_files_additive_with_override(self, tmp_path, base_config_path):
        """Override extra_files appends to base extra_files rather than replacing."""
        override_config = {
            "modes": {
                "resolve": {
                    "extra_files": ["CONTRIBUTING.md"],
                },
            },
        }
        override_path = str(tmp_path / "override.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        result = resolve_config(base_config_path, override_path, "resolve")
        extra = result.get("extra_files", [])
        # Both base and override files should be present
        assert "AGENTS.md" in extra
        assert "CONTRIBUTING.md" in extra

    def test_extra_files_additive_with_local(self, tmp_path, base_config_path):
        """Local config extra_files appends after base and override layers."""
        override_config = {
            "modes": {"resolve": {"extra_files": ["CONTRIBUTING.md"]}},
        }
        local_config = {
            "modes": {"resolve": {"extra_files": ["LOCAL.md"]}},
        }
        override_path = str(tmp_path / "override.yaml")
        local_path = str(tmp_path / "local.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        with open(local_path, "w") as f:
            yaml.dump(local_config, f)
        result = resolve_config(
            base_config_path, override_path, "resolve", local_path=local_path
        )
        extra = result.get("extra_files", [])
        assert "AGENTS.md" in extra
        assert "CONTRIBUTING.md" in extra
        assert "LOCAL.md" in extra

    def test_extra_files_additive_with_inline_args(self, base_config_path):
        """Inline extra_files arg appends on top of all config-layer files."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"extra_files": ["README.md"]},
        )
        extra = result.get("extra_files", [])
        assert "AGENTS.md" in extra
        assert "README.md" in extra

    def test_extra_files_deduplication(self, tmp_path, base_config_path):
        """Duplicate file names across layers appear only once."""
        override_config = {
            "modes": {"resolve": {"extra_files": ["AGENTS.md"]}},  # same as base
        }
        override_path = str(tmp_path / "override.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        result = resolve_config(base_config_path, override_path, "resolve")
        extra = result.get("extra_files", [])
        assert extra.count("AGENTS.md") == 1

    def test_extra_files_order_preserved(self, tmp_path, base_config_path):
        """extra_files order: base → override → local → inline args."""
        override_config = {
            "modes": {"resolve": {"extra_files": ["OVERRIDE.md"]}},
        }
        local_config = {
            "modes": {"resolve": {"extra_files": ["LOCAL.md"]}},
        }
        override_path = str(tmp_path / "override.yaml")
        local_path = str(tmp_path / "local.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        with open(local_path, "w") as f:
            yaml.dump(local_config, f)
        result = resolve_config(
            base_config_path, override_path, "resolve",
            local_path=local_path,
            args={"extra_files": ["INLINE.md"]},
        )
        extra = result.get("extra_files", [])
        # Verify relative ordering
        assert extra.index("AGENTS.md") < extra.index("OVERRIDE.md")
        assert extra.index("OVERRIDE.md") < extra.index("LOCAL.md")
        assert extra.index("LOCAL.md") < extra.index("INLINE.md")

    # ------------------------------------------------------------------ #
    # Timeout defaults                                                     #
    # ------------------------------------------------------------------ #

    def test_timeout_defaults_to_120(self, base_config_path):
        """Default timeout is 120 minutes when not set anywhere."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert result["timeout_minutes"] == 120

    def test_timeout_from_yaml(self, tmp_path):
        """Timeout from YAML agent config is used when no inline arg given."""
        config = self._make_config()
        config["agent"]["timeout_minutes"] = 90
        path = str(tmp_path / "base.yaml")
        with open(path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["timeout_minutes"] == 90

    def test_timeout_inline_arg_beats_yaml(self, tmp_path):
        """Inline timeout_minutes arg wins over YAML agent.timeout_minutes."""
        config = self._make_config()
        config["agent"]["timeout_minutes"] = 90
        path = str(tmp_path / "base.yaml")
        with open(path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(
            path, "nonexistent.yaml", "resolve",
            args={"timeout_minutes": 45},
        )
        assert result["timeout_minutes"] == 45

    def test_timeout_flag_beats_yaml(self, tmp_path):
        """timeout_minutes parameter (from --timeout-minutes flag) wins over YAML."""
        config = self._make_config()
        config["agent"]["timeout_minutes"] = 90
        path = str(tmp_path / "base.yaml")
        with open(path, "w") as f:
            yaml.dump(config, f)
        result = resolve_config(path, "nonexistent.yaml", "resolve", timeout_minutes=30)
        assert result["timeout_minutes"] == 30

    # ------------------------------------------------------------------ #
    # Edge cases                                                           #
    # ------------------------------------------------------------------ #

    def test_missing_base_config_uses_override_only(self, tmp_path):
        """When base config is missing, override config is used on its own."""
        override_config = {
            "default_model": "claude-small",
            "models": {
                "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
            },
            "modes": {
                "resolve": {"max_iterations": 25},
            },
            "agent": {"max_iterations": 25},
        }
        override_path = str(tmp_path / "override.yaml")
        with open(override_path, "w") as f:
            yaml.dump(override_config, f)
        result = resolve_config(
            str(tmp_path / "nonexistent-base.yaml"), override_path, "resolve"
        )
        assert result["mode"] == "resolve"
        assert result["max_iterations"] == 25

    def test_empty_args_dict(self, base_config_path):
        """Passing an empty args dict is equivalent to passing no args."""
        result_none = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        result_empty = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve", args={}
        )
        assert result_none["max_iterations"] == result_empty["max_iterations"]
        assert result_none["timeout_minutes"] == result_empty["timeout_minutes"]

    def test_none_args_treated_as_empty(self, base_config_path):
        """args=None (the default) is treated as an empty dict."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve", args=None
        )
        assert result["mode"] == "resolve"

    def test_unknown_inline_arg_rejected_by_parse_args(self):
        """parse_args raises ValueError for unknown argument names."""
        with pytest.raises(ValueError, match="Unknown"):
            parse_args(["totally_unknown_arg = 42"])

    def test_result_has_required_keys(self, base_config_path):
        """Result dict always includes the standard set of keys."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        for key in ("mode", "model", "alias", "max_iterations", "pr_type",
                    "has_override", "timeout_minutes"):
            assert key in result, f"Key '{key}' missing from resolve_config result"

    def test_real_base_config_resolve_mode(self, rdb_base_path):
        """resolve_config works end-to-end with the real remote-dev-bot.yaml."""
        result = resolve_config(rdb_base_path, "nonexistent.yaml", "resolve")
        assert result["mode"] == "resolve"
        assert result["model"]  # non-empty model ID
        assert result["timeout_minutes"] > 0

    def test_real_base_config_design_mode(self, rdb_base_path):
        """resolve_config works end-to-end with the real remote-dev-bot.yaml in design mode."""
        result = resolve_config(rdb_base_path, "nonexistent.yaml", "design")
        assert result["mode"] == "design"
        assert result["model"]

    def test_target_branch_explicit_false_by_default(self, base_config_path):
        """target_branch_explicit is False when branch is not set via inline arg."""
        result = resolve_config(base_config_path, "nonexistent.yaml", "resolve")
        assert result["target_branch_explicit"] is False

    def test_target_branch_explicit_true_via_args(self, base_config_path):
        """target_branch_explicit is True when branch is set via inline arg."""
        result = resolve_config(
            base_config_path, "nonexistent.yaml", "resolve",
            args={"branch": "my-feature"},
        )
        assert result["target_branch_explicit"] is True
        assert result["target_branch"] == "my-feature"
