"""Tests for lib/feedback.py — install feedback reporting."""

import json
from unittest.mock import patch

import pytest

from lib.feedback import (
    DEFAULT_REPO,
    MAX_ISSUES_PER_INSTALL,
    InstallProblem,
    InstallReport,
    add_comment,
    file_issue,
    find_matching_issue,
    format_issue_body,
    format_issue_title,
    format_metoo_comment,
    format_summary_issue_body,
    get_consent_prompt,
    get_environment_info,
    report_problems,
    search_existing_issues,
)


# --- InstallProblem tests ---


def test_install_problem_basic():
    """InstallProblem should store all fields."""
    problem = InstallProblem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="gh api should succeed",
        actual="403 Forbidden",
        workaround="Used web UI",
        suggested_fix="Add admin note",
    )

    assert problem.step == "2.1"
    assert problem.title == "Enable Actions Permissions"
    assert problem.result == "fail"
    assert problem.expected == "gh api should succeed"
    assert problem.actual == "403 Forbidden"
    assert problem.workaround == "Used web UI"
    assert problem.suggested_fix == "Add admin note"


def test_install_problem_optional_fields():
    """InstallProblem optional fields should default to None."""
    problem = InstallProblem(
        step="1.1",
        title="Check gh",
        result="fail",
        expected="version shown",
        actual="not found",
    )

    assert problem.workaround is None
    assert problem.suggested_fix is None


def test_install_problem_from_exception():
    """InstallProblem.from_exception should create problem from exception."""
    exc = ValueError("something went wrong")
    problem = InstallProblem.from_exception(
        step="2.1",
        title="Enable Actions Permissions",
        exc=exc,
        expected="gh api should succeed",
        workaround="Used web UI",
    )

    assert problem.step == "2.1"
    assert problem.title == "Enable Actions Permissions"
    assert problem.result == "fail"
    assert problem.expected == "gh api should succeed"
    assert problem.actual == "ValueError: something went wrong"
    assert problem.workaround == "Used web UI"


def test_install_problem_from_exception_minimal():
    """InstallProblem.from_exception should work with minimal args."""
    exc = RuntimeError("oops")
    problem = InstallProblem.from_exception(
        step="1.1",
        title="Check gh",
        exc=exc,
        expected="version shown",
    )

    assert problem.result == "fail"
    assert problem.actual == "RuntimeError: oops"
    assert problem.workaround is None
    assert problem.suggested_fix is None


# --- InstallReport tests ---


def test_install_report_auto_collects_environment():
    """InstallReport should auto-collect environment info."""
    report = InstallReport()

    # Should have non-empty values auto-collected
    assert isinstance(report.os_info, str)
    assert len(report.os_info) > 0
    assert isinstance(report.shell, str)
    assert isinstance(report.python_version, str)
    assert len(report.python_version) > 0


def test_install_report_add_problem():
    """InstallReport.add_problem should add problems to the list."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="deviate",
        expected="CLI method",
        actual="403 error",
        workaround="Used web UI",
        suggested_fix="Add admin note",
    )

    assert len(report.problems) == 1
    assert report.problems[0].step == "2.1"
    assert report.problems[0].workaround == "Used web UI"


def test_install_report_has_problems():
    """InstallReport.has_problems should return True when problems exist."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    assert not report.has_problems()

    report.add_problem(
        step="1.1",
        title="Check gh",
        result="fail",
        expected="version shown",
        actual="not found",
    )
    assert report.has_problems()


