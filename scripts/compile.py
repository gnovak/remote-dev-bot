#!/usr/bin/env python3
"""Compile a single-file workflow from the reusable workflow + shim setup.

This script reads the reusable workflow (resolve.yml), the shim (agent.yml),
config parsing logic (lib/config.py), and model aliases (remote-dev-bot.yaml),
then produces a self-contained workflow file that users can drop into their repo.

Output is a single agent.yml that:
- Triggers on issue_comment and pull_request_review_comment
- Has the same author_association security gate as the shim
- Inlines all config (model aliases, OpenHands settings) directly
- Inlines config parsing logic (no cross-repo checkout needed)
- Uses github.token as default (PAT_TOKEN optional)
- Injects the security microagent
- Runs OpenHands resolver and creates PRs

Usage:
    python scripts/compile.py [output_path]

Default output path is dist/agent.yml
"""

import os
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
        content = f.read()
        # Handle 'on:' being parsed as boolean True by PyYAML
        # We need to load it in a way that preserves the 'on' key
        data = yaml.safe_load(content)
        # Fix the 'on' key if it was parsed as True
        if True in data and 'on' not in data:
            data['on'] = data.pop(True)
        return data


def extract_security_gate(shim):
    """Extract the author_association list from the shim's if condition."""
    # The shim has: contains(fromJson('["OWNER","COLLABORATOR","MEMBER"]'), ...)
    # We extract this list
    if_condition = shim.get("jobs", {}).get("resolve", {}).get("if", "")
    # Parse out the JSON array from the condition
    import re
    match = re.search(r'fromJson\(\'(\[.*?\])\'\)', if_condition)
    if match:
        return match.group(1)
    # Default fallback
    return '["OWNER","COLLABORATOR","MEMBER"]'


def inline_config_parsing(config_yaml):
    """Generate shell script that includes Python code for parsing config inline.

    Returns shell script that extracts alias from comment and resolves model.
    """
    models = config_yaml.get("models", {})
    default_model = config_yaml.get("default_model", "claude-medium")
    oh = config_yaml.get("openhands", {})
    max_iterations = oh.get("max_iterations", 50)
    oh_version = oh.get("version", "1.3.0")
    pr_type = oh.get("pr_type", "ready")

    # Build the models dictionary as Python code
    models_dict_lines = []
    for alias, model_info in models.items():
        model_id = model_info["id"]
        models_dict_lines.append(f'    "{alias}": "{model_id}",')
    models_dict = "\n".join(models_dict_lines)

    # Use a shell script that invokes Python
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

# Parse alias from comment
comment = os.environ.get("COMMENT", "")
# Extract alias: "/agent-claude-large do X" -> "claude-large", "/agent" -> ""
match = re.match(r'^/agent-?([a-z0-9-]*)', comment)
alias = match.group(1) if match else ""

if not alias:
    alias = DEFAULT_MODEL

if alias not in MODELS:
    print(f"ERROR: Unknown model alias: {{alias}}. Available: {{list(MODELS.keys())}}", file=sys.stderr)
    sys.exit(1)

model = MODELS[alias]

# Write outputs
output_file = os.environ.get("GITHUB_OUTPUT")
if output_file:
    with open(output_file, "a") as f:
        f.write(f"model={{model}}\\n")
        f.write(f"alias={{alias}}\\n")
        f.write(f"max_iterations={{MAX_ITERATIONS}}\\n")
        f.write(f"oh_version={{OH_VERSION}}\\n")
        f.write(f"pr_type={{PR_TYPE}}\\n")

