"""Tests for the SCOPE section of resolve.py's system prompt.

The SCOPE section tells the agent to treat substantial design / spec
comments as the binding contract for the work, rather than scope-reducing
based on the issue body alone. This guards against the failure mode where
an agent with a vague issue body + detailed spec in comments scope-reduces
to a "foundational subset" and ships a tiny PR — see bridge-analysis #436
(PR #437: 3 files / 40 LOC out of a ~10-file web app spec).

The fix lives in resolve's general prompt so it works for both manual
flows (user runs /agent-design, then /agent-resolve on the same issue)
and delegate (which is conceptually the macro expansion of the manual
flow). No delegate-specific Stage 4 prompt — single source of truth.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

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


class TestScopeSection:
    """The SCOPE section must be present and assert the spec-as-contract rule."""

    def test_scope_section_exists(self):
        assert "## Scope: what counts as \"done\"" in resolve_mod.SCOPE

    def test_scope_mentions_design_and_spec_comments(self):
        import re
        # Whitespace-tolerant match (the SCOPE prompt is hard-wrapped).
        normalized = re.sub(r"\s+", " ", resolve_mod.SCOPE.lower())
        assert "design analysis" in normalized
        assert "implementation spec" in normalized

    def test_scope_names_the_macro_commands(self):
        for cmd in ("/agent-design", "/agent-workshop", "/agent-delegate"):
            assert cmd in resolve_mod.SCOPE, f"SCOPE should mention {cmd!r}"

    def test_scope_warns_against_scope_reduction(self):
        # The phrase doesn't have to be verbatim, but the anti-shortcut
        # framing must be present in some form so the model can pattern-match.
        text = resolve_mod.SCOPE.lower()
        assert "scope-reduc" in text or "shortcut" in text or "foundational" in text

    def test_scope_says_dont_finish_with_unaddressed_items(self):
        text = resolve_mod.SCOPE.lower()
        assert "finish" in text and "unaddressed" in text

    def test_scope_is_in_assembled_system_prompt(self):
        """SCOPE must actually be wired into build_system_prompt's output."""
        prompt = resolve_mod.build_system_prompt(
            repo_context="some repo context",
            issue_context_str="some issue body",
        )
        assert "## Scope: what counts as \"done\"" in prompt


class TestBudgetParagraphAcknowledgesLargerScopes:
    """The iteration-budget paragraph must acknowledge spec-driven runs need
    way more iterations than typical bug fixes — otherwise the old "20-30
    iterations is unusual" guidance keeps biasing the agent toward early
    finish() even with SCOPE present."""

    def test_budget_mentions_spec_driven_iteration_range(self):
        text = resolve_mod._budget_paragraph(150)
        assert "spec" in text.lower()
        # 50+ iterations should be acknowledged as normal for spec runs.
        assert "50" in text or "100" in text

    def test_budget_still_warns_against_padding(self):
        # SCOPE-aware doesn't mean we lift the "don't pad" guard for small fixes.
        text = resolve_mod._budget_paragraph(50)
        assert "ceiling, not a target" in text
        assert "pad" in text.lower()
