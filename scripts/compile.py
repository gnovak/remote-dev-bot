#!/usr/bin/env python3
"""Compile two self-contained workflows from the reusable workflow + shim.

Reads the reusable workflow (resolve.yml), the shim (agent.yml), and config
(remote-dev-bot.yaml), then produces two compiled files:

  dist/agent-resolve.yml  — triggers on /agent-resolve[-<model>]
  dist/agent-design.yml   — triggers on /agent-design[-<model>]

Each compiled file is self-contained: inlined config, no cross-repo checkout,
uses github.token by default (RDB_PAT_TOKEN and GitHub App optional).

Usage:
    python scripts/compile.py                  # writes to dist/
    python scripts/compile.py output_dir/      # custom output dir
"""

import os
import re
import sys

import yaml
from pathlib import Path


# Custom YAML representer: use block scalar (|) for multi-line strings
# so that `run:` blocks are human-readable in the compiled output.
class BlockScalarStr(str):
    """String subclass that triggers block scalar style in YAML output."""
    pass


def _block_scalar_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


yaml.add_representer(BlockScalarStr, _block_scalar_representer)


def load_yaml(path):
    """Load YAML file, exit if missing."""
    if not os.path.exists(path):
        print(f"ERROR: Required file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        data = yaml.safe_load(f.read())
        # Handle 'on:' being parsed as boolean True by PyYAML
        if True in data and 'on' not in data:
            data['on'] = data.pop(True)
        return data


def find_step(steps, name):
    """Find a step by name. Raises KeyError if not found."""
    for step in steps:
        if step.get("name") == name:
            return step
    raise KeyError(f"Step not found: '{name}'")


def extract_security_gate(shim):
    """Extract the author_association list from the shim's if condition."""
    if_condition = shim.get("jobs", {}).get("resolve", {}).get("if", "")
    match = re.search(r'fromJson\(\'(\[.*?\])\'\)', if_condition)
    if match:
        return match.group(1)
    return '["OWNER","COLLABORATOR","MEMBER"]'


def inline_config_parsing(config_yaml, mode):
    """Generate inline Python for parsing config, specialized for a known mode.

    Since mode is known at compile time, we just strip the known prefix
    (e.g., /agent-resolve- or /agent-design-) to get the model alias.
    """
    modes_config = config_yaml.get("modes", {})
    mode_config = modes_config.get(mode, {})
    default_model = mode_config.get("default_model",
                                     config_yaml.get("default_model", "claude-small"))

    models = config_yaml.get("models", {})
    oh = config_yaml.get("openhands", {})
    max_iterations = oh.get("max_iterations", 50)
    # NOTE: keep this default in sync with lib/config.py resolve_config()
    oh_version = oh.get("version", "1.3.0")
    pr_type = oh.get("pr_type", "ready")
    on_failure = oh.get("on_failure", "comment")
    target_branch = oh.get("target_branch", "main")

    # Commit trailer template (resolve mode only)
    commit_trailer_template = config_yaml.get("commit_trailer", "")
    # Escape for Python string literal
    commit_trailer_escaped = commit_trailer_template.replace('\\', '\\\\').replace('"', '\\"')

    # Build models dict as Python code
    models_dict_lines = []
    for alias, model_info in models.items():
        model_id = model_info["id"]
        models_dict_lines.append(f'    "{alias}": "{model_id}",')
    models_dict = "\n".join(models_dict_lines)

    code = f'''python3 << 'PYTHON_EOF'
import os
import sys
import re

# --- MODEL_CONFIG: default model and available aliases ---
# Change the default model or add/modify aliases below
MODELS = {{
{models_dict}
}}
DEFAULT_MODEL = "{default_model}"

# --- MAX_ITERATIONS: how many steps the agent can take ---
MAX_ITERATIONS = {max_iterations}

# --- OpenHands version ---
OH_VERSION = "{oh_version}"

# --- PR_STYLE: "draft" or "ready" ---
PR_TYPE = "{pr_type}"

# --- ON_FAILURE: what to do when the agent can't fully resolve the issue ---
# "comment" — post a comment explaining the situation, no PR
# "draft"   — post the same comment AND open a draft PR with partial changes
ON_FAILURE = "{on_failure}"

# --- TARGET_BRANCH: branch the agent opens PRs against ---
TARGET_BRANCH = "{target_branch}"

# --- COMMIT_TRAILER: appended to commit messages (resolve mode only) ---
# Supported variables: {{model_alias}}, {{model_id}}, {{oh_version}}
COMMIT_TRAILER_TEMPLATE = "{commit_trailer_escaped}"

# Parse alias from comment — mode is known at compile time
comment = os.environ.get("COMMENT", "")
# Strip the known prefix: "/agent-{mode}-claude-large do X" -> "claude-large"
match = re.match(r'^/agent-{mode}-?([a-z0-9-]*)', comment)
alias = match.group(1) if match else ""

if not alias:
    alias = DEFAULT_MODEL

if alias not in MODELS:
    print(f"ERROR: Unknown model alias: {{alias}}. Available: {{list(MODELS.keys())}}", file=sys.stderr)
    sys.exit(1)

model = MODELS[alias]

# Resolve commit trailer template
commit_trailer = ""
if COMMIT_TRAILER_TEMPLATE:
    commit_trailer = COMMIT_TRAILER_TEMPLATE.format(
        model_alias=alias,
        model_id=model,
        oh_version=OH_VERSION,
    )

# Write outputs
output_file = os.environ.get("GITHUB_OUTPUT")
if output_file:
    with open(output_file, "a") as f:
        f.write(f"model={{model}}\\n")
        f.write(f"alias={{alias}}\\n")
        f.write(f"max_iterations={{MAX_ITERATIONS}}\\n")
        f.write(f"oh_version={{OH_VERSION}}\\n")
        f.write(f"pr_type={{PR_TYPE}}\\n")
        f.write(f"on_failure={{ON_FAILURE}}\\n")
        f.write(f"target_branch={{TARGET_BRANCH}}\\n")
        f.write(f"commit_trailer={{commit_trailer}}\\n")

# Log for visibility
print(f"Mode: {mode}")
print(f"Model alias: {{alias}}")
print(f"Model ID: {{model}}")
print(f"PR type: {{PR_TYPE}}")
PYTHON_EOF
'''
    return code


def make_header(mode):
    """Generate the configuration header comment for a compiled file."""
    return f"""# ============================================================
# CONFIGURATION - Remote Dev Bot ({mode.title()} Mode)
# ============================================================
#
# This is a compiled, self-contained workflow. To customize:
#
# - MODEL_CONFIG: Search for this to change the default model or add/modify aliases
# - PR_STYLE: Search for this to switch between draft and ready PRs
# - MAX_ITERATIONS: Search for this to adjust how many steps the agent takes
# - SECURITY_GATE: Search for this to change who can trigger the agent
#
# Authentication (optional — bot works without any of these):
# - Default: github.token is used. Bot posts as github-actions[bot]. No CI on bot PRs.
# - GitHub App: Set RDB_APP_ID (variable) + RDB_APP_PRIVATE_KEY (secret) for a custom
#   bot identity and CI triggering on bot PRs.
# - PAT: Set RDB_PAT_TOKEN (secret) for CI triggering. Bot posts as the PAT owner.
#
# Prerequisites:
# - At least one LLM API key secret: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY
# - Actions permissions: read/write + allow PR creation
#
# ============================================================

"""


def build_base_job(security_roles, trigger_prefix):
    """Build the base job dict with security gate for a specific trigger prefix."""
    return {
        "runs-on": "ubuntu-latest",
        "if": (
            f"(github.event.issue || github.event.pull_request) && "
            f"startsWith(github.event.comment.body, '{trigger_prefix}') && "
            f"contains(fromJson('{security_roles}'), "
            f"github.event.comment.author_association)"
        ),
    }


def apply_block_scalars(steps):
    """Convert multi-line run: values to block scalars for readability."""
    for step in steps:
        if "run" in step and "\n" in step["run"]:
            step["run"] = BlockScalarStr(step["run"])


def generate_output_yaml(compiled, security_roles):
    """Generate the final YAML string with SECURITY_GATE comments."""
    yaml_str = yaml.dump(compiled, default_flow_style=False, sort_keys=False, width=1000)
    yaml_str = yaml_str.replace("'on':", "on:")

    # Add SECURITY_GATE marker before the if condition
    yaml_str = yaml_str.replace(
        "    if: (github.event.issue",
        "    # --- SECURITY_GATE: change who can trigger the agent ---\n"
        "    # Current: " + security_roles + "\n"
        "    # To restrict to owner only: " + '["OWNER"]' + "\n"
        "    # To allow contributors: " + '["OWNER","COLLABORATOR","MEMBER","CONTRIBUTOR"]' + "\n"
        "    if: (github.event.issue"
    )

    return yaml_str


def compile_resolve(shim, workflow, config_yaml, output_path):
    """Compile the resolve mode workflow (agent-resolve.yml)."""
    security_roles = extract_security_gate(shim)
    resolve_steps = workflow["jobs"]["resolve"]["steps"]

    steps = []

    # Generate app token (optional — only runs if RDB_APP_ID is set)
    steps.append({
        "name": "Generate app token",
        "if": "vars.RDB_APP_ID != ''",
        "uses": "actions/create-github-app-token@v1",
        "id": "app-token",
        "with": {
            "app-id": "${{ vars.RDB_APP_ID }}",
            "private-key": "${{ secrets.RDB_APP_PRIVATE_KEY }}",
        },
    })

    # Checkout
    steps.append({
        "name": "Checkout repository",
        "uses": "actions/checkout@v4",
        "with": {"token": "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"},
    })

    # Set up Python
    steps.append(find_step(resolve_steps, "Set up Python").copy())

    # Parse config (inline, resolve mode)
    steps.append({
        "name": "Parse config and model alias",
        "id": "parse",
        "env": {"COMMENT": "${{ github.event.comment.body }}"},
        "run": inline_config_parsing(config_yaml, "resolve"),
    })

    # Determine API key
    steps.append(find_step(resolve_steps, "Determine API key").copy())

    # React to comment (from parse job — the shared setup)
    parse_steps = workflow["jobs"]["parse"]["steps"]
    react_step = find_step(parse_steps, "React to comment").copy()
    react_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(react_step)

    # Assign commenter to issue (from parse job)
    assign_step = find_step(parse_steps, "Assign commenter to issue").copy()
    assign_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(assign_step)

    # Install OpenHands
    steps.append(find_step(resolve_steps, "Install OpenHands").copy())

    # Inject security guardrails
    steps.append(find_step(resolve_steps, "Inject security guardrails").copy())

    # Resolve issue (strip internal canary var, update token)
    resolve_step = find_step(resolve_steps, "Resolve issue").copy()
    resolve_step["env"] = {k: v for k, v in resolve_step["env"].items()
                           if k != "SANDBOX_ENV_E2E_TEST_TOKEN"}
    resolve_step["env"]["GITHUB_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(resolve_step)

    # Create pull request (update token)
    pr_step = find_step(resolve_steps, "Create pull request").copy()
    pr_step["env"]["GITHUB_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(pr_step)

    # Amend commit with model info
    amend_step = find_step(resolve_steps, "Amend commit with model info").copy()
    steps.append(amend_step)

    # Upload artifact
    steps.append(find_step(resolve_steps, "Upload output artifact").copy())

    # Calculate and post cost
    cost_step = find_step(resolve_steps, "Calculate and post cost").copy()
    cost_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(cost_step)

    # Fix needs.parse.outputs -> steps.parse.outputs (compiled is single-job)
    _rewrite_needs_refs(steps)

    apply_block_scalars(steps)

    job = build_base_job(security_roles, "/agent-resolve")
    job["steps"] = steps

    compiled = {
        "name": "Remote Dev Bot — Resolve (Compiled)",
        "on": shim["on"],
        "permissions": shim["permissions"],
        "jobs": {"resolve": job},
    }

    header = make_header("resolve")
    yaml_str = generate_output_yaml(compiled, security_roles)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(header + yaml_str)

    return output_path


def compile_design(shim, workflow, config_yaml, output_path):
    """Compile the design mode workflow (agent-design.yml)."""
    security_roles = extract_security_gate(shim)
    design_steps = workflow["jobs"]["design"]["steps"]

    # Build the prompt_prefix as a Python string for inlining
    modes_config = config_yaml.get("modes", {})
    design_config = modes_config.get("design", {})
    prompt_prefix = design_config.get("prompt_prefix", "")

    steps = []

    # Generate app token (optional — only runs if RDB_APP_ID is set)
    steps.append({
        "name": "Generate app token",
        "if": "vars.RDB_APP_ID != ''",
        "uses": "actions/create-github-app-token@v1",
        "id": "app-token",
        "with": {
            "app-id": "${{ vars.RDB_APP_ID }}",
            "private-key": "${{ secrets.RDB_APP_PRIVATE_KEY }}",
        },
    })

    # Checkout
    steps.append({
        "name": "Checkout repository",
        "uses": "actions/checkout@v4",
        "with": {"token": "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"},
    })

    # Set up Python
    steps.append(find_step(design_steps, "Set up Python").copy())

    # Parse config (inline, design mode)
    steps.append({
        "name": "Parse config and model alias",
        "id": "parse",
        "env": {"COMMENT": "${{ github.event.comment.body }}"},
        "run": inline_config_parsing(config_yaml, "design"),
    })

    # Determine API key
    steps.append(find_step(design_steps, "Determine API key").copy())

    # React to comment — design mode doesn't have its own, use from parse job
    parse_steps = workflow["jobs"]["parse"]["steps"]
    react_step = find_step(parse_steps, "React to comment").copy()
    react_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(react_step)

    # Assign commenter to issue (from parse job)
    assign_step = find_step(parse_steps, "Assign commenter to issue").copy()
    assign_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(assign_step)

    # Install dependencies (PyYAML + litellm)
    steps.append(find_step(design_steps, "Install dependencies").copy())

    # Gather issue context
    gather_step = find_step(design_steps, "Gather issue context").copy()
    gather_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(gather_step)

    # Call LLM for design analysis — rewrite to inline prompt_prefix and context_files
    llm_step = find_step(design_steps, "Call LLM for design analysis").copy()
    # The step reads prompt_prefix from config files on disk. In compiled mode,
    # we inline it. Replace the config-loading Python code.
    if prompt_prefix:
        escaped_prefix = prompt_prefix.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    else:
        escaped_prefix = ""
    llm_run = llm_step.get("run", "")
    # Replace the config-loading block with a simple variable assignment
    # Note: re.sub interprets backslash sequences in the replacement string,
    # so we need to escape backslashes again to preserve \n as literal \n
    replacement = f'prompt_prefix = "{escaped_prefix}"\n'
    replacement_escaped = replacement.replace('\\', '\\\\')
    llm_run = re.sub(
        r'# Load prompt_prefix from config.*?break\n',
        replacement_escaped,
        llm_run,
        flags=re.DOTALL,
    )
    # Remove the remote-dev-bot checkout reference
    llm_run = llm_run.replace(
        'config_path = ".remote-dev-bot/lib/../remote-dev-bot.yaml"\n', ''
    )
    # Inline the context_files list (compiled workflows can't read from config at runtime)
    context_files = design_config.get("context_files", [])
    context_files_repr = repr(context_files)
    llm_run = llm_run.replace(
        'context_files = json.loads(os.environ.get("CONTEXT_FILES", "[]") or "[]")',
        f'context_files = {context_files_repr}',
    )
    llm_step["run"] = llm_run
    # Remove CONTEXT_FILES env var since the list is inlined
    if "env" in llm_step and "CONTEXT_FILES" in llm_step["env"]:
        del llm_step["env"]["CONTEXT_FILES"]
    steps.append(llm_step)

    # Post comment
    post_step = find_step(design_steps, "Post comment").copy()
    post_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(post_step)

    # Post cost comment
    cost_step = find_step(design_steps, "Post cost comment").copy()
    cost_step["env"]["GH_TOKEN"] = "${{ steps.app-token.outputs.token || secrets.RDB_PAT_TOKEN || github.token }}"
    steps.append(cost_step)

    # Fix needs.parse.outputs -> steps.parse.outputs
    _rewrite_needs_refs(steps)

    apply_block_scalars(steps)

    job = build_base_job(security_roles, "/agent-design")
    job["steps"] = steps

    compiled = {
        "name": "Remote Dev Bot — Design (Compiled)",
        "on": shim["on"],
        "permissions": shim["permissions"],
        "jobs": {"design": job},
    }

    header = make_header("design")
    yaml_str = generate_output_yaml(compiled, security_roles)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(header + yaml_str)

    return output_path


def _rewrite_needs_refs(steps):
    """Rewrite needs.parse.outputs.X -> steps.parse.outputs.X in step values.

    The reusable workflow uses multi-job with needs; compiled is single-job
    so outputs come from prior steps instead.
    """
    def rewrite(obj):
        if isinstance(obj, str):
            return obj.replace("needs.parse.outputs.", "steps.parse.outputs.")
        elif isinstance(obj, dict):
            return {k: rewrite(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [rewrite(v) for v in obj]
        return obj

    for i, step in enumerate(steps):
        steps[i] = rewrite(step)


def main():
    """Main entry point."""
    workspace = Path(__file__).parent.parent
    shim_path = workspace / ".github" / "workflows" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    # Output directory
    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
    else:
        output_dir = str(workspace / "dist")

    os.makedirs(output_dir, exist_ok=True)

    # Load source files
    shim = load_yaml(str(shim_path))
    workflow = load_yaml(str(workflow_path))
    config_yaml = load_yaml(str(config_path))

    # Compile both modes
    resolve_path = compile_resolve(
        shim, workflow, config_yaml,
        os.path.join(output_dir, "agent-resolve.yml")
    )
    print(f"Compiled resolve workflow: {resolve_path}")

    design_path = compile_design(
        shim, workflow, config_yaml,
        os.path.join(output_dir, "agent-design.yml")
    )
    print(f"Compiled design workflow: {design_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
