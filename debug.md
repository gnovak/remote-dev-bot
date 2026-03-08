# Debug / Tuning Parameters

These inline arguments are available for debugging and tuning agent behavior.
They are not part of the stable public interface and may change without notice.
Pass them in the comment body when triggering the agent:

    /agent-resolve bash_output_limit = 4000

---

## Context and Cost Tuning

### `bash_output_limit`

Maximum characters of bash tool output to include in the agent's context.
Output exceeding this limit is truncated with a note. Set to `0` to disable truncation.

- **Default:** `8000`
- **Lower values:** Reduce context size and cost; risk hiding relevant output
- **Higher values / 0:** Full output; can cause context bloat on verbose commands

### `context_keep_tool_results`

Number of recent tool call/result pairs to keep in the conversation context.
Older pairs are replaced with a placeholder. This prevents O(N²) context growth
over long runs. Set to `0` to keep all tool results (default behavior).

- **Default:** `0` (keep all)
- **Suggested starting point:** `20` (keeps the last 20 tool interactions)
- **Lower values:** Smaller context, lower cost, but agent may "forget" earlier work
- **Higher values / 0:** Full history; safe but expensive on long runs

---

## Iteration and Behavior

### `status_log_interval`

*(Coming soon)* Every N iterations, the agent writes a one-sentence status update
to a running log. The log is posted as a comment at the end of the run.
Set to `0` to disable.

- **Default:** `0` (disabled)
