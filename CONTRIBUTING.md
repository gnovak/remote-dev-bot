# Contributing to Remote Dev Bot

This file documents the development and testing infrastructure. If you're a user looking to install remote-dev-bot, see [runbook.md](runbook.md).

## Repos

| Repo | Purpose |
|------|---------|
| `gnovak/remote-dev-bot` | The reusable workflow, config, tests, and docs (this repo) |
| `gnovak/remote-dev-bot-test` | Throwaway test repo. Shim points at `resolve.yml@dev`. Git history and issues don't matter — leave a mess. |

## Test Accounts

Three separate GitHub identities are used so each role is cleanly separated:
- **`gnovak`** owns the repos and does normal development
- **`remote-dev-bot`** acts as a friendly collaborator, so e2e tests can trigger agent runs without polluting `gnovak`'s contribution stats and without special-casing the security gate
- **`remote-dev-bot-tester`** simulates an external stranger, so security tests can verify the collaborator gate actually blocks unauthorized users

| Account | Purpose | Credentials stored as |
|---------|---------|----------------------|
| `gnovak` | Repo owner. Used for normal development and testing. | `RDB_PAT_TOKEN` (on both repos), or GitHub App (`RDB_APP_ID` variable + `RDB_APP_PRIVATE_KEY` secret) |
| `remote-dev-bot` | Dedicated bot account. Collaborator on `remote-dev-bot-test`. Posts authorized test comments that trigger agent runs without attributing activity to `gnovak`. | `RDB_TESTER_PAT_TOKEN` (on remote-dev-bot) |
| `remote-dev-bot-tester` | Simulates an unauthorized external user. NOT a collaborator on any repo. | `RDB_TESTER_UNAUTHORIZED_PAT_TOKEN` (on remote-dev-bot) |

### remote-dev-bot (bot account) details
- Classic PAT with `public_repo` + `workflow` scopes, no expiration
- **`public_repo`** — create issues, post comments, open PRs in public repos (standard e2e test flow)
- **`workflow`** — read/write `.github/workflows/` files; required by compiled e2e tests, which temporarily swap the shim for the compiled workflow and must restore it afterwards. Without this scope, the swap fails with HTTP 404.
- Must be a collaborator on `remote-dev-bot-test` so the security gate allows its trigger comments
- Keeps test activity out of `gnovak`'s GitHub contribution stats

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
- Permissions (all Read & write): Contents, Issues, Pull Requests, Workflows, Actions, Checks
  - **Workflows** is included because this app devs rdb itself, so the agent may need to modify `.github/workflows/` files. Regular rdb users should *not* grant this — the runbook intentionally omits it.
  - **Actions + Checks** are included so the agent can inspect CI logs and check run results when debugging ("PR XYZ is failing, dig into the logs"). The OpenHands sandbox has `gh` CLI and GitHub API access, so these work. Regular rdb users don't need these unless they specifically want the agent to debug CI.
- Webhooks: inactive (tokens are generated on-demand via `actions/create-github-app-token`)
- Private key stored as `RDB_APP_PRIVATE_KEY` secret; App ID stored as `RDB_APP_ID` variable

### GitHub username: `remote-dev-bot`
- Active as a dedicated bot account (collaborator on `remote-dev-bot-test`)
- Used by e2e tests to post authorized trigger comments (see Test Accounts above)
- The GitHub App (`remote-dev-bot[bot]`) is a separate identity used for agent responses and PRs

## Secrets Map

Secrets stored on `gnovak/remote-dev-bot`:

| Secret | What it is |
|--------|-----------|
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude models) |
| `OPENAI_API_KEY` | OpenAI API key (for GPT models) |
| `GEMINI_API_KEY` | Google AI API key (for Gemini models) |
| `RDB_PAT_TOKEN` | Fine-grained PAT (gnovak). Scoped to all repos, with Contents/Issues/PRs/Workflows read-write. |
| `RDB_APP_PRIVATE_KEY` | (Optional) GitHub App private key, for bot identity on comments/PRs. |
| `RDB_TESTER_PAT_TOKEN` | PAT for `remote-dev-bot` account (collaborator on rdb-test). Used by e2e tests to post authorized trigger comments. |
| `RDB_TESTER_UNAUTHORIZED_PAT_TOKEN` | PAT for `remote-dev-bot-tester` (not a collaborator). Used by security e2e tests to verify unauthorized users are blocked. |

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

## Config Layering

rdb uses a three-layer config merge (each layer is optional, deeper layers win):

| Layer | Path | Source |
|-------|------|--------|
| Base | `.remote-dev-bot/remote-dev-bot.yaml` | rdb repo, via sparse-checkout |
| Override | `remote-dev-bot.yaml` | Target repo (user's settings) |
| Local | `remote-dev-bot.local.yaml` | Target repo (deepest override) |

All merges are deep (leaf-level), so overriding `modes.design.max_iterations`
does not clobber `modes.design.context_files`.  Lists replace entirely (no
concatenation).

### Self-dev local config (`remote-dev-bot.local.yaml`)

This file lives in the rdb repo root and applies when rdb is used to develop
itself.  It adds rdb implementation files (`lib/config.py`, etc.) to the design
agent's `context_files` so the design agent can see actual code rather than
guessing.

It is **not** distributed to users: the sparse-checkout uses non-cone mode and
only fetches `remote-dev-bot.yaml` and `lib/`, so `remote-dev-bot.local.yaml`
never appears in a user's `.remote-dev-bot/` directory.

Users can create their own `remote-dev-bot.local.yaml` if they want a third
config layer, but there is no documented use case for this — `remote-dev-bot.yaml`
already covers all user customisation needs.

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
- Requires repos to be public and uses `RDB_TESTER_PAT_TOKEN`

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

E2E tests cost real money (they invoke LLM APIs), so the full test suite is not automated. Run it manually before each release.

### Steps

1. **Ensure main is clean**: all PRs merged, unit CI green.

2. **Run the full test suite** via GitHub Actions → Full Test Suite → Run workflow (branch: main).
   - This runs unit tests → e2e shim (all models) → e2e compiled (all models) → e2e security, sequentially.
   - Do not trigger other e2e workflows while this is running — they share the test repo and will interfere.
   - If it fails, debug using targeted e2e triggers (one at a time), fix on a branch, merge to main, and re-run.

3. **Compile the release artifacts**:
   ```bash
   python scripts/compile.py
   ```
   This writes `dist/agent-resolve.yml` and `dist/agent-design.yml`. Commit the updated dist files if they changed.

4. **Tag the release**:
   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z: summary of changes"
   git push origin vX.Y.Z
   ```

5. **Create the GitHub release** with both compiled workflows:
   ```bash
   gh release create vX.Y.Z dist/agent-resolve.yml dist/agent-design.yml \
     --title "vX.Y.Z" \
     --notes "Release notes here"
   ```

### What goes in a release

- Two compiled workflow files: `agent-resolve.yml` (issue resolution) and `agent-design.yml` (design analysis). Both are self-contained with inlined config, model aliases, and security guardrails.
- Users who installed via compiled workflows get updates by downloading the new release.
- Users who installed via the shim get updates automatically (the shim calls `resolve.yml@main`).
