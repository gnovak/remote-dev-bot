# Remote Dev Bot — Setup Runbook

This file is both documentation and executable instructions. It's designed to be followed by:
- **A human** reading step-by-step
- **An AI assistant** (like Claude Code) that can execute steps, ask for confirmation, and handle errors

When following this runbook with an AI assistant, the assistant should:
- Explain what each step does before executing it
- Ask for confirmation before modifying external services (GitHub settings, API accounts)
- Verify each step succeeded before moving to the next
- If a step fails, diagnose the issue and suggest recovery options

---

## Prerequisites

- [ ] A GitHub account
- [ ] A GitHub repository where you want the bot to operate
- [ ] `gh` CLI installed and authenticated (`gh auth status` to verify)
- [ ] API key for at least one LLM provider (Anthropic, OpenAI, or Google)

---

## Phase 1: GitHub Repository Settings

### Step 1.1: Enable Actions Permissions

**What this does:** Allows GitHub Actions workflows to create branches and pull requests in your repository.

**Instructions:**
1. Go to your repository on GitHub
2. Navigate to Settings → Actions → General
3. Under "Workflow permissions":
   - Select "Read and write permissions"
   - Check "Allow GitHub Actions to create and approve pull requests"
4. Click Save

**With `gh` CLI:**
```bash
# There's no direct CLI command for this — it requires the web UI or API.
# The AI assistant can use Chrome integration to do this, or guide you through it.
gh api repos/{owner}/{repo}/actions/permissions/workflow \
  --method PUT \
  --field default_workflow_permissions=write \
  --field can_approve_pull_request_reviews=true
```

**Verify:**
```bash
gh api repos/{owner}/{repo}/actions/permissions/workflow
# Should show: default_workflow_permissions: "write", can_approve_pull_request_reviews: true
```

### Step 1.2: Add Repository Secrets

**What this does:** Stores your LLM API keys securely so the GitHub Action can use them.

**Required secrets:**

| Secret Name | Value | Required? |
|-------------|-------|-----------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key | If using Claude models |
| `OPENAI_API_KEY` | Your OpenAI API key | If using OpenAI models |
| `GEMINI_API_KEY` | Your Google AI API key | If using Gemini models |
| `PAT_TOKEN` | GitHub Personal Access Token | Recommended (see below) |

**Instructions:**
```bash
# Set each secret you need (will prompt for the value):
gh secret set ANTHROPIC_API_KEY --repo {owner}/{repo}
gh secret set OPENAI_API_KEY --repo {owner}/{repo}
gh secret set GEMINI_API_KEY --repo {owner}/{repo}
```

**Verify:**
```bash
gh secret list --repo {owner}/{repo}
# Should list the secrets you just set (values are hidden)
```

### Step 1.3: Create a Personal Access Token (PAT)

**What this does:** The default `GITHUB_TOKEN` has limited permissions. A PAT allows the bot to create PRs and push branches more reliably.

**Instructions:**
1. Go to https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Click "Generate new token"
3. Name it something like "remote-dev-bot"
4. Set expiration (recommend 90 days — add a calendar reminder to rotate)
5. Under "Repository access", select "Only select repositories" and choose your repo
6. Under "Permissions", grant:
   - Contents: Read and write
   - Issues: Read and write
   - Pull requests: Read and write
   - Workflows: Read and write
7. Generate and copy the token

```bash
# Store it as a repo secret:
gh secret set PAT_TOKEN --repo {owner}/{repo}
```

---

## Phase 2: Install the Workflow

### Step 2.1: Copy Workflow Files

**What this does:** Adds the GitHub Actions workflow that triggers the agent.

The workflow file should already be in this repository at `.github/workflows/agent.yml`. If you're setting this up in a different repo, copy it there:

```bash
# From within the target repo:
mkdir -p .github/workflows
cp /path/to/remote-dev-bot/.github/workflows/agent.yml .github/workflows/
cp /path/to/remote-dev-bot/remote-dev-bot.yaml .
```

### Step 2.2: Push and Verify

```bash
git add .github/workflows/agent.yml remote-dev-bot.yaml
git commit -m "Add remote dev bot workflow and config"
git push
```

**Verify the workflow is recognized:**
```bash
gh workflow list
# Should show "Remote Dev Bot" (or whatever the workflow is named)
```

---

## Phase 3: Test It

### Step 3.1: Create a Test Issue

```bash
gh issue create --title "Test: Add a hello world script" \
  --body "Create a simple hello.py that prints 'Hello from Remote Dev Bot'"
```

### Step 3.2: Trigger the Agent

Comment on the issue to trigger the agent:
```bash
gh issue comment {issue-number} --body "/agent"
```

### Step 3.3: Monitor the Run

```bash
# Watch the Actions tab:
gh run list --workflow=agent.yml

# View logs for a specific run:
gh run view {run-id} --log
```

### Step 3.4: Check Results

The agent should:
1. Create a new branch
2. Make the requested changes
3. Open a draft PR
4. Comment on the issue with a link to the PR

---

## Phase 4: Customize (Optional)

### Step 4.1: Add Repository Context for the Agent

Create `.openhands/microagents/repo.md` in your target repo with any context the agent should know (coding conventions, architecture, test commands, etc.).

### Step 4.2: Adjust Model Aliases

Edit `remote-dev-bot.yaml` to add, remove, or change model aliases.

### Step 4.3: Adjust Iteration Limits

The `max_iterations` setting in `remote-dev-bot.yaml` controls how many steps the agent can take. Higher = more capable but more expensive. Default is 50.

---

## Troubleshooting

### Agent doesn't trigger
- Verify the workflow file is on the default branch (main)
- Check that the commenter has collaborator/member/owner access to the repo
- Look at the Actions tab for failed runs

### Agent fails mid-run
- Check the Actions run log for error details
- Common issues: rate limiting (wait and retry), context overflow (simplify the issue)
- Try a more capable model: `/agent-claude-large`

### Agent produces bad results
- Add more context to the issue description
- Add repo context in `.openhands/microagents/repo.md`
- Comment `/agent` on the PR with specific feedback for another attempt

---

## Future Phases (Not Yet Implemented)

These are planned but not yet built. Placeholders for future runbook sections.

- [ ] **LLM account setup**: Walk through creating accounts, getting API keys, setting spending limits for each provider
- [ ] **Cost reporting**: Extract cost data from agent runs and post as PR comments
- [ ] **EC2 backend**: Run the agent on a dedicated EC2 instance instead of GitHub Actions (for longer runs, more resources, or cost optimization)
- [ ] **Chrome-assisted setup**: Use Claude's Chrome integration to automate web UI steps (creating tokens, configuring settings)
