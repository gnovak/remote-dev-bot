"""Regression tests for module-level imports under the production sys.path layout.

The remote-dev-bot.yml workflow invokes the lib/ modules with
`sys.path.insert(0, '.remote-dev-bot/lib')` — i.e., only the lib/
directory is on sys.path, NOT the rdb repo root. Modules that import
their siblings as `from lib.X import ...` will silently break in
production while continuing to pass test suites that run with
`PYTHONPATH=.` (which adds both to the path).

This file spawns a subprocess with sys.path set up the same way as the
workflow heredoc, then imports each module. The subprocess isolation
matters: if the test process already has both paths on sys.path,
`from lib.X` will resolve from the rdb root and mask the bug.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
LIB_DIR = REPO_ROOT / "lib"


def _import_in_production_pathlayout(module_name: str) -> subprocess.CompletedProcess:
    """Run `python -c 'import <module_name>'` with only lib/ on sys.path.

    Mimics the production invocation: workflow heredocs do
    `sys.path.insert(0, '.remote-dev-bot/lib')` and then `from <module> import ...`.
    Returns the CompletedProcess so tests can assert on returncode and stderr.
    """
    # Match the workflow heredoc: prepend lib/ to sys.path, but leave stdlib
    # paths in place. Critically, the REPO ROOT (which would let `from lib.X`
    # resolve) must NOT be on sys.path — that's the production condition we're
    # reproducing.
    code = (
        "import sys; "
        f"sys.path = [p for p in sys.path if p not in ({str(REPO_ROOT)!r}, '')]; "
        f"sys.path.insert(0, {str(LIB_DIR)!r}); "
        f"import {module_name}"
    )
    # Use the same Python that's running pytest. PYTHONPATH must be cleared so
    # the parent process's path doesn't leak in and mask the bug.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestProductionSysPathImports:
    """Each library module must import cleanly when only lib/ is on sys.path."""

    @pytest.mark.parametrize("module_name", [
        "workshop",
        "cumulative_cost",
        "formatting",
        "context",
        "tools",
        "distill",
        "design_loop",
    ])
    def test_module_imports_with_only_lib_on_path(self, module_name):
        """The workflow heredoc puts only lib/ on sys.path. Modules must
        respect that — they must not assume the rdb repo root is also there
        (which would let `from lib.X import ...` work).

        If this fails for a module, change its top-level imports from
        `from lib.X import Y` to `from X import Y` to match the heredoc style.
        Modules that are *script entry points* (resolve.py, reconcile.py,
        post_fallback_cost.py) handle this themselves with a
        `sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))` —
        those are not tested here because they would have to be invoked as
        scripts, not imported.
        """
        result = _import_in_production_pathlayout(module_name)
        assert result.returncode == 0, (
            f"Importing {module_name!r} with production sys.path failed:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
