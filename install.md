# Remote Dev Bot — Setup Guide

## Quick Start

This guide will walk you through setting up Remote Dev Bot on your GitHub
repository. By the end, you'll have an AI-powered bot that can automatically
resolve issues and create pull requests when triggered by a `/agent-resolve`
comment.

The easiest way to install is to tell your favorite AI agent "Follow the
runbook.md file to set up remote-dev-bot for my repo {owner}/{repo}."

---

## Overview

**How the bot works:** When you comment `/agent-resolve` on an issue, a GitHub
Actions workflow starts. It runs a custom LiteLLM agent loop, points it at your
issue, and lets it work. The agent reads the issue, explores your codebase,
writes code, runs tests, and iterates until it has a solution. Then it pushes a
branch and opens a draft PR for your review. You can also use `/agent-design` for AI design analysis posted
as a comment (no code changes), or `/agent-review` on a pull request to get an
AI code review. Once you have human or machine generated comments and requested
changes on the PR, you can comment '/agent-resolve' on the PR to make the
requested changes.

**What you'll set up:**

1. **Phase 1: Install and Configure GitHub CLI** — Install the `gh` command-line
   tool and authenticate with GitHub
2. **Phase 2: GitHub Repository Settings** — Configure repository permissions,
   create API keys for your chosen LLM provider(s), and store them as GitHub
   secrets
3. **Phase 3: Install the Workflow** — Add a small workflow file to your
   repository that connects to the Remote Dev Bot system
4. **Phase 4: Test It** — Create a test issue and trigger the bot to verify
   everything works
5. **Phase 5: Customize (Optional)** — See README.md for adding repo context,
   adjusting models, and tuning iteration limits
6. **Phase 6: Report Install Feedback (Optional)** — If you encountered
   problems, report them to help improve the guide

**Time estimate:** 15-30 minutes for initial setup, depending on whether you
already have the GitHub CLI installed and authenticated.

---

## How to Use This Guide

This file is both documentation and executable instructions. It's designed to be
followed by:

- **A human** reading step-by-step
- **An AI assistant** (like Claude Code) that can execute steps, ask for
  confirmation, and handle errors

When following this guide with an AI assistant, the assistant should **default
to the guided experience** unless the user asks to go faster:

- Explain what each step does and why it's needed **before** executing it
- Ask for confirmation before each action (not just secrets — all steps)
- Ask whether the user already has API keys, PATs, etc. before creating new ones
- After each step, confirm it succeeded and explain what happened
- If a step fails, diagnose the issue and suggest recovery options
- Keep the user oriented: "We just finished X. Next is Y, which does Z."

Experienced users can ask for a faster pace (see prompt examples below), in
which case the assistant should skip explanations and only pause for secrets and
confirmations that require user input.

---

## Prerequisites

Before starting, make sure you have:

- [ ] A GitHub account
- [ ] A GitHub repository where you want the bot to operate
- [ ] **(For AI-assisted install)** An AI coding agent installed and configured.
      Supported options include:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` CLI)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini` CLI)
  - [OpenAI Codex CLI](https://github.com/openai/codex) (`codex` CLI)
  - Or any other AI coding assistant that can execute shell commands

Throughout this guide, replace `{owner}/{repo}` with your actual GitHub owner
and repo name (e.g., `myuser/myproject`).

---

## Using This Guide with an AI Coding Agent

If you have an AI coding agent installed, you can have it guide you through the
setup process.

**First time? Use the guided setup** (recommended):

```bash
claude "Follow the install.md file to set up remote-dev-bot for my repo {owner}/{repo}. This is my first time — walk me through each step, explain what's happening, and ask before doing anything."
```

**Done this before? Use the fast setup:**

```bash
claude "Follow the install.md file to set up remote-dev-bot for my repo {owner}/{repo}. I'm familiar with the process — go fast, just ask me for secrets and confirmations."
```

These examples use Claude Code, but the same prompts work with any AI coding
agent (Gemini CLI, Codex CLI, etc.) — just replace `claude` with your agent's
command.

The AI agent will read this guide, execute the necessary commands, and prompt
you when it needs your input (like pasting API keys or confirming GitHub
settings changes).

---

## Phase 1: Install and Configure GitHub CLI

> **Note for humans:** This phase is optional if you prefer using the web
> interface. Throughout this guide, most steps provide both web interface and
> command line options. If you skip this phase, just use the "Via web interface"
> instructions in later steps. The CLI is useful for automation and scripting,
> but not required.

### Step 1.1: Check if GitHub CLI is Already Installed

**What this does:** Verifies if you already have the GitHub command-line tool
installed. If it's already installed, you can skip the installation step.

```bash
gh --version
```

If this command succeeds and shows a version number, you already have `gh`
installed. Skip to Step 1.2.

If the command fails (command not found), proceed with the installation:

**On macOS:**

```bash
brew install gh
```

**On Linux (Debian/Ubuntu):**

`gh` isn't in the standard Debian/Ubuntu repositories, so this script adds
GitHub's own apt repository first (downloading their signing key and registering
the repo), then installs from it:

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

