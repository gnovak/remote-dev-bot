# Contributing to Remote Dev Bot

This file documents the development and testing infrastructure. If you're a user looking to install remote-dev-bot, see [runbook.md](runbook.md).

## Repos

| Repo | Purpose |
|------|---------|
| `gnovak/remote-dev-bot` | The reusable workflow, config, tests, and docs (this repo) |
| `gnovak/remote-dev-bot-test` | Throwaway test repo. Shim points at `resolve.yml@dev`. Git history and issues don't matter — leave a mess. |

## Test Accounts

| Account | Purpose | PAT stored as |
|---------|---------|---------------|
| `gnovak` | Repo owner. Used for normal development and testing. | `PAT_TOKEN` (on both repos) |
| `remote-dev-bot-tester` | Simulates an unauthorized external user. NOT a collaborator on any repo. | `TESTER_PAT_TOKEN` (on remote-dev-bot) |

### remote-dev-bot-tester details
- Classic PAT with `public_repo` scope, no expiration
- Used by e2e security tests to verify that non-collaborators cannot trigger agent runs
- The PAT only works on public repos — the gating test requires repos to be public

## Secrets Map

Secrets stored on `gnovak/remote-dev-bot`:

| Secret | What it is |
|--------|-----------|
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude models) |
| `OPENAI_API_KEY` | OpenAI API key (for GPT models) |
| `GEMINI_API_KEY` | Google AI API key (for Gemini models) |
| `PAT_TOKEN` | Fine-grained PAT (gnovak). Scoped to all repos, with Contents/Issues/PRs/Workflows read-write. |
| `TESTER_PAT_TOKEN` | Classic PAT (remote-dev-bot-tester). `public_repo` scope only. For security e2e tests. |

Secrets stored on `gnovak/remote-dev-bot-test`:

| Secret | What it is |
|--------|-----------|
| `ANTHROPIC_API_KEY` | Same key as above (shared) |
| `OPENAI_API_KEY` | Same key as above (shared) |
| `GEMINI_API_KEY` | Same key as above (shared) |
| `PAT_TOKEN` | Same PAT as above (shared) |

## Dev Cycle

See [CLAUDE.md](CLAUDE.md) for the full dev cycle documentation, including how the `dev` branch pointer works and how to trigger test runs.

## Test Infrastructure

### Unit tests (`tests/test_config.py`, `tests/test_yaml.py`)
- Run with `pytest tests/ -v` (needs `PYTHONPATH=.`)
- CI runs these on PRs to main (`.github/workflows/test.yml`)

### E2E tests (`tests/e2e.sh`)
- Creates issues in remote-dev-bot-test, triggers agent, polls for completion
- Modes: `--provider claude` (one provider), `--all-models` (every alias)
- Run via GitHub Actions: `.github/workflows/e2e.yml` (workflow_dispatch)
- See `./tests/e2e.sh --help` for options

### Security e2e tests (`tests/e2e-security.sh`)
- Secret exfiltration: verify agent refuses to expose secrets
- User gating: verify non-collaborator comments don't trigger runs
- Requires repos to be public and uses `TESTER_PAT_TOKEN`

### Compiled workflow tests
- Unit tests (`tests/test_compile.py`): validate both compiled files (resolve and design) — structure, triggers, permissions, model aliases, security microagent
- E2E: `./tests/e2e.sh --compiled` swaps compiled workflows into the test repo, runs the full suite, then restores the shim. Use this before releases.

## Release Procedure

Releases distribute two compiled workflows (`agent-resolve.yml` and `agent-design.yml`) that users download into their repos.

### Steps

1. **Ensure main is clean**: all PRs merged, CI green.

2. **Run E2E tests against the compiled workflows**:
   ```bash
   ./tests/e2e.sh --compiled --provider claude
   ```
   This compiles both workflows, swaps them into the test repo, and runs the full test suite.

3. **Compile the release artifacts**:
   ```bash
   python3 scripts/compile.py dist/
   ```

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
