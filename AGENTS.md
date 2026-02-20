# AGENTS.md

Project conventions for AI coding agents working on this repository.

## Project

Remote Dev Bot — a GitHub Action that triggers an AI agent (OpenHands) to resolve issues and create PRs, controlled via `/agent-resolve` and `/agent-design` comments on GitHub issues.

### Key Files
- `remote-dev-bot.yaml` — model aliases and OpenHands settings
- `runbook.md` — setup instructions (designed to be followed by humans or AI assistants)
- `.github/workflows/resolve.yml` — the reusable workflow (all the real logic)
- `.github/workflows/agent.yml` — thin shim that calls resolve.yml
- `.github/workflows/test.yml` — CI: runs pytest on PRs to main
- `.github/workflows/e2e.yml` — manual trigger for E2E tests
- `lib/config.py` — config parsing logic (used by resolve.yml and unit tests)
- `scripts/compile.py` — compiles two self-contained workflows (`dist/agent-resolve.yml`, `dist/agent-design.yml`)
- `tests/` — pytest unit tests and E2E test script
- `.openhands/microagents/repo.md` — (in target repos) context for the agent

### How It Works
1. User comments `/agent-resolve[-<model>]` or `/agent-design[-<model>]` on a GitHub issue
2. Target repo's shim workflow calls `resolve.yml` from this repo
3. Reusable workflow parses the mode and model, dispatches to the right job
4. Resolve mode: OpenHands runs, edits code, opens a draft PR. Design mode: LLM analyzes the issue, posts a comment.
5. Iterative: comment `/agent-resolve` again on the PR with feedback for another pass

### Dev Cycle (detailed)

This project has an unusual dev cycle because GitHub Actions only runs workflows from the default branch. You can't just push a feature branch and test it — the workflow won't trigger. Instead, we use a two-repo setup with a `dev` pointer branch.

**Repos:**
- `remote-dev-bot` — the reusable workflow, config, and docs (this repo)
- `remote-dev-bot-test` — a test repo whose shim points at `resolve.yml@dev` (not `@main`)

**How the `dev` branch works:**
- `dev` is NOT a long-lived development branch. It's a pointer.
- Before testing, force-set `dev` to your feature branch: `git branch -f dev my-feature && git push --force-with-lease origin dev`
- The test repo's shim calls `resolve.yml@dev`, so it picks up whatever `dev` points to.
- Only one feature can be tested at a time (since there's only one `dev` pointer).

**Important: config/lib vs workflow code (the "main checkout" constraint):**
- The shim (`agent.yml`) determines which branch of `resolve.yml` to use (`@main` or `@dev`)
- But `resolve.yml` checks out `remote-dev-bot.yaml` and `lib/` in a separate step that always pulls from `main` — GitHub Actions doesn't expose which ref a reusable workflow was called with, so there's no way to say "use the same branch as myself"
- This means changes to `lib/config.py` or `remote-dev-bot.yaml` on your feature branch won't take effect in E2E tests unless they're already on `main`
- Workaround for config values: with config layering, you can put a `remote-dev-bot.yaml` in the target repo (remote-dev-bot-test) to override specific values during testing

**PR constraint — separate config parsing from workflow changes:**
- `lib/config.py` is checked out from `main` at runtime, but unit tests (pytest) run against the branch version
- If you change both config parsing logic AND workflow behavior in one PR, E2E tests will use the old (main) config.py with the new workflow — they won't match
- **Rule: config parsing changes (`lib/config.py`) go in their own PR, merged first.** Then workflow changes that depend on them go in a follow-up PR.
- This is usually natural: config changes tend to be additive ("add a new field"), and the code that reads the new field comes separately
- Unit tests catch config parsing bugs on the branch; E2E tests validate the full workflow after config changes reach main

**Full dev cycle:**
1. Create a feature branch from `main`: `git checkout -b my-feature main`
2. Make changes, commit freely (work log mode)
3. Point dev at your branch: `git branch -f dev my-feature && git push --force-with-lease origin dev`
4. In `remote-dev-bot-test`: create an issue, comment `/agent-resolve-claude-small`
5. Monitor: `gh run list --repo gnovak/remote-dev-bot-test --workflow=agent.yml --limit 3`
6. If it fails: check logs, fix, commit, push dev again, re-trigger
7. If it works: clean up git history (rebase), open a PR (dev → main), merge

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

- **All changes go through a PR. Never commit or push directly to main.** Open a PR and let the user merge it. This keeps GitHub's PR list as a complete, searchable record of every change.
- For small changes, a single-commit PR self-merged immediately is fine — the point is the artifact, not the review ceremony.

## Compiler: two-file output

`scripts/compile.py` produces two compiled workflows: `dist/agent-resolve.yml` and `dist/agent-design.yml`. It finds steps by **name** (not index), so reordering steps in resolve.yml is safe as long as step names don't change.

**Rule: if you add, remove, or rename a step in resolve.yml, update compile.py to match.** Run `pytest tests/test_compile.py -v` after changes — the step-count tripwire tests (`test_resolve_step_count`, `test_design_step_count`) will fail if the compiled output doesn't match the expected step list, forcing you to update both `compile.py` and the expected step lists in `test_compile.py`.

## Code Style
- Follow existing patterns in the codebase
- Keep implementations simple and focused
- Document non-obvious design decisions in comments

## Runbook Execution

When executing `runbook.md` to set up remote-dev-bot for a user:

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