**On Windows:** Download and install from https://cli.github.com/ or use:

```bash
winget install --id GitHub.cli
```

**Other platforms:** See https://cli.github.com/ for installation instructions.

After installation, verify:

```bash
gh --version
```

### Step 1.2: Authenticate with GitHub

**What this does:** Logs you into GitHub through the command line so you can
manage repositories, secrets, and workflows.

```bash
gh auth login
```

Follow the prompts:

- Choose **HTTPS** as your preferred protocol
- Choose **Login with a web browser**
- Copy the one-time code shown in your terminal
- Press Enter to open the browser (or manually go to
  https://github.com/login/device)
- Paste the code and authorize the GitHub CLI

### Step 1.3: Verify Authentication

**What this does:** Confirms that authentication is working correctly and you
have the necessary permissions.

```bash
# Check authentication status
gh auth status

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

**What this does:** Allows GitHub Actions workflows to create branches and pull
requests in your repository.

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

_Via web:_ Go to `https://github.com/{owner}/{repo}/settings/actions` and check
that the settings are as described above.

_Via command line:_

```bash
gh api repos/{owner}/{repo}/actions/permissions/workflow
# Should show: default_workflow_permissions: "write", can_approve_pull_request_reviews: true
```

### Step 2.2: Create an LLM API Key

**What this does:** The agent needs an API key to call the LLM. You need at
least one key for whichever provider you want to use.

> **Already have an API key?** One API key works across all your repos — just
> set the same key as a secret on each repo (Step 2.3). You don't need a
> separate key per repo. Skip ahead to Step 2.3.
>
> **Per-repo keys (optional):** If you want to track API costs per repo, create
> a separate key for each one and name it after the repo (e.g.,
> "remote-dev-bot-myrepo"). This is optional — most users share one key.

**For Anthropic (Claude models):**

1. Go to https://console.anthropic.com/settings/keys
2. Click "+ Create Key"
3. Name it "remote-dev-bot" (or "remote-dev-bot-myrepo" if using per-repo keys)
4. Leave the workspace as "Default" (unless you have a specific workspace)
5. Click "Add"
6. **Copy the key immediately** — you won't be able to see it again

**For OpenAI (GPT models):**

1. Go to https://platform.openai.com/api-keys (note: this is separate from your
   ChatGPT account)
2. Click "Create new secret key"
3. Name it "remote-dev-bot", set permissions to "All"
4. Click "Create secret key"
5. **Copy the key immediately** — you won't be able to see it again
6. **Billing:** You must add a payment method at
   https://platform.openai.com/settings/organization/billing/overview before the
   key will work. New accounts get a $100/month usage limit by default; you can
   adjust this in the limits page.

**For Google (Gemini models):**

1. Go to https://aistudio.google.com/app/apikey (this is Google AI Studio — much
   simpler than the Google Cloud Console, but uses the same underlying API)
