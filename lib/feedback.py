"""Install feedback reporting for remote-dev-bot.

Provides utilities for tracking install problems and reporting them as GitHub issues.
Used by AI agents following the runbook to report deviations and failures.

Key design decisions:
- Only report problems (deviations/failures), not successes
- Require explicit user consent before posting
- Search for existing issues before filing new ones
- Limit to 3 issues per install to avoid spam
- Group related problems into single issues
"""

import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InstallProblem:
    """A single problem encountered during installation."""

    step: str  # e.g., "2.1"
    title: str  # e.g., "Enable Actions Permissions"
    result: str  # "fail" or "deviate"
    expected: str  # What the runbook said to do
    actual: str  # What actually happened (error message, etc.)
    workaround: Optional[str] = None  # What the user did instead
    suggested_fix: Optional[str] = None  # How to update the runbook


@dataclass
class InstallReport:
    """Collection of problems from a single install attempt."""

    os_info: str = field(default_factory=lambda: f"{platform.system()}-{platform.release()}")
    shell: str = field(default_factory=lambda: os.environ.get("SHELL", "unknown"))
    problems: list[InstallProblem] = field(default_factory=list)

    def add_problem(
        self,
        step: str,
        title: str,
        result: str,
        expected: str,
        actual: str,
        workaround: Optional[str] = None,
        suggested_fix: Optional[str] = None,
    ) -> None:
        """Add a problem to the report."""
        self.problems.append(
            InstallProblem(
                step=step,
                title=title,
                result=result,
                expected=expected,
                actual=actual,
                workaround=workaround,
                suggested_fix=suggested_fix,
            )
        )

    def has_problems(self) -> bool:
        """Return True if any problems were recorded."""
        return len(self.problems) > 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "os": self.os_info,
            "shell": self.shell,
            "problems": [
                {
                    "step": p.step,
                    "title": p.title,
                    "result": p.result,
                    "expected": p.expected,
                    "actual": p.actual,
                    "workaround": p.workaround,
                    "suggested_fix": p.suggested_fix,
                }
                for p in self.problems
            ],
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


# Default repository for filing issues
DEFAULT_REPO = "gnovak/remote-dev-bot"
MAX_ISSUES_PER_INSTALL = 3


def get_environment_info() -> dict:
    """Gather environment information for the report."""
    return {
        "os": f"{platform.system()}-{platform.release()}",
        "shell": os.environ.get("SHELL", "unknown"),
        "python": platform.python_version(),
    }


def format_issue_title(problem: InstallProblem) -> str:
    """Format a GitHub issue title for a problem."""
    return f"Runbook: [Step {problem.step}] {problem.title}"


def format_issue_body(problem: InstallProblem, env_info: dict) -> str:
    """Format a GitHub issue body for a problem."""
    body = f"""## Environment
- OS: {env_info['os']}
- Shell: {env_info['shell']}

## Step that failed
Step {problem.step}: {problem.title}

## Expected behavior
{problem.expected}

## Actual behavior
{problem.actual}
"""

    if problem.workaround:
        body += f"""
## Workaround
{problem.workaround}
"""

    if problem.suggested_fix:
        body += f"""
## Suggested fix
{problem.suggested_fix}
"""

    return body


def format_metoo_comment(problem: InstallProblem, env_info: dict) -> str:
    """Format a 'me too' comment for an existing issue."""
    comment = f"""**Me too** — encountered the same issue.

**Environment:**
- OS: {env_info['os']}
- Shell: {env_info['shell']}

**What happened:**
{problem.actual}
"""

    if problem.workaround:
        comment += f"""
**Workaround used:**
{problem.workaround}
"""

    return comment


def format_summary_issue_body(report: InstallReport) -> str:
    """Format a summary issue body when too many problems occurred."""
    env_info = get_environment_info()
    body = f"""## Environment
- OS: {env_info['os']}
- Shell: {env_info['shell']}

## Summary
This install encountered {len(report.problems)} problems, suggesting a fundamental issue.

## Problems encountered
"""

    for i, problem in enumerate(report.problems, 1):
        body += f"""
### {i}. Step {problem.step}: {problem.title}
- **Result:** {problem.result}
- **Expected:** {problem.expected}
- **Actual:** {problem.actual}
"""
        if problem.workaround:
            body += f"- **Workaround:** {problem.workaround}\n"
        if problem.suggested_fix:
            body += f"- **Suggested fix:** {problem.suggested_fix}\n"

    return body


