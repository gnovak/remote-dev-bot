"""Config parsing for remote-dev-bot.

Loads base config from remote-dev-bot repo, merges with optional
per-repo override config, resolves model aliases and modes, and writes
GitHub Actions outputs.

Commands follow the pattern: /agent-<verb>[-<model>]
  /agent-resolve           — resolve mode, default model
  /agent-resolve-claude-large — resolve mode, specific model
  /agent-design            — design mode, default model

Arguments can be passed on subsequent lines:
  /agent resolve
  max iterations = 75
  context = file1.txt file2.txt

Argument names are normalized (spaces/dashes/underscores are equivalent).
Values after = can be single values or space-separated lists.

Called by remote-dev-bot.yml at runtime and imported directly by unit tests.
"""

import json
import os
import re
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

# Arguments that can be overridden via command-line args
ALLOWED_ARGS = {
    "max_iterations": int,  # openhands.max_iterations
    "context": list,  # mode's context_files (alias)
    "context_files": list,  # mode's context_files
}


def normalize_arg_name(name):
    """Normalize argument name: lowercase, replace spaces/dashes with underscores.

    >>> normalize_arg_name("max iterations")
    'max_iterations'
    >>> normalize_arg_name("max-iterations")
    'max_iterations'
    >>> normalize_arg_name("Max_Iterations")
    'max_iterations'
    >>> normalize_arg_name("context files")
    'context_files'
    """
    return re.sub(r"[\s-]+", "_", name.strip().lower())


def parse_args(lines):
    """Parse argument lines into a dict.

    Each line should be in the format: name = value
    Names are normalized (spaces/dashes/underscores equivalent).
    Values can be single values or space-separated lists.

    >>> parse_args(["max iterations = 75"])
    {'max_iterations': 75}
    >>> parse_args(["max-iterations = 100"])
    {'max_iterations': 100}
    >>> parse_args(["context = file1.txt file2.txt"])
    {'context_files': ['file1.txt', 'file2.txt']}
    >>> parse_args(["context files = README.md"])
    {'context_files': ['README.md']}
    >>> parse_args([])
    {}
    """
    result = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            # Skip lines without = (could be continuation or comment)
            continue

        name, _, value = line.partition("=")
        name = normalize_arg_name(name)
        value = value.strip()

        if not name or not value:
            continue

        # Map 'context' alias to 'context_files'
        if name == "context":
            name = "context_files"

        if name not in ALLOWED_ARGS:
            raise ValueError(
                f"Unknown argument: '{name}'. Allowed: {sorted(ALLOWED_ARGS.keys())}"
            )

        arg_type = ALLOWED_ARGS[name]
        if arg_type == int:
            try:
                result[name] = int(value)
            except ValueError:
                raise ValueError(f"Argument '{name}' must be an integer, got: {value}")
        elif arg_type == list:
            # Split on whitespace for list values
            result[name] = value.split()
        else:
            result[name] = value

    return result


