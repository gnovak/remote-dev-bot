"""Shared context management utilities for remote-dev-bot agent loops.

Provides functions for managing conversation context size across
resolve, design, and review modes.
"""


import json
import re


# Patterns that indicate a bash command is a "write" operation.
# Write operation results are protected from being dropped by trim_tool_results,
# so context about what was actually changed is preserved longer.
_WRITE_BASH_PATTERNS = [
    r"\bgit\s+commit\b",           # git commit
    r"\bgit\s+push\b",             # git push
    r"\bgit\s+add\b",              # git add
    r"\bgit\s+merge\b",            # git merge
    r"\bgit\s+rebase\b",           # git rebase
    r"\bgit\s+reset\b",            # git reset
    r"\bgit\s+checkout\s+-b\b",   # git checkout -b (branch creation)
    r"\bgit\s+branch\s+",          # git branch operations
    r"\bgit\s+tag\b",              # git tag
    r"\bgit\s+rm\b",               # git rm
    r"\bgit\s+mv\b",               # git mv
    r">>?\s*[\w/]",                 # output redirection (>, >>)
    r"\bsed\s+-i\b",               # sed -i (in-place edit)
    r"\bpatch\b",                   # patch command
    r"\btouch\b",                   # touch (create file)
    r"\bcp\b",                      # cp (copy file)
    r"\bmv\b",                      # mv (move file)
    r"\brm\b",                      # rm (delete file)
    r"\bmkdir\b",                   # mkdir
    r"\bcat\s+>",                   # cat > (write to file)
    r"\btee\b",                     # tee (write to file)
    r"\bpip\s+install\b",          # pip install
    r"\bnpm\s+install\b",          # npm install
    r"\bapt\s+install\b",          # apt install
    r"\bchmod\b",                   # chmod
    r"\bchown\b",                   # chown
]

_WRITE_PATTERN_RE = re.compile("|".join(_WRITE_BASH_PATTERNS), re.IGNORECASE)


def _is_write_bash_command(command):
    """Return True if a bash command appears to be a write/modification operation.

    Write operations (file edits, git commits, git push) are more valuable to
    keep in context because they represent changes that were actually made.
    Read operations (cat, ls, grep) can be dropped more aggressively.
    """
    return bool(_WRITE_PATTERN_RE.search(command))


def _build_tool_call_map(messages):
    """Build a mapping from tool_call_id to {name, arguments}.

    Scans all assistant messages with tool_calls and returns a dict mapping
    each tool_call_id to the function name and arguments string.
    """
    call_map = {}
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    tc_id = tc.get("id")
                    fn = tc.get("function", {})
                    if tc_id:
                        call_map[tc_id] = {
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", ""),
                        }
    return call_map


def _is_write_tool_result(tool_call_id, call_map):
    """Return True if the tool call with this ID was a write/modification operation.

    Read-only tools (read_file, grep) are always droppable.
    Bash commands that modify files or run git write operations are protected.
    finish() calls are also droppable (they only appear at end of run).
    """
    info = call_map.get(tool_call_id, {})
    tool_name = info.get("name", "")

    # read_file and grep are always read-only
    if tool_name in ("read_file", "grep", "finish"):
        return False

    # bash calls may be reads or writes — check the command
    if tool_name == "bash":
        args_str = info.get("arguments", "")
        try:
            args = json.loads(args_str)
            command = args.get("command", args_str)
        except (json.JSONDecodeError, AttributeError):
            command = args_str
        return _is_write_bash_command(command)

    # Unknown tool — conservatively treat as write to avoid dropping
    return True


