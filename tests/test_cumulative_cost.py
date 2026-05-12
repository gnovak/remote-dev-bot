"""Tests for lib/cumulative_cost.py — cumulative cost aggregation across steps.

Covers:
  - extract_costs_from_text: pure regex parsing of per-step cost tables
  - compute_cumulative_table: orchestration with mocked gh api subprocess calls
"""

import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, "lib")
from cumulative_cost import (
    _fmt_loc,
    _fmt_tok,
    compute_cumulative_table,
    extract_costs_from_text,
)


# ---------------------------------------------------------------------------
# Helpers: sample per-step cost table fragments
# ---------------------------------------------------------------------------

STEP_TABLE_1 = """\
### 💰 Cost

| Metric | Value |
|--------|-------|
| Time | 2m 30s |
| Iterations | 5 |
| Input | 10.0K tokens |
| Output | 2.0K tokens |
| Diff | 3 files changed, 42 insertions(+), 10 deletions(-) |
| Info | 1.5 Kbit |
| **Cost** | **$1.23** |
"""

STEP_TABLE_2 = """\
### 💰 Cost

| Metric | Value |
|--------|-------|
| Time | 1m 10s |
| Iterations | 3 |
| Input | 5.5K tokens |
| Output | 1.0K tokens |
| Diff | 1 file changed, 20 insertions(+), 5 deletions(-) |
| Info | 0.8 Kbit |
| **Cost** | **$0.50** |
"""

CUMULATIVE_TABLE = """\
### 📊 Feature total (2 steps)

| Metric | Value |
|--------|-------|
| Cumulative LOC | ~77 (estimate) |
| Cumulative info | 2.3 Kbit |
| Cumulative input | 15.5K tokens |
| Cumulative output | 3.0K tokens |
| Cumulative LOC/$ | ~44 loc/$ |
| Cumulative info/$ | 1.3 Kbit/$ |
| Cumulative cost | $1.73 |
"""


# ---------------------------------------------------------------------------
# _fmt_tok
# ---------------------------------------------------------------------------


def test_fmt_tok_small():
    """Small numbers returned as plain string."""
    assert _fmt_tok(0) == "0"
    assert _fmt_tok(999) == "999"


def test_fmt_tok_thousands():
    """1 000–9 999 formatted as X.XK; 10 000+ as XK."""
    assert _fmt_tok(1_000) == "1.0K"
    assert _fmt_tok(9_999) == "10.0K"  # round(9.999, 1) = 10.0
    assert _fmt_tok(10_000) == "10K"
    assert _fmt_tok(42_500) == "42K"  # round(42.5) = 42


def test_fmt_tok_millions():
    """1 000 000+ formatted as XM or X.XM."""
    assert _fmt_tok(1_000_000) == "1.0M"
    assert _fmt_tok(10_000_000) == "10M"
    assert _fmt_tok(2_500_000) == "2.5M"


# ---------------------------------------------------------------------------
# _fmt_loc
# ---------------------------------------------------------------------------


def test_fmt_loc_small():
    """Small numbers returned as plain string."""
    assert _fmt_loc(0) == "0"
    assert _fmt_loc(500) == "500"


def test_fmt_loc_thousands():
    """1 000+ formatted as X.Xk."""
    assert _fmt_loc(1_000) == "1.0k"
    assert _fmt_loc(15_000) == "15.0k"


def test_fmt_loc_millions():
    """1 000 000+ formatted as X.XM."""
    assert _fmt_loc(1_000_000) == "1.0M"
    assert _fmt_loc(2_500_000) == "2.5M"


# ---------------------------------------------------------------------------
# extract_costs_from_text — basic single-table parsing
# ---------------------------------------------------------------------------


def test_extract_basic_step_table():
    """Parse a single per-step cost table correctly."""
    cost, ins, dl, in_tok, out_tok, info = extract_costs_from_text(STEP_TABLE_1)
    assert cost == pytest.approx(1.23)
    assert ins == 42
    assert dl == 10
    assert in_tok == 10_000
    assert out_tok == 2_000
    assert info == pytest.approx(1_500.0)


def test_extract_cost_bold_only():
    """Only bold **$X.XX** values are counted as per-step costs."""
    text = "| **Cost** | **$2.50** |"
    cost, *_ = extract_costs_from_text(text)
    assert cost == pytest.approx(2.50)


def test_extract_bare_cost_ignored():
    """Bare $X.XX (cumulative format) must NOT be counted."""
    text = "| Cumulative cost | $5.00 |"
    cost, *_ = extract_costs_from_text(text)
    assert cost == 0.0