def parse_invocation(comment_body, known_modes, command_prefix="agent"):
    """Parse a full comment body into (mode, model_alias, args).

    The first line should be the command (e.g., "/agent resolve claude-large").
    Subsequent lines are optional keyword arguments.

    command_prefix is the slash command prefix (e.g., "agent" for /agent, "dogfood"
    for /dogfood). Defaults to "agent".

    >>> parse_invocation("/agent resolve", {"resolve", "design"})
    ('resolve', '', {})
    >>> parse_invocation("/agent resolve claude-large", {"resolve", "design"})
    ('resolve', 'claude-large', {})
    >>> parse_invocation("/agent resolve\\nmax iterations = 75", {"resolve", "design"})
    ('resolve', '', {'max_iterations': 75})
    >>> parse_invocation("/agent-design-claude-small\\ncontext = a.txt b.txt", {"resolve", "design"})
    ('design', 'claude-small', {'context_files': ['a.txt', 'b.txt']})
    >>> parse_invocation("/dogfood resolve", {"resolve", "design"}, command_prefix="dogfood")
    ('resolve', '', {})
    """
    lines = comment_body.strip().split("\n")
    if not lines:
        raise ValueError("Empty comment body")

    first_line = lines[0].strip()
    prefix = re.escape(command_prefix)

    # Extract command from first line: "/prefix-resolve-claude-large" or "/prefix resolve claude large"
    # Match /prefix followed by dash or space, then capture the rest
    match = re.match(rf"^/{prefix}[- ](.+?)(?:\s*$|\s+[^a-zA-Z0-9-])", first_line, re.IGNORECASE)
    if not match:
        # Try simpler match for just the command part
        match = re.match(rf"^/{prefix}[- ]([a-zA-Z0-9][a-zA-Z0-9 -]*)", first_line, re.IGNORECASE)

    if not match:
        # Check if it's bare /prefix
        if re.match(rf"^/{prefix}\s*$", first_line, re.IGNORECASE):
            raise ValueError(
                f"Bare /{command_prefix} is not supported. "
                f"Use /{command_prefix}-<mode> where mode is one of: {sorted(known_modes)}"
            )
        raise ValueError(f"Invalid command format: {first_line}")

    command_part = match.group(1).strip()
    # Normalize: replace spaces with dashes, lowercase
    command_string = re.sub(r"\s+", "-", command_part).lower()

    # Parse the command string into mode and model alias
    mode, model_alias = parse_command(command_string, known_modes)

    # Parse remaining lines as arguments
    arg_lines = lines[1:] if len(lines) > 1 else []
    args = parse_args(arg_lines)

    return mode, model_alias, args


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

    Commands are case-insensitive (e.g., /agent-resolve-Claude-Large works).

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
    >>> parse_command("Resolve-Claude-Large", {"resolve", "design"})
    ('resolve', 'claude-large')
    """
    if not command_string:
        raise ValueError(
            "Bare /agent is not supported. "
            f"Use /agent-<mode> where mode is one of: {sorted(known_modes)}"
        )

    # Normalize to lowercase for case-insensitive matching
    command_string = command_string.lower()

    parts = command_string.split("-", 1)
    verb = parts[0]

    if verb not in known_modes:
        raise ValueError(
            f"Unknown mode: '{verb}'. Available modes: {sorted(known_modes)}"
        )

    model_alias = parts[1] if len(parts) > 1 else ""
    return verb, model_alias


def resolve_commit_trailer(template, alias, model_id, oh_version):
    """Resolve template variables in commit_trailer.

    Supported variables: {model_alias}, {model_id}, {oh_version}
    Returns empty string if template is empty/None.
    """
    if not template:
        return ""
    return template.format(
        model_alias=alias,
        model_id=model_id,
        oh_version=oh_version,
    )


def resolve_config(base_path, override_path, command_string, local_path=None, args=None):
    """Load configs, merge, resolve mode + alias, return outputs dict.

    Applies up to three config layers (each is optional):
      base_path     — remote-dev-bot defaults (from sparse-checkout of rdb repo)
      override_path — target repo's remote-dev-bot.yaml
      local_path    — target repo's remote-dev-bot.local.yaml (deepest override)

    command_string is the raw text after '/agent-' (e.g. 'resolve-claude-large').
    args is an optional dict of command-line argument overrides (e.g. {'max_iterations': 75}).

    Returns a dict with keys: mode, model, alias, max_iterations, oh_version,
    pr_type, has_override, plus any mode-specific settings.
    """
    if args is None:
        args = {}
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

    # Read local extension from target repo (if it exists)
    local_config = {}
    if local_path and os.path.exists(local_path):
        with open(local_path) as f:
            local_config = yaml.safe_load(f) or {}

    # Merge: base → override → local (each layer wins over the previous)
    config = deep_merge(deep_merge(base_config, override_config), local_config)

    # Log the merge so users can see what config is actually in effect
    print("=== Config Merge ===")
    print("Base (remote-dev-bot defaults):")
    print(yaml.dump(base_config, default_flow_style=False, sort_keys=False).rstrip() if base_config else "  (none)")
    print()
    if override_config:
        print("Override (target repo remote-dev-bot.yaml):")
        print(yaml.dump(override_config, default_flow_style=False, sort_keys=False).rstrip())
    else:
        print("Override (target repo remote-dev-bot.yaml): (none)")
    print()
    if local_config:
        print("Local extension (remote-dev-bot.local.yaml):")
        print(yaml.dump(local_config, default_flow_style=False, sort_keys=False).rstrip())
        print()
    print("Merged:")
    print(yaml.dump(config, default_flow_style=False, sort_keys=False).rstrip())
    print("===================")
    print()

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
    # NOTE: keep this default in sync with scripts/compile.py inline_config_parsing()
    oh_version = oh.get("version", "1.4.0")
    pr_type = oh.get("pr_type", "ready")
    on_failure = oh.get("on_failure", "comment")
    target_branch = oh.get("target_branch", "main")
    assign_issue = oh.get("assign_issue", True)
    assign_pr = oh.get("assign_pr", True)
    if on_failure not in ("comment", "draft"):
        raise ValueError(
            f"openhands.on_failure must be 'comment' or 'draft', got: {on_failure!r}"
        )

    # Mode settings
    action = mode_config.get("action", "pr")

    # Apply command-line arg overrides
    if "max_iterations" in args:
        max_iter = args["max_iterations"]

    result = {
        "mode": mode,
        "action": action,
        "model": model_id,
        "alias": alias,
        "max_iterations": max_iter,
        "oh_version": oh_version,
        "pr_type": pr_type,
        "on_failure": on_failure,
        "target_branch": target_branch,
        "assign_issue": assign_issue,
        "assign_pr": assign_pr,
        "has_override": bool(override_config),
    }

    # Include prompt_prefix if the mode defines one
    if "prompt_prefix" in mode_config:
        result["prompt_prefix"] = mode_config["prompt_prefix"]

    # Include context_files: command-line args append to mode config
    # (replace semantics would force users to re-type all existing files)
    if "context_files" in mode_config:
        result["context_files"] = mode_config["context_files"] + args.get("context_files", [])
    elif "context_files" in args:
        result["context_files"] = args["context_files"]

    # Log command-line args if any were provided
    if args:
        print("Command-line args:")
        for key, value in args.items():
            print(f"  {key}: {value}")
        print()

    # Resolve commit_trailer template (for resolve mode)
    commit_trailer_template = config.get("commit_trailer", "")
    result["commit_trailer"] = resolve_commit_trailer(
        commit_trailer_template, alias, model_id, oh_version
    )

    return result


def main():
    """Main entry point for config parsing.

    Accepts either:
      1. A single command string argument (legacy): "resolve-claude-large"
      2. A full comment body via stdin (new): "/agent resolve\\nmax iterations = 75"

    When COMMENT_BODY env var is set, reads the full comment from stdin.
    Otherwise, uses the first command-line argument as the command string.
    """
    base_path = ".remote-dev-bot/remote-dev-bot.yaml"
    override_path = "remote-dev-bot.yaml"
    local_path = "remote-dev-bot.local.yaml"

    # Check if we should read the full comment body from env var
    comment_body = os.environ.get("COMMENT_BODY", "")
    command_prefix = os.environ.get("COMMAND_PREFIX", "agent")

    try:
        if comment_body:
            # New mode: parse full comment body with args
            # First, we need to load config to get known_modes
            base_config = {}
            if os.path.exists(base_path):
                with open(base_path) as f:
                    base_config = yaml.safe_load(f) or {}
            override_config = {}
            if os.path.exists(override_path):
                with open(override_path) as f:
                    override_config = yaml.safe_load(f) or {}
            local_config = {}
            if local_path and os.path.exists(local_path):
                with open(local_path) as f:
                    local_config = yaml.safe_load(f) or {}
            config = deep_merge(deep_merge(base_config, override_config), local_config)
            known_modes = set(config.get("modes", {}).keys())

            mode, model_alias, args = parse_invocation(comment_body, known_modes, command_prefix)
            command_string = f"{mode}-{model_alias}" if model_alias else mode
            result = resolve_config(base_path, override_path, command_string, local_path=local_path, args=args)
        else:
            # Legacy mode: single command string argument
            command_string = sys.argv[1] if len(sys.argv) > 1 else ""
            result = resolve_config(base_path, override_path, command_string, local_path=local_path)
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
            f.write(f"on_failure={result['on_failure']}\n")
            f.write(f"target_branch={result['target_branch']}\n")
            f.write(f"assign_issue={str(result['assign_issue']).lower()}\n")
            f.write(f"assign_pr={str(result['assign_pr']).lower()}\n")
            if "context_files" in result:
                f.write(f"context_files={json.dumps(result['context_files'])}\n")
            f.write(f"commit_trailer={result['commit_trailer']}\n")

    # Log for visibility
    override_label = "target repo" if result["has_override"] else "none"
    print(f"Config: base=remote-dev-bot, override={override_label}")
    print(f"Mode: {result['mode']} (action: {result['action']})")
    print(f"Model alias: {result['alias']}")
    print(f"Model ID: {result['model']}")


if __name__ == "__main__":
    main()
