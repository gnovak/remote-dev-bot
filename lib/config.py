"""Config parsing for remote-dev-bot.

Loads base config from remote-dev-bot repo, merges with optional
per-repo override config, resolves model aliases and modes, and writes
GitHub Actions outputs.

Commands follow the pattern: /agent-<verb>[-<model>]
  /agent-resolve              — resolve mode, default model
  /agent-resolve-claude-large — resolve mode, specific model
  /agent-design               — design mode, default model

Arguments can be passed on subsequent lines:
  /agent resolve
  max_iterations = 75
  extra_files = file1.txt file2.txt
  timeout_minutes = 60

Argument names are normalized (spaces/dashes/underscores are equivalent).
Values after = can be single values or space-separated lists.

Called by remote-dev-bot.yml at runtime and imported directly by unit tests.
"""

import argparse
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

DEFAULT_TIMEOUT_MINUTES = 120

# Arguments that can be overridden via inline args (lines after the command)
ALLOWED_ARGS = {
    "max_iterations": int,  # openhands.max_iterations
    "timeout_minutes": int,  # openhands.timeout_minutes
    "extra_files": list,  # mode's extra_files
    "target_branch": str,  # openhands.target_branch
}


def normalize_arg_name(name):
    """Normalize argument name: lowercase, replace spaces/dashes with underscores.

    >>> normalize_arg_name("max iterations")
    'max_iterations'
    >>> normalize_arg_name("max-iterations")
    'max_iterations'
    >>> normalize_arg_name("Max_Iterations")
    'max_iterations'
    >>> normalize_arg_name("extra files")
    'extra_files'
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
    >>> parse_args(["extra_files = file1.txt file2.txt"])
    {'extra_files': ['file1.txt', 'file2.txt']}
    >>> parse_args(["extra files = README.md"])
    {'extra_files': ['README.md']}
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
    >>> parse_invocation("/agent-design-claude-small\\nextra_files = a.txt b.txt", {"resolve", "design"})
    ('design', 'claude-small', {'extra_files': ['a.txt', 'b.txt']})
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
    command_string = command_string.lower().strip()

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


def resolve_config(base_path, override_path, command_string, local_path=None, timeout_minutes=None, args=None):
    """Load configs, merge, resolve mode + alias, return outputs dict.

    Applies up to three config layers (each is optional):
      base_path     — remote-dev-bot defaults (from sparse-checkout of rdb repo)
      override_path — target repo's remote-dev-bot.yaml
      local_path    — target repo's remote-dev-bot.local.yaml (deepest override)

    command_string is the raw text after '/agent-' (e.g. 'resolve-claude-large').
    timeout_minutes is the per-invocation override (from --timeout-minutes argparse flag).
    args is an optional dict of command-line argument overrides (e.g. {'max_iterations': 75}).

    Returns a dict with keys: mode, model, alias, max_iterations, oh_version,
    pr_type, has_override, timeout_minutes, plus any mode-specific settings.
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
    if args:
        print("Runtime args (from comment body):")
        for k, v in args.items():
            print(f"  {k} = {v}")
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

    # Graceful wrap-up settings
    graceful_wrapup = oh.get("graceful_wrapup", {})
    wrapup_enabled = graceful_wrapup.get("enabled", True)
    wrapup_threshold = graceful_wrapup.get("threshold", 0.8)
    if not (0 < wrapup_threshold <= 1):
        raise ValueError(
            f"openhands.graceful_wrapup.threshold must be between 0 and 1, got: {wrapup_threshold}"
        )

    # Resolve timeout: per-invocation > yaml config > hardcoded default
    # Per-invocation can come from inline arg (timeout = N) or --timeout-minutes flag.
    # NOTE: GitHub Actions has a hard 6-hour limit. If a run legitimately needs
    # more than 6 hours, set timeout-minutes in the calling workflow's job definition.
    yaml_timeout = oh.get("timeout_minutes")
    effective_timeout = timeout_minutes if timeout_minutes is not None else (args or {}).get("timeout_minutes")
    resolved_timeout = (
        effective_timeout if effective_timeout is not None
        else (yaml_timeout if yaml_timeout is not None
              else DEFAULT_TIMEOUT_MINUTES)
    )

    # Mode settings
    action = mode_config.get("action", "pr")

    # Apply command-line arg overrides
    if "max_iterations" in args:
        max_iter = args["max_iterations"]
    if "timeout_minutes" in args:
        resolved_timeout = args["timeout_minutes"]
    if "target_branch" in args:
        target_branch = args["target_branch"]

    # Calculate the iteration warning threshold (iteration number at which to warn)
    wrapup_iteration = int(max_iter * wrapup_threshold) if wrapup_enabled else 0

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
        "graceful_wrapup_enabled": wrapup_enabled,
        "graceful_wrapup_threshold": wrapup_threshold,
        "graceful_wrapup_iteration": wrapup_iteration,
        "timeout_minutes": resolved_timeout,
    }

    # Include extra_instructions if the mode defines one (appended to canonical prompt)
    if "extra_instructions" in mode_config:
        result["extra_instructions"] = mode_config["extra_instructions"]

    # Include extra_files: all layers are additive (base + override + local + runtime args).
    # Using pre-merge configs here instead of mode_config (post-merge) so that user-provided
    # extra_files always extend the base list rather than silently replacing it.
    base_mode_extra = base_config.get("modes", {}).get(mode, {}).get("extra_files", [])
    override_mode_extra = override_config.get("modes", {}).get(mode, {}).get("extra_files", [])
    local_mode_extra = local_config.get("modes", {}).get(mode, {}).get("extra_files", [])
    arg_extra = args.get("extra_files", [])
    seen = set()
    combined_extra_files = []
    for f in base_mode_extra + override_mode_extra + local_mode_extra + arg_extra:
        if f not in seen:
            seen.add(f)
            combined_extra_files.append(f)
    if combined_extra_files:
        result["extra_files"] = combined_extra_files

    # Log command-line args if any were provided
    if args:
        print("Command-line args:")
        for key, value in args.items():
            print(f"  {key}: {value}")
        print()

    # Include max_iterations for agentic loop modes (design and review)
    if action == "design" and "max_iterations" in mode_config:
        result["design_max_iterations"] = mode_config["max_iterations"]
    if action == "review" and "max_iterations" in mode_config:
        result["review_max_iterations"] = mode_config["max_iterations"]

    # Resolve commit_trailer template (for resolve mode) — lives under openhands:
    commit_trailer_template = config.get("openhands", {}).get("commit_trailer", "")
    result["commit_trailer"] = resolve_commit_trailer(
        commit_trailer_template, alias, model_id, oh_version
    )

    return result


