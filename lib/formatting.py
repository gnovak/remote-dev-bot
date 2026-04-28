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