2. Sign in with your Google account and accept the Terms of Service if prompted
3. Click "Create API Key", name it "remote-dev-bot", then select or create a
   Google Cloud project
4. **Copy the key immediately** (it starts with `AIza`)
5. **Billing:** The free tier works for testing and light use (5-15 RPM
   depending on model). On the free tier, a compromised key can't cost you money
   — it's just rate-limited. For production use, enable billing on the
   underlying Google Cloud project. Paid tier (Tier 1) unlocks 150-300 RPM.
6. **Note:** Google AI Studio is separate from a Google One AI Premium
   subscription ($20/mo). The subscription gives access to the Gemini chatbot;
   it does not provide API credits or affect API billing.

**Tip:** Store your API key in a password manager.

### Step 2.2.1: Set Cost Limits (Recommended)

**What this does:** Configures spending limits on your LLM provider accounts to
prevent unexpected charges. Each provider handles this differently.

**For OpenAI:**

OpenAI provides two types of limits:

- **Usage limits** — caps how much you can spend per month
- **Charge limits** — caps how much can be charged to your payment method per
  month

1. Go to https://platform.openai.com/settings/organization/limits
2. Under "Usage limits":
   - Set a monthly budget (e.g., $20 for testing, $100 for regular use)
   - You'll receive email notifications at 50%, 75%, and 100% of your limit
   - API calls will be rejected once you hit the limit
3. Under "Charge limits" (if available):
   - This caps the actual charges to your payment method
   - Useful as a secondary safeguard

**Recommended starting point:** Set usage limit to $20-50 while testing.
Increase as needed once you understand your usage patterns.

**For Anthropic:**

Anthropic provides usage limits that cap your monthly spending.

1. Go to https://console.anthropic.com/settings/limits
2. Set your monthly spend limit (e.g., $20 for testing, $100 for regular use)
3. You'll receive email notifications as you approach the limit
4. API calls will be rejected once you hit the limit

**Recommended starting point:** Set limit to $20-50 while testing. Increase as
needed.

**For Google (Gemini):**

⚠️ **Important:** Google's billing model makes it difficult to set hard spending
limits. Unlike OpenAI and Anthropic, Google is post-paid and does not offer
dollar-based caps that stop API calls.

**What you can do:**

1. **Use the free tier** (recommended for testing): Stay on the free tier and
   your costs are capped at $0. The free tier has rate limits (5-15 RPM
   depending on model) but works fine for testing.

2. **Set up budget alerts** (advisory only — does NOT stop spending):
   - Go to https://console.cloud.google.com/billing/budgets
   - Create a budget (e.g., $100)
   - Configure email alerts at 50%, 90%, and 100%
   - **Note:** This only sends emails — it does NOT stop API calls when exceeded

3. **Set API quotas** (rate limits, not dollar limits):
   - Go to
     https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas
   - The most relevant quotas to limit are:
     - `GenerateContent requests per minute per region` — e.g., set to 30
     - `Request limit per model per day per project` — e.g., set to 1000
     - `GenerateContent input token count per model per minute` — e.g., set to
       500,000
   - **Note:** These limit API calls, not dollars. The limits suggested here are
     conservative in an attempt to limit the damage that can be caused by a
     leaked API key, but the resulting bill can still be large.

**Recommended approach for Google:** If you need hard cost limits, consider
using OpenAI or Anthropic instead. If you must use Google with billing enabled,
set conservative API quotas and monitor your budget alerts closely. The free
tier is the only way to guarantee $0 spend.

### Step 2.3: Add Repository Secrets

**What this does:** Stores your API keys securely as GitHub repository secrets
so the workflow can use them. Secret values are encrypted and never exposed in
logs.

**Via web interface:**

1. Go to `https://github.com/{owner}/{repo}/settings/secrets/actions`
2. Click "New repository secret"
3. For the Name, enter `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` or
   `GEMINI_API_KEY` depending on your provider)
4. Paste your API key in the Secret field
5. Click "Add secret"
6. Repeat for any additional API keys you need

**Via command line:**

