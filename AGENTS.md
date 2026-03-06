# AGENTS.md

Project conventions for AI coding agents working on this repository.

## Project

Remote Dev Bot — a GitHub Action that triggers an AI agent to resolve issues
and create PRs, controlled via `/agent-resolve`, `/agent-design`, and
`/agent-review` comments on GitHub issues and PRs.

### How It Works

1. User comments `/agent-resolve[-<model>]`, `/agent-design[-<model>]`, or
   `/agent-review[-<model>]` on a GitHub issue or PR
2. Target repo's shim workflow calls `remote-dev-bot.yml` from this repo
3. Reusable workflow parses the mode and model, dispatches to the right job
4. Resolve mode: agent loop runs (`lib/resolve.py`), edits code, opens a PR.
   Design mode: LLM analyzes the issue, posts a comment. Review mode: LLM
   reviews a PR, posts a code review comment.
5. Iterative: comment `/agent-resolve` again on the PR with feedback for another
   pass

### Key Files

**Workflows** (`.github/workflows/`):

- `remote-dev-bot.yml` — the reusable workflow; all real logic; jobs: `parse`,
  `resolve`, `design`, `review`, `explore` (`explore` is dev-only, not yet released to `main`)
- `agent.yml` — thin shim users copy into their repos; calls
  `remote-dev-bot.yml@main`
- `dogfood.yml` — internal shim for rdb self-dev; fires on `/dogfood` comments;
  calls `remote-dev-bot.yml@dev`
- `test.yml` — CI: runs pytest on PRs to main
- `e2e.yml` — manual trigger for E2E tests against `remote-dev-bot-test`
- `e2e-security.yml` — manual trigger for security E2E tests (verifies
  collaborator gate blocks outsiders)
- `full-test-suite.yml` — runs unit tests + all E2E tests together

**Python**:

- `lib/config.py` — config parsing: `parse_invocation`, `parse_args`,
  `resolve_config`, `ALLOWED_ARGS`; called by the workflow and unit tests
- `lib/feedback.py` — install feedback collection: `InstallReport`,
  `InstallProblem`, `report_problems`; used during runbook execution
- `scripts/compile.py` — compiles `remote-dev-bot.yml` →
  `dist/agent-resolve.yml`, `dist/agent-design.yml`, `dist/agent-review.yml`;
  finds steps by **name** not index

**Tests** (`tests/`):

- `test_config.py` — unit tests for all `lib/config.py` functions
- `test_compile.py` — tests that compiled outputs contain expected steps
- `test_yaml.py` — structural/validity tests for YAML files (workflow and
  config)
- `test_cost.py` — tests for cost parsing helpers (`parse_cost_from_comment`
  bash function in `e2e.sh`)
- `test_feedback.py` — unit tests for `lib/feedback.py`
- `e2e.sh` — full E2E test runner; creates issues in `remote-dev-bot-test`,
  triggers runs, checks results
- `e2e-security.sh` — security-specific E2E tests

**Config**:

- `remote-dev-bot.yaml` — model aliases and agent settings (canonical config;
  also serves as template for user repos)
- `remote-dev-bot.local.yaml` — local overrides (gitignored); use for dev
  without affecting CI
- `install.md` — setup instructions designed to be followed by humans or AI
  assistants

**Note on config layering:** The config system has a `.local.yaml` override file
(`remote-dev-bot.local.yaml`) used in the remote-dev-bot repo itself for
self-development/dogfooding. This is a developer tool only — do NOT document it
in user-facing docs (README.md, how-it-works.md, install.md). It belongs only in
CONTRIBUTING.md. User-facing docs should describe only the two-layer system:
base config (in remote-dev-bot repo) + target repo override
(`remote-dev-bot.yaml` in the calling repo).

### Running Tests

```bash
# All unit tests
pytest tests/ -q

# Specific test file
pytest tests/test_config.py -v
pytest tests/test_compile.py -v    # Run after any workflow or compile.py changes

# With doctests
pytest --doctest-modules lib/config.py
```

## Common Tasks — Where to Look

### Adding a new per-invocation argument (e.g., `foo_bar = value` in a comment)

