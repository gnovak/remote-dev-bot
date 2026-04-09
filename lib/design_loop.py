"""Reusable design loop for agentic exploration and analysis.

Extracted from the inline Python in the design workflow job so it can be
reused by both /agent-design and /agent-workshop (Stages 1 and 3).
"""

import json
import os
import re
import subprocess
import sys


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
# Path validation
# ---------------------------------------------------------------------------

def validate_path(path):
    """Validate and resolve a file path within the repository.

    Returns (True, resolved_path) on success or (False, error_message) on
    failure.
    """
    normalized = os.path.normpath(path)
    if normalized.startswith("..") or os.path.isabs(normalized):
        return False, f"Access denied: path '{path}' is outside the repository"
    if not os.path.exists(normalized):
        return False, f"File not found: {normalized}"
    return True, normalized


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def execute_read_file(path):
    """Execute the read_file tool."""
    valid, result = validate_path(path)
    if not valid:
        return result
    if os.path.isdir(result):
        try:
            entries = sorted(os.listdir(result))
            return f"Directory listing for {result}:\n" + "\n".join(entries)
        except Exception as e:
            return f"Error listing directory: {e}"
    try:
        with open(result) as f:
            content = f.read()
        if len(content) > 50000:
            content = (
                content[:50000]
                + "\n\n... (file truncated, showing first 50000 characters)"
            )
        return content
    except Exception as e:
        return f"Error reading file: {e}"


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


def execute_tool(tool_name, arguments):
    """Execute a tool and return the result."""
    if tool_name == "read_file":
        return execute_read_file(arguments.get("path", ""))
    elif tool_name == "grep":
        return execute_grep(arguments.get("pattern", ""), arguments.get("path"))
    elif tool_name == "submit_analysis":
        return arguments.get("analysis", "")
    else:
        return f"Error: Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Design loop system prompt
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are analyzing a GitHub issue for design discussion using an agentic exploration loop. "
    "You have access to tools to read files and search the codebase.\n\n"
    "Your goal is to understand the issue, explore the relevant code, and produce a thorough "
    "design analysis. Use the read_file and grep tools to explore the repository.\n\n"
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

    Returns
    -------
    dict with keys:
        - analysis: str or None — the final analysis text
        - input_tokens: int
        - output_tokens: int
        - cost: float
        - iterations: int
    """
    from litellm import completion as litellm_completion

    # Import context trimming helper
    try:
        from context import trim_tool_results
    except ImportError:
        # Fallback: might be running from a different directory
        sys.path.insert(0, os.path.dirname(__file__))
        from context import trim_tool_results

    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    if extra_instructions:
        system_prompt += f"\n\n## Additional Instructions\n\n{extra_instructions}"

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
    final_analysis = None
    last_response = None
    wrapup_injected = False
    iteration = 0

    for iteration in range(max_iterations):
        print(f"=== Iteration {iteration + 1}/{max_iterations} ===")

        response = litellm_completion(
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
    }


def has_agent_command(text):
    """Check if text contains /agent commands (loop prevention)."""
    if not text:
        return False
    return bool(re.search(r"^/agent", text, re.MULTILINE))
