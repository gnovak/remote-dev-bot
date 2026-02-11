# Remote Dev Bot

An AI-powered development workflow where GitHub issues get resolved autonomously via pull requests — like having a remote colleague who checks GitHub between surf sessions.

## How It Works

1. Create a GitHub issue describing a feature or bug
2. Comment `/agent` (or `/agent-claude-large`, `/agent-openai`, etc.) on the issue
3. A GitHub Action spins up an AI agent (powered by [OpenHands](https://github.com/OpenHands/OpenHands)) that:
   - Reads the issue and codebase
   - Implements the requested changes
   - Opens a draft PR
4. Review the PR. If changes are needed, comment `/agent` on the PR with feedback and the agent runs again.

## Model Selection

Comment with an alias to choose the model:

| Command | Model |
|---------|-------|
| `/agent` | Default (Claude Haiku — fast and cheap) |
| `/agent-claude-small` | Claude Haiku |
| `/agent-claude-large` | Claude Opus |
| `/agent-openai` | GPT-4o |
| `/agent-gemini` | Gemini 2.0 Flash |

Aliases are configured in `remote-dev-bot.yaml`.

## Architecture

The system has two parts:

- **Shim workflow** (`.github/workflows/agent.yml`) — a thin trigger that lives in each target repo. Fires on `/agent` comments and calls the reusable workflow. See `examples/agent.yml` for the template.
- **Reusable workflow** (`.github/workflows/resolve.yml`) — all the logic: parses model aliases, installs OpenHands, resolves the issue, creates a draft PR. Lives in this repo and is called by shims in target repos.
- **OpenHands** — the AI agent framework that does the actual code exploration and editing
- **`remote-dev-bot.yaml`** — model aliases and OpenHands settings (version, max iterations, PR type)
- **`runbook.md`** — step-by-step setup instructions, designed to be followed by a human or by an AI assistant (like Claude Code)

## Setup

See `runbook.md` for complete setup instructions. The runbook is designed so you (or an AI assistant) can follow it step-by-step to get this running in your own GitHub account.

**Quick version:** You need a GitHub repo, API keys for your preferred LLM provider(s), and about 10 minutes.

## Development

GitHub Actions only runs workflows from the default branch (main), so developing remote-dev-bot requires a non-standard workflow.

**Repos:**
- `remote-dev-bot` — the reusable workflow, config, and docs
- `remote-dev-bot-test` — a test repo with the shim pointed at the `dev` branch of remote-dev-bot (instead of `main`)

**Dev cycle:**
1. In `remote-dev-bot`: reset `dev` to `main`, then make changes on `dev`
2. In `remote-dev-bot-test`: create an issue and comment `/agent-claude-medium` to trigger the agent
3. The shim in the test repo calls `resolve.yml@dev`, so it picks up your changes
4. If it works, clean up the git history on `dev` (squash, rebase, reword) and merge to `main`
5. If not, make more commits on `dev` and trigger the agent again

This keeps test issues out of the main repo and lets you iterate on workflow changes before they hit `main`.

## Current Status

**v0.1.0** — First working version (Feb 9, 2026). End-to-end pipeline operational: `/agent` comment on an issue triggers OpenHands, which resolves the issue and opens a draft PR. Tested with Claude Sonnet (`/agent-claude-medium`).