1. Add to `ALLOWED_ARGS` in `lib/config.py` (name → type)
2. Add handling in `resolve_config()` where other args are applied (search for
   `if "branch" in args` as an example)
3. If it produces a workflow output, add it to the `GITHUB_OUTPUT` writes in
   `main()`
4. Add tests in `tests/test_config.py`
5. **Data flow**: comment body → `parse_invocation` → `parse_args` →
   `ALLOWED_ARGS` validation → `resolve_config` → `main`

### Adding or modifying a workflow step

1. Edit the step in `.github/workflows/remote-dev-bot.yml`
2. Update `scripts/compile.py` if the step needs to appear in compiled output
   (compile.py finds steps by name)
3. Update expected step lists in `tests/test_compile.py` — the step-count
   tripwire tests will fail if the compiled output doesn't match
4. Run `pytest tests/test_compile.py -v` to verify

### Adding a new mode

1. Add the mode to `remote-dev-bot.yaml` under `modes:` with an `action:` field
2. Add a job to `.github/workflows/remote-dev-bot.yml`
3. `resolve_config()` in `lib/config.py` reads the mode's config from the YAML —
   no code change needed unless the mode has a novel output field

### Adding a new model provider (e.g., a new LLM vendor)

1. Add the provider prefix to `KNOWN_PROVIDERS` in `lib/config.py` (e.g.,
   `"newvendor/"`)
2. Add an API key check in the "Determine API key" step of
   `.github/workflows/remote-dev-bot.yml` — there are four copies (resolve,
   design, review, explore); update all of them
3. Add model aliases under `models:` in `remote-dev-bot.yaml` with IDs using the
   new prefix
4. Add the API key secret (`NEWVENDOR_API_KEY`) to the secrets passed through in
   `agent.yml` and `dogfood.yml`
5. Update the runbook.md to mention the new provider as an option

### Changing the cost/metrics step

The cost step in `remote-dev-bot.yml` reads `/tmp/llm_usage.json` (written by
`lib/resolve.py` and the design/review loops) and formats a cost summary comment.
`test_cost.py` tests the `parse_cost_from_comment` bash function in `e2e.sh`.
After changing the cost step, run `pytest tests/test_cost.py -v`.

## Inline Args System

Users can pass per-invocation arguments on lines after the command:

```
/agent resolve
max iterations = 75
context_files = extra-file.md
target branch = design/gemini
```

**How it flows:**

- `COMMENT_BODY` env var carries the full comment text into `lib/config.py`
- `parse_invocation(comment_body, known_modes, command_prefix)` splits the first
  line (command) from subsequent lines (args)
- `parse_args(lines)` parses `name = value` lines; `normalize_arg_name` maps
  spaces/dashes/underscores to underscores
- `ALLOWED_ARGS` in `lib/config.py` defines accepted names and types; unknown
  names are rejected with an error
- `resolve_config(..., args=...)` applies parsed args on top of YAML config
- `context_files` **appends** to the mode's existing list (does not replace)

## compile.py: Three-File Output

`scripts/compile.py` inlines config parsing and selected steps from
`remote-dev-bot.yml` into three standalone files: `dist/agent-resolve.yml`,
`dist/agent-design.yml`, and `dist/agent-review.yml`. It finds steps by **name**
(not index), so reordering steps is safe as long as step names don't change.

**Rule: if you add, remove, or rename a step in remote-dev-bot.yml, update
compile.py to match**, then run `pytest tests/test_compile.py -v`. The
step-count tripwire tests will catch mismatches.

## Branch Model

| Branch     | Purpose                                                         | Who points here            |
| ---------- | --------------------------------------------------------------- | -------------------------- |
| `main`     | Stable, released, tagged                                        | External users' shims      |
| `dev`      | Long-lived integration branch, accumulates work ahead of `main` | Owner's own repo shims     |
| `e2e-test` | Ephemeral pointer, reset by e2e scripts before each test run    | `remote-dev-bot-test` shim |

**PRs go to `dev`, not `main`**, unless the change is a bug fix or
doc/config-only.

**Feature workflow:** `git checkout -b my-feature origin/dev` → PR → merge to
`dev`

**Bug-fix workflow:** `git checkout -b my-fix origin/main` → PR → merge to
`main` → rebase `dev` onto new `main`

