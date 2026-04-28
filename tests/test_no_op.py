"""Tests for the no_op() tool behavior in lib/resolve.py.

resolve.py reads ISSUE_NUMBER from os.environ at import time, so we must
patch the environment before the module is imported. We do this once at
module level using importlib so each test shares the already-imported module.
"""

import importlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import resolve.py with the required env vars set so module-level code succeeds.
_ENV_PATCH = patch.dict(
    os.environ,
    {
        "ISSUE_NUMBER": "456",
        "GITHUB_REPOSITORY": "owner/repo",
        "LLM_MODEL": "anthropic/claude-3-5-sonnet-20241022",
        "BASH_OUTPUT_LIMIT": "0",
        "CONTEXT_KEEP_TOOL_RESULTS": "0",
        "MAX_CONTEXT_TOKENS": "0",
        "COMPACTION_COVERAGE": "0.5",
        "COMPACTION_FACTOR": "0.5",
    },
)
_ENV_PATCH.start()
import lib.resolve as resolve_mod  # noqa: E402  (after env patch)
_ENV_PATCH.stop()


def _call_write_status_to_temp(tmp_path, *args, **kwargs):
    """Call write_status but redirect /tmp/resolve_status.json to tmp_path."""
    real_status = tmp_path / "resolve_status.json"
    _real_open = io.open  # capture un-patched open

    def _redirect_open(path, mode="r", **kw):
        if path == "/tmp/resolve_status.json":
            return _real_open(str(real_status), mode, **kw)
        return _real_open(path, mode, **kw)

    with patch("builtins.open", side_effect=_redirect_open):
        resolve_mod.write_status(*args, **kwargs)

    return real_status


# ---------------------------------------------------------------------------
# write_status with no_op flag
# ---------------------------------------------------------------------------

def test_write_status_no_op_sets_flag(tmp_path):
    """write_status with no_op=True writes no_op: true to the status file."""
    status_path = _call_write_status_to_temp(tmp_path, True, "no change needed", no_op=True)
    data = json.loads(status_path.read_text())
    assert data["success"] is True
    assert data["no_op"] is True
    assert data["explanation"] == "no change needed"


def test_write_status_no_op_false_omits_flag(tmp_path):
    """write_status without no_op does not include no_op key in output."""
    status_path = _call_write_status_to_temp(tmp_path, True, "task complete")
    data = json.loads(status_path.read_text())
    assert "no_op" not in data


def test_write_status_no_op_default_is_false(tmp_path):
    """write_status no_op parameter defaults to False (key absent from JSON)."""
    status_path = _call_write_status_to_temp(tmp_path, False, "failed")
    data = json.loads(status_path.read_text())
    assert "no_op" not in data


def test_write_status_no_op_json_structure(tmp_path):
    """write_status with no_op=True produces the expected exact JSON structure."""
    status_path = _call_write_status_to_temp(
        tmp_path, True, "The code is already correct", no_op=True
    )
    data = json.loads(status_path.read_text())
    assert data == {
        "success": True,
        "explanation": "The code is already correct",
        "no_op": True,
    }


# ---------------------------------------------------------------------------
# no_op tool in TOOLS list
# ---------------------------------------------------------------------------

def test_no_op_tool_in_tools_list():
    """The TOOLS list must include a no_op tool definition."""
    tool_names = [t["function"]["name"] for t in resolve_mod.TOOLS]
    assert "no_op" in tool_names


def test_no_op_tool_has_reason_parameter():
    """The no_op tool must accept a 'reason' parameter that is required."""
    no_op_tool = next(
        t for t in resolve_mod.TOOLS if t["function"]["name"] == "no_op"
    )
    params = no_op_tool["function"]["parameters"]
    assert "reason" in params["properties"]
    assert "reason" in params["required"]


def test_finish_tool_still_present():
    """The finish tool must still be present alongside no_op."""
    tool_names = [t["function"]["name"] for t in resolve_mod.TOOLS]
    assert "finish" in tool_names


# ---------------------------------------------------------------------------
# System prompt mentions no_op
# ---------------------------------------------------------------------------

def test_system_prompt_mentions_no_op():
    """The GIT_INSTRUCTIONS constant must mention no_op."""
    assert "no_op" in resolve_mod.GIT_INSTRUCTIONS


def test_system_prompt_no_op_explains_when_to_use():
    """GIT_INSTRUCTIONS must explain when to use no_op vs finish."""
    assert "no change is needed" in resolve_mod.GIT_INSTRUCTIONS or \
           "no change needed" in resolve_mod.GIT_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Workflow YAML — no_op detection in Post result comment
# ---------------------------------------------------------------------------

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "remote-dev-bot.yml"


@pytest.fixture(scope="module")
def workflow_content():
    return WORKFLOW_PATH.read_text()


def test_workflow_detects_no_op_flag(workflow_content):
    """The workflow YAML must extract NO_OP from resolve_status.json."""
    import yaml
    data = yaml.safe_load(workflow_content)

    # Collect all 'run' step values from YAML jobs
    run_scripts = []
    def collect_runs(obj):
        if isinstance(obj, dict):
            if "run" in obj and isinstance(obj["run"], str):
                run_scripts.append(obj["run"])
            for v in obj.values():
                collect_runs(v)
        elif isinstance(obj, list):
            for item in obj:
                collect_runs(item)

    collect_runs(data.get("jobs", {}))

    # Verify no_op is referenced via the actual Python extraction pattern
    # (not just in comments), proving it's functionally checked in the workflow
    extraction_pattern = "d.get('no_op')"
    matching_scripts = [s for s in run_scripts if extraction_pattern in s]
    assert len(matching_scripts) >= 2, (
        f"Expected at least 2 workflow 'run' steps that extract no_op via "
        f"d.get('no_op'), got {len(matching_scripts)}"
    )


def test_workflow_no_op_comment_text(workflow_content):
    """The workflow must post a 'No change needed' comment for no_op runs."""
    assert "No change needed" in workflow_content


def test_workflow_no_op_skips_council_review(workflow_content):
    """The workflow council review step must silently skip when no_op=true."""
    # Verify the no_op check appears before the council review error message
    no_op_idx = workflow_content.index("Agent signaled no_op")
    council_error_idx = workflow_content.index("did not produce a pull request")
    assert no_op_idx < council_error_idx, (
        "no_op silent-skip should appear before the council error message"
    )


def test_workflow_no_op_exits_zero(workflow_content):
    """The no_op branch in Post result comment must exit 0 (success)."""
    # Find the no_op block and verify it has 'exit 0'.
    # The block spans ~1200 chars (includes the gh comment call before exit 0).
    noop_section_start = workflow_content.index('if [[ "$NO_OP" == "true" ]]')
    block = workflow_content[noop_section_start:noop_section_start + 1400]
    assert "exit 0" in block, "no_op block must exit with code 0"
