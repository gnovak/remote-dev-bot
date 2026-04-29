"""Tests for the design loop module."""

import os
import sys
import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from design_loop import (
    validate_path,
    execute_read_file,
    execute_grep,
    execute_tool,
    has_agent_command,
    TOOLS,
    DEFAULT_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# validate_path
# ---------------------------------------------------------------------------

class TestValidatePath:
    def test_valid_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        ok, result = validate_path("file.txt")
        assert ok is True
        assert result == "file.txt"

    def test_rejects_absolute_path(self):
        ok, msg = validate_path("/etc/passwd")
        assert ok is False
        assert "outside the repository" in msg

    def test_rejects_parent_traversal(self):
        ok, msg = validate_path("../secret")
        assert ok is False
        assert "outside the repository" in msg

    def test_rejects_nonexistent(self):
        ok, msg = validate_path("does_not_exist_xyz.py")
        assert ok is False
        assert "not found" in msg.lower()


# ---------------------------------------------------------------------------
# execute_read_file
# ---------------------------------------------------------------------------

class TestExecuteReadFile:
    def test_reads_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "test.txt").write_text("content here")
        result = execute_read_file("test.txt")
        assert result == "content here"

    def test_returns_error_for_missing_file(self):
        result = execute_read_file("no_such_file_xyz.py")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_directory_listing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        (subdir / "a.txt").write_text("a")
        (subdir / "b.txt").write_text("b")
        result = execute_read_file("mydir")
        assert "a.txt" in result
        assert "b.txt" in result

    def test_truncates_large_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "big.txt").write_text("x" * 60000)
        result = execute_read_file("big.txt")
        assert "truncated" in result
        assert len(result) < 60000


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------

class TestExecuteTool:
    def test_submit_analysis_returns_analysis(self):
        result = execute_tool("submit_analysis", {"analysis": "my analysis"})
        assert result == "my analysis"

    def test_unknown_tool(self):
        result = execute_tool("unknown_tool", {})
        assert "Unknown tool" in result

    def test_gh_dispatches_to_gh(self, monkeypatch):
        captured = {}

        def fake_run(cmd, *a, **kw):
            captured["cmd"] = cmd
            class R:
                returncode = 0
                stdout = "issue body"
                stderr = ""
            return R()

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        result = execute_tool("gh", {"args": "issue view 584"})
        assert result == "issue body"
        assert captured["cmd"] == ["gh", "issue", "view", "584"]


# ---------------------------------------------------------------------------
# has_agent_command
# ---------------------------------------------------------------------------

class TestHasAgentCommand:
    def test_detects_agent_command(self):
        assert has_agent_command("/agent-resolve\nsome text") is True

    def test_detects_agent_design(self):
        assert has_agent_command("text\n/agent-design\nmore") is True

    def test_no_agent_command(self):
        assert has_agent_command("just regular text") is False

    def test_empty_string(self):
        assert has_agent_command("") is False

    def test_none(self):
        assert has_agent_command(None) is False

    def test_agent_in_middle_of_line_not_detected(self):
        # /agent must be at the start of a line
        assert has_agent_command("text /agent-resolve") is False


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_has_four_tools(self):
        assert len(TOOLS) == 4

    def test_tool_names(self):
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {"read_file", "grep", "gh", "submit_analysis"}

    def test_all_tools_have_descriptions(self):
        for tool in TOOLS:
            assert tool["function"]["description"]

    def test_gh_tool_takes_args(self):
        gh_tool = next(t for t in TOOLS if t["function"]["name"] == "gh")
        assert "args" in gh_tool["function"]["parameters"]["properties"]
        assert gh_tool["function"]["parameters"]["required"] == ["args"]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_prompt_is_nonempty(self):
        assert len(DEFAULT_SYSTEM_PROMPT) > 100

    def test_prompt_mentions_tools(self):
        assert "read_file" in DEFAULT_SYSTEM_PROMPT or "tools" in DEFAULT_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_submit_analysis(self):
        assert "submit_analysis" in DEFAULT_SYSTEM_PROMPT

    def test_prompt_mentions_gh_tool(self):
        assert "gh" in DEFAULT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Distillation flag
# ---------------------------------------------------------------------------

class TestDistillationFlag:
    """Verify run_design_loop's distill_enabled parameter contract.

    Full-loop behavior testing is infeasible without elaborate mocking of
    litellm. These tests verify the public-API contract:
      - the parameter exists, defaults to True
      - workshop and delegate accept and thread it through
      - the docstring documents the new return-dict keys

    Behavioral verification happens via /dogfood runs after merge.
    """

    def test_run_design_loop_signature(self):
        import inspect
        from design_loop import run_design_loop
        sig = inspect.signature(run_design_loop)
        assert "distill_enabled" in sig.parameters
        assert sig.parameters["distill_enabled"].default is True

    def test_workshop_signatures_thread_distill_enabled(self):
        import inspect
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        from workshop import run_workshop, run_delegate
        for fn in (run_workshop, run_delegate):
            sig = inspect.signature(fn)
            assert "distill_enabled" in sig.parameters, f"{fn.__name__} missing distill_enabled"
            assert sig.parameters["distill_enabled"].default is True

    def test_docstring_documents_return_keys(self):
        from design_loop import run_design_loop
        doc = run_design_loop.__doc__ or ""
        for key in ("distill_input_tokens", "distill_output_tokens", "distill_cost"):
            assert key in doc, f"return-dict key {key!r} not documented in run_design_loop docstring"
