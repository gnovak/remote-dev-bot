"""Tests for context distillation (lib/distill.py)."""

import os
import tempfile
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from lib.distill import (
    SOURCE_EXTENSIONS,
    SKIP_EXTENSIONS,
    SKIP_DIRS,
    SOURCE_FILE_CAP,
    OTHER_FILE_CAP,
    DISTILL_SMALL_REPO_LIMIT,
    DISTILL_STRUCT_EXTRACT_LIMIT,
    DISTILL_OUTPUT_TOKENS,
    TRUNC_HALF_CHARS,
    OTHER_TRUNC_HALF_CHARS,
    gather_repo_files,
    format_codebase,
    format_structural_extract,
    maybe_distill,
    _truncate_content,
    _should_skip_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_git_repo(tmp_path, files=None):
    """Create a git repo in tmp_path with given files.
    
    files is a dict of {path: content}. If content is bytes, written in binary mode.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
    
    if files:
        for path, content in files.items():
            full_path = tmp_path / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                full_path.write_bytes(content)
            else:
                full_path.write_text(content)
        
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    
    return tmp_path


# ---------------------------------------------------------------------------
# _should_skip_path
# ---------------------------------------------------------------------------

class TestShouldSkipPath:
    def test_skip_extension(self):
        assert _should_skip_path("image.png") is True
        assert _should_skip_path("data.csv") is True
        assert _should_skip_path("app.min.js") is True
        assert _should_skip_path("Pipfile.lock") is True

    def test_skip_directory(self):
        assert _should_skip_path("node_modules/foo.js") is True
        assert _should_skip_path("venv/lib/site.py") is True
        assert _should_skip_path("__pycache__/mod.pyc") is True
        assert _should_skip_path("dist/bundle.js") is True
        assert _should_skip_path("build/output.js") is True

    def test_allow_normal_files(self):
        assert _should_skip_path("lib/resolve.py") is False
        assert _should_skip_path("README.md") is False
        assert _should_skip_path("config.yaml") is False
        assert _should_skip_path("src/index.ts") is False

    def test_deep_nested_skip_dir(self):
        assert _should_skip_path("foo/node_modules/bar/baz.js") is True
        assert _should_skip_path("a/b/__pycache__/c.pyc") is True


# ---------------------------------------------------------------------------
# _truncate_content
# ---------------------------------------------------------------------------

class TestTruncateContent:
    def test_short_content_not_truncated(self):
        content = "short text"
        result, truncated = _truncate_content(content, cap=1000, half_chars=100)
        assert result == content
        assert truncated is False

    def test_exactly_at_cap_not_truncated(self):
        content = "x" * 1000
        result, truncated = _truncate_content(content, cap=1000, half_chars=100)
        assert result == content
        assert truncated is False

    def test_over_cap_is_truncated(self):
        content = "A" * 500 + "B" * 500 + "C" * 500
        result, truncated = _truncate_content(content, cap=1000, half_chars=200)
        assert truncated is True
        assert "A" * 200 in result
        assert "C" * 200 in result
        assert "... [" in result
        assert "chars omitted" in result

    def test_truncation_preserves_boundaries(self):
        content = "START" + "x" * 10000 + "END"
        result, truncated = _truncate_content(content, cap=100, half_chars=50)
        assert truncated is True
        assert result.startswith("START")
        assert result.endswith("END")


# ---------------------------------------------------------------------------
# gather_repo_files
# ---------------------------------------------------------------------------

class TestGatherRepoFiles:
    def test_basic_gather(self, tmp_path):
        files = {
            "main.py": "print('hello')",
            "README.md": "# Title",
            "config.yaml": "key: value",
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        paths = [f["path"] for f in result]
        assert "main.py" in paths
        assert "README.md" in paths
        assert "config.yaml" in paths

    def test_skip_binary_files(self, tmp_path):
        files = {
            "main.py": "print('hello')",
            "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00",
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        paths = [f["path"] for f in result]
        assert "main.py" in paths
        assert "image.png" not in paths

    def test_skip_dirs(self, tmp_path):
        files = {
            "main.py": "print('hello')",
            "node_modules/dep.js": "module.exports = {}",
            "__pycache__/mod.cpython-311.pyc": b"\x00\x00",
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        paths = [f["path"] for f in result]
        assert "main.py" in paths
        assert "node_modules/dep.js" not in paths

    def test_skip_extensions(self, tmp_path):
        files = {
            "main.py": "print('hello')",
            "data.csv": "a,b,c\n1,2,3",
            "bundle.min.js": "minified code",
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        paths = [f["path"] for f in result]
        assert "main.py" in paths
        assert "data.csv" not in paths
        assert "bundle.min.js" not in paths

    def test_source_file_classification(self, tmp_path):
        files = {
            "app.py": "# Python source",
            "style.css": "body {}",
            "notes.log": "some log data",
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        by_path = {f["path"]: f for f in result}
        assert by_path["app.py"]["is_source"] is True
        assert by_path["style.css"]["is_source"] is True
        # .log is not in SOURCE_EXTENSIONS
        assert by_path["notes.log"]["is_source"] is False

    def test_truncation_applied(self, tmp_path):
        large_content = "x" * (OTHER_FILE_CAP + 1000)
        files = {
            "big.log": large_content,
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        by_path = {f["path"]: f for f in result}
        assert by_path["big.log"]["truncated"] is True
        assert len(by_path["big.log"]["content"]) < len(large_content)

    def test_sorted_by_path(self, tmp_path):
        files = {
            "z.py": "z",
            "a.py": "a",
            "m.py": "m",
        }
        make_git_repo(tmp_path, files)
        
        result = gather_repo_files(str(tmp_path))
        paths = [f["path"] for f in result]
        assert paths == sorted(paths)

    def test_utf8_decode_error_skipped(self, tmp_path):
        files = {
            "good.py": "print('hello')",
            "bad.dat": b"\x80\x81\x82\x83\x84",  # invalid UTF-8
        }
        make_git_repo(tmp_path, files)
        
        # .dat is in SKIP_EXTENSIONS, so let's use a different extension
        # that's not in the skip list
        bad_path = tmp_path / "bad.bin2"
        bad_path.write_bytes(b"\x80\x81\x82\x83\x84")
        subprocess.run(["git", "add", "bad.bin2"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add bad"], cwd=tmp_path, capture_output=True)
        
        result = gather_repo_files(str(tmp_path))
        paths = [f["path"] for f in result]
        assert "good.py" in paths
        assert "bad.bin2" not in paths


# ---------------------------------------------------------------------------
# format_codebase
# ---------------------------------------------------------------------------

class TestFormatCodebase:
    def test_basic_format(self):
        files = [
            {"path": "main.py", "content": "print('hello')", "is_source": True, "truncated": False},
        ]
        result = format_codebase(files)
        assert "<codebase>" in result
        assert "</codebase>" in result
        assert '<file path="main.py">' in result
        assert "print('hello')" in result

    def test_truncated_attribute(self):
        files = [
            {"path": "big.py", "content": "...", "is_source": True, "truncated": True},
        ]
        result = format_codebase(files)
        assert 'truncated="true"' in result

    def test_not_truncated_no_attribute(self):
        files = [
            {"path": "small.py", "content": "x", "is_source": True, "truncated": False},
        ]
        result = format_codebase(files)
        assert 'truncated=' not in result

    def test_multiple_files(self):
        files = [
            {"path": "a.py", "content": "aaa", "is_source": True, "truncated": False},
            {"path": "b.py", "content": "bbb", "is_source": True, "truncated": False},
        ]
        result = format_codebase(files)
        assert '<file path="a.py">' in result
        assert '<file path="b.py">' in result


# ---------------------------------------------------------------------------
# format_structural_extract
# ---------------------------------------------------------------------------

class TestFormatStructuralExtract:
    def test_python_extract(self):
        py_content = '''
def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

class MyClass:
    """A sample class."""
    
    def method(self, x: int):
        """Do something with x."""
        return x * 2
'''
        files = [
            {"path": "mod.py", "content": py_content, "is_source": True, "truncated": False},
        ]
        result = format_structural_extract(files)
        assert "<structural_extract>" in result
        assert "</structural_extract>" in result
        assert "hello" in result
        assert "MyClass" in result
        assert "method" in result

    def test_non_python_first_lines(self):
        js_content = "\n".join([f"line {i}" for i in range(50)])
        files = [
            {"path": "app.js", "content": js_content, "is_source": True, "truncated": False},
        ]
        result = format_structural_extract(files)
        # Should include first 30 lines
        assert "line 0" in result
        assert "line 29" in result
        # Should not include line 40+
        assert "line 40" not in result

    def test_python_parse_failure_falls_back(self):
        bad_py = "def broken(\n  this is not valid python"
        files = [
            {"path": "bad.py", "content": bad_py, "is_source": True, "truncated": False},
        ]
        # Should not raise, falls back to first-20-lines
        result = format_structural_extract(files)
        assert "broken" in result


# ---------------------------------------------------------------------------
# maybe_distill — tier selection and error handling
# ---------------------------------------------------------------------------

class TestMaybeDistill:
    def test_returns_original_on_failure(self, tmp_path):
        """If LLM call fails, returns repo_context unchanged."""
        files = {
            "main.py": "print('hello')",
        }
        make_git_repo(tmp_path, files)
        
        original_context = "## Repository File Listing\n\nmain.py"
        issue_context = "Fix a bug"
        
        with patch("lib.distill.completion", side_effect=Exception("API error")):
            result = maybe_distill(original_context, issue_context, "anthropic/claude-sonnet-4-5", root=str(tmp_path))
        
        assert result[0] == original_context  # context unchanged
        assert result[1] == 0  # no tokens used
        assert result[2] == 0
        assert result[3] == 0.0

    def test_small_repo_sends_full_codebase(self, tmp_path):
        """Small repo (< DISTILL_SMALL_REPO_LIMIT tokens) sends full codebase."""
        files = {
            "main.py": "print('hello')",
            "lib.py": "def helper(): pass",
        }
        make_git_repo(tmp_path, files)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Distilled: main.py is relevant"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response._hidden_params = {"response_cost": 0.01}
        
        original_context = "## Repo\n\nmain.py\nlib.py"
        
        with patch("lib.distill.completion", return_value=mock_response) as mock_comp:
            result = maybe_distill(original_context, "Fix a bug", "anthropic/claude-sonnet-4-5", root=str(tmp_path))
        
        assert result[0] == "Distilled: main.py is relevant"
        assert result[1] == 100
        assert result[2] == 50
        assert result[3] == 0.01
        # Verify distill was called with full codebase
        call_args = mock_comp.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][1]
        # The user message should contain <codebase> (full codebase format)
        user_msg = [m for m in messages if m["role"] == "user"][0]["content"]
        assert "<codebase>" in user_msg

    def test_large_repo_skips_distillation(self, tmp_path):
        """Large repos (> DISTILL_STRUCT_EXTRACT_LIMIT) skip distillation."""
        files = {
            "main.py": "print('hello')",
        }
        make_git_repo(tmp_path, files)
        
        original_context = "## Repo context"
        
        # Mock gather_repo_files to return a huge file list
        huge_files = [
            {"path": f"file_{i}.py", "content": "x" * 100000, "is_source": True, "truncated": False}
            for i in range(200)
        ]
        
        with patch("lib.distill.gather_repo_files", return_value=huge_files):
            result = maybe_distill(original_context, "Fix a bug", "anthropic/claude-sonnet-4-5", root=str(tmp_path))
        
        assert result[0] == original_context  # unchanged
        assert result[1] == 0

    def test_medium_repo_uses_structural_extract(self, tmp_path):
        """Medium repos use structural extract approach."""
        files = {
            "main.py": "def main(): pass",
        }
        make_git_repo(tmp_path, files)
        
        # Create files that total between SMALL and STRUCT limits
        medium_files = [
            {"path": f"mod_{i}.py", "content": "x" * 2000, "is_source": True, "truncated": False}
            for i in range(300)
        ]
        
        # First call: _identify_relevant_files — returns file paths (one per line)
        identify_response = MagicMock()
        identify_response.choices = [MagicMock()]
        identify_response.choices[0].message.content = "mod_1.py\nmod_2.py"
        identify_response.usage = MagicMock()
        identify_response.usage.prompt_tokens = 200
        identify_response.usage.completion_tokens = 50
        identify_response._hidden_params = {"response_cost": 0.01}
        
        # Second call: distill — returns the distilled context
        distill_response = MagicMock()
        distill_response.choices = [MagicMock()]
        distill_response.choices[0].message.content = "Distilled: mod_1.py and mod_2.py are relevant"
        distill_response.usage = MagicMock()
        distill_response.usage.prompt_tokens = 150
        distill_response.usage.completion_tokens = 100
        distill_response._hidden_params = {"response_cost": 0.02}
        
        with patch("lib.distill.gather_repo_files", return_value=medium_files), \
             patch("lib.distill.completion", side_effect=[identify_response, distill_response]):
            result = maybe_distill("## Repo", "Fix a bug", "anthropic/claude-sonnet-4-5", root=str(tmp_path))
        
        assert result[0] == "Distilled: mod_1.py and mod_2.py are relevant"
        assert result[1] == 350   # 200 + 150
        assert result[2] == 150   # 50 + 100

    def test_returns_tuple(self, tmp_path):
        """maybe_distill returns (context, input_tokens, output_tokens, cost, structural_extract)."""
        files = {"main.py": "x"}
        make_git_repo(tmp_path, files)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "distilled"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response._hidden_params = {"response_cost": 0.001}

        with patch("lib.distill.completion", return_value=mock_response):
            ctx, inp, out, cost, struct_extract = maybe_distill("repo", "task", "anthropic/claude-sonnet-4-5", root=str(tmp_path))

        assert ctx == "distilled"
        assert inp == 10
        assert out == 5
        assert cost == 0.001
        assert "<structural_extract>" in struct_extract


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_source_extensions_are_lowercase(self):
        for ext in SOURCE_EXTENSIONS:
            assert ext == ext.lower(), f"{ext} should be lowercase"
            assert ext.startswith("."), f"{ext} should start with ."

    def test_skip_extensions_are_lowercase(self):
        for ext in SKIP_EXTENSIONS:
            assert ext == ext.lower(), f"{ext} should be lowercase"
            assert ext.startswith("."), f"{ext} should start with ."

    def test_no_overlap_source_skip(self):
        overlap = SOURCE_EXTENSIONS & SKIP_EXTENSIONS
        assert not overlap, f"Extensions in both SOURCE and SKIP: {overlap}"

    def test_caps_are_positive(self):
        assert SOURCE_FILE_CAP > 0
        assert OTHER_FILE_CAP > 0
        assert DISTILL_SMALL_REPO_LIMIT > 0
        assert DISTILL_STRUCT_EXTRACT_LIMIT > DISTILL_SMALL_REPO_LIMIT
        assert DISTILL_OUTPUT_TOKENS > 0


# ---------------------------------------------------------------------------
# compress_linked_issue
# ---------------------------------------------------------------------------

from lib.distill import (
    compress_linked_issue,
    LINKED_ISSUE_COMPRESS_OUTPUT_TOKENS,
    LINKED_ISSUE_COMPRESS_SYSTEM_PROMPT,
)


class TestCompressLinkedIssue:
    def test_returns_compressed_text(self):
        """compress_linked_issue returns (text, input_tokens, output_tokens, cost)."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary: implement X using Y approach"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 500
        mock_response.usage.completion_tokens = 100
        mock_response._hidden_params = {"response_cost": 0.005}

        with patch("lib.distill.completion", return_value=mock_response) as mock_comp:
            text, inp, out, cost = compress_linked_issue(
                "Issue title",
                "Issue body text",
                "--- @user ---\nSome comment\n\n",
                "PR body text",
                "diff content",
                "anthropic/claude-sonnet-4-5",
            )

        assert text == "Summary: implement X using Y approach"
        assert inp == 500
        assert out == 100
        assert cost == 0.005
        # Verify LLM was called once
        mock_comp.assert_called_once()

    def test_passes_all_context_to_llm(self):
        """Verify the LLM call includes issue title, body, comments, PR body, and diff."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "compressed"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response._hidden_params = {"response_cost": 0.001}

        with patch("lib.distill.completion", return_value=mock_response) as mock_comp:
            compress_linked_issue(
                "My Issue Title",
                "The issue body",
                "--- @dev ---\nDesign comment\n\n",
                "PR fixes things",
                "+added line\n-removed line",
                "anthropic/claude-sonnet-4-5",
            )

        call_args = mock_comp.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][1]
        user_msg = [m for m in messages if m["role"] == "user"][0]["content"]
        system_msg = [m for m in messages if m["role"] == "system"][0]["content"]

        # Check all context pieces are included
        assert "My Issue Title" in user_msg
        assert "The issue body" in user_msg
        assert "Design comment" in user_msg
        assert "PR fixes things" in user_msg
        assert "+added line" in user_msg
        # Check system prompt is the compression one
        assert system_msg == LINKED_ISSUE_COMPRESS_SYSTEM_PROMPT

    def test_uses_correct_max_tokens(self):
        """Verify the LLM call uses the linked issue compression token budget."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "compressed"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response._hidden_params = {"response_cost": 0.001}

        with patch("lib.distill.completion", return_value=mock_response) as mock_comp:
            compress_linked_issue(
                "title", "body", "comments", "pr body", "diff", "anthropic/claude-sonnet-4-5"
            )

        call_args = mock_comp.call_args
        assert call_args[1]["max_tokens"] == LINKED_ISSUE_COMPRESS_OUTPUT_TOKENS

    def test_handles_empty_response(self):
        """Empty LLM response returns empty string."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 0
        mock_response._hidden_params = {"response_cost": 0.001}

        with patch("lib.distill.completion", return_value=mock_response):
            text, inp, out, cost = compress_linked_issue(
                "title", "body", "comments", "pr body", "diff", "anthropic/claude-sonnet-4-5"
            )

        assert text == ""

    def test_handles_no_choices(self):
        """Response with empty choices list returns empty string."""
        mock_response = MagicMock()
        mock_response.choices = []
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 0
        mock_response._hidden_params = {"response_cost": 0.0}

        with patch("lib.distill.completion", return_value=mock_response):
            text, inp, out, cost = compress_linked_issue(
                "title", "body", "comments", "pr body", "diff", "anthropic/claude-sonnet-4-5"
            )

        assert text == ""

    def test_propagates_llm_exceptions(self):
        """LLM errors are propagated to the caller."""
        with patch("lib.distill.completion", side_effect=Exception("API down")):
            with pytest.raises(Exception, match="API down"):
                compress_linked_issue(
                    "title", "body", "comments", "pr body", "diff", "anthropic/claude-sonnet-4-5"
                )

    def test_output_token_budget_constant(self):
        """The output token budget is 4096."""
        assert LINKED_ISSUE_COMPRESS_OUTPUT_TOKENS == 4_096


# ---------------------------------------------------------------------------
# parse_linked_issues (from lib/resolve.py)
# ---------------------------------------------------------------------------

with patch.dict(os.environ, {
    "ISSUE_NUMBER": "1",
    "GITHUB_REPOSITORY": "test/repo",
    "LLM_MODEL": "anthropic/test",
    "BASH_OUTPUT_LIMIT": "0",
    "CONTEXT_KEEP_TOOL_RESULTS": "0",
    "MAX_CONTEXT_TOKENS": "0",
    "COMPACTION_COVERAGE": "0.5",
    "COMPACTION_FACTOR": "0.5",
}):
    from lib.resolve import parse_linked_issues


class TestParseLinkedIssues:
    def test_fixes_hash(self):
        assert parse_linked_issues("Fixes #123") == ["123"]

    def test_closes_hash(self):
        assert parse_linked_issues("Closes #456") == ["456"]

    def test_resolves_hash(self):
        assert parse_linked_issues("Resolves #789") == ["789"]

    def test_case_insensitive(self):
        assert parse_linked_issues("fixes #100") == ["100"]
        assert parse_linked_issues("FIXES #200") == ["200"]
        assert parse_linked_issues("Fixes #300") == ["300"]

    def test_fix_singular(self):
        assert parse_linked_issues("Fix #42") == ["42"]

    def test_close_singular(self):
        assert parse_linked_issues("Close #42") == ["42"]

    def test_resolve_singular(self):
        assert parse_linked_issues("Resolve #42") == ["42"]

    def test_fixed_past_tense(self):
        assert parse_linked_issues("Fixed #42") == ["42"]

    def test_closed_past_tense(self):
        assert parse_linked_issues("Closed #42") == ["42"]

    def test_resolved_past_tense(self):
        assert parse_linked_issues("Resolved #42") == ["42"]

    def test_multiple_issues(self):
        body = "Fixes #10\nCloses #20\nResolves #30"
        assert parse_linked_issues(body) == ["10", "20", "30"]

    def test_deduplication(self):
        body = "Fixes #10\nAlso fixes #10"
        assert parse_linked_issues(body) == ["10"]

    def test_with_repo_prefix(self):
        body = "Fixes owner/repo#123"
        assert parse_linked_issues(body) == ["123"]

    def test_empty_body(self):
        assert parse_linked_issues("") == []
        assert parse_linked_issues(None) == []

    def test_no_linked_issues(self):
        assert parse_linked_issues("This PR adds a feature") == []

    def test_embedded_in_text(self):
        body = "This PR fixes #42 by refactoring the parser"
        assert parse_linked_issues(body) == ["42"]

    def test_multiple_on_same_line(self):
        body = "Fixes #1, closes #2"
        # Both should be found
        result = parse_linked_issues(body)
        assert "1" in result
        assert "2" in result
