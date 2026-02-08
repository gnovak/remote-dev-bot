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

- **GitHub Actions workflow** (`.github/workflows/agent.yml`) — triggers on issue/PR comments, parses the model alias, runs OpenHands
- **OpenHands** — the AI agent framework that does the actual code exploration and editing
- **remote-dev-bot.yaml** — model aliases and settings
- **runbook.md** — step-by-step setup instructions, designed to be followed by a human or by an AI assistant (like Claude Code)

## Setup

See `runbook.md` for complete setup instructions. The runbook is designed so you (or an AI assistant) can follow it step-by-step to get this running in your own GitHub account.

**Quick version:** You need a GitHub repo, API keys for your preferred LLM provider(s), and about 10 minutes.

## Current Status

MVP in development. See `runbook.md` for what's implemented and what's planned.
