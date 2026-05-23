"""Reusable design loop for agentic exploration and analysis.

Extracted from the inline Python in the design workflow job so it can be
reused by both /agent-design and /agent-workshop (Stages 1 and 3).
"""

import json
import os
import re
import subprocess
import sys

from tools import (
    validate_path as _tools_validate_path,
    execute_read_file as _tools_execute_read_file,
    execute_gh as _tools_execute_gh,
)


# ---------------------------------------------------------------------------
# Tool definitions (shared by the design loop)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file from the repository. "
                "Use this to examine source code, configuration, tests, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file relative to repository root",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search for a pattern in repository files using git grep. "
                "Returns matching lines with file paths and line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The search pattern (supports basic regex)",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional: limit search to a specific file or directory"
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gh",
            "description": (
                "Run a `gh` CLI command to inspect GitHub state — issues, PRs, "
                "comments, Actions run logs, etc. Read-only inspection only; do "
                "not use this for write operations (no commenting, no editing, "
                "no merging). Provide the subcommand and arguments without the "
                "leading 'gh'. Examples: `issue view 584`, "
                "`pr view 597 --json title,body,comments`, "
                "`run view 25084646693 --log`, "
                "`api repos/owner/repo/issues/N/comments`. "
                "Token scope is current-repo by default; cross-repo when the "
                "workflow was invoked via /dogfood. 30-second timeout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "gh subcommand and arguments, without the leading 'gh'.",
                    }
                },
                "required": ["args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_analysis",
            "description": (
                "Submit your final design analysis. Call this when you have "
                "completed your exploration and are ready to present your findings. "
                "Use Markdown formatting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "analysis": {
                        "type": "string",
                        "description": "The complete design analysis in Markdown format",
                    }
                },
                "required": ["analysis"],
            },
        },
    },
]




# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def validate_path(path):
    """Validate a path (design_loop variant: no repo-bounds check, checks existence).

    Returns (True, resolved_path) on success or (False, error_message) on failure.
    """
    return _tools_validate_path(path, repo_bounds=False)


def execute_read_file(path):
    """Execute the read_file tool (design_loop variant: enables directory listing)."""
    return _tools_execute_read_file(path, list_directory=True, repo_bounds=False)


def execute_grep(pattern, path=None):
    """Execute the grep tool."""
    try:
        cmd = ["git", "grep", "-n", "--no-color", pattern]
        if path:
            valid, validated_path = validate_path(path)
            if not valid:
                return f"Error: {validated_path}"
            cmd.append("--")
            cmd.append(validated_path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        if not output:
            return "No matches found."
        lines = output.split("\n")
        if len(lines) > 100:
            output = (
                "\n".join(lines[:100])
                + f"\n\n... ({len(lines) - 100} more matches truncated)"
            )
        return output
    except subprocess.TimeoutExpired:
        return "Error: Search timed out"
    except Exception as e:
        return f"Error executing grep: {e}"


def execute_gh(args):
    """Execute the gh tool (delegates to lib.tools.execute_gh)."""
    return _tools_execute_gh(args)


def execute_tool(tool_name, arguments):
    """Execute a tool and return the result."""
    if tool_name == "read_file":
        return execute_read_file(arguments.get("path", ""))
    elif tool_name == "grep":
        return execute_grep(arguments.get("pattern", ""), arguments.get("path"))
    elif tool_name == "gh":
        return execute_gh(arguments.get("args", ""))
    elif tool_name == "submit_analysis":
        return arguments.get("analysis", "")
    else:
        return f"Error: Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Design loop system prompt
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are analyzing a GitHub issue for design discussion using an agentic exploration loop. "
    "You have access to tools to read files, search the codebase, and inspect GitHub state.\n\n"
    "Your goal is to understand the issue, explore the relevant code, and produce a thorough "
    "design analysis. Use the read_file and grep tools to explore the repository. "
    "Use the gh tool when you need to look at GitHub state — past issues, PRs, comments, "
    "or Actions run logs — for example when the question is 'why did run X fail' or "
    "'what was discussed on issue Y'. The gh tool is for read-only inspection only; "
    "do not use it to comment, edit, or merge.\n\n"
    "When you have gathered enough information, call the submit_analysis tool with your "
    "complete analysis in Markdown format.\n\n"
    "Your analysis should include:\n"
    "1. **Summary** of the issue and what needs to change\n"
    "2. **Relevant code** you found and how it relates to the issue\n"
    "3. **Proposed approach** with specific files and changes\n"
    "4. **Risks and considerations**\n"
    "5. **Open questions** if any\n\n"
    "Calibrate your analysis to the level of abstraction signaled by the issue:\n\n"
    "- If the issue describes a **high-level goal** (e.g., 'add workshop mode'), "
    "focus on architecture: components, data flow, key interfaces. Do NOT write implementation-level code.\n"
    "- If the issue is an **implementation spec** (e.g., specific function signatures, config schemas), "
    "go deeper: file-level changes, function signatures, edge cases, test strategy.\n"
    "- If the issue is a **bug report**, focus on root-cause analysis and the minimal fix.\n"
    "- If the issue is an **exploratory question** (e.g., feasibility assessment, data availability, "
    "'is X possible?'), focus on answering the question directly. Explore the codebase and data as needed, "
    "give a clear answer, and skip the implementation-plan scaffolding.\n\n"
    "Match the level of detail the issue author is asking for — don't over-specify when they want boxes-and-arrows, "
    "and don't under-specify when they want an implementation plan."
)


