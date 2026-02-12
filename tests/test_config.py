"""Tests for lib/config.py — config parsing and model resolution."""

import os
import tempfile

import pytest
import yaml

from lib.config import deep_merge, detect_api_provider, resolve_config


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


# --- resolve_config ---


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp dir with base config files."""
    base = tmp_path / "base"
    base.mkdir()
    config = {
        "default_model": "claude-medium",
        "models": {
            "claude-small": {"id": "anthropic/claude-haiku-4-5"},
            "claude-medium": {"id": "anthropic/claude-sonnet-4-5"},
            "openai-small": {"id": "openai/gpt-5-nano"},
        },
        "openhands": {
            "version": "1.3.0",
            "max_iterations": 50,
            "pr_type": "ready",
        },
    }
    (base / "remote-dev-bot.yaml").write_text(yaml.dump(config))
    return tmp_path, str(base / "remote-dev-bot.yaml")


def test_resolve_config_default_alias(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "")
    assert result["alias"] == "claude-medium"
    assert result["model"] == "anthropic/claude-sonnet-4-5"


def test_resolve_config_explicit_alias(config_dir):
    tmp_path, base_path = config_dir
    result = resolve_config(base_path, "nonexistent.yaml", "claude-small")
    assert result["alias"] == "claude-small"
    assert result["model"] == "anthropic/claude-haiku-4-5"


def test_resolve_config_unknown_alias(config_dir):
    tmp_path, base_path = config_dir
    with pytest.raises(KeyError, match="Unknown model alias"):
        resolve_config(base_path, "nonexistent.yaml", "does-not-exist")


def test_resolve_config_override_wins(config_dir):
    tmp_path, base_path = config_dir
    override_path = str(tmp_path / "override.yaml")
    override = {
        "default_model": "openai-small",
        "openhands": {"max_iterations": 10},
    }
    with open(override_path, "w") as f:
        yaml.dump(override, f)

    result = resolve_config(base_path, override_path, "")
    assert result["alias"] == "openai-small"
    assert result["model"] == "openai/gpt-5-nano"
    assert result["max_iterations"] == 10
    # Version should come from base (not overridden)
    assert result["oh_version"] == "1.3.0"
    assert result["has_override"] is True


def test_resolve_config_openhands_defaults():
    """When base config has no openhands section, defaults kick in."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {"default_model": "m", "models": {"m": {"id": "anthropic/test"}}}, f
        )
        path = f.name
    try:
        result = resolve_config(path, "nonexistent.yaml", "")
        assert result["max_iterations"] == 50
        assert result["oh_version"] == "0.39.0"
        assert result["pr_type"] == "ready"
    finally:
        os.unlink(path)


def test_resolve_config_missing_base():
    """Missing base config file should still work (empty base)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"models": {"x": {"id": "anthropic/test"}}}, f)
        path = f.name
    try:
        # Use the override as the only config source, base doesn't exist
        result = resolve_config("nonexistent_base.yaml", path, "x")
        assert result["model"] == "anthropic/test"
    finally:
        os.unlink(path)


def test_resolve_config_malformed_yaml(tmp_path):
    """Malformed YAML should raise an error."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(": this is not valid yaml\n  - broken:\nindent")
    with pytest.raises(yaml.YAMLError):
        resolve_config(str(bad_yaml), "nonexistent.yaml", "")
