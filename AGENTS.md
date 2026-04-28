# AGENTS.md

Project conventions for AI coding agents working on this repository.

## Project

Remote Dev Bot — a GitHub Action that runs an AI coding agent to resolve issues and create PRs, controlled via `/agent-resolve`, `/agent-design`, and `/agent-review` comments on GitHub issues and PRs.

### How It Works
1. User comments `/agent-resolve[-<model>]`, `/agent-design[-<model>]`, or `/agent-review[-<model>]` on a GitHub issue or PR
2. Target repo's shim workflow calls `remote-dev-bot.yml` from this repo
3. Reusable workflow parses the mode and model, dispatches to the right job
4. **Resolve mode**: `lib/resolve.py` runs a LiteLLM agent loop — explores the repo, edits files, commits, opens a PR
5. **Design mode**: LiteLLM agent loop analyzes the issue and posts a design comment
6. **Review mode**: LiteLLM agent loop reviews a PR diff and posts a code review comment
7. Iterative: comment `/agent-resolve` again on the PR with feedback for another pass

### Key Files

**Workflows** (`.github/workflows/`):
- `remote-dev-bot.yml` — the reusable workflow; all real logic; jobs: `parse`, `resolve`, `design`, `review`, `workshop`, `build`
- `agent.yml` — thin shim users copy into their repos; calls `remote-dev-bot.yml@main`
- `dogfood.yml` — internal shim for rdb self-dev; fires on `/dogfood` comments; calls `remote-dev-bot.yml@dev`
- `test.yml` — CI: runs pytest on PRs to main
- `e2e.yml` — manual trigger for E2E tests against `remote-dev-bot-test`
- `e2e-security.yml` — manual trigger for security E2E tests (verifies collaborator gate blocks outsiders)
- `full-test-suite.yml` — runs unit tests + all E2E tests together

**Python**:
- `lib/resolve.py` — the resolve agent loop: tools (bash, read_file, grep, finish), system prompt construction, main loop, git setup, PR creation. Reads config from env vars set by the workflow.
- `lib/context.py` — shared context management: `trim_tool_results` (drop old tool call pairs), `compact_messages` (LLM-summarize oldest messages), `estimate_tokens`
- `lib/config.py` — config parsing: `parse_invocation`, `parse_args`, `resolve_config`, `normalize_config`, `ALLOWED_ARGS`; called by the workflow and unit tests
- `lib/feedback.py` — install feedback collection: `InstallReport`, `InstallProblem`, `report_problems`; used during runbook execution

**Tests** (`tests/`):
- `test_config.py` — unit tests for all `lib/config.py` functions
- `test_compaction.py` — unit tests for `lib/context.py` compaction functions
- `test_yaml.py` — structural/validity tests for YAML files (workflow and config)
- `test_syntax.py` — `py_compile` check for every .py file under `lib/` and `scripts/`; catches SyntaxErrors that wouldn't be caught by import-based tests
- `test_cost.py` — tests for cost parsing helpers (`parse_cost_from_comment` bash function in `e2e.sh`)
- `test_feedback.py` — unit tests for `lib/feedback.py`
- `e2e.sh` — full E2E test runner; creates issues in `remote-dev-bot-test`, triggers runs, checks results
- `e2e-security.sh` — security-specific E2E tests

**Config**:
- `remote-dev-bot.yaml` — model aliases and agent settings (canonical config; also serves as template for user repos)
- `remote-dev-bot.local.yaml` — local overrides (gitignored); use for dev without affecting CI
- `install.md` — setup instructions designed to be followed by humans or AI assistants

**Note on config layering:** The config system loads three layers: base (`remote-dev-bot.yaml` in this repo) → target repo override → local (`.local.yaml`). `normalize_config()` in `lib/config.py` runs on each layer before merging to handle renamed keys. Do NOT document the `.local.yaml` mechanism in user-facing docs (README.md, how-it-works.md, install.md) — it belongs only in CONTRIBUTING.md. User-facing docs describe only the two-layer system: base + target repo override.

### Running Tests

```bash
# All unit tests
pytest tests/ -q

# Specific test file
pytest tests/test_config.py -v

# With doctests
pytest --doctest-modules lib/config.py
```

## Codebase Index

### Agent loop internals (`lib/resolve.py`)

Each iteration: call `completion(model, messages, tools, max_tokens=16384)` → extract tool calls → execute each (bash / read_file / grep / finish) → append role=`tool` results → repeat. A single assistant message may have multiple tool_calls; `trim_tool_results()` drops the oldest **pairs** (assistant + all its tool results), not individual messages.

