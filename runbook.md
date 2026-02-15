# Remote Dev Bot — Setup Runbook

## Overview

This runbook will guide you through setting up Remote Dev Bot on your GitHub repository. By the end, you'll have an AI-powered bot that can automatically resolve issues and create pull requests when triggered by a `/agent-resolve` comment.

**How the bot works:** When you comment `/agent-resolve` on an issue, a GitHub Actions workflow starts. It spins up [OpenHands](https://github.com/All-Hands-AI/OpenHands) (an open-source AI coding agent) in a sandboxed container, points it at your issue, and lets it work. The agent reads the issue, explores your codebase, writes code, runs tests, and iterates until it has a solution. Then it pushes a branch and opens a draft PR for your review. You can also use `/agent-design` for AI design analysis posted as a comment (no code changes).

**What you'll set up:**

1. **Phase 1: Install and Configure GitHub CLI** — Install the `gh` command-line tool and authenticate with GitHub
2. **Phase 2: GitHub Repository Settings** — Configure repository permissions, create API keys for your chosen LLM provider(s), and store them as GitHub secrets
3. **Phase 3: Install the Workflow** — Add a small workflow file to your repository that connects to the Remote Dev Bot system
4. **Phase 4: Test It** — Create a test issue and trigger the bot to verify everything works
5. **Phase 5: Customize (Optional)** — Add repository context, adjust model settings, and tune iteration limits

**Time estimate:** 15-30 minutes for initial setup, depending on whether you already have the GitHub CLI installed and authenticated.

---

## How to Use This Runbook

This file is both documentation and executable instructions. It's designed to be followed by:
- **A human** reading step-by-step
- **An AI assistant** (like Claude Code) that can execute steps, ask for confirmation, and handle errors

When following this runbook with an AI assistant, the assistant should **default to the guided experience** unless the user asks to go faster:
- Explain what each step does and why it's needed **before** executing it
- Ask for confirmation before each action (not just secrets — all steps)
- Ask whether the user already has API keys, PATs, etc. before creating new ones
- After each step, confirm it succeeded and explain what happened
- If a step fails, diagnose the issue and suggest recovery options
- Keep the user oriented: "We just finished X. Next is Y, which does Z."

Experienced users can ask for a faster pace (see prompt examples below), in which case the assistant should skip explanations and only pause for secrets and confirmations that require user input.

---

## Prerequisites

Before starting, make sure you have:

- [ ] A GitHub account
- [ ] A GitHub repository where you want the bot to operate
- [ ] **(For AI-assisted install)** An AI coding agent installed and configured. Supported options include:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` CLI)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini` CLI)
  - [OpenAI Codex CLI](https://github.com/openai/codex) (`codex` CLI)
  - Or any other AI coding assistant that can execute shell commands

Throughout this runbook, replace `{owner}/{repo}` with your actual GitHub owner and repo name (e.g., `myuser/myproject`).

---

## Using This Runbook with an AI Coding Agent

If you have an AI coding agent installed, you can have it guide you through the setup process.

**First time? Use the guided setup** (recommended):
```bash
claude "Follow the runbook.md file to set up remote-dev-bot for my repo {owner}/{repo}. This is my first time — walk me through each step, explain what's happening, and ask before doing anything."
```

**Done this before? Use the fast setup:**
```bash
claude "Follow the runbook.md file to set up remote-dev-bot for my repo {owner}/{repo}. I'm familiar with the process — go fast, just ask me for secrets and confirmations."
```

These examples use Claude Code, but the same prompts work with any AI coding agent (Gemini CLI, Codex CLI, etc.) — just replace `claude` with your agent's command.

The AI agent will read the runbook, execute the necessary commands, and prompt you when it needs your input (like pasting API keys or confirming GitHub settings changes).

---

## Phase 1: Install and Configure GitHub CLI

> **Note for humans:** This phase is optional if you prefer using the web interface. Throughout this runbook, most steps provide both web interface and command line options. If you skip this phase, just use the "Via web interface" instructions in later steps. The CLI is useful for automation and scripting, but not required.

### Step 1.1: Check if GitHub CLI is Already Installed

**What this does:** Verifies if you already have the GitHub command-line tool installed. If it's already installed, you can skip the installation step.

```bash
gh --version
```

If this command succeeds and shows a version number, you already have `gh` installed. Skip to Step 1.2.

If the command fails (command not found), proceed with the installation:

**On macOS:**
```bash
brew install gh
```

**On Linux (Debian/Ubuntu):**
```bash
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh -y
```

**On Linux (Fedora/RHEL/CentOS):**
```bash
sudo dnf install gh
```

**On Windows:**
Download and install from https://cli.github.com/ or use:
```bash
winget install --id GitHub.cli
```

**Other platforms:** See https://cli.github.com/ for installation instructions.

After installation, verify:
```bash
gh --version
```

### Step 1.2: Authenticate with GitHub

**What this does:** Logs you into GitHub through the command line so you can manage repositories, secrets, and workflows.

```bash
gh auth login
```

Follow the prompts:
- Choose **HTTPS** as your preferred protocol
- Choose **Login with a web browser**
- Copy the one-time code shown in your terminal
- Press Enter to open the browser (or manually go to https://github.com/login/device)
- Paste the code and authorize the GitHub CLI

### Step 1.3: Add Required Scopes

**What this does:** Grants the GitHub CLI permission to manage workflows and set up Git authentication.

```bash
# Add workflow scope (required to manage Actions workflows)
gh auth refresh --hostname github.com --scopes workflow

# Set up git credential helper (allows git commands to use gh authentication)
gh auth setup-git
```

### Step 1.4: Verify Authentication

**What this does:** Confirms that authentication is working correctly and you have the necessary permissions.

```bash
# Check authentication status
gh auth status
# Should show you logged in with the `workflow` scope

# Test by listing your repositories
gh repo list --limit 5
# Should show a list of your repositories

# Test by viewing info about your target repository
gh repo view {owner}/{repo}
# Replace {owner}/{repo} with your actual repo (e.g., myuser/myproject)
# Should show repository information including description and stats
```

If all these commands succeed, your GitHub CLI is properly configured!

---

## Phase 2: GitHub Repository Settings

### Step 2.1: Enable Actions Permissions

**What this does:** Allows GitHub Actions workflows to create branches and pull requests in your repository.

**Via web interface:**
1. Go to `https://github.com/{owner}/{repo}/settings/actions`
2. Scroll down to "Workflow permissions"
3. Select "Read and write permissions"
4. Check "Allow GitHub Actions to create and approve pull requests"
5. Click "Save"

**Via command line:**
```bash
gh api repos/{owner}/{repo}/actions/permissions/workflow \
  --method PUT \
  --field default_workflow_permissions=write \
  --field can_approve_pull_request_reviews=true
```

**Verify:**

*Via web:* Go to `https://github.com/{owner}/{repo}/settings/actions` and check that the settings are as described above.

*Via command line:*
```bash
gh api repos/{owner}/{repo}/actions/permissions/workflow
# Should show: default_workflow_permissions: "write", can_approve_pull_request_reviews: true
```

### Step 2.2: Create an LLM API Key

**What this does:** The agent needs an API key to call the LLM. You need at least one key for whichever provider you want to use.

> **Already have an API key?** One API key works across all your repos — just set the same key as a secret on each repo (Step 2.3). You don't need a separate key per repo. Skip ahead to Step 2.3.
>
> **Per-repo keys (optional):** If you want to track API costs per repo, create a separate key for each one and name it after the repo (e.g., "remote-dev-bot-myrepo"). This is optional — most users share one key.

**For Anthropic (Claude models):**
1. Go to https://console.anthropic.com/settings/keys
2. Click "+ Create Key"
3. Name it "remote-dev-bot" (or "remote-dev-bot-myrepo" if using per-repo keys)
4. Leave the workspace as "Default" (unless you have a specific workspace)
5. Click "Add"
6. **Copy the key immediately** — you won't be able to see it again

**For OpenAI (GPT models):**
1. Go to https://platform.openai.com/api-keys (note: this is separate from your ChatGPT account)
2. Click "Create new secret key"
3. Name it "remote-dev-bot", set permissions to "All"
4. Click "Create secret key"
5. **Copy the key immediately** — you won't be able to see it again
6. **Billing:** You must add a payment method at https://platform.openai.com/settings/organization/billing/overview before the key will work. New accounts get a $100/month usage limit by default; you can adjust this in the limits page.

**For Google (Gemini models):**
1. Go to https://aistudio.google.com/app/apikey (this is Google AI Studio — much simpler than the Google Cloud Console, but uses the same underlying API)
2. Sign in with your Google account and accept the Terms of Service if prompted
3. Click "Create API Key", name it "remote-dev-bot", then select or create a Google Cloud project
4. **Copy the key immediately** (it starts with `AIza`)
5. **Billing:** The free tier works for testing and light use (5-15 RPM depending on model). On the free tier, a compromised key can't cost you money — it's just rate-limited. For production use, enable billing on the underlying Google Cloud project. Paid tier (Tier 1) unlocks 150-300 RPM.
6. **Note:** Google AI Studio is separate from a Google One AI Premium subscription ($20/mo). The subscription gives access to the Gemini chatbot; it does not provide API credits or affect API billing.
7. **Useful links:** [API keys](https://aistudio.google.com/app/apikey) · [Usage & rate limits](https://aistudio.google.com/app/usage) · [Projects](https://aistudio.google.com/app/projects)

**Tip:** Store your API key in a password manager. Name it "remote-dev-bot" so you can find it later when adding it to other repos.

### Step 2.2.1: Set Cost Limits (Recommended)

**What this does:** Configures spending limits on your LLM provider accounts to prevent unexpected charges. Each provider handles this differently.

**For OpenAI:**

OpenAI provides two types of limits:
- **Usage limits** — caps how much you can spend per month
- **Charge limits** — caps how much can be charged to your payment method per month

1. Go to https://platform.openai.com/settings/organization/limits
2. Under "Usage limits":
   - Set a monthly budget (e.g., $20 for testing, $100 for regular use)
   - You'll receive email notifications at 50%, 75%, and 100% of your limit
   - API calls will be rejected once you hit the limit
3. Under "Charge limits" (if available):
   - This caps the actual charges to your payment method
   - Useful as a secondary safeguard

**Recommended starting point:** Set usage limit to $20-50 while testing. Increase as needed once you understand your usage patterns.

**For Anthropic:**

Anthropic provides usage limits that cap your monthly spending.

1. Go to https://console.anthropic.com/settings/limits
2. Set your monthly spend limit (e.g., $20 for testing, $100 for regular use)
3. You'll receive email notifications as you approach the limit
4. API calls will be rejected once you hit the limit

**Recommended starting point:** Set limit to $20-50 while testing. Increase as needed.

**For Google (Gemini):**

⚠️ **Important:** Google's billing model makes it difficult to set hard spending limits. Unlike OpenAI and Anthropic, Google is post-paid and does not offer dollar-based caps that stop API calls.

**What you can do:**

1. **Use the free tier** (recommended for testing): Stay on the free tier and your costs are capped at $0. The free tier has rate limits (5-15 RPM depending on model) but works fine for testing.

2. **Set up budget alerts** (advisory only — does NOT stop spending):
   - Go to https://console.cloud.google.com/billing/budgets
   - Create a budget (e.g., $100)
   - Configure email alerts at 50%, 90%, and 100%
   - **Note:** This only sends emails — it does NOT stop API calls when exceeded

3. **Set API quotas** (rate limits, not dollar limits):
   - Go to https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas
   - The most relevant quotas to limit are:
     - `GenerateContent requests per minute per region` — e.g., set to 3-10
     - `Request limit per model per day per project` — e.g., set to 100-500
     - `GenerateContent input token count per model per minute` — e.g., set to 20,000-100,000
   - **Note:** These limit API calls, not dollars. A few expensive calls can still add up.

**Recommended approach for Google:** If you need hard cost limits, consider using OpenAI or Anthropic instead. If you must use Google with billing enabled, set conservative API quotas and monitor your budget alerts closely. The free tier is the only way to guarantee $0 spend.

### Step 2.3: Add Repository Secrets

**What this does:** Stores your API keys securely as GitHub repository secrets so the workflow can use them. Secret values are encrypted and never exposed in logs.

**Via web interface:**
1. Go to `https://github.com/{owner}/{repo}/settings/secrets/actions`
2. Click "New repository secret"
3. For the Name, enter `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` or `GEMINI_API_KEY` depending on your provider)
4. Paste your API key in the Secret field
5. Click "Add secret"
6. Repeat for any additional API keys you need

**Via command line:**

**Important:** The `gh secret set` command reads the secret value from your terminal interactively. You must run these commands yourself (not through an AI assistant's shell) so you can paste the key when prompted.

```bash
# Set the API key for whichever provider(s) you're using:
gh secret set ANTHROPIC_API_KEY --repo {owner}/{repo}
# Paste your Anthropic API key when prompted, then press Enter

gh secret set OPENAI_API_KEY --repo {owner}/{repo}
gh secret set GEMINI_API_KEY --repo {owner}/{repo}
```

**Verify:**

*Via web:* Go to `https://github.com/{owner}/{repo}/settings/secrets/actions` — you should see your secrets listed (values are hidden).

*Via command line:*
```bash
gh secret list --repo {owner}/{repo}
# Should list the secrets you just set (values are hidden)
```

### Step 2.4: Create a Personal Access Token (PAT) — Optional

> **You can skip this step.** The compiled single-file workflow (Step 3.1) works without a PAT. The only thing you lose is automatic CI triggering: when the bot creates a PR, your CI checks won't run automatically. You can always trigger them manually, or come back and add a PAT later.

<details>
<summary><strong>Click to expand PAT setup instructions</strong> (needed only if you want bot PRs to auto-trigger CI)</summary>

#### Why a PAT Helps

GitHub's default `GITHUB_TOKEN` can push branches and create PRs, but PRs it creates won't trigger other workflows (like CI checks). This is a GitHub security feature to prevent infinite loops. A PAT bypasses this limitation.

With the single-file install, the PAT only needs access to your own repo — no cross-repo scoping required.

#### Instructions

1. Go to https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Click "Generate new token"
3. **Token name:** "remote-dev-bot" (or "remote-dev-bot-myrepo" for per-repo tokens)
4. **Expiration:** No expiration is fine for a token scoped to one repo
5. **Resource owner:** Your GitHub account
6. **Repository access:** Select "Only select repositories" and choose your target repo
7. **Permissions** — under "Repository permissions", set these to **Read and write**:
   - Contents
   - Issues
   - Pull requests
   - Workflows
8. Click "Generate token"
9. **Copy the token immediately** — you won't be able to see it again

Store the token as a repository secret:

```bash
gh secret set PAT_TOKEN --repo {owner}/{repo}
# Paste the token when prompted, then press Enter
```

> **Already have a PAT?** If you have an existing PAT scoped to "All repositories", just set it as a secret: `gh secret set PAT_TOKEN --repo {owner}/{repo}`.

</details>

---

## Phase 3: Install the Workflow

### Step 3.1: Download the Workflow File

**What this does:** Adds two self-contained workflow files to your repository. Each file includes everything the bot needs — model configuration, config parsing, security guardrails, and the agent runner.

```bash
# From within the target repo:
mkdir -p .github/workflows
curl -o .github/workflows/agent-resolve.yml \
  https://github.com/gnovak/remote-dev-bot/releases/latest/download/agent-resolve.yml
curl -o .github/workflows/agent-design.yml \
  https://github.com/gnovak/remote-dev-bot/releases/latest/download/agent-design.yml
```

The files are self-contained and configurable. Search for these markers to customize:
- `MODEL_CONFIG` — change the default model or available aliases
- `MAX_ITERATIONS` — adjust how many steps the agent can take
- `PR_STYLE` — switch between draft and ready PRs
- `SECURITY_GATE` — change who can trigger the agent

### Step 3.2: Push and Verify

```bash
git add .github/workflows/agent-resolve.yml .github/workflows/agent-design.yml
git commit -m "Add remote dev bot workflows"
git push
```

> **New empty repo?** If your repository has no commits yet, you'll need to set the branch name before pushing: `git branch -M main` before `git push -u origin main`.

**Verify the workflow is recognized:**

*Via web:* Go to `https://github.com/{owner}/{repo}/actions` — you should see "Remote Dev Bot" listed in the left sidebar under "All workflows".

*Via command line:*
```bash
gh workflow list --repo {owner}/{repo}
# Should show "Remote Dev Bot"
```

<details>
<summary><strong>Alternative: Shim install (auto-updating)</strong></summary>

Instead of the self-contained file, you can use a thin shim that calls the reusable workflow from `gnovak/remote-dev-bot`. This means you automatically get updates when the bot is improved, but requires a PAT with cross-repo access.

```yaml
name: Remote Dev Bot

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  resolve:
    if: >
      (github.event.issue || github.event.pull_request) &&
      startsWith(github.event.comment.body, '/agent-') &&
      contains(fromJson('["OWNER","COLLABORATOR","MEMBER"]'), github.event.comment.author_association)
    uses: gnovak/remote-dev-bot/.github/workflows/resolve.yml@main
    secrets: inherit
```

This requires:
- A PAT with access to both your repo and `gnovak/remote-dev-bot` (see Step 2.4)
- The PAT stored as `PAT_TOKEN` secret on your repo

**Using your own fork:** For full control, fork `gnovak/remote-dev-bot` and point the `uses:` line at your fork. You'll need to set Actions access to `user` level on the fork (see Troubleshooting).

</details>

---

## Phase 4: Test It

### Step 4.1: Create a Test Issue

**Via web interface:**
1. Go to `https://github.com/{owner}/{repo}/issues/new`
2. Title: `Test: Add a hello world script`
3. Body: `Create a simple hello.py that prints 'Hello from Remote Dev Bot'`
4. Click "Submit new issue"

**Via command line:**
```bash
gh issue create --repo {owner}/{repo} \
  --title "Test: Add a hello world script" \
  --body "Create a simple hello.py that prints 'Hello from Remote Dev Bot'"
```

### Step 4.2: Trigger the Agent

Comment on the issue to trigger the agent. For your first test, use `claude-medium` (Sonnet) — it handles the task lifecycle more reliably than `claude-small` (Haiku).

**Via web interface:**
1. Go to `https://github.com/{owner}/{repo}/issues/{issue-number}` (or click on the issue you just created)
2. Scroll to the comment box at the bottom
3. Type `/agent-resolve-claude-medium`
4. Click "Comment"

**Via command line:**
```bash
gh issue comment {issue-number} --repo {owner}/{repo} --body "/agent-resolve-claude-medium"
```

### Step 4.3: Monitor the Run

**Via web interface:**
1. Go to `https://github.com/{owner}/{repo}/actions`
2. Click on "Remote Dev Bot" in the left sidebar to filter to just this workflow
3. Click on the most recent run to see its status and logs
4. Click on the "resolve" job to see detailed step-by-step logs

**Via command line:**
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

### Step 4.4: Check Results

If successful, you should see:
- A new branch created by the agent
- A draft PR linked to the issue
- A rocket emoji reaction on your `/agent-resolve` comment

**Via web interface:**
- Go to `https://github.com/{owner}/{repo}/pulls` to see the new draft PR
- Or check the issue page — it should have a link to the PR in the sidebar

**Via command line:**
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
| `Missing Anthropic API Key` or `x-api-key header is required` | API key not set or set empty | Re-set the secret via web (`https://github.com/{owner}/{repo}/settings/secrets/actions`) or `gh secret set` |
| `Agent reached maximum iteration` | Agent loops instead of finishing | Try `/agent-resolve-claude-medium` instead of `/agent-resolve` |
| `429 Too Many Requests` | GitHub API rate limit | Wait a few minutes and try again |
| `KeyError: 'LLM_API_KEY'` in PR creation step | Missing env vars in PR step | Update workflow to pass `LLM_API_KEY` and `LLM_MODEL` to both steps |
| Workflow file issue (instant failure, 0s) | Reusable workflow not accessible | Set Actions access to `user` level on remote-dev-bot (see below) |
| `Not Found` on config checkout step | PAT can't access remote-dev-bot repo | PAT must include remote-dev-bot in its repository scope (update at `https://github.com/settings/tokens`) |
| `404 Not Found` on issues API (Resolve step) | PAT doesn't cover the target repo | Update PAT to "All repositories" or add the target repo to its scope (at `https://github.com/settings/tokens`) |

---

## Phase 5: Customize (Optional)

### Step 5.1: Add Repository Context for the Agent

Create `.openhands/microagents/repo.md` in your target repo with any context the agent should know (coding conventions, architecture, test commands, etc.).

### Step 5.2: Adjust Model Aliases

Edit `remote-dev-bot.yaml` to add, remove, or change model aliases. The default model is set by the `default_model` field.

### Step 5.3: Adjust Iteration Limits

The `max_iterations` setting in `remote-dev-bot.yaml` controls how many steps the agent can take. Higher = more capable but more expensive. Default is 50. If using cheaper models that tend to loop, consider lowering to 30.

---

## Troubleshooting

### Cross-repo reusable workflow access

The shim in your target repo calls `resolve.yml` from `gnovak/remote-dev-bot`. For this to work with a private repo, you must enable Actions access sharing on `remote-dev-bot`:

**Via web interface:**
1. Go to `https://github.com/gnovak/remote-dev-bot/settings/actions`
2. Scroll down to "Access" section
3. Select "Accessible from repositories owned by the user 'gnovak'" (or your fork's owner)
4. Click "Save"

**Via command line:**
```bash
gh api repos/gnovak/remote-dev-bot/actions/permissions/access \
  --method PUT \
  --field access_level=user
```

This allows all repos owned by the same user to call reusable workflows in `remote-dev-bot`. Without this, the shim will fail instantly with "workflow file issue."

Also ensure your PAT token covers all repos involved — both the target repo and `remote-dev-bot`. The simplest approach is to set the PAT to "All repositories" scope in your GitHub token settings (at `https://github.com/settings/tokens`).

### Agent doesn't trigger
- Verify the shim workflow file is on the default branch (usually `main`) of the target repo
- Check that the commenter has collaborator/member/owner access to the repo
- Look at the Actions tab for failed runs (go to `https://github.com/{owner}/{repo}/actions`)
- Make sure the comment starts with exactly `/agent-resolve` or `/agent-design` (no leading spaces)
- Verify the shim points to the correct ref (e.g., `@main` or `@dev`)

### Agent fails during setup steps (first 2 minutes)
- Check the run log — these are usually missing dependencies or config issues
- See the error table in Step 4.4 above for common issues and fixes

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
- Comment `/agent-resolve` on the PR with specific feedback for another pass

---

## Future Phases (Not Yet Implemented)

These are planned but not yet built. See GitHub issues for discussion.

- [x] **LLM account setup**: Walk through creating accounts, getting API keys, setting spending limits for each provider (done — see Step 2.2 and Step 2.2.1)
- [ ] **Cost reporting**: Extract cost data from agent runs and post as PR comments
- [ ] **EC2 backend**: Run the agent on a dedicated EC2 instance instead of GitHub Actions (for longer runs, more resources, or cost optimization)
- [x] **Reusable workflow**: Split into shim + reusable workflow so target repos auto-update (done)
- [x] **Testing infrastructure**: Separate test repo (`remote-dev-bot-test`) with shim pointed at `@dev` branch (done)