def trim_tool_results(messages, keep_n):
    """Remove oldest tool call/result pairs, keeping the last keep_n pairs.

    Preserves all assistant text content and the system prompt.
    Operates on OpenAI-format messages where tool calls are in assistant messages
    (role="assistant", tool_calls=[...]) and results are role="tool" messages.

    Drop policy (smart ordering):
    - Read-only results (read_file, grep, read-style bash) are dropped first.
    - Write results (git commit/push, file edits) are dropped only if necessary
      after all read-only results have been exhausted.
    - This preserves context about what was actually changed for longer.
    """
    if keep_n <= 0:
        return messages

    # Collect indices of all "tool" role messages (each is one tool result)
    tool_result_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]

    if len(tool_result_indices) <= keep_n:
        return messages

    # Number of pairs to drop
    n_drop = len(tool_result_indices) - keep_n

    # Build tool call map to classify each result as read vs write
    call_map = _build_tool_call_map(messages)

    # Classify tool results: separate read-only from write results
    # (preserving chronological order within each group)
    read_indices = []
    write_indices = []
    for idx in tool_result_indices:
        tool_call_id = messages[idx].get("tool_call_id")
        if _is_write_tool_result(tool_call_id, call_map):
            write_indices.append(idx)
        else:
            read_indices.append(idx)

    # Build the set of indices to drop:
    # Drop oldest read-only results first, then oldest write results if needed.
    indices_to_drop = set()

    # Drop from read-only pool first (oldest first)
    for idx in read_indices:
        if len(indices_to_drop) >= n_drop:
            break
        indices_to_drop.add(idx)

    # If we still need to drop more, drop from write pool (oldest first)
    for idx in write_indices:
        if len(indices_to_drop) >= n_drop:
            break
        indices_to_drop.add(idx)

    # Now remove the selected tool results and update their assistant messages
    dropped_tool_call_ids = set()
    for idx in indices_to_drop:
        dropped_tool_call_ids.add(messages[idx].get("tool_call_id"))

    new_messages = []
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if i in indices_to_drop:
            # Drop this tool result message entirely
            continue
        if role == "assistant" and msg.get("tool_calls"):
            # Filter out tool_calls whose IDs are being dropped
            remaining_calls = [
                tc for tc in msg["tool_calls"]
                if tc.get("id") not in dropped_tool_call_ids
            ]
            dropped_calls = [
                tc for tc in msg["tool_calls"]
                if tc.get("id") in dropped_tool_call_ids
            ]
            if dropped_calls:
                # Build a new assistant message: preserve content, replace dropped calls
                # with a placeholder text note. Keep remaining tool calls if any.
                n_omitted = len(dropped_calls)
                placeholder_text = f"[{n_omitted} tool call(s) omitted for context]"
                new_msg = dict(msg)
                if remaining_calls:
                    new_msg["tool_calls"] = remaining_calls
                    # Prepend placeholder to content (content may be str or list or None)
                    if new_msg.get("content") is None:
                        new_msg["content"] = placeholder_text
                    elif isinstance(new_msg["content"], str):
                        new_msg["content"] = placeholder_text + "\n" + new_msg["content"]
                    else:
                        # list of content blocks — prepend text block
                        new_msg["content"] = [{"type": "text", "text": placeholder_text}] + list(new_msg["content"])
                else:
                    # No remaining calls — strip tool_calls entirely, keep only content
                    new_msg = {"role": "assistant"}
                    if msg.get("content") is None or msg.get("content") == []:
                        new_msg["content"] = placeholder_text
                    elif isinstance(msg["content"], str):
                        new_msg["content"] = (msg["content"] + "\n" + placeholder_text).strip()
                    else:
                        new_msg["content"] = list(msg["content"]) + [{"type": "text", "text": placeholder_text}]
                new_messages.append(new_msg)
            else:
                new_messages.append(msg)
        else:
            new_messages.append(msg)

    return new_messages


