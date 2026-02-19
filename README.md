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

**See it in action:**

- **Simple resolve:** [Issue #33](https://github.com/gnovak/remote-dev-bot/issues/33) asked for model name documentation → [PR #52](https://github.com/gnovak/remote-dev-bot/pull/52) was created and merged autonomously.

- **Design then resolve:** [Issue #124](https://github.com/gnovak/remote-dev-bot/issues/124) asked whether commands should be case-insensitive (for mobile autocorrect) → `/agent-design` posted [analysis with a recommendation](https://github.com/gnovak/remote-dev-bot/issues/124#issuecomment-3912240858) → human agreed → `/agent-resolve` created [PR #131](https://github.com/gnovak/remote-dev-bot/pull/131), merged.

- **Resolve with feedback:** [Issue #95](https://github.com/gnovak/remote-dev-bot/issues/95) asked about preventing agent loops → `/agent-resolve` created [PR #109](https://github.com/gnovak/remote-dev-bot/pull/109) → reviewer [pointed out a regex bypass vulnerability](https://github.com/gnovak/remote-dev-bot/pull/109#issuecomment-3909533145) → `/agent-resolve` on the PR fixed it → merged.

## Commands

| Command | What it does |
|---------|-------------|
| `/agent-resolve` | Resolve the issue and open a PR (default model) |
| `/agent-resolve-claude-large` | Resolve with a specific model |
| `/agent-design` | Post design analysis as a comment (no code changes) |
| `/agent-design-claude-large` | Design analysis with a specific model |

Modes and model aliases are configured in `remote-dev-bot.yaml`.

**Mobile-friendly syntax:** Commands are case-insensitive and you can use spaces instead of dashes: `/agent resolve claude large` works the same as `/agent-resolve-claude-large`.

### Understanding Model Names

Model aliases (like `claude-small`) map to **LiteLLM model identifiers** in `remote-dev-bot.yaml`. LiteLLM is the library OpenHands uses to talk to different LLM providers through a unified interface.

**Model ID format:** `provider/model-name`

| Provider | Prefix | Example |
|----------|--------|---------|
| Anthropic (Claude) | `anthropic/` | `anthropic/claude-sonnet-4-5` |
| OpenAI (GPT) | `openai/` | `openai/gpt-5.1-codex-mini` |
| Google (Gemini) | `gemini/` | `gemini/gemini-2.5-flash` |

### Supported Providers

Remote Dev Bot currently supports three LLM providers out of the box:

| Provider | Secret Name | Model Prefix |
|----------|-------------|--------------|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | `anthropic/` |
| OpenAI (GPT) | `OPENAI_API_KEY` | `openai/` |
| Google (Gemini) | `GEMINI_API_KEY` | `gemini/` |

The workflow automatically selects the correct API key based on the model prefix. For example, a model ID starting with `anthropic/` will use `ANTHROPIC_API_KEY`.

**Adding a new provider:** LiteLLM supports many providers beyond these three. To add support for a new provider, you'll need to modify `.github/workflows/resolve.yml`:

1. Add the new secret to the `workflow_call.secrets` section
2. Add a case in the "Determine API key" step to match the provider prefix
3. Pass the secret to the environment in the resolve and design jobs

See the [LiteLLM providers documentation](https://docs.litellm.ai/docs/providers) for the full list of supported providers and their model prefixes.

### Finding Valid Model Names

OpenHands uses LiteLLM, so the model strings must be valid LiteLLM identifiers. Browse available models at **[models.litellm.ai](https://models.litellm.ai)** — search by name, filter by provider, and see context windows and pricing.

Prefix the model string with the provider name in `remote-dev-bot.yaml` (e.g., `anthropic/claude-sonnet-4-5`).

### Choosing a Model

**For most tasks:** Use the default (`/agent-resolve`). Claude Sonnet (`claude-small`) offers a good balance of capability and cost.

**For complex multi-file features:** Use `/agent-resolve-claude-large` (Opus) or `/agent-resolve-gpt-large` (GPT Codex). These models handle larger contexts and more intricate reasoning.

**For coding-heavy tasks:** Models with "codex" in the name (e.g., `openai/gpt-5.1-codex-mini`) are specifically tuned for code generation and may perform better on implementation tasks.

### Commit Trailers

By default, each OpenHands commit includes a trailer identifying the model used:

```
Model: claude-large (anthropic/claude-opus-4-5), openhands-ai v0.39.0
```

This is appended by amending the commit after `send_pull_request` pushes it, which causes a force-push event visible in the PR timeline. To disable this (no trailer, no force push), set `commit_trailer` to empty in your `remote-dev-bot.yaml`:

```yaml
commit_trailer: ""
```

## Architecture

The system has two parts:

- **Shim workflow** (`.github/workflows/agent.yml`) — a thin trigger that lives in each target repo. Fires on `/agent-` commands and calls the reusable workflow. Copy this file to set up the shim install.
- **Reusable workflow** (`.github/workflows/resolve.yml`) — all the logic: parses commands, dispatches to resolve or design mode, runs the agent. Lives in this repo and is called by shims in target repos.
- **OpenHands** — the AI agent framework that does the actual code exploration and editing
- **`remote-dev-bot.yaml`** — model aliases and OpenHands settings (version, max iterations, PR type)
- **`runbook.md`** — step-by-step setup instructions, designed to be followed by a human or by an AI assistant (like Claude Code)

## Setup

See `runbook.md` for complete setup instructions. The runbook is designed so you (or an AI assistant) can follow it step-by-step to get this running in your own GitHub account.

**Quick version:** You need a GitHub repo, API keys for your preferred LLM provider(s), and about 10 minutes. No PAT or special authentication is required — the bot works with GitHub's built-in token and posts as `github-actions[bot]`.

**Advanced auth options:** If you want bot PRs to auto-trigger CI, or a custom bot identity (e.g., `your-app[bot]`), see the advanced auth section in the runbook. Options include a GitHub App (recommended) or a PAT.

## Customization

### Add Repo Context for the Agent

Create `.openhands/microagents/repo.md` in your target repo with anything the agent should know about your codebase: coding conventions, architecture overview, how to run tests, directories to avoid, etc. The agent reads this file before starting work.

An AI assistant can write this for you — just ask it to read your codebase and generate a `repo.md` describing the architecture and conventions.

### Model Aliases

Add or modify model aliases in your repo's `remote-dev-bot.yaml` (create it in the repo root if it doesn't exist):

```yaml
models:
  my-alias:
    id: anthropic/claude-sonnet-4-5
    description: "My custom model"
```

These settings layer on top of the base config in `remote-dev-bot.yaml` from the remote-dev-bot repo. Your repo's settings take precedence. See [how-it-works.md](how-it-works.md) for config layering details.

### Iteration Limits

The agent runs for up to 50 iterations by default. Lower this for simpler repos (less cost, faster results) or raise it for complex tasks:

```yaml
openhands:
  max_iterations: 30
```

## Troubleshooting

### Getting a second PR instead of a revision

You probably commented on the original issue instead of the PR. Commenting on the issue always creates a new PR; commenting on the PR adds commits to the existing one. Check which page you're on before triggering.

(The two-PR behavior is also intentional when you want to compare different model implementations — trigger from the issue twice with different model aliases.)

### Cost showing $0.00

The workflow couldn't capture token usage data from this run. Check the Actions log for the run — look at the "Calculate and post cost" or "Post cost comment" step to see what was found.

### Agent triggered but no PR appeared

The agent ran but didn't open a PR. The log will say "Issue was not successfully resolved. Skipping PR creation." This usually means the agent hit the iteration limit without finishing. Try a more capable model (`/agent-resolve-claude-large`) or add more detail to the issue description.

**Diagnosing failures with an interactive agent:** The fastest way to understand what went wrong is to ask an AI coding assistant to read the logs for you:

```
Have a look at issue 50 — I triggered the agent but it didn't make a PR. Look through the Actions logs and tell me what went wrong.
```

Or point at a specific run ID from the Actions tab:

```
Have a look at Actions run 12345678 in this repo. What went wrong?
```

The assistant can fetch the logs via `gh run view`, identify the failure point, and suggest a fix.

### Other issues

See the Troubleshooting section in `runbook.md` for installation-related problems (workflow not triggering, secrets not reaching the workflow, etc.).

## Development

GitHub Actions only runs workflows from the default branch (main), so developing remote-dev-bot requires a non-standard workflow.

**Repos:**
- `remote-dev-bot` — the reusable workflow, config, and docs
- `remote-dev-bot-test` — a test repo with the shim pointed at the `dev` branch of remote-dev-bot (instead of `main`)

**Dev cycle:**
1. In `remote-dev-bot`: reset `dev` to `main`, then make changes on `dev`
2. In `remote-dev-bot-test`: create an issue and comment `/agent-resolve-claude-small` to trigger the agent
3. The shim in the test repo calls `resolve.yml@dev`, so it picks up your changes
4. If it works, clean up the git history on `dev` (squash, rebase, reword) and merge to `main`
5. If not, make more commits on `dev` and trigger the agent again

This keeps test issues out of the main repo and lets you iterate on workflow changes before they hit `main`.

For detailed dev cycle instructions (especially for AI assistants), see `AGENTS.md`.

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
