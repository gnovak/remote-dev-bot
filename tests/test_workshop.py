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
    run_build_council,
    COUNCIL_REVIEW_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# resolve_council_models
# ---------------------------------------------------------------------------

class TestRunBuildCouncilLabels:
    """run_build_council is shared by build Stage 2, delegate Stage 5, and
    /agent-review council=true. Each uses different banner/attribution/
    completion labels — verify the parameters are threaded through to the
    posted comments so the labels can be customized per-caller."""

    def _mock_review_result(self, alias="claude-small"):
        return {
            "review": f"## Code Review by {alias}\n\nLooks good.",
            "model_alias": alias,
            "model_id": "anthropic/test",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost": 0.01,
            "elapsed": 1.0,
        }

    def test_default_labels_match_build_stage_2(self):
        from unittest.mock import patch
        posted = []
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("workshop.run_council_code_review",
                   return_value=self._mock_review_result()):
            run_build_council(
                council_models=[{"alias": "claude-small", "id": "anthropic/test"}],
                issue_title="t",
                issue_body="b",
                pr_title="pt",
                pr_body="pb",
                pr_diff="diff",
                post_comment_fn=posted.append,
            )
        joined = "\n".join(posted)
        assert "Build Stage 2 — Council Code Review" in joined
        assert "/agent-build Stage 2" in joined
        assert "Build Stage 2 complete" in joined

    def test_custom_labels_for_review_council(self):
        """When /agent-review with council=true calls this function, labels
        should NOT say 'Build Stage 2' — that text would confuse the user
        about which command they invoked."""
        from unittest.mock import patch
        posted = []
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("workshop.run_council_code_review",
                   return_value=self._mock_review_result()):
            run_build_council(
                council_models=[{"alias": "claude-small", "id": "anthropic/test"}],
                issue_title="t",
                issue_body="b",
                pr_title="pt",
                pr_body="pb",
                pr_diff="diff",
                post_comment_fn=posted.append,
                banner_label="Council Code Review",
                attribution_label="/agent-review council=true",
                completion_label="Council code review complete — awaiting human review",
            )
        joined = "\n".join(posted)
        # Custom labels present
        assert "## 🏛️ Council Code Review" in joined
        assert "/agent-review council=true" in joined
        assert "Council code review complete — awaiting human review" in joined
        # Build-mode labels NOT leaking in
        assert "Build Stage 2" not in joined
        assert "/agent-build" not in joined


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

    def test_default_council_includes_design_model(self):
        """Default council (no config) includes all models, including the design model."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
        )
        aliases = [m["alias"] for m in result]
        # Design model is included so it can critique its own work
        assert "claude-large" in aliases
        assert "claude-small" in aliases
        assert "gpt-small" in aliases
        assert "gemini-small" in aliases

    def test_default_council_single_model(self):
        """If only the design model is configured, council contains just that model."""
        models = {"claude-large": {"id": "anthropic/claude-opus-4-6"}}
        result = resolve_council_models(models, design_alias="claude-large")
        assert len(result) == 1
        assert result[0]["alias"] == "claude-large"

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
        """An empty council_config list falls back to default behavior (all models)."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=[],
        )
        aliases = [m["alias"] for m in result]
        # Default includes all models including design model
        assert "claude-large" in aliases
        assert len(aliases) == 4  # all models

    def test_none_council_config_uses_default(self):
        """None council_config falls back to default behavior (all models)."""
        result = resolve_council_models(
            self.SAMPLE_MODELS,
            design_alias="claude-large",
            council_config=None,
        )
        aliases = [m["alias"] for m in result]
        assert "claude-large" in aliases
        assert len(aliases) == 4


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


# ---------------------------------------------------------------------------
# Delegate mode: _run_revision_call, run_delegate, and system prompts
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock

from workshop import (
    DESIGN_REVISION_SYSTEM_PROMPT,
    _run_revision_call,
    run_delegate,
)


class TestRevisionSystemPrompts:
    """Tests for delegate-specific system prompt constants."""

    def test_design_revision_prompt_nonempty(self):
        assert len(DESIGN_REVISION_SYSTEM_PROMPT) > 100

    def test_design_revision_prompt_mentions_revision(self):
        lower = DESIGN_REVISION_SYSTEM_PROMPT.lower()
        assert "revise" in lower or "revised" in lower

    def test_design_revision_prompt_mentions_council(self):
        lower = DESIGN_REVISION_SYSTEM_PROMPT.lower()
        assert "council" in lower or "critiq" in lower or "feedback" in lower


