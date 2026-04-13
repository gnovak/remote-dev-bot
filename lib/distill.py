"""Context distillation pre-step for reducing agent exploration costs.

Gathers the target codebase, makes a single LLM call to extract only what's
relevant to the task, and returns a focused context block for the agent.

Three tiers:
  1. Small repos (<= DISTILL_SMALL_REPO_LIMIT tokens): send full codebase
  2. Medium repos (<= DISTILL_STRUCT_EXTRACT_LIMIT tokens): send structural
     extract, identify relevant files, read those in full (second pass)
  3. Large repos: skip distillation entirely (return original context)
"""

import ast
import os
import subprocess

from litellm import completion


# --- Constants (all hardcoded — no user-facing config) ---

# Token budget for the distillation call input
DISTILL_SMALL_REPO_LIMIT = 100_000    # tokens — try to send whole codebase
DISTILL_STRUCT_EXTRACT_LIMIT = 300_000  # tokens — for medium repos, use structural extract

# Per-file size caps before truncation (in characters)
SOURCE_FILE_CAP = 50_000    # for source/config files
OTHER_FILE_CAP = 8_000      # for other text files

# Characters of truncated file shown from beginning + end (symmetric)
TRUNC_HALF_CHARS = 2_000          # for source files
OTHER_TRUNC_HALF_CHARS = 500      # for non-source files

# Extensions treated as "source files" (generous cap, send in full if possible)
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".html", ".css", ".scss", ".sass", ".less",
    ".sql", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json",
    ".md", ".rst", ".txt",
    ".rb", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cpp", ".h",
    ".tf", ".hcl",
}

# Extensions that are always skipped (binary/junk/generated)
SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd",
    ".min.js", ".min.css",
    ".map",
    ".lock",
    ".dat", ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".ogg",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".pdf", ".docx", ".xlsx",
    ".so", ".dylib", ".dll", ".exe",
    ".wasm",
}

# Directories always skipped
SKIP_DIRS = {
    "node_modules", ".git", "venv", ".venv", "env",
    "dist", "build", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".eggs",
    "coverage", ".coverage",
}

# Output token budget for the distillation call
DISTILL_OUTPUT_TOKENS = 8_192

# Output token budget for structural extract (medium repo pass 1)
STRUCT_OUTPUT_TOKENS = 16_384

# First N lines to include for non-Python files in structural extract
STRUCT_EXTRACT_HEAD_LINES = 30


# --- File gathering ---

def _should_skip_path(path):
    """Check if a path should be skipped based on directory or extension rules."""
    parts = path.split(os.sep)
    # Check directory components
    for part in parts[:-1]:  # all but the filename
        if part in SKIP_DIRS:
            return True
        # Handle glob-style patterns like *.egg-info
        for skip_dir in SKIP_DIRS:
            if skip_dir.startswith("*") and part.endswith(skip_dir[1:]):
                return True

    # Check extension — handle compound extensions like .min.js
    basename = parts[-1] if parts else path
    for skip_ext in SKIP_EXTENSIONS:
        if basename.endswith(skip_ext):
            return True

    return False


def _is_source_file(path):
    """Check if a file is a source/config file based on extension."""
    _, ext = os.path.splitext(path)
    return ext.lower() in SOURCE_EXTENSIONS


def _truncate_content(content, cap, half_chars):
    """Truncate content to cap characters, keeping first and last halves."""
    if len(content) <= cap:
        return content, False
    omitted = len(content) - (half_chars * 2)
    return (
        content[:half_chars]
        + f"\n\n... [{omitted} chars omitted] ...\n\n"
        + content[-half_chars:]
    ), True