def main():
    """Main entry point for config parsing.

    Accepts either:
      1. COMMENT_BODY env var (primary, new): full comment body with optional args
      2. Argparse with positional command and --timeout-minutes flag (legacy, internal):
         called by the workflow step for backwards compatibility

    When COMMENT_BODY env var is set, reads the full comment body and parses it
    using parse_invocation (supports multi-line argument syntax).
    Otherwise, falls back to argparse: positional command string + --timeout-minutes.
    """
    base_path = ".remote-dev-bot/remote-dev-bot.yaml"
    override_path = "remote-dev-bot.yaml"
    local_path = "remote-dev-bot.local.yaml"

    # Check if we should read the full comment body from env var
    comment_body = os.environ.get("COMMENT_BODY", "")
    command_prefix = os.environ.get("COMMAND_PREFIX", "agent")

    # Set up argparse for the legacy internal path (--timeout-minutes flag)
    parser = argparse.ArgumentParser(description="Remote Dev Bot config resolver")
    parser.add_argument(
        "command",
        nargs="?",
        default="",
        help="Command string following '/agent-' (e.g. 'resolve-claude-large')",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=None,
        metavar="N",
        help="Override job timeout in minutes for this invocation (internal, called by workflow)",
    )
    parsed_args = parser.parse_args()

    try:
        if comment_body:
            # Primary mode: parse full comment body with args (COMMENT_BODY env var)
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

            mode, model_alias, invocation_args = parse_invocation(comment_body, known_modes, command_prefix)
            command_string = f"{mode}-{model_alias}" if model_alias else mode
            result = resolve_config(
                base_path, override_path, command_string,
                local_path=local_path,
                args=invocation_args,
            )
        else:
            # Legacy mode: argparse with positional command + optional --timeout-minutes
            # This path is called by the workflow step internally
            result = resolve_config(
                base_path, override_path, parsed_args.command,
                local_path=local_path,
                timeout_minutes=parsed_args.timeout_minutes,
            )
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
            if "extra_instructions" in result:
                f.write(f"extra_instructions={result['extra_instructions']}\n")
            if "extra_files" in result:
                f.write(f"extra_files={json.dumps(result['extra_files'])}\n")
            if "design_max_iterations" in result:
                f.write(f"design_max_iterations={result['design_max_iterations']}\n")
            if "review_max_iterations" in result:
                f.write(f"review_max_iterations={result['review_max_iterations']}\n")
            f.write(f"commit_trailer={result['commit_trailer']}\n")
            f.write(f"graceful_wrapup_enabled={str(result['graceful_wrapup_enabled']).lower()}\n")
            f.write(f"graceful_wrapup_iteration={result['graceful_wrapup_iteration']}\n")
            f.write(f"timeout_minutes={result['timeout_minutes']}\n")

    # Log for visibility
    override_label = "target repo" if result["has_override"] else "none"
    print(f"Config: base=remote-dev-bot, override={override_label}")
    print(f"Mode: {result['mode']} (action: {result['action']})")
    print(f"Model alias: {result['alias']}")
    print(f"Model ID: {result['model']}")
    if comment_body:
        timeout_source = "default (COMMENT_BODY mode)"
    elif parsed_args.timeout_minutes is not None:
        timeout_source = "per-invocation override (--timeout-minutes)"
    else:
        timeout_source = "default"
    print(f"Timeout: {result['timeout_minutes']} minutes ({timeout_source})")


if __name__ == "__main__":
    main()
