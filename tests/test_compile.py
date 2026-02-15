"""Tests for scripts/compile.py — workflow compiler."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml


def test_compile_produces_valid_yaml(tmp_path):
    """Compiler should produce valid YAML output."""
    # Import and run the compiler
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"
    output_path = tmp_path / "agent.yml"

    # Compile
    compile_workflow(str(shim_path), str(workflow_path), str(config_path), str(output_path))

    # Verify output exists
    assert output_path.exists()

    # Verify it's valid YAML
    with open(output_path) as f:
        data = yaml.safe_load(f)

    assert data is not None
    assert "name" in data
    assert "jobs" in data


def test_compile_has_required_markers():
    """Compiled workflow should have searchable configuration markers."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Read as text to check for markers
        with open(output_path) as f:
            content = f.read()

        # Check for configuration markers
        assert "MODEL_CONFIG" in content, "Missing MODEL_CONFIG marker"
        assert "SECURITY_GATE" in content, "Missing SECURITY_GATE marker"
        assert "MAX_ITERATIONS" in content, "Missing MAX_ITERATIONS marker"
        assert "PR_STYLE" in content, "Missing PR_STYLE marker"
        assert "PAT_TOKEN" in content, "Missing PAT_TOKEN documentation"

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_has_security_microagent():
    """Compiled workflow should include security microagent content."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Read as text
        with open(output_path) as f:
            content = f.read()

        # Check for security microagent
        assert "Security Rules (injected by remote-dev-bot)" in content
        assert "NEVER output, print, log, echo, or write environment variable values" in content
        assert "remote-dev-bot-security.md" in content

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_no_cross_repo_checkout():
    """Compiled workflow should not have cross-repo checkout steps."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Read as text
        with open(output_path) as f:
            content = f.read()

        # Should NOT have cross-repo checkout
        assert "gnovak/remote-dev-bot" not in content, "Should not checkout remote-dev-bot repo"
        assert ".remote-dev-bot" not in content, "Should not reference .remote-dev-bot directory"

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_has_correct_triggers():
    """Compiled workflow should trigger on correct events."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Parse YAML
        with open(output_path) as f:
            content = f.read()
            # Handle 'on' being parsed as True
            data = yaml.safe_load(content)
            if True in data and 'on' not in data:
                data['on'] = data.pop(True)

        # Check triggers
        assert 'on' in data
        triggers = data['on']
        assert 'issue_comment' in triggers
        assert 'pull_request_review_comment' in triggers
        assert triggers['issue_comment']['types'] == ['created']
        assert triggers['pull_request_review_comment']['types'] == ['created']

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_has_permissions():
    """Compiled workflow should have correct permissions."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Parse YAML
        with open(output_path) as f:
            data = yaml.safe_load(f)

        # Check permissions
        assert 'permissions' in data
        perms = data['permissions']
        assert perms['contents'] == 'write'
        assert perms['issues'] == 'write'
        assert perms['pull-requests'] == 'write'

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_inlines_model_aliases():
    """Compiled workflow should inline all model aliases."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Read as text
        with open(output_path) as f:
            content = f.read()

        # Check that model aliases are present
        assert "claude-small" in content
        assert "claude-medium" in content
        assert "claude-large" in content
        assert "openai-small" in content
        assert "gemini-medium" in content

        # Check that model IDs are present
        assert "anthropic/claude-sonnet-4-5" in content
        assert "openai/gpt-5-nano" in content
        assert "gemini/gemini-2.5-flash" in content

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_missing_source_file():
    """Compiler should exit with error if source file is missing."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Try to compile with missing file
        with pytest.raises(SystemExit) as exc_info:
            compile_workflow(
                "nonexistent.yml",
                "nonexistent2.yml",
                "nonexistent3.yaml",
                output_path
            )
        assert exc_info.value.code != 0

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_compile_uses_github_token_fallback():
    """Compiled workflow should use github.token as fallback."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.compile import compile_workflow

    workspace = Path(__file__).parent.parent
    shim_path = workspace / "examples" / "agent.yml"
    workflow_path = workspace / ".github" / "workflows" / "resolve.yml"
    config_path = workspace / "remote-dev-bot.yaml"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        output_path = f.name

    try:
        # Compile
        compile_workflow(str(shim_path), str(workflow_path), str(config_path), output_path)

        # Read as text
        with open(output_path) as f:
            content = f.read()

        # Check for PAT_TOKEN || github.token pattern
        assert "secrets.PAT_TOKEN || github.token" in content

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)