def gather_repo_files(root="."):
    """Gather all non-binary, non-junk files tracked by git.

    Returns list of dicts: [{path, content, is_source, truncated}]
    Content is already truncated to the per-file cap.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True, text=True, timeout=30,
            cwd=root,
        )
        if result.returncode != 0:
            return []
        paths = result.stdout.strip().split("\n")
    except Exception:
        return []

    files = []
    for path in paths:
        if not path.strip():
            continue
        if _should_skip_path(path):
            continue

        full_path = os.path.join(root, path)
        try:
            with open(full_path, encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            # Binary file or unreadable — skip silently
            continue

        is_source = _is_source_file(path)
        if is_source:
            content, truncated = _truncate_content(
                content, SOURCE_FILE_CAP, TRUNC_HALF_CHARS
            )
        else:
            content, truncated = _truncate_content(
                content, OTHER_FILE_CAP, OTHER_TRUNC_HALF_CHARS
            )

        files.append({
            "path": path,
            "content": content,
            "is_source": is_source,
            "truncated": truncated,
        })

    return sorted(files, key=lambda f: f["path"])


# --- Token estimation ---

def estimate_tokens_for_files(files):
    """Estimate total tokens for a list of gathered files (chars / 4)."""
    return sum(len(f["content"]) for f in files) // 4


# --- Formatting ---

def format_codebase(files):
    """Format gathered files as a single text block for the distillation call.

    Uses XML-ish tags to delimit file boundaries unambiguously.
    """
    parts = ["<codebase>"]
    for f in files:
        trunc_attr = ' truncated="true"' if f["truncated"] else ""
        parts.append(f'<file path="{f["path"]}"{trunc_attr}>')
        parts.append(f["content"])
        parts.append("</file>")
    parts.append("</codebase>")
    return "\n".join(parts)


def _extract_python_signatures(content, include_line_numbers=False):
    """Extract function/class signatures and docstrings from Python source."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Fall back to first N lines if parsing fails
        lines = content.split("\n")
        return "\n".join(lines[:STRUCT_EXTRACT_HEAD_LINES])

    parts = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # Get the function signature from source lines
            sig = _format_function_sig(node, content)
            docstring = ast.get_docstring(node)
            if include_line_numbers:
                parts.append(f"{sig}  # line {node.lineno}")
            else:
                parts.append(sig)
            if docstring:
                parts.append(f'    """{docstring}"""')
            parts.append("    ...")
            parts.append("")
        elif isinstance(node, ast.ClassDef):
            if include_line_numbers:
                parts.append(f"class {node.name}:  # line {node.lineno}")
            else:
                parts.append(f"class {node.name}:")
            docstring = ast.get_docstring(node)
            if docstring:
                parts.append(f'    """{docstring}"""')
            # Include method signatures
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _format_function_sig(item, content)
                    if include_line_numbers:
                        parts.append(f"    {sig}  # line {item.lineno}")
                    else:
                        parts.append(f"    {sig}")
                    method_doc = ast.get_docstring(item)
                    if method_doc:
                        parts.append(f'        """{method_doc}"""')
                    parts.append("        ...")
            parts.append("")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # Include imports for context
            parts.append(ast.get_source_segment(content, node) or "")

    return "\n".join(parts) if parts else content.split("\n")[:STRUCT_EXTRACT_HEAD_LINES]


def _format_function_sig(node, source):
    """Format a function/async function node as its signature line."""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    # Try to get the source segment for just the signature
    try:
        args = ast.get_source_segment(source, node.args)
        if args:
            return f"{prefix} {node.name}({args}):"
    except Exception:
        pass
    # Fallback: reconstruct from AST
    arg_names = [a.arg for a in node.args.args]
    return f"{prefix} {node.name}({', '.join(arg_names)}):"


def format_structural_extract(files, include_line_numbers=False):
    """Format a compact structural representation for medium repos.

    Python files: AST-extracted function/class signatures + docstrings.
    Other files: first N lines only.
    """
    parts = ["<structural_extract>"]
    for f in files:
        parts.append(f'<file path="{f["path"]}">')
        if f["path"].endswith(".py"):
            extract = _extract_python_signatures(
                f["content"], include_line_numbers=include_line_numbers
            )
            if isinstance(extract, list):
                parts.append("\n".join(extract))
            else:
                parts.append(extract)
        else:
            lines = f["content"].split("\n")
            parts.append("\n".join(lines[:STRUCT_EXTRACT_HEAD_LINES]))
        parts.append("</file>")
    parts.append("</structural_extract>")
    return "\n".join(parts)


# --- Distillation LLM call ---

DISTILL_SYSTEM_PROMPT = """\
You are a code relevance filter. Given a codebase and a task description, \
extract ONLY what is directly relevant to implementing the task:
- Full content of files that will need to be modified
- Signatures and docstrings (not full bodies) of functions that provide context \
but won't be directly modified
- Schema definitions, data structures, or config formats the task touches
- Brief explanation of how each included item relates to the task

Your goal is to reduce the need for the downstream coding agent to explore and \
understand the whole codebase. The agent should be able to read your output and \
know exactly which files to modify, which functions to call, and what interfaces \
to respect — without needing to read anything else.

Be explicit about boundaries: "you need to read this file", "you need this \
function signature but don't need the full body", "don't bother reading X, \
it's not relevant to this task".

Omit everything unrelated to the task. Be concise — the output feeds directly \
into a coding agent's working context."""


