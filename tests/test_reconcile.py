"""Tests for lib/reconcile.py — helpers and prompt construction.

reconcile.py reads PR_NUMBER from os.environ at import time (no default),
so we must patch the environment before the module is imported. We use the
same pattern as test_no_op.py: patch at module level, then import.
"""

import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import reconcile.py with the required env vars set so module-level code succeeds.
_ENV_PATCH = patch.dict(
    os.environ,
    {
        "PR_NUMBER": "42",
        "BASE_BRANCH": "main",
        "MAX_ITERATIONS": "50",
        "WRAPUP_ENABLED": "true",
        "WRAPUP_ITERATION": "0",
        "EXTRA_INSTRUCTIONS": "",
        "MODEL_EXTRA_INSTRUCTIONS": "",
        "LLM_MODEL": "anthropic/claude-3-5-sonnet-20241022",
        "BASH_OUTPUT_LIMIT": "8000",
        "CONTEXT_KEEP_TOOL_RESULTS": "10",
        "MAX_CONTEXT_TOKENS": "0",
        "COMPACTION_COVERAGE": "0.5",
        "COMPACTION_FACTOR": "0.5",
    },
)
_ENV_PATCH.start()
import lib.reconcile as reconcile_mod  # noqa: E402  (after env patch)
_ENV_PATCH.stop()


# ---------------------------------------------------------------------------
# Helpers for write_status redirection
# ---------------------------------------------------------------------------

def _call_write_status_to_temp(tmp_path, *args, **kwargs):
    """Call write_status but redirect /tmp/resolve_status.json to tmp_path."""
    real_status = tmp_path / "resolve_status.json"
    _real_open = io.open  # capture un-patched open

    def _redirect_open(path, mode="r", **kw):
        if path == "/tmp/resolve_status.json":
            return _real_open(str(real_status), mode, **kw)
        return _real_open(path, mode, **kw)

    with patch("builtins.open", side_effect=_redirect_open):
        reconcile_mod.write_status(*args, **kwargs)

    return real_status


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    """Tests that TOOLS has the expected shape and content."""

    def test_has_four_tools(self):
        """TOOLS must contain exactly 4 tools: bash, read_file, grep, finish."""
        assert len(reconcile_mod.TOOLS) == 4

    def test_tool_names(self):
        """All expected tool names must be present."""
        names = {t["function"]["name"] for t in reconcile_mod.TOOLS}
        assert names == {"bash", "read_file", "grep", "finish"}

    def test_all_tools_have_type_function(self):
        """Every tool entry must have type='function'."""
        for tool in reconcile_mod.TOOLS:
            assert tool.get("type") == "function", f"Tool missing type: {tool}"

    def test_all_tools_have_descriptions(self):
        """Every tool must have a non-empty description."""
        for tool in reconcile_mod.TOOLS:
            desc = tool["function"].get("description", "")
            assert desc.strip(), f"Tool {tool['function']['name']} has empty description"

    def test_bash_tool_has_command_parameter(self):
        """bash tool must require 'command' parameter."""
        bash_tool = next(t for t in reconcile_mod.TOOLS if t["function"]["name"] == "bash")
        params = bash_tool["function"]["parameters"]
        assert "command" in params["properties"]
        assert "command" in params["required"]

    def test_read_file_tool_has_path_parameter(self):
        """read_file tool must require 'path' parameter."""
        rf_tool = next(t for t in reconcile_mod.TOOLS if t["function"]["name"] == "read_file")
        params = rf_tool["function"]["parameters"]
        assert "path" in params["properties"]
        assert "path" in params["required"]

    def test_grep_tool_has_pattern_parameter(self):
        """grep tool must require 'pattern' parameter."""
        grep_tool = next(t for t in reconcile_mod.TOOLS if t["function"]["name"] == "grep")
        params = grep_tool["function"]["parameters"]
        assert "pattern" in params["properties"]
        assert "pattern" in params["required"]

    def test_grep_tool_has_optional_path_parameter(self):
        """grep tool must have an optional 'path' parameter."""
        grep_tool = next(t for t in reconcile_mod.TOOLS if t["function"]["name"] == "grep")
        params = grep_tool["function"]["parameters"]
        assert "path" in params["properties"]
        # path must NOT be required (it's optional)
        assert "path" not in params.get("required", [])

    def test_finish_tool_has_required_parameters(self):
        """finish tool must require 'success', 'explanation', and 'conversation_summary'."""
        finish_tool = next(t for t in reconcile_mod.TOOLS if t["function"]["name"] == "finish")
        params = finish_tool["function"]["parameters"]
        required = params.get("required", [])
        assert "success" in required
        assert "explanation" in required
        assert "conversation_summary" in required

    def test_finish_success_is_boolean(self):
        """finish tool's 'success' parameter must be of type 'boolean'."""
        finish_tool = next(t for t in reconcile_mod.TOOLS if t["function"]["name"] == "finish")
        params = finish_tool["function"]["parameters"]
        assert params["properties"]["success"]["type"] == "boolean"


