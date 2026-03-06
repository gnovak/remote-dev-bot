# How Remote Dev Bot Works

This document explains the architecture of Remote Dev Bot: what files live
where, how the pieces connect, and how to think about the system when setting it
up.

## The Two-Repo Model

Remote Dev Bot uses a **shim + reusable workflow** pattern that involves two
repositories:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TARGET REPO                                       │
│                    (where you want AI to help develop)                      │
│                                                                             │
│   .github/workflows/agent.yml  ←── Shim: triggers on /agent- commands       │
│                                    and calls remote-dev-bot.yml from remote-dev-bot│
│                                                                             │
│   remote-dev-bot.yaml          ←── (Optional) Override config for this repo │
│                                                                             │
│   AGENTS.md / CLAUDE.md          ← (Optional) Context for the AI agent      │
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
│   .github/workflows/remote-dev-bot.yml  ←── Reusable workflow: all the logic          │
│                                      (model parsing, LiteLLM agent loop, PR creation)│
│                                                                             │
│   remote-dev-bot.yaml            ←── Base config: model aliases, settings   │
│                                                                             │
│   .github/workflows/agent.yml    ←── Shim (also the template for target repos)│
│                                                                             │
│   install.md                     ←── Setup instructions                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## What Lives Where

### In the Remote-Dev-Bot Repo

This is the "engine" — the shared infrastructure that all target repos use.

| File                                   | Purpose                                                                                                                                        |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `.github/workflows/remote-dev-bot.yml` | The reusable workflow. Contains all the logic: parses model aliases, runs the LiteLLM agent loop, resolves issues, creates PRs. Target repos call this. |
| `remote-dev-bot.yaml`                  | Base configuration. Defines model aliases (`claude-small`, `claude-large`, etc.) and agent settings (max iterations, PR type).                         |
| `.github/workflows/agent.yml`          | Shim workflow. Also serves as the template — copy this to target repos.                                                                        |
| `install.md`                           | Step-by-step setup instructions for humans or AI assistants.                                                                                   |

**Who maintains this:** The upstream maintainer (gnovak), or you if you forked
it. Updates here automatically flow to all target repos that reference it.

### In Each Target Repo

This is where you want the AI agent to help with development.

| File                             | Purpose                                                                                                                                                                                                                                                      |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `.github/workflows/agent.yml`    | **Required.** The shim workflow. Triggers on `/agent-resolve`, `/agent-design`, and `/agent-review` comments and calls `remote-dev-bot.yml` from remote-dev-bot. This is the only workflow file you need.                                                    |
| `remote-dev-bot.yaml`            | **Optional.** Override config. Add model aliases, change settings, or override defaults for this specific repo. Merged on top of the base config.                                                                                                                                      |
| `AGENTS.md` / `CLAUDE.md`        | **Optional.** Context for the AI agent. Describe your codebase, coding conventions, test commands, architecture — anything the agent should know. Add them to `extra_files` in your `remote-dev-bot.yaml` so the agent reads them before starting work. |

**Repository Secrets (required):**

- At least one LLM API key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or
  `GEMINI_API_KEY`

**Repository Secrets/Variables (optional — for bot identity or CI triggering):**

- `RDB_APP_ID` (variable) + `RDB_APP_PRIVATE_KEY` (secret): GitHub App — bot
  posts as `app-name[bot]`, CI triggers on bot PRs
- `RDB_PAT_TOKEN` (secret): PAT — bot posts as the PAT owner, CI triggers on bot
  PRs
- Without either: bot posts as `github-actions[bot]`, bot PRs don't trigger CI

## How the Pieces Connect

When someone comments `/agent-resolve-claude-large` on an issue:

1. **Shim triggers** — The target repo's `agent.yml` fires on the comment
2. **Calls reusable workflow** — The shim calls `remote-dev-bot.yml@main` from
   remote-dev-bot
3. **Config checkout** — remote-dev-bot.yml sparse-checks out
   `remote-dev-bot.yaml` and `lib/` from remote-dev-bot
4. **Config merge** — base config from remote-dev-bot is merged with any
   override config in the target repo
5. **Model resolution** — The alias `claude-large` is resolved to a model ID
   like `anthropic/claude-opus-4-5`
6. **Feedback** — A rocket emoji is added to your comment and you're assigned to
   the issue, so you can see at a glance which issues have active work
7. **Agent runs** — LiteLLM agent loop (resolve.py) reads the issue, explores
   the codebase, makes changes
8. **PR created** — A draft (or ready) PR is opened with the changes

```
User comments /agent-resolve-claude-large
         │
         ▼
┌─────────────────────┐
│ target repo         │
│ agent.yml triggers  │
└─────────────────────┘
         │
         │ uses: gnovak/remote-dev-bot/.github/workflows/remote-dev-bot.yml@main
         ▼
┌─────────────────────┐
│ remote-dev-bot      │
│ remote-dev-bot.yml runs    │
│   • checkout config │
│   • parse alias     │
│   • run resolve.py  │
│   • create PR       │
└─────────────────────┘
         │
         ▼
   Draft PR opened in target repo
```

## Config Layering

Configuration is merged across three layers (each is optional, deeper layers win):

| Layer    | File                          | Where it lives                                    |
| -------- | ----------------------------- | ------------------------------------------------- |
| Base     | `remote-dev-bot.yaml`         | remote-dev-bot repo (fetched via sparse-checkout) |
| Override | `remote-dev-bot.yaml`         | target repo root                                  |
| Local    | `remote-dev-bot.local.yaml`   | target repo root (gitignored, for local overrides)|

Example:

```yaml
# remote-dev-bot/remote-dev-bot.yaml (base)
default_model: claude-small
agent:
  max_iterations: 50
  pr_type: ready

# target-repo/remote-dev-bot.yaml (override)
default_model: claude-large
agent:
  max_iterations: 30
```

Result: `default_model: claude-large`, `max_iterations: 30`, `pr_type: ready`
(inherited from base).

Merges are deep (leaf-level): overriding `agent.max_iterations` does not
clobber other `agent` fields.

**`extra_files` is additive across all layers**, not last-wins. Files from
the base config are always included; each deeper layer appends to that list
(duplicates are dropped). This prevents accidentally losing system-default
context files when a user adds their own entries.

This lets you:

- Use different default models per repo
- Set lower iteration limits for repos with simpler tasks
- Override only the settings that matter to your repo — everything else is
  inherited from the base

The workflow logs show which configs were loaded, so you can verify what's in
effect:

```
Config: base=remote-dev-bot, override=target repo
```

## Per-Invocation Arguments (Inline Args)

Users can override config values for a single run by adding argument lines after
the command in their GitHub comment:

```
/agent-resolve
max iterations = 75
branch = my-feature
extra_files = docs/architecture.md extra-context.md
```

**How it works:**

- The first line is the command; subsequent `name = value` lines are parsed as
  arguments
- Argument names are normalized: spaces, dashes, and underscores are equivalent
  (`max iterations`, `max-iterations`, and `max_iterations` all resolve to the
  same thing)

**Supported arguments:**

| Argument          | Applies to               | Description                                                           |
| ----------------- | ------------------------ | --------------------------------------------------------------------- |
| `max_iterations`  | `agent.max_iterations`   | Override iteration limit for this run                                 |
| `branch`          | `agent.branch`           | Override target branch for this run                                   |
| `timeout_minutes` | `agent.timeout_minutes`  | Override watchdog timeout for this run                                |
| `extra_files`     | the mode's `extra_files` | Add files (space-separated) — appended to base and config-layer lists |

Unknown argument names are rejected with an error comment.

## Authentication and Bot Identity

### How tokens work

The workflow uses a three-way token fallback: GitHub App token >
`RDB_PAT_TOKEN` > `github.token`. Whichever is configured takes priority. Each
option has different trade-offs:

|                            | No config (default)   | RDB_PAT_TOKEN                | GitHub App                        |
| -------------------------- | --------------------- | ---------------------------- | --------------------------------- |
| **Bot identity**           | `github-actions[bot]` | PAT owner's personal account | `app-name[bot]`                   |
| **CI triggers on bot PRs** | No                    | Yes                          | Yes                               |
| **Setup effort**           | None                  | Create PAT, add secret       | Create app, add secret + variable |

**For most users, the default (no config) is the right choice.** The bot posts
as `github-actions[bot]`, which is clearly not you. The only downside is that CI
workflows won't auto-run on bot-created PRs — you can trigger them manually.

### Cross-owner secret passing

GitHub Actions does not pass `secrets: inherit` across different repo owners.
Since your target repo and `gnovak/remote-dev-bot` have different owners, the
shim must list secrets explicitly:

```yaml
uses: gnovak/remote-dev-bot/.github/workflows/remote-dev-bot.yml@main
secrets:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  RDB_PAT_TOKEN: ${{ secrets.RDB_PAT_TOKEN }}
  RDB_APP_PRIVATE_KEY: ${{ secrets.RDB_APP_PRIVATE_KEY }}
```

If you fork remote-dev-bot into your own org and your target repos are in the
same org, `secrets: inherit` will work.

### Advanced: GitHub App setup

A GitHub App gives the bot a distinct identity (e.g., `remote-dev-bot[bot]`) and
triggers CI on bot PRs. See [install.md](install.md) for step-by-step setup
instructions.

### Advanced: PAT setup

A PAT is simpler than a GitHub App but the bot posts as your personal account.
See [install.md](install.md) for PAT creation instructions. Store it as
`RDB_PAT_TOKEN`.

### Visibility requirements

The shim install requires `gnovak/remote-dev-bot` (or your fork) to be
**public** so the target repo's workflow can call the reusable workflow. Your
target repo can be public or private — only the repo hosting the reusable
workflow must be public (or in the same org with appropriate Actions access
settings).

The compiled install has no visibility requirements since the workflow is
self-contained.

## Using Your Own Fork

Organizations often want full control over the reusable workflow. To use a fork:

1. Fork `gnovak/remote-dev-bot` to your org (e.g., `myorg/remote-dev-bot`)
2. In your target repos' shims, change the `uses:` line:
   ```yaml
   uses: myorg/remote-dev-bot/.github/workflows/remote-dev-bot.yml@main
   ```
3. Set Actions access on your fork (Settings → Actions → General → Access →
   "Accessible from repositories owned by the user")
4. If your fork and target repos are in the same org, you can use
   `secrets: inherit` instead of listing secrets explicitly

Now updates to your fork flow to your target repos, and you control the release
cadence.

**Private forks:** If you keep your fork private, your target repos must be in
the same org/user account (GitHub doesn't allow cross-owner calls to private
repo workflows). Set the Actions access level as described in step 3.

## Quick Reference

| I want to...                             | Where                                           |
| ---------------------------------------- | ----------------------------------------------- |
| Set up a new repo to use the bot         | Follow [runbook.md](runbook.md)                 |
| Change the default model for my repo     | `remote-dev-bot.yaml` in target repo            |
| Give the agent context about my codebase | `AGENTS.md` / `CLAUDE.md` via `extra_files` in `remote-dev-bot.yaml` |
| Override a setting for a single run      | Inline args in the trigger comment (see above)  |