def test_install_report_to_dict():
    """InstallReport.to_dict should include all fields including python."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="deviate",
        expected="CLI method",
        actual="403 error",
        workaround="Used web UI",
        suggested_fix="Add admin note",
    )

    d = report.to_dict()
    assert d["os"] == "Linux-5.4.0"
    assert d["shell"] == "/bin/bash"
    assert d["python"] == "3.11.0"
    assert len(d["problems"]) == 1
    assert d["problems"][0]["step"] == "2.1"
    assert d["problems"][0]["workaround"] == "Used web UI"


def test_install_report_to_json():
    """InstallReport.to_json should return valid JSON."""
    report = InstallReport(os_info="Darwin-24.6.0", shell="/bin/zsh", python_version="3.12.0")
    report.add_problem(
        step="1.1",
        title="Check gh",
        result="fail",
        expected="version shown",
        actual="not found",
    )

    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed["os"] == "Darwin-24.6.0"
    assert parsed["python"] == "3.12.0"
    assert len(parsed["problems"]) == 1


# --- Formatting functions ---


def test_format_issue_title():
    """format_issue_title should create proper title format."""
    problem = InstallProblem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )
    title = format_issue_title(problem)
    assert title == "Runbook: [Step 2.1] Enable Actions Permissions"


def test_format_issue_body():
    """format_issue_body should include all sections including Python."""
    problem = InstallProblem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="gh api should succeed",
        actual="403 Forbidden",
        workaround="Used web UI",
        suggested_fix="Add admin note",
    )
    env_info = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    body = format_issue_body(problem, env_info)

    assert "## Environment" in body
    assert "Linux-5.4.0" in body
    assert "/bin/bash" in body
    assert "Python: 3.11.0" in body
    assert "## Step that failed" in body
    assert "Step 2.1" in body
    assert "## Expected behavior" in body
    assert "gh api should succeed" in body
    assert "## Actual behavior" in body
    assert "403 Forbidden" in body
    assert "## Workaround" in body
    assert "Used web UI" in body
    assert "## Suggested fix" in body
    assert "Add admin note" in body


def test_format_issue_body_without_optional_fields():
    """format_issue_body should omit optional sections when not provided."""
    problem = InstallProblem(
        step="1.1",
        title="Check gh",
        result="fail",
        expected="version shown",
        actual="not found",
    )
    env_info = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    body = format_issue_body(problem, env_info)

    assert "## Workaround" not in body
    assert "## Suggested fix" not in body


def test_format_metoo_comment():
    """format_metoo_comment should create proper comment format with Python."""
    problem = InstallProblem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="403 Forbidden",
        workaround="Used web UI",
    )
    env_info = {"os": "Darwin-24.6.0", "shell": "/bin/zsh", "python": "3.12.0"}

    comment = format_metoo_comment(problem, env_info)

    assert "**Me too**" in comment
    assert "Darwin-24.6.0" in comment
    assert "/bin/zsh" in comment
    assert "Python: 3.12.0" in comment
    assert "403 Forbidden" in comment
    assert "Used web UI" in comment


@patch("lib.feedback.get_environment_info")
def test_format_summary_issue_body(mock_env):
    """format_summary_issue_body should list all problems with Python."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="1.1", title="Problem 1", result="fail", expected="a", actual="b"
    )
    report.add_problem(
        step="2.1",
        title="Problem 2",
        result="deviate",
        expected="c",
        actual="d",
        workaround="did something else",
    )

    body = format_summary_issue_body(report)

    assert "## Environment" in body
    assert "Linux-5.4.0" in body
    assert "Python: 3.11.0" in body
    assert "2 problems" in body
    assert "### 1. Step 1.1: Problem 1" in body
    assert "### 2. Step 2.1: Problem 2" in body
    assert "did something else" in body


# --- get_environment_info ---


def test_get_environment_info():
    """get_environment_info should return os, shell, and python."""
    env_info = get_environment_info()

    assert "os" in env_info
    assert "shell" in env_info
    assert "python" in env_info
    # Values should be non-empty strings
    assert isinstance(env_info["os"], str)
    assert len(env_info["os"]) > 0
    assert isinstance(env_info["python"], str)
    assert len(env_info["python"]) > 0


# --- get_consent_prompt ---


@patch("lib.feedback.get_environment_info")
def test_get_consent_prompt(mock_env):
    """get_consent_prompt should describe what will be shared."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    prompt = get_consent_prompt(report)

    assert "1 problem" in prompt
    assert "Linux-5.4.0" in prompt
    assert "GitHub" in prompt
    assert "yes/no" in prompt.lower() or "consent" in prompt.lower() or "continue" in prompt.lower()


def test_get_consent_prompt_plural():
    """get_consent_prompt should use plural for multiple problems."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(step="1.1", title="P1", result="fail", expected="a", actual="b")
    report.add_problem(step="2.1", title="P2", result="fail", expected="c", actual="d")

    prompt = get_consent_prompt(report)

    assert "2 problems" in prompt


# --- Constants ---


def test_default_repo():
    """DEFAULT_REPO should be set."""
    assert DEFAULT_REPO == "gnovak/remote-dev-bot"


def test_max_issues_per_install():
    """MAX_ISSUES_PER_INSTALL should be 3."""
    assert MAX_ISSUES_PER_INSTALL == 3


# --- report_problems dry_run ---


