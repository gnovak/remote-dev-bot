"""Tests for the spec generation + revision prompts in lib/workshop.py.

Source: bridge-analysis PR #438 postmortem. The implementation spec
shipped with two prompt-shaped problems:
  (1) hallucinated file location: "BT functions already present in
      bridge_analysis" — actually in notebooks/leaderboard.py
  (2) `...` placeholder in a function template body — the implementer
      agent read this as "supply something reasonable" and shipped a
      simplified stand-in

Both problems live in the spec-generation prompt, not the resolve
prompt. PR #631 hardened resolve to catch this kind of thing
downstream; this file pins the upstream fix.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from workshop import (
    SPEC_DESIGN_SYSTEM_PROMPT,
    SPEC_REVISION_SYSTEM_PROMPT,
)


class TestSpecDesignPrompt:
    """The agent that produces the implementation spec must (1) verify
    every file/function citation against the real codebase, (2) not use
    `...` placeholders in code templates, and (3) require named tests
    for load-bearing methodology claims."""

    def test_requires_verifying_file_references(self):
        text = SPEC_DESIGN_SYSTEM_PROMPT.lower()
        # Must explicitly tell the agent to grep / read_file before citing.
        assert "verify" in text
        # Must call out the failure mode (citation wrong → implementer
        # stubs instead of hunting).
        assert "stub" in text or "stand-in" in text

    def test_warns_about_specific_real_world_failure(self):
        """The 'design says module X but code is in notebooks/Y' case is
        the bridge-analysis PR #438 exact failure mode. Naming the case
        with concrete examples (notebooks, bridge_analysis) makes the
        rule easier to pattern-match against."""
        text = SPEC_DESIGN_SYSTEM_PROMPT.lower()
        assert "notebooks" in text and "bridge_analysis" in text

    def test_bans_placeholder_bodies_in_code_templates(self):
        text = SPEC_DESIGN_SYSTEM_PROMPT
        # Must explicitly call out the `...` (or TODO) placeholder pattern
        # and tell the agent NOT to use it.
        assert "..." in text  # the placeholder is mentioned literally
        assert "Do NOT use" in text or "do not use" in text.lower()

    def test_offers_concrete_alternative_to_placeholders(self):
        """Banning placeholders without saying what to do instead leaves
        the agent confused. Must offer: spell out the body OR write a
        structured semantic spec naming the canonical reference."""
        text = SPEC_DESIGN_SYSTEM_PROMPT.lower()
        assert "semantic specification" in text or "canonical" in text

    def test_requires_named_test_for_methodology_claims(self):
        text = SPEC_DESIGN_SYSTEM_PROMPT
        # Must require a specific test format like
        # test_X_matches_reference_within_tolerance.
        assert "test_" in text and ("tolerance" in text.lower() or "reference" in text.lower())

    def test_warns_methodology_claim_without_test_is_just_a_label(self):
        text = SPEC_DESIGN_SYSTEM_PROMPT.lower()
        # The "label vs contract" framing is the key insight from the
        # bridge agent postmortem.
        assert "label" in text or "all existing tests pass" in text


class TestSpecRevisionPrompt:
    """The spec-revision prompt must preserve the spec-design properties
    even if council feedback would weaken them (e.g., a reviewer says
    'this is too verbose, just say "use the existing impl"' — that
    weakening must be refused)."""

    def test_preserves_real_file_references_rule(self):
        text = SPEC_REVISION_SYSTEM_PROMPT.lower()
        assert "real code" in text or "resolve to real" in text

    def test_preserves_no_placeholders_rule(self):
        text = SPEC_REVISION_SYSTEM_PROMPT
        assert "..." in text
        assert "placeholder" in text.lower()

    def test_preserves_methodology_test_requirement(self):
        text = SPEC_REVISION_SYSTEM_PROMPT.lower()
        assert "test" in text and ("methodology" in text or "tolerance" in text)

    def test_explicitly_marks_these_rules_as_non_negotiable(self):
        """Council feedback that pushes against these rules is wrong;
        the revision must not weaken them. The prompt should say so."""
        text = SPEC_REVISION_SYSTEM_PROMPT.lower()
        # Looking for "non-negotiable", "must preserve", or similar.
        assert "non-negotiable" in text or "never weaken" in text or "must preserve" in text