def test_extract_cumulative_labels_ignored():
    """Cumulative table labels (Cumulative input / info / LOC) must not be double-counted."""
    cumulative_block = """\
### 📊 Feature total (2 steps)

| Metric | Value |
|--------|-------|
| Cumulative LOC | ~52 (estimate) |
| Cumulative info | 2.3 Kbit |
| Cumulative input | 15.5K tokens |
| Cumulative output | 3.0K tokens |
| Cumulative cost | $1.73 |
"""
    cost, ins, dl, in_tok, out_tok, info = extract_costs_from_text(cumulative_block)
    assert cost == 0.0
    assert ins == 0
    assert dl == 0
    assert in_tok == 0
    assert out_tok == 0
    assert info == 0.0


def test_extract_multiple_tables():
    """Multiple per-step tables in one body are all summed."""
    text = STEP_TABLE_1 + "\n" + STEP_TABLE_2
    cost, ins, dl, in_tok, out_tok, info = extract_costs_from_text(text)
    assert cost == pytest.approx(1.73)
    assert ins == 42 + 20
    assert dl == 10 + 5
    assert in_tok == 10_000 + 5_500
    assert out_tok == 2_000 + 1_000
    assert info == pytest.approx(1_500.0 + 800.0)


def test_extract_mbit_info():
    """Info in Mbit is correctly converted to bits."""
    text = "| Info | 1.0 Mbit |"
    _, _, _, _, _, info = extract_costs_from_text(text)
    assert info == pytest.approx(1_000_000.0)


def test_extract_kbit_info():
    """Info in Kbit is correctly converted to bits."""
    text = "| Info | 2.5 Kbit |"
    _, _, _, _, _, info = extract_costs_from_text(text)
    assert info == pytest.approx(2_500.0)


def test_extract_mtoken_input():
    """Input tokens in M suffix are correctly scaled."""
    text = "| Input | 1.5M tokens |"
    _, _, _, in_tok, _, _ = extract_costs_from_text(text)
    assert in_tok == 1_500_000


def test_extract_no_deletions():
    """Diff with no deletions does not crash; deletions = 0."""
    text = "| Diff | 1 file changed, 5 insertions(+) |"
    _, ins, dl, _, _, _ = extract_costs_from_text(text)
    assert ins == 5
    assert dl == 0


def test_extract_no_insertions():
    """Diff with no insertions does not crash; insertions = 0."""
    text = "| Diff | 1 file changed, 3 deletions(-) |"
    _, ins, dl, _, _, _ = extract_costs_from_text(text)
    assert ins == 0
    assert dl == 3


def test_extract_empty_text():
    """Empty text returns all zeros."""
    cost, ins, dl, in_tok, out_tok, info = extract_costs_from_text("")
    assert cost == 0.0
    assert ins == 0
    assert dl == 0
    assert in_tok == 0
    assert out_tok == 0
    assert info == 0.0


def test_extract_malformed_table():
    """Malformed or partial table does not raise; unrecognised rows are skipped."""
    malformed = """\
### 💰 Cost
| Metric | Value |
| **Cost** | **$0.99** |
| Input | not-a-number tokens |
| Diff | broken |
"""
    cost, ins, dl, in_tok, out_tok, info = extract_costs_from_text(malformed)
    # Cost is extracted; tokens and diff gracefully skipped
    assert cost == pytest.approx(0.99)
    assert ins == 0
    assert dl == 0
    assert in_tok == 0
    assert out_tok == 0


def test_extract_mixed_per_step_and_cumulative():
    """Text containing both per-step and cumulative tables only counts per-step values."""
    text = STEP_TABLE_1 + "\n" + CUMULATIVE_TABLE
    cost, ins, dl, in_tok, out_tok, info = extract_costs_from_text(text)
    # Only values from STEP_TABLE_1 should be counted
    assert cost == pytest.approx(1.23)
    assert ins == 42
    assert dl == 10
    assert in_tok == 10_000
    assert out_tok == 2_000
    assert info == pytest.approx(1_500.0)


# ---------------------------------------------------------------------------
# compute_cumulative_table — helpers for mocking subprocess.run
# ---------------------------------------------------------------------------


