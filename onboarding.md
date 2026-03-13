# Getting Started with Remote Dev Bot

Now that you've installed remote-dev-bot, let's try it out on your repo. These
exercises walk you through the main workflows so you can see how everything
works in practice.

**Time estimate:** 30-60 minutes total, depending on how complex your test tasks
are.

---

## Before You Start

Make sure you've completed [install.md](install.md) and verified the bot works
(Phase 4 test). You should have:

- [ ] The workflow file in `.github/workflows/agent.yml`
- [ ] At least one API key secret configured
- [ ] A successful test run from Phase 4

---

## Exercise 1: Your First Resolve

Let's create a real issue and have the agent resolve it.

### Step 1: Pick a Simple Task

Choose something small and well-defined for your first real task. Good
candidates:

- Add a missing docstring to a function
- Fix a typo in documentation
- Add a simple configuration option
- Create a small utility function

**Tip:** The clearer the issue description, the better the result. Include:

- What you want changed
- Where in the codebase it should happen (if you know)
- Any constraints or preferences

### Step 2: Create the Issue

Create a GitHub issue with your task. Example:

> **Title:** Add docstring to the `process_data` function
>
> **Body:** The `process_data` function in `src/utils.py` is missing a
> docstring. Please add one that explains:
>
> - What the function does
> - The parameters and their types
> - The return value

### Step 3: Trigger the Agent

Comment on your issue:

```
/agent-resolve
```

### Step 4: Watch It Work

1. **Look for the 🚀 reaction** on your comment — this confirms the workflow
   started
2. **Check the Actions tab** in your repo to see the workflow running
3. **Wait for the PR** — this typically takes 5-15 minutes depending on
   complexity

### Step 5: Review the Result

When the PR appears:

- Read the PR description — the agent explains what it did
- Check the diff — verify the changes match what you asked for
- Look at the cost comment — see how much the run cost

If the changes look good, merge the PR. If not, proceed to Exercise 4 to learn
how to iterate.

---

## Exercise 2: Design Mode

Design mode is for when you want to think through a problem before implementing
it.

### Step 1: Pick a Design Question

Choose something that needs analysis, not just implementation:

- "Should we refactor X to use pattern Y?"
- "What's the best way to add feature Z?"
- "How should we handle error case W?"

### Step 2: Create the Issue

Create an issue describing what you want analyzed. Example:

> **Title:** Design: How should we handle rate limiting?
>
> **Body:** We're getting rate limited by the external API. What are our options
> for handling this gracefully? Consider:
>
> - Retry strategies
> - Caching
> - User feedback

### Step 3: Trigger Design Mode

Comment on your issue:

```
/agent-design
```

### Step 4: Review the Analysis

The agent will post a comment with:

- Analysis of the problem
- Exploration of options
- A recommendation

**No PR is created** — design mode only posts a comment.

### Step 5: Decide Next Steps

After reading the analysis:

- **Agree with the recommendation?** Comment `/agent-resolve` to implement it
- **Want a different approach?** Update the issue with your preferred direction,
  then `/agent-resolve`
- **Need more analysis?** Ask follow-up questions in the issue

---

## Exercise 3: Review Mode

Review mode gives you AI feedback on a pull request.

### Step 1: Find or Create a PR

You need an open PR to review. Options:

- Use the PR from Exercise 1 (before merging)
- Create a new PR with some changes
- Use any existing open PR in your repo

### Step 2: Trigger Review Mode

Comment on the PR:

```
/agent-review
```

### Step 3: Read the Review

The agent will post a code review comment covering:

- Code quality observations
- Potential issues or bugs
- Suggestions for improvement
- Security considerations (if relevant)

**No changes are made** — review mode only posts feedback.

### Step 4: Act on Feedback

If the review identifies issues you want fixed:

- Fix them manually, or
- Comment `/agent-resolve` on the PR to have the agent fix them (see Exercise 4)

---

## Exercise 4: Iterating on a PR

When a PR needs changes — whether from human review or `/agent-review` — you can
have the agent make the fixes.

### Step 1: Start with a PR That Needs Changes

Use one of these:

- A PR from Exercise 1 that needs tweaks
- A PR that received feedback from `/agent-review`
- Any PR with review comments requesting changes

### Step 2: Add Your Feedback

If there isn't already feedback on the PR, add a comment describing what needs
to change:

> The error message should be more specific — include the actual value that
> failed validation.

### Step 3: Trigger Resolve on the PR

**Important:** Comment on the **PR**, not the original issue.

```
/agent-resolve
```

### Step 4: Watch the Agent Iterate

The agent will:

1. Read the existing PR and its review comments
2. Make changes to address the feedback
3. Push new commits to the same PR

### Step 5: Review Again

Check that the agent addressed the feedback. Repeat if needed — you can run
`/agent-resolve` on a PR multiple times.

**Tip:** This is the normal code review workflow. The agent acts like a
developer responding to review feedback.

---

## Exercise 5: Using Model Variants

Different models have different strengths. Learn when to use each.

### The Default Model

When you run `/agent-resolve` without a model suffix, you get the default model
(typically Claude Sonnet). This is good for most tasks.

### When to Use Larger Models

Try `/agent-resolve-claude-large` or `/agent-resolve-gpt-large` when:

- The task involves complex reasoning across multiple files
- Previous attempts with the default model failed or produced poor results
- You're working on architecture-level changes

### Try It

1. Create an issue with a moderately complex task
2. First try: `/agent-resolve` (default model)
3. If the result isn't satisfactory, try: `/agent-resolve-claude-large`
4. Compare the results and costs

### Cost Tradeoffs

Larger models cost more per run. Check the cost comment on each PR to understand
the tradeoff. For simple tasks, the default model is usually sufficient and more
cost-effective.

---

## Tips for Writing Good Issues

Now that you've tried the workflows, here are tips for getting the best results:

### Be Specific

❌ "Fix the bug in the login flow"

✅ "Fix the bug where users see a blank screen after clicking 'Login' when their
session has expired. The issue is in `src/auth/login.js` — the redirect logic
doesn't handle expired sessions."

### Include Context

- What file(s) are involved
- What the current behavior is
- What the desired behavior is
- Any constraints (don't change the API, must be backward compatible, etc.)

### Use Design Mode First for Ambiguous Tasks

If you're not sure exactly what you want, start with `/agent-design` to explore
options before committing to an implementation.

### Break Down Large Tasks

Instead of one massive issue, create smaller focused issues. The agent handles
well-scoped tasks better than sprawling ones.

---

## What's Next?

You've now used all the main features of remote-dev-bot:

- ✅ Resolve mode — implementing changes
- ✅ Design mode — analyzing problems
- ✅ Review mode — getting feedback
- ✅ Iteration — incorporating feedback on PRs
- ✅ Model variants — choosing the right model for the task

For more details on customization and advanced usage, see the
[README.md](README.md):

- Adding repo context for the agent
- Configuring iteration limits
- Setting up custom model aliases
- Security considerations

Happy building! 🚀
