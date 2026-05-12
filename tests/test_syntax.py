"""Syntax-level checks for Python files in the repo.

Most of `lib/` is invoked as scripts (`python3 lib/resolve.py`) rather than
imported by tests, so a SyntaxError can ship to `dev` without any test
catching it. The runtime symptom is a cryptic "agent process exited
unexpectedly" with $0.00 cost — see issue #497 for the incident that
motivated this test.

This module compiles every .py file under `lib/` and `scripts/` to catch
syntax errors at test time instead of in production.
"""

import py_compile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _python_files():
    files = []
    for sub in ("lib", "scripts"):
        d = REPO_ROOT / sub
        if d.exists():
            files.extend(sorted(d.rglob("*.py")))
    return files


@pytest.mark.parametrize(
    "py_file",
    _python_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_python_file_compiles(py_file):
    """Every .py file in lib/ and scripts/ must parse without SyntaxError."""
    try:
        py_compile.compile(str(py_file), doraise=True)
    except py_compile.PyCompileError as e:
        pytest.fail(f"Syntax error in {py_file.relative_to(REPO_ROOT)}: {e}")
