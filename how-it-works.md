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
│     • (Optional) RDB_APP_PRIVATE_KEY or RDB_PAT_TOKEN — see Auth below    │
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
│   .github/workflows/agent.yml    ←── Shim (also the template for target repos)│
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
| `remote-dev-bot.yaml` | Base configuration. Defines model aliases (`claude-small`, `claude-large`, etc.) and OpenHands settings (version, max iterations, PR type). |
| `lib/config.py` | Config parsing logic. Loads base config, merges with target repo overrides, resolves aliases. Used by resolve.yml at runtime. |
| `.github/workflows/agent.yml` | Shim workflow. Also serves as the template — copy this to target repos. |
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

**Repository Secrets/Variables (optional — for bot identity or CI triggering):**
- `RDB_APP_ID` (variable) + `RDB_APP_PRIVATE_KEY` (secret): GitHub App — bot posts as `app-name[bot]`, CI triggers on bot PRs
- `RDB_PAT_TOKEN` (secret): PAT — bot posts as the PAT owner, CI triggers on bot PRs
- Without either: bot posts as `github-actions[bot]`, bot PRs don't trigger CI

## How the Pieces Connect

When someone comments `/agent-claude-large` on an issue:

1. **Shim triggers** — The target repo's `agent.yml` fires on the comment
2. **Calls reusable workflow** — The shim calls `resolve.yml@main` from remote-dev-bot
3. **Config checkout** — resolve.yml checks out `lib/config.py` from remote-dev-bot
4. **Config merge** — config.py loads base config from remote-dev-bot, merges with any override config in the target repo
5. **Model resolution** — The alias `claude-large` is resolved to a model ID like `anthropic/claude-opus-4-5`
6. **Feedback** — A rocket emoji is added to your comment and you're assigned to the issue, so you can see at a glance which issues have active work
7. **Agent runs** — OpenHands reads the issue, explores the codebase, makes changes
8. **PR created** — A draft (or ready) PR is opened with the changes

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
default_model: claude-small
openhands:
  max_iterations: 50
  pr_type: ready

# target-repo/remote-dev-bot.yaml (override)
default_model: claude-large
openhands:
  max_iterations: 30
```

Result: `default_model: claude-large`, `max_iterations: 30`, `pr_type: ready` (inherited from base).

This lets you:
- Use different default models per repo
- Set lower iteration limits for repos with simpler tasks
- Test config changes without modifying remote-dev-bot

## Authentication and Bot Identity

### How tokens work

The workflow uses a three-way token fallback: GitHub App token > `RDB_PAT_TOKEN` > `github.token`. Whichever is configured takes priority. Each option has different trade-offs:

| | No config (default) | RDB_PAT_TOKEN | GitHub App |
|---|---|---|---|
| **Bot identity** | `github-actions[bot]` | PAT owner's personal account | `app-name[bot]` |
| **CI triggers on bot PRs** | No | Yes | Yes |
| **Setup effort** | None | Create PAT, add secret | Create app, add secret + variable |

**For most users, the default (no config) is the right choice.** The bot posts as `github-actions[bot]`, which is clearly not you. The only downside is that CI workflows won't auto-run on bot-created PRs — you can trigger them manually.

### Cross-owner secret passing

GitHub Actions does not pass `secrets: inherit` across different repo owners. Since your target repo and `gnovak/remote-dev-bot` have different owners, the shim must list secrets explicitly:

```yaml
    uses: gnovak/remote-dev-bot/.github/workflows/resolve.yml@main
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      RDB_PAT_TOKEN: ${{ secrets.RDB_PAT_TOKEN }}
      RDB_APP_PRIVATE_KEY: ${{ secrets.RDB_APP_PRIVATE_KEY }}
```

If you fork remote-dev-bot into your own org and your target repos are in the same org, `secrets: inherit` will work.

### Advanced: GitHub App setup

A GitHub App gives the bot a distinct identity (e.g., `remote-dev-bot[bot]`) and triggers CI on bot PRs. To set one up:

1. Create a GitHub App at https://github.com/settings/apps/new
2. Grant repository permissions: Contents, Issues, Pull Requests (all Read & write)
3. Uncheck Webhook "Active" (not needed)
4. Install the app on your repo(s)
5. Store the App ID as a repository **variable** `RDB_APP_ID`
6. Generate a private key and store it as a repository **secret** `RDB_APP_PRIVATE_KEY`

### Advanced: PAT setup

A PAT is simpler than a GitHub App but the bot posts as your personal account. See the runbook for PAT creation instructions. Store it as `RDB_PAT_TOKEN`.

### Visibility requirements

The shim install requires `gnovak/remote-dev-bot` (or your fork) to be **public** so the target repo's workflow can call the reusable workflow. Your target repo can be public or private — only the repo hosting the reusable workflow must be public (or in the same org with appropriate Actions access settings).

The compiled install has no visibility requirements since the workflow is self-contained.

## Using Your Own Fork

Organizations often want full control over the reusable workflow. To use a fork:

1. Fork `gnovak/remote-dev-bot` to your org (e.g., `myorg/remote-dev-bot`)
2. In your target repos' shims, change the `uses:` line:
   ```yaml
   uses: myorg/remote-dev-bot/.github/workflows/resolve.yml@main
   ```
3. Set Actions access on your fork (Settings → Actions → General → Access → "Accessible from repositories owned by the user")
4. If your fork and target repos are in the same org, you can use `secrets: inherit` instead of listing secrets explicitly

Now updates to your fork flow to your target repos, and you control the release cadence.

**Private forks:** If you keep your fork private, your target repos must be in the same org/user account (GitHub doesn't allow cross-owner calls to private repo workflows). Set the Actions access level as described in step 3.

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
