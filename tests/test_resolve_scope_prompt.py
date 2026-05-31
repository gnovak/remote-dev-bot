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

    def test_budget_mentions_spec_driven_scope(self):
        text = resolve_mod._budget_paragraph(150)
        # The paragraph should explicitly contemplate spec-driven runs,
        # not just typical bug fixes.
        assert "spec" in text.lower()

    def test_budget_mentions_algorithm_extraction(self):
        """Reading a reference notebook end-to-end is exactly the work the
        budget exists for — the paragraph must say so, otherwise the agent
        keeps shortcutting algorithm-port tasks."""
        text = resolve_mod._budget_paragraph(150)
        text_lower = text.lower()
        assert "extraction" in text_lower or "porting" in text_lower or "reference" in text_lower

    def test_budget_still_warns_against_padding(self):
        # Spec-aware doesn't mean we lift the "don't pad" guard for small fixes.
        text = resolve_mod._budget_paragraph(50)
        assert "ceiling, not a target" in text
        assert "pad" in text.lower()


class TestMethodologyFaithfulnessSection:
    """Spec-named algorithms / referenced existing implementations must be
    ported faithfully, not approximated. Source: bridge-analysis PR #438
    shipped EB-shrunk averages where the spec said BT+EB — agent buried
    the deviation in a docstring."""

    def test_section_exists_in_module(self):
        assert hasattr(resolve_mod, "METHODOLOGY_FAITHFULNESS")
        assert "## Methodology faithfulness" in resolve_mod.METHODOLOGY_FAITHFULNESS

    def test_section_names_finish_success_false_as_escape(self):
        text = resolve_mod.METHODOLOGY_FAITHFULNESS
        assert "finish(success=False)" in text

    def test_section_warns_against_ship_with_todo(self):
        text = resolve_mod.METHODOLOGY_FAITHFULNESS.lower()
        # The "ship a stand-in + add a TODO" failure mode must be explicitly
        # called out so the agent can't rationalize it as good practice.
        assert "todo" in text and "shipping" in text

    def test_section_addresses_spec_internal_inconsistency(self):
        """When the spec says 'use functions from module X' but they actually
        live in notebooks/Y, the agent should grep for the real location, not
        write a stub. This is the bridge-analysis #438 exact failure mode."""
        text = resolve_mod.METHODOLOGY_FAITHFULNESS.lower()
        assert "spec is internally inconsistent" in text or "spec citation" in text

    def test_wired_into_assembled_prompt(self):
        prompt = resolve_mod.build_system_prompt(
            repo_context="ctx", issue_context_str="task"
        )
        assert "## Methodology faithfulness" in prompt


class TestDeviationReportingSection:
    """If the agent simplified, stubbed, or skipped, the PR body's first
    paragraph must say so. Buried docstrings don't count."""

    def test_section_exists(self):
        assert hasattr(resolve_mod, "DEVIATION_REPORTING")
        assert "Reporting deviations" in resolve_mod.DEVIATION_REPORTING

    def test_requires_first_paragraph_disclosure(self):
        text = resolve_mod.DEVIATION_REPORTING.lower()
        assert "first paragraph" in text and "pr body" in text

    def test_explicitly_rejects_buried_comments(self):
        text = resolve_mod.DEVIATION_REPORTING.lower()
        assert "buried" in text or "docstring" in text or "don't count" in text

    def test_wired_into_assembled_prompt(self):
        prompt = resolve_mod.build_system_prompt(
            repo_context="ctx", issue_context_str="task"
        )
        assert "Reporting deviations" in prompt


class TestTestsSection:
    """Spec-driven implementations must add tests for new code — existing
    tests passing only shows you didn't break old stuff."""

    def test_section_exists(self):
        assert hasattr(resolve_mod, "TESTS")
        assert "## Tests" in resolve_mod.TESTS

    def test_section_requires_tests_for_new_code(self):
        text = resolve_mod.TESTS.lower()
        # Must explicitly require a test per new function/class/module,
        # not just "run existing tests."
        assert "write a test" in text or "tests for it" in text

    def test_section_flags_methodology_claim_tests_as_load_bearing(self):
        text = resolve_mod.TESTS.lower()
        assert "methodology" in text and "tolerance" in text

    def test_wired_into_assembled_prompt(self):
        prompt = resolve_mod.build_system_prompt(
            repo_context="ctx", issue_context_str="task"
        )
        assert "## Tests" in prompt


class TestEndToEndSection:
    """Unit tests don't catch wrong-signature library calls, missing config
    wiring, or never-invoked functions. The agent must actually run the
    thing it built before declaring success."""

    def test_section_exists(self):
        assert hasattr(resolve_mod, "END_TO_END")
        assert "## End-to-end verification" in resolve_mod.END_TO_END

    def test_section_calls_out_server_path(self):
        text = resolve_mod.END_TO_END.lower()
        # Web app / server is the case that surfaced the gap (bridge #438).
        assert "server" in text or "uvicorn" in text

    def test_section_covers_cli_and_library_paths(self):
        text = resolve_mod.END_TO_END.lower()
        assert "cli" in text
        assert "library" in text or "function" in text

    def test_section_names_smoke_test_examples(self):
        text = resolve_mod.END_TO_END.lower()
        # The bug class to catch: TemplateResponse signature, missing wiring,
        # ImportError on startup.
        assert "templateresponse" in text or "importerror" in text or "wrong-signature" in text

    def test_wired_into_assembled_prompt(self):
        prompt = resolve_mod.build_system_prompt(
            repo_context="ctx", issue_context_str="task"
        )
        assert "## End-to-end verification" in prompt


class TestSoftenedExplorationLanguage:
    """The 'read only what you need / 20-30 iterations max' language was
    added when we were dropping tool calls due to cost. With prompt caching
    + distillation that pressure is gone, and the language now actively
    discourages the right behavior for extract-and-port tasks."""

    def test_workflow_does_not_cap_iterations_at_thirty(self):
        # The old "complex multi-file change rarely needs more than 20-30"
        # is exactly the bias that capped bridge #438 at 65 iterations
        # with a simplified BT stand-in. Must be gone.
        text = resolve_mod.WORKFLOW.lower()
        assert "rarely needs more than 20" not in text
        assert "rarely needs more than 30" not in text

    def test_workflow_acknowledges_reference_reading(self):
        """For algorithm-extraction tasks, reading the full reference
        implementation is the right thing to do."""
        text = resolve_mod.WORKFLOW.lower()
        # Must hint that reading large reference impls is sometimes correct.
        assert "reference" in text or "1500" in text or "notebook" in text