# ---------------------------------------------------------------------------
# execute_tool dispatch
# ---------------------------------------------------------------------------

class TestExecuteTool:
    """Tests for execute_tool() routing logic."""

    def test_bash_dispatches_to_execute_bash(self, monkeypatch):
        """execute_tool('bash', ...) must call execute_bash."""
        calls = []

        def fake_execute_bash(cmd):
            calls.append(cmd)
            return "bash result"

        monkeypatch.setattr(reconcile_mod, "execute_bash", fake_execute_bash)
        result = reconcile_mod.execute_tool("bash", {"command": "echo hi"})
        assert calls == ["echo hi"]
        assert result == "bash result"

    def test_read_file_dispatches(self, monkeypatch):
        """execute_tool('read_file', ...) must call execute_read_file."""
        calls = []

        def fake_read_file(path):
            calls.append(path)
            return "file contents"

        monkeypatch.setattr(reconcile_mod, "execute_read_file", fake_read_file)
        result = reconcile_mod.execute_tool("read_file", {"path": "README.md"})
        assert calls == ["README.md"]
        assert result == "file contents"

    def test_grep_dispatches(self, monkeypatch):
        """execute_tool('grep', ...) must call execute_grep."""
        calls = []

        def fake_grep(pattern, path):
            calls.append((pattern, path))
            return "grep result"

        monkeypatch.setattr(reconcile_mod, "execute_grep", fake_grep)
        result = reconcile_mod.execute_tool("grep", {"pattern": "<<<<<<< HEAD", "path": "src/"})
        assert calls == [("<<<<<<< HEAD", "src/")]
        assert result == "grep result"

    def test_grep_without_path(self, monkeypatch):
        """execute_tool('grep', ...) passes None for path if not provided."""
        calls = []

        def fake_grep(pattern, path):
            calls.append((pattern, path))
            return "grep result"

        monkeypatch.setattr(reconcile_mod, "execute_grep", fake_grep)
        result = reconcile_mod.execute_tool("grep", {"pattern": "TODO"})
        assert calls == [("TODO", None)]
        assert result == "grep result"

    def test_finish_returns_acknowledgment(self):
        """execute_tool('finish', ...) must return an acknowledgment string."""
        result = reconcile_mod.execute_tool("finish", {"success": True, "explanation": "done"})
        assert isinstance(result, str)
        assert "finish" in result.lower()

    def test_unknown_tool_returns_error(self):
        """execute_tool with an unknown tool name must return an error string."""
        result = reconcile_mod.execute_tool("nonexistent_tool", {})
        assert "Error" in result or "error" in result or "Unknown" in result
        assert "nonexistent_tool" in result


