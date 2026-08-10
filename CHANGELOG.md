# Changelog

## v1.0.0 — Stabilization, model tiers, zero-config install (Aug 2026)

The 1.0 release. Everything since v0.9.0 was driven by a comprehensive
code/workflow/docs/usage review (checked into the repo under
`comprehensive-review/2026-06-11/`) followed by a fix campaign, plus a
redesign of the model alias system for long-term stability. The release
gate was a fully green run of the complete test suite — unit tests, e2e
across every model alias on all three providers, and the security suite.

### Model aliases: three capability tiers

- **New tier system**: aliases are now `{provider}-{small,medium,large}` —
  small = best value agentic-coding workhorse, medium = the provider's
  flagship, large = frontier-above-flagship where one exists. Tiers are
  anchored on capability at agentic coding (price is an expectation, not
  the admission test), the ladder is monotone, and every alias always
  resolves to a runnable model — providers lacking a distinct model for a
  tier co-point at the tier below. The reasoning and repointing rules are
  documented in `remote-dev-bot.yaml` and the README.
- **Breaking (pre-1.0)**: `claude-large` now means the frontier tier
  (Claude Fable 5); the Opus flagship moved to `claude-medium`. `gpt-*`
  and `gemini-*` gained `medium` tiers.
- **Current mappings**: claude → sonnet-5 / opus-5 / fable-5; gpt → all
  tiers on gpt-5.3-codex (GPT-5.6 Sol cannot run tool loops via chat
  completions — restore tracked in #653); gemini → all tiers on
  2.5-flash (gemini-3.6-flash blocked on a litellm thought-signature
  bug — #654).
- **Post-1.0 policy**: the alias set is append-only; repointing an alias
  is expected and gets a changelog entry. Pin your own aliases in your
  repo's `models:` section if you'd draw the lines differently.

### Zero-config install

- **`default_model: auto`**: fresh installs no longer fail when no model
  is configured. The default resolves from whichever provider API key
  secrets are present (priority: `ANTHROPIC_API_KEY` > `OPENAI_API_KEY` >
  `GEMINI_API_KEY`). Explicit configuration always wins; no keys at all
  fails at parse time with an actionable message.
- **install.md rewritten around optional config**: the per-repo
  `remote-dev-bot.yaml` is optional; the previous instructions curl'd a
  template file that had been deleted (every fresh install 404'd at that
  step). The base config in this repo is now the live reference.

### Security hardening

- **PR-title shell injection closed**: `create_pr` built a `shell=True`
  command with the LLM-authored title escaped only for double quotes;
  backticks and `$(...)` from a prompt-injected issue could execute on
  the runner. Now an argv-list subprocess call with no shell.
- **Config values no longer interpolated into workflow Python**:
  `extra_instructions` and friends were spliced into heredoc Python
  source in 7 workflow steps — multi-line values (the documented format)
  crashed the step, and target-repo config could inject code. All sites
  now pass values through step `env:` blocks.
- **Phantom security docs removed**: the README described a
  `SECURITY_GATE` marker and "security microagent" that did not exist;
  the real gate (author association) is now documented as such.

### Reliability fixes (from the 2026-06-11 review)

- **Context-overflow recovery un-deadened**: `ContextWindowExceededError`
  subclasses `BadRequestError` and was caught by the wrong handler, so
  the emergency trim + graceful wrap-up path never ran. Handler order
  fixed; overflowing runs now wrap up instead of dying.
- **Compaction no longer corrupts tool-call pairing**: the boundary cut
  could orphan tool results from their tool calls, producing message
  lists providers reject with a 400. The cut now respects group
  boundaries.
- **resolve.py uses the shared read/write-aware context trimming** (its
  stale local copy dropped write results as readily as reads).
- **Reconcile hardened**: transient provider errors (529s) are retried
  like the sibling loops; context/truncation config is actually plumbed
  into the job; the rebase conflict-marker explanation in the prompt had
  the sides reversed and is now correct.
- **Silent-failure statuses**: the "no tool calls ×3" break paths in
  resolve and reconcile now write failure statuses instead of ending
  runs with no explanation.
- **CI on dev PRs**: unit tests now run on PRs targeting `dev` (the
  development branch model) — previously only `main`, so dev PRs merged
  with zero checks.
- **/dogfood repaired**: an invalid `workflows: write` permissions key
  (hard-rejected by GitHub since ~May) invalidated the workflow file,
  breaking `/dogfood` comments and attaching a phantom failed run to
  every push for three months.

### Cost & caching correctness

- **Design loops now use prompt caching**: the moving-tail cache marker
  (in resolve and reconcile since v0.7) was ported to the design loop —
  standalone `/agent-design` and workshop/delegate design stages were
  paying full input price every iteration on Anthropic models.
- **Cache-write tokens actually tracked**: all three loops read a
  litellm field that doesn't exist (`cache_creation_input_tokens` vs
  `cache_creation_tokens`), so cache-write costs never appeared and
  savings were overstated.
- **Design-mode distillation un-broken**: a 5-vs-6 tuple unpack mismatch
  silently disabled the distillation pre-pass for every `/agent-design`
  run (the swallowed error meant full-repo context every time).
- **Distillation and workshop/delegate costs fully accounted**:
  structural-extract signatures no longer degrade to bare argument
  names, and distillation cost is included in workshop/delegate totals.

### Delegate & loop behavior

- **Delegate Stage 3 safety blocking fixed**: a revised design containing
  `/agent` commands is now discarded (falling back to the vetted Stage 1
  design) instead of merely not being posted while still flowing to
  later stages.
- **Design-stage wrapup fixed**: the wrap-up nudge iteration was computed
  against the code budget (40 of 50) and passed into 15-iteration design
  loops, where it could never fire. Now rescaled per stage.
- **Wrapup mechanics unified**: all three loops re-inject the wrap-up
  nudge every iteration past the threshold (deliberate escalation —
  previously three different implementations).
- **Configured design/review iteration budgets respected**: the parse
  job never exported `design_max_iterations` / `review_max_iterations`,
  so design loops ran hardcoded defaults and inline overrides were
  silently ignored.

### Test infrastructure

- **e2e pre-flight**: both e2e scripts validate GitHub tokens up front
  and print the token owner and expiry, failing fast with rotation
  instructions instead of mid-suite 401 confusion.
- **Reconcile e2e failures now count** toward the suite exit code
  (previously a reconcile failure could exit green).
- **Timeout test hardened (third design)**: the watchdog test now
  demands 200 individual git commits, making wall-clock the constraint —
  fast models had twice outrun task designs that raced reasoning speed.

### Known issues

- `gemini-3.6-flash` is temporarily off the alias table: litellm's
  Gemini 3.x thought-signature handling intermittently breaks multi-turn
  tool calling (#654; upstream litellm #16893/#25322). The gemini tiers
  point at `gemini-2.5-flash` until a fixed litellm release lands.
- GPT-5.6 Sol requires OpenAI's Responses API for tool use; the gpt
  tiers point at `gpt-5.3-codex` until litellm's responses bridge covers
  it (#653).

**Breaking changes:** model alias renames described above (pre-1.0, no
compatibility guarantee was in effect). Post-1.0, alias names are stable.

## v0.9.0 — Delegate mode, reconcile mode, council reviews (May 2026)

- **Delegate mode** (`/agent-delegate`): Full design-to-implementation pipeline
  with no human pauses. 6 stages: design loop → council critique → optional
  implementation spec round → resolve → council code review → agentic code
  revision. Two independent iteration budgets (`max_iterations` and
  `max_design_iterations`). Optional `design_rounds=2` adds an implementation
  spec round between design and code.
- **Reconcile mode** (`/agent-reconcile`): Rebases a PR onto its base branch
  and resolves merge conflicts via the agent loop. Same status logs, cost
  reporting, and graceful wrapup as resolve mode.
- **Council mode for `/agent-review`**: Pass `council=true` to invoke all
  configured review models in parallel and post their critiques as separate
  comments on the PR.
- **Cumulative cost tables**: Per-step cost tables now include `Info/$`,
  `LOC/$`, and `Cumulative cost` rows. Delegate mode posts the full pipeline
  cost summary on the resulting PR rather than the source issue.

## v0.8.0 — Workshop mode, build mode, and context compaction (Mar 2026)

- **Workshop mode** (`/agent-workshop`): Two-stage multi-model design council.
  Stage 1 runs an agentic design exploration; Stage 2 runs parallel
  non-agentic critique from all council models. A human checkpoint sits between
  the two stages so you can steer before critique begins.
- **Build mode** (`/agent-build`): Two-stage build pipeline. Stage 1 resolves
  the issue (full agentic loop); Stage 2 posts parallel council code reviews
  directly on the resulting PR.
- **Context window compaction**: When the context grows too large, the oldest
  messages are summarized and replaced in place. Configurable via
  `max_context_tokens`, `compaction_coverage`, and `compaction_factor`.

**Breaking changes:** None.

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