def _budget_paragraph(max_iterations):
    """Build the iteration-budget paragraph for the design loop's system prompt.

    Names the budget explicitly so the model can pace itself, but warns
    against treating it as a target — without that, "you have N iterations"
    reads as "spend N iterations." Mirrors resolve.py and reconcile.py.
    """
    return (
        f"\n## Iteration Budget\n\n"
        f"You have a budget of **{max_iterations} iterations** for this analysis. "
        f"Aim to finish in significantly fewer if the question allows — the budget is "
        f"a ceiling, not a target. Don't pad with extra exploration just because the "
        f"budget is there. A focused design question rarely needs more than 5-8 "
        f"iterations of reading before submit_analysis is appropriate.\n"
    )


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def run_design_loop(
    *,
    model,
    issue_title,
    issue_body,
    issue_comments="",
    extra_instructions="",
    extra_context="",
    max_iterations=10,
    wrapup_enabled=True,
    wrapup_iteration=0,
    context_keep_tool_results=0,
    system_prompt=None,
    distill_enabled=True,
):
    """Run the agentic design exploration loop.

    Parameters
    ----------
    model : str
        The LiteLLM model identifier (e.g. "anthropic/claude-sonnet-4-20250514").
    issue_title : str
        Title of the GitHub issue.
    issue_body : str
        Body of the GitHub issue.
    issue_comments : str
        Formatted issue comments (optional).
    extra_instructions : str
        Additional instructions to append to the system prompt.
    extra_context : str
        Additional context (e.g. repo file listing, loaded context files).
    max_iterations : int
        Maximum number of agentic loop iterations.
    wrapup_enabled : bool
        Whether to inject a graceful wrapup message.
    wrapup_iteration : int
        Iteration number at which to inject the wrapup message.
    context_keep_tool_results : int
        Number of recent tool results to keep (0 = keep all).
    system_prompt : str or None
        Override the default system prompt entirely.
    distill_enabled : bool
        If True (default), run a distillation pre-pass via
        lib.distill.maybe_distill to focus extra_context on the parts
        relevant to the issue. Set False to skip (e.g. for tests, or
        when extra_context is already focused).

    Returns
    -------
    dict with keys:
        - analysis: str or None — the final analysis text
        - input_tokens: int
        - output_tokens: int
        - cost: float
        - iterations: int
        - distill_input_tokens: int
        - distill_output_tokens: int
        - distill_cost: float
    """
    from litellm import completion as litellm_completion

    # Import context trimming helper
    try:
        from context import trim_tool_results, completion_with_retries
    except ImportError:
        # Fallback: might be running from a different directory
        sys.path.insert(0, os.path.dirname(__file__))
        from context import trim_tool_results, completion_with_retries

    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    # Iteration-budget hint: name the budget so the model can pace itself,
    # but warn against treating it as a target. Mirrors resolve.py.
    system_prompt = system_prompt + _budget_paragraph(max_iterations)

    if extra_instructions:
        system_prompt += f"\n\n## Additional Instructions\n\n{extra_instructions}"

    # Distillation pre-pass: pre-select the parts of the codebase relevant
    # to the issue, so the agent doesn't have to discover them via tool
    # calls. Mirrors the pattern used in resolve.py.
    distill_input_tokens = 0
    distill_output_tokens = 0
    distill_cost = 0.0
    if distill_enabled and extra_context:
        try:
            try:
                from distill import maybe_distill
            except ImportError:
                sys.path.insert(0, os.path.dirname(__file__))
                from distill import maybe_distill
            issue_context_text = (
                f"## Issue: {issue_title}\n\n{issue_body}"
                + (f"\n\n## Discussion so far:\n{issue_comments}" if issue_comments else "")
            )
            print("Running context distillation pre-step (design loop)...")
            # Note: design loop currently doesn't surface a per-iter savings
            # metric, so we discard codebase_total_tokens here.
            (distilled, distill_input_tokens, distill_output_tokens,
             distill_cost, structural_extract, _codebase_total) = maybe_distill(
                extra_context, issue_context_text, model
            )
            if distilled != extra_context:
                # Replace extra_context with focused content + index of all
                # function/class definitions for direct navigation.
                new_extra = f"## Distilled Context\n\n{distilled}"
                if structural_extract:
                    new_extra += f"\n\n## Codebase Index\n\n{structural_extract}"
                extra_context = new_extra
                print(f"  Distillation: ~{distill_input_tokens} in, ~{distill_output_tokens} out, ${distill_cost:.4f}")
        except Exception as e:
            print(f"Distillation failed: {e} — proceeding with full extra_context")

    # Build user content
    user_content = f"## Issue: {issue_title}\n\n{issue_body}"
    if issue_comments:
        user_content += f"\n\n## Discussion so far:\n{issue_comments}"
    if extra_context:
        user_content += f"\n\n{extra_context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
    final_analysis = None
    last_response = None
    wrapup_injected = False
    iteration = 0

    for iteration in range(max_iterations):
        print(f"=== Iteration {iteration + 1}/{max_iterations} ===")

        response = completion_with_retries(
            litellm_completion,
            model=model,
            messages=messages,
            tools=TOOLS,
            max_tokens=16384,
        )

        # Track token usage
        usage = getattr(response, "usage", None)
        if usage:
            total_input_tokens += getattr(usage, "prompt_tokens", 0)
            total_output_tokens += getattr(usage, "completion_tokens", 0)
            # Prompt caching token details (normalized by LiteLLM across providers)
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            if prompt_details:
                total_cache_read_tokens += getattr(prompt_details, "cached_tokens", 0) or 0
                total_cache_creation_tokens += getattr(prompt_details, "cache_creation_input_tokens", 0) or 0
        cost = getattr(response, "_hidden_params", {}).get("response_cost", None)
        if cost:
            total_cost += cost

        message = response.choices[0].message
        last_response = message.content

        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            print("No tool calls — stopping loop")
            break

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.dict() for tc in tool_calls],
        })

        done = False
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            if tool_name == "bash":
                print(f"  Tool: bash({arguments.get('command', '')[:80]!r})")
            elif tool_name in ("read_file", "grep", "finish"):
                print(f"  Tool: {tool_name}({arguments})")
            else:
                print(f"  Tool: {tool_name}({list(arguments.keys())})")
            result = execute_tool(tool_name, arguments)

            if tool_name == "submit_analysis":
                final_analysis = result
                done = True

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        if context_keep_tool_results > 0:
            messages = trim_tool_results(messages, context_keep_tool_results)

        if done:
            break

        # Graceful wrapup injection
        if (
            wrapup_enabled
            and wrapup_iteration > 0
            and not wrapup_injected
            and iteration + 1 >= wrapup_iteration
        ):
            remaining = max_iterations - (iteration + 1)
            messages.append({
                "role": "user",
                "content": (
                    f"You have used {iteration + 1} of {max_iterations} iterations "
                    f"({remaining} remaining). "
                    "Please wrap up your analysis now and call submit_analysis with "
                    "whatever analysis you have gathered so far. "
                    "Do not start new lines of inquiry."
                ),
            })
            wrapup_injected = True

    analysis = final_analysis or last_response or ""

    return {
        "analysis": analysis if analysis else None,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost": total_cost,
        "iterations": (iteration + 1) if max_iterations > 0 else 0,
        "cache_read_tokens": total_cache_read_tokens,
        "cache_creation_tokens": total_cache_creation_tokens,
        "distill_input_tokens": distill_input_tokens,
        "distill_output_tokens": distill_output_tokens,
        "distill_cost": distill_cost,
    }


def has_agent_command(text):
    """Check if text contains /agent commands (loop prevention)."""
    if not text:
        return False
    return bool(re.search(r"^/agent", text, re.MULTILINE))
