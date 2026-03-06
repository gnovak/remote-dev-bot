# Remote Dev Bot — Demo

See what remote-dev-bot does before you install it. This page walks through real
examples from the remote-dev-bot repository itself.

---

## What You'll See

When you trigger remote-dev-bot on an issue:

1. **Trigger** — You comment `/agent-resolve` (or `/agent-design`, `/agent-review`)
2. **Acknowledgment** — A 🚀 reaction appears on your comment
3. **Processing** — A GitHub Actions workflow runs (visible in the Actions tab)
4. **Result** — A PR is created (resolve), a comment is posted (design/review),
   or both

The examples below show this flow in action.

---

## Example 1: Simple Resolve

**The issue:**
[Issue #33](https://github.com/gnovak/remote-dev-bot/issues/33) asked for
documentation of model names — a straightforward documentation task.

**What happened:**

1. Someone commented `/agent-resolve` on the issue
2. The agent read the issue, explored the codebase, and found where model
   documentation belonged
3. The agent created
   [PR #52](https://github.com/gnovak/remote-dev-bot/pull/52) with the changes
4. The PR was reviewed and merged

**What to look at:**

- The [issue description](https://github.com/gnovak/remote-dev-bot/issues/33) —
  clear, specific request
- The [PR diff](https://github.com/gnovak/remote-dev-bot/pull/52/files) — the
  agent's implementation
- The PR description — the agent explains what it did and why

**Takeaway:** For well-defined tasks, the agent can go from issue to merged PR
with minimal human intervention.

---

## Example 2: Design Then Resolve

**The issue:**
[Issue #124](https://github.com/gnovak/remote-dev-bot/issues/124) asked whether
commands should be case-insensitive (to handle mobile autocorrect). This needed
design analysis before implementation.

**What happened:**

1. Someone commented `/agent-design` to get analysis first
2. The agent posted a
   [detailed design analysis](https://github.com/gnovak/remote-dev-bot/issues/124#issuecomment-3912240858)
   as a comment — exploring tradeoffs, suggesting an approach
3. A human reviewed the analysis and agreed with the recommendation
4. Someone commented `/agent-resolve` to implement
5. The agent created
   [PR #131](https://github.com/gnovak/remote-dev-bot/pull/131), which was merged

**What to look at:**

- The [design comment](https://github.com/gnovak/remote-dev-bot/issues/124#issuecomment-3912240858) —
  the agent's analysis of the problem
- The human response agreeing with the approach
- The [resulting PR](https://github.com/gnovak/remote-dev-bot/pull/131) —
  implementation matching the design

**Takeaway:** Use `/agent-design` when you want to think through a problem
before committing to an implementation. The agent explores the codebase and
gives you a recommendation you can accept, modify, or reject.

---

## Example 3: Resolve With Feedback

**The issue:**
[Issue #95](https://github.com/gnovak/remote-dev-bot/issues/95) asked about
preventing agent loops — a security-sensitive feature.

**What happened:**

1. Someone commented `/agent-resolve` on the issue
2. The agent created
   [PR #109](https://github.com/gnovak/remote-dev-bot/pull/109) with an initial
   implementation
3. A reviewer
   [pointed out a regex bypass vulnerability](https://github.com/gnovak/remote-dev-bot/pull/109#issuecomment-3909533145)
   in the implementation
4. Someone commented `/agent-resolve` **on the PR** (not the issue) to
   incorporate the feedback
5. The agent fixed the vulnerability and pushed new commits to the same PR
6. The PR was merged

**What to look at:**

- The [original PR](https://github.com/gnovak/remote-dev-bot/pull/109) — first
  implementation attempt
- The [reviewer comment](https://github.com/gnovak/remote-dev-bot/pull/109#issuecomment-3909533145) —
  identifying the security issue
- The commit history — showing the agent's fix after feedback

**Takeaway:** The agent can iterate on its own PRs. Comment `/agent-resolve` on
a PR (not the original issue) to have the agent incorporate review feedback.
This is the normal code review workflow — just with an AI making the fixes.

---

## The Three Modes

| Mode       | Command          | What it does                              |
| ---------- | ---------------- | ----------------------------------------- |
| **Resolve** | `/agent-resolve` | Implements changes and opens a PR         |
| **Design** | `/agent-design`  | Analyzes the problem and posts a comment  |
| **Review** | `/agent-review`  | Reviews a PR and posts feedback           |

All modes support model variants: `/agent-resolve-claude-large`,
`/agent-design-gpt-large`, etc.

---

## Ready to Install?

Now that you've seen what remote-dev-bot does, head back to
[install.md](install.md) to set it up on your own repository.

After installation, see [onboarding.md](onboarding.md) for hands-on exercises
that walk you through using each mode on your own repo.
