"""Tests for workshop mode: multi-model design council."""

import json
import os
import sys
import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from workshop import (
    build_council_review_prompt,
    resolve_council_models,
    COUNCIL_REVIEW_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# resolve_council_models
# ---------------------------------------------------------------------------

class TestResolveCouncilModels:
    """Tests for council model filtering logic."""

    SAMPLE_MODELS = {
        "claude-small": {"id": "anthropic/claude-sonnet-4-20250514"},
        "claude-large": {"id": "anthropic/claude-opus-4-6"},
        "gpt-small": {"id": "openai/gpt-4o-mini"},
        "gemini-small": {"id": "gemini/gemini-2.5-flash"},
    }

    def test_explicit_council_list(self):
        """Explicit council config uses exactly those models."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=["claude-small", "gpt-small"],
        )
        aliases = [m["alias"] for m in result]
        assert aliases == ["claude-small", "gpt-small"]
        assert result[0]["id"] == "anthropic/claude-sonnet-4-20250514"
        assert result[1]["id"] == "openai/gpt-4o-mini"

    def test_explicit_council_includes_design_model(self):
        """If the design model is explicitly in the council list, it's included."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=["claude-large", "gpt-small"],
        )
        aliases = [m["alias"] for m in result]
        assert "claude-large" in aliases
        assert "gpt-small" in aliases

    def test_default_council_excludes_design_model(self):
        """Default council (no config) includes all models except the design model."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
        )
        aliases = [m["alias"] for m in result]
        assert "claude-large" not in aliases
        assert "claude-small" in aliases
        assert "gpt-small" in aliases
        assert "gemini-small" in aliases

    def test_default_council_empty_when_only_design_model(self):
        """If only the design model is configured, council is empty."""
        models = {"claude-large": {"id": "anthropic/claude-opus-4-6"}}
        result = resolve_council_models(models, design_alias="claude-large")
        assert result == []

    def test_explicit_council_skips_unknown_aliases(self):
        """Unknown aliases in the council config are silently skipped."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=["claude-small", "nonexistent-model"],
        )
        aliases = [m["alias"] for m in result]
        assert aliases == ["claude-small"]

    def test_empty_council_config_uses_default(self):
        """An empty council_config list falls back to default behavior."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=[],
        )
        aliases = [m["alias"] for m in result]
        assert "claude-large" not in aliases
        assert len(aliases) == 3  # all except design model

    def test_none_council_config_uses_default(self):
        """None council_config falls back to default behavior."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=None,
        )
        aliases = [m["alias"] for m in result]
        assert "claude-large" not in aliases
        assert len(aliases) == 3


# ---------------------------------------------------------------------------
# build_council_review_prompt
# ---------------------------------------------------------------------------

class TestBuildCouncilReviewPrompt:
    """Tests for council review prompt construction."""

    def test_prompt_includes_issue_context(self):
        prompt = build_council_review_prompt(
            issue_title="Add workshop mode",
            issue_body="We need a multi-model review flow.",
            issue_comments="Some discussion here.",
            design_analysis="## Proposed Design\nDo the thing.",
            model_alias="claude-small",
        )
        assert "Add workshop mode" in prompt
        assert "We need a multi-model review flow." in prompt
        assert "Some discussion here." in prompt

    def test_prompt_includes_design_analysis(self):
        prompt = build_council_review_prompt(
            issue_title="Test",
            issue_body="Body",
            issue_comments="",
            design_analysis="## My Design\n\nThis is the design.",
            model_alias="gpt-small",
        )
        assert "## My Design" in prompt
        assert "This is the design." in prompt

    def test_prompt_includes_model_alias_in_format(self):
        prompt = build_council_review_prompt(
            issue_title="Test",
            issue_body="Body",
            issue_comments="",
            design_analysis="Design here.",
            model_alias="gemini-small",
        )
        assert "## Design Review by gemini-small" in prompt

    def test_prompt_includes_review_sections(self):
        prompt = build_council_review_prompt(
            issue_title="Test",
            issue_body="Body",
            issue_comments="",
            design_analysis="Design here.",
            model_alias="test-model",
        )
        assert "**What I'd keep:**" in prompt
        assert "**Concerns:**" in prompt
        assert "**Alternatives worth considering:**" in prompt
        assert "**Open questions for the author:**" in prompt


# ---------------------------------------------------------------------------
# System prompt sanity
# ---------------------------------------------------------------------------

class TestCouncilSystemPrompt:
    def test_system_prompt_is_nonempty(self):
        assert len(COUNCIL_REVIEW_SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_design_review(self):
        assert "design review" in COUNCIL_REVIEW_SYSTEM_PROMPT.lower()
