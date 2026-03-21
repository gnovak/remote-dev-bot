#!/usr/bin/env python3
"""
Generate a repo index (class fields and function signatures) for agent context.

Walks Python source files in the current directory, extracts dataclass fields
and function/method signatures via the AST, and writes a Markdown document to
stdout. No LLM required — output is always in sync with the code.

Usage:
    python generate_index.py [root_dir]  # defaults to current directory
"""

import ast
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "__pycache__", "venv", ".venv", "env", ".env",
    "node_modules", "dist", ".tox", ".mypy_cache", ".ruff_cache",
    "site-packages", ".remote-dev-bot",
}


def unparse(node):
    return ast.unparse(node) if node else ""


def format_args(args_node):
    """Format an arguments node into a parameter string."""
    parts = []
    all_args = args_node.posonlyargs + args_node.args
    # Build defaults map: last N defaults correspond to last N args
    defaults_map = {}
    for arg, default in zip(reversed(all_args), reversed(args_node.defaults)):
        defaults_map[arg.arg] = default

    for i, arg in enumerate(args_node.posonlyargs):
        s = arg.arg
        if arg.annotation:
            s += f": {unparse(arg.annotation)}"
        if arg.arg in defaults_map:
            s += f" = {unparse(defaults_map[arg.arg])}"
        parts.append(s)
    if args_node.posonlyargs:
        parts.append("/")

    for arg in args_node.args:
        s = arg.arg
        if arg.annotation:
            s += f": {unparse(arg.annotation)}"
        if arg.arg in defaults_map:
            s += f" = {unparse(defaults_map[arg.arg])}"
        parts.append(s)

    if args_node.vararg:
        parts.append(f"*{args_node.vararg.arg}")
    elif args_node.kwonlyargs:
        parts.append("*")

    kw_defaults = {
        a.arg: d
        for a, d in zip(args_node.kwonlyargs, args_node.kw_defaults)
        if d is not None
    }
    for arg in args_node.kwonlyargs:
        s = arg.arg
        if arg.annotation:
            s += f": {unparse(arg.annotation)}"
        if arg.arg in kw_defaults:
            s += f" = {unparse(kw_defaults[arg.arg])}"
        parts.append(s)

    if args_node.kwarg:
        parts.append(f"**{args_node.kwarg.arg}")

    return ", ".join(parts)


def is_dataclass(node):
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id == "dataclass":
            return True
        if isinstance(d, ast.Attribute) and d.attr == "dataclass":
            return True
    return False


def format_func_sig(node, indent=""):
    params = format_args(node.args)
    sig = f"{indent}def {node.name}({params})"
    if node.returns:
        sig += f" -> {unparse(node.returns)}"
    return sig


def process_file(path):
    """Return index lines for a single Python file, or [] if nothing useful."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    lines = []

    for node in ast.iter_child_nodes(tree):
        # Module-level functions (skip private/dunder)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                lines.append(format_func_sig(node))

        # Classes
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(unparse(b) for b in node.bases)
            class_line = f"class {node.name}" + (f"({bases})" if bases else "") + ":"
            if is_dataclass(node):
                lines.append("@dataclass")
            lines.append(class_line)

            if is_dataclass(node):
                # Show field definitions
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field = f"    {item.target.id}: {unparse(item.annotation)}"
                        if item.value:
                            field += f" = {unparse(item.value)}"
                        lines.append(field)
            else:
                # Show public method signatures
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("_") or item.name == "__init__":
                            lines.append(format_func_sig(item, indent="    "))

    return lines


def find_source_files(root):
    root = Path(root)
    files = []
    for path in sorted(root.rglob("*.py")):
        # Skip unwanted directories
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        # Skip test files
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        files.append(path)
    return files


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    files = find_source_files(root)

    python_files = [(f, process_file(f)) for f in files]
    python_files = [(f, lines) for f, lines in python_files if lines]

    if not python_files:
        return  # No output — nothing to add to context

    print("# Repo Index (auto-generated)")
    print()
    print("> Class fields and function signatures extracted from source.")
    print("> **Trust these definitions.** Read source files only if you need")
    print("> implementation details or are about to modify a specific function.")
    print()

    for path, lines in python_files:
        rel = path.relative_to(root)
        print(f"## `{rel}`")
        print()
        print("```python")
        print("\n".join(lines))
        print("```")
        print()


if __name__ == "__main__":
    main()
