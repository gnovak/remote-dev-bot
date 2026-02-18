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
