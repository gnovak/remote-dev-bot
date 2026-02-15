# Remote Dev Bot

An AI-powered development workflow where GitHub issues get resolved autonomously via pull requests — like having a remote colleague who checks GitHub between surf sessions. Using shell-based agents feels like pair programming, which is a valuable mode of collaboration, but sometimes you want something that feels more like delegating work to an experienced coworker. This system aims to provide that alternative.

There are already excellent vendor-specific implementations of this pattern (GitHub Copilot Workspace, Cursor, etc.), so this project isn't necessarily better than those. However, it's intentionally cross-platform and was built as a learning exercise — a way to understand the agent tooling space and explore how to design agents that can autonomously handle real development tasks.

## How It Works

1. Create a GitHub issue describing a feature or bug
2. Comment `/agent-resolve` (or `/agent-resolve-claude-large`, etc.) to trigger implementation
3. A GitHub Action spins up an AI agent (powered by [OpenHands](https://github.com/OpenHands/OpenHands)) that:
   - Reads the issue and codebase
   - Implements the requested changes
   - Opens a draft PR
4. Review the PR. If changes are needed, comment `/agent-resolve` on the PR with feedback for another pass.

Or use `/agent-design` to get AI design analysis posted as a comment (no code changes).

**See it in action:** [Issue #33](https://github.com/gnovak/remote-dev-bot/issues/33) asked for model name documentation → [PR #52](https://github.com/gnovak/remote-dev-bot/pull/52) was created and merged autonomously.

## Commands

| Command | What it does |
|---------|-------------|
| `/agent-resolve` | Resolve the issue and open a PR (default model) |
| `/agent-resolve-claude-large` | Resolve with a specific model |
| `/agent-design` | Post design analysis as a comment (no code changes) |
| `/agent-design-claude-small` | Design analysis with a specific model |

Modes and model aliases are configured in `remote-dev-bot.yaml`.

### Understanding Model Names

Model aliases (like `claude-medium`) map to **LiteLLM model identifiers** in `remote-dev-bot.yaml`. LiteLLM is the library OpenHands uses to talk to different LLM providers through a unified interface.

**Model ID format:** `provider/model-name`

| Provider | Prefix | Example |
|----------|--------|---------|
| Anthropic (Claude) | `anthropic/` | `anthropic/claude-sonnet-4-5` |
| OpenAI (GPT) | `openai/` | `openai/gpt-5.1-codex-mini` |
| Google (Gemini) | `gemini/` | `gemini/gemini-2.5-flash` |

### Finding Valid Model Names

OpenHands uses LiteLLM, so the model strings must be valid LiteLLM identifiers. Browse available models at **[models.litellm.ai](https://models.litellm.ai)** — search by name, filter by provider, and see context windows and pricing.

Prefix the model string with the provider name in `remote-dev-bot.yaml` (e.g., `anthropic/claude-sonnet-4-5`).

### Choosing a Model

**For most tasks:** Use the default (`/agent-resolve`). Claude Sonnet offers a good balance of capability and cost.

**For complex multi-file features:** Use `/agent-resolve-claude-large` (Opus) or `/agent-resolve-openai-large` (GPT Codex). These models handle larger contexts and more intricate reasoning.

**For simple, well-defined tasks:** Use `/agent-resolve-claude-small` (Haiku) or `/agent-resolve-gemini-small`. Faster and cheaper, but may struggle with ambiguous requirements.

**For coding-heavy tasks:** Models with "codex" in the name (e.g., `openai/gpt-5.1-codex-mini`) are specifically tuned for code generation and may perform better on implementation tasks.

### Customizing Models

To add or modify model aliases, edit `remote-dev-bot.yaml`:

```yaml
models:
  my-custom-alias:
    id: anthropic/claude-sonnet-4-5
    description: "My custom model configuration"
```

You can also create a `remote-dev-bot.yaml` in your target repo to override the defaults. See `runbook.md` Phase 5 for details.

## Architecture

The system has two parts:

- **Shim workflow** (`.github/workflows/agent.yml`) — a thin trigger that lives in each target repo. Fires on `/agent-` commands and calls the reusable workflow. See `examples/agent.yml` for the template.
- **Reusable workflow** (`.github/workflows/resolve.yml`) — all the logic: parses commands, dispatches to resolve or design mode, runs the agent. Lives in this repo and is called by shims in target repos.
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
2. In `remote-dev-bot-test`: create an issue and comment `/agent-resolve-claude-medium` to trigger the agent
3. The shim in the test repo calls `resolve.yml@dev`, so it picks up your changes
4. If it works, clean up the git history on `dev` (squash, rebase, reword) and merge to `main`
5. If not, make more commits on `dev` and trigger the agent again

This keeps test issues out of the main repo and lets you iterate on workflow changes before they hit `main`.

For detailed dev cycle instructions (especially for AI assistants like Claude Code), see `CLAUDE.md`.

## LLM Provider Quick Reference

Dashboard, billing, and API key management links for each supported provider.

**Anthropic (Claude)**
- [Dashboard](https://console.anthropic.com/dashboard) · [API keys](https://console.anthropic.com/settings/keys) · [Usage](https://console.anthropic.com/settings/usage) · [Limits](https://console.anthropic.com/settings/limits) · [Billing](https://console.anthropic.com/settings/billing)

**OpenAI (GPT)**
- [Dashboard](https://platform.openai.com/settings/organization/billing/overview) · [API keys](https://platform.openai.com/api-keys) · [Usage](https://platform.openai.com/account/usage) · [Limits](https://platform.openai.com/account/billing/limits) · [Billing](https://platform.openai.com/settings/organization/billing/overview)

**Google (Gemini)**
- [API keys](https://aistudio.google.com/app/apikey) · [Usage & rate limits](https://aistudio.google.com/app/usage) · [Projects](https://aistudio.google.com/app/projects)
- Google AI Studio is the simplest way to manage Gemini API keys. It's a lightweight frontend to the same API available through Google Cloud Console.

## Current Status

**v0.3.0** — Mode-based commands + compiled workflows (Feb 15, 2026). Two command modes: `/agent-resolve` (opens PR) and `/agent-design` (posts analysis comment). Multi-provider support (Claude, GPT, Gemini). Two-file compiled install. Security guardrails and config layering. See [CHANGELOG.md](CHANGELOG.md) for details.

**v0.2.0** — Shim + reusable workflow (Feb 11, 2026). Refactored into a thin shim per target repo that calls a shared reusable workflow. Cross-repo support tested with separate test repo.

**v0.1.0** — First working version (Feb 9, 2026). End-to-end pipeline operational: `/agent` comment on an issue triggers OpenHands, which resolves the issue and opens a draft PR.
