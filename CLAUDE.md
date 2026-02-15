# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- `examples/agent.yml` — shim template for target repos to copy
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
4. In `remote-dev-bot-test`: create an issue, comment `/agent-resolve-claude-medium`
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
  --body "/agent-resolve-claude-medium"
# Monitor
gh run list --repo gnovak/remote-dev-bot-test --workflow=agent.yml --limit 3
# Check logs on failure
gh run view RUN_ID --repo gnovak/remote-dev-bot-test --log | tail -40
```

## Git Workflow Preferences

### Git Push/Merge Policy

**Allowed freely:**
- `git push` to any branch that isn't `main` (including `--force-with-lease` for rebased branches)
- `git merge` between non-main branches

**Restricted (ask the user first):**
- Any push to `main` (`git push origin main`)
- Merging into `main` (whether via `git merge` on main or `git push origin feature:main`)
- `git push --force` (without `--with-lease`) to any branch — always use `--force-with-lease` instead

### Two Modes of Git Usage
Git serves **two different purposes** depending on the phase of work:

### During Development: Work Log Mode
While actively developing, git is a **work log and safety net**:
- **Commit freely**: Track actual history as it happens - "this was the state on XYZ date at ABC time"
- **Don't clean up yet**: Keep all commits including fixes, iterations, debugging attempts
- **Value of messy history**: Helps with debugging, provides rollback points, shows how we got here
- **No premature rebasing**: Don't waste time cleaning up history that might change

Benefits:
- Easy to bisect and find when bugs were introduced
- Can easily revert to known working states
- Shows the actual development process for debugging

### Before Merging to Main: Clean History Mode
Before merging, **rebase to tell a clean story**:
- **Future readers don't care HOW**: They care about WHAT was built and WHY
- **Interactive rebase**: Clean up the commit history to show logical progression
- **Goal**: Make it look like we implemented everything correctly on the first try
- **Not about ego**: It's about making the permanent history useful and scannable

The cleaned history should show:
- What features/changes were made
- Why they were made (in commit messages)
- Logical organization (not chronological accidents)

### Example Workflow
```bash
# DURING DEVELOPMENT - commit as you go
git commit -m "Try fixing column visibility"
git commit -m "Oops, fix typo in previous commit"
git commit -m "Add debugging logs"
git commit -m "Remove debugging, actual fix for visibility"
git commit -m "Update based on PR feedback"

# BEFORE MERGING - clean up the story
git rebase -i main
# In editor: squash/fixup commits, reorder, rewrite messages
# Result: Clean commits like "Add column visibility feature"

# Rebase onto current main
git checkout main
git pull
git checkout feature-branch
git rebase main

# Merge with explicit merge commit
git checkout main
git merge --no-ff feature-branch -m "Merge feature: column visibility"
```

### Commit Message Guidelines (for cleaned history)
- Clear, descriptive commit messages that explain WHAT and WHY
- Include "Co-Authored-By: Claude <model_version> <noreply@anthropic.com>" on all commits with <model_verison> replaced by the model and version.
- Mark behavior changes explicitly in commit messages
- Separate refactoring from feature changes

### Branch Naming
- Use distinct branch names that won't be confused with existing branches
- Avoid names that differ by only one character (e.g., `add-config` vs `add-configs`)
- Check existing branches before creating a new one to avoid similar names

## Compiler: two-file output

`scripts/compile.py` produces two compiled workflows: `dist/agent-resolve.yml` and `dist/agent-design.yml`. It finds steps by **name** (not index), so reordering steps in resolve.yml is safe as long as step names don't change.

**Rule: if you rename a step in resolve.yml, update compile.py to match.** Run `pytest tests/test_compile.py -v` after changes — the unit tests validate the compiled output structure.

## Code Style
- Follow existing patterns in the codebase
- Keep implementations simple and focused
- Document non-obvious design decisions in comments