def estimate_tokens(messages):
    """Estimate the total token count for a list of messages.

    Uses the simple heuristic of character count / 4.
    Handles content that is a string, a list of content blocks, or None.
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content")
        if content is None:
            pass
        elif isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
                elif isinstance(block, str):
                    total_chars += len(block)
        # Count tool_calls arguments as tokens too
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                total_chars += len(fn.get("arguments", ""))
                total_chars += len(fn.get("name", ""))
    return total_chars // 4


def _extract_text(msg):
    """Extract text content from a message for summarization."""
    content = msg.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def compact_messages(messages, compaction_coverage, compaction_factor, llm_call_fn):
    """Compact the oldest portion of conversation by LLM-summarizing it.

    Args:
        messages: The full message list (system prompt + conversation).
        compaction_coverage: Fraction of post-system messages to compact (from oldest end).
        compaction_factor: Target fraction of selected content to remove (0.5 = 50% reduction).
        llm_call_fn: A callable(messages, max_tokens) -> str that makes an LLM call
                     for summarization. Should return the summary text.

    Returns:
        (new_messages, stats) where stats is a dict with:
            - messages_compacted: number of messages that were replaced
            - tokens_before: estimated tokens in the selected messages
            - tokens_after: estimated tokens in the summary message
    """
    if len(messages) < 3:
        # Need at least system + 1 msg + 1 recent msg
        return messages, {"messages_compacted": 0, "tokens_before": 0, "tokens_after": 0}

    # Identify system prompt (index 0) — always preserved
    system_msg = messages[0]
    post_system = messages[1:]

    # Number of messages to compact (from oldest end of post_system)
    n_to_compact = max(1, int(len(post_system) * compaction_coverage))

    # Always keep at least 2 recent messages to preserve immediate context
    if n_to_compact >= len(post_system) - 1:
        n_to_compact = max(1, len(post_system) - 2)

    selected = post_system[:n_to_compact]
    remaining = post_system[n_to_compact:]

    # Build text representation of selected messages for summarization
    text_parts = []
    for msg in selected:
        role = msg.get("role", "unknown")
        text = _extract_text(msg)
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tc_summaries = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    tc_summaries.append(f"{fn.get('name', '?')}({fn.get('arguments', '')[:200]})")
            if tc_summaries:
                text += "\nTool calls: " + "; ".join(tc_summaries)
        if text.strip():
            text_parts.append(f"[{role}]: {text.strip()}")

    selected_text = "\n\n".join(text_parts)
    if not selected_text.strip():
        return messages, {"messages_compacted": 0, "tokens_before": 0, "tokens_after": 0}

    tokens_before = estimate_tokens(selected)

    # Target summary length: (1 - compaction_factor) * original size
    target_tokens = max(100, int(tokens_before * (1 - compaction_factor)))

    # Make the summarization call
    summary_prompt = [
        {
            "role": "user",
            "content": (
                "Summarize the following conversation history. "
                "Preserve all technical decisions, file paths, code written or modified, "
                "commands run and their results, errors encountered and how they were "
                "resolved, and any conclusions reached. Omit conversational filler.\n\n"
                f"Target length: approximately {target_tokens * 4} characters.\n\n"
                "---\n\n"
                f"{selected_text}"
            ),
        }
    ]

    try:
        summary = llm_call_fn(summary_prompt, max(256, target_tokens))
    except Exception as e:
        # If summarization fails, return messages unchanged
        print(f"  [Compaction] Summarization call failed: {e}")
        return messages, {"messages_compacted": 0, "tokens_before": 0, "tokens_after": 0}

    if not summary or not summary.strip():
        return messages, {"messages_compacted": 0, "tokens_before": 0, "tokens_after": 0}

    # Build the compacted summary message
    summary_msg = {
        "role": "user",
        "content": (
            f"[COMPACTED HISTORY — {n_to_compact} messages compressed to summary]\n\n"
            f"{summary.strip()}"
        ),
    }

    tokens_after = estimate_tokens([summary_msg])

    new_messages = [system_msg, summary_msg] + remaining

    stats = {
        "messages_compacted": n_to_compact,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
    }

    return new_messages, stats


def completion_with_retries(completion_fn, *args, **kwargs):
    """Call a litellm completion function with retry logic for transient errors.

    Retries on ServiceUnavailableError and InternalServerError (e.g., Anthropic
    "overloaded" errors) with exponential backoff. These errors are typically
    transient and resolve within seconds to minutes.

    Args:
        completion_fn: The litellm completion callable to wrap.
        *args, **kwargs: Passed directly to completion_fn.

    Returns:
        The completion response on success.

    Raises:
        The last exception if all retries are exhausted.
        Any non-retryable exception immediately.
    """
    import time
    import litellm

    RETRYABLE_ERRORS = (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.InternalServerError,
    )
    MAX_RETRIES = 5
    BASE_DELAY_SECS = 10
    MAX_DELAY_SECS = 120

    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return completion_fn(*args, **kwargs)
        except RETRYABLE_ERRORS as exc:
            last_exc = exc
            if attempt >= MAX_RETRIES:
                print(f"  [Retry] Transient error — exhausted {MAX_RETRIES} retries: {exc}")
                raise
            delay = min(BASE_DELAY_SECS * (2 ** attempt), MAX_DELAY_SECS)
            print(
                f"  [Retry] Transient error (attempt {attempt + 1}/{MAX_RETRIES}), "
                f"retrying in {delay}s: {exc}"
            )
            time.sleep(delay)
