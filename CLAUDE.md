# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Remote Dev Bot — a GitHub Action that triggers an AI agent (OpenHands) to resolve issues and create PRs, controlled via `/agent` comments on GitHub issues.

### Key Files
- `remote-dev-bot.yaml` — model aliases and OpenHands settings
- `runbook.md` — setup instructions (designed to be followed by humans or AI assistants)
- `.github/workflows/agent.yml` — the GitHub Actions workflow
- `.openhands/microagents/repo.md` — (in target repos) context for the agent

### How It Works
1. User comments `/agent` or `/agent-<alias>` on a GitHub issue
2. Workflow parses the alias, looks up the model in `remote-dev-bot.yaml`
3. OpenHands resolver runs with that model, reads the issue, edits code, opens a draft PR
4. Iterative: comment `/agent` again on the PR with feedback for another pass

## Git Workflow Preferences

### Restricted Git Commands
Do NOT execute these git commands:
- `git push`
- `git merge`

The user will run these commands themselves. You can suggest them or explain what needs to be done, but do not execute them.

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

## Code Style
- Follow existing patterns in the codebase
- Keep implementations simple and focused
- Document non-obvious design decisions in comments