def distill(codebase_text, task_context, model):
    """Make a single distillation LLM call.

    Returns (distilled_text, input_tokens, output_tokens, cost).
    Raises on LLM failure.
    """
    messages = [
        {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Task\n\n{task_context}\n\n"
                f"## Codebase\n\n{codebase_text}\n\n"
                "## Instructions\n\n"
                "Extract only what is relevant to the task above. Format as:\n\n"
                "### Relevant Files\n\n"
                "**`path/to/file.py`** — [one sentence: why this file matters]\n"
                "```python\n[full content or relevant excerpt]\n```\n\n"
                "### Key Interfaces\n\n"
                "[signatures and docstrings from other files that the task touches, "
                "without full bodies]\n\n"
                "### Exploration Boundaries\n\n"
                "[what the agent does NOT need to read or explore]\n\n"
                "### Summary\n\n"
                "[2-3 sentences: what exists, what needs to change]"
            ),
        },
    ]

    response = completion(
        model=model,
        messages=messages,
        max_tokens=DISTILL_OUTPUT_TOKENS,
    )

    text = ""
    if response.choices:
        msg = response.choices[0].message
        if hasattr(msg, "content") and msg.content:
            text = msg.content

    # Extract token usage
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = getattr(response, "_hidden_params", {}).get("response_cost", 0.0) or 0.0

    return text, input_tokens, output_tokens, cost


def _identify_relevant_files(extract_text, task_context, model):
    """Ask the model to identify relevant file paths from a structural extract.

    Returns (list_of_paths, input_tokens, output_tokens, cost).
    """
    messages = [
        {"role": "system", "content": (
            "You are a code relevance filter. Given a structural extract of a "
            "codebase (function signatures, class names, first lines of files) "
            "and a task description, identify which files are relevant to the task. "
            "Output ONLY a newline-separated list of file paths, nothing else."
        )},
        {
            "role": "user",
            "content": (
                f"## Task\n\n{task_context}\n\n"
                f"## Structural Extract\n\n{extract_text}\n\n"
                "List the file paths that are relevant to this task, one per line. "
                "Include files that need to be modified AND files that provide "
                "important context (interfaces, types, configs)."
            ),
        },
    ]

    response = completion(
        model=model,
        messages=messages,
        max_tokens=STRUCT_OUTPUT_TOKENS,
    )

    text = ""
    if response.choices:
        msg = response.choices[0].message
        if hasattr(msg, "content") and msg.content:
            text = msg.content

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = getattr(response, "_hidden_params", {}).get("response_cost", 0.0) or 0.0

    # Parse file paths from response (one per line, strip whitespace/backticks)
    paths = []
    for line in text.strip().split("\n"):
        line = line.strip().strip("`").strip("- ")
        if line and not line.startswith("#") and ("/" in line or "." in line):
            paths.append(line)

    return paths, input_tokens, output_tokens, cost


# --- Main entry point ---

