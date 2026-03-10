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
