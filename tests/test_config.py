"""Tests for lib/config.py — config parsing, command parsing, and model resolution."""

import os
import tempfile

import pytest
import yaml

from lib.config import deep_merge, detect_api_provider, parse_command, resolve_config, resolve_commit_trailer


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

KNOWN_MODES = {"resolve", "design"}


def test_parse_command_resolve():
    assert parse_command("resolve", KNOWN_MODES) == ("resolve", "")


def test_parse_command_resolve_with_model():
    assert parse_command("resolve-claude-large", KNOWN_MODES) == ("resolve", "claude-large")


def test_parse_command_design():
    assert parse_command("design", KNOWN_MODES) == ("design", "")


def test_parse_command_design_with_model():
    assert parse_command("design-claude-large", KNOWN_MODES) == ("design", "claude-large")


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
                "prompt_prefix": "You are analyzing this issue.",
            },
        },
        "openhands": {
            "version": "1.3.0",
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
    assert "prompt_prefix" in result
    assert "analyzing" in result["prompt_prefix"]


def test_resolve_config_design_with_model(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "design-claude-large")
    assert result["mode"] == "design"
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
        "openhands": {"max_iterations": 10},
    }
    with open(override_path, "w") as f:
        yaml.dump(override, f)

    result = resolve_config(base_path, override_path, "resolve")
    assert result["alias"] == "gpt-small"
    assert result["model"] == "openai/gpt-5.1-codex-mini"
    assert result["max_iterations"] == 10
    # Version should come from base (not overridden)
    assert result["oh_version"] == "1.3.0"
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


def test_resolve_config_context_files_for_design(config_dir):
    """Design mode should include context_files when configured."""
    tmp_path, base_path = config_dir
    # Add context_files to the config
    with open(base_path) as f:
        config = yaml.safe_load(f)
    config["modes"]["design"]["context_files"] = ["README.md", "AGENTS.md"]
    with open(base_path, "w") as f:
        yaml.dump(config, f)

    result = resolve_config(base_path, "nonexistent.yaml", "design")
    assert "context_files" in result
    assert result["context_files"] == ["README.md", "AGENTS.md"]


def test_resolve_config_no_context_files_for_resolve(config_dir):
    """Resolve mode should not have context_files."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert "context_files" not in result


def test_resolve_config_no_prompt_prefix_for_resolve(config_dir):
    """Resolve mode should not have a prompt_prefix."""
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "resolve")
    assert "prompt_prefix" not in result


def test_resolve_config_openhands_defaults():
    """When base config has no openhands section, defaults kick in."""
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
        assert result["oh_version"] == "0.39.0"
        assert result["pr_type"] == "ready"
    finally:
        os.unlink(path)


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
        "Model: {model_alias} ({model_id}), openhands-ai v{oh_version}",
        "claude-large",
        "anthropic/claude-opus-4-5",
        "1.3.0",
    )
    assert result == "Model: claude-large (anthropic/claude-opus-4-5), openhands-ai v1.3.0"


def test_resolve_commit_trailer_empty_template():
    """Empty template returns empty string."""
    assert resolve_commit_trailer("", "alias", "model", "1.0") == ""
    assert resolve_commit_trailer(None, "alias", "model", "1.0") == ""


def test_resolve_commit_trailer_partial_template():
    """Template with only some variables."""
    result = resolve_commit_trailer("Model: {model_alias}", "claude-small", "anthropic/claude-sonnet-4-5", "1.3.0")
    assert result == "Model: claude-small"


def test_resolve_commit_trailer_no_variables():
    """Template with no variables."""
    result = resolve_commit_trailer("Static trailer", "alias", "model", "1.0")
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
                "openhands": {"version": "1.3.0"},
                "commit_trailer": "Model: {model_alias} ({model_id}), v{oh_version}",
            },
            f,
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "resolve")
        assert result["commit_trailer"] == "Model: m1 (anthropic/test-model), v1.3.0"
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
                "openhands": {"version": "1.3.0"},
                "commit_trailer": "Base trailer: {model_alias}",
            },
            base_f,
        )
        base_path = base_f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as override_f:
        yaml.dump(
            {
                "commit_trailer": "Override trailer: {model_id}",
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
                "commit_trailer": "Base trailer: {model_alias}",
            },
            base_f,
        )
        base_path = base_f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as override_f:
        yaml.dump(
            {
                "commit_trailer": "",
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
