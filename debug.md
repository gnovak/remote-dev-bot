# Debugging and Observability

This document describes the observability and tuning features available in
remote-dev-bot.

## Configuration Arguments

These arguments can be passed inline in the trigger comment (after the command
line):

```
/agent resolve
status_log_interval = 5
max_iterations = 50
```

---

## Context and Cost Tuning

### `bash_output_limit`

Maximum characters of bash tool output to include in the agent's context.
Output exceeding this limit is truncated with a note. Set to `0` to disable
truncation.

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

Every N iterations, the agent is asked for a 1-2 sentence status update (a
side-channel call that does not affect the main conversation). The collected
updates are posted as an issue comment at the end of the run.

- **Default:** `0` (disabled)
- **Suggested:** `5` for a 50-iteration run (gives ~10 checkpoints)
- **Cost:** One small extra API call per interval; output is tiny so cost impact
  is minimal

---

## PR Description

When the agent calls `finish()`, it is required to provide a
`conversation_summary` — a 3-5 sentence description of the approach taken, key
decisions made, and any dead ends hit. This appears as a `## Summary` section
at the top of the PR description.

## GitHub Actions Step Summary

After each resolve run, a summary table is written to the GitHub Actions run
page (`$GITHUB_STEP_SUMMARY`). This appears at the top of the Actions run
without needing to dig through logs, and includes:

- Result (success/failure)
- Estimated cost
- Number of iterations used
- Model alias and ID
- Agent's final status explanation
