"""Config parsing for remote-dev-bot.

Loads base config from remote-dev-bot repo, merges with optional
per-repo override config, resolves model aliases, and writes
GitHub Actions outputs.

Called by resolve.yml at runtime (checked out from main via sparse-checkout)
and imported directly by unit tests. See CLAUDE.md "PR constraints" for why
config parsing changes must be in their own PR, separate from workflow changes.
"""

import os
import sys

import yaml


def deep_merge(base, override):
    """Merge override into base, recursively for dicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


KNOWN_PROVIDERS = ("anthropic/", "openai/", "gemini/")


def detect_api_provider(model_id):
    """Return the provider name for a model ID.

    >>> detect_api_provider("anthropic/claude-sonnet-4-5")
    'anthropic'
    >>> detect_api_provider("openai/gpt-5-nano")
    'openai'
    >>> detect_api_provider("gemini/gemini-2.5-flash")
    'gemini'
    """
    for prefix in KNOWN_PROVIDERS:
        if model_id.startswith(prefix):
            return prefix.rstrip("/")
    raise ValueError(f"Unknown provider for model: {model_id}")


def resolve_config(base_path, override_path, alias):
    """Load configs, merge, resolve alias, return outputs dict.

    Returns a dict with keys: model, alias, max_iterations, oh_version, pr_type.
    """
    # Read base config
    base_config = {}
    if os.path.exists(base_path):
        with open(base_path) as f:
            base_config = yaml.safe_load(f) or {}

    # Read override config from target repo (if it exists)
    override_config = {}
    if os.path.exists(override_path):
        with open(override_path) as f:
            override_config = yaml.safe_load(f) or {}

    # Merge: target repo overrides remote-dev-bot defaults
    config = deep_merge(base_config, override_config)

    # Resolve model alias
    if not alias:
        alias = config.get("default_model", "claude-small")

    models = config.get("models", {})
    if alias not in models:
        raise KeyError(
            f"Unknown model alias: {alias}. Available: {list(models.keys())}"
        )

    model_id = models[alias]["id"]

    # Read OpenHands settings
    oh = config.get("openhands", {})
    max_iter = oh.get("max_iterations", 50)
    oh_version = oh.get("version", "0.39.0")
    pr_type = oh.get("pr_type", "ready")

    return {
        "model": model_id,
        "alias": alias,
        "max_iterations": max_iter,
        "oh_version": oh_version,
        "pr_type": pr_type,
        "has_override": bool(override_config),
    }


def main():
    alias = sys.argv[1] if len(sys.argv) > 1 else ""

    base_path = ".remote-dev-bot/remote-dev-bot.yaml"
    override_path = "remote-dev-bot.yaml"

    try:
        result = resolve_config(base_path, override_path, alias)
    except (KeyError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Write outputs
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"model={result['model']}\n")
            f.write(f"alias={result['alias']}\n")
            f.write(f"max_iterations={result['max_iterations']}\n")
            f.write(f"oh_version={result['oh_version']}\n")
            f.write(f"pr_type={result['pr_type']}\n")

    # Log for visibility
    override_label = "target repo" if result["has_override"] else "none"
    print(f"Config: base=remote-dev-bot, override={override_label}")
    print(f"Model alias: {result['alias']}")
    print(f"Model ID: {result['model']}")
    print(f"PR type: {result['pr_type']}")


if __name__ == "__main__":
    main()
