# Changelog

## v0.7.0 — Reliability, observability, and context management (Mar 2026)

- **Rolling status log**: Every N iterations the agent posts a brief status
  comment on the issue, so you can see what it's doing without tailing logs.
  Configure with `status_log_interval` in the `agent:` section (default: 5).
- **PR summary**: The agent writes a `## Summary` section at the top of every
  PR describing its approach and key decisions.
- **Actions job summary**: Cost, token counts, and result are now written to
  the GitHub Actions run page — no log-diving needed.
- **Bash output truncation**: Runaway command output no longer blows up the
  context window. Configurable via `bash_output_limit` (default: 8000 chars,
  head + tail). See `debug.md` for tuning options.
- **Reliability improvements**: Rate limit retry with backoff; work is pushed
  to the remote after every commit so nothing is lost if a run is interrupted;
  better wrapup instructions reduce stalled runs.
- **`on_failure: draft` expanded**: Now also opens a draft PR when the agent
  exhausts its iteration budget or crashes mid-run with committed work.
- **Improved design prompt**: Exploration-first, better abstraction calibration.

**Breaking changes:** None.

## v0.6.0 — Custom LiteLLM agent loop, OpenHands removed (Mar 2026)

OpenHands has been replaced with a custom LiteLLM agent loop (`lib/resolve.py`),
the same approach already used by design and review modes. This gives full control
over branch naming, git workflow, and PR creation.

Other changes: Claude 4.6 models, gpt-5.3-codex, model label on all comments,
improved resolve prompt (AGENT_ROLE, WORKFLOW, STUCK_RECOVERY, worked example),
graceful iteration wrapup, `commit_trailer` config removed (agent signs commits
directly via `AGENTS.md`), branch collision handling (`rdb-fix-issue-{n}-2`, etc.),
PR review context now includes formal review submissions and inline review comments,
and various e2e test fixes.

**Breaking changes:** `openhands:` → `agent:` in config (old key still works);
`target_branch` → `branch` (old key still works); branch names are now
`rdb-fix-issue-{n}-{alias}`; `oh_version` config key removed.

## v0.5.0 — Better design and review, additive config (Mar 3, 2026)

### Improvements

- **`/agent-design` now uses a multi-iteration agentic loop**: Previously
  design analysis was a single LLM call with a static repo listing. Now the
  agent can read files and explore the codebase across multiple iterations
  before posting its analysis — the same capability as `/agent-resolve`, but
  read-only. Expect noticeably richer, more grounded design comments.
- **`/agent-review` replaced with a direct LiteLLM loop**: The previous
  implementation ran OpenHands to perform code review, which was slow and
  unreliable. The new implementation drives the review directly via LiteLLM
  with the same multi-iteration agentic loop, making review faster and more
  consistent.
- **`extra_files` is additive across all config layers**: Files listed in the
  base config (e.g., `AGENTS.md`, `CLAUDE.md`) are always included; each
  deeper config layer appends rather than replaces. You can add your own
  `extra_files` entries without losing system defaults.
- **`extra_instructions` appends, not replaces**: Per-mode `extra_instructions`
  in your `remote-dev-bot.yaml` are appended to the canonical system prompt
  rather than replacing it. The agent's core instructions are always preserved.
- **Graceful wrapup**: The agent receives an iteration budget hint and is
  prompted to commit partial work and call `finish()` before hitting the limit,
  rather than stopping mid-task with nothing committed.
- **Helpful API key error**: When a required API key secret is missing, the bot
  posts a comment explaining which secret to add and how.
- `install.md` updated with a cleaner install flow and a
  `remote-dev-bot.yaml.template` starter config.
- Cost summary shows "API Calls" (not "Iterations") when metrics come from
  LiteLLM rather than OpenHands, to reflect the data source accurately.
- Agent process crashes (e.g., `send_pull_request` failure) are now detected
  and reported distinctly from normal agent failure.

### Breaking changes

- **`context_files` renamed to `extra_files`**: Update your
  `remote-dev-bot.yaml` if you used `context_files` under `modes.resolve` or
  `modes.design`. The old key is no longer recognized.
- **`additional_instructions` renamed to `extra_instructions`**: Update your
  config if you used `additional_instructions`. The old key is no longer
  recognized.
- **Compiled workflows removed**: The `dist/` compiled workflows are no longer
  built or distributed. All users should use the shim install (see
  `install.md`).

