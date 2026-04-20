"""Shared cumulative cost aggregation for remote-dev-bot.

Scans prior issue/PR comments for per-step cost tables (### 💰 Cost),
extracts metrics, and returns a cumulative summary table to append to
the current step's cost comment.

Usage from workflow Python heredoc:
    import sys; sys.path.insert(0, 'lib')
    from cumulative_cost import compute_cumulative_table
    cum = compute_cumulative_table(repo, number, cost, input_tokens, ...)
    if cum:
        _tbl.append('')
        _tbl.append(cum)
"""

import json
import re
import subprocess


def _fmt_tok(n: int) -> str:
    n = int(n)
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{round(v)}M" if v >= 10 else f"{round(v, 1)}M"
    elif n >= 1_000:
        v = n / 1_000
        return f"{round(v)}K" if v >= 10 else f"{round(v, 1)}K"
    return str(n)


def _fmt_loc(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def extract_costs_from_text(text: str) -> tuple:
    """Extract per-step cost metrics from text containing cost tables.

    Returns (cost, loc_ins, loc_del, input_tokens, output_tokens, info_bits).

    IMPORTANT: This function intentionally matches ONLY per-step format:
      - Cost:   **$X.XX**  (bold)     — cumulative uses bare $X.XX
      - Tokens: | Input |             — cumulative uses | Cumulative input |
      - Info:   | Info |              — cumulative uses | Cumulative info |
      - Diff:   | Diff |             — cumulative uses | Cumulative LOC |
    Do NOT change the cumulative table labels to match per-step labels,
    or future runs will double-count.
    """
    total_cost = 0.0
    total_ins = 0
    total_del = 0
    total_in_tok = 0
    total_out_tok = 0
    total_info_bits = 0.0

    # Bold cost values: **$X.XX** — only in per-step tables
    for m in re.finditer(r'\*\*\$([0-9]+\.[0-9]+)\*\*', text):
        total_cost += float(m.group(1))

    # LOC from Diff rows: "N insertions(+), M deletions(-)"
    for m in re.finditer(r'\| Diff \|[^|]*\|', text):
        diff_cell = m.group(0)
        ins = re.search(r'(\d+) insertion', diff_cell)
        if ins:
            total_ins += int(ins.group(1))
        dl = re.search(r'(\d+) deletion', diff_cell)
        if dl:
            total_del += int(dl.group(1))

    # Token counts: | Input | 42.5K tokens |  (NOT | Cumulative input |)
    for m in re.finditer(r'\| Input \| ([0-9.]+)([KM]?) tokens \|', text):
        v = float(m.group(1))
        sfx = m.group(2)
        if sfx == 'K':
            v *= 1000
        elif sfx == 'M':
            v *= 1_000_000
        total_in_tok += int(v)

    for m in re.finditer(r'\| Output \| ([0-9.]+)([KM]?) tokens \|', text):
        v = float(m.group(1))
        sfx = m.group(2)
        if sfx == 'K':
            v *= 1000
        elif sfx == 'M':
            v *= 1_000_000
        total_out_tok += int(v)

    # Info bits: | Info | 1.2 Mbit |  (NOT | Cumulative info |)
    for m in re.finditer(r'\| Info \| ([0-9.]+) (Kbit|Mbit) \|', text):
        v = float(m.group(1))
        if m.group(2) == 'Mbit':
            v *= 1_000_000
        else:
            v *= 1_000
        total_info_bits += v

    return total_cost, total_ins, total_del, total_in_tok, total_out_tok, total_info_bits


def _fetch_comments(repo: str, number: str) -> str:
    """Fetch all comments + body for an issue/PR. Returns concatenated text."""
    text_parts = []

    # Fetch the issue/PR body
    try:
        r = subprocess.run(
            ['gh', 'api', f'repos/{repo}/issues/{number}', '--jq', '.body // ""'],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            text_parts.append(r.stdout)
    except Exception:
        pass

    # Fetch all comments (paginated)
    try:
        r = subprocess.run(
            ['gh', 'api', f'repos/{repo}/issues/{number}/comments',
             '--paginate', '--jq', '.[].body'],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            text_parts.append(r.stdout)
    except Exception:
        pass

    return '\n'.join(text_parts)


def _find_linked_issue(repo: str, number: str, text: str) -> str | None:
    """If number is a PR, find the linked issue via Fixes/Closes/Resolves #N.

    Also checks the PR title via API.
    """
    # Check if this is a PR (has pull_request key)
    try:
        r = subprocess.run(
            ['gh', 'api', f'repos/{repo}/issues/{number}',
             '--jq', '.pull_request // empty'],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None  # Not a PR
    except Exception:
        return None

    # It's a PR — look for linked issue in body text
    m = re.search(r'(?:Fixes|Closes|Resolves)\s+#([0-9]+)', text, re.IGNORECASE)
    if m:
        return m.group(1)

    # Also check the PR title
    try:
        r = subprocess.run(
            ['gh', 'api', f'repos/{repo}/issues/{number}', '--jq', '.title // ""'],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            m = re.search(r'(?:Fixes|Closes|Resolves)\s+#([0-9]+)',
                           r.stdout, re.IGNORECASE)
            if m:
                return m.group(1)
    except Exception:
        pass

    return None


def compute_cumulative_table(
    repo: str,
    number: str,
    current_cost: float,
    current_input_tokens: int,
    current_output_tokens: int,
    current_loc: int = 0,
    current_info_bits: float = 0,
) -> str:
    """Scan prior comments for cost tables, add current step, return cumulative markdown.

    Returns the cumulative table as a markdown string, or '' if fewer than 2 total steps.
    The returned string should be appended to the per-step cost table.

    Args:
        repo: GitHub repository (owner/name)
        number: Issue or PR number to scan and post to
        current_cost: This step's cost in dollars
        current_input_tokens: This step's input token count
        current_output_tokens: This step's output token count
        current_loc: This step's LOC changed (insertions + deletions)
        current_info_bits: This step's compressed diff size in bits
    """
    if not repo or not number:
        return ''

    # Collect all text to scan
    all_text = _fetch_comments(repo, number)

    # If this is a PR, also scan the linked issue
    linked_issue = _find_linked_issue(repo, number, all_text)
    if linked_issue:
        issue_text = _fetch_comments(repo, linked_issue)
        all_text += '\n' + issue_text

    # Count prior cost tables
    num_prior = len(re.findall(r'### 💰 Cost', all_text))
    if num_prior == 0:
        return ''  # This is the first step — no cumulative needed

    # Extract prior costs
    prior_cost, prior_ins, prior_del, prior_in_tok, prior_out_tok, prior_info = \
        extract_costs_from_text(all_text)

    # Compute cumulative (prior + current)
    cum_steps = num_prior + 1
    cum_cost = prior_cost + current_cost
    cum_loc = (prior_ins + prior_del) + current_loc
    cum_in_tok = prior_in_tok + current_input_tokens
    cum_out_tok = prior_out_tok + current_output_tokens
    cum_info = prior_info + current_info_bits

    if cum_cost <= 0:
        return ''

    # Build cumulative table
    # FORMATTING RULES (anti-double-counting):
    #   - Use "Cumulative cost" (not "Cost" or "**Cost**")
    #   - Use bare $X.XX (not **$X.XX**)
    #   - Use "Cumulative input/output/info" (not "Input"/"Output"/"Info")
    #   - Use "Cumulative LOC" (not "Diff")
    lines = [
        f'### \U0001f4ca Feature total ({cum_steps} steps)',
        '',
        '| Metric | Value |',
        '|--------|-------|',
        f'| Cumulative cost | ${cum_cost:.2f} |',
    ]

    if cum_loc > 0:
        lines.append(f'| Cumulative LOC | ~{_fmt_loc(cum_loc)} (estimate) |')
        cum_loc_per_dollar = int(cum_loc / cum_cost) if cum_cost > 0 else 0
        if cum_loc_per_dollar > 0:
            lines.append(f'| Cumulative LOC/$ | ~{_fmt_loc(cum_loc_per_dollar)} loc/$ |')

    if cum_info > 0:
        info_str = (f"{cum_info / 1_000_000:.1f} Mbit"
                    if cum_info >= 1_000_000
                    else f"{cum_info / 1_000:.1f} Kbit")
        lines.append(f'| Cumulative info | {info_str} |')
        if cum_cost > 0:
            bpd = cum_info / cum_cost
            bpd_str = (f"{bpd / 1_000_000:.1f} Mbit/$"
                       if bpd >= 1_000_000
                       else f"{bpd / 1_000:.1f} Kbit/$")
            lines.append(f'| Cumulative info/$ | {bpd_str} |')

    if cum_in_tok > 0:
        lines.append(f'| Cumulative input | {_fmt_tok(cum_in_tok)} tokens |')
    if cum_out_tok > 0:
        lines.append(f'| Cumulative output | {_fmt_tok(cum_out_tok)} tokens |')

    return '\n'.join(lines)
