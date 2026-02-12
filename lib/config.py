"""Config parsing for remote-dev-bot.

Loads base config from remote-dev-bot repo, merges with optional
per-repo override config, resolves model aliases and modes, and writes
GitHub Actions outputs.

Commands follow the pattern: /agent-<verb>[-<model>]
  /agent-resolve           — resolve mode, default model
  /agent-resolve-claude-large — resolve mode, specific model
  /agent-design            — design mode, default model

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


def parse_command(command_string, known_modes):
    """Parse a command string into (mode, model_alias).

    The command string is what follows '/agent-' in the comment.
    Grammar: <verb>[-<model>]

    If the command string is empty, raises ValueError (bare /agent not allowed).
    The first segment must be a known mode; remaining segments form the model alias.

    >>> parse_command("resolve", {"resolve", "design"})
    ('resolve', '')
    >>> parse_command("resolve-claude-large", {"resolve", "design"})
    ('resolve', 'claude-large')
    >>> parse_command("design", {"resolve", "design"})
    ('design', '')
    >>> parse_command("design-claude-large", {"resolve", "design"})
    ('design', 'claude-large')
    """
    if not command_string:
        raise ValueError(
            "Bare /agent is not supported. "
            f"Use /agent-<mode> where mode is one of: {sorted(known_modes)}"
        )

    parts = command_string.split("-", 1)
    verb = parts[0]

    if verb not in known_modes:
        raise ValueError(
            f"Unknown mode: '{verb}'. Available modes: {sorted(known_modes)}"
        )

    model_alias = parts[1] if len(parts) > 1 else ""
    return verb, model_alias


def resolve_config(base_path, override_path, command_string):
    """Load configs, merge, resolve mode + alias, return outputs dict.

    command_string is the raw text after '/agent-' (e.g. 'resolve-claude-large').

    Returns a dict with keys: mode, model, alias, max_iterations, oh_version,
    pr_type, has_override, plus any mode-specific settings.
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

    # Parse command into mode + model alias
    modes = config.get("modes", {})
    known_modes = set(modes.keys())
    mode, alias = parse_command(command_string, known_modes)

    mode_config = modes[mode]

    # Resolve model alias — use mode's default if none specified
    if not alias:
        alias = mode_config.get("default_model", config.get("default_model", "claude-small"))

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

    # Mode settings
    action = mode_config.get("action", "pr")

    result = {
        "mode": mode,
        "action": action,
        "model": model_id,
        "alias": alias,
        "max_iterations": max_iter,
        "oh_version": oh_version,
        "pr_type": pr_type,
        "has_override": bool(override_config),
    }

    # Include prompt_prefix if the mode defines one
    if "prompt_prefix" in mode_config:
        result["prompt_prefix"] = mode_config["prompt_prefix"]

    return result


def main():
    command_string = sys.argv[1] if len(sys.argv) > 1 else ""

    base_path = ".remote-dev-bot/remote-dev-bot.yaml"
    override_path = "remote-dev-bot.yaml"

    try:
        result = resolve_config(base_path, override_path, command_string)
    except (KeyError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Write outputs
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"mode={result['mode']}\n")
            f.write(f"action={result['action']}\n")
            f.write(f"model={result['model']}\n")
            f.write(f"alias={result['alias']}\n")
            f.write(f"max_iterations={result['max_iterations']}\n")
            f.write(f"oh_version={result['oh_version']}\n")
            f.write(f"pr_type={result['pr_type']}\n")

    # Log for visibility
    override_label = "target repo" if result["has_override"] else "none"
    print(f"Config: base=remote-dev-bot, override={override_label}")
    print(f"Mode: {result['mode']} (action: {result['action']})")
    print(f"Model alias: {result['alias']}")
    print(f"Model ID: {result['model']}")


if __name__ == "__main__":
    main()