**Wrapup:** At `WRAPUP_ITERATION` (default 80% of `MAX_ITERATIONS`), a user message is injected instructing the agent to commit and call `finish()` immediately. The loop still runs but the agent should stop exploring and wrap up.

**Context compaction:** When estimated tokens exceed 85% of `MAX_CONTEXT_TOKENS`, `compact_messages()` in `lib/context.py` summarizes the oldest `compaction_coverage` fraction of messages via a one-shot LLM call and replaces them with the summary. Disabled by default (`max_context_tokens=0`).

**`finish()` tool args:** `success` (bool), `explanation`, `pr_title`, `pr_body`, `conversation_summary`. After finish, resolve.py calls `gh pr create` and writes `/tmp/llm_usage.json` (cost/tokens) and `/tmp/resolve_status.json`.

**Bash truncation:** If output > `BASH_OUTPUT_LIMIT` chars, the context gets first-half + last-half only (agent is told). Full output still appears in workflow logs.

### Config → env var data flow

`parse` job runs `lib/config.py`, writes outputs via `$GITHUB_OUTPUT`. Downstream jobs consume them via `${{ needs.parse.outputs.name }}` and export to Python via the job's `env:` block. Key mappings:

| Config field | GITHUB_OUTPUT | resolve.py env var |
|---|---|---|
| model id | `model` | `LLM_MODEL` |
| model alias | `alias` | `ALIAS` |
| max_iterations | `max_iterations` | `MAX_ITERATIONS` |
| extra_files | `extra_files` | `EXTRA_FILES` |
| extra_instructions | `extra_instructions` | `EXTRA_INSTRUCTIONS` |
| model extra_instructions | `model_extra_instructions` | `MODEL_EXTRA_INSTRUCTIONS` |
| bash_output_limit | `bash_output_limit` | `BASH_OUTPUT_LIMIT` |
| max_context_tokens | `max_context_tokens` | `MAX_CONTEXT_TOKENS` |
| graceful_wrapup.threshold | `wrapup_iteration` | `WRAPUP_ITERATION` |
| council (JSON) | `council_models` | `COUNCIL_MODELS` |

### Workshop / build mechanics

**Workshop Stage 1** = design mode agentic loop (`lib/design_loop.py`), reads the codebase, calls `submit_analysis()` tool, posts result as issue comment.

**Workshop Stage 2** (`lib/workshop.py`): each council model gets a single non-agentic LLM call with the Stage 1 analysis as input. No codebase access. Cheap (~7K tokens each). Results posted as individual issue comments. Human checkpoint before Stage 2 — user can steer.

**Build Stage 1** = resolve mode (opens a PR). **Build Stage 2** = council code review on the PR diff (same non-agentic pattern as workshop Stage 2).

**`extra_instructions` composition:** mode-level `extra_instructions` + model-level `extra_instructions` are both appended to the system prompt. Council reviewers get the same composition but per their own model entry.

### Key patterns

- `normalize_config()` must run on each YAML layer before merging to handle legacy key renames.
- Adding a per-invocation arg: `ALLOWED_ARGS` in `config.py` → `resolve_config()` → `main()` GITHUB_OUTPUT write → workflow `env:` block → `os.environ.get()` in `resolve.py`.
- Adding a provider: update `KNOWN_PROVIDERS` in `config.py`; add API key check to **all five** "Determine API key" steps in the workflow (resolve, design, review, workshop, build).
- Mode names must be single words — the command parser splits `/agent-<verb>-<model>` on the first hyphen.

## Common Tasks — Where to Look

### Adding a new per-invocation argument (e.g., `foo_bar = value` in a comment)

1. Add to `ALLOWED_ARGS` in `lib/config.py` (name → type)
2. Add handling in `resolve_config()` where other args are applied (search for `if "branch" in args` as an example)
3. If it produces a workflow output, add it to the `GITHUB_OUTPUT` writes in `main()`
4. If resolve.py needs it, add `FOO_BAR = os.environ.get("FOO_BAR", ...)` in `lib/resolve.py` and add the env var to the "Resolve issue" step in `remote-dev-bot.yml`
5. Add tests in `tests/test_config.py`
6. **Data flow**: comment body → `parse_invocation` → `parse_args` → `ALLOWED_ARGS` validation → `resolve_config` → `main` → GITHUB_OUTPUT → workflow env var → `lib/resolve.py`

### Adding or modifying a workflow step

1. Edit the step in `.github/workflows/remote-dev-bot.yml`
2. If the step affects branch-aware jobs (design/workshop/delegate) or token plumbing, the assertions in `tests/test_yaml.py` may need updating