class TestRunRevisionCall:
    """Tests for _run_revision_call — the non-agentic LLM call helper."""

    def _mock_response(self, text="Revised design here.", input_tokens=100, output_tokens=50, cost=0.01):
        """Build a mock LiteLLM response."""
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = text
        usage = MagicMock()
        usage.prompt_tokens = input_tokens
        usage.completion_tokens = output_tokens
        resp.usage = usage
        resp._hidden_params = {"response_cost": cost}
        return resp

    @patch("context.completion_with_retries")
    @patch("litellm.completion")
    def test_basic_call(self, mock_litellm, mock_retries):
        """Basic revision call returns expected structure."""
        mock_retries.return_value = self._mock_response("Revised output.")
        result = _run_revision_call(
            model_id="anthropic/test-model",
            system_prompt="You are a reviewer.",
            user_content="Please review this.",
        )
        assert result["text"] == "Revised output."
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cost"] == 0.01
        mock_retries.assert_called_once()

    @patch("context.completion_with_retries")
    @patch("litellm.completion")
    def test_extra_instructions_appended(self, mock_litellm, mock_retries):
        """Extra instructions are appended to the system prompt."""
        mock_retries.return_value = self._mock_response()
        _run_revision_call(
            model_id="anthropic/test-model",
            system_prompt="Base system prompt.",
            user_content="User content.",
            extra_instructions="Focus on security.",
        )
        call_args = mock_retries.call_args
        messages = call_args.kwargs["messages"]
        system_content = messages[0]["content"]
        assert "Base system prompt." in system_content
        assert "Focus on security." in system_content

    @patch("context.completion_with_retries")
    @patch("litellm.completion")
    def test_empty_response_text(self, mock_litellm, mock_retries):
        """Empty response content is handled gracefully."""
        resp = self._mock_response(text=None)
        resp.choices[0].message.content = None
        mock_retries.return_value = resp
        result = _run_revision_call(
            model_id="anthropic/test-model",
            system_prompt="System.",
            user_content="User.",
        )
        assert result["text"] == ""

    @patch("context.completion_with_retries")
    @patch("litellm.completion")
    def test_missing_usage(self, mock_litellm, mock_retries):
        """Missing usage attributes default to 0."""
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = "Output text"
        resp.usage = None
        resp._hidden_params = {}
        mock_retries.return_value = resp
        result = _run_revision_call(
            model_id="anthropic/test-model",
            system_prompt="System.",
            user_content="User.",
        )
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["cost"] == 0.0