def search_existing_issues(
    search_term: str, repo: str = DEFAULT_REPO, state: str = "open"
) -> list[dict]:
    """Search for existing issues matching a search term.

    Returns a list of matching issues with their number, title, and URL.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "search",
                "issues",
                "--repo",
                repo,
                "--state",
                state,
                "--json",
                "number,title,url",
                search_term,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []
    except json.JSONDecodeError:
        return []


def find_matching_issue(problem: InstallProblem, repo: str = DEFAULT_REPO) -> Optional[dict]:
    """Find an existing issue that matches this problem.

    Searches by step number first, then by title keywords.
    Returns the first matching issue or None.
    """
    # Search by step number
    step_search = f"Step {problem.step}"
    issues = search_existing_issues(step_search, repo)
    if issues:
        return issues[0]

    # Search by title keywords (first few words)
    title_words = problem.title.split()[:3]
    if title_words:
        title_search = " ".join(title_words)
        issues = search_existing_issues(title_search, repo)
        if issues:
            return issues[0]

    return None


def file_issue(
    title: str, body: str, repo: str = DEFAULT_REPO, labels: Optional[list[str]] = None
) -> Optional[dict]:
    """File a new GitHub issue.

    Returns the created issue info (number, url) or None on failure.
    """
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]

    if labels:
        for label in labels:
            cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # gh issue create outputs the URL on success
        url = result.stdout.strip()
        # Extract issue number from URL
        if url:
            number = url.rstrip("/").split("/")[-1]
            return {"number": number, "url": url}
        return None
    except subprocess.CalledProcessError:
        return None


def add_comment(issue_number: str, body: str, repo: str = DEFAULT_REPO) -> bool:
    """Add a comment to an existing issue.

    Returns True on success, False on failure.
    """
    try:
        subprocess.run(
            ["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def report_problems(
    report: InstallReport, repo: str = DEFAULT_REPO, dry_run: bool = False
) -> dict:
    """Report all problems from an install attempt.

    Handles searching for existing issues, filing new ones, and adding comments.
    Respects the MAX_ISSUES_PER_INSTALL limit.

    Args:
        report: The InstallReport containing problems to report
        repo: The GitHub repository to file issues on
        dry_run: If True, don't actually file issues, just return what would be done

    Returns:
        A dict with:
        - filed: list of newly filed issues
        - commented: list of issues that received comments
        - skipped: list of problems that were skipped (due to limits)
        - errors: list of problems that failed to report
    """
    if not report.has_problems():
        return {"filed": [], "commented": [], "skipped": [], "errors": []}

    env_info = get_environment_info()
    result = {"filed": [], "commented": [], "skipped": [], "errors": []}

    # If too many problems, file a summary issue instead
    if len(report.problems) > MAX_ISSUES_PER_INSTALL:
        title = f"Runbook: Multiple problems during install ({len(report.problems)} issues)"
        body = format_summary_issue_body(report)

        if dry_run:
            result["filed"].append({"title": title, "body": body, "dry_run": True})
        else:
            issue = file_issue(title, body, repo, labels=["runbook-feedback"])
            if issue:
                result["filed"].append(issue)
            else:
                result["errors"].append({"title": title, "error": "Failed to file issue"})

        return result

    # Process each problem individually
    issues_filed = 0
    for problem in report.problems:
        # Check if we've hit the limit
        if issues_filed >= MAX_ISSUES_PER_INSTALL:
            result["skipped"].append(
                {"step": problem.step, "reason": "Issue limit reached"}
            )
            continue

        # Search for existing issue
        existing = find_matching_issue(problem, repo)

        if existing:
            # Add a "me too" comment
            comment = format_metoo_comment(problem, env_info)
            if dry_run:
                result["commented"].append(
                    {
                        "issue": existing,
                        "comment": comment,
                        "dry_run": True,
                    }
                )
            else:
                if add_comment(str(existing["number"]), comment, repo):
                    result["commented"].append(existing)
                else:
                    result["errors"].append(
                        {"step": problem.step, "error": "Failed to add comment"}
                    )
        else:
            # File a new issue
            title = format_issue_title(problem)
            body = format_issue_body(problem, env_info)

            if dry_run:
                result["filed"].append({"title": title, "body": body, "dry_run": True})
                issues_filed += 1
            else:
                issue = file_issue(title, body, repo, labels=["runbook-feedback"])
                if issue:
                    result["filed"].append(issue)
                    issues_filed += 1
                else:
                    result["errors"].append(
                        {"step": problem.step, "error": "Failed to file issue"}
                    )

    return result


def get_consent_prompt(report: InstallReport) -> str:
    """Generate the consent prompt to show the user."""
    env_info = get_environment_info()
    problem_count = len(report.problems)
    problem_word = "problem" if problem_count == 1 else "problems"

    return f"""Your install encountered {problem_count} {problem_word} that could help improve the runbook. Would you like to report them to the remote-dev-bot project?

This will post the following information publicly to GitHub:
- Your operating system ({env_info['os']})
- Which steps failed or required workarounds
- What you did to fix them

Your GitHub username will be visible as the issue author. No secrets or repository contents will be shared.

Do you want to continue? (yes/no)"""