**CRITICAL — always branch from the remote ref, not the local ref:**

```bash
git checkout -b my-feature origin/dev   # CORRECT
git checkout -b my-feature dev          # WRONG — local ref may be stale
git checkout -b my-fix origin/main      # CORRECT
git checkout -b my-fix main             # WRONG — local ref may be stale
```

`git fetch` updates `origin/dev` and `origin/main` but does NOT move local `dev`
or `main`. Using the local ref silently branches from a stale commit.

### Dev Cycle (detailed)

This project has an unusual dev cycle because GitHub Actions only runs workflows
from the default branch. You can't just push a feature branch and test it — the
workflow won't trigger. Instead, we use a two-repo setup with an `e2e-test`
pointer branch.

**Repos:**

- `remote-dev-bot` — the reusable workflow, config, and docs (this repo)
- `remote-dev-bot-test` — a test repo whose shim points at
  `remote-dev-bot.yml@e2e-test`

**How the `e2e-test` branch works:**

- `e2e-test` is NOT a development branch. It's an ephemeral pointer reset before
  each e2e run.
- Before testing, force-set `e2e-test` to your feature branch:
  `git push --force-with-lease origin my-feature:e2e-test`
- The test repo's shim calls `remote-dev-bot.yml@e2e-test`, so it picks up
  whatever `e2e-test` points to.

**Config/lib checkout is self-referential:**

- `remote-dev-bot.yml` reads `github.workflow_ref` to detect which branch it was
  called from, then checks out `remote-dev-bot.yaml` and `lib/` from that same
  branch
- Changes to `lib/config.py` or `remote-dev-bot.yaml` on your feature branch
  take effect automatically when `e2e-test` points at your branch

**Full dev cycle:**

1. Create a feature branch from `dev`: `git checkout -b my-feature origin/dev`
2. Make changes, commit freely
3. Point `e2e-test` at your branch:
   `git push --force-with-lease origin my-feature:e2e-test`
4. In `remote-dev-bot-test`: create an issue, comment
   `/agent-resolve-claude-small`
5. Monitor:
   `gh run list --repo gnovak/remote-dev-bot-test --workflow=agent.yml --limit 3`
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

- **All changes go through a PR. Never commit or push directly to main.** Open a
  PR and let the user merge it.
- For small changes, a single-commit PR self-merged immediately is fine — the
  point is the artifact, not the review ceremony.

## Commit Attribution

Sign every commit with a `Co-Authored-By` trailer that identifies you (the
model) by name and version:

```
Co-Authored-By: <Your Model Name and Version> <noreply@your-provider.com>
```

Fill in your actual model name, version, and your provider's noreply address.
For example, a Gemini model might use `noreply@google.com`; an OpenAI model
`noreply@openai.com`. Use whatever is accurate for your model.

## Code Style

- Follow existing patterns in the codebase
- Keep implementations simple and focused
- Document non-obvious design decisions in comments

## Runbook Execution

When executing `install.md` to set up remote-dev-bot for a user:

### Problem Collection

- **Collect problems automatically** as you go through phases — the user should
  not need to provide this information
- Use `InstallReport` to track problems; it auto-collects environment info (OS,
  shell, Python version)
- When a step fails or requires a workaround, call `report.add_problem()` with
  the details
- Use `InstallProblem.from_exception()` as a convenience when catching
  exceptions

### What to Record

For each problem, capture:

- **step**: The step number (e.g., "2.1")
- **title**: The step title (e.g., "Enable Actions Permissions")
- **result**: "fail" (step didn't work) or "deviate" (worked but differently
  than documented)
- **expected**: What the runbook said should happen
- **actual**: What actually happened (error message, unexpected behavior)
- **workaround**: What you did instead (optional)
- **suggested_fix**: How to update the runbook (optional)

### Security

**Do not include secrets in problem reports.** This includes:

- API keys, tokens, passwords
- Repository contents that might contain secrets
- Environment variables that might contain secrets

You have no reason to include secrets in error reports, so this should be
straightforward.

### Consent

- The consent step is the **only user interaction required** for feedback
- Use `get_consent_prompt(report)` to show the user what will be reported
- Only call `report_problems()` if the user explicitly consents
- Never auto-consent or skip the consent prompt
