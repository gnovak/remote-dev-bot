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
        "examples/agent.yml",
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
    assert "openhands" in bot_config


def test_default_model_exists_in_models(bot_config):
    default = bot_config["default_model"]
    assert default in bot_config["models"], (
        f"default_model '{default}' not in models"
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
