# Example Issue

This shows what a typical issue looks like when using Remote Dev Bot.

---

## Issue Title

**Add dark mode support to the settings page**

## Issue Body

The settings page currently only has a light theme. Add a dark mode toggle that:

1. Adds a toggle switch in the settings UI
2. Persists the user's preference to localStorage
3. Applies the appropriate CSS class to the body element

The dark mode colors should follow our existing design tokens in `styles/tokens.css`.

---

## Agent Invocation

After creating the issue, a collaborator comments to trigger the agent:

```
/agent-claude-large
```

This tells Remote Dev Bot to use Claude Opus (the large model) to resolve the issue.

Other options:
- `/agent` — uses the default model (Claude Sonnet)
- `/agent-claude-small` — uses Claude Haiku (faster, cheaper)
- `/agent-openai` — uses GPT-4o

---

## What Happens Next

1. The GitHub Action triggers and spins up OpenHands
2. The agent reads the issue description and explores the codebase
3. It implements the requested changes
4. A pull request is automatically created

See [example-pr.md](./example-pr.md) for what the resulting PR looks like.
