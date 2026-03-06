"""Tests for cost parsing functions.

- parse_cost_from_comment: bash function in tests/e2e.sh for cost aggregation

The function is extracted from its source file at test time, so tests
always exercise the actual code that runs in CI.
"""

import re
import subprocess
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parent.parent


# --- parse_cost_from_comment (bash function in e2e.sh) ---


@pytest.fixture(scope="module")
def parse_cost_from_comment():
    """Return a callable that invokes parse_cost_from_comment from e2e.sh."""
    e2e_path = WORKSPACE / "tests" / "e2e.sh"

    # Extract just the function definition from e2e.sh
    with open(e2e_path) as f:
        content = f.read()

    # Find the function definition
    match = re.search(
        r"(parse_cost_from_comment\(\) \{.*?\n\})",
        content,
        re.DOTALL,
    )
    assert match, "Could not find parse_cost_from_comment function in e2e.sh"
    func_def = match.group(1)

    def _parse(body: str) -> str:
        # Define the function and call it
        script = f"""
{func_def}
parse_cost_from_comment "$1"
"""
        result = subprocess.run(
            ["bash", "-c", script, "_", body],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return _parse


def test_parse_cost_typical_comment(parse_cost_from_comment):
    """Parse cost from a typical Cost Summary comment."""
    body = """### 💰 Cost Summary

**Model:** `claude-small` (anthropic/claude-3-haiku-20240307)
**Mode:** resolve

| Metric | Value |
|--------|-------|
| Agent outcome | ✓ Completed |
| Iterations | 5 / 50 |
| Elapsed time | 2m 30s |
| Input tokens | 10000 |
| Output tokens | 5000 |
| Total tokens | 15000 |
| **Estimated cost** | **$1.23** |

_Cost is estimated based on token usage and may vary from actual billing._"""
    assert parse_cost_from_comment(body) == "1.23"


def test_parse_cost_zero_cost(parse_cost_from_comment):
    """Parse cost when cost is $0.00."""
    body = "| **Estimated cost** | **$0.00** |"
    assert parse_cost_from_comment(body) == "0.00"


def test_parse_cost_large_amount(parse_cost_from_comment):
    """Parse cost with larger dollar amounts."""
    body = "| **Estimated cost** | **$12.34** |"
    assert parse_cost_from_comment(body) == "12.34"


def test_parse_cost_no_match(parse_cost_from_comment):
    """Return 0.00 when no cost pattern is found."""
    body = "This comment has no cost information"
    assert parse_cost_from_comment(body) == "0.00"


def test_parse_cost_empty_body(parse_cost_from_comment):
    """Return 0.00 for empty body."""
    assert parse_cost_from_comment("") == "0.00"


def test_parse_cost_multiple_costs_takes_first(parse_cost_from_comment):
    """When multiple cost patterns exist, take the first one."""
    body = """| **Estimated cost** | **$1.00** |
| **Estimated cost** | **$2.00** |"""
    assert parse_cost_from_comment(body) == "1.00"
