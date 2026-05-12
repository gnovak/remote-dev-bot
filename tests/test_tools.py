"""Tests for lib/tools.py shared tool implementations.

Currently covers execute_gh; other helpers are tested via the consuming
modules' test files (test_design_loop, test_resolve, test_reconcile).
"""

import os
import sys

# Ensure lib/ is importable as a top-level package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.tools import execute_gh


class _FakeRun:
    """Minimal stand-in for subprocess.run's CompletedProcess result."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestExecuteGh:
    def test_runs_subcommand_without_leading_gh(self, monkeypatch):
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            return _FakeRun(stdout="issue body")

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        result = execute_gh("issue view 584")
        assert result == "issue body"
        assert captured["cmd"] == ["gh", "issue", "view", "584"]

    def test_strips_leading_gh(self, monkeypatch):
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            return _FakeRun(stdout="ok")

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        execute_gh("gh issue view 584")
        assert captured["cmd"] == ["gh", "issue", "view", "584"]

    def test_empty_input_returns_error(self):
        assert "Error" in execute_gh("")
        assert "Error" in execute_gh("   ")
        assert "Error" in execute_gh("gh")
        assert "Error" in execute_gh("gh ")

    def test_handles_quoted_arguments(self, monkeypatch):
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            return _FakeRun(stdout="ok")

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        execute_gh('issue list --search "hello world"')
        assert captured["cmd"] == ["gh", "issue", "list", "--search", "hello world"]

    def test_unbalanced_quotes_returns_error(self):
        result = execute_gh('issue list --search "unclosed')
        assert "Error parsing" in result

    def test_nonzero_exit_prefixes_output(self, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            return _FakeRun(stdout="", stderr="not found", returncode=1)

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        result = execute_gh("issue view 99999")
        assert "exit code 1" in result
        assert "not found" in result

    def test_no_shell_interpolation(self, monkeypatch):
        # Shell metacharacters should be passed as literal arguments to gh,
        # not interpreted by a shell. This is enforced by passing a list to
        # subprocess.run instead of shell=True.
        captured = {}

        def fake_run(cmd, *args, shell=None, **kwargs):
            captured["cmd"] = cmd
            captured["shell"] = shell
            return _FakeRun(stdout="ok")

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        execute_gh("issue view 1; rm -rf /")
        # Whether shlex parses this in one shot or barfs, we never invoke a shell
        assert captured.get("shell") in (None, False)

    def test_gh_missing_returns_error(self, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            raise FileNotFoundError("gh")

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        result = execute_gh("issue view 1")
        assert "gh CLI not found" in result

    def test_timeout_returns_error(self, monkeypatch):
        import subprocess as _subprocess

        def fake_run(cmd, *args, **kwargs):
            raise _subprocess.TimeoutExpired(cmd=cmd, timeout=30)

        monkeypatch.setattr("lib.tools.subprocess.run", fake_run)
        result = execute_gh("api repos/owner/repo")
        assert "timed out" in result
