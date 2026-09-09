"""Tests for cache and distillation savings helpers in lib/formatting.py.

These helpers compute the savings strings shown in the agent status log.
The previous formula in resolve.py used `cost / (input + output)` as a proxy
for the input rate, which produced estimates 3-4× too low because:
  - The numerator was the post-cache cost (already discounted)
  - The denominator mixed output tokens with input tokens

The new helpers use LiteLLM's list pricing (`input_cost_per_token` and the
explicit `cache_read_input_token_cost` / `cache_creation_input_token_cost`).
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.formatting import (
    build_cache_savings_summary,
    build_distillation_summary,
    _model_rates,
)


# Pricing fixture matching Claude Sonnet 4.6: $3/M input, $15/M output,
# $0.30/M cache reads, $3.75/M cache writes.
SONNET_PRICES = {
    "input_cost_per_token": 3e-6,
    "output_cost_per_token": 1.5e-5,
    "cache_read_input_token_cost": 3e-7,
    "cache_creation_input_token_cost": 3.75e-6,
}


def _write_usage(tmp_path, **kwargs):
    """Write a /tmp-style usage JSON file and return its path."""
    p = tmp_path / "llm_usage.json"
    p.write_text(json.dumps(kwargs))
    return str(p)


# ---------------------------------------------------------------------------
# _model_rates
# ---------------------------------------------------------------------------

class TestModelRates:
    def test_returns_zeros_for_unknown_model(self):
        # The patched get_model_info raises; helper must return zeros.
        with patch("litellm.get_model_info", side_effect=Exception("unknown")):
            assert _model_rates("nonsense/model") == (0.0, 0.0, 0.0)

    def test_returns_explicit_rates(self):
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            inp, read, write = _model_rates("anthropic/claude-sonnet-4-6")
        assert inp == 3e-6
        assert read == 3e-7
        assert write == 3.75e-6

    def test_falls_back_to_standard_ratios_when_cache_rates_missing(self):
        # Only input rate present — fallback to 0.1× / 1.25×
        with patch("litellm.get_model_info",
                   return_value={"input_cost_per_token": 3e-6}):
            inp, read, write = _model_rates("anthropic/claude-sonnet-4-6")
        assert inp == 3e-6
        assert read == pytest.approx(3e-7)
        assert write == pytest.approx(3.75e-6)


# ---------------------------------------------------------------------------
# build_cache_savings_summary
# ---------------------------------------------------------------------------

class TestCacheSavingsSummary:
    def test_empty_when_no_cache(self, tmp_path):
        path = _write_usage(tmp_path, cache_read_tokens=0, cache_creation_tokens=0)
        assert build_cache_savings_summary(path, "anthropic/claude-sonnet-4-6") == ""

    def test_empty_when_file_missing(self):
        assert build_cache_savings_summary("/nonexistent/file.json", "any/model") == ""

    def test_reads_only_with_savings(self, tmp_path):
        """497K cache reads on Sonnet → ~$1.34 saved (matches bridge-analysis run)."""
        path = _write_usage(tmp_path, cache_read_tokens=497_000, cache_creation_tokens=0)
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_cache_savings_summary(path, "anthropic/claude-sonnet-4-6")
        # 497_000 × (3e-6 - 3e-7) = 497_000 × 2.7e-6 = $1.3419 → round = $1.34
        assert "497K tokens read from cache" in out
        assert "$1.34 saved" in out

    def test_no_model_omits_savings(self, tmp_path):
        path = _write_usage(tmp_path, cache_read_tokens=497_000, cache_creation_tokens=0)
        out = build_cache_savings_summary(path, model=None)
        assert "497K tokens read from cache" in out
        assert "saved" not in out

    def test_writes_only_no_savings_estimate(self, tmp_path):
        path = _write_usage(tmp_path, cache_read_tokens=0, cache_creation_tokens=50_000)
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_cache_savings_summary(path, "anthropic/claude-sonnet-4-6")
        # Writes alone are a NET OVERHEAD, not savings — no $ figure shown.
        assert "50K tokens written to cache" in out
        assert "saved" not in out

    def test_reads_and_writes_net_savings(self, tmp_path):
        """Mixed reads and writes: read savings net out write overhead."""
        path = _write_usage(tmp_path,
                            cache_read_tokens=500_000,
                            cache_creation_tokens=100_000)
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_cache_savings_summary(path, "anthropic/claude-sonnet-4-6")
        # read_savings = 500_000 × 2.7e-6 = $1.35
        # write_overhead = 100_000 × 0.75e-6 = $0.075
        # net = $1.275 → round = $1.27 (banker's rounding) or $1.28
        import re
        m = re.search(r"\$([\d.]+) saved", out)
        assert m is not None
        assert float(m.group(1)) == pytest.approx(1.27, abs=0.02)

    def test_write_overhead_swamps_reads_no_savings(self, tmp_path):
        """If write overhead > read savings, omit the savings line."""
        path = _write_usage(tmp_path,
                            cache_read_tokens=1_000,
                            cache_creation_tokens=10_000_000)
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_cache_savings_summary(path, "anthropic/claude-sonnet-4-6")
        assert "saved" not in out


# ---------------------------------------------------------------------------
# build_distillation_summary
# ---------------------------------------------------------------------------

class TestDistillationSummary:
    def test_empty_when_no_savings(self):
        # post >= pre means distillation actually grew the context — bail.
        assert build_distillation_summary(100, 200, 10, None) == ""

    def test_empty_when_zero_iterations(self):
        assert build_distillation_summary(1000, 500, 0, None) == ""

    def test_basic_summary_no_model(self):
        out = build_distillation_summary(100_000, 20_000, 15, None)
        assert "100K" in out
        assert "20K" in out
        assert "80K saved/iter" in out
        assert "15 iters" in out
        assert "saved" not in out.split("saved/iter")[1]  # no cost figure

    def test_cost_savings_uses_cache_aware_formula(self):
        """The dominant cost saving is iter-1 (uncached) plus (N-1) cache hits.

        For 80K tokens × 15 iters on Sonnet:
          iter 1:  80_000 × $3e-6 = $0.24
          iters 2..15 (14 iters cached): 80_000 × $3e-7 × 14 = $0.336
          total = $0.576 → round = $0.58
        """
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_distillation_summary(100_000, 20_000, 15,
                                              "anthropic/claude-sonnet-4-6")
        assert "$0.58 saved" in out

    def test_single_iteration_pays_full_rate_only(self):
        """For a 1-iter run, only the uncached first-iter cost applies."""
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_distillation_summary(100_000, 20_000, 1,
                                              "anthropic/claude-sonnet-4-6")
        # 80_000 × $3e-6 = $0.24
        assert "$0.24 saved" in out

    def test_not_overstated_vs_naive_formula(self):
        """The new formula must produce significantly lower savings than the
        old (now-removed) formula which used full input rate every iter.

        Old: 80K × $3e-6 × 15 = $3.60
        New: $0.24 + 80K × $3e-7 × 14 = $0.576
        """
        with patch("litellm.get_model_info", return_value=SONNET_PRICES):
            out = build_distillation_summary(100_000, 20_000, 15,
                                              "anthropic/claude-sonnet-4-6")
        # Naive (incorrect) formula would have produced ~$3.60 — assert we're
        # well under that.
        import re
        m = re.search(r"\$([\d.]+) saved", out)
        assert m is not None
        assert float(m.group(1)) < 1.0