**Important:** The `gh secret set` command reads the secret value from your
terminal interactively. You must run these commands yourself (not through an AI
assistant's shell) so you can paste the key when prompted.

```bash
# Set the API key for whichever provider(s) you're using:
gh secret set ANTHROPIC_API_KEY --repo {owner}/{repo}
# Paste your Anthropic API key when prompted, then press Enter

gh secret set OPENAI_API_KEY --repo {owner}/{repo}
gh secret set GEMINI_API_KEY --repo {owner}/{repo}
```

**Verify:**

_Via web:_ Go to `https://github.com/{owner}/{repo}/settings/secrets/actions` —
you should see your secrets listed (values are hidden).

_Via command line:_

```bash
gh secret list --repo {owner}/{repo}
# Should list the secrets you just set (values are hidden)
```

### Step 2.3.1: Create remote-dev-bot.yaml

**What this does:** Sets `default_model` in your repo's config file to match
the API key you just added. Without this step, the bot defaults to a Claude
model — which will fail on the first run if you added a Gemini or OpenAI key
instead.

Start from the provided template, which includes commented examples of the most
useful options:

```bash
# From within the target repo:
curl -o remote-dev-bot.yaml \
  https://raw.githubusercontent.com/gnovak/remote-dev-bot/main/remote-dev-bot.yaml.template
```

Then open the file and uncomment the `default_model` line that matches your API
key:

- `default_model: claude-small` — if you added `ANTHROPIC_API_KEY`
- `default_model: gemini-small` — if you added `GEMINI_API_KEY`
- `default_model: gpt-small` — if you added `OPENAI_API_KEY`

The rest of the file shows available options with explanations — all commented
out, so there are no active overrides until you choose to enable them. Browse
it to see what's configurable; you can always come back and tweak later.

### Step 2.4: Bot Identity & CI Triggering

**Choose your path:**

- **Just trying it out?** Skip this step entirely. The bot works out of the box
  using GitHub's built-in `GITHUB_TOKEN` — it pushes branches, creates PRs, and
  posts comments as `github-actions[bot]`. The only limitation is that
  bot-created PRs won't auto-trigger your CI workflows (you can trigger CI
  manually). Come back and set this up once you're sold.

- **Ready to commit?** The typical setup uses a GitHub App (Option A below). It
  gives the bot a clear identity, auto-triggers CI on bot PRs, and doesn't
  involve rotating tokens. This is the recommended long-term setup.

**Options A and B are alternatives — pick one, not both.**

| Option                       | Skip for now | Bot identity           | CI triggers | Setup effort                      |
| ---------------------------- | ------------ | ---------------------- | ----------- | --------------------------------- |
| **None** (default)           | ✓            | `github-actions[bot]`  | No          | None                              |
| **GitHub App** (recommended) |              | `your-app-name[bot]`   | Yes         | Create app, set variable + secret |
| **PAT**                      |              | Posts as the PAT owner | Yes         | Create PAT, set secret            |

<details>
<summary><strong>Option A: GitHub App (recommended for long-term use)</strong></summary>

A GitHub App gives the bot a clear, distinct identity and triggers CI on bot
PRs. Token management is automatic — no expiring PATs to rotate.

**First time setting up the app:**

1. Go to https://github.com/settings/apps/new
2. **Name:** Choose a name (this becomes the `name[bot]` identity)
   - **Avatar:** The bot will use the app owner's avatar by default. To set a
     custom avatar, upload one on the app settings page after creation.
3. **Homepage URL:** Your repo URL is fine
4. **Uncheck** Webhook "Active" (not needed)
5. **Repository permissions** — set to Read & write:
   - Contents
   - Issues
   - Pull requests
6. **Where can this app be installed:** "Only on this account" is fine
7. Click "Create GitHub App"
8. Note the **App ID** shown on the app's settings page
9. Scroll down and click **Generate a private key** (downloads a `.pem` file)
   - **Store the key securely:** Copy the full contents of the `.pem` file into
     your password manager (name it "remote-dev-bot private key" or similar),
     then delete the downloaded file. You won't be able to download it again —
     if lost, you'll need to generate a new one.
