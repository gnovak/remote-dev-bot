# Contributing to Remote Dev Bot

This file documents the development and testing infrastructure. If you're a user looking to install remote-dev-bot, see [runbook.md](runbook.md).

## Repos

| Repo | Purpose |
|------|---------|
| `gnovak/remote-dev-bot` | The reusable workflow, config, tests, and docs (this repo) |
| `gnovak/remote-dev-bot-test` | Throwaway test repo. Shim points at `resolve.yml@dev`. Git history and issues don't matter — leave a mess. |

## Test Accounts

| Account | Purpose | Credentials stored as |
|---------|---------|----------------------|
| `gnovak` | Repo owner. Used for normal development and testing. | `RDB_PAT_TOKEN` (on both repos), or GitHub App (`RDB_APP_ID` variable + `RDB_APP_PRIVATE_KEY` secret) |
| `remote-dev-bot-tester` | Simulates an unauthorized external user. NOT a collaborator on any repo. | `TESTER_PAT_TOKEN` (on remote-dev-bot) |

### remote-dev-bot-tester details
- Classic PAT with `public_repo` scope, no expiration
- Used by e2e security tests to verify that non-collaborators cannot trigger agent runs
- The PAT only works on public repos — the gating test requires repos to be public

## GitHub App and Reserved Identities

### GitHub App: `remote-dev-bot`
- Created at https://github.com/settings/apps/remote-dev-bot (owned by `gnovak`)
- When used, the bot posts as `remote-dev-bot[bot]` — a clearly distinct identity from the repo owner
- App ID: `2895037`
- Installed on all `gnovak` repos (blanket install). Only repos with `RDB_APP_PRIVATE_KEY` secret actually use it. Currently configured on: `gnovak/remote-dev-bot`, `gnovak/remote-dev-bot-test`, `gnovak/bridge-analysis`
- Permissions: Contents, Issues, Pull Requests, Workflows (all Read & write)
  - **Workflows** is included because this app is used to dev rdb itself, which means the agent may need to modify `.github/workflows/` files. Regular rdb users should *not* grant their app Workflows permission — the runbook intentionally omits it.
- Webhooks: inactive (tokens are generated on-demand via `actions/create-github-app-token`)
- Private key stored as `RDB_APP_PRIVATE_KEY` secret; App ID stored as `RDB_APP_ID` variable

### Reserved GitHub username: `remote-dev-bot`
- Reserved for potential future use as a dedicated bot account
- Not currently active — the GitHub App approach is preferred over a dedicated user account

## Secrets Map

Secrets stored on `gnovak/remote-dev-bot`:

| Secret | What it is |
|--------|-----------|
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude models) |
| `OPENAI_API_KEY` | OpenAI API key (for GPT models) |
| `GEMINI_API_KEY` | Google AI API key (for Gemini models) |
| `RDB_PAT_TOKEN` | Fine-grained PAT (gnovak). Scoped to all repos, with Contents/Issues/PRs/Workflows read-write. |
| `RDB_APP_PRIVATE_KEY` | (Optional) GitHub App private key, for bot identity on comments/PRs. |
| `TESTER_PAT_TOKEN` | Classic PAT (remote-dev-bot-tester). `public_repo` scope only. For security e2e tests. |

Variables stored on `gnovak/remote-dev-bot`:

| Variable | Value | What it is |
|----------|-------|-----------|
| `RDB_APP_ID` | `2895037` | GitHub App ID for the "remote-dev-bot" app. Used with `RDB_APP_PRIVATE_KEY` to generate a short-lived token so the bot posts as `remote-dev-bot[bot]`. This is a variable (not a secret) because app IDs are public. Set on `remote-dev-bot`, `remote-dev-bot-test`, and `bridge-analysis`. |

Secrets stored on `gnovak/remote-dev-bot-test`:

| Secret | What it is |
|--------|-----------|
| `ANTHROPIC_API_KEY` | Same key as above (shared) |
| `OPENAI_API_KEY` | Same key as above (shared) |
| `GEMINI_API_KEY` | Same key as above (shared) |
| `RDB_PAT_TOKEN` | Same PAT as above (shared) |