## v0.4.0 — Review mode, inline args, and reliability (Feb 28, 2026)

### New features

- **`/agent-review` mode**: Comment `/agent-review` on a PR to get a code
  review posted as a comment. Works cross-model — run Claude's review
  alongside Gemini's or GPT's.
- **Per-invocation inline args**: Pass overrides on lines after the slash
  command:
  ```
  /agent-resolve
  max_iterations = 30
  timeout_minutes = 20
  target_branch = my-branch
  context = extra-notes.md
  ```
- **`on_failure` config**: `on_failure: draft` opens a partial PR when the
  agent can't fully resolve an issue. Default (`comment`) posts a comment only.
- **Three-layer config**: Base config in the rdb repo, per-repo override
  (`remote-dev-bot.yaml`), and local dev override
  (`remote-dev-bot.local.yaml`). Layers deep-merge at the leaf level.
- **Commit trailer**: Optionally append model info to agent commits
  (configurable via `commit_trailer` in config).
- **Auto-assign PR**: Triggering user is automatically assigned to the
  resulting PR (`assign_pr` config).

### Improvements

- **install.md overhaul**: Renamed from `runbook.md`. Compiled-first install
  path. Expanded auth options (GitHub App, PAT, default token).
- **Timeout watchdog**: Configurable per-invocation (`timeout_minutes = N`)
  or via `remote-dev-bot.yaml`. Compiled workflows now honor inline args.
- **Cost reporting**: Per-run LLM cost posted in issue/PR comments.
- **Silent failure fixes**: When the resolver crashes without creating a PR,
  the workflow now posts a comment explaining what happened (and optionally
  opens a draft PR with partial changes via `on_failure: draft`).
- **Design agent**: No hallucination on missing context files; repo file
  listing included in design context.
- **E2E test overhaul**: Parallel polling, self-contained review+feedback
  test, timeout enforcement test, 85% → 99% test coverage.

### Notable changes

- Compiled install is now three files: `agent-resolve.yml`,
  `agent-design.yml`, `agent-review.yml`. Existing two-file installs keep
  working; add `agent-review.yml` to get review mode.

## v0.3.0 — Mode-based commands + compiled workflows (Feb 15, 2026)

### New features

- **Two command modes**: `/agent-resolve` (opens a PR) and `/agent-design`
  (posts design analysis as a comment). Replaces the old bare `/agent` command.
- **Multi-provider model support**: OpenAI (GPT) and Google (Gemini) model
  aliases alongside Anthropic (Claude). Configure in `remote-dev-bot.yaml`.
- **Two-file compiled install**: Single-file workflows (`agent-resolve.yml` and
  `agent-design.yml`) that users download into their repos — no shim or
  cross-repo reference needed.
- **Security guardrails**: Microagent injection prevents secret exfiltration.
  Author association gate restricts who can trigger agent runs.
- **Config layering**: Target repos can override defaults with their own
  `remote-dev-bot.yaml`.

### Improvements

- **Runbook overhaul**: Guided setup with cost limits, PAT walkthrough,
  provider-specific instructions, private repo support, troubleshooting table.
  Phases renumbered 1-5.
- **Testing framework**: Unit tests for config parsing and YAML validation, E2E
  test script with per-provider and all-models modes, security E2E tests,
  compiled workflow tests.
- **PR feedback loop**: Comment `/agent-resolve` on a PR to iterate with
  feedback.
- **Compiler rewrite**: Step lookup by name instead of hardcoded indices.
  Produces two self-contained workflow files.

### Breaking changes

- `/agent` and `/agent-<model>` commands no longer work. Use `/agent-resolve` or
  `/agent-resolve-<model>`.
- Compiled workflow install is now two files (`agent-resolve.yml` +
  `agent-design.yml`) instead of one.

## v0.2.0 — Shim + reusable workflow (Feb 11, 2026)

- Refactored into a thin shim (`agent.yml`) per target repo that calls a shared
  reusable workflow (`remote-dev-bot.yml`).
- Cross-repo support tested with separate test repo.
- Dev cycle infrastructure in place.

## v0.1.0 — First working version (Feb 9, 2026)

- End-to-end pipeline operational: `/agent` comment on an issue triggers
  OpenHands, which resolves the issue and opens a draft PR.
