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

Before starting, make sure you have:

- [ ] A GitHub account
- [ ] A GitHub repository where you want the bot to operate

- [ ] **`gh` CLI installed and authenticated.** This is the GitHub command-line tool used throughout this runbook.
  - Install: `brew install gh` (macOS) or see https://cli.github.com/ for other platforms
  - Authenticate: `gh auth login` (follow the prompts — choose HTTPS and authenticate via browser)
  - Add workflow scope: `gh auth refresh --hostname github.com --scopes workflow`
  - Set up git credential helper: `gh auth setup-git`
  - Verify: `gh auth status` should show you logged in with the `workflow` scope

- [ ] API key for at least one LLM provider (Anthropic, OpenAI, or Google) — see Step 1.2

Throughout this runbook, replace `{owner}/{repo}` with your actual GitHub owner and repo name (e.g., `myuser/myproject`).

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

### Step 1.2: Create an LLM API Key

**What this does:** The agent needs an API key to call the LLM. You need at least one key for whichever provider you want to use.

**For Anthropic (Claude models):**
1. Go to https://console.anthropic.com/settings/keys
2. Click "+ Create Key"
3. Name it something identifiable (e.g., "remote-dev-bot" or "remote-dev-bot-myrepo")
4. Leave the workspace as "Default" (unless you have a specific workspace)
5. Click "Add"
6. **Copy the key immediately** — you won't be able to see it again

**For OpenAI or Google:** Follow their respective console instructions to create an API key.

**Tip:** Naming the key after the project helps you track costs and revoke it later if needed.

### Step 1.3: Add Repository Secrets

**What this does:** Stores your API keys securely as GitHub repository secrets so the workflow can use them. Secret values are encrypted and never exposed in logs.

