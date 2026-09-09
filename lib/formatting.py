"""Shared formatting helpers for cost tables and metrics.

This module is the single source of truth for all cost/metric formatting
functions used across lib/resolve.py, lib/workshop.py, lib/cumulative_cost.py,
and workflow Python heredocs in remote-dev-bot.yml.
"""

import gzip


def _fmt_tok(n: int) -> str:
    """Format token count: 42500 → '42.5K', 1500000 → '1.5M'."""
    n = int(n)
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{round(v)}M" if v >= 10 else f"{round(v, 1)}M"
    elif n >= 1_000:
        v = n / 1_000
        return f"{round(v)}K" if v >= 10 else f"{round(v, 1)}K"
    return str(n)


def _fmt_ela(s: int) -> str:
    """Format elapsed seconds: 90 → '1m 30s', 45 → '45s'."""
    s = int(s)
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def _fmt_bpd(text, cost: float) -> str:
    """Format bits-per-dollar from text and cost. Returns 'N/A' if cost <= 0."""
    if cost <= 0:
        return 'N/A'
    data = text.encode('utf-8') if isinstance(text, str) else text
    bpd = (len(gzip.compress(data)) * 8) / cost  # bits per dollar
    if bpd >= 1_000_000:
        return f"{bpd / 1_000_000:.1f} Mbit/$"
    return f"{bpd / 1_000:.1f} Kbit/$"


def _fmt_loc(n: int) -> str:
    """Format LOC count: 1500 → '1.5k', 1500000 → '1.5M'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fmt_info(text) -> 'str | None':
    """Format compressed size of text in Kbit/Mbit. Returns None if text is empty."""
    if not text:
        return None
    data = text.encode('utf-8') if isinstance(text, str) else text
    b = len(gzip.compress(data)) * 8
    if b >= 1_000_000:
        return f"{b / 1_000_000:.1f} Mbit"
    return f"{b / 1_000:.1f} Kbit"


TABLE_HEADER: list = [
    '---',
    '',
    '### 💰 Cost',
    '',
    '| Metric | Value |',
    '|--------|-------|',
]


def _model_rates(model: str):
    """Return (list_input_rate, cache_read_rate, cache_write_rate) for the model,
    or (0, 0, 0) if LiteLLM doesn't know the model. Rates are per-token dollars.

    Falls back to standard Anthropic ratios (read = 0.1× input, write = 1.25× input)
    if LiteLLM has the input rate but not the cache rates.
    """
    try:
        import litellm
        info = litellm.get_model_info(model)
    except Exception:
        return (0.0, 0.0, 0.0)
    list_input = float(info.get("input_cost_per_token") or 0)
    if not list_input:
        return (0.0, 0.0, 0.0)
    cache_read = float(info.get("cache_read_input_token_cost") or 0) or (list_input * 0.1)
    cache_write = float(info.get("cache_creation_input_token_cost") or 0) or (list_input * 1.25)
    return (list_input, cache_read, cache_write)


def build_cache_savings_summary(usage_path: str = "/tmp/llm_usage.json",
                                 model: 'str | None' = None) -> str:
    """Build a cache savings summary string for the agent status log.

    Reads cache_read_tokens / cache_creation_tokens from usage_path (written
    by write_usage in resolve / reconcile) and estimates savings against the
    model's list input rate from LiteLLM's pricing table — NOT against the
    blended post-cache cost (which was the bug fixed in this commit:
    the old formula divided actual_cost by total_tokens, producing a rate
    that was already discounted by caching AND diluted by output tokens,
    leading to estimates 3-4× too low).

    Returns '' if cache was not used or the file is missing.
    """
    import json

    try:
        with open(usage_path) as f:
            d = json.load(f)
    except Exception:
        return ""

    cache_read = int(d.get("cache_read_tokens", 0) or 0)
    cache_write = int(d.get("cache_creation_tokens", 0) or 0)
    if cache_read == 0 and cache_write == 0:
        return ""

    parts = []
    if cache_read > 0:
        parts.append(f"{_fmt_tok(cache_read)} tokens read from cache")
    if cache_write > 0:
        parts.append(f"{_fmt_tok(cache_write)} tokens written to cache")

    if model:
        list_input, read_rate, write_rate = _model_rates(model)
        if list_input > 0:
            # Reads: saved (list_input - read_rate) per token (default 0.9× list).
            # Writes: cost extra (write_rate - list_input) per token (default 0.25× list).
            read_savings = cache_read * (list_input - read_rate)
            write_overhead = cache_write * (write_rate - list_input)
            net = read_savings - write_overhead
            if net > 0:
                parts.append(f"~${round(net, 2):.2f} saved")

    return f"**Cache:** {', '.join(parts)}"


def build_distillation_summary(pre_tokens: int, post_tokens: int,
                                iterations: int, model: 'str | None' = None) -> str:
    """Build a distillation savings summary for the agent status log.

    Distillation reduces tokens-per-iteration by (pre - post). After iteration 1,
    those tokens sit in the prompt cache, so the per-iter saving from iter 2
    onward is at the full input rate minus the cache-read rate (i.e., they
    would have been cached too without distillation).

    To avoid overstating savings, we apply the cache-read rate for iters 2..N
    (the previous formula used the full input rate, overstating by ~10× for
    long runs since the alternative — sending more tokens every iter — would
    also have been cached).
    """
    if pre_tokens <= 0 or post_tokens <= 0 or iterations <= 0:
        return ""
    tokens_per_iter = pre_tokens - post_tokens
    if tokens_per_iter <= 0:
        return ""

    summary = (
        f"**Distillation:** {_fmt_tok(pre_tokens)} → {_fmt_tok(post_tokens)} tokens "
        f"({_fmt_tok(tokens_per_iter)} saved/iter × {iterations} iters"
    )

    if model:
        list_input, read_rate, _ = _model_rates(model)
        if list_input > 0:
            # First iteration would have paid full rate; subsequent iters would
            # have been cache hits at read_rate. Distillation lets us avoid
            # sending these tokens at all.
            cost_saved = tokens_per_iter * (list_input + max(iterations - 1, 0) * read_rate)
            if cost_saved > 0:
                summary += f" = ~${round(cost_saved, 2):.2f} saved"

    summary += ")"
    return summary