10. Click **Install App** in the left sidebar
    - **Private app note:** If the app is not published to the GitHub
      Marketplace, it won't appear in your repo's Settings → Integrations list.
      You must install it from the app settings page.
    - Choose **"Only select repositories"** and pick your target repo — or
      **"All repositories"** if you plan to use the bot on multiple repos.
      Installing on all repositories is safe: the bot only acts on repos where
      `RDB_APP_PRIVATE_KEY` is configured.

Store the credentials on your repo:

```bash
# Store App ID as a repository variable (not a secret — it's not sensitive)
gh variable set RDB_APP_ID --repo {owner}/{repo}
# Enter the App ID when prompted

# Store the private key as a repository secret
gh secret set RDB_APP_PRIVATE_KEY --repo {owner}/{repo} < path/to/your-app.pem
```

**Adding the bot to another repo (app already exists):**

You don't need a new key — reuse the same App ID and private key. You just need
to:

1. Go to your app's settings page (https://github.com/settings/apps) and click
   **Install App**, then add the new repo
2. Set the same credentials on the new repo:

```bash
gh variable set RDB_APP_ID --repo {owner}/{new-repo}
# Enter the same App ID

gh secret set RDB_APP_PRIVATE_KEY --repo {owner}/{new-repo} < path/to/your-app.pem
```

</details>

<details>
<summary><strong>Option B: Personal Access Token (PAT)</strong></summary>

A PAT is an alternative to the GitHub App. Choose this if you prefer not to
create a GitHub App, but note that the bot will post as your personal account,
which can be confusing if you're also commenting on the same issues.

**Alternatives to posting as yourself:**

- Organizations can create a dedicated GitHub user (e.g., `my-org-bot`) and use
  that user's PAT
- This gives a distinct identity without the complexity of a GitHub App

1. Go to https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Click "Generate new token"
3. **Token name:** "remote-dev-bot"
4. **Expiration:** No expiration is fine for a token scoped to one repo
5. **Resource owner:** Your GitHub account (or the bot account)
6. **Repository access:** Select "Only select repositories" and choose your
   target repo
7. **Permissions** — under "Repository permissions", set these to **Read and
   write**:
   - Contents
   - Issues
   - Pull requests
8. Click "Generate token"
9. **Copy the token immediately** — you won't be able to see it again

Store the token as a repository secret:

```bash
gh secret set RDB_PAT_TOKEN --repo {owner}/{repo}
# Paste the token when prompted, then press Enter
```

</details>

---

## Phase 3: Install the Workflow

### Step 3.1: Download the Workflow File

**What this does:** Adds a thin shim workflow to your repository. The shim calls
the reusable workflow from `gnovak/remote-dev-bot`, so you automatically get
updates when the bot is improved — no need to download new releases.

```bash
# From within the target repo:
mkdir -p .github/workflows
curl -o .github/workflows/agent.yml \
  https://raw.githubusercontent.com/gnovak/remote-dev-bot/main/.github/workflows/agent.yml
```

The file is self-documenting — read the comments at the top for notes on
optional secrets and auth.

**Using your own fork:** For full control, fork `gnovak/remote-dev-bot`, then
edit the `uses:` line to point at your fork. If the fork is in the same
owner/org as your target repos, `secrets: inherit` will work. You'll need to set
Actions access to `user` level on the fork (see Troubleshooting).

**Note to `gnovak/remote-dev-bot` users:** GitHub does not notify repo owners
when someone forks their repository. If you'd like the maintainer to know about
your usage (and potentially get notified of relevant updates), consider starring
the repo or opening a brief issue.

### Step 3.2: Commit and Push the Workflow File

```bash
git add .github/workflows/agent.yml
git commit -m "Add remote dev bot workflow"
```

> **AI agents:** Stop here. Pushing `.github/workflows/` files requires
> `workflow` scope, which your `gh` credential helper may not have. Ask the user
> to run `git push` (or `git push -u origin main` for a new repo) and confirm it
> succeeded before continuing.