def _ok(stdout: str):
    """Return a mock subprocess.CompletedProcess with returncode=0."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    return m


def _err():
    """Return a mock subprocess.CompletedProcess with returncode=1."""
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    return m


# ---------------------------------------------------------------------------
# compute_cumulative_table — early-return cases
# ---------------------------------------------------------------------------


def test_cumulative_empty_repo_and_number():
    """Returns '' immediately when repo or number is empty."""
    assert compute_cumulative_table("", "1", 1.0, 1000, 500) == ""
    assert compute_cumulative_table("owner/repo", "", 1.0, 1000, 500) == ""


def test_cumulative_first_step_no_prior_tables():
    """Returns '' when there are no prior cost tables (this is the first step)."""
    # The issue body and comments contain no ### 💰 Cost headers
    empty_body = "Just a plain issue body with no cost table.\n"
    empty_comments = ""

    with patch("subprocess.run") as mock_run:
        # Not a PR (pull_request check returns empty)
        mock_run.side_effect = [
            _ok(empty_body),    # _fetch_comments: issue body
            _ok(empty_comments),  # _fetch_comments: comments
            _err(),              # _find_linked_issue: not a PR
        ]
        result = compute_cumulative_table("owner/repo", "42", 1.23, 10000, 2000)

    assert result == ""


def test_cumulative_one_prior_step_returns_table():
    """With one prior step table, total steps = 2 → cumulative table returned."""
    # Prior comment has exactly one ### 💰 Cost table
    prior_comment = STEP_TABLE_1

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),             # issue body (no table)
            _ok(prior_comment),  # comments (one table)
            _err(),              # not a PR
        ]
        result = compute_cumulative_table(
            "owner/repo", "42",
            current_cost=0.50,
            current_input_tokens=5_500,
            current_output_tokens=1_000,
            current_loc=25,
            current_info_bits=800.0,
        )

    assert result != ""
    assert "### 📊 Feature total (2 steps)" in result
    assert "$1.73" in result  # 1.23 + 0.50


# ---------------------------------------------------------------------------
# compute_cumulative_table — aggregation math
# ---------------------------------------------------------------------------


def test_cumulative_cost_math():
    """Cumulative cost is sum of prior + current."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(STEP_TABLE_1),  # prior: $1.23
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.77,
            current_input_tokens=0,
            current_output_tokens=0,
        )
    assert "$2.00" in result


def test_cumulative_loc_math():
    """Cumulative LOC = prior (ins+del) + current_loc."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(STEP_TABLE_1),  # 42 ins + 10 del = 52 prior
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.10,
            current_input_tokens=0,
            current_output_tokens=0,
            current_loc=8,       # 52 + 8 = 60
        )
    assert "60" in result  # ~60 (estimate)


def test_cumulative_info_bits_math():
    """Cumulative info = prior_info + current_info_bits."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(STEP_TABLE_1),  # 1500 bits prior
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.10,
            current_input_tokens=0,
            current_output_tokens=0,
            current_info_bits=500.0,  # 1500 + 500 = 2000 = 2.0 Kbit
        )
    assert "2.0 Kbit" in result


def test_cumulative_token_math():
    """Cumulative input and output tokens are summed correctly."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(STEP_TABLE_1),  # 10K input, 2K output
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.10,
            current_input_tokens=5_000,
            current_output_tokens=1_000,
        )
    assert "15K" in result   # 10K + 5K input
    assert "3.0K" in result  # 2K + 1K output


def test_cumulative_three_steps():
    """Three prior steps are all aggregated."""
    two_tables = STEP_TABLE_1 + "\n" + STEP_TABLE_2  # $1.23 + $0.50 = $1.73

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(two_tables),
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.27,
            current_input_tokens=0,
            current_output_tokens=0,
        )
    assert "### 📊 Feature total (3 steps)" in result
    assert "$2.00" in result  # 1.73 + 0.27


def test_cumulative_zero_cost_returns_empty():
    """Returns '' when cumulative cost is zero (nothing meaningful to show)."""
    table_zero_cost = """\
### 💰 Cost
| **Cost** | **$0.00** |
"""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(table_zero_cost),
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.0,
            current_input_tokens=0,
            current_output_tokens=0,
        )
    assert result == ""


# ---------------------------------------------------------------------------
# compute_cumulative_table — PR-with-linked-issue traversal
# ---------------------------------------------------------------------------


def _make_pr_body(linked_issue: str, keyword: str = "Fixes") -> str:
    return f"This PR {keyword} #{linked_issue}\n\nSome description."


def test_cumulative_pr_linked_issue_via_fixes():
    """When called with a PR number, follows Fixes #N to aggregate the linked issue."""
    pr_body = _make_pr_body("100", "Fixes")
    # PR itself has no prior cost table
    # Linked issue #100 has one prior cost table
    linked_issue_text = STEP_TABLE_1  # $1.23, 10K in, 2K out, 52 loc, 1500 info

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            # _fetch_comments(repo, "42") — the PR
            _ok(pr_body),         # PR body
            _ok(""),              # PR comments (none with tables)
            # _find_linked_issue(repo, "42", text)
            _ok("yes"),           # pull_request key present → is a PR
            # body text already has "Fixes #100"
            # _fetch_comments(repo, "100") — the linked issue
            _ok(linked_issue_text),  # linked issue body (has the table)
            _ok(""),                 # linked issue comments
        ]
        result = compute_cumulative_table(
            "owner/repo", "42",
            current_cost=0.50,
            current_input_tokens=5_500,
            current_output_tokens=1_000,
            current_loc=25,
            current_info_bits=800.0,
        )

    assert result != ""
    assert "### 📊 Feature total (2 steps)" in result
    assert "$1.73" in result