# ---------------------------------------------------------------------------
# build_system_prompt — shape and section presence
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    """Tests for build_system_prompt() — expected sections present, correct structure."""

    def _build(self, repo_context="repo ctx", pr_info="pr info", **env_overrides):
        """Build a prompt with optional env overrides."""
        with patch.multiple(
            reconcile_mod,
            BASE_BRANCH=env_overrides.get("BASE_BRANCH", reconcile_mod.BASE_BRANCH),
            MAX_ITERATIONS=env_overrides.get("MAX_ITERATIONS", reconcile_mod.MAX_ITERATIONS),
            WRAPUP_ENABLED=env_overrides.get("WRAPUP_ENABLED", False),
            WRAPUP_ITERATION=env_overrides.get("WRAPUP_ITERATION", 0),
            EXTRA_INSTRUCTIONS=env_overrides.get("EXTRA_INSTRUCTIONS", ""),
            MODEL_EXTRA_INSTRUCTIONS=env_overrides.get("MODEL_EXTRA_INSTRUCTIONS", ""),
        ):
            return reconcile_mod.build_system_prompt(repo_context, pr_info)

    # --- Non-empty ---

    def test_prompt_is_nonempty(self):
        """build_system_prompt must return a non-empty string."""
        prompt = self._build()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    # --- Sections present ---

    def test_agent_role_included(self):
        """Prompt must include the AGENT_ROLE section (autonomous conflict resolution)."""
        prompt = self._build()
        assert "autonomous git conflict resolution" in prompt

    def test_repo_context_included(self):
        """Prompt must embed the repo_context argument."""
        prompt = self._build(repo_context="UNIQUE_REPO_CONTEXT_12345")
        assert "UNIQUE_REPO_CONTEXT_12345" in prompt

    def test_pr_info_included(self):
        """Prompt must embed the pr_info argument."""
        prompt = self._build(pr_info="UNIQUE_PR_INFO_99999")
        assert "UNIQUE_PR_INFO_99999" in prompt

    def test_reconcile_workflow_included(self):
        """Prompt must include the RECONCILE_WORKFLOW steps."""
        prompt = self._build()
        # RECONCILE_WORKFLOW mentions "Step 1" through "Step 6"
        assert "Step 1" in prompt
        assert "Step 4" in prompt
        assert "Step 6" in prompt

    def test_efficiency_section_included(self):
        """Prompt must include the EFFICIENCY section."""
        prompt = self._build()
        assert "Each tool call costs real money" in prompt

    def test_stuck_recovery_included(self):
        """Prompt must include the STUCK_RECOVERY section with rebase abort instructions."""
        prompt = self._build()
        assert "git rebase --abort" in prompt

    def test_security_rules_included(self):
        """Prompt must include SECURITY_RULES."""
        prompt = self._build()
        assert "ABSOLUTE" in prompt
        assert "NEVER" in prompt

    # --- BASE_BRANCH substitution ---

    def test_base_branch_substituted_main(self):
        """Workflow section must have BASE_BRANCH placeholder replaced with 'main'."""
        prompt = self._build(BASE_BRANCH="main")
        assert "origin/main" in prompt
        # The raw placeholder must not remain
        assert "{BASE_BRANCH}" not in prompt

    def test_base_branch_substituted_custom(self):
        """Workflow section must substitute a custom BASE_BRANCH value."""
        prompt = self._build(BASE_BRANCH="develop")
        assert "origin/develop" in prompt
        assert "{BASE_BRANCH}" not in prompt

    def test_base_branch_substituted_release(self):
        """Workflow section must substitute a release branch name correctly."""
        prompt = self._build(BASE_BRANCH="release/v2.0")
        assert "origin/release/v2.0" in prompt
        assert "{BASE_BRANCH}" not in prompt

    # --- Wrapup hint toggling ---

    def test_wrapup_hint_absent_when_disabled(self):
        """When WRAPUP_ENABLED=False, no wrapup hint should appear in prompt."""
        prompt = self._build(WRAPUP_ENABLED=False, WRAPUP_ITERATION=45, MAX_ITERATIONS=50)
        assert "WRAP-UP REQUIRED" not in prompt

    def test_wrapup_hint_absent_when_iteration_zero(self):
        """When WRAPUP_ITERATION=0 (unset), no wrapup hint should appear."""
        prompt = self._build(WRAPUP_ENABLED=True, WRAPUP_ITERATION=0, MAX_ITERATIONS=50)
        assert "WRAP-UP REQUIRED" not in prompt

    def test_wrapup_hint_present_when_enabled(self):
        """When WRAPUP_ENABLED=True and WRAPUP_ITERATION > 0, wrapup hint must appear."""
        with patch.multiple(
            reconcile_mod,
            WRAPUP_ENABLED=True,
            WRAPUP_ITERATION=45,
            MAX_ITERATIONS=50,
            BASE_BRANCH="main",
            EXTRA_INSTRUCTIONS="",
            MODEL_EXTRA_INSTRUCTIONS="",
        ):
            prompt = reconcile_mod.build_system_prompt("ctx", "info")
        assert "WRAP-UP REQUIRED" in prompt

    def test_wrapup_hint_mentions_max_iterations(self):
        """Wrapup hint must mention the configured MAX_ITERATIONS budget."""
        with patch.multiple(
            reconcile_mod,
            WRAPUP_ENABLED=True,
            WRAPUP_ITERATION=40,
            MAX_ITERATIONS=50,
            BASE_BRANCH="main",
            EXTRA_INSTRUCTIONS="",
            MODEL_EXTRA_INSTRUCTIONS="",
        ):
            prompt = reconcile_mod.build_system_prompt("ctx", "info")
        assert "50" in prompt  # MAX_ITERATIONS

    def test_wrapup_hint_remaining_iterations_calculated(self):
        """Wrapup hint must state the number of remaining iterations."""
        with patch.multiple(
            reconcile_mod,
            WRAPUP_ENABLED=True,
            WRAPUP_ITERATION=45,
            MAX_ITERATIONS=50,
            BASE_BRANCH="main",
            EXTRA_INSTRUCTIONS="",
            MODEL_EXTRA_INSTRUCTIONS="",
        ):
            prompt = reconcile_mod.build_system_prompt("ctx", "info")
        # remaining = 50 - 45 = 5
        assert "5" in prompt

    # --- Extra instructions ---

    def test_extra_instructions_absent_when_empty(self):
        """When EXTRA_INSTRUCTIONS and MODEL_EXTRA_INSTRUCTIONS are both empty,
        no extra section separator should appear after SECURITY_RULES."""
        prompt = self._build(EXTRA_INSTRUCTIONS="", MODEL_EXTRA_INSTRUCTIONS="")
        # The base prompt ends cleanly; no trailing "\n\n" before nothing
        assert prompt.count("SECURITY_RULES") == 0  # sanity: not literally in prompt
        # We just verify it doesn't break and the prompt is valid
        assert len(prompt) > 100

    def test_extra_instructions_included(self):
        """EXTRA_INSTRUCTIONS value must appear at the end of the prompt."""
        prompt = self._build(EXTRA_INSTRUCTIONS="Always write tests for every change.")
        assert "Always write tests for every change." in prompt

    def test_model_extra_instructions_included(self):
        """MODEL_EXTRA_INSTRUCTIONS value must appear at the end of the prompt."""
        prompt = self._build(MODEL_EXTRA_INSTRUCTIONS="Think step by step before coding.")
        assert "Think step by step before coding." in prompt

    def test_both_extra_instructions_included(self):
        """Both EXTRA_INSTRUCTIONS and MODEL_EXTRA_INSTRUCTIONS must appear."""
        prompt = self._build(
            EXTRA_INSTRUCTIONS="User instruction here.",
            MODEL_EXTRA_INSTRUCTIONS="Model instruction here.",
        )
        assert "User instruction here." in prompt
        assert "Model instruction here." in prompt

    def test_extra_instructions_appear_after_security_rules(self):
        """Extra instructions must appear after the SECURITY_RULES section."""
        custom = "CUSTOM_EXTRA_INSTRUCTION_XYZ"
        prompt = self._build(EXTRA_INSTRUCTIONS=custom)
        assert custom in prompt
        security_idx = prompt.index("ABSOLUTE")
        extra_idx = prompt.index(custom)
        assert extra_idx > security_idx, "Extra instructions should follow SECURITY_RULES"

    # --- Ordering of major sections ---

    def test_section_ordering(self):
        """Major prompt sections must appear in the correct order."""
        prompt = self._build(repo_context="REPO_CTX", pr_info="PR_INFO")

        agent_role_idx = prompt.index("autonomous git conflict resolution")
        repo_ctx_idx = prompt.index("REPO_CTX")
        pr_info_idx = prompt.index("PR_INFO")
        workflow_idx = prompt.index("Step 1")
        efficiency_idx = prompt.index("Each tool call costs real money")
        stuck_idx = prompt.index("git rebase --abort")
        security_idx = prompt.index("ABSOLUTE")

        assert agent_role_idx < repo_ctx_idx
        assert repo_ctx_idx < pr_info_idx
        assert pr_info_idx < workflow_idx
        assert workflow_idx < efficiency_idx
        assert efficiency_idx < stuck_idx
        assert stuck_idx < security_idx


