"""Shared tool implementations for resolve, reconcile, and design_loop agents.

All three agent loops (lib/resolve.py, lib/reconcile.py, lib/design_loop.py)
use the same core set of tools: path validation, dangerous-command detection,
bash execution, file reading, and grep. This module provides canonical
implementations with flags for the minor behavioral variants each caller needs.
"""

import os
import re
import subprocess


def validate_path(path, *, repo_bounds=True):
    """Validate that a path is safe (no directory traversal, within repo).

    Parameters
    ----------
    path : str
        The path to validate.
    repo_bounds : bool
        When True (default), rejects paths outside the current working
        directory even if they pass the .. and absolute-path checks.
        Pass False for design_loop, which instead checks that the
        path exists on disk.

    Returns
    -------
    (ok, result) : (bool, str)
        (True, normalized_path) on success; (False, error_message) on failure.
    """
    normalized = os.path.normpath(path)
    if normalized.startswith("..") or os.path.isabs(normalized):
        if repo_bounds:
            return False, "Path must be relative to repository root and cannot use '..'"
        else:
            return False, f"Access denied: path '{path}' is outside the repository"

    if repo_bounds:
        abs_path = os.path.abspath(normalized)
        repo_root = os.path.abspath(".")
        if not abs_path.startswith(repo_root):
            return False, "Path must be within the repository"
    else:
        if not os.path.exists(normalized):
            return False, f"File not found: {normalized}"

    return True, normalized


def is_dangerous_command(command):
    """Return (True, reason) if a command matches a blocked pattern."""
    dangerous_patterns = [
        (r"\brm\s+-rf\s+/", "rm -rf / is not allowed"),
        (r"\bdd\s+if=", "dd if= is not allowed"),
        (r":\(\)\s*\{.*\}", "fork bomb pattern is not allowed"),
        (r">\s*/dev/sd[a-z]", "direct disk write is not allowed"),
    ]
    for pattern, reason in dangerous_patterns:
        if re.search(pattern, command):
            return True, reason
    return False, ""


def execute_bash(command, *, timeout=30, bash_output_limit=0):
    """Execute a bash command in the repository root.

    Parameters
    ----------
    command : str
        The shell command to run.
    timeout : int
        Seconds before the command is killed. Default 30; pass 300 for
        reconcile which needs longer-running git operations.
    bash_output_limit : int
        Maximum characters of output to return. 0 means unlimited.
    """
    dangerous, reason = is_dangerous_command(command)
    if dangerous:
        return f"Error: {reason}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.abspath("."),
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            output = f"(exit code {result.returncode})\n" + output
        output = output or "(no output)"
        if bash_output_limit > 0 and len(output) > bash_output_limit:
            half = bash_output_limit // 2
            output = (
                output[:half]
                + f"\n\n... [output truncated: {len(output)} chars total, showing first and last {half} chars] ...\n\n"
                + output[-half:]
            )
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {e}"


def execute_read_file(path, *, list_directory=False, repo_bounds=True):
    """Read a file from the repository.

    Parameters
    ----------
    path : str
        Path to the file, relative to the repository root.
    list_directory : bool
        When True, if path points to a directory return a sorted listing
        instead of an error. Used by design_loop.
    """
    valid, result = validate_path(path, repo_bounds=repo_bounds)
    if not valid:
        return f"Error: {result}"
    if not os.path.exists(result):
        return f"Error: File not found: {path}"
    if os.path.isdir(result):
        if list_directory:
            try:
                entries = sorted(os.listdir(result))
                return f"Directory listing for {result}:\n" + "\n".join(entries)
            except Exception as e:
                return f"Error listing directory: {e}"
        return f"Error: Path is a directory, not a file: {path}"
    try:
        with open(result) as f:
            content = f.read()
        if len(content) > 50000:
            content = (
                content[:50000]
                + "\n\n... (file truncated, showing first 50000 characters)"
            )
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def execute_grep(pattern, path=None):
    """Search for a pattern in repository files using git grep."""
    try:
        cmd = ["git", "grep", "-n", "--no-color", pattern]
        if path:
            valid, validated_path = validate_path(path)
            if not valid:
                return f"Error: {validated_path}"
            cmd.extend(["--", validated_path])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if not output:
            return "No matches found."
        lines = output.split("\n")
        if len(lines) > 100:
            output = "\n".join(lines[:100]) + f"\n\n... ({len(lines) - 100} more matches truncated)"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Search timed out"
    except Exception as e:
        return f"Error executing grep: {e}"