### Adding a new mode

1. Add the mode to `remote-dev-bot.yaml` under `modes:` with an `action:` field
2. Add a job to `.github/workflows/remote-dev-bot.yml`
3. `resolve_config()` in `lib/config.py` reads the mode's config from the YAML — no code change needed unless the mode has a novel output field

> **Mode names must be single words (no hyphens).** The command parser splits
> `/agent-<verb>-<model>` on the first hyphen to separate verb from model alias,
> so a hyphenated mode name like `very-cool` would be misread as verb `very`.
> Model aliases, which are user-defined, may contain any number of hyphens.

### Adding a new model provider (e.g., a new LLM vendor)

1. Add the provider prefix to `KNOWN_PROVIDERS` in `lib/config.py` (e.g., `"newvendor/"`)
2. Add an API key check in the "Determine API key" step of `.github/workflows/remote-dev-bot.yml` — there are five copies (resolve, design, review, workshop, build); update all of them
3. Add model aliases under `models:` in `remote-dev-bot.yaml` with IDs using the new prefix
4. Add the API key secret (`NEWVENDOR_API_KEY`) to the secrets passed through in `agent.yml` and `dogfood.yml`
5. Update the runbook.md to mention the new provider as an option

### Changing the cost/metrics step

The cost step in `remote-dev-bot.yml` reads `/tmp/llm_usage.json` (written by `lib/resolve.py` and the design/review loops) and formats a cost summary comment. `test_cost.py` tests the `parse_cost_from_comment` bash function in `e2e.sh`. After changing the cost step, run `pytest tests/test_cost.py -v`.

## Inline Args System

Users can pass per-invocation arguments on lines after the command:

```
/agent resolve
max iterations = 75
extra_files = extra-file.md
target branch = design/gemini
```

**How it flows:**

- `COMMENT_BODY` env var carries the full comment text into `lib/config.py`
- `parse_invocation(comment_body, known_modes, command_prefix)` splits the first line (command) from subsequent lines (args)
- `parse_args(lines)` parses `name = value` lines; `normalize_arg_name` maps spaces/dashes/underscores to underscores
- `ALLOWED_ARGS` in `lib/config.py` defines accepted names and types; unknown names are rejected with an error
- `resolve_config(..., args=...)` applies parsed args on top of YAML config
- `extra_files` **appends** to the mode's existing list (does not replace)

## Branch Model

| Branch     | Purpose                                                         | Who points here            |
| ---------- | --------------------------------------------------------------- | -------------------------- |
| `main`     | Stable, released, tagged                                        | External users' shims      |
| `dev`      | Long-lived integration branch, accumulates work ahead of `main` | Owner's own repo shims     |
| `e2e-test` | Ephemeral pointer, reset by e2e scripts before each test run    | `remote-dev-bot-test` shim |

**All development goes on `dev`. Every PR branches from `origin/dev` and targets `dev`. No exceptions — bug fixes, doc changes, config-only tweaks, one-line typos, all of it.**