## Dev Cycle

See [AGENTS.md](AGENTS.md) for the full dev cycle documentation, including how the `dev` branch pointer works and how to trigger test runs.

## Test Infrastructure

### Unit tests (`tests/test_config.py`, `tests/test_yaml.py`)
- Run with `pytest tests/ -v` (needs `PYTHONPATH=.`)
- CI runs these on PRs to main (`.github/workflows/test.yml`)

### E2E tests (`tests/e2e.sh`)
- Creates issues in remote-dev-bot-test, triggers agent, polls for completion
- Modes: `--provider claude` (one model family), `--all-models` (every alias)
- Run via GitHub Actions: `.github/workflows/e2e.yml` (workflow_dispatch)
- See `./tests/e2e.sh --help` for options

### Security e2e tests (`tests/e2e-security.sh`)
- Secret exfiltration: verify agent refuses to expose secrets
- User gating: verify non-collaborator comments don't trigger runs
- Requires repos to be public and uses `TESTER_PAT_TOKEN`

### Loop prevention (not e2e tested — intentionally)
The design agent has two layers of defense against recursive loops (where its response starts with `/agent` and re-triggers itself): a prompt instruction telling the LLM not to do it, and a regex check that blocks the response if it does. We deliberately do NOT e2e test this, because the test itself would be dangerous — if the regex has a bug, the test creates the very loop it's trying to prevent, consuming LLM budget. The regex is well covered by unit tests (`tests/test_yaml.py::TestLoopPreventionRegex`). The shim's `startsWith(comment.body, '/agent-')` trigger requires `/` as the literal first character (leading whitespace defeats it), which provides an additional layer of safety.

### Compiled workflow tests
- Unit tests (`tests/test_compile.py`): validate both compiled files (resolve and design) — structure, triggers, permissions, model aliases, security microagent
- E2E: `./tests/e2e.sh --compiled` swaps compiled workflows into the test repo, runs the full suite, then restores the shim. Use this before releases.

### Full test suite (`.github/workflows/full-test-suite.yml`)
- One-button "run everything" workflow: unit tests → e2e shim → e2e compiled → e2e security
- Jobs run **sequentially** — all e2e tests share `remote-dev-bot-test` and cannot run in parallel (shared dev pointer, workflow files, and issues)
- Use before releases to validate everything in one go

### Shared state constraint
All e2e tests (functional, compiled, security) use `remote-dev-bot-test` as their target repo. They share:
- The `dev` branch pointer (set to the branch under test)
- Workflow files in the test repo (compiled tests swap out the shim)
- Issues and PRs created during the test run

**Do not run e2e workflows in parallel.** Use the full test suite workflow for sequential execution, or run individual workflows one at a time.

## Release Procedure

Releases distribute two compiled workflows (`agent-resolve.yml` and `agent-design.yml`) that users download into their repos.

### Steps

1. **Ensure main is clean**: all PRs merged, CI green.

2. **Run E2E tests against the shim-based workflow** (tests the reusable workflow on main):
   ```bash
   ./tests/e2e.sh --provider claude
   ```

3. **Run E2E tests against the compiled workflows** (tests the standalone install):
   ```bash
   ./tests/e2e.sh --compiled --provider claude
   ```

   Both must pass before proceeding.

4. **Compile the release artifacts**:
   ```bash
   python3 scripts/compile.py dist/
   ```

5. **Tag the release**:
   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z: summary of changes"
   git push origin vX.Y.Z
   ```

6. **Create the GitHub release** with both compiled workflows:
   ```bash
   gh release create vX.Y.Z dist/agent-resolve.yml dist/agent-design.yml \
     --title "vX.Y.Z" \
     --notes "Release notes here"
   ```

### What goes in a release

- Two compiled workflow files: `agent-resolve.yml` (issue resolution) and `agent-design.yml` (design analysis). Both are self-contained with inlined config, model aliases, and security guardrails.
- Users who installed via compiled workflows get updates by downloading the new release.
- Users who installed via the shim get updates automatically (the shim calls `resolve.yml@main`).
