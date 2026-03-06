# Changelog

## v0.6.0 — Remove OpenHands, custom LiteLLM agent loop (Mar 2026)

### What changed

- **OpenHands removed**: The resolve mode no longer uses `openhands-ai`. A custom
  LiteLLM agent loop (`lib/resolve.py`) now handles codebase exploration, file
  editing, committing, and PR creation directly — the same approach already used
  by design and review modes.
- **Branch control**: Branches are now named `rdb-fix-issue-{n}` (was
  `openhands-fix-issue-{n}-try{n}`). For PR-comment triggers, the agent works
  directly on the PR's existing branch rather than creating a new one.
- **Multi-branch support**: The `branch` parameter now controls both where the
  agent starts work and where the PR is targeted. Rename `openhands.target_branch`
  → `agent.branch` in your config.
- **Config key renamed**: `openhands:` → `agent:` in `remote-dev-bot.yaml`.
  Old configs continue to work (backward compatible until v1).
- **Security disclosure updated**: Agent runs bash directly on ephemeral GitHub
  Actions VMs (not in a container). The security posture is equivalent — the
  runner is isolated and discarded after each run.

### Breaking changes

- **Config key**: `openhands:` is now deprecated in favor of `agent:`. Both still
  work, but update your `remote-dev-bot.yaml` to use `agent:`.
- **`target_branch` → `branch`**: Rename in both config and inline args. `target_branch`
  still accepted as an alias.
- **`oh_version` removed**: The `openhands.version` config key is ignored. Remove it
  from your config.
- **`commit_trailer`**: If you use `{oh_version}` in your commit trailer template,
  remove it. Supported variables are now only `{model_alias}` and `{model_id}`.
- **Branch naming**: Agent-created branches are now `rdb-fix-issue-{n}`. If you have
  scripts or searches expecting `openhands-fix-issue-*`, update them.

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