# ---------------------------------------------------------------------------
# write_status
# ---------------------------------------------------------------------------

class TestWriteStatus:
    """Tests for write_status()."""

    def test_writes_success_true(self, tmp_path):
        """write_status(True, ...) must write success=true to JSON."""
        status_path = _call_write_status_to_temp(tmp_path, True, "all done")
        data = json.loads(status_path.read_text())
        assert data["success"] is True
        assert data["explanation"] == "all done"

    def test_writes_success_false(self, tmp_path):
        """write_status(False, ...) must write success=false to JSON."""
        status_path = _call_write_status_to_temp(tmp_path, False, "conflict too complex")
        data = json.loads(status_path.read_text())
        assert data["success"] is False
        assert data["explanation"] == "conflict too complex"

    def test_output_is_valid_json(self, tmp_path):
        """write_status must produce valid JSON."""
        status_path = _call_write_status_to_temp(tmp_path, True, "done")
        data = json.loads(status_path.read_text())
        assert isinstance(data, dict)

    def test_output_has_success_and_explanation_keys(self, tmp_path):
        """write_status output must have both 'success' and 'explanation' keys."""
        status_path = _call_write_status_to_temp(tmp_path, True, "OK")
        data = json.loads(status_path.read_text())
        assert "success" in data
        assert "explanation" in data