> **New empty repo?** If your repository has no commits yet, you'll need to set
> the branch name before pushing:
> `git branch -M main && git push -u origin main`.

Push to your repo:

```bash
git push
```

> **Common gotcha — `workflow` scope:** Pushing `.github/workflows/` files
> requires the `workflow` OAuth scope, which the GitHub CLI may not request by
> default. If `git push` fails with a permission or scope error, you have two
> options:
>
> - **Option 1 (recommended):** Run `gh auth refresh -s workflow` to add the
>   scope to your existing credentials, then retry `git push`.
> - **Option 2:** The file is already committed — just run
>   `git push origin <branch>` directly with your regular git credentials
>   (SSH key, credential manager, etc.) instead of going through `gh`.

**Verify the workflow is recognized:**

_Via web:_ Go to `https://github.com/{owner}/{repo}/actions` — you should see
"Remote Dev Bot" listed in the left sidebar under "All workflows".

_Via command line:_

```bash
gh workflow list --repo {owner}/{repo}
# Should show "Remote Dev Bot"
```

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

Comment on the issue to trigger the agent.

**Via web interface:**

1. Go to `https://github.com/{owner}/{repo}/issues/{issue-number}` (or click on
   the issue you just created)
2. Scroll to the comment box at the bottom
3. Type `/agent-resolve`
4. Click "Comment"

**Via command line:**

```bash
gh issue comment {issue-number} --repo {owner}/{repo} --body "/agent-resolve"
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

1. Set up dependencies (~1-2 min)
2. Read the issue and work on the solution (~3-7 min)
3. Create a draft PR (~30 sec)

### Step 4.4: Check Results

If successful, you should see:

- A new branch created by the agent
- A draft PR linked to the issue
- A rocket emoji reaction on your `/agent-resolve` comment
- You're auto-assigned to the issue (so your issues list shows what has active
  work)

**Via web interface:**

- Go to `https://github.com/{owner}/{repo}/pulls` to see the new draft PR
- Or check the issue page — it should have a link to the PR in the sidebar

**Via command line:**

```bash
gh pr list --repo {owner}/{repo}
```

**If the run fails**, check the logs for the specific error. Some issues:

| Error                                                         | Cause                                     | Fix                                                                                              |
| ------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `Missing Anthropic API Key` or `x-api-key header is required` | API key not reaching the workflow         | Re-check the secret value via web (`https://github.com/{owner}/{repo}/settings/secrets/actions`) |
| `Agent reached maximum iteration`                             | Agent may be looping instead of finishing | Try a more capable model                                                                         |
| Workflow file issue (instant failure, 0s)                     | Reusable workflow not accessible          | If using a private fork of `gnovak/remote-dev-bot` set Actions access to `user` level            |

---

## Phase 5: Customize (Optional)

See the Customization section in `README.md` for details on adding repo context
for the agent, adjusting model aliases, and changing iteration limits. These can
be done any time after install — not just during initial setup.

---

## Phase 6: Report Install Feedback (Optional)

> **This phase only applies if you encountered problems during installation.**
> If everything worked perfectly, you're done! Skip to the Troubleshooting
> section if you need help with specific issues.

### Why Report Feedback?

If your install required workarounds or failed at certain steps, reporting this
helps improve the guide for future users. Your feedback tells us exactly what
needs to be fixed.

### What Gets Reported

The report includes:

- **Environment info**: Operating system, shell type
- **What went wrong**: Which steps failed or required deviations
- **What you did instead**: The workaround or fix you used (if any)

The report does **not** include:

- API keys or secrets
- Repository contents
- Personal information beyond your GitHub username (which is public anyway)

### For AI Assistants / Agents

> **This section is for AI agents executing this guide.** If you're a human
> following this guide manually and encounter problems, you can file issues
> directly at https://github.com/gnovak/remote-dev-bot/issues — no special
> format required.

If you're an AI agent executing this guide, you should automatically collect
problem details as you go through the phases. The user should not need to
provide this information — you observed what happened.