def test_report_problems_empty():
    """report_problems should return empty result for empty report."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")

    result = report_problems(report, dry_run=True)

    assert result["filed"] == []
    assert result["commented"] == []
    assert result["skipped"] == []
    assert result["errors"] == []


@patch("lib.feedback.find_matching_issue", return_value=None)
def test_report_problems_dry_run_files_new_issue(mock_find):
    """report_problems dry_run should show what would be filed."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    result = report_problems(report, dry_run=True)

    assert len(result["filed"]) == 1
    assert result["filed"][0]["dry_run"] is True
    assert "Enable Actions Permissions" in result["filed"][0]["title"]


@patch("lib.feedback.find_matching_issue")
def test_report_problems_dry_run_comments_existing(mock_find):
    """report_problems dry_run should show what would be commented."""
    mock_find.return_value = {"number": 42, "title": "Existing issue", "url": "https://..."}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    result = report_problems(report, dry_run=True)

    assert len(result["commented"]) == 1
    assert result["commented"][0]["dry_run"] is True
    assert result["commented"][0]["issue"]["number"] == 42


@patch("lib.feedback.find_matching_issue", return_value=None)
def test_report_problems_respects_limit(mock_find):
    """report_problems should skip problems beyond MAX_ISSUES_PER_INSTALL when exactly at limit."""
    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    # Add exactly MAX_ISSUES_PER_INSTALL problems (should file all, skip none)
    for i in range(MAX_ISSUES_PER_INSTALL):
        report.add_problem(
            step=f"{i}.1",
            title=f"Problem {i}",
            result="fail",
            expected="x",
            actual="y",
        )

    result = report_problems(report, dry_run=True)

    # Should file exactly MAX_ISSUES_PER_INSTALL issues
    assert len(result["filed"]) == MAX_ISSUES_PER_INSTALL
    assert len(result["skipped"]) == 0