def maybe_distill(repo_context, issue_context, model, root="."):
    """Run context distillation pre-step.

    Returns (context_text, input_tokens, output_tokens, cost, structural_extract).
    On failure or skip, returns (repo_context, 0, 0, 0.0, "").
    The structural_extract is a compact index of all functions/classes with line
    numbers, intended to be included in the agent's system prompt alongside the
    distilled context.
    """
    fallback = (repo_context, 0, 0, 0.0, "")

    try:
        files = gather_repo_files(root=root)
        if not files:
            print("  [Distill] No files gathered — skipping distillation")
            return fallback

        total_tokens = estimate_tokens_for_files(files)
        print(f"  [Distill] Gathered {len(files)} files, ~{total_tokens:,} tokens estimated")

        # Always build the agent-facing structural extract with line numbers.
        # This is cheap (no LLM call) and gives the agent a complete index of
        # every function/class so it can jump directly to definitions.
        agent_structural_extract = format_structural_extract(
            files, include_line_numbers=True
        )
        extract_tokens = len(agent_structural_extract) // 4
        print(f"  [Distill] Structural extract: ~{extract_tokens:,} tokens")

        total_input = 0
        total_output = 0
        total_cost = 0.0

        if total_tokens <= DISTILL_SMALL_REPO_LIMIT:
            # Tier 1: Small repo — send full codebase
            print("  [Distill] Tier 1 (small repo): sending full codebase")
            codebase_text = format_codebase(files)
            result, inp, out, cost = distill(codebase_text, issue_context, model)
            total_input += inp
            total_output += out
            total_cost += cost

        elif total_tokens <= DISTILL_STRUCT_EXTRACT_LIMIT:
            # Tier 2: Medium repo — structural extract + second pass
            print("  [Distill] Tier 2 (medium repo): structural extract + targeted read")
            # The distillation input uses the extract without line numbers
            # (line numbers aren't useful for the distillation LLM's task of
            # identifying relevant files).
            extract_text = format_structural_extract(files)

            # Pass 1: identify relevant files
            relevant_paths, inp, out, cost = _identify_relevant_files(
                extract_text, issue_context, model
            )
            total_input += inp
            total_output += out
            total_cost += cost
            print(f"  [Distill] Identified {len(relevant_paths)} relevant files")

            # Pass 2: gather only relevant files in full
            files_by_path = {f["path"]: f for f in files}
            relevant_files = []
            for path in relevant_paths:
                if path in files_by_path:
                    relevant_files.append(files_by_path[path])

            if not relevant_files:
                print("  [Distill] No relevant files matched — falling back")
                return fallback

            codebase_text = format_codebase(relevant_files)
            result, inp, out, cost = distill(codebase_text, issue_context, model)
            total_input += inp
            total_output += out
            total_cost += cost

        else:
            # Tier 3: Large repo — skip
            print(f"  [Distill] Repo too large (~{total_tokens:,} tokens) — skipping distillation")
            return fallback

        if not result or not result.strip():
            print("  [Distill] Empty distillation result — falling back")
            return fallback

        print(f"  [Distill] Distillation complete: ~{len(result) // 4:,} tokens output")
        return result, total_input, total_output, total_cost, agent_structural_extract

    except Exception as e:
        print(f"  [Distill] Distillation failed: {e} — proceeding with full repo context")
        return fallback


# --- Linked issue compression ---

LINKED_ISSUE_COMPRESS_SYSTEM_PROMPT = """\
You are a context compressor for a coding agent. You receive the full body and \
comment thread of a linked GitHub issue, along with the PR body and diff that \
references it.

Your job: extract ONLY what the coding agent needs to act on the PR. That means:
- The settled design decisions and approach agreed upon
- Relevant data structures, APIs, or file paths mentioned
- Specific requirements, constraints, or acceptance criteria
- Any implementation guidance or architectural notes

Omit:
- Debates and back-and-forth that led to the final decision (only keep the conclusion)
- Status updates, bot comments, and administrative noise
- Duplicate information already present in the PR body or diff
- Exploratory ideas that were rejected

Be concise. The output feeds directly into a coding agent's working context."""

LINKED_ISSUE_COMPRESS_OUTPUT_TOKENS = 4_096


def compress_linked_issue(issue_title, issue_body, issue_comments,
                          pr_body, pr_diff, model):
    """Compress a linked issue's context into a task-relevant summary.

    Makes a single non-agentic LLM call to distill the linked issue body
    and comments into the key decisions and requirements.

    Returns (compressed_text, input_tokens, output_tokens, cost).
    Raises on LLM failure.
    """
    messages = [
        {"role": "system", "content": LINKED_ISSUE_COMPRESS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Linked Issue: {issue_title}\n\n"
                f"### Issue Body\n\n{issue_body}\n\n"
                f"### Issue Discussion\n\n{issue_comments}\n\n"
                f"## PR Body\n\n{pr_body}\n\n"
                f"## PR Diff\n\n```diff\n{pr_diff}\n```\n\n"
                "## Instructions\n\n"
                "Summarize the linked issue context that is relevant to this PR. "
                "Focus on:\n"
                "1. **Settled decisions** — what approach was agreed on\n"
                "2. **Requirements** — what must the implementation do\n"
                "3. **Key details** — specific files, functions, data structures, "
                "or APIs mentioned\n"
                "4. **Constraints** — any limitations or things to avoid\n\n"
                "Output a concise summary (not the full thread). "
                "Skip anything already covered in the PR body or diff."
            ),
        },
    ]

    response = completion(
        model=model,
        messages=messages,
        max_tokens=LINKED_ISSUE_COMPRESS_OUTPUT_TOKENS,
    )

    text = ""
    if response.choices:
        msg = response.choices[0].message
        if hasattr(msg, "content") and msg.content:
            text = msg.content

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = getattr(response, "_hidden_params", {}).get("response_cost", 0.0) or 0.0

    return text, input_tokens, output_tokens, cost
