"""Cost calculation for remote-dev-bot.

Calculates LLM API costs based on token usage and model pricing.
Used by resolve.yml to post cost transparency comments after agent runs.
"""

import json
import math
import os
import re
from typing import Optional

# Pricing per 1M tokens (input, output) in USD
# These are approximate prices for the models defined in remote-dev-bot.yaml
MODEL_PRICING = {
    # Anthropic models
    "anthropic/claude-haiku-4-5": {"input": 0.25, "output": 1.25},
    "anthropic/claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "anthropic/claude-opus-4-5": {"input": 15.00, "output": 75.00},
    # OpenAI models
    "openai/gpt-5-nano": {"input": 0.15, "output": 0.60},
    "openai/gpt-5.1-codex-mini": {"input": 1.50, "output": 6.00},
    "openai/gpt-5.2-codex": {"input": 10.00, "output": 30.00},
    # Gemini models
    "gemini/gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini/gemini-2.5-pro": {"input": 1.25, "output": 5.00},
}


def calculate_cost(
    model: str, input_tokens: int, output_tokens: int
) -> Optional[float]:
    """Calculate cost in USD for given token usage.

    Args:
        model: Model ID (e.g., "anthropic/claude-sonnet-4-5")
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens

    Returns:
        Cost in USD, or None if model pricing is unknown
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return None

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def parse_openhands_output(output_path: str) -> dict:
    """Parse OpenHands output.jsonl to extract token usage.

    The output.jsonl file contains one JSON object per line, with various
    event types. We look for metrics or usage information.

    Args:
        output_path: Path to output.jsonl file

    Returns:
        Dict with keys: input_tokens, output_tokens, total_cost (if calculable)
    """
    if not os.path.exists(output_path):
        return {"error": f"Output file not found: {output_path}"}

    total_input = 0
    total_output = 0
    model = None

    with open(output_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Look for metrics in various places OpenHands might put them
            # Check for 'metrics' field
            if "metrics" in event:
                metrics = event["metrics"]
                if "accumulated_cost" in metrics:
                    # OpenHands may provide accumulated cost directly
                    return {
                        "input_tokens": metrics.get("accumulated_input_tokens", 0),
                        "output_tokens": metrics.get("accumulated_output_tokens", 0),
                        "total_cost": metrics.get("accumulated_cost", 0),
                        "source": "openhands_metrics",
                    }

            # Check for 'extras' field with model info
            if "extras" in event:
                extras = event["extras"]
                if "model" in extras:
                    model = extras["model"]

            # Check for token usage in response
            if "llm_metrics" in event:
                llm = event["llm_metrics"]
                total_input += llm.get("prompt_tokens", 0)
                total_output += llm.get("completion_tokens", 0)

    result = {
        "input_tokens": total_input,
        "output_tokens": total_output,
    }

    if model:
        result["model"] = model
        cost = calculate_cost(model, total_input, total_output)
        if cost is not None:
            result["total_cost"] = cost

    return result


def parse_litellm_logs(log_content: str) -> dict:
    """Parse LiteLLM standard logging payload from log output.

    When LITELLM_PRINT_STANDARD_LOGGING_PAYLOAD=1 is set, LiteLLM prints
    JSON payloads containing cost and token information for each LLM call.
    This function extracts and sums those values.

    Args:
        log_content: String containing log output (stdout/stderr)

    Returns:
        Dict with keys: input_tokens, output_tokens, total_cost, call_count
    """
    total_input = 0
    total_output = 0
    total_cost = 0.0
    call_count = 0

    # LiteLLM prints JSON objects with StandardLoggingPayload structure
    # We look for JSON objects containing the expected fields
    # The JSON is printed with indent=4, so we need to find complete objects

    # Find all JSON-like blocks (starting with { and ending with })
    # Use a simple approach: find lines that look like JSON start/end
    lines = log_content.split("\n")
    json_buffer = []
    in_json = False
    brace_count = 0

    for line in lines:
        stripped = line.strip()

        # Detect start of JSON object (line starts with { at any indentation)
        if not in_json and stripped.startswith("{"):
            in_json = True
            json_buffer = [line]
            brace_count = line.count("{") - line.count("}")
        elif in_json:
            json_buffer.append(line)
            brace_count += line.count("{") - line.count("}")

            # Check if we've closed all braces
            if brace_count <= 0:
                json_str = "\n".join(json_buffer)
                try:
                    data = json.loads(json_str)
                    # Check if this looks like a StandardLoggingPayload
                    if (
                        isinstance(data, dict)
                        and "response_cost" in data
                        and "prompt_tokens" in data
                    ):
                        total_input += data.get("prompt_tokens", 0) or 0
                        total_output += data.get("completion_tokens", 0) or 0
                        cost = data.get("response_cost", 0) or 0
                        if isinstance(cost, (int, float)):
                            total_cost += cost
                        call_count += 1
                except (json.JSONDecodeError, ValueError):
                    pass
                in_json = False
                json_buffer = []
                brace_count = 0

            # If we encounter a new JSON start while in_json and brace_count
            # is still positive, the previous JSON was malformed. Reset and
            # start fresh with this line.
            elif stripped.startswith("{") and brace_count > 0:
                # Try to parse what we have so far (likely will fail)
                json_str = "\n".join(json_buffer[:-1])  # exclude current line
                try:
                    data = json.loads(json_str)
                    if (
                        isinstance(data, dict)
                        and "response_cost" in data
                        and "prompt_tokens" in data
                    ):
                        total_input += data.get("prompt_tokens", 0) or 0
                        total_output += data.get("completion_tokens", 0) or 0
                        cost = data.get("response_cost", 0) or 0
                        if isinstance(cost, (int, float)):
                            total_cost += cost
                        call_count += 1
                except (json.JSONDecodeError, ValueError):
                    pass
                # Start fresh with current line
                json_buffer = [line]
                brace_count = line.count("{") - line.count("}")

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_cost": total_cost if call_count > 0 else None,
        "call_count": call_count,
        "source": "litellm_logs" if call_count > 0 else None,
    }


def format_cost_comment(
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_cost: Optional[float] = None,
    mode: str = "resolve",
    alias: str = "",
) -> str:
    """Format a cost summary as a GitHub comment.

    Args:
        model: Model ID used
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        total_cost: Pre-calculated cost, or None to calculate
        mode: Agent mode (resolve/design)
        alias: Model alias used in command

    Returns:
        Markdown-formatted comment string
    """
    if total_cost is None:
        total_cost = calculate_cost(model, input_tokens, output_tokens)

    total_tokens = input_tokens + output_tokens

    lines = [
        "### 💰 Cost Summary",
        "",
        f"**Model:** `{alias}` ({model})",
        f"**Mode:** {mode}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Input tokens | {input_tokens:,} |",
        f"| Output tokens | {output_tokens:,} |",
        f"| Total tokens | {total_tokens:,} |",
    ]

    if total_cost is not None:
        # Round up to the nearest penny. This ensures:
        # 1. Cost estimates align with natural scale (pennies, not fractional pennies)
        # 2. Exactly $0.00 indicates broken cost estimates (helpful for debugging)
        # 3. Non-zero costs always show at least $0.01 (giving visibility into usage)
        # Always rounding UP (not standard rounding) prevents masking tiny costs as $0.00
        rounded_cost = math.ceil(total_cost * 100) / 100
        lines.append(f"| **Estimated cost** | **${rounded_cost:.2f}** |")
    else:
        lines.append("| Estimated cost | _(pricing unavailable)_ |")

    lines.extend(
        [
            "",
            "_Cost is estimated based on token usage and may vary from actual billing._",
        ]
    )

    return "\n".join(lines)


def main():
    """CLI entry point for cost calculation.

    Usage: python -m lib.cost <output_path> <model> <alias> <mode>

    Reads token usage from output.jsonl (or uses provided values),
    calculates cost, and prints a formatted comment.
    """
    import sys

    if len(sys.argv) < 5:
        print("Usage: python -m lib.cost <output_path> <model> <alias> <mode>")
        print("       python -m lib.cost - <model> <alias> <mode> <input_tokens> <output_tokens>")
        sys.exit(1)

    output_path = sys.argv[1]
    model = sys.argv[2]
    alias = sys.argv[3]
    mode = sys.argv[4]

    if output_path == "-":
        # Direct token counts provided
        if len(sys.argv) < 7:
            print("When output_path is '-', provide input_tokens and output_tokens")
            sys.exit(1)
        input_tokens = int(sys.argv[5])
        output_tokens = int(sys.argv[6])
        total_cost = calculate_cost(model, input_tokens, output_tokens)
    else:
        # Parse from output.jsonl
        result = parse_openhands_output(output_path)
        if "error" in result:
            print(f"Error: {result['error']}", file=sys.stderr)
            sys.exit(1)

        input_tokens = result.get("input_tokens", 0)
        output_tokens = result.get("output_tokens", 0)
        total_cost = result.get("total_cost")

        # If no cost from file, calculate it
        if total_cost is None:
            total_cost = calculate_cost(model, input_tokens, output_tokens)

    comment = format_cost_comment(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        mode=mode,
        alias=alias,
    )

    print(comment)

    # Also write to file for workflow to use
    output_file = os.environ.get("COST_COMMENT_FILE", "/tmp/cost_comment.md")
    with open(output_file, "w") as f:
        f.write(comment)


if __name__ == "__main__":
    main()