def test_cumulative_pr_linked_issue_via_closes():
    """Closes #N is also recognized as a linked-issue keyword."""
    pr_body = _make_pr_body("200", "Closes")
    linked_issue_text = STEP_TABLE_2  # $0.50

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(pr_body),
            _ok(""),
            _ok("yes"),           # is a PR
            _ok(linked_issue_text),
            _ok(""),
        ]
        result = compute_cumulative_table(
            "owner/repo", "55",
            current_cost=0.10,
            current_input_tokens=0,
            current_output_tokens=0,
        )

    assert "$0.60" in result  # 0.50 + 0.10


def test_cumulative_pr_linked_issue_via_resolves():
    """Resolves #N is also recognized as a linked-issue keyword."""
    pr_body = _make_pr_body("300", "Resolves")
    linked_issue_text = STEP_TABLE_2  # $0.50

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(pr_body),
            _ok(""),
            _ok("yes"),
            _ok(linked_issue_text),
            _ok(""),
        ]
        result = compute_cumulative_table(
            "owner/repo", "55",
            current_cost=0.10,
            current_input_tokens=0,
            current_output_tokens=0,
        )

    assert "$0.60" in result


def test_cumulative_pr_no_linked_issue():
    """PR without a Fixes/Closes/Resolves link only scans the PR thread."""
    pr_body = "This PR adds a feature.\n"

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(pr_body),
            _ok(STEP_TABLE_1),  # one prior table in PR comments
            _ok("yes"),          # is a PR
            # No linked issue found → title check
            _ok("Some unrelated title"),  # PR title (no Fixes/Closes)
            # _find_linked_issue returns None → no further fetch
        ]
        result = compute_cumulative_table(
            "owner/repo", "77",
            current_cost=0.10,
            current_input_tokens=0,
            current_output_tokens=0,
        )

    # One prior table → total 2 steps → cumulative produced
    assert "### 📊 Feature total (2 steps)" in result


def test_cumulative_not_a_pr_skips_linked_issue_lookup():
    """For a plain issue (not a PR), _find_linked_issue returns None immediately."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),             # issue body
            _ok(STEP_TABLE_1),  # issue comments
            _err(),              # pull_request check: empty → not a PR
        ]
        result = compute_cumulative_table(
            "owner/repo", "99",
            current_cost=0.20,
            current_input_tokens=0,
            current_output_tokens=0,
        )

    # One prior table → total 2 steps
    assert "### 📊 Feature total (2 steps)" in result
    # Should NOT have fetched linked issue (only 3 subprocess.run calls)
    assert mock_run.call_count == 3


# ---------------------------------------------------------------------------
# compute_cumulative_table — output format
# ---------------------------------------------------------------------------


def test_cumulative_table_format_sections():
    """Cumulative table contains expected section header and metric rows."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(STEP_TABLE_1),
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.50,
            current_input_tokens=5_500,
            current_output_tokens=1_000,
            current_loc=25,
            current_info_bits=800.0,
        )

    lines = result.splitlines()
    assert lines[0].startswith("### 📊 Feature total")
    assert any("Cumulative cost" in l for l in lines)
    assert any("Cumulative input" in l for l in lines)
    assert any("Cumulative output" in l for l in lines)
    assert any("Cumulative LOC" in l for l in lines)
    assert any("Cumulative info" in l for l in lines)
    assert any("Cumulative LOC/$" in l for l in lines)
    assert any("Cumulative info/$" in l for l in lines)


def test_cumulative_omits_zero_loc_rows():
    """When there is no LOC data, the LOC and LOC/$ rows are omitted."""
    # STEP_TABLE_1 has LOC; create a table with no diff info
    no_loc_table = """\
### 💰 Cost

| Metric | Value |
|--------|-------|
| Input | 5.0K tokens |
| Output | 1.0K tokens |
| **Cost** | **$0.50** |
"""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _ok(""),
            _ok(no_loc_table),
            _err(),
        ]
        result = compute_cumulative_table(
            "owner/repo", "10",
            current_cost=0.10,
            current_input_tokens=1_000,
            current_output_tokens=500,
            current_loc=0,
            current_info_bits=0.0,
        )

    assert result != ""
    assert "Cumulative LOC" not in result
    assert "Cumulative info" not in result


def test_cumulative_fetch_failure_graceful():
    """If _fetch_comments raises, compute_cumulative_table returns '' gracefully."""
    with patch("subprocess.run", side_effect=Exception("gh not found")):
        result = compute_cumulative_table(
            "owner/repo", "42",
            current_cost=1.0,
            current_input_tokens=1000,
            current_output_tokens=500,
        )
    # Exception in subprocess is caught inside _fetch_comments; no tables found → ''
    assert result == ""
