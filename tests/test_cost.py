"""Tests for cost parsing functions.

- parse_litellm_logs: embedded in remote-dev-bot.yml's cost step
- parse_cost_from_comment: embedded in tests/e2e.sh for cost aggregation

Both functions are extracted from their source files at test time, so tests
always exercise the actual code that runs in CI.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

WORKSPACE = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def parse_litellm_logs():
    """Extract and return parse_litellm_logs from remote-dev-bot.yml's cost step."""
    with open(WORKSPACE / ".github/workflows/remote-dev-bot.yml") as f:
        workflow = yaml.safe_load(f)

    resolve_steps = workflow["jobs"]["resolve"]["steps"]
    cost_step = next(
        s for s in resolve_steps if s.get("name") == "Calculate and post cost"
    )

    run_text = cost_step["run"]
    match = re.search(r"python3 << 'PYEOF'\n(.*?)PYEOF", run_text, re.DOTALL)
    assert match, "Could not find PYEOF block in 'Calculate and post cost' step"

    python_code = match.group(1)
    # Keep only the function definition; stop before the file-I/O main body
    func_code = python_code.split("# Try OpenHands output")[0]

    ns = {}
    exec(func_code, ns)  # noqa: S102 — intentional, test-only
    return ns["parse_litellm_logs"]


# --- parse_litellm_logs ---


def test_empty_log(parse_litellm_logs):
    result = parse_litellm_logs("")
    assert result == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_cost": None,
        "call_count": 0,
    }


def test_single_call_tokens_in_root(parse_litellm_logs):
    entry = {"response_cost": 0.01, "prompt_tokens": 100, "completion_tokens": 50}
    result = parse_litellm_logs(json.dumps(entry))
    assert result["call_count"] == 1
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["total_cost"] == pytest.approx(0.01)


def test_single_call_tokens_in_metadata(parse_litellm_logs):
    """Tokens nested in metadata.usage_object are preferred over root fields."""
    entry = {
        "response_cost": 0.02,
        "metadata": {"usage_object": {"prompt_tokens": 200, "completion_tokens": 80}},
    }
    result = parse_litellm_logs(json.dumps(entry))
    assert result["call_count"] == 1
    assert result["input_tokens"] == 200
    assert result["output_tokens"] == 80
    assert result["total_cost"] == pytest.approx(0.02)


def test_multiple_calls_accumulate(parse_litellm_logs):
    entries = [
        {"response_cost": 0.01, "prompt_tokens": 100, "completion_tokens": 50},
        {"response_cost": 0.02, "prompt_tokens": 200, "completion_tokens": 100},
    ]
    log = " ".join(json.dumps(e) for e in entries)
    result = parse_litellm_logs(log)
    assert result["call_count"] == 2
    assert result["input_tokens"] == 300
    assert result["output_tokens"] == 150
    assert result["total_cost"] == pytest.approx(0.03)


def test_none_cost_treated_as_zero(parse_litellm_logs):
    """None response_cost is treated as 0, but the call is still counted."""
    entry = {"response_cost": None, "prompt_tokens": 100, "completion_tokens": 50}
    result = parse_litellm_logs(json.dumps(entry))
    assert result["call_count"] == 1
    assert result["total_cost"] == pytest.approx(0.0)


def test_none_tokens_treated_as_zero(parse_litellm_logs):
    """None token values are treated as 0."""
    entry = {"response_cost": 0.01, "prompt_tokens": None, "completion_tokens": None}
    result = parse_litellm_logs(json.dumps(entry))
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0


def test_malformed_json_skipped(parse_litellm_logs):
    """Malformed JSON fragments are skipped; valid entries are still counted."""
    valid = {"response_cost": 0.01, "prompt_tokens": 100, "completion_tokens": 50}
    log = f"not json at all {json.dumps(valid)} more garbage {{broken"
    result = parse_litellm_logs(log)
    assert result["call_count"] == 1
    assert result["input_tokens"] == 100


def test_non_matching_json_skipped(parse_litellm_logs):
    """JSON objects without response_cost are ignored."""
    noise = {"some_other": "data", "no_cost_here": True}
    valid = {"response_cost": 0.01, "prompt_tokens": 50, "completion_tokens": 25}
    log = json.dumps(noise) + " " + json.dumps(valid)
    result = parse_litellm_logs(log)
    assert result["call_count"] == 1
    assert result["input_tokens"] == 50


def test_total_cost_none_when_no_calls(parse_litellm_logs):
    """total_cost is None (not 0.0) when no matching calls are found."""
    log = json.dumps({"no_response_cost": True})
    result = parse_litellm_logs(log)
    assert result["total_cost"] is None
    assert result["call_count"] == 0


def test_log_with_surrounding_noise(parse_litellm_logs):
    """Realistic log: JSON objects embedded in non-JSON log lines."""
    valid = {"response_cost": 0.005, "prompt_tokens": 75, "completion_tokens": 30}
    log = (
        "2026-01-01 INFO LiteLLM cost tracking enabled\n"
        f"2026-01-01 INFO payload: {json.dumps(valid)}\n"
        "2026-01-01 INFO done\n"
    )
    result = parse_litellm_logs(log)
    assert result["call_count"] == 1
    assert result["total_cost"] == pytest.approx(0.005)


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