**Important:** The `gh secret set` command reads the secret value from your terminal interactively. You must run these commands yourself (not through an AI assistant's shell) so you can paste the key when prompted.

```bash
# Set the API key for whichever provider(s) you're using:
gh secret set ANTHROPIC_API_KEY --repo {owner}/{repo}
# Paste your Anthropic API key when prompted, then press Enter

gh secret set OPENAI_API_KEY --repo {owner}/{repo}
gh secret set GEMINI_API_KEY --repo {owner}/{repo}
```

**Verify:**
```bash
gh secret list --repo {owner}/{repo}
# Should list the secrets you just set (values are hidden)
```

### Step 1.4: Create a Personal Access Token (PAT)

**What this does:** GitHub Actions workflows get a default `GITHUB_TOKEN`, but it has limited permissions — it can't reliably create branches and open PRs across all scenarios. A Personal Access Token (PAT) gives the bot explicit permission to do these things.

We use a **fine-grained** token (not classic) because it can be scoped to a single repository with only the permissions the bot needs. This limits the blast radius if the token is ever compromised.

**Instructions:**
1. Go to https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Click "Generate new token"
3. **Token name:** Something like "remote-dev-bot" (or "remote-dev-bot-myrepo" if you plan to have multiple)
4. **Expiration:** Your choice. "No expiration" is convenient for a fine-grained token scoped to one repo; 90 days is more conservative (set a calendar reminder to rotate). The security risk is low since fine-grained tokens are limited to specific repos and permissions.
5. **Resource owner:** Your GitHub account
6. **Repository access:** Select "Only select repositories" and choose the repo where the bot will run
7. **Permissions** — under "Repository permissions", set these four to **Read and write**:
   - Contents (to push branches)
   - Issues (to read issues and post comments)
   - Pull requests (to create draft PRs)
   - Workflows (to trigger workflow runs)
   - Metadata will be added automatically as Read-only — that's fine
8. Click "Generate token"
9. **Copy the token immediately** — you won't be able to see it again

```bash
# Store it as a repo secret (run this yourself, not through an AI shell):
gh secret set PAT_TOKEN --repo {owner}/{repo}
# Paste the token when prompted, then press Enter
```

**Verify:**
```bash
gh secret list --repo {owner}/{repo}
# Should now show PAT_TOKEN alongside your API key(s)
```

---

## Phase 2: Install the Workflow

### Step 2.1: Copy Workflow Files

**What this does:** Adds the GitHub Actions workflow and config to your repository.

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
gh workflow list --repo {owner}/{repo}
# Should show "Remote Dev Bot" (or whatever the workflow is named)
```

---

## Phase 3: Test It

### Step 3.1: Create a Test Issue

```bash
gh issue create --repo {owner}/{repo} \
  --title "Test: Add a hello world script" \
  --body "Create a simple hello.py that prints 'Hello from Remote Dev Bot'"
```

### Step 3.2: Trigger the Agent

Comment on the issue to trigger the agent. For your first test, use `claude-medium` (Sonnet) — it handles the task lifecycle more reliably than `claude-small` (Haiku).

```bash
gh issue comment {issue-number} --repo {owner}/{repo} --body "/agent-claude-medium"
```

### Step 3.3: Monitor the Run

```bash
# Check the Actions tab for runs:
gh run list --repo {owner}/{repo} --workflow=agent.yml

# View logs for a specific run:
gh run view {run-id} --repo {owner}/{repo} --log
```

A successful run typically takes 5-10 minutes. The agent will:
1. Install OpenHands and dependencies (~1-2 min)
2. Read the issue and work on the solution (~3-7 min)
3. Create a draft PR (~30 sec)

### Step 3.4: Check Results

If successful, you should see:
- A new branch created by the agent
- A draft PR linked to the issue
- A rocket emoji reaction on your `/agent` comment

```bash
gh pr list --repo {owner}/{repo}
```

**If the run fails**, check the logs for the specific error. Common first-run issues:

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'yaml'` | PyYAML not installed before config parsing | Should be fixed in current workflow — update to latest |
| `ImportError: cannot import name 'WorkspaceState'` | Old OpenHands version | Update `openhands.version` in `remote-dev-bot.yaml` to latest (currently 1.3.0) |
| `error: the following arguments are required: --selected-repo` | OpenHands 1.x API change | Update workflow — `--repo` was renamed to `--selected-repo` |
| `ValueError: Username is required` | Missing env vars | Workflow needs `GITHUB_USERNAME` and `GIT_USERNAME` |
| `Missing Anthropic API Key` or `x-api-key header is required` | API key not set or set empty | Re-run `gh secret set` interactively from your terminal |
| `Agent reached maximum iteration` | Agent loops instead of finishing | Try `/agent-claude-medium` instead of `/agent` |
| `429 Too Many Requests` | GitHub API rate limit | Wait a few minutes and try again |
| `KeyError: 'LLM_API_KEY'` in PR creation step | Missing env vars in PR step | Update workflow to pass `LLM_API_KEY` and `LLM_MODEL` to both steps |

---

## Phase 4: Customize (Optional)

### Step 4.1: Add Repository Context for the Agent

Create `.openhands/microagents/repo.md` in your target repo with any context the agent should know (coding conventions, architecture, test commands, etc.).

### Step 4.2: Adjust Model Aliases

Edit `remote-dev-bot.yaml` to add, remove, or change model aliases. The default model is set by the `default_model` field.

### Step 4.3: Adjust Iteration Limits

The `max_iterations` setting in `remote-dev-bot.yaml` controls how many steps the agent can take. Higher = more capable but more expensive. Default is 50. If using cheaper models that tend to loop, consider lowering to 30.

---

## Troubleshooting

### Agent doesn't trigger
- Verify the workflow file is on the default branch (usually `main`)
- Check that the commenter has collaborator/member/owner access to the repo
- Look at the Actions tab for failed runs
- Make sure the comment starts with exactly `/agent` (no leading spaces)

### Agent fails during setup steps (first 2 minutes)
- Check the run log — these are usually missing dependencies or config issues
- See the error table in Step 3.4 above for common issues and fixes

### Agent runs but hits max iterations
- The agent completed the work but couldn't gracefully stop
- Try a more capable model: `/agent-claude-medium` or `/agent-claude-large`
- Or lower `max_iterations` in `remote-dev-bot.yaml`

### Agent runs but skips PR creation
- The log will say "Issue was not successfully resolved. Skipping PR creation."
- This often means the agent hit max iterations — OpenHands marks this as "error" even if the code changes were correct
- Try again with a more capable model

### Agent produces bad results
- Add more context to the issue description
- Add repo context in `.openhands/microagents/repo.md`
- Comment `/agent` on the PR with specific feedback for another pass

---

## Future Phases (Not Yet Implemented)

These are planned but not yet built. See GitHub issues for discussion.

- [ ] **LLM account setup**: Walk through creating accounts, getting API keys, setting spending limits for each provider
- [ ] **Cost reporting**: Extract cost data from agent runs and post as PR comments
- [ ] **EC2 backend**: Run the agent on a dedicated EC2 instance instead of GitHub Actions (for longer runs, more resources, or cost optimization)
- [ ] **Testing infrastructure**: Separate test repo to avoid cluttering the main repo with test issues (see issue #5)
