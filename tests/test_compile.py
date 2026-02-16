"""Tests for scripts/compile.py — two-file workflow compiler."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

# Repo root
WORKSPACE = Path(__file__).parent.parent


@pytest.fixture
def compiled_dir(tmp_path):
    """Compile both workflows into a temp directory."""
    import sys
    sys.path.insert(0, str(WORKSPACE))
    from scripts.compile import compile_resolve, compile_design, load_yaml

    shim = load_yaml(str(WORKSPACE / ".github" / "workflows" / "agent.yml"))
    workflow = load_yaml(str(WORKSPACE / ".github" / "workflows" / "resolve.yml"))
    config = load_yaml(str(WORKSPACE / "remote-dev-bot.yaml"))

    compile_resolve(shim, workflow, config, str(tmp_path / "agent-resolve.yml"))
    compile_design(shim, workflow, config, str(tmp_path / "agent-design.yml"))

    return tmp_path


def _load_compiled(path):
    """Load a compiled YAML file, fixing the 'on' key."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if True in data and 'on' not in data:
        data['on'] = data.pop(True)
    return data


def _read_text(path):
    with open(path) as f:
        return f.read()


# --- Both files: valid YAML ---


def test_resolve_produces_valid_yaml(compiled_dir):
    data = _load_compiled(compiled_dir / "agent-resolve.yml")
    assert data is not None
    assert "name" in data
    assert "jobs" in data


def test_design_produces_valid_yaml(compiled_dir):
    data = _load_compiled(compiled_dir / "agent-design.yml")
    assert data is not None
    assert "name" in data
    assert "jobs" in data


# --- Correct triggers ---


def test_resolve_trigger(compiled_dir):
    content = _read_text(compiled_dir / "agent-resolve.yml")
    assert "startsWith(github.event.comment.body, '/agent-resolve')" in content


def test_design_trigger(compiled_dir):
    content = _read_text(compiled_dir / "agent-design.yml")
    assert "startsWith(github.event.comment.body, '/agent-design')" in content


def test_both_have_correct_event_triggers(compiled_dir):
    for fname in ["agent-resolve.yml", "agent-design.yml"]:
        data = _load_compiled(compiled_dir / fname)
        triggers = data['on']
        assert 'issue_comment' in triggers
        assert 'pull_request_review_comment' in triggers
        assert triggers['issue_comment']['types'] == ['created']
        assert triggers['pull_request_review_comment']['types'] == ['created']


# --- Permissions ---


def test_both_have_correct_permissions(compiled_dir):
    for fname in ["agent-resolve.yml", "agent-design.yml"]:
        data = _load_compiled(compiled_dir / fname)
        perms = data['permissions']
        assert perms['contents'] == 'write'
        assert perms['issues'] == 'write'
        assert perms['pull-requests'] == 'write'


# --- Resolve-specific ---


def test_resolve_has_security_microagent(compiled_dir):
    content = _read_text(compiled_dir / "agent-resolve.yml")
    assert "Security Rules (injected by remote-dev-bot)" in content
    assert "NEVER output, print, log, echo, or write environment variable values" in content
    assert "remote-dev-bot-security.md" in content


def test_resolve_has_openhands_steps(compiled_dir):
    content = _read_text(compiled_dir / "agent-resolve.yml")
    assert "Install OpenHands" in content
    assert "Resolve issue" in content
    assert "Create pull request" in content
    assert "openhands.resolver" in content


# --- Design-specific ---


def test_design_has_no_openhands_steps(compiled_dir):
    """Design mode should not install or run OpenHands."""
    content = _read_text(compiled_dir / "agent-design.yml")
    assert "Install OpenHands" not in content
    assert "openhands.resolver" not in content
    assert "Resolve issue" not in content
    assert "Create pull request" not in content


def test_design_has_litellm(compiled_dir):
    content = _read_text(compiled_dir / "agent-design.yml")
    assert "litellm" in content


def test_design_has_llm_and_comment_steps(compiled_dir):
    content = _read_text(compiled_dir / "agent-design.yml")
    assert "Call LLM for design analysis" in content
    assert "Post comment" in content
    assert "Gather issue context" in content


def test_design_has_inlined_context_files(compiled_dir):
    """Compiled design workflow should have context file paths inlined."""
    content = _read_text(compiled_dir / "agent-design.yml")
    assert "README.md" in content
    assert "AGENTS.md" in content
    assert ".openhands/microagents/repo.md" in content
    # Should NOT use the env var approach (that's for the reusable workflow)
    assert 'CONTEXT_FILES' not in content


# --- Cost transparency ---


def test_resolve_has_cost_step(compiled_dir):
    """Resolve mode should post a cost summary comment."""
    content = _read_text(compiled_dir / "agent-resolve.yml")
    assert "Calculate and post cost" in content
    assert "Cost Summary" in content
    assert "Input tokens" in content
    assert "Output tokens" in content