class TestRunDelegate:
    """Tests for the full delegate pipeline (Stages 1-3)."""

    @pytest.fixture(autouse=True)
    def set_api_key(self, monkeypatch):
        """Set a fake API key so council review API key checks don't skip mocked calls."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_design_result(self, analysis="## Proposed Design\n\nDo the thing."):
        return {
            "analysis": analysis,
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost": 0.05,
            "iterations": 5,
        }

    def _mock_council_review(self, alias="claude-small", model_id="anthropic/test"):
        return {
            "review": f"Review from {alias}: looks good with minor concerns.",
            "model_alias": alias,
            "model_id": model_id,
            "input_tokens": 200,
            "output_tokens": 100,
            "cost": 0.01,
        }

    def _mock_revision_result(self, text="## Revised Design\n\nRevised content here."):
        return {
            "text": text,
            "input_tokens": 300,
            "output_tokens": 200,
            "cost": 0.02,
        }

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_full_pipeline_stages_1_3(self, mock_design, mock_council, mock_revision):
        """Full pipeline runs Stages 1-3 and returns expected structure."""
        mock_design.return_value = self._mock_design_result()
        mock_council.return_value = self._mock_council_review()
        mock_revision.return_value = self._mock_revision_result()

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
        )

        assert "design_result" in result
        assert "design_analysis" in result
        assert "council_results" in result
        assert "revised_design" in result
        assert "revision_result" in result
        assert result["design_analysis"] == "## Proposed Design\n\nDo the thing."
        assert result["revised_design"] == "## Revised Design\n\nRevised content here."
        assert len(result["council_results"]) == 1
        assert result["total_input_tokens"] > 0
        assert result["total_output_tokens"] > 0
        assert result["total_cost"] > 0

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_pipeline_no_design_aborts(self, mock_design, mock_council, mock_revision):
        """Pipeline aborts if design loop produces no analysis."""
        mock_design.return_value = {
            "analysis": "",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost": 0.01,
        }

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[],
            issue_title="Test Issue",
            issue_body="Test body.",
        )

        assert result["council_results"] == []
        assert result["revised_design"] is None
        mock_council.assert_not_called()
        mock_revision.assert_not_called()

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_pipeline_agent_command_in_design_aborts(self, mock_design, mock_council, mock_revision):
        """Pipeline aborts if design contains /agent commands."""
        mock_design.return_value = {
            "analysis": "Design here.\n/agent-resolve embedded",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost": 0.01,
        }

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[],
            issue_title="Test Issue",
            issue_body="Test body.",
        )

        assert result["revised_design"] is None
        mock_council.assert_not_called()
        mock_revision.assert_not_called()

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_pipeline_no_council_models(self, mock_design, mock_council, mock_revision):
        """Pipeline works with no council models (skips Stage 2)."""
        mock_design.return_value = self._mock_design_result()
        mock_revision.return_value = self._mock_revision_result()

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[],
            issue_title="Test Issue",
            issue_body="Test body.",
        )

        assert result["council_results"] == []
        assert result["revised_design"] == "## Revised Design\n\nRevised content here."
        mock_council.assert_not_called()

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_pipeline_posts_comments(self, mock_design, mock_council, mock_revision):
        """Pipeline calls post_comment_fn for each stage."""
        mock_design.return_value = self._mock_design_result()
        mock_council.return_value = self._mock_council_review()
        mock_revision.return_value = self._mock_revision_result()

        comments = []

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
            post_comment_fn=lambda body: comments.append(body),
        )

        # Should have comments for: Stage 1 start, Stage 1 result, Stage 2 start,
        # Stage 2 review, Stage 3 start, Stage 3 result, Stages 1-3 complete, aggregate cost
        assert len(comments) >= 6  # at least 6 posts
        # Check stage markers
        stage1_found = any("Stage 1" in c for c in comments)
        stage2_found = any("Stage 2" in c for c in comments)
        stage3_found = any("Stage 3" in c for c in comments)
        assert stage1_found
        assert stage2_found
        assert stage3_found

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_pipeline_cost_aggregation(self, mock_design, mock_council, mock_revision):
        """Pipeline aggregates costs from all stages."""
        mock_design.return_value = self._mock_design_result()
        mock_council.return_value = self._mock_council_review()
        mock_revision.return_value = self._mock_revision_result()

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
        )

        # Stage 1: 1000 + Stage 2: 200 + Stage 3: 300 = 1500
        assert result["total_input_tokens"] == 1500
        # Stage 1: 500 + Stage 2: 100 + Stage 3: 200 = 800
        assert result["total_output_tokens"] == 800
        # Stage 1: 0.05 + Stage 2: 0.01 + Stage 3: 0.02 = 0.08
        assert abs(result["total_cost"] - 0.08) < 0.001

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_design_rounds_1_skips_spec_stages(self, mock_design, mock_council, mock_revision):
        """design_rounds=1 (default) does not run spec stages."""
        mock_design.return_value = self._mock_design_result()
        mock_council.return_value = self._mock_council_review()
        mock_revision.return_value = self._mock_revision_result()

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
            design_rounds=1,
        )

        assert result["spec_result"] is None
        assert result["spec_council_results"] == []
        assert result["revised_spec"] is None
        # Exactly one design loop call (Stage 1); no Stage 3a
        assert mock_design.call_count == 1
        # Exactly one revision call (Stage 3); no Stage 3c
        assert mock_revision.call_count == 1

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_design_rounds_2_runs_spec_stages(self, mock_design, mock_council, mock_revision):
        """design_rounds=2 runs Stages 3a/3b/3c in addition to 1/2/3."""
        # Stage 1 design, then Stage 3a spec
        mock_design.side_effect = [
            self._mock_design_result(analysis="## Design\n\nDo X."),
            self._mock_design_result(analysis="## Spec\n\nEdit files A, B, C."),
        ]
        mock_council.return_value = self._mock_council_review()
        # Stage 3 revision, then Stage 3c spec revision
        mock_revision.side_effect = [
            self._mock_revision_result(text="## Revised Design\n\nRevised X."),
            self._mock_revision_result(text="## Revised Spec\n\nRevised spec."),
        ]

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
            design_rounds=2,
        )

        assert result["revised_design"] == "## Revised Design\n\nRevised X."
        assert result["revised_spec"] == "## Revised Spec\n\nRevised spec."
        assert result["spec_result"] is not None
        assert len(result["spec_council_results"]) == 1
        # Two design loop calls: Stage 1 + Stage 3a
        assert mock_design.call_count == 2
        # Two council review calls: Stage 2 + Stage 3b
        assert mock_council.call_count == 2
        # Two revision calls: Stage 3 + Stage 3c
        assert mock_revision.call_count == 2

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_design_rounds_2_passes_revised_design_as_spec_context(
        self, mock_design, mock_council, mock_revision
    ):
        """Spec loop receives the revised design via extra_context."""
        mock_design.side_effect = [
            self._mock_design_result(analysis="## Design\n\nDo X."),
            self._mock_design_result(analysis="## Spec\n\nFile details."),
        ]
        mock_council.return_value = self._mock_council_review()
        mock_revision.side_effect = [
            self._mock_revision_result(text="## Revised Design\n\nAPPROVED DESIGN CONTENT."),
            self._mock_revision_result(text="## Revised Spec"),
        ]

        run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
            extra_context="## Repo Listing\n\nfile1\nfile2",
            design_rounds=2,
        )

        # Second design_loop call is Stage 3a (spec) — check extra_context
        _, stage3a_kwargs = mock_design.call_args_list[1]
        spec_extra_context = stage3a_kwargs["extra_context"]
        # Should include the original extra_context and the approved design
        assert "Repo Listing" in spec_extra_context
        assert "APPROVED DESIGN CONTENT" in spec_extra_context
        assert "Approved Design" in spec_extra_context
        # Should use the spec system prompt override
        assert "system_prompt" in stage3a_kwargs
        assert stage3a_kwargs["system_prompt"] is not None

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_max_design_iterations_threads_into_design_loops(
        self, mock_design, mock_council, mock_revision
    ):
        """run_delegate passes max_design_iterations to design loops, not max_iterations.

        The design budget (Stage 1 design, Stage 3a implementation spec) is
        independent from the code-writing budget (Stages 4, 6). When a
        caller differentiates the two, both agentic exploration loops must
        use the design budget.
        """
        mock_design.side_effect = [
            self._mock_design_result(analysis="## Design\n\nDo X."),
            self._mock_design_result(analysis="## Spec\n\nFile details."),
        ]
        mock_council.return_value = self._mock_council_review()
        mock_revision.side_effect = [
            self._mock_revision_result(text="## Revised Design\n\nApproved."),
            self._mock_revision_result(text="## Revised Spec"),
        ]

        run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[{"alias": "claude-small", "id": "anthropic/test"}],
            issue_title="Test Issue",
            issue_body="Test body.",
            max_iterations=80,
            max_design_iterations=12,
            design_rounds=2,
        )

        # Stage 1 design loop
        _, stage1_kwargs = mock_design.call_args_list[0]
        assert stage1_kwargs["max_iterations"] == 12
        # Stage 3a implementation spec loop
        _, stage3a_kwargs = mock_design.call_args_list[1]
        assert stage3a_kwargs["max_iterations"] == 12

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_max_design_iterations_falls_back_to_max_iterations(
        self, mock_design, mock_council, mock_revision
    ):
        """When max_design_iterations is omitted, design loops inherit max_iterations.

        Callers that don't differentiate (older/simpler entry points) should
        get uniform behavior — the design loop still gets a sensible budget.
        """
        mock_design.return_value = self._mock_design_result()
        mock_council.return_value = self._mock_council_review()
        mock_revision.return_value = self._mock_revision_result()

        run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[{"alias": "claude-small", "id": "anthropic/test"}],
            issue_title="Test Issue",
            issue_body="Test body.",
            max_iterations=25,
            # max_design_iterations intentionally omitted
        )

        _, stage1_kwargs = mock_design.call_args_list[0]
        assert stage1_kwargs["max_iterations"] == 25

    @patch("workshop._run_revision_call")
    @patch("workshop.run_council_review")
    @patch("design_loop.run_design_loop")
    def test_design_rounds_2_empty_spec_aborts(
        self, mock_design, mock_council, mock_revision
    ):
        """Pipeline aborts cleanly if Stage 3a spec loop produces nothing."""
        mock_design.side_effect = [
            self._mock_design_result(analysis="## Design\n\nDo X."),
            {"analysis": "", "input_tokens": 50, "output_tokens": 25, "cost": 0.005},
        ]
        mock_council.return_value = self._mock_council_review()
        mock_revision.return_value = self._mock_revision_result(
            text="## Revised Design\n\nRevised."
        )

        result = run_delegate(
            model="anthropic/test-model",
            model_alias="test-model",
            council_models=[
                {"alias": "claude-small", "id": "anthropic/test"},
            ],
            issue_title="Test Issue",
            issue_body="Test body.",
            design_rounds=2,
        )

        # Stage 3 still ran (revised_design present), but spec stages aborted
        assert result["revised_design"] == "## Revised Design\n\nRevised."
        assert result["revised_spec"] is None
        # Only Stage 3 revision ran; Stage 3c did not
        assert mock_revision.call_count == 1
