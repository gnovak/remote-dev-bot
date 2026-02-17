"""Tests for lib/cost.py — cost calculation and formatting."""

import json
import os
import tempfile

import pytest

from lib.cost import (
    MODEL_PRICING,
    calculate_cost,
    format_cost_comment,
    parse_openhands_output,
)


# --- calculate_cost ---


def test_calculate_cost_anthropic_sonnet():
    """Test cost calculation for Claude Sonnet."""
    # 1M input tokens at $3.00, 1M output tokens at $15.00
    cost = calculate_cost("anthropic/claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.00)


def test_calculate_cost_anthropic_haiku():
    """Test cost calculation for Claude Haiku (cheap model)."""
    # 1M input at $0.25, 1M output at $1.25
    cost = calculate_cost("anthropic/claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(1.50)


def test_calculate_cost_anthropic_opus():
    """Test cost calculation for Claude Opus (expensive model)."""
    # 1M input at $15.00, 1M output at $75.00
    cost = calculate_cost("anthropic/claude-opus-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(90.00)


def test_calculate_cost_openai_nano():
    """Test cost calculation for GPT-5 Nano."""
    cost = calculate_cost("openai/gpt-5-nano", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75)


def test_calculate_cost_gemini_flash():
    """Test cost calculation for Gemini Flash."""
    cost = calculate_cost("gemini/gemini-2.5-flash", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75)


def test_calculate_cost_small_usage():
    """Test cost calculation for typical small usage."""
    # 10K input, 2K output on Sonnet
    cost = calculate_cost("anthropic/claude-sonnet-4-5", 10_000, 2_000)
    # (10000/1M * 3.00) + (2000/1M * 15.00) = 0.03 + 0.03 = 0.06
    assert cost == pytest.approx(0.06)


def test_calculate_cost_zero_tokens():
    """Test cost calculation with zero tokens."""
    cost = calculate_cost("anthropic/claude-sonnet-4-5", 0, 0)
    assert cost == 0.0


def test_calculate_cost_unknown_model():
    """Test that unknown models return None."""
    cost = calculate_cost("unknown/model", 1000, 1000)
    assert cost is None


def test_all_models_have_pricing():
    """Verify all expected models have pricing defined."""
    expected_models = [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-opus-4-5",
        "openai/gpt-5-nano",
        "openai/gpt-5.1-codex-mini",
        "openai/gpt-5.2-codex",
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-pro",
    ]
    for model in expected_models:
        assert model in MODEL_PRICING, f"Missing pricing for {model}"
        assert "input" in MODEL_PRICING[model]
        assert "output" in MODEL_PRICING[model]


# --- parse_openhands_output ---


def test_parse_openhands_output_with_metrics():
    """Test parsing output.jsonl with accumulated metrics."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Write some events followed by metrics
        f.write(json.dumps({"type": "action", "action": "run"}) + "\n")
        f.write(
            json.dumps(
                {
                    "type": "observation",
                    "metrics": {
                        "accumulated_cost": 0.0523,
                        "accumulated_input_tokens": 15000,
                        "accumulated_output_tokens": 3000,
                    },
                }
            )
            + "\n"
        )
        path = f.name

    try:
        result = parse_openhands_output(path)
        assert result["input_tokens"] == 15000
        assert result["output_tokens"] == 3000
        assert result["total_cost"] == pytest.approx(0.0523)
        assert result["source"] == "openhands_metrics"
    finally:
        os.unlink(path)


def test_parse_openhands_output_missing_file():
    """Test parsing non-existent file."""
    result = parse_openhands_output("/nonexistent/path/output.jsonl")
    assert "error" in result


def test_parse_openhands_output_empty_file():
    """Test parsing empty file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        result = parse_openhands_output(path)
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
    finally:
        os.unlink(path)


def test_parse_openhands_output_with_llm_metrics():
    """Test parsing output.jsonl with per-call llm_metrics."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(
            json.dumps({"llm_metrics": {"prompt_tokens": 1000, "completion_tokens": 200}})
            + "\n"
        )
        f.write(
            json.dumps({"llm_metrics": {"prompt_tokens": 1500, "completion_tokens": 300}})
            + "\n"
        )
        path = f.name

    try:
        result = parse_openhands_output(path)
        assert result["input_tokens"] == 2500
        assert result["output_tokens"] == 500
    finally:
        os.unlink(path)


def test_parse_openhands_output_with_model_info():
    """Test parsing output.jsonl that includes model info."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"extras": {"model": "anthropic/claude-sonnet-4-5"}}) + "\n")
        f.write(
            json.dumps({"llm_metrics": {"prompt_tokens": 10000, "completion_tokens": 2000}})
            + "\n"
        )
        path = f.name

    try:
        result = parse_openhands_output(path)
        assert result["model"] == "anthropic/claude-sonnet-4-5"
        assert result["input_tokens"] == 10000
        assert result["output_tokens"] == 2000
        # Should calculate cost based on model
        assert "total_cost" in result
        expected_cost = (10000 / 1_000_000 * 3.00) + (2000 / 1_000_000 * 15.00)
        assert result["total_cost"] == pytest.approx(expected_cost)
    finally:
        os.unlink(path)


# --- format_cost_comment ---


def test_format_cost_comment_basic():
    """Test basic cost comment formatting."""
    comment = format_cost_comment(
        model="anthropic/claude-sonnet-4-5",
        input_tokens=10000,
        output_tokens=2000,
        total_cost=0.06,
        mode="resolve",
        alias="claude-small",
    )

    assert "### 💰 Cost Summary" in comment
    assert "claude-small" in comment
    assert "anthropic/claude-sonnet-4-5" in comment
    assert "resolve" in comment
    assert "10,000" in comment
    assert "2,000" in comment
    assert "12,000" in comment
    assert "$0.0600" in comment


def test_format_cost_comment_no_cost():
    """Test cost comment when cost is unavailable."""
    comment = format_cost_comment(
        model="unknown/model",
        input_tokens=1000,
        output_tokens=500,
        total_cost=None,
        mode="design",
        alias="custom",
    )

    assert "pricing unavailable" in comment
    assert "1,000" in comment
    assert "500" in comment


def test_format_cost_comment_calculates_cost():
    """Test that format_cost_comment calculates cost if not provided."""
    comment = format_cost_comment(
        model="anthropic/claude-sonnet-4-5",
        input_tokens=100000,
        output_tokens=20000,
        mode="resolve",
        alias="claude-small",
    )

    # Should calculate: (100000/1M * 3.00) + (20000/1M * 15.00) = 0.30 + 0.30 = 0.60
    assert "$0.6000" in comment


def test_format_cost_comment_large_numbers():
    """Test formatting with large token counts."""
    comment = format_cost_comment(
        model="anthropic/claude-opus-4-5",
        input_tokens=1_500_000,
        output_tokens=500_000,
        mode="resolve",
        alias="claude-large",
    )

    assert "1,500,000" in comment
    assert "500,000" in comment
    assert "2,000,000" in comment