def test_design_has_cost_step(compiled_dir):
    """Design mode should post a cost summary comment."""
    content = _read_text(compiled_dir / "agent-design.yml")
    assert "Post cost comment" in content
    assert "Cost Summary" in content
    assert "Input tokens" in content
    assert "Output tokens" in content


# --- Both: model aliases ---


def test_both_inline_model_aliases(compiled_dir):
    for fname in ["agent-resolve.yml", "agent-design.yml"]:
        content = _read_text(compiled_dir / fname)
        assert "claude-small" in content
        assert "claude-large" in content
        assert "openai-small" in content
        assert "openai-large" in content
        assert "gemini-small" in content
        assert "gemini-large" in content
        assert "anthropic/claude-sonnet-4-5" in content
        assert "openai/gpt-5.1-codex-mini" in content
        assert "gemini/gemini-2.5-flash" in content


# --- Both: github.token fallback ---


def test_both_use_github_token_fallback(compiled_dir):
    for fname in ["agent-resolve.yml", "agent-design.yml"]:
        content = _read_text(compiled_dir / fname)
        assert "secrets.PAT_TOKEN || github.token" in content


# --- Both: no cross-repo checkout ---


def test_no_cross_repo_checkout(compiled_dir):
    for fname in ["agent-resolve.yml", "agent-design.yml"]:
        content = _read_text(compiled_dir / fname)
        assert "gnovak/remote-dev-bot" not in content, \
            f"{fname} should not checkout remote-dev-bot repo"
        assert ".remote-dev-bot" not in content, \
            f"{fname} should not reference .remote-dev-bot directory"


# --- Both: configuration markers ---


def test_both_have_required_markers(compiled_dir):
    for fname in ["agent-resolve.yml", "agent-design.yml"]:
        content = _read_text(compiled_dir / fname)
        assert "MODEL_CONFIG" in content, f"{fname} missing MODEL_CONFIG marker"
        assert "SECURITY_GATE" in content, f"{fname} missing SECURITY_GATE marker"
        assert "MAX_ITERATIONS" in content, f"{fname} missing MAX_ITERATIONS marker"
        assert "PR_STYLE" in content, f"{fname} missing PR_STYLE marker"
        assert "PAT_TOKEN" in content, f"{fname} missing PAT_TOKEN documentation"


# --- Step count tripwire ---
# These tests fail when steps are added to or removed from resolve.yml,
# forcing you to check whether compile.py needs a corresponding update.


EXPECTED_RESOLVE_STEPS = [
    "Checkout repository",
    "Set up Python",
    "Parse config and model alias",
    "Determine API key",
    "React to comment",
    "Assign commenter to issue",
    "Install OpenHands",
    "Inject security guardrails",
    "Resolve issue",
    "Create pull request",
    "Upload output artifact",
    "Calculate and post cost",
]

EXPECTED_DESIGN_STEPS = [
    "Checkout repository",
    "Set up Python",
    "Parse config and model alias",
    "Determine API key",
    "React to comment",
    "Assign commenter to issue",
    "Install dependencies",
    "Gather issue context",
    "Call LLM for design analysis",
    "Post comment",
    "Post cost comment",
]


def test_resolve_step_count(compiled_dir):
    """Tripwire: fails if steps are added/removed from resolve.yml without updating compile.py."""
    data = _load_compiled(compiled_dir / "agent-resolve.yml")
    job = list(data["jobs"].values())[0]
    actual = [s.get("name", "(unnamed)") for s in job["steps"]]
    assert actual == EXPECTED_RESOLVE_STEPS, (
        f"Compiled resolve steps changed. If you added/removed a step in resolve.yml, "
        f"update compile.py and this list.\n  Expected: {EXPECTED_RESOLVE_STEPS}\n  Actual:   {actual}"
    )


def test_design_step_count(compiled_dir):
    """Tripwire: fails if steps are added/removed from resolve.yml without updating compile.py."""
    data = _load_compiled(compiled_dir / "agent-design.yml")
    job = list(data["jobs"].values())[0]
    actual = [s.get("name", "(unnamed)") for s in job["steps"]]
    assert actual == EXPECTED_DESIGN_STEPS, (
        f"Compiled design steps changed. If you added/removed a step in resolve.yml, "
        f"update compile.py and this list.\n  Expected: {EXPECTED_DESIGN_STEPS}\n  Actual:   {actual}"
    )


# --- Error handling ---


def test_compile_missing_source_file():
    import sys
    sys.path.insert(0, str(WORKSPACE))
    from scripts.compile import load_yaml

    with pytest.raises(SystemExit) as exc_info:
        load_yaml("nonexistent.yml")
    assert exc_info.value.code != 0