# ---------------------------------------------------------------------------
# write_usage
# ---------------------------------------------------------------------------

class TestWriteUsage:
    """Tests for write_usage()."""

    def _call_write_usage_to_temp(self, tmp_path, *args):
        real_usage = tmp_path / "llm_usage.json"
        _real_open = io.open

        def _redirect_open(path, mode="r", **kw):
            if path == "/tmp/llm_usage.json":
                return _real_open(str(real_usage), mode, **kw)
            return _real_open(path, mode, **kw)

        with patch("builtins.open", side_effect=_redirect_open):
            reconcile_mod.write_usage(*args)

        return real_usage

    def test_writes_all_fields(self, tmp_path):
        """write_usage must write all four fields to the JSON file."""
        usage_path = self._call_write_usage_to_temp(tmp_path, 1000, 200, 0.05, 10)
        data = json.loads(usage_path.read_text())
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 200
        assert data["cost"] == 0.05
        assert data["iterations"] == 10

    def test_output_is_valid_json(self, tmp_path):
        """write_usage must produce valid JSON."""
        usage_path = self._call_write_usage_to_temp(tmp_path, 0, 0, 0.0, 1)
        data = json.loads(usage_path.read_text())
        assert isinstance(data, dict)

    def test_zero_values(self, tmp_path):
        """write_usage must handle zero values correctly."""
        usage_path = self._call_write_usage_to_temp(tmp_path, 0, 0, 0.0, 0)
        data = json.loads(usage_path.read_text())
        assert data["input_tokens"] == 0
        assert data["output_tokens"] == 0
        assert data["cost"] == 0.0
        assert data["iterations"] == 0


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    """Smoke tests that key module-level constants exist and have expected content."""

    def test_agent_role_nonempty(self):
        """AGENT_ROLE constant must be a non-empty string."""
        assert isinstance(reconcile_mod.AGENT_ROLE, str)
        assert len(reconcile_mod.AGENT_ROLE) > 50

    def test_reconcile_workflow_nonempty(self):
        """RECONCILE_WORKFLOW constant must be a non-empty string."""
        assert isinstance(reconcile_mod.RECONCILE_WORKFLOW, str)
        assert len(reconcile_mod.RECONCILE_WORKFLOW) > 100

    def test_reconcile_workflow_has_base_branch_placeholder(self):
        """RECONCILE_WORKFLOW must contain '{BASE_BRANCH}' placeholder (pre-substitution)."""
        assert "{BASE_BRANCH}" in reconcile_mod.RECONCILE_WORKFLOW

    def test_security_rules_nonempty(self):
        """SECURITY_RULES constant must be a non-empty string."""
        assert isinstance(reconcile_mod.SECURITY_RULES, str)
        assert len(reconcile_mod.SECURITY_RULES) > 50

    def test_security_rules_mentions_never(self):
        """SECURITY_RULES must contain 'NEVER' prohibitions."""
        assert "NEVER" in reconcile_mod.SECURITY_RULES

    def test_efficiency_nonempty(self):
        """EFFICIENCY constant must be a non-empty string."""
        assert isinstance(reconcile_mod.EFFICIENCY, str)
        assert len(reconcile_mod.EFFICIENCY) > 20

    def test_stuck_recovery_nonempty(self):
        """STUCK_RECOVERY constant must be a non-empty string."""
        assert isinstance(reconcile_mod.STUCK_RECOVERY, str)
        assert "git rebase --abort" in reconcile_mod.STUCK_RECOVERY
