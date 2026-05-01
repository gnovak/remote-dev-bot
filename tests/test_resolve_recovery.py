"""Tests for the recovery helpers in lib/resolve.py — currently
_commit_dirty_wip().

resolve.py reads ISSUE_NUMBER from os.environ at import time, so we patch
the environment before importing — same pattern as test_no_op.py and
test_reconcile.py.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import resolve.py with required env vars so module-level code succeeds.
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


class TestCommitDirtyWip:
    """Tests for _commit_dirty_wip() — the auto-save-WIP recovery helper."""

    def test_clean_tree_returns_false_no_commit(self, monkeypatch):
        """If git status is clean, return False without git add/commit/push."""
        calls = []

        def fake_run(cmd, *, check=True, timeout=60):
            calls.append(cmd)
            if "git status" in cmd:
                return ""  # clean tree
            return ""

        monkeypatch.setattr(resolve_mod, "run", fake_run)
        result = resolve_mod._commit_dirty_wip("test")
        assert result is False
        # Only `git status --porcelain` should have been called
        assert len(calls) == 1
        assert "git status" in calls[0]

    def test_dirty_tree_commits_and_pushes(self, monkeypatch):
        """If git status shows changes, run add → commit → push and return True."""
        calls = []

        def fake_run(cmd, *, check=True, timeout=60):
            calls.append(cmd)
            if "git status" in cmd:
                return " M lib/resolve.py\n?? scratch.py\n"  # dirty
            return ""

        monkeypatch.setattr(resolve_mod, "run", fake_run)
        result = resolve_mod._commit_dirty_wip("agent did not finish")
        assert result is True
        # Should have run: status, add, commit, push (4 commands)
        assert len(calls) == 4
        assert "git status" in calls[0]
        assert calls[1] == "git add -A"
        assert "git commit" in calls[2]
        assert "--no-verify" in calls[2]
        assert "agent did not finish" in calls[2]
        assert calls[3] == "git push origin HEAD"

    def test_label_appears_in_commit_message(self, monkeypatch):
        """The label argument is included in the commit message."""
        commit_cmd = []

        def fake_run(cmd, *, check=True, timeout=60):
            if "git status" in cmd:
                return " M file.py\n"
            if "git commit" in cmd:
                commit_cmd.append(cmd)
            return ""

        monkeypatch.setattr(resolve_mod, "run", fake_run)
        resolve_mod._commit_dirty_wip("custom-label-xyz")
        assert len(commit_cmd) == 1
        assert "custom-label-xyz" in commit_cmd[0]

    def test_default_label(self, monkeypatch):
        """Calling without arguments uses default label 'partial work'."""
        commit_cmd = []

        def fake_run(cmd, *, check=True, timeout=60):
            if "git status" in cmd:
                return " M file.py\n"
            if "git commit" in cmd:
                commit_cmd.append(cmd)
            return ""

        monkeypatch.setattr(resolve_mod, "run", fake_run)
        resolve_mod._commit_dirty_wip()
        assert "partial work" in commit_cmd[0]

    def test_exception_is_non_fatal(self, monkeypatch):
        """If a git command raises, _commit_dirty_wip returns False without re-raising."""

        def fake_run(cmd, *, check=True, timeout=60):
            raise RuntimeError("simulated git failure")

        monkeypatch.setattr(resolve_mod, "run", fake_run)
        # Must not raise
        result = resolve_mod._commit_dirty_wip("test")
        assert result is False

    def test_uses_no_verify_flag(self, monkeypatch):
        """Commit must include --no-verify to skip pre-commit hooks."""
        # Pre-commit hooks running tests/formatters could fail and lose the WIP
        # work entirely. --no-verify ensures the safety-net commit always lands.
        commit_cmd = []

        def fake_run(cmd, *, check=True, timeout=60):
            if "git status" in cmd:
                return " M f.py\n"
            if "git commit" in cmd:
                commit_cmd.append(cmd)
            return ""

        monkeypatch.setattr(resolve_mod, "run", fake_run)
        resolve_mod._commit_dirty_wip("test")
        assert "--no-verify" in commit_cmd[0]
