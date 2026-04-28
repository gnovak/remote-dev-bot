#!/usr/bin/env python3
"""Post a fallback cost comment to a GitHub issue or PR.

Used by the remote-dev-bot workflow when the primary cost-embedding path
(resolve.py success comment, Post result comment, Append cost to PR) did
not run. This script consolidates ~6 identical YAML blocks into one place.

Usage:
    python3 lib/post_fallback_cost.py \
      --issue-number <N> \
      --max-iterations <N> \
      [--usage-file /tmp/llm_usage.json] \
      [--start-time-file /tmp/start_time] \
      --model-alias <alias> \
      --model <model-id> \
      --repo <owner/repo> \
      [--message "⚠️ Agent did not complete — partial cost:"] \
      [--pr]
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure lib/ is importable when run from a target repo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.formatting import _fmt_ela, _fmt_tok


def _read_usage(usage_file: str) -> dict:
    """Read /tmp/llm_usage.json and return its contents, or defaults on failure."""
    try:
        with open(usage_file) as f:
            d = json.load(f)
        return {
            "input_tokens": int(d.get("input_tokens", 0)),
            "output_tokens": int(d.get("output_tokens", 0)),
            "cost": float(d.get("cost") or 0),
            "iterations": int(d.get("iterations", 0)),
        }
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "iterations": 0}


def _read_start_time(start_time_file: str) -> int | None:
    """Read /tmp/start_time and return the Unix timestamp, or None on failure."""
    try:
        return int(Path(start_time_file).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _fmt_cost(cost: float) -> str:
    """Round cost up to the nearest cent."""
    return f"{math.ceil(cost * 100) / 100:.2f}"


def _fmt_iterations(iterations: int, max_iterations: str) -> str:
    """Format iterations as 'N / M' if max is known, else 'N'."""
    if max_iterations and max_iterations.isdigit() and int(max_iterations) > 0:
        return f"{iterations} / {max_iterations}"
    return str(iterations)


def build_comment(
    alias: str,
    model: str,
    elapsed_seconds: int | None,
    iterations: int,
    max_iterations: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    message: str,
) -> str:
    """Build the markdown comment body."""
    elapsed_fmt = _fmt_ela(elapsed_seconds) if elapsed_seconds is not None else "unknown"
    iterations_fmt = _fmt_iterations(iterations, max_iterations)
    input_fmt = _fmt_tok(input_tokens)
    output_fmt = _fmt_tok(output_tokens)
    cost_fmt = _fmt_cost(cost)

    lines = [
        f"🤖 **Model:** `{alias}` (`{model}`)",
        "",
        message,
        "",
        "### 💰 Cost",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Time | {elapsed_fmt} |",
        f"| Iterations | {iterations_fmt} |",
        f"| Input | {input_fmt} tokens |",
        f"| Output | {output_fmt} tokens |",
        f"| **Cost** | **${cost_fmt}** |",
    ]
    return "\n".join(lines) + "\n"


def post_comment(
    body: str,
    issue_number: int,
    repo: str,
    use_pr: bool,
) -> None:
    """Post the comment via gh CLI."""
    cmd_type = "pr" if use_pr else "issue"
    cmd = [
        "gh", cmd_type, "comment", str(issue_number),
        "--repo", repo,
        "--body", body,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh {cmd_type} comment failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post a fallback cost comment to a GitHub issue or PR."
    )
    parser.add_argument("--issue-number", required=True, type=int,
                        help="GitHub issue or PR number")
    parser.add_argument("--max-iterations", default="",
                        help="Maximum iteration count (for formatting iterations field)")
    parser.add_argument("--usage-file", default="/tmp/llm_usage.json",
                        help="Path to llm_usage.json (default: /tmp/llm_usage.json)")
    parser.add_argument("--start-time-file", default="/tmp/start_time",
                        help="Path to start_time file (default: /tmp/start_time)")
    parser.add_argument("--model-alias", required=True,
                        help="Human-readable model alias (e.g. claude-small)")
    parser.add_argument("--model", required=True,
                        help="Model ID (e.g. anthropic/claude-sonnet-4-5)")
    parser.add_argument("--repo", required=True,
                        help="GitHub repository (owner/name)")
    parser.add_argument("--message",
                        default="⚠️ Agent did not complete — partial cost:",
                        help="Warning message line in the comment")
    parser.add_argument("--pr", action="store_true",
                        help="Post as a PR comment instead of an issue comment")

    args = parser.parse_args()

    usage = _read_usage(args.usage_file)
    start_time = _read_start_time(args.start_time_file)
    elapsed = int(time.time()) - start_time if start_time is not None else None

    body = build_comment(
        alias=args.model_alias,
        model=args.model,
        elapsed_seconds=elapsed,
        iterations=usage["iterations"],
        max_iterations=args.max_iterations,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cost=usage["cost"],
        message=args.message,
    )

    post_comment(
        body=body,
        issue_number=args.issue_number,
        repo=args.repo,
        use_pr=args.pr,
    )


if __name__ == "__main__":
    main()