# Log for visibility
print(f"Model alias: {{alias}}")
print(f"Model ID: {{model}}")
print(f"PR type: {{PR_TYPE}}")
PYTHON_EOF
'''
    return code


def compile_workflow(shim_path, workflow_path, config_path, output_path):
    """Compile the single-file workflow."""
    # Load source files
    shim = load_yaml(shim_path)
    workflow = load_yaml(workflow_path)
    config_yaml = load_yaml(config_path)

    # Extract security gate from shim
    security_roles = extract_security_gate(shim)

    # Build the compiled workflow
    compiled = {
        "name": "Remote Dev Bot (Compiled)",
    }

    # Add on triggers from shim
    compiled["on"] = shim["on"]

    # Add permissions from shim
    compiled["permissions"] = shim["permissions"]

    # Build the job
    job = {
        "runs-on": "ubuntu-latest",
    }

    # Add security gate as if condition
    # --- SECURITY_GATE: change who can trigger the agent ---
    job["if"] = (
        f"(github.event.issue || github.event.pull_request) && "
        f"startsWith(github.event.comment.body, '/agent') && "
        f"contains(fromJson('{security_roles}'), github.event.comment.author_association)"
    )

    # Get steps from reusable workflow
    resolve_job = workflow["jobs"]["resolve"]
    steps = resolve_job["steps"]

    # Build new steps list (filtering and modifying)
    new_steps = []

    # Step 1: Checkout (keep, but update comment)
    checkout_step = steps[0].copy()
    checkout_step["name"] = "Checkout repository"
    # Add PAT_TOKEN comment
    new_steps.append({
        "name": "Checkout repository",
        "uses": "actions/checkout@v4",
        "with": {
            "token": "${{ secrets.PAT_TOKEN || github.token }}"
        }
    })

    # Skip step 2: "Checkout remote-dev-bot config" - we're inlining it

    # Step 3: Set up Python (keep)
    new_steps.append(steps[2])

    # Skip step 4: "Install PyYAML" - compiled version doesn't need it

    # Step 5: Parse config and model alias (replace with inline version)
    config_parse_code = inline_config_parsing(config_yaml)
    new_steps.append({
        "name": "Parse config and model alias",
        "id": "parse",
        "env": {
            "COMMENT": "${{ github.event.comment.body }}"
        },
        "run": config_parse_code
    })

    # Step 6: Determine API key (keep)
    new_steps.append(steps[5])

    # Step 7: React to comment (keep, but update token)
    react_step = steps[6].copy()
    react_step["env"]["GH_TOKEN"] = "${{ secrets.PAT_TOKEN || github.token }}"
    new_steps.append(react_step)

    # Step 8: Install OpenHands (keep)
    new_steps.append(steps[7])

    # Skip step 9: "Clean up config checkout" - not needed

    # Step 10: Inject security guardrails (keep)
    new_steps.append(steps[9])

    # Step 11: Resolve issue (keep, update token, remove internal test secrets)
    resolve_step = steps[10].copy()
    resolve_step["env"] = {k: v for k, v in resolve_step["env"].items()
                           if k != "E2E_TEST_SECRET"}
    resolve_step["env"]["GITHUB_TOKEN"] = "${{ secrets.PAT_TOKEN || github.token }}"
    new_steps.append(resolve_step)

    # Step 12: Create pull request (keep, update token)
    pr_step = steps[11].copy()
    pr_step["env"]["GITHUB_TOKEN"] = "${{ secrets.PAT_TOKEN || github.token }}"
    new_steps.append(pr_step)

    # Step 13: Upload artifact (keep)
    new_steps.append(steps[12])

    # Convert multi-line run: values to block scalars for readability
    for step in new_steps:
        if "run" in step and "\n" in step["run"]:
            step["run"] = BlockScalarStr(step["run"])

    job["steps"] = new_steps

    compiled["jobs"] = {
        "resolve": job
    }

    # Generate the YAML output
    output = generate_output_yaml(compiled, security_roles, config_yaml)

    # Write to file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(output)

    return output_path


def generate_output_yaml(compiled, security_roles, config_yaml):
    """Generate the final YAML with configuration comments."""

    # Build configuration header
    header = """# ============================================================
# CONFIGURATION - Single-File Remote Dev Bot
# ============================================================
#
# This is a compiled, self-contained workflow. To customize:
#
# - MODEL_CONFIG: Search for this to change the default model or add/modify aliases
# - PR_STYLE: Search for this to switch between draft and ready PRs
# - MAX_ITERATIONS: Search for this to adjust how many steps the agent takes
# - SECURITY_GATE: Search for this to change who can trigger the agent
# - PAT_TOKEN: Optional secret. Without it, github.token is used.
#
# About PAT_TOKEN:
# - PAT_TOKEN is optional. If not set, github.token is used (works for most cases).
# - Add a PAT (scoped to this repo) if you want bot-created PRs to auto-trigger CI.
# - Without a PAT, bot PRs won't trigger CI workflows (GitHub security feature).
#
# Prerequisites:
# - At least one LLM API key secret: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY
# - Actions permissions: read/write + allow PR creation
#
# ============================================================

"""

    # Convert to YAML
    yaml_str = yaml.dump(compiled, default_flow_style=False, sort_keys=False, width=1000)

    # Fix the quoted 'on' key to be unquoted
    yaml_str = yaml_str.replace("'on':", "on:")

    # Insert comment markers for searchability
    # We need to be careful here - the MODEL_CONFIG is in the Python code
    # So we'll add comments around it

    # Add SECURITY_GATE marker before the if condition
    yaml_str = yaml_str.replace(
        "    if: (github.event.issue",
        "    # --- SECURITY_GATE: change who can trigger the agent ---\n"
        "    # Current: " + security_roles + "\n"
        "    # To restrict to owner only: " + '["OWNER"]' + "\n"
        "    # To allow contributors: " + '["OWNER","COLLABORATOR","MEMBER","CONTRIBUTOR"]' + "\n"
        "    if: (github.event.issue"
    )

    return header + yaml_str


def main():
    """Main entry point."""
    # Determine paths
    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    # Output path
    if len(sys.argv) > 1:
        output_path = sys.argv[1]
    else:
        output_path = str(workspace / "dist" / "agent.yml")

    # Compile
    result_path = compile_workflow(
        str(shim_path),
        str(workflow_path),
        str(config_path),
        output_path
    )

    print(f"Compiled workflow written to: {result_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