**Why no "bug-fix → main" shortcut:** in the past, landing a fix on `main` and then independently "re-fixing" the same bug on `dev` produced two divergent fixes in the same files, creating a landmine for the eventual `dev → main` merge. That actually happened (see PRs #488 / #503 / #512 / #513 on this repo) and cost real cleanup work. The cost of keeping everything on `dev` is much lower than the cost of one bad merge.

**Standard workflow:** `git checkout -b my-change origin/dev` → PR → merge to `dev`

**CRITICAL — always branch from the remote ref, not the local ref:**

```bash
git checkout -b my-change origin/dev   # CORRECT
git checkout -b my-change dev          # WRONG — local ref may be stale
```

`git fetch` updates `origin/dev` but does NOT move local `dev`. Using the local ref silently branches from a stale commit.

**Base-branch confirmation rule (for AI agents):** if for any reason you are about to open a PR whose base branch is **not** `dev` (e.g., you believe a revert on `main` is required), STOP before running `gh pr create` and explicitly ask the user to confirm the base branch. Do not assume the exception is warranted — make the user say "yes, base=main" in words. The common failure mode is opening a main-targeting PR on autopilot when dev was the right target.

### Dev Cycle (detailed)

This project has an unusual dev cycle because GitHub Actions only runs workflows from the default branch. You can't just push a feature branch and test it — the workflow won't trigger. Instead, we use a two-repo setup with an `e2e-test` pointer branch.

**Repos:**

- `remote-dev-bot` — the reusable workflow, config, and docs (this repo)
- `remote-dev-bot-test` — a test repo whose shim points at `remote-dev-bot.yml@e2e-test`

**How the `e2e-test` branch works:**

- `e2e-test` is NOT a development branch. It's an ephemeral pointer reset before each e2e run.
- Before testing, force-set `e2e-test` to your feature branch: `git push --force-with-lease origin my-feature:e2e-test`
- The test repo's shim calls `remote-dev-bot.yml@e2e-test`, so it picks up whatever `e2e-test` points to.

**Config/lib checkout is self-referential:**

- `remote-dev-bot.yml` reads `github.workflow_ref` to detect which branch it was called from, then checks out `remote-dev-bot.yaml` and `lib/` from that same branch
- Changes to `lib/config.py`, `lib/resolve.py`, or `remote-dev-bot.yaml` on your feature branch take effect automatically when `e2e-test` points at your branch

**Full dev cycle:**

1. Create a feature branch from `dev`: `git checkout -b my-feature origin/dev`
2. Make changes, commit freely
3. Point `e2e-test` at your branch: `git push --force-with-lease origin my-feature:e2e-test`
4. In `remote-dev-bot-test`: create an issue, comment `/agent-resolve-claude-small`
5. Monitor: `gh run list --repo gnovak/remote-dev-bot-test --workflow=agent.yml --limit 3`
6. If it fails: check logs, fix, commit, push `e2e-test` again, re-trigger
7. If it works: clean up git history (rebase), open a PR against `dev`, merge

**Triggering a test:**

```bash
# Create issue
gh issue create --repo gnovak/remote-dev-bot-test \
  --title "Test: description" --body "What to do"
# Trigger agent
gh issue comment ISSUE_NUM --repo gnovak/remote-dev-bot-test \
  --body "/agent-resolve-claude-small"
# Monitor
gh run list --repo gnovak/remote-dev-bot-test --workflow=agent.yml --limit 3
# Check logs on failure
gh run view RUN_ID --repo gnovak/remote-dev-bot-test --log | tail -40
```

## PR Policy

- **All changes go through a PR. Never commit or push directly to `main` or `dev`.** Open a PR and let the user merge it.
- For small changes, a single-commit PR self-merged immediately is fine — the point is the artifact, not the review ceremony.
- **Issue references in PR bodies: `Fixes #NNN` only.** Do not casually mention issue numbers (e.g., "related to #NNN", "follow-up to #NNN", "see #NNN for context"). Every `#NNN` reference in a PR body creates a "mentioned this issue" entry in the issue timeline. Since PRs target `dev` (not `main`), GitHub won't auto-close issues on merge — we close them manually. Stray mentions make it hard to scan the timeline and tell which PRs actually resolve which issues. If a PR doesn't close an issue, don't reference the issue number in the PR body at all.

## Commit Attribution

Sign every commit with a `Co-Authored-By` trailer that identifies you (the model) by name and version:

```
Co-Authored-By: <Your Model Name and Version> <noreply@your-provider.com>
```

Fill in your actual model name, version, and your provider's noreply address. For example, a Gemini model might use `noreply@google.com`; an OpenAI model `noreply@openai.com`. Use whatever is accurate for your model.

## Code Style

- Follow existing patterns in the codebase
- Keep implementations simple and focused
- Document non-obvious design decisions in comments

## Runbook Execution

When executing `install.md` to set up remote-dev-bot for a user:

### Problem Collection

- **Collect problems automatically** as you go through phases — the user should not need to provide this information
- Use `InstallReport` to track problems; it auto-collects environment info (OS, shell, Python version)
- When a step fails or requires a workaround, call `report.add_problem()` with the details
- Use `InstallProblem.from_exception()` as a convenience when catching exceptions

### What to Record

For each problem, capture:

- **step**: The step number (e.g., "2.1")
- **title**: The step title (e.g., "Enable Actions Permissions")
- **result**: "fail" (step didn't work) or "deviate" (worked but differently than documented)
- **expected**: What the runbook said should happen
- **actual**: What actually happened (error message, unexpected behavior)
- **workaround**: What you did instead (optional)
- **suggested_fix**: How to update the runbook (optional)

### Security

**Do not include secrets in problem reports.** This includes:

- API keys, tokens, passwords
- Repository contents that might contain secrets
- Environment variables that might contain secrets

You have no reason to include secrets in error reports, so this should be straightforward.

### Consent

- The consent step is the **only user interaction required** for feedback
- Use `get_consent_prompt(report)` to show the user what will be reported
- Only call `report_problems()` if the user explicitly consents
- Never auto-consent or skip the consent prompt