**During execution:**

As you execute each phase, track any problems that occur:

```python
from lib.feedback import InstallReport, InstallProblem

# Create a report at the start of the install
report = InstallReport()

# When a step fails or requires a workaround, record it:
report.add_problem(
    step="2.1",
    title="Enable Actions Permissions",
    result="fail",  # or "deviate" if you found a workaround
    expected="gh api command should succeed",
    actual="403 Forbidden - user lacks admin access",
    workaround="Used web UI instead",  # optional
    suggested_fix="Add note that admin access is required"  # optional
)
```

**Important:** Do not include secrets, API keys, tokens, or other sensitive data
in problem reports. You have no reason to include them, so this should be
straightforward.

**After all phases complete:**

If problems were recorded, ask the user for consent before filing:

```python
from lib.feedback import get_consent_prompt, report_problems

if report.has_problems():
    # Show the user what will be reported and ask for consent
    print(get_consent_prompt(report))

    # Only proceed if the user explicitly consents
    if user_confirms():  # Your agent's method for getting user confirmation
        result = report_problems(report, dry_run=False)
        print(f"Filed {len(result['filed'])} new issues")
        print(f"Added comments to {len(result['commented'])} existing issues")
```

**What the library handles automatically:**

- Environment collection (OS, shell, Python version)
- Searching for existing issues to avoid duplicates
- Adding "me too" comments to existing issues instead of filing duplicates
- Limiting to 3 issues per install to avoid spam
- Grouping many problems into a single summary issue

**Consent is required:** The `report_problems()` function will post to GitHub
using the user's credentials. Always show the user what will be reported (via
`get_consent_prompt()`) and get explicit confirmation before calling
`report_problems()`.

---

## Security

See the [Security section in README.md](README.md#security) for an overview of
who can trigger the agent, what it can access, prompt injection mitigations, and
recommendations.

---

## Troubleshooting

### Cross-repo reusable workflow access (shim install only)

The shim calls `remote-dev-bot.yml` from `gnovak/remote-dev-bot`. Since that
repo is public, this works automatically — no special access settings needed.

**If using a private fork:** You must enable Actions access sharing on your
fork:

1. Go to your fork's Settings → Actions → General → Access
2. Select "Accessible from repositories owned by the user" (or org)
3. Click "Save"

Without this, the shim will fail instantly with "workflow file issue."

### Secrets not reaching the reusable workflow (shim install only)

If the agent fails with `x-api-key header is required` or similar authentication
errors, check that secrets are passed explicitly in the shim (not via
`secrets: inherit`). GitHub Actions does not pass inherited secrets across
different repo owners. See the shim template in `.github/workflows/agent.yml`.

### Agent doesn't trigger

- Verify the shim workflow file is on the default branch (usually `main`) of the
  target repo
- Check that the commenter has collaborator/member/owner access to the repo
- Look at the Actions tab for failed runs (go to
  `https://github.com/{owner}/{repo}/actions`)
- Make sure the comment starts with exactly `/agent-resolve`, `/agent-design`,
  or `/agent-review` (no leading spaces)
- Verify the shim points to the correct ref (e.g., `@main` or `@dev`)

### Agent fails during setup steps (first 2 minutes)

- Check the run log — these are usually missing dependencies or config issues
- See the error table in Step 4.4 above for common issues and fixes

### Agent runs but hits max iterations

- The agent completed the work but couldn't gracefully stop
- Try a more capable model: `/agent-resolve-claude-large`
- Or increase `max_iterations` in `remote-dev-bot.yaml`

### Agent runs but skips PR creation

- The log will say "Issue was not successfully resolved. Skipping PR creation."
- This often means the agent hit max iterations — it will mark this as
  "error" even if the code changes were correct
- Try again with a more capable model

### Agent produces bad results

- Add more context to the issue description
- Add repo context via `AGENTS.md` or `CLAUDE.md` and include it in `extra_files`
  in your `remote-dev-bot.yaml`
- Comment `/agent-resolve` on the PR with specific feedback for another pass
