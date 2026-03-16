"""Shared context management utilities for remote-dev-bot agent loops.

Provides functions for managing conversation context size across
resolve, design, and review modes.
"""


def trim_tool_results(messages, keep_n):
    """Remove oldest tool call/result pairs, keeping the last keep_n pairs.

    Preserves all assistant text content and the system prompt.
    Operates on OpenAI-format messages where tool calls are in assistant messages
    (role="assistant", tool_calls=[...]) and results are role="tool" messages.
    """
    if keep_n <= 0:
        return messages

    # Collect indices of all "tool" role messages (each is one tool result)
    tool_result_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]

    if len(tool_result_indices) <= keep_n:
        return messages

    # Number of pairs to drop
    n_drop = len(tool_result_indices) - keep_n
    indices_to_drop = set(tool_result_indices[:n_drop])

    # Also find the assistant messages that contain tool_calls for the pairs we're dropping.
    # Each assistant message with tool_calls is immediately followed by one or more tool messages.
    # We scan backwards from each tool_result index to find its owning assistant message.
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
                "Summarize the following conversation history as concisely as possible. "
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
