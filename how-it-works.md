# How Remote Dev Bot Works

This document explains the architecture of Remote Dev Bot: what files live where, how the pieces connect, and how to think about the system when setting it up or developing it.

## The Two-Repo Model

Remote Dev Bot uses a **shim + reusable workflow** pattern that involves two repositories:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TARGET REPO                                       │
│                    (where you want AI to help develop)                      │
│                                                                             │
│   .github/workflows/agent.yml  ←── Shim: triggers on /agent- commands       │
│                                    and calls resolve.yml from remote-dev-bot│
│                                                                             │
│   remote-dev-bot.yaml          ←── (Optional) Override config for this repo │
│                                                                             │
│   .openhands/microagents/repo.md ← (Optional) Context for the AI agent      │
│                                                                             │
│   Repository Secrets:                                                       │
│     • ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY (at least one)     │
│     • PAT_TOKEN (Personal Access Token for cross-repo access)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ calls (via GitHub Actions)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         REMOTE-DEV-BOT REPO                                 │
│              (gnovak/remote-dev-bot or your org's fork)                     │
│                                                                             │
│   .github/workflows/resolve.yml  ←── Reusable workflow: all the logic       │
│                                      (model parsing, OpenHands, PR creation)│
│                                                                             │
│   remote-dev-bot.yaml            ←── Base config: model aliases, settings   │
│                                                                             │
│   lib/config.py                  ←── Config parsing logic                   │
│                                                                             │
│   examples/agent.yml             ←── Shim template to copy to target repos  │
│                                                                             │
│   runbook.md                     ←── Setup instructions                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## What Lives Where

### In the Remote-Dev-Bot Repo

This is the "engine" — the shared infrastructure that all target repos use.

| File | Purpose |
|------|---------|
| `.github/workflows/resolve.yml` | The reusable workflow. Contains all the logic: parses model aliases, installs OpenHands, resolves issues, creates PRs. Target repos call this. |
| `remote-dev-bot.yaml` | Base configuration. Defines model aliases (claude-small, claude-large, etc.) and OpenHands settings (version, max iterations, PR type). |
| `lib/config.py` | Config parsing logic. Loads base config, merges with target repo overrides, resolves aliases. Used by resolve.yml at runtime. |
| `examples/agent.yml` | Template shim workflow. Copy this to target repos at `.github/workflows/agent.yml`. |
| `runbook.md` | Step-by-step setup instructions for humans or AI assistants. |
| `AGENTS.md` | Development guidance for AI assistants working on this repo. |

**Who maintains this:** You (if you forked it) or the upstream maintainer (gnovak). Updates here automatically flow to all target repos that reference it.

### In Each Target Repo

This is where you want the AI agent to help with development.

| File | Purpose |
|------|---------|
| `.github/workflows/agent.yml` | **Required.** The shim workflow. Triggers on `/agent-resolve` and `/agent-design` comments and calls `resolve.yml` from remote-dev-bot. This is the only workflow file you need. |
| `remote-dev-bot.yaml` | **Optional.** Override config. Add model aliases, change settings, or override defaults for this specific repo. Merged on top of the base config. |
| `.openhands/microagents/repo.md` | **Optional.** Context for the AI agent. Describe your codebase, coding conventions, test commands, architecture — anything the agent should know. |

**Repository Secrets (required):**
- At least one LLM API key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`
- `PAT_TOKEN`: A Personal Access Token with repo access (needed for cross-repo workflow calls and PR creation)

## How the Pieces Connect

When someone comments `/agent-claude-large` on an issue:

1. **Shim triggers** — The target repo's `agent.yml` fires on the comment
2. **Calls reusable workflow** — The shim calls `resolve.yml@main` from remote-dev-bot
3. **Config checkout** — resolve.yml checks out `lib/config.py` from remote-dev-bot
4. **Config merge** — config.py loads base config from remote-dev-bot, merges with any override config in the target repo
5. **Model resolution** — The alias `claude-large` is resolved to a model ID like `anthropic/claude-opus-4-5`
6. **Agent runs** — OpenHands reads the issue, explores the codebase, makes changes
7. **PR created** — A draft (or ready) PR is opened with the changes

```
User comments /agent-claude-large
         │
         ▼
┌─────────────────────┐
│ target repo         │
│ agent.yml triggers  │
└─────────────────────┘
         │
         │ uses: gnovak/remote-dev-bot/.github/workflows/resolve.yml@main
         ▼
┌─────────────────────┐
│ remote-dev-bot      │
│ resolve.yml runs    │
│   • checkout config │
│   • parse alias     │
│   • run OpenHands   │
│   • create PR       │
└─────────────────────┘
         │
         ▼
   Draft PR opened in target repo
```

## Config Layering

Configuration is layered: target repo settings override remote-dev-bot defaults.

```yaml
# remote-dev-bot/remote-dev-bot.yaml (base)
default_model: claude-medium
openhands:
  max_iterations: 50
  pr_type: ready

# target-repo/remote-dev-bot.yaml (override)
default_model: claude-small
openhands:
  max_iterations: 30
```

Result: `default_model: claude-small`, `max_iterations: 30`, `pr_type: ready` (inherited from base).

This lets you:
- Use different default models per repo
- Set lower iteration limits for repos with simpler tasks
- Test config changes without modifying remote-dev-bot

## Using Your Own Fork

Organizations often want full control over the reusable workflow. To use a fork:

1. Fork `gnovak/remote-dev-bot` to your org (e.g., `myorg/remote-dev-bot`)
2. In your target repos' shims, change the `uses:` line:
   ```yaml
   uses: myorg/remote-dev-bot/.github/workflows/resolve.yml@main
   ```
3. Set Actions access on your fork (Settings → Actions → General → Access → "Accessible from repositories owned by the user")

Now updates to your fork flow to your target repos, and you control the release cadence.

## The Special Case: Developing Remote-Dev-Bot Itself

When using remote-dev-bot to develop remote-dev-bot, the two repos are the same. This creates a bootstrapping situation:

- The shim (`agent.yml`) lives in remote-dev-bot
- The reusable workflow (`resolve.yml`) also lives in remote-dev-bot
- The shim calls `resolve.yml@main`, so changes on feature branches don't take effect

**Solution: Use a separate test repo.**

The recommended dev cycle uses two repos:
- `remote-dev-bot` — the main repo with the reusable workflow
- `remote-dev-bot-test` — a test repo whose shim points at `resolve.yml@dev`

See `AGENTS.md` for the full dev cycle, including how the `dev` branch works as a pointer.

## Quick Reference: What Goes Where

| I want to... | File to edit | Which repo |
|--------------|--------------|------------|
| Add a new model alias | `remote-dev-bot.yaml` | remote-dev-bot (or your fork) |
| Change the default model for one repo | `remote-dev-bot.yaml` | target repo |
| Modify how the agent runs | `.github/workflows/resolve.yml` | remote-dev-bot |
| Give the agent context about my codebase | `.openhands/microagents/repo.md` | target repo |
| Set up a new repo to use the bot | `.github/workflows/agent.yml` + secrets | target repo |
| Change config parsing logic | `lib/config.py` | remote-dev-bot |

## Troubleshooting

**"Which config file is being used?"**

The workflow logs show which configs were loaded:
```
Config: base=remote-dev-bot, override=target repo
```
or
```
Config: base=remote-dev-bot, override=none
```

**"My config changes aren't taking effect"**

- If you changed `remote-dev-bot.yaml` in the target repo: changes should work immediately
- If you changed `remote-dev-bot.yaml` in remote-dev-bot: the target repo's shim must reference the branch with your changes (e.g., `@dev` instead of `@main`)
- If you changed `lib/config.py`: this is checked out from `main` at runtime, so changes must be merged to main first (see AGENTS.md for details)

**"I'm confused about which repo I'm in"**

Check the `uses:` line in your shim:
```yaml
uses: gnovak/remote-dev-bot/.github/workflows/resolve.yml@main
```
This tells you which remote-dev-bot repo (and branch) you're using.