@patch("lib.feedback.get_environment_info")
def test_report_problems_summary_for_many_problems(mock_env):
    """report_problems should file summary issue when > MAX_ISSUES_PER_INSTALL."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    # Add more problems than the limit + 1 to trigger summary
    for i in range(MAX_ISSUES_PER_INSTALL + 2):
        report.add_problem(
            step=f"{i}.1",
            title=f"Problem {i}",
            result="fail",
            expected="x",
            actual="y",
        )

    result = report_problems(report, dry_run=True)

    # Should file a single summary issue instead of individual ones
    assert len(result["filed"]) == 1
    assert "Multiple problems" in result["filed"][0]["title"]
    assert f"{MAX_ISSUES_PER_INSTALL + 2} issues" in result["filed"][0]["title"]


# --- Tests for subprocess-based functions (mocked) ---


@patch("lib.feedback.subprocess.run")
def test_search_existing_issues_success(mock_run):
    """search_existing_issues should return parsed JSON on success."""
    mock_run.return_value.stdout = '[{"number": 42, "title": "Test", "url": "https://..."}]'
    mock_run.return_value.returncode = 0

    result = search_existing_issues("Step 2.1")

    assert len(result) == 1
    assert result[0]["number"] == 42
    mock_run.assert_called_once()


@patch("lib.feedback.subprocess.run")
def test_search_existing_issues_empty_result(mock_run):
    """search_existing_issues should return empty list for empty result."""
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    result = search_existing_issues("nonexistent")

    assert result == []


@patch("lib.feedback.subprocess.run")
def test_search_existing_issues_subprocess_error(mock_run):
    """search_existing_issues should return empty list on subprocess error."""
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

    result = search_existing_issues("Step 2.1")

    assert result == []


@patch("lib.feedback.subprocess.run")
def test_search_existing_issues_json_error(mock_run):
    """search_existing_issues should return empty list on JSON parse error."""
    mock_run.return_value.stdout = "not valid json"
    mock_run.return_value.returncode = 0

    result = search_existing_issues("Step 2.1")

    assert result == []




@patch("lib.feedback.subprocess.run")
def test_search_existing_issues_custom_repo_and_state(mock_run):
    """search_existing_issues passes repo and state to gh."""
    mock_run.return_value.stdout = "[]"

    search_existing_issues("term", repo="myorg/myrepo", state="closed")

    call_args = mock_run.call_args[0][0]
    assert "--repo" in call_args
    assert "myorg/myrepo" in call_args
    assert "--state" in call_args
    assert "closed" in call_args


@patch("lib.feedback.search_existing_issues")
def test_find_matching_issue_by_step(mock_search):
    """find_matching_issue should find issue by step number."""
    mock_search.return_value = [{"number": 42, "title": "Step 2.1 issue"}]

    problem = InstallProblem(
        step="2.1", title="Enable Actions", result="fail", expected="x", actual="y"
    )
    result = find_matching_issue(problem)

    assert result["number"] == 42
    mock_search.assert_called_once_with("Step 2.1", DEFAULT_REPO)


@patch("lib.feedback.search_existing_issues")
def test_find_matching_issue_by_title(mock_search):
    """find_matching_issue should fall back to title search."""
    # First call (step search) returns empty, second call (title search) returns match
    mock_search.side_effect = [[], [{"number": 99, "title": "Enable Actions issue"}]]

    problem = InstallProblem(
        step="2.1", title="Enable Actions Permissions", result="fail", expected="x", actual="y"
    )
    result = find_matching_issue(problem)

    assert result["number"] == 99
    assert mock_search.call_count == 2


@patch("lib.feedback.search_existing_issues")
def test_find_matching_issue_not_found(mock_search):
    """find_matching_issue should return None when no match found."""
    mock_search.return_value = []

    problem = InstallProblem(
        step="2.1", title="Enable Actions", result="fail", expected="x", actual="y"
    )
    result = find_matching_issue(problem)

    assert result is None


@patch("lib.feedback.subprocess.run")
def test_file_issue_success(mock_run):
    """file_issue should return issue info on success."""
    mock_run.return_value.stdout = "https://github.com/owner/repo/issues/123"
    mock_run.return_value.returncode = 0

    result = file_issue("Test title", "Test body")

    assert result["number"] == "123"
    assert "123" in result["url"]


@patch("lib.feedback.subprocess.run")
def test_file_issue_with_labels(mock_run):
    """file_issue should include labels in command."""
    mock_run.return_value.stdout = "https://github.com/owner/repo/issues/456"
    mock_run.return_value.returncode = 0

    result = file_issue("Test title", "Test body", labels=["bug", "runbook"])

    assert result["number"] == "456"
    # Verify labels were passed
    call_args = mock_run.call_args[0][0]
    assert "--label" in call_args
    assert "bug" in call_args
    assert "runbook" in call_args


@patch("lib.feedback.subprocess.run")
def test_file_issue_failure(mock_run):
    """file_issue should return None on failure."""
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

    result = file_issue("Test title", "Test body")

    assert result is None


@patch("lib.feedback.subprocess.run")
def test_file_issue_empty_url(mock_run):
    """file_issue should return None when gh returns empty output."""
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    result = file_issue("Test title", "Test body")

    assert result is None


@patch("lib.feedback.subprocess.run")
def test_file_issue_without_labels(mock_run):
    """file_issue omits --label when labels is None."""
    mock_run.return_value.stdout = "https://github.com/example/repo/issues/1\n"

    file_issue("Title", "Body", labels=None)

    call_args = mock_run.call_args[0][0]
    assert "--label" not in call_args


@patch("lib.feedback.subprocess.run")
def test_add_comment_success(mock_run):
    """add_comment should return True on success."""
    mock_run.return_value.returncode = 0

    result = add_comment("42", "Test comment")

    assert result is True


@patch("lib.feedback.subprocess.run")
def test_add_comment_failure(mock_run):
    """add_comment should return False on failure."""
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

    result = add_comment("42", "Test comment")

    assert result is False


# --- report_problems with mocked subprocess (non-dry_run) ---


@patch("lib.feedback.file_issue")
@patch("lib.feedback.find_matching_issue", return_value=None)
def test_report_problems_files_new_issue(mock_find, mock_file):
    """report_problems should file new issue when no existing match."""
    mock_file.return_value = {"number": "123", "url": "https://..."}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    result = report_problems(report, dry_run=False)

    assert len(result["filed"]) == 1
    assert result["filed"][0]["number"] == "123"
    mock_file.assert_called_once()


@patch("lib.feedback.file_issue")
@patch("lib.feedback.find_matching_issue", return_value=None)
def test_report_problems_file_issue_failure(mock_find, mock_file):
    """report_problems should record error when file_issue fails."""
    mock_file.return_value = None

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    result = report_problems(report, dry_run=False)

    assert len(result["errors"]) == 1
    assert "Failed to file issue" in result["errors"][0]["error"]


@patch("lib.feedback.add_comment")
@patch("lib.feedback.find_matching_issue")
def test_report_problems_comments_existing_issue(mock_find, mock_comment):
    """report_problems should add comment to existing issue."""
    mock_find.return_value = {"number": 42, "title": "Existing issue", "url": "https://..."}
    mock_comment.return_value = True

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    result = report_problems(report, dry_run=False)

    assert len(result["commented"]) == 1
    assert result["commented"][0]["number"] == 42
    mock_comment.assert_called_once()


@patch("lib.feedback.add_comment")
@patch("lib.feedback.find_matching_issue")
def test_report_problems_comment_failure(mock_find, mock_comment):
    """report_problems should record error when add_comment fails."""
    mock_find.return_value = {"number": 42, "title": "Existing issue", "url": "https://..."}
    mock_comment.return_value = False

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Enable Actions Permissions",
        result="fail",
        expected="x",
        actual="y",
    )

    result = report_problems(report, dry_run=False)

    assert len(result["errors"]) == 1
    assert "Failed to add comment" in result["errors"][0]["error"]


@patch("lib.feedback.file_issue")
@patch("lib.feedback.get_environment_info")
def test_report_problems_summary_non_dry_run(mock_env, mock_file):
    """report_problems should file summary issue for many problems (non-dry_run)."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}
    mock_file.return_value = {"number": "999", "url": "https://..."}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    for i in range(MAX_ISSUES_PER_INSTALL + 2):
        report.add_problem(
            step=f"{i}.1",
            title=f"Problem {i}",
            result="fail",
            expected="x",
            actual="y",
        )

    result = report_problems(report, dry_run=False)

    assert len(result["filed"]) == 1
    assert result["filed"][0]["number"] == "999"
    mock_file.assert_called_once()


@patch("lib.feedback.file_issue")
@patch("lib.feedback.get_environment_info")
def test_report_problems_summary_file_failure(mock_env, mock_file):
    """report_problems should record error when summary issue filing fails."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}
    mock_file.return_value = None

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    for i in range(MAX_ISSUES_PER_INSTALL + 2):
        report.add_problem(
            step=f"{i}.1",
            title=f"Problem {i}",
            result="fail",
            expected="x",
            actual="y",
        )

    result = report_problems(report, dry_run=False)

    assert len(result["errors"]) == 1
    assert "Failed to file issue" in result["errors"][0]["error"]


@patch("lib.feedback.file_issue")
@patch("lib.feedback.find_matching_issue", return_value=None)
def test_report_problems_files_all_at_limit_non_dry_run(mock_find, mock_file):
    """report_problems should file all issues when exactly at MAX_ISSUES_PER_INSTALL."""
    mock_file.return_value = {"number": "123", "url": "https://..."}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    # Add exactly MAX_ISSUES_PER_INSTALL problems
    for i in range(MAX_ISSUES_PER_INSTALL):
        report.add_problem(
            step=f"{i}.1",
            title=f"Problem {i}",
            result="fail",
            expected="x",
            actual="y",
        )

    result = report_problems(report, dry_run=False)

    # Should file all MAX_ISSUES_PER_INSTALL issues, none skipped
    assert len(result["filed"]) == MAX_ISSUES_PER_INSTALL
    assert len(result["skipped"]) == 0
    assert mock_file.call_count == MAX_ISSUES_PER_INSTALL


# --- format_summary_issue_body edge cases ---


@patch("lib.feedback.get_environment_info")
def test_format_summary_issue_body_with_workaround(mock_env):
    """format_summary_issue_body should include workaround when present."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Problem with workaround",
        result="deviate",
        expected="CLI method",
        actual="403 error",
        workaround="Used web UI instead",
    )

    body = format_summary_issue_body(report)

    assert "Used web UI instead" in body
    assert "**Workaround:**" in body


@patch("lib.feedback.get_environment_info")
def test_format_summary_issue_body_with_suggested_fix(mock_env):
    """format_summary_issue_body should include suggested_fix when present."""
    mock_env.return_value = {"os": "Linux-5.4.0", "shell": "/bin/bash", "python": "3.11.0"}

    report = InstallReport(os_info="Linux-5.4.0", shell="/bin/bash", python_version="3.11.0")
    report.add_problem(
        step="2.1",
        title="Problem with fix",
        result="fail",
        expected="CLI method",
        actual="403 error",
        suggested_fix="Add admin note to runbook",
    )

    body = format_summary_issue_body(report)

    assert "Add admin note to runbook" in body
    assert "**Suggested fix:**" in body
