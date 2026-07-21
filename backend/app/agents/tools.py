"""Standard tool definitions and handlers for agent use."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.policy.engine import (
    check_allowlisted_command,
    check_command,
    check_path,
    check_path_in_worktree,
)

# --- Tool specs (Anthropic input_schema format) ---

READ_ONLY_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the full contents of a file. Always read a file before editing it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the repo root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory. Returns file paths relative to repo root. Use pattern='**/*.py' to filter by type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path (default: repo root)",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern filter (e.g. '**/*.py', '**/*.ts')",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a string or regex pattern across the repository. Returns file:line:match results. Use this to find where something is defined or used.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex or literal string to search for",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Limit search to files matching this glob (e.g. '*.py', '*.ts')",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "search_symbols",
        "description": "Search for function, class, or interface definitions by name. Faster than search_code for finding where something is defined. Use this before referencing any function or class to confirm it exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Symbol name or partial name to search for (e.g. 'get_task', 'DevTask', 'fetchTasks')",
                },
                "kind": {
                    "type": "string",
                    "enum": ["function", "class", "all"],
                    "description": "Symbol type to search for (default: all)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_file_tree",
        "description": "Get a tree view of the project structure. Use this first to understand what exists before exploring individual files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Starting directory (default: repo root)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Max depth to show, 1-4 (default: 3)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_log",
        "description": "Show recent git commits with messages. Use this to understand recent changes, active areas, and what was recently modified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of commits to show (default: 10, max: 30)",
                },
                "file": {
                    "type": "string",
                    "description": "Optional: show only commits that touched this file",
                },
            },
            "required": [],
        },
    },
    # ---- Enhanced search & analysis tools (non-destructive) ----
    {
        "name": "read_files",
        "description": "Read multiple files at once. Returns each file's content labeled by path. Far more efficient than calling read_file repeatedly when you need to explore several files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths relative to repo root (max 20 files)",
                },
            },
            "required": ["paths"],
        },
    },
    {
        "name": "file_exists",
        "description": "Check whether a file or directory exists before reading or editing it. Returns true/false with type (file/directory/not_found).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File or directory path relative to repo root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_info",
        "description": "Get metadata about a file: size in bytes, line count, last modified time, and language detected from extension.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "find_references",
        "description": "Find every place in the codebase where a function, class, or variable is referenced/called. Shows file:line context. Use this before refactoring to understand impact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol name to find usages of (e.g. 'get_task', 'DevTask', 'fetchTasks')",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Limit to files matching this glob (e.g. '*.py', '*.ts')",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "find_todos",
        "description": "Find all TODO, FIXME, HACK, XXX, and NOTE comments across the codebase. Essential for understanding what is incomplete or known-broken.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to search (default: repo root)",
                },
                "kind": {
                    "type": "string",
                    "enum": ["all", "TODO", "FIXME", "HACK", "XXX"],
                    "description": "Marker type to find (default: all)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_imports",
        "description": "Find all import statements for a specific module, package, or symbol. Use this to understand how a library is used, or to find all callers of a module.",
        "input_schema": {
            "type": "object",
            "properties": {
                "module": {
                    "type": "string",
                    "description": "Module/package name to search (e.g. 'fastapi', 'asyncpg', 'useState')",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Limit to file type (e.g. '*.py', '*.ts')",
                },
            },
            "required": ["module"],
        },
    },
    {
        "name": "git_status",
        "description": "Show current git working tree state: staged, modified, untracked files. Always run before committing or diffing.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "git_show",
        "description": "Show the full details of a specific commit: message, author, date, and unified diff of changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Commit hash, tag, or relative ref like HEAD~2 (default: HEAD)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_blame",
        "description": "Show who last modified each line of a file and in which commit. Use to understand history and context of specific code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to blame (optional)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to blame (optional)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "analyze_file",
        "description": "Get a structural summary of a file: top-level imports, class names, function/method signatures. Fast way to understand what a file contains before reading it fully.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root (.py, .ts, .tsx supported)",
                },
            },
            "required": ["path"],
        },
    },
]

CODER_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "edit_file",
        "description": (
            "Make a targeted edit to a file by replacing an exact string. "
            "PREFER this over write_file for modifying existing files — it is safer because "
            "it only changes the specified region and fails if the text is not found. "
            "old_string must be unique in the file. Read the file first if unsure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the worktree root",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find and replace. Must appear exactly once in the file.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text. Can be empty string to delete old_string.",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write full content to a file (creates or completely overwrites). "
            "Use edit_file instead when modifying an existing file. "
            "Only use write_file for NEW files or when you need to fully replace a file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to worktree root",
                },
                "content": {
                    "type": "string",
                    "description": "Complete file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "git_diff",
        "description": "Show the current diff of changes in the worktree. Use this to review your own changes before submitting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Optional: show diff for a specific file only",
                },
            },
            "required": [],
        },
    },
    {
        "name": "bash",
        "description": "Run a shell command (allowlisted safe commands only). Use for running tests, typecheck, and lint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "submit_patch",
        "description": "Signal that implementation is complete. Call this ONLY after all tests pass.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files_changed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths that were created or modified",
                },
                "summary": {
                    "type": "string",
                    "description": "One-paragraph summary of what was implemented and verified",
                },
            },
            "required": ["files_changed", "summary"],
        },
    },
]

# QA Agent: read + bash (test/build only, no write)
_QA_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run test or build commands only. Allowed: pytest, mypy, ruff, tsc, npm test/build/lint. "
        "No write operations, no deploy commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Test/build command to run"},
        },
        "required": ["command"],
    },
}

_SUBMIT_QA_TOOL = {
    "name": "submit_qa_result",
    "description": "Submit the final QA result after all checks are complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["passed", "failed"]},
            "tests_run": {"type": "integer"},
            "tests_passed": {"type": "integer"},
            "tests_failed": {"type": "integer"},
            "typecheck_clean": {"type": "boolean"},
            "lint_clean": {"type": "boolean"},
            "errors": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": [
            "status",
            "tests_run",
            "tests_passed",
            "tests_failed",
            "typecheck_clean",
            "lint_clean",
            "errors",
            "summary",
        ],
    },
}

# QA has read tools + bash (test only) + submit_qa_result. NO write_file, NO edit.
QA_TOOLS = READ_ONLY_TOOLS + [_QA_BASH_TOOL, _SUBMIT_QA_TOOL]

_SUBMIT_REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the structured code review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["blocking", "non-blocking", "suggestion"],
                        },
                        "file": {"type": "string"},
                        "line": {"type": ["integer", "null"]},
                        "finding": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["severity", "file", "finding", "recommendation"],
                },
            },
            "verdict": {"type": "string", "enum": ["approved", "changes_required"]},
            "summary": {"type": "string"},
        },
        "required": ["findings", "verdict", "summary"],
    },
}

# Reviewer has read tools ONLY + submit_review. NO bash, NO write, NO edit.
REVIEWER_TOOLS = READ_ONLY_TOOLS + [_SUBMIT_REVIEW_TOOL]

_DEVOPS_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run read-only health-check commands only. Allowed prefixes come from config DEVOPS_BASH_ALLOWLIST. "
        "No write, no deploy, no remote push, no credential access."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Read-only health check command",
            },
        },
        "required": ["command"],
    },
}

_SUBMIT_HEALTH_REPORT_TOOL = {
    "name": "submit_health_report",
    "description": "Submit the structured system health report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "status": {"type": "string", "enum": ["ok", "warn", "fail"]},
                        "detail": {"type": "string"},
                    },
                    "required": ["name", "status", "detail"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["status", "checks", "summary"],
    },
}

# DevOps: read tools + allowlisted bash + submit_health_report. NO write_file.
DEVOPS_TOOLS = READ_ONLY_TOOLS + [_DEVOPS_BASH_TOOL, _SUBMIT_HEALTH_REPORT_TOOL]

# Allowed QA bash commands (prefix checks)
_QA_ALLOWED_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m mypy",
    "python -m ruff",
    "python3 -m pytest",
    "python3 -m mypy",
    "python3 -m ruff",
    "npx tsc",
    "npm test",
    "npm run",
    "cat ",
    "head ",
    "git diff",
    "git log",
    "git status",
)


# --- Tool handlers ---


def make_read_only_handlers(repo_path: str) -> dict[str, Any]:
    base = Path(repo_path)

    def read_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        p = base / rel
        if not p.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            return str(p.read_text(encoding="utf-8"))
        except Exception as e:
            return f"[ERROR] Cannot read {rel}: {e}"

    def list_files(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        pattern = str(inp.get("pattern", "**/*"))
        search_root = base / directory if directory else base
        if not search_root.exists():
            return f"[ERROR] Directory not found: {directory}"
        str_paths: list[str] = []
        for p in search_root.glob(pattern):
            if p.is_file():
                try:
                    str_paths.append(str(p.relative_to(base)))
                except ValueError:
                    pass  # skip symlinks or paths that escape the repo root
        return "\n".join(sorted(str_paths)[:200])

    def search_code(inp: dict[str, Any]) -> str:
        pattern = inp["pattern"]
        file_pattern = inp.get("file_pattern", "")
        cmd = ["grep", "-rn", "--include", file_pattern or "*", pattern, str(base)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            output = result.stdout[:8000] if result.stdout else "(no matches)"
            return output
        except subprocess.TimeoutExpired:
            return "[ERROR] Search timed out"

    def search_symbols(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        kind = inp.get("kind", "all")
        patterns: list[str] = []
        if kind in ("function", "all"):
            patterns += [
                f"def {name}",
                f"async def {name}",
                f"function {name}",
                f"const {name} =",
            ]
        if kind in ("class", "all"):
            patterns += [f"class {name}", f"interface {name}", f"type {name} ="]
        results: list[str] = []
        for pat in patterns:
            try:
                result = subprocess.run(
                    [
                        "grep",
                        "-rn",
                        "--include=*.py",
                        "--include=*.ts",
                        "--include=*.tsx",
                        pat,
                        str(base),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.stdout:
                    results.append(result.stdout[:2000])
            except subprocess.TimeoutExpired:
                pass
        combined = "\n".join(results)[:6000]
        return combined if combined.strip() else f"(no symbol '{name}' found)"

    def get_file_tree(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        max_depth = min(int(inp.get("max_depth", 3)), 4)
        start = base / directory if directory else base
        if not start.exists():
            return f"[ERROR] Directory not found: {directory}"
        _SKIP = {
            "__pycache__",
            "node_modules",
            ".next",
            ".venv",
            "venv",
            ".git",
            "dist",
            "build",
            ".mypy_cache",
        }
        lines: list[str] = [directory or "."]

        def _tree(path: Path, depth: int, prefix: str) -> None:
            if depth > max_depth:
                return
            try:
                items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return
            items = [
                i for i in items if i.name not in _SKIP and not i.name.startswith(".")
            ]
            for idx, item in enumerate(items):
                connector = "└── " if idx == len(items) - 1 else "├── "
                lines.append(f"{prefix}{connector}{item.name}")
                if item.is_dir() and depth < max_depth:
                    ext = "    " if idx == len(items) - 1 else "│   "
                    _tree(item, depth + 1, prefix + ext)

        _tree(start, 1, "")
        return "\n".join(lines[:300])

    def git_log(inp: dict[str, Any]) -> str:
        count = min(int(inp.get("count", 10)), 30)
        file_filter = str(inp.get("file", ""))
        cmd = ["git", "log", "--oneline", f"-{count}", "--no-merges"]
        if file_filter:
            cmd.extend(["--", file_filter])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(base), timeout=15
            )
            if result.returncode != 0:
                return f"[ERROR] git log failed: {result.stderr[:300]}"
            return result.stdout[:4000] if result.stdout else "(no commits found)"
        except subprocess.TimeoutExpired:
            return "[ERROR] git log timed out"

    def read_files(inp: dict[str, Any]) -> str:
        paths: list[str] = inp.get("paths", [])[:20]
        parts: list[str] = []
        for rel in paths:
            p = base / rel
            if not p.exists():
                parts.append(f"=== {rel} ===\n[ERROR] Not found")
            else:
                try:
                    content = p.read_text(encoding="utf-8")
                    parts.append(f"=== {rel} ===\n{content}")
                except Exception as e:
                    parts.append(f"=== {rel} ===\n[ERROR] {e}")
        return "\n\n".join(parts) if parts else "[ERROR] No paths provided"

    def file_exists(inp: dict[str, Any]) -> str:
        p = base / str(inp["path"])
        if p.is_file():
            return "file"
        if p.is_dir():
            return "directory"
        return "not_found"

    def file_info(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        p = base / rel
        if not p.exists():
            return f"[ERROR] Not found: {rel}"
        import datetime

        stat = p.stat()
        size = stat.st_size
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(
            timespec="seconds"
        )
        kind = "directory" if p.is_dir() else "file"
        lines = ""
        if p.is_file():
            try:
                lines = f"\nlines: {len(p.read_text(encoding='utf-8', errors='replace').splitlines())}"
            except Exception:
                pass
        ext = p.suffix or "(no extension)"
        return f"path: {rel}\ntype: {kind}\nsize: {size} bytes\nextension: {ext}{lines}\nmodified: {mtime}"

    def find_references(inp: dict[str, Any]) -> str:
        symbol = inp["symbol"]
        file_pattern = inp.get("file_pattern", "")
        cmd = ["grep", "-rn"]
        if file_pattern:
            cmd += ["--include", file_pattern]
        cmd += [r"\b" + symbol + r"\b", str(base)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            out = result.stdout[:6000]
            return out if out.strip() else f"(no references to '{symbol}' found)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Search timed out"

    def find_todos(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        kind = str(inp.get("kind", "all"))
        search_root = base / directory if directory else base
        markers = ["TODO", "FIXME", "HACK", "XXX"] if kind == "all" else [kind]
        pattern = "|".join(markers)
        try:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-E",
                    f"({pattern}):",
                    str(search_root),
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.tsx",
                    "--include=*.js",
                    "--include=*.md",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            out = result.stdout[:5000]
            return out if out.strip() else "(no TODOs found)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Search timed out"

    def search_imports(inp: dict[str, Any]) -> str:
        module = inp["module"]
        file_pattern = inp.get("file_pattern", "")
        patterns = [
            f"import {module}",
            f"from {module}",
            f'require("{module}")',
            f"require('{module}')",
        ]
        results: list[str] = []
        for pat in patterns:
            cmd = ["grep", "-rn"]
            if file_pattern:
                cmd += ["--include", file_pattern]
            cmd += [pat, str(base)]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if r.stdout.strip():
                    results.append(r.stdout[:2000])
            except subprocess.TimeoutExpired:
                pass
        combined = "\n".join(results)[:6000]
        return combined if combined.strip() else f"(no imports of '{module}' found)"

    def git_status(inp: dict[str, Any]) -> str:
        try:
            result = subprocess.run(
                ["git", "status", "--short", "--branch"],
                capture_output=True,
                text=True,
                cwd=str(base),
                timeout=10,
            )
            return result.stdout or "(clean)"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_show(inp: dict[str, Any]) -> str:
        ref = str(inp.get("ref", "HEAD"))
        try:
            result = subprocess.run(
                ["git", "show", "--stat", "--no-color", ref],
                capture_output=True,
                text=True,
                cwd=str(base),
                timeout=15,
            )
            return (result.stdout or result.stderr)[:5000]
        except Exception as e:
            return f"[ERROR] {e}"

    def git_blame(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        start = inp.get("start_line")
        end = inp.get("end_line")
        cmd = ["git", "blame", "--date=short", "-w"]
        if start and end:
            cmd += [f"-L{start},{end}"]
        cmd.append(rel)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(base), timeout=15
            )
            return (result.stdout or result.stderr)[:5000]
        except Exception as e:
            return f"[ERROR] {e}"

    def analyze_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        p = base / rel
        if not p.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[ERROR] {e}"

        lines = content.splitlines()
        total = len(lines)
        imports: list[str] = []
        definitions: list[str] = []

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Python / TS imports
            if stripped.startswith(("import ", "from ")):
                imports.append(f"  L{i}: {stripped}")
            # Python definitions
            elif stripped.startswith(("def ", "async def ", "class ")):
                definitions.append(f"  L{i}: {stripped.rstrip(':')}")
            # TypeScript/JS definitions
            elif any(
                stripped.startswith(p)
                for p in (
                    "export function ",
                    "export async function ",
                    "export class ",
                    "export const ",
                    "export default ",
                    "export interface ",
                    "export type ",
                    "function ",
                    "const ",
                    "class ",
                    "interface ",
                    "type ",
                )
            ) and ("=" in stripped or "(" in stripped or "{" in stripped):
                definitions.append(f"  L{i}: {stripped[:100]}")

        summary = [f"File: {rel}  ({total} lines)"]
        if imports:
            summary.append(f"\nImports ({len(imports)}):")
            summary.extend(imports[:30])
        if definitions:
            summary.append(f"\nDefinitions ({len(definitions)}):")
            summary.extend(definitions[:50])
        return "\n".join(summary)

    return {
        "read_file": read_file,
        "read_files": read_files,
        "list_files": list_files,
        "search_code": search_code,
        "search_symbols": search_symbols,
        "get_file_tree": get_file_tree,
        "git_log": git_log,
        "file_exists": file_exists,
        "file_info": file_info,
        "find_references": find_references,
        "find_todos": find_todos,
        "search_imports": search_imports,
        "git_status": git_status,
        "git_show": git_show,
        "git_blame": git_blame,
        "analyze_file": analyze_file,
    }


def make_coder_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    handlers = make_read_only_handlers(repo_path)
    wt = Path(worktree_path)
    patch_result: dict[str, Any] = {}

    def write_file(inp: dict[str, Any]) -> str:
        rel_path = inp["path"]
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        target = wt / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written: {rel_path}"

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=60,
            )
            out = (result.stdout + result.stderr)[:4000]
            return out if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out after 60s"

    def edit_file(inp: dict[str, Any]) -> str:
        rel_path = str(inp["path"])
        old_string = str(inp["old_string"])
        new_string = str(inp["new_string"])
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        target = wt / rel_path
        if not target.exists():
            return f"[ERROR] File not found: {rel_path}. Use write_file to create a new file."
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Cannot read {rel_path}: {e}"
        if old_string not in content:
            return f"[ERROR] old_string not found in {rel_path}. The exact text was not present."
        count = content.count(old_string)
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel_path}. Provide more context to make it unique."
        target.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Edited {rel_path}"

    def git_diff(inp: dict[str, Any]) -> str:
        file_filter = str(inp.get("file", ""))
        cmd = ["git", "diff", "--no-color"]
        if file_filter:
            cmd += ["--", file_filter]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=worktree_path, timeout=15
            )
            if result.returncode != 0:
                return f"[ERROR] git diff: {result.stderr[:300]}"
            return result.stdout[:8000] if result.stdout else "(no changes yet)"
        except subprocess.TimeoutExpired:
            return "[ERROR] git diff timed out"

    def submit_patch(inp: dict[str, Any]) -> str:
        patch_result["files_changed"] = inp.get("files_changed", [])
        patch_result["summary"] = inp.get("summary", "")
        return "Patch submitted"

    handlers["edit_file"] = edit_file
    handlers["git_diff"] = git_diff
    handlers["write_file"] = write_file
    handlers["bash"] = bash
    handlers["submit_patch"] = submit_patch
    handlers["_patch_result"] = patch_result  # caller reads this after run
    return handlers


def make_qa_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    """QA agent: read-only + bash (test/build only) + submit_qa_result. No writes."""
    handlers = make_read_only_handlers(repo_path)
    qa_result: dict[str, Any] = {}

    # Prepend venv bin dir so `python`, `pytest`, `mypy`, `ruff` resolve correctly.
    _venv_bin = str(Path(sys.executable).parent)
    _env_with_venv = os.environ.copy()
    _env_with_venv["PATH"] = _venv_bin + ":" + _env_with_venv.get("PATH", "")

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _QA_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=worktree_path,
                env=_env_with_venv,
                timeout=120,
            )
            out = (result.stdout + result.stderr)[:6000]
            return out if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out after 120s"

    def submit_qa_result(inp: dict[str, Any]) -> str:
        qa_result.update(inp)
        return "QA result submitted"

    handlers["bash"] = bash
    handlers["submit_qa_result"] = submit_qa_result
    handlers["_qa_result"] = qa_result  # caller reads this after run
    return handlers


def make_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Reviewer agent: read-only only + submit_review. No bash, no writes."""
    handlers = make_read_only_handlers(repo_path)
    review_result: dict[str, Any] = {}

    def submit_review(inp: dict[str, Any]) -> str:
        review_result.update(inp)
        return "Review submitted"

    handlers["submit_review"] = submit_review
    handlers["_review_result"] = review_result  # caller reads this after run
    return handlers


def make_devops_handlers(repo_path: str) -> dict[str, Any]:
    """DevOps agent: read-only + allowlisted bash (health checks only) + submit_health_report. No write."""
    from app.config import get_settings

    handlers = make_read_only_handlers(repo_path)
    health_result: dict[str, Any] = {}

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        devops_prefixes = get_settings().devops_bash_allowlist_tuple
        policy = check_allowlisted_command(cmd, devops_prefixes)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=30,
            )
            out = (result.stdout + result.stderr)[:4000]
            return out if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out after 30s"

    def submit_health_report(inp: dict[str, Any]) -> str:
        health_result.update(inp)
        return "Health report submitted"

    handlers["bash"] = bash
    handlers["submit_health_report"] = submit_health_report
    handlers["_health_result"] = health_result  # caller reads this after run
    return handlers


# ---- Phase 6 — Research Agent tools ----

_WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for technical information using DuckDuckGo. "
        "Returns titles, URLs, and snippets for up to 5 results. "
        "Use for finding library documentation, versions, and best practices."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
}

_SUBMIT_RESEARCH_TOOL = {
    "name": "submit_research",
    "description": "Submit the final research report with findings, library recommendations, approach, and risks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key findings from the research",
            },
            "relevantLibraries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "rationale"],
                },
            },
            "recommendedApproach": {"type": "string"},
            "risks": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["findings", "relevantLibraries", "recommendedApproach", "risks"],
    },
}

# Research agent: minimal read tools + submit_research only (no AST tools, no web_search placeholder).
# Kept small to stay within free-tier TPM limits — the agent can read files and search code.
RESEARCH_TOOLS = [
    READ_ONLY_TOOLS[0],
    READ_ONLY_TOOLS[1],
    READ_ONLY_TOOLS[2],
    _SUBMIT_RESEARCH_TOOL,
]


def web_search(inp: dict[str, Any]) -> str:
    """Search the web via DuckDuckGo — no API key needed. Standalone (not repo-scoped)
    so any agent can reuse it, not just the research agent."""
    query = str(inp.get("query", "")).strip()
    if not query:
        return "[ERROR] query is required"
    try:
        from duckduckgo_search import DDGS

        results = list(DDGS().text(query, max_results=5))
        if not results:
            return f"(no results found for: {query!r})"
        lines = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")[:300]
            lines.append(f"## {title}\n{href}\n{body}")
        return "\n\n".join(lines)[:6000]
    except Exception as exc:
        return f"[ERROR] web_search failed: {exc}"


def make_research_handlers(repo_path: str) -> dict[str, Any]:
    """Research agent: read-only + web_search placeholder + submit_research. No write, no bash."""
    handlers = make_read_only_handlers(repo_path)
    research_result: dict[str, Any] = {}

    def submit_research(inp: dict[str, Any]) -> str:
        research_result.update(inp)
        return "Research report submitted"

    handlers["web_search"] = web_search
    handlers["submit_research"] = submit_research
    handlers["_research_result"] = research_result  # caller reads this after run
    return handlers


# ---- Phase 6 — Docs Agent tools ----

_SUBMIT_DOCS_TOOL = {
    "name": "submit_docs",
    "description": "Submit the list of documentation files written or updated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files_written": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths of markdown files created or updated",
            },
            "summary": {
                "type": "string",
                "description": "Brief summary of documentation changes",
            },
        },
        "required": ["files_written", "summary"],
    },
}


def make_docs_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    """Docs agent: read-only + write_file (scoped to *.md and docs/**) + submit_docs."""
    from app.policy.engine import check_path_in_worktree

    handlers = make_read_only_handlers(repo_path)
    wt = Path(worktree_path)
    docs_result: dict[str, Any] = {}

    def write_file(inp: dict[str, Any]) -> str:
        rel_path = str(inp["path"])
        # Docs agent: only .md files or docs/** allowed
        is_md = rel_path.endswith(".md")
        is_docs = rel_path.startswith("docs/")
        if not (is_md or is_docs):
            return (
                f"[POLICY DENIED] Docs agent may only write .md files or paths under docs/. "
                f"Got: {rel_path!r}"
            )
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            target = wt / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(inp["content"], encoding="utf-8")
            return f"Written: {rel_path}"
        except Exception as e:
            return f"[ERROR] Cannot write {rel_path}: {e}"

    def submit_docs(inp: dict[str, Any]) -> str:
        docs_result.update(inp)
        return "Docs report submitted"

    handlers["write_file"] = write_file
    handlers["submit_docs"] = submit_docs
    handlers["_docs_result"] = docs_result
    return handlers


# Docs agent tool list: read tools + write_file + submit_docs. NO bash.
DOCS_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "write_file",
        "description": "Write content to a markdown file (*.md) or a path under docs/ only. No other file types.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the worktree root (must be *.md or docs/**)",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    _SUBMIT_DOCS_TOOL,
]

# ---------------------------------------------------------------------------
# CHAT AGENT TOOLS — full unrestricted access (dangerous cmds need confirmation)
# ---------------------------------------------------------------------------

_DELETE_FILE_TOOL = {
    "name": "delete_file",
    "description": (
        "Permanently delete a file from the repository. "
        "Cannot delete .env*, secrets/**, or .github/workflows/**. "
        "Always confirm with the user before deleting important files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "reason": {
                "type": "string",
                "description": "Why this file is being deleted",
            },
        },
        "required": ["path", "reason"],
    },
}

_GIT_PUSH_TOOL = {
    "name": "git_push",
    "description": (
        "Push commits to the remote repository. "
        "ALWAYS requires explicit user confirmation before executing. "
        "Specify the branch; defaults to current branch."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch to push (defaults to current branch)",
            },
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "force": {
                "type": "boolean",
                "description": "Force push (default: false — requires extra confirmation)",
            },
        },
        "required": [],
    },
}

_CREATE_BRANCH_TOOL = {
    "name": "create_branch",
    "description": "Create a new git branch and optionally switch to it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Branch name (e.g. 'feat/add-login')",
            },
            "checkout": {
                "type": "boolean",
                "description": "Switch to the new branch after creating it (default: true)",
            },
            "from_branch": {
                "type": "string",
                "description": "Base branch (default: current HEAD)",
            },
        },
        "required": ["name"],
    },
}

_CHAT_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run any shell command in the repository. "
        "Dangerous commands (rm -rf, git push, docker push, kubectl delete, etc.) "
        "will be paused for user confirmation before executing. "
        "Use this for running tests, installs, builds, or any investigation command."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "cwd": {
                "type": "string",
                "description": "Working directory override (default: repo root)",
            },
        },
        "required": ["command"],
    },
}

_SUBMIT_RESULT_TOOL = {
    "name": "submit_result",
    "description": "Signal that the task is fully complete. Include a summary of what was done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What was accomplished, files changed, commands run",
            },
            "status": {
                "type": "string",
                "enum": ["done", "blocked"],
                "description": "done = complete, blocked = hit a wall and need help",
            },
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths of files created or modified",
            },
        },
        "required": ["summary", "status"],
    },
}

_APPEND_FILE_TOOL = {
    "name": "append_file",
    "description": "Append content to the end of an existing file. Creates the file if it doesn't exist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "content": {"type": "string", "description": "Content to append"},
        },
        "required": ["path", "content"],
    },
}

_RENAME_FILE_TOOL = {
    "name": "rename_file",
    "description": "Rename or move a file within the repository. Cannot move outside the repo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_path": {
                "type": "string",
                "description": "Current file path relative to repo root",
            },
            "to_path": {
                "type": "string",
                "description": "New file path relative to repo root",
            },
        },
        "required": ["from_path", "to_path"],
    },
}

_COPY_FILE_TOOL = {
    "name": "copy_file",
    "description": "Copy a file to a new location within the repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_path": {
                "type": "string",
                "description": "Source file path relative to repo root",
            },
            "to_path": {
                "type": "string",
                "description": "Destination file path relative to repo root",
            },
        },
        "required": ["from_path", "to_path"],
    },
}

_GIT_COMMIT_TOOL = {
    "name": "git_commit",
    "description": "Stage specified files and create a git commit. Uses conventional commit format. Always run tests before committing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message (use conventional commits: feat/fix/docs/refactor: description)",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage and commit. Use ['--all'] to stage all changes.",
            },
        },
        "required": ["message", "files"],
    },
}

_GIT_BRANCH_TOOL = {
    "name": "git_branch",
    "description": "List all branches, or create a new branch. To switch branches use git_checkout.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete"],
                "description": "Action to perform (default: list)",
            },
            "name": {
                "type": "string",
                "description": "Branch name (required for create/delete)",
            },
        },
        "required": [],
    },
}

_GIT_CHECKOUT_TOOL = {
    "name": "git_checkout",
    "description": "Switch to a branch or restore a file to its last committed state.",
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Branch name or commit hash to checkout",
            },
            "file": {
                "type": "string",
                "description": "If provided, restore only this file (git checkout -- file)",
            },
        },
        "required": ["target"],
    },
}

_GIT_STASH_TOOL = {
    "name": "git_stash",
    "description": "Stash current changes or pop the most recent stash. Useful for temporarily saving work.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["push", "pop", "list", "drop"],
                "description": "Stash action (default: push)",
            },
            "message": {
                "type": "string",
                "description": "Optional label for the stash (push only)",
            },
        },
        "required": [],
    },
}

_GIT_PULL_TOOL = {
    "name": "git_pull",
    "description": "Pull latest changes from remote. Optionally specify remote and branch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "branch": {
                "type": "string",
                "description": "Branch to pull (default: current branch)",
            },
            "rebase": {
                "type": "boolean",
                "description": "Use --rebase instead of merge (default: false)",
            },
        },
        "required": [],
    },
}

_GIT_FETCH_TOOL = {
    "name": "git_fetch",
    "description": "Fetch latest refs from remote without merging. Safe read-only remote operation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "prune": {
                "type": "boolean",
                "description": "Remove stale remote-tracking refs (default: false)",
            },
        },
        "required": [],
    },
}

_GIT_RESTORE_TOOL = {
    "name": "git_restore",
    "description": "Discard changes in a file and restore it to the last committed version. This CANNOT be undone.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to restore (relative to repo root)",
            },
            "staged": {
                "type": "boolean",
                "description": "Unstage staged changes instead of discarding working tree changes (default: false)",
            },
        },
        "required": ["path"],
    },
}

_RUN_TESTS_TOOL = {
    "name": "run_tests",
    "description": "Run the test suite. Supports pytest (Python) and npm test (Node). Returns test output including failures.",
    "input_schema": {
        "type": "object",
        "properties": {
            "runner": {
                "type": "string",
                "enum": ["pytest", "npm_test", "tsc"],
                "description": "Test runner to use (default: pytest)",
            },
            "path": {
                "type": "string",
                "description": "Specific test file or directory to run (optional)",
            },
            "flags": {
                "type": "string",
                "description": "Extra flags to pass to the test runner (e.g. '-v -x -k test_name')",
            },
        },
        "required": [],
    },
}

_RUN_LINTER_TOOL = {
    "name": "run_linter",
    "description": "Run linting and type-checking tools. Returns errors and warnings. Fix these before declaring a task complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool": {
                "type": "string",
                "enum": ["ruff", "mypy", "tsc", "eslint", "black", "all"],
                "description": "Linter to run (default: all — runs ruff + mypy for Python, tsc for TypeScript)",
            },
            "path": {
                "type": "string",
                "description": "Path to lint (default: backend/ or apps/web/)",
            },
            "fix": {
                "type": "boolean",
                "description": "Auto-fix issues where possible (ruff only, default: false)",
            },
        },
        "required": [],
    },
}

# _BACKGROUND_PROCESSES used to be a module-level dict (shared across all sessions).
# It is now a per-session dict created inside make_chat_handlers() so that one session
# cannot kill or read output from another session's background process.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 1: File / Editing extras
# ---------------------------------------------------------------------------

_FIND_FILE_TOOL = {
    "name": "find_file",
    "description": "Find files by name or glob pattern across the repository. Faster than list_files when you know the filename.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Filename or pattern to find (e.g. 'config.py', '*.json', 'test_*.py')",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search (default: repo root)",
            },
        },
        "required": ["name"],
    },
}

_FORMAT_FILE_TOOL = {
    "name": "format_file",
    "description": "Auto-format a source file using the appropriate formatter (black/ruff for Python, prettier for TS/JS).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "formatter": {
                "type": "string",
                "enum": ["auto", "black", "ruff", "prettier"],
                "description": "Formatter to use (default: auto — detects by extension)",
            },
        },
        "required": ["path"],
    },
}

_ORGANIZE_IMPORTS_TOOL = {
    "name": "organize_imports",
    "description": "Sort and organize import statements in a Python file using ruff (isort-compatible). Also removes unused imports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Python file path relative to repo root",
            },
        },
        "required": ["path"],
    },
}

_INSERT_AT_LINE_TOOL = {
    "name": "insert_at_line",
    "description": "Insert content at a specific line number in a file. Existing content shifts down.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "line": {
                "type": "integer",
                "description": "1-indexed line to insert before. Use 0 to prepend.",
            },
            "content": {"type": "string", "description": "Content to insert"},
        },
        "required": ["path", "line", "content"],
    },
}

_REPLACE_FUNCTION_TOOL = {
    "name": "replace_function",
    "description": "Replace an entire function/method definition in a Python file. Finds by name and replaces the full block.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Python file path relative to repo root",
            },
            "function_name": {
                "type": "string",
                "description": "Name of the function or method to replace",
            },
            "new_code": {
                "type": "string",
                "description": "Complete new function code (def line + body, properly indented)",
            },
        },
        "required": ["path", "function_name", "new_code"],
    },
}

_DELETE_LINES_TOOL = {
    "name": "delete_lines",
    "description": "Delete a range of lines from a file (1-indexed, inclusive). Prefer edit_file for targeted changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to delete (1-indexed, inclusive)",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to delete (1-indexed, inclusive)",
            },
        },
        "required": ["path", "start_line", "end_line"],
    },
}

_APPLY_PATCH_TOOL_DEF = {
    "name": "apply_patch",
    "description": "Apply a unified diff patch (git diff format) to files in the repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": "Unified diff string (output of git diff or diff -u)",
            },
            "strip": {
                "type": "integer",
                "description": "Strip N leading path components (like patch -pN, default: 1)",
            },
        },
        "required": ["patch"],
    },
}

_COMPARE_FILES_TOOL = {
    "name": "compare_files",
    "description": "Show a unified diff between two files. Useful for comparing versions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path_a": {
                "type": "string",
                "description": "First file path relative to repo root",
            },
            "path_b": {
                "type": "string",
                "description": "Second file path relative to repo root",
            },
            "context": {
                "type": "integer",
                "description": "Lines of context around changes (default: 3)",
            },
        },
        "required": ["path_a", "path_b"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 2: Terminal extras
# ---------------------------------------------------------------------------

_RUN_BACKGROUND_TOOL_DEF = {
    "name": "run_background",
    "description": "Start a shell command in the background. Returns immediately with a PID. Use kill_process to stop it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run in background",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (default: repo root)",
            },
        },
        "required": ["command"],
    },
}

_KILL_PROCESS_TOOL = {
    "name": "kill_process",
    "description": "Kill a background process by PID. Use after run_background.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID to kill"},
            "signal": {
                "type": "string",
                "enum": ["TERM", "KILL", "INT"],
                "description": "Signal to send (default: TERM)",
            },
        },
        "required": ["pid"],
    },
}

_RUN_PYTHON_SNIPPET_TOOL = {
    "name": "run_python_snippet",
    "description": "Run an inline Python code snippet and return stdout/stderr. Runs in the repo's virtualenv if available.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30)",
            },
        },
        "required": ["code"],
    },
}

_RUN_MAKE_TOOL = {
    "name": "run_make",
    "description": "Run a Makefile target. Lists available targets if no target specified.",
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Make target to run (e.g. 'test', 'build', 'lint'). Leave empty to list.",
            },
            "directory": {
                "type": "string",
                "description": "Directory containing Makefile (default: repo root)",
            },
        },
        "required": [],
    },
}

_FETCH_URL_TOOL = {
    "name": "fetch_url",
    "description": "Fetch content from a URL (HTTP GET). Useful for reading documentation or checking API endpoints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 15)",
            },
        },
        "required": ["url"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 3: Git extras
# ---------------------------------------------------------------------------

_GIT_MERGE_TOOL = {
    "name": "git_merge",
    "description": "Merge a branch into the current branch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch name to merge into current branch",
            },
            "no_ff": {
                "type": "boolean",
                "description": "Create a merge commit even for fast-forwards (default: false)",
            },
            "squash": {
                "type": "boolean",
                "description": "Squash all commits into one (default: false)",
            },
            "message": {
                "type": "string",
                "description": "Commit message for the merge (optional)",
            },
        },
        "required": ["branch"],
    },
}

_GIT_RESET_TOOL = {
    "name": "git_reset",
    "description": "Reset HEAD. --soft keeps staged, --mixed keeps working tree, --hard discards all (requires confirmation).",
    "input_schema": {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "Ref to reset to (e.g. 'HEAD~1', commit hash). Default: HEAD",
            },
            "mode": {
                "type": "string",
                "enum": ["soft", "mixed", "hard"],
                "description": "Reset mode (default: mixed)",
            },
        },
        "required": [],
    },
}

_GIT_WORKTREE_TOOL = {
    "name": "git_worktree",
    "description": "Manage git worktrees — isolated checkouts for parallel work.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove"],
                "description": "Action to perform (default: list)",
            },
            "path": {
                "type": "string",
                "description": "Path for the new worktree (required for add)",
            },
            "branch": {
                "type": "string",
                "description": "Branch for the new worktree (required for add)",
            },
        },
        "required": [],
    },
}

_CREATE_PR_TOOL = {
    "name": "create_pr",
    "description": "Create a GitHub Pull Request using the gh CLI. Requires gh to be authenticated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR title"},
            "body": {"type": "string", "description": "PR description/body"},
            "base": {
                "type": "string",
                "description": "Base branch to merge into (default: main)",
            },
            "draft": {
                "type": "boolean",
                "description": "Create as draft PR (default: false)",
            },
        },
        "required": ["title"],
    },
}

_GENERATE_COMMIT_MSG_TOOL = {
    "name": "generate_commit_msg",
    "description": "Show current staged diff summary to help you write a conventional commit message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "staged_only": {
                "type": "boolean",
                "description": "Use only staged changes (default: true)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 4: Testing extras
# ---------------------------------------------------------------------------

_RUN_SINGLE_TEST_TOOL = {
    "name": "run_single_test",
    "description": "Run a single test by name/keyword. Much faster than running the full suite.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Test name or keyword to match (-k flag for pytest)",
            },
            "file": {
                "type": "string",
                "description": "Specific test file to run (optional)",
            },
            "verbose": {
                "type": "boolean",
                "description": "Show verbose output (default: true)",
            },
        },
        "required": ["keyword"],
    },
}

_COVERAGE_REPORT_TOOL = {
    "name": "coverage_report",
    "description": "Run pytest with coverage and return a summary showing which lines are uncovered.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to run tests on (default: backend/tests/)",
            },
            "source": {
                "type": "string",
                "description": "Source directory to measure coverage for (default: backend/app/)",
            },
            "min_coverage": {
                "type": "integer",
                "description": "Fail if coverage is below this percentage (optional)",
            },
        },
        "required": [],
    },
}

_TYPE_CHECK_TOOL = {
    "name": "type_check",
    "description": "Run static type checking (mypy for Python, tsc for TypeScript). Returns type errors.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to check (default: backend/ for Python, apps/web/ for TS)",
            },
            "strict": {
                "type": "boolean",
                "description": "Use --strict mode for mypy (default: false)",
            },
            "language": {
                "type": "string",
                "enum": ["python", "typescript", "both"],
                "description": "Which language to check (default: both)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 5: Code Intelligence
# ---------------------------------------------------------------------------

_LIST_FUNCTIONS_TOOL = {
    "name": "list_functions",
    "description": "List all function and method definitions in a file with their line numbers and signatures.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root (.py, .ts, .tsx supported)",
            },
        },
        "required": ["path"],
    },
}

_LIST_CLASSES_TOOL = {
    "name": "list_classes",
    "description": "List all class definitions in a file with their methods and line numbers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root (.py, .ts, .tsx supported)",
            },
        },
        "required": ["path"],
    },
}

_FIND_FUNCTION_BODY_TOOL = {
    "name": "find_function_body",
    "description": "Extract the complete source code of a named function or method, including its body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "function_name": {
                "type": "string",
                "description": "Name of the function or method to extract",
            },
        },
        "required": ["path", "function_name"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 6: Debug tools
# ---------------------------------------------------------------------------

_READ_LOGS_TOOL = {
    "name": "read_logs",
    "description": "Read log files from common locations. Specify path for a log file or service name for journalctl.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Log file path, or service name (e.g. 'uvicorn', 'postgresql')",
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to return (default: 50)",
            },
            "level": {
                "type": "string",
                "enum": ["all", "ERROR", "WARNING", "INFO"],
                "description": "Filter by log level (default: all)",
            },
        },
        "required": [],
    },
}

_ANALYZE_ERROR_TOOL = {
    "name": "analyze_error",
    "description": "Parse and analyze a Python traceback or error message. Returns structured breakdown with suggestions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "error": {
                "type": "string",
                "description": "Error message or full traceback to analyze",
            },
        },
        "required": ["error"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 7: Database tools
# ---------------------------------------------------------------------------

_RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": "Execute a SQL query against the project's PostgreSQL database via psql.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQL query to execute"},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Query parameters (positional, replaces $1, $2, ...)",
            },
        },
        "required": ["query"],
    },
}

_INSPECT_SCHEMA_TOOL = {
    "name": "inspect_schema",
    "description": "Show the PostgreSQL database schema: tables, columns, types, and constraints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Specific table name to inspect (default: list all tables)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 8: Docker tools
# ---------------------------------------------------------------------------

_DOCKER_PS_TOOL = {
    "name": "docker_ps",
    "description": "List running Docker containers. Shows ID, image, status, and ports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "all": {
                "type": "boolean",
                "description": "Show all containers including stopped ones (default: false)",
            },
        },
        "required": [],
    },
}

_DOCKER_LOGS_TOOL = {
    "name": "docker_logs",
    "description": "Get recent logs from a Docker container by name or ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
            "lines": {
                "type": "integer",
                "description": "Number of recent log lines (default: 50)",
            },
        },
        "required": ["container"],
    },
}

_DOCKER_EXEC_TOOL = {
    "name": "docker_exec",
    "description": "Run a command inside a running Docker container.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
            "command": {
                "type": "string",
                "description": "Command to run inside the container",
            },
        },
        "required": ["container", "command"],
    },
}

_DOCKER_COMPOSE_TOOL = {
    "name": "docker_compose",
    "description": "Run docker compose commands (up, down, restart, build, ps, logs, pull).",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["up", "down", "restart", "build", "ps", "logs", "pull"],
                "description": "Action to perform",
            },
            "services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific services to target (default: all)",
            },
            "detach": {
                "type": "boolean",
                "description": "Run in background for 'up' (default: true)",
            },
        },
        "required": ["action"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 9: Security
# ---------------------------------------------------------------------------

_SECRETS_SCAN_TOOL = {
    "name": "secrets_scan",
    "description": "Scan the repository for hardcoded secrets, API keys, passwords, and tokens.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: entire repo)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# DAY 1 TOOL SPECS — Batches 10-16
# ---------------------------------------------------------------------------

# Batch 10 — AST Engine
_PARSE_AST_TOOL = {
    "name": "parse_ast",
    "description": (
        "Parse a Python (.py) file using the AST module and return a JSON structure "
        "with all functions (name, line, args, decorators), classes (name, line, bases, methods), "
        "and imports. Far more accurate than grep for code analysis."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root (must be .py)",
            },
        },
        "required": ["path"],
    },
}

_IMPORT_GRAPH_TOOL = {
    "name": "import_graph",
    "description": "Show every module imported by a Python file, and which symbols are imported from each.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the .py file (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}

_CALL_GRAPH_TOOL = {
    "name": "call_graph",
    "description": (
        "Show what functions each function calls inside a Python file. "
        "Optionally limit to a single function by name."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the .py file"},
            "function_name": {
                "type": "string",
                "description": "Name of function to inspect (empty = all functions)",
            },
        },
        "required": ["path"],
    },
}

_DEAD_CODE_DETECT_TOOL = {
    "name": "dead_code_detect",
    "description": (
        "Heuristically detect public Python functions defined in a directory that are never called "
        "anywhere in that directory. Results are indicative — external callers are not visible."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (relative to repo root, default: repo root)",
            },
        },
        "required": [],
    },
}

_CIRCULAR_DEP_DETECT_TOOL = {
    "name": "circular_dep_detect",
    "description": "Detect circular local import chains in a Python package directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: repo root)",
            },
        },
        "required": [],
    },
}

_RENAME_SYMBOL_TOOL = {
    "name": "rename_symbol",
    "description": (
        "Word-boundary rename a symbol (function, class, variable) across all matching files. "
        "Uses Python regex to avoid false positives. Shows each file changed and replacement count. "
        "Always read the file first to confirm the symbol before renaming."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "old_name": {
                "type": "string",
                "description": "Current symbol name (must be a valid identifier)",
            },
            "new_name": {
                "type": "string",
                "description": "New symbol name (must be a valid identifier)",
            },
            "directory": {
                "type": "string",
                "description": "Root directory to rename within (default: repo root)",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern for files (default: *.py)",
            },
        },
        "required": ["old_name", "new_name"],
    },
}

# Batch 11 — Git extras
_GIT_REBASE_TOOL = {
    "name": "git_rebase",
    "description": "Rebase current branch onto another branch or commit. Interactive rebase is not supported (no TTY).",
    "input_schema": {
        "type": "object",
        "properties": {
            "onto": {
                "type": "string",
                "description": "Branch or commit to rebase onto (e.g. 'main', 'HEAD~3')",
            },
        },
        "required": ["onto"],
    },
}

_GIT_CHERRY_PICK_TOOL = {
    "name": "git_cherry_pick",
    "description": "Apply a specific commit from another branch onto the current branch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "commit_hash": {
                "type": "string",
                "description": "SHA or ref of the commit to cherry-pick",
            },
            "no_commit": {
                "type": "boolean",
                "description": "Stage changes without committing (default: false)",
            },
        },
        "required": ["commit_hash"],
    },
}

# Batch 12 — Terminal extras
_READ_OUTPUT_TOOL = {
    "name": "read_output",
    "description": "Read the latest stdout/stderr from a background process started with run_background.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "description": "Process ID returned by run_background",
            },
            "lines": {
                "type": "integer",
                "description": "Max lines to return (default: 50)",
            },
        },
        "required": ["pid"],
    },
}

_RUN_NODE_TOOL = {
    "name": "run_node",
    "description": "Execute a Node.js code snippet and return its output. Node.js must be installed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "JavaScript code to execute via `node -e`",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30)",
            },
        },
        "required": ["code"],
    },
}

_RUN_SCRIPT_TOOL = {
    "name": "run_script",
    "description": "Execute a script file (.py, .sh, .js). Auto-detects interpreter from extension.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the script file (relative to repo root)",
            },
            "interpreter": {
                "type": "string",
                "description": "Interpreter to use: 'auto', 'python3', 'bash', 'node' (default: auto)",
            },
        },
        "required": ["path"],
    },
}

_DOCKER_BUILD_TOOL = {
    "name": "docker_build",
    "description": "Build a Docker image from a Dockerfile. Runs `docker build -t <tag> <context>`.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tag": {"type": "string", "description": "Image tag, e.g. 'myapp:latest'"},
            "context": {
                "type": "string",
                "description": "Build context directory (default: repo root)",
            },
            "dockerfile": {
                "type": "string",
                "description": "Path to Dockerfile (optional, uses Docker default)",
            },
        },
        "required": ["tag"],
    },
}

_DOCKER_RESTART_TOOL = {
    "name": "docker_restart",
    "description": "Restart a running Docker container by name or ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
        },
        "required": ["container"],
    },
}

# Batch 13 — Smart search
_FIND_ROUTE_TOOL = {
    "name": "find_route",
    "description": (
        "Find API route definitions (FastAPI @router.get/post/put/delete, Flask @app.route) in the codebase. "
        "Filter by HTTP method and/or path pattern."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "description": "HTTP method to filter: GET, POST, PUT, DELETE, PATCH (empty = all)",
            },
            "path_pattern": {
                "type": "string",
                "description": "URL path string to search for (e.g. '/users', '/api')",
            },
        },
        "required": [],
    },
}

_FIND_API_TOOL = {
    "name": "find_api",
    "description": "Find API endpoint function definitions by name or keyword in the codebase.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Function or endpoint name to search for (empty = all route handlers)",
            },
        },
        "required": [],
    },
}

_FIND_SQL_TOOL = {
    "name": "find_sql",
    "description": "Find SQL queries and database operations in the codebase (SELECT, INSERT, SQLAlchemy text(), etc).",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "SQL keyword to search for, e.g. 'SELECT', 'INSERT', 'UPDATE' (empty = all SQL)",
            },
        },
        "required": [],
    },
}

_FIND_TEST_TOOL = {
    "name": "find_test",
    "description": "Find test functions that test a specific function or feature by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "function_name": {
                "type": "string",
                "description": "Name of the function or feature to find tests for",
            },
        },
        "required": ["function_name"],
    },
}

_FIND_CONFIG_TOOL = {
    "name": "find_config",
    "description": "Search for a configuration key across all config files (.env.example, config.py, settings files, YAML).",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Config key to find (e.g. 'DATABASE_URL', 'API_KEY', 'debug')",
            },
        },
        "required": ["key"],
    },
}

# Batch 14 — Monitoring
_CPU_USAGE_TOOL = {
    "name": "cpu_usage",
    "description": "Get current CPU usage percentage from /proc/stat or the `top` command.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_MEMORY_USAGE_TOOL = {
    "name": "memory_usage",
    "description": "Get current RAM usage from /proc/meminfo or the `free` command.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_DISK_USAGE_TOOL = {
    "name": "disk_usage",
    "description": "Get disk usage (total, used, free) for a path using shutil.disk_usage (stdlib).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to check (default: repo root)",
            },
        },
        "required": [],
    },
}

_HEALTH_CHECK_TOOL = {
    "name": "health_check",
    "description": "Check if backend services are up: backend HTTP health endpoint and database connectivity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service to check: 'all', 'backend', 'db' (default: all)",
            },
        },
        "required": [],
    },
}

_TASK_PROGRESS_TOOL = {
    "name": "task_progress",
    "description": "Query recent task status from the dev_tasks database table. Optionally filter by task ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "Specific task ID (optional; default: last 10 tasks)",
            },
            "limit": {
                "type": "integer",
                "description": "Max tasks to return (default: 10)",
            },
        },
        "required": [],
    },
}

# Batch 15 — Editing extras
_REPLACE_CLASS_TOOL = {
    "name": "replace_class",
    "description": (
        "Replace an entire class block in a Python file by class name. "
        "Finds the class by its `class <name>` line and replaces everything up to the next "
        "top-level definition. Always read the file first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (relative to repo root)",
            },
            "class_name": {
                "type": "string",
                "description": "Name of the class to replace",
            },
            "new_code": {
                "type": "string",
                "description": "Complete new class code (including the class definition line)",
            },
        },
        "required": ["path", "class_name", "new_code"],
    },
}

_UNDO_CHANGES_TOOL = {
    "name": "undo_changes",
    "description": (
        "Restore a file to its last committed state using `git checkout -- <path>`. "
        "This DISCARDS all uncommitted changes to that file. Requires confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to restore (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}

_GENERATE_PATCH_TOOL = {
    "name": "generate_patch",
    "description": (
        "Generate a unified diff patch from two text contents using Python's difflib. "
        "Useful for previewing changes before applying them. Does NOT modify any files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content_a": {
                "type": "string",
                "description": "Original file content (the 'before' version)",
            },
            "content_b": {
                "type": "string",
                "description": "New file content (the 'after' version)",
            },
            "filename": {
                "type": "string",
                "description": "Filename shown in the patch header (default: 'file')",
            },
        },
        "required": ["content_a", "content_b"],
    },
}

# Batch 16 — DB extras
_EXPLAIN_QUERY_TOOL = {
    "name": "explain_query",
    "description": (
        "Run EXPLAIN ANALYZE on a SQL query against the configured DATABASE_URL. "
        "Shows query plan and execution times. Read-only (EXPLAIN does not modify data)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to analyse (no trailing semicolon needed)",
            },
        },
        "required": ["query"],
    },
}

_RUN_MIGRATION_TOOL = {
    "name": "run_migration",
    "description": (
        "Run Alembic database migrations. Defaults to `alembic upgrade head`. "
        "WARNING: This modifies the database schema. Requires user confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "description": "'upgrade' or 'downgrade' (default: upgrade)",
            },
            "revision": {
                "type": "string",
                "description": "Target revision (default: head for upgrade, -1 for downgrade)",
            },
        },
        "required": [],
    },
}

_SEED_DATABASE_TOOL = {
    "name": "seed_database",
    "description": (
        "Run a database seed script to populate initial/test data. "
        "Looks for backend/scripts/seed.py by default. Requires user confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Path to seed script (relative to repo root, default: backend/scripts/seed.py)",
            },
        },
        "required": [],
    },
}


# ===========================================================================
# Day 2 Agents — shared tool spec constants, tool lists, handler factories
# ===========================================================================

_EDIT_FILE_TOOL_SPEC = {
    "name": "edit_file",
    "description": (
        "Make a targeted edit to a file by replacing an exact string. "
        "old_string must appear exactly once in the file. "
        "Always read the file first with read_file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {
                "type": "string",
                "description": "Exact text to replace (must be unique in file)",
            },
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_string", "new_string"],
    },
}

_WRITE_FILE_TOOL_SPEC = {
    "name": "write_file",
    "description": "Write full content to a file (creates or overwrites). Prefer edit_file for modifications.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
}

_GIT_DIFF_TOOL_SPEC = {
    "name": "git_diff",
    "description": "Show current unstaged and staged diff. Optionally limit to one file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Limit to this file (optional)"},
        },
        "required": [],
    },
}

# --- Day 2 submit tool specs ---

_SUBMIT_BUG_FIX_TOOL = {
    "name": "submit_bug_fix",
    "description": "Submit the bug fix: root cause analysis and files modified.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {"type": "string"},
            "fix_summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "tests_passed": {"type": "boolean"},
        },
        "required": ["root_cause", "fix_summary", "files_changed"],
    },
}

_SUBMIT_SECURITY_REPORT_TOOL = {
    "name": "submit_security_report",
    "description": "Submit security review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low", "none"],
            },
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["severity", "findings", "recommendations"],
    },
}

_SUBMIT_ARCH_REVIEW_TOOL = {
    "name": "submit_arch_review",
    "description": "Submit architecture review result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["approved", "changes_needed", "rejected"],
            },
            "issues": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["verdict", "issues", "recommendations", "summary"],
    },
}

_SUBMIT_SQL_REPORT_TOOL = {
    "name": "submit_sql_report",
    "description": "Submit SQL agent output: query results or migration summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "result": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "result"],
    },
}

_SUBMIT_DOCKER_REPORT_TOOL = {
    "name": "submit_docker_report",
    "description": "Submit Docker agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "outcome": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "outcome"],
    },
}

_SUBMIT_CICD_REPORT_TOOL = {
    "name": "submit_cicd_report",
    "description": "Submit CI/CD agent analysis or workflow changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["analysis"],
    },
}

_SUBMIT_REFACTOR_REPORT_TOOL = {
    "name": "submit_refactor_report",
    "description": "Submit refactoring agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "breaking_changes": {"type": "boolean"},
        },
        "required": ["summary", "files_changed"],
    },
}

_SUBMIT_DEPENDENCY_REPORT_TOOL = {
    "name": "submit_dependency_report",
    "description": "Submit dependency upgrade analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "outdated": {"type": "array", "items": {"type": "string"}},
            "upgraded": {"type": "array", "items": {"type": "string"}},
            "issues": {"type": "array", "items": {"type": "string"}},
            "files_changed": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["outdated", "upgraded"],
    },
}

_SUBMIT_MONITORING_REPORT_TOOL = {
    "name": "submit_monitoring_report",
    "description": "Submit system monitoring report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy", "warning", "critical"]},
            "metrics": {"type": "object"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "metrics"],
    },
}

_CICD_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run shell command. CI/CD agent limited to: git log/diff/status/show, cat, grep, echo, ls.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_REFACTOR_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run shell command. Refactor agent limited to: python -m pytest, mypy, ruff, black, isort.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_DEPENDENCY_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run dependency commands: pip index versions, pip show/list, npm audit/outdated/list.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

# --- Day 2 Tool Lists ---

BUG_FIX_TOOLS = READ_ONLY_TOOLS + [
    _PARSE_AST_TOOL,
    _CALL_GRAPH_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    _ANALYZE_ERROR_TOOL,
    _READ_LOGS_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _SUBMIT_BUG_FIX_TOOL,
]

SECURITY_REVIEWER_TOOLS = READ_ONLY_TOOLS + [
    _SECRETS_SCAN_TOOL,
    _FIND_SQL_TOOL,
    _FIND_CONFIG_TOOL,
    _FIND_API_TOOL,
    _FIND_ROUTE_TOOL,
    _SUBMIT_SECURITY_REPORT_TOOL,
]

ARCH_REVIEWER_TOOLS = READ_ONLY_TOOLS + [
    _IMPORT_GRAPH_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _CALL_GRAPH_TOOL,
    _SUBMIT_ARCH_REVIEW_TOOL,
]

SQL_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _FIND_SQL_TOOL,
    _EXPLAIN_QUERY_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_SQL_REPORT_TOOL,
]

DOCKER_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _DOCKER_PS_TOOL,
    _DOCKER_LOGS_TOOL,
    _DOCKER_EXEC_TOOL,
    _DOCKER_COMPOSE_TOOL,
    _DOCKER_BUILD_TOOL,
    _DOCKER_RESTART_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCKER_REPORT_TOOL,
]

CICD_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _CICD_BASH_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_CICD_REPORT_TOOL,
]

REFACTOR_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    _PARSE_AST_TOOL,
    _CALL_GRAPH_TOOL,
    _IMPORT_GRAPH_TOOL,
    _RENAME_SYMBOL_TOOL,
    _REPLACE_FUNCTION_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _REFACTOR_BASH_TOOL_SPEC,
    _SUBMIT_REFACTOR_REPORT_TOOL,
]

README_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

API_DOCS_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _FIND_ROUTE_TOOL,
    _FIND_API_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

DEPENDENCY_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _DEPENDENCY_BASH_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _SUBMIT_DEPENDENCY_REPORT_TOOL,
]

MONITORING_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _CPU_USAGE_TOOL,
    _MEMORY_USAGE_TOOL,
    _DISK_USAGE_TOOL,
    _HEALTH_CHECK_TOOL,
    _TASK_PROGRESS_TOOL,
    _READ_LOGS_TOOL,
    _SUBMIT_MONITORING_REPORT_TOOL,
]


# --- Day 2 shared sub-factories (reduce duplication) ---


def _make_edit_file_handler(root: Path) -> Any:
    def edit_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, str(root)):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        old_s, new_s = inp["old_string"], inp["new_string"]
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited {rel}"

    return edit_file_h


def _make_write_file_handler(root: Path) -> Any:
    def write_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, str(root)):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    return write_file_h


def _make_git_diff_handler(repo_path: str) -> Any:
    def git_diff_h(inp: dict[str, Any]) -> str:
        r = subprocess.run(
            ["git", "diff", "--no-color"] + ([inp["file"]] if inp.get("file") else []),
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        return r.stdout[:8000] or "No changes."

    return git_diff_h


# --- Day 2 Handler Factories ---


def make_bug_fix_handlers(repo_path: str) -> dict[str, Any]:
    """Bug Fix agent: read-only + AST analysis + direct file writes + submit_bug_fix."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    bug_fix_result: dict[str, Any] = {}

    def bf_parse_ast(inp: dict[str, Any]) -> str:
        return _ast.parse_file_ast(str(root / inp["path"]))

    def bf_call_graph(inp: dict[str, Any]) -> str:
        return _ast.build_call_graph(
            str(root / inp["path"]), inp.get("function_name", "")
        )

    def bf_find_function_body(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        r = subprocess.run(
            ["grep", "-rn", f"def {name}", str(root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:4000] if r.stdout else f"(function '{name}' not found)"

    def bf_analyze_error(inp: dict[str, Any]) -> str:
        tb = str(inp.get("traceback", ""))
        lines = [
            ln
            for ln in tb.splitlines()
            if "File" in ln or "Error" in ln or "Exception" in ln
        ]
        return "\n".join(lines[:40]) or "(no error markers found)"

    def bf_read_logs(inp: dict[str, Any]) -> str:
        log_path = str(inp.get("path", "backend/logs/app.log"))
        n = int(inp.get("lines", 100))
        try:
            p = root / log_path
            if not p.exists():
                return f"[ERROR] Log not found: {log_path}"
            return "\n".join(
                p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def bf_submit(inp: dict[str, Any]) -> str:
        bug_fix_result.update(inp)
        return "Bug fix submitted"

    handlers["parse_ast"] = bf_parse_ast
    handlers["call_graph"] = bf_call_graph
    handlers["find_function_body"] = bf_find_function_body
    handlers["analyze_error"] = bf_analyze_error
    handlers["read_logs"] = bf_read_logs
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["git_diff"] = _make_git_diff_handler(repo_path)
    handlers["submit_bug_fix"] = bf_submit
    handlers["_bug_fix_result"] = bug_fix_result
    return handlers


def make_security_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Security reviewer: read-only + specialized search + submit_security_report. No writes."""
    import re as _re

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    security_result: dict[str, Any] = {}

    _SEC_PATTERNS = [
        r"(api_key|apikey|secret|password|token|passwd|private_key)\s*=\s*['\"][^'\"]{8,}['\"]",
        r"(AKIA|AGPA|AROA|AIPA|ANPA|ANVA|ASIA)[0-9A-Z]{16}",
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        r"ghp_[0-9A-Za-z]{36}",
        r"sk-[0-9A-Za-z]{48}",
    ]
    _SEC_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".next"}
    _SEC_SKIP_EXTS = {".pyc", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".zip"}

    def sec_secrets_scan(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        scan_root = root / directory if directory else root
        hits: list[str] = []
        for fp in scan_root.rglob("*"):
            if fp.is_dir() or any(p in _SEC_SKIP_DIRS for p in fp.parts):
                continue
            if fp.suffix in _SEC_SKIP_EXTS:
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for pat in _SEC_PATTERNS:
                for m in _re.finditer(pat, text, _re.IGNORECASE):
                    rel = str(fp.relative_to(root))
                    line_no = text[: m.start()].count("\n") + 1
                    hits.append(f"  {rel}:{line_no}  {m.group()[:80]}")
        if not hits:
            return "✅ No obvious secrets detected."
        return f"⚠️  {len(hits)} potential secret(s):\n" + "\n".join(hits[:50])

    def sec_find_sql(inp: dict[str, Any]) -> str:
        keyword = str(inp.get("keyword", ""))
        fp = str(inp.get("file_pattern", "*.py"))
        if keyword:
            r = subprocess.run(
                ["grep", "-rn", "-i", "-w", keyword, "--include", fp, str(root)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-i",
                    "-E",
                    "SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|DROP TABLE",
                    "--include",
                    fp,
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        return r.stdout[:6000] if r.stdout else "(no SQL found)"

    def sec_find_config(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file_pattern", "*.py"))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-i",
                "-E",
                r"(host|port|database|db_url|dsn|connection_string)\s*=",
                "--include",
                fp,
                str(root),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.stdout[:6000] if r.stdout else "(no config patterns found)"

    def sec_find_api(inp: dict[str, Any]) -> str:
        name = str(inp.get("name", ""))
        if name:
            r = subprocess.run(
                ["grep", "-rn", name, "--include=*.py", str(root)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-E",
                    r"@(app|router)\.(get|post|put|delete|patch)",
                    "--include=*.py",
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        return r.stdout[:6000] if r.stdout else "(no API handlers found)"

    def sec_find_route(inp: dict[str, Any]) -> str:
        path_pat = str(inp.get("path", ""))
        r = subprocess.run(
            ["grep", "-rn", path_pat or "/api/", "--include=*.py", str(root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no routes found)"

    def sec_submit(inp: dict[str, Any]) -> str:
        security_result.update(inp)
        return "Security report submitted"

    handlers["secrets_scan"] = sec_secrets_scan
    handlers["find_sql"] = sec_find_sql
    handlers["find_config"] = sec_find_config
    handlers["find_api"] = sec_find_api
    handlers["find_route"] = sec_find_route
    handlers["submit_security_report"] = sec_submit
    handlers["_security_result"] = security_result
    return handlers


def make_arch_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Architecture reviewer: read-only + AST analysis + submit_arch_review."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    arch_result: dict[str, Any] = {}

    def ar_import_graph(inp: dict[str, Any]) -> str:
        return _ast.build_import_graph(str(root / inp["path"]))

    def ar_circular_dep(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        return _ast.detect_circular_imports(
            str(root / directory) if directory else str(root)
        )

    def ar_dead_code(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        return _ast.detect_dead_code(str(root / directory) if directory else str(root))

    def ar_parse_ast(inp: dict[str, Any]) -> str:
        return _ast.parse_file_ast(str(root / inp["path"]))

    def ar_list_functions(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^(async )?def ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no functions)"

    def ar_list_classes(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^class ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no classes)"

    def ar_call_graph(inp: dict[str, Any]) -> str:
        return _ast.build_call_graph(
            str(root / inp["path"]), inp.get("function_name", "")
        )

    def ar_submit(inp: dict[str, Any]) -> str:
        arch_result.update(inp)
        return "Architecture review submitted"

    handlers["import_graph"] = ar_import_graph
    handlers["circular_dep_detect"] = ar_circular_dep
    handlers["dead_code_detect"] = ar_dead_code
    handlers["parse_ast"] = ar_parse_ast
    handlers["list_functions"] = ar_list_functions
    handlers["list_classes"] = ar_list_classes
    handlers["call_graph"] = ar_call_graph
    handlers["submit_arch_review"] = ar_submit
    handlers["_arch_result"] = arch_result
    return handlers


def make_sql_agent_handlers(repo_path: str) -> dict[str, Any]:
    """SQL agent: read-only + SQL execution + schema inspection + write migrations."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    sql_result: dict[str, Any] = {}

    def sq_run_sql(inp: dict[str, Any]) -> str:
        sq_query = str(inp["query"])
        sq_settings = get_settings()
        sq_db_url = getattr(sq_settings, "database_url", None)
        if not sq_db_url:
            return "[ERROR] DATABASE_URL not configured"
        try:
            r = subprocess.run(
                ["psql", str(sq_db_url), "-c", sq_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except FileNotFoundError:
            return "[ERROR] psql not found — install postgresql-client"
        except subprocess.TimeoutExpired:
            return "[ERROR] Query timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def sq_inspect_schema(inp: dict[str, Any]) -> str:
        is_table = str(inp.get("table", ""))
        is_settings = get_settings()
        is_db_url = getattr(is_settings, "database_url", None)
        if not is_db_url:
            return "[ERROR] DATABASE_URL not configured"
        if is_table:
            is_query = (
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                f"WHERE table_name = '{is_table}' ORDER BY ordinal_position"
            )
        else:
            is_query = (
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
        try:
            r = subprocess.run(
                ["psql", str(is_db_url), "-c", is_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr)[:5000] or "(empty)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def sq_find_sql(inp: dict[str, Any]) -> str:
        keyword = str(inp.get("keyword", ""))
        fp = str(inp.get("file_pattern", "*.py"))
        if keyword:
            r = subprocess.run(
                ["grep", "-rn", "-i", "-w", keyword, "--include", fp, str(root)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-i",
                    "-E",
                    "SELECT|INSERT|UPDATE|DELETE|CREATE TABLE",
                    "--include",
                    fp,
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        return r.stdout[:6000] if r.stdout else "(no SQL found)"

    def sq_explain_query(inp: dict[str, Any]) -> str:
        eq_query = str(inp.get("query", ""))
        eq_settings = get_settings()
        eq_db_url = getattr(eq_settings, "database_url", None)
        if not eq_db_url:
            return "[ERROR] DATABASE_URL not configured"
        try:
            r = subprocess.run(
                [
                    "psql",
                    str(eq_db_url),
                    "-c",
                    f"EXPLAIN ANALYZE {eq_query}",
                    "--no-password",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no plan)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def sq_submit(inp: dict[str, Any]) -> str:
        sql_result.update(inp)
        return "SQL report submitted"

    handlers["run_sql"] = sq_run_sql
    handlers["inspect_schema"] = sq_inspect_schema
    handlers["find_sql"] = sq_find_sql
    handlers["explain_query"] = sq_explain_query
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_sql_report"] = sq_submit
    handlers["_sql_result"] = sql_result
    return handlers


def make_docker_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Docker agent: read-only + docker CLI inspection + limited docker actions + write_file."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docker_result: dict[str, Any] = {}

    def dk_docker_ps(inp: dict[str, Any]) -> str:
        r = subprocess.run(
            [
                "docker",
                "ps",
                "--format",
                "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout or r.stderr or "(no containers)"

    def dk_docker_logs(inp: dict[str, Any]) -> str:
        dl_container = str(inp["container"])
        dl_n = int(inp.get("lines", 50))
        r = subprocess.run(
            ["docker", "logs", "--tail", str(dl_n), dl_container],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (r.stdout + r.stderr)[:6000] or "(no logs)"

    def dk_docker_exec(inp: dict[str, Any]) -> str:
        de_container = str(inp["container"])
        de_cmd = str(inp["command"])
        if any(
            d in de_cmd
            for d in ["rm ", "kill", "stop", "restart", "drop", "delete", "truncate"]
        ):
            return f"[POLICY DENIED] Docker exec not allowed: {de_cmd!r}"
        r = subprocess.run(
            ["docker", "exec", de_container] + de_cmd.split(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:4000] or "(no output)"

    def dk_docker_compose(inp: dict[str, Any]) -> str:
        dc_action = str(inp.get("action", "ps"))
        dc_allowed = {"ps", "logs", "config", "images"}
        if dc_action not in dc_allowed:
            return f"[POLICY DENIED] Only allowed: {sorted(dc_allowed)}. Got: {dc_action!r}"
        r = subprocess.run(
            ["docker", "compose", dc_action],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:6000] or "(no output)"

    def dk_docker_build(inp: dict[str, Any]) -> str:
        db_tag = str(inp.get("tag", "app:dev"))
        db_file = str(inp.get("dockerfile", "Dockerfile"))
        db_ctx = str(inp.get("context", "."))
        r = subprocess.run(
            ["docker", "build", "-t", db_tag, "-f", db_file, db_ctx],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        out = (r.stdout + r.stderr)[:8000]
        return f"Build {'succeeded' if r.returncode == 0 else 'FAILED'}:\n{out}"

    def dk_docker_restart(inp: dict[str, Any]) -> str:
        dr_container = str(inp["container"])
        r = subprocess.run(
            ["docker", "restart", dr_container],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr).strip() or f"Restarted {dr_container}"

    def dk_submit(inp: dict[str, Any]) -> str:
        docker_result.update(inp)
        return "Docker report submitted"

    handlers["docker_ps"] = dk_docker_ps
    handlers["docker_logs"] = dk_docker_logs
    handlers["docker_exec"] = dk_docker_exec
    handlers["docker_compose"] = dk_docker_compose
    handlers["docker_build"] = dk_docker_build
    handlers["docker_restart"] = dk_docker_restart
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_docker_report"] = dk_submit
    handlers["_docker_result"] = docker_result
    return handlers


def make_cicd_agent_handlers(repo_path: str) -> dict[str, Any]:
    """CI/CD agent: read-only + limited bash (git/grep only) + file writes + submit."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    cicd_result: dict[str, Any] = {}

    _CICD_ALLOWED = (
        "git log",
        "git diff",
        "git status",
        "git show",
        "cat ",
        "grep ",
        "echo ",
        "ls ",
    )

    def ci_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _CICD_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:4000] or "(no output)"

    def ci_submit(inp: dict[str, Any]) -> str:
        cicd_result.update(inp)
        return "CI/CD report submitted"

    handlers["bash"] = ci_bash
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_cicd_report"] = ci_submit
    handlers["_cicd_result"] = cicd_result
    return handlers


def make_refactor_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Refactor agent: read-only + AST + write + rename + limited bash (test/lint only)."""
    from app.repo_tools import ast_engine as _ast
    import re as _re

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    refactor_result: dict[str, Any] = {}

    _RF_ALLOWED = ("python -m pytest", "mypy", "ruff", "black", "isort")

    def rf_list_functions(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^(async )?def ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no functions)"

    def rf_list_classes(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^class ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no classes)"

    def rf_find_function_body(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        r = subprocess.run(
            ["grep", "-rn", f"def {name}", str(root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:4000] if r.stdout else f"(function '{name}' not found)"

    def rf_parse_ast(inp: dict[str, Any]) -> str:
        return _ast.parse_file_ast(str(root / inp["path"]))

    def rf_call_graph(inp: dict[str, Any]) -> str:
        return _ast.build_call_graph(
            str(root / inp["path"]), inp.get("function_name", "")
        )

    def rf_import_graph(inp: dict[str, Any]) -> str:
        return _ast.build_import_graph(str(root / inp["path"]))

    def rf_rename_symbol(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        return _ast.rename_symbol(
            inp["old_name"],
            inp["new_name"],
            str(root / directory) if directory else str(root),
            str(inp.get("file_pattern", "*.py")),
        )

    def rf_replace_function(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        name = str(inp["function_name"])
        new_body = str(inp["new_body"])
        text = target.read_text(encoding="utf-8")
        pat = _re.compile(
            r"(?m)^((?:async )?def "
            + _re.escape(name)
            + r"\b.*?)(?=\n(?:async )?def |\Z)",
            _re.DOTALL,
        )
        m = pat.search(text)
        if not m:
            return f"[ERROR] Function '{name}' not found in {rel}"
        target.write_text(
            text[: m.start()] + new_body + text[m.end() :], encoding="utf-8"
        )
        return f"Replaced function '{name}' in {rel}"

    def rf_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _RF_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=60,
        )
        return (r.stdout + r.stderr)[:6000] or "(no output)"

    def rf_submit(inp: dict[str, Any]) -> str:
        refactor_result.update(inp)
        return "Refactor report submitted"

    handlers["list_functions"] = rf_list_functions
    handlers["list_classes"] = rf_list_classes
    handlers["find_function_body"] = rf_find_function_body
    handlers["parse_ast"] = rf_parse_ast
    handlers["call_graph"] = rf_call_graph
    handlers["import_graph"] = rf_import_graph
    handlers["rename_symbol"] = rf_rename_symbol
    handlers["replace_function"] = rf_replace_function
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["git_diff"] = _make_git_diff_handler(repo_path)
    handlers["bash"] = rf_bash
    handlers["submit_refactor_report"] = rf_submit
    handlers["_refactor_result"] = refactor_result
    return handlers


def make_readme_agent_handlers(repo_path: str) -> dict[str, Any]:
    """README agent: read-only + AST + write_file (*.md only) + submit_docs."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    def rm_parse_ast(inp: dict[str, Any]) -> str:
        return _ast.parse_file_ast(str(root / inp["path"]))

    def rm_list_functions(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^(async )?def ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no functions)"

    def rm_list_classes(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^class ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no classes)"

    def rm_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] README agent may only write .md files. Got: {rel!r}"
            )
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    def rm_submit(inp: dict[str, Any]) -> str:
        docs_result.update(inp)
        return "Docs submitted"

    handlers["parse_ast"] = rm_parse_ast
    handlers["list_functions"] = rm_list_functions
    handlers["list_classes"] = rm_list_classes
    handlers["write_file"] = rm_write_file
    handlers["submit_docs"] = rm_submit
    handlers["_docs_result"] = docs_result
    return handlers


def make_api_docs_agent_handlers(repo_path: str) -> dict[str, Any]:
    """API Docs agent: read-only + route/API finders + AST + write_file (*.md) + submit_docs."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    def ad_find_route(inp: dict[str, Any]) -> str:
        path_pat = str(inp.get("path", ""))
        r = subprocess.run(
            ["grep", "-rn", path_pat or "/api/", "--include=*.py", str(root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no routes)"

    def ad_find_api(inp: dict[str, Any]) -> str:
        name = str(inp.get("name", ""))
        if name:
            r = subprocess.run(
                ["grep", "-rn", name, "--include=*.py", str(root)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-E",
                    r"@(app|router)\.(get|post|put|delete|patch)",
                    "--include=*.py",
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        return r.stdout[:6000] if r.stdout else "(no API handlers)"

    def ad_parse_ast(inp: dict[str, Any]) -> str:
        return _ast.parse_file_ast(str(root / inp["path"]))

    def ad_list_functions(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file", ""))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                "^(async )?def ",
                "--include=*.py",
                str(root / fp) if fp else str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:6000] if r.stdout else "(no functions)"

    def ad_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] API docs agent may only write .md files. Got: {rel!r}"
            )
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    def ad_submit(inp: dict[str, Any]) -> str:
        docs_result.update(inp)
        return "API docs submitted"

    handlers["find_route"] = ad_find_route
    handlers["find_api"] = ad_find_api
    handlers["parse_ast"] = ad_parse_ast
    handlers["list_functions"] = ad_list_functions
    handlers["write_file"] = ad_write_file
    handlers["submit_docs"] = ad_submit
    handlers["_docs_result"] = docs_result
    return handlers


def make_dependency_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Dependency agent: read-only + bash (pip/npm audit only) + edit requirements + submit."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    dep_result: dict[str, Any] = {}

    _DEP_ALLOWED = (
        "pip index versions",
        "pip show",
        "pip list",
        "npm audit",
        "npm outdated",
        "npm list",
        "safety check",
        "pip-audit",
    )
    _DEP_EDITABLE = {
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "pyproject.toml",
    }

    def dep_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _DEP_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=60,
        )
        return (r.stdout + r.stderr)[:6000] or "(no output)"

    def dep_edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if Path(rel).name not in _DEP_EDITABLE:
            return f"[POLICY DENIED] Dependency agent may only edit requirements/package files. Got: {rel!r}"
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        old_s, new_s = inp["old_string"], inp["new_string"]
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited {rel}"

    def dep_submit(inp: dict[str, Any]) -> str:
        dep_result.update(inp)
        return "Dependency report submitted"

    handlers["bash"] = dep_bash
    handlers["edit_file"] = dep_edit_file
    handlers["submit_dependency_report"] = dep_submit
    handlers["_dependency_result"] = dep_result
    return handlers


def make_monitoring_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Monitoring agent: read-only + system metrics + submit_monitoring_report. No writes."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    monitoring_result: dict[str, Any] = {}

    def mon_cpu_usage(inp: dict[str, Any]) -> str:
        r = subprocess.run(["top", "-bn1"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "%Cpu" in line or "Cpu(s)" in line:
                return line.strip()
        return r.stdout[:500] or "[ERROR] Could not read CPU"

    def mon_memory_usage(inp: dict[str, Any]) -> str:
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "[ERROR] Could not read memory"

    def mon_disk_usage(inp: dict[str, Any]) -> str:
        du_path = str(inp.get("path", "/"))
        r = subprocess.run(
            ["df", "-h", du_path], capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() or "[ERROR] Could not read disk"

    def mon_health_check(inp: dict[str, Any]) -> str:
        hc_url = str(inp.get("url", "http://localhost:8000/health"))
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code} %{time_total}s",
                hc_url,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.strip() or r.stderr.strip() or "[ERROR] curl failed"

    def mon_task_progress(inp: dict[str, Any]) -> str:
        tp_task_id = inp.get("task_id")
        tp_settings = get_settings()
        tp_db_url = getattr(tp_settings, "database_url", None)
        if not tp_db_url:
            return "[ERROR] DATABASE_URL not configured"
        if tp_task_id:
            query = f"SELECT id, title, status, updated_at FROM dev_tasks WHERE id={int(tp_task_id)}"
        else:
            query = "SELECT id, title, status, updated_at FROM dev_tasks ORDER BY updated_at DESC LIMIT 10"
        try:
            r = subprocess.run(
                ["psql", str(tp_db_url), "-c", query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr)[:4000] or "(no tasks)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def mon_read_logs(inp: dict[str, Any]) -> str:
        rl_path = str(inp.get("path", "backend/logs/app.log"))
        rl_n = int(inp.get("lines", 100))
        try:
            p = root / rl_path
            if not p.exists():
                return f"[ERROR] Log not found: {rl_path}"
            return "\n".join(
                p.read_text(encoding="utf-8", errors="replace").splitlines()[-rl_n:]
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def mon_submit(inp: dict[str, Any]) -> str:
        monitoring_result.update(inp)
        return "Monitoring report submitted"

    handlers["cpu_usage"] = mon_cpu_usage
    handlers["memory_usage"] = mon_memory_usage
    handlers["disk_usage"] = mon_disk_usage
    handlers["health_check"] = mon_health_check
    handlers["task_progress"] = mon_task_progress
    handlers["read_logs"] = mon_read_logs
    handlers["submit_monitoring_report"] = mon_submit
    handlers["_monitoring_result"] = monitoring_result
    return handlers


# ===========================================================================
# Day 3 — Browser, Memory, Planning, MCP tool specs + Agent tool lists + Factories
# ===========================================================================

# --- Day 3A: Browser tool specs ---

_BROWSER_OPEN_TOOL: dict[str, Any] = {
    "name": "browser_open",
    "description": "Open a URL in a headless browser. Returns page title, URL, and status.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to open"}},
        "required": ["url"],
    },
}

_BROWSER_NAVIGATE_TOOL: dict[str, Any] = {
    "name": "browser_navigate",
    "description": "Navigate the current browser page to a new URL.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}

_BROWSER_SCREENSHOT_TOOL: dict[str, Any] = {
    "name": "browser_screenshot",
    "description": "Take a screenshot of the current page. Saves to /tmp and returns the file path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional output path. Auto-generated if omitted.",
            }
        },
        "required": [],
    },
}

_BROWSER_READ_DOM_TOOL: dict[str, Any] = {
    "name": "browser_read_dom",
    "description": "Read the visible text content of the current page, or a specific selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector (optional). If omitted, reads entire body.",
            }
        },
        "required": [],
    },
}

_BROWSER_CLICK_TOOL: dict[str, Any] = {
    "name": "browser_click",
    "description": "Click an element by CSS selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of element to click",
            }
        },
        "required": ["selector"],
    },
}

_BROWSER_TYPE_TOOL: dict[str, Any] = {
    "name": "browser_type",
    "description": "Type text into an input field identified by a CSS selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["selector", "text"],
    },
}

_BROWSER_CLOSE_TOOL: dict[str, Any] = {
    "name": "browser_close",
    "description": "Close the browser session and release resources.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# --- Day 3B: Memory tool specs ---

_MEMORY_READ_TOOL: dict[str, Any] = {
    "name": "memory_read",
    "description": "Read a value from the per-repo memory store by key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key to read from memory"}
        },
        "required": ["key"],
    },
}

_MEMORY_WRITE_TOOL: dict[str, Any] = {
    "name": "memory_write",
    "description": "Write a value to the per-repo memory store under a key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key", "value"],
    },
}

_DECISION_LOG_APPEND_TOOL: dict[str, Any] = {
    "name": "decision_log_append",
    "description": "Append a design decision with rationale to the project decision log.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "description": "The decision made"},
            "reason": {"type": "string", "description": "Why this decision was made"},
            "alternatives": {
                "type": "string",
                "description": "What alternatives were considered (optional)",
            },
        },
        "required": ["decision", "reason"],
    },
}

_TASK_HISTORY_QUERY_TOOL: dict[str, Any] = {
    "name": "task_history_query",
    "description": "Query recent task history from the task_logs table.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max records to return (default 20)",
            },
            "status": {
                "type": "string",
                "description": "Filter by status: completed, failed, blocked (optional)",
            },
        },
        "required": [],
    },
}

_KNOWN_ISSUES_READ_TOOL: dict[str, Any] = {
    "name": "known_issues_read",
    "description": "Read the project's known issues file.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_KNOWN_ISSUES_WRITE_TOOL: dict[str, Any] = {
    "name": "known_issues_write",
    "description": "Append a new known issue to the project known issues file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "Description of the issue"},
            "severity": {
                "type": "string",
                "description": "critical / high / medium / low",
            },
        },
        "required": ["issue", "severity"],
    },
}

# --- Day 3C: Planning + docs tool specs ---

_ESTIMATE_COMPLEXITY_TOOL: dict[str, Any] = {
    "name": "estimate_complexity",
    "description": "Estimate task complexity as XS/S/M/L/XL based on heuristics (description token count, file scope).",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Task or feature description to estimate",
            },
            "context_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of files/dirs likely involved",
            },
        },
        "required": ["description"],
    },
}

_SUMMARIZE_FOLDER_TOOL: dict[str, Any] = {
    "name": "summarize_folder",
    "description": "Return a concise summary of every .py/.ts file in a folder (up to 20 files).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative folder path to summarize",
            },
            "extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File extensions to include (default: .py, .ts, .tsx)",
            },
        },
        "required": ["path"],
    },
}

_GENERATE_API_DOCS_TEXT_TOOL: dict[str, Any] = {
    "name": "generate_api_docs_text",
    "description": "Parse a FastAPI route file and return a structured markdown template of all endpoints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "route_path": {
                "type": "string",
                "description": "Relative path to the FastAPI router file",
            }
        },
        "required": ["route_path"],
    },
}

_MERMAID_FROM_SCHEMA_TOOL: dict[str, Any] = {
    "name": "mermaid_from_schema",
    "description": "Convert a database schema inspection into a Mermaid ER diagram string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Table name to focus on (optional — uses all tables if omitted)",
            }
        },
        "required": [],
    },
}

# --- Day 2 Gap: Smart search tools ---

_FIND_QUEUE_TOOL: dict[str, Any] = {
    "name": "find_queue",
    "description": "Search the codebase for Queue / task-queue patterns (asyncio.Queue, BullMQ, RQ, Celery). Returns file:line matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Repo root to search (optional, defaults to current repo)",
            }
        },
        "required": [],
    },
}

_FIND_WORKER_TOOL: dict[str, Any] = {
    "name": "find_worker",
    "description": "Search the codebase for Worker / consumer patterns (Worker class, @worker, celery worker, RQ worker). Returns file:line matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Repo root to search (optional)",
            }
        },
        "required": [],
    },
}

# --- Day 2 Gap: Advanced editing tools ---

_INSERT_BEFORE_TOOL: dict[str, Any] = {
    "name": "insert_before",
    "description": "Insert lines of text immediately BEFORE the first line matching a pattern in a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "pattern": {
                "type": "string",
                "description": "String or regex pattern to match",
            },
            "content": {
                "type": "string",
                "description": "Text to insert (can be multi-line)",
            },
        },
        "required": ["path", "pattern", "content"],
    },
}

_INSERT_AFTER_TOOL: dict[str, Any] = {
    "name": "insert_after",
    "description": "Insert lines of text immediately AFTER the first line matching a pattern in a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "pattern": {
                "type": "string",
                "description": "String or regex pattern to match",
            },
            "content": {
                "type": "string",
                "description": "Text to insert (can be multi-line)",
            },
        },
        "required": ["path", "pattern", "content"],
    },
}

_DELETE_BLOCK_TOOL: dict[str, Any] = {
    "name": "delete_block",
    "description": "Delete all lines between (inclusive) start_pattern and end_pattern in a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "start_pattern": {
                "type": "string",
                "description": "Pattern marking the start of the block to delete",
            },
            "end_pattern": {
                "type": "string",
                "description": "Pattern marking the end of the block to delete",
            },
        },
        "required": ["path", "start_pattern", "end_pattern"],
    },
}

# --- Day 2 Gap: Documentation generation tools ---

_GENERATE_CHANGELOG_TOOL: dict[str, Any] = {
    "name": "generate_changelog",
    "description": "Generate a CHANGELOG.md entry from git log between two refs (Keep-a-Changelog format). Returns the changelog text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_ref": {
                "type": "string",
                "description": "Starting git ref (tag or commit). Defaults to previous tag.",
            },
            "to_ref": {
                "type": "string",
                "description": "Ending git ref (default: HEAD)",
            },
            "repo_path": {"type": "string", "description": "Repo root (optional)"},
        },
        "required": [],
    },
}

_SUMMARIZE_REPO_TOOL: dict[str, Any] = {
    "name": "summarize_repo",
    "description": "Generate a high-level summary of the repository: file tree (top 3 levels), line counts, language breakdown, and README excerpt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repo root (optional)"}
        },
        "required": [],
    },
}

_GENERATE_RELEASE_NOTES_TOOL: dict[str, Any] = {
    "name": "generate_release_notes",
    "description": "Generate a formatted release notes document from git history between two version tags.",
    "input_schema": {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "description": "New version number (e.g. v1.2.0)",
            },
            "from_ref": {
                "type": "string",
                "description": "Previous version tag or commit",
            },
            "repo_path": {"type": "string", "description": "Repo root (optional)"},
        },
        "required": ["version"],
    },
}

# --- Day 2 Gap: File type tools ---

_READ_PDF_TOOL: dict[str, Any] = {
    "name": "read_pdf",
    "description": "Extract text content from a PDF file using pdfplumber. Returns plain text, one paragraph per page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file"},
            "max_pages": {
                "type": "integer",
                "description": "Maximum pages to extract (default: 20)",
            },
        },
        "required": ["path"],
    },
}

_READ_IMAGE_TOOL: dict[str, Any] = {
    "name": "read_image",
    "description": "Read an image file and return basic metadata (format, size, mode) plus a base64-encoded thumbnail for vision inspection.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the image file (PNG, JPG, GIF, BMP, WebP)",
            },
        },
        "required": ["path"],
    },
}

# --- Day 2 Gap: GitHub PR tool ---

_GITHUB_CREATE_PR_TOOL: dict[str, Any] = {
    "name": "github_create_pr",
    "description": "Create a GitHub pull request using the gh CLI. Requires gh to be authenticated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR title"},
            "body": {"type": "string", "description": "PR description / body"},
            "base": {
                "type": "string",
                "description": "Target base branch (default: main)",
            },
            "draft": {
                "type": "boolean",
                "description": "Create as draft PR (default: false)",
            },
        },
        "required": ["title", "body"],
    },
}

# --- Day 3G: MCP / External integration tool specs ---

_GITHUB_CREATE_ISSUE_TOOL: dict[str, Any] = {
    "name": "github_create_issue",
    "description": "Create a GitHub issue using the gh CLI. Requires gh to be authenticated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional label names",
            },
        },
        "required": ["title", "body"],
    },
}

_GITHUB_LIST_PRS_TOOL: dict[str, Any] = {
    "name": "github_list_prs",
    "description": "List GitHub pull requests using the gh CLI.",
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "description": "open / closed / merged (default: open)",
            }
        },
        "required": [],
    },
}

_GITHUB_COMMENT_TOOL: dict[str, Any] = {
    "name": "github_comment",
    "description": "Post a comment on a GitHub issue or pull request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "Issue or PR number"},
            "body": {"type": "string", "description": "Comment text"},
            "kind": {"type": "string", "description": "issue or pr (default: issue)"},
        },
        "required": ["number", "body"],
    },
}

_LINEAR_CREATE_ISSUE_TOOL: dict[str, Any] = {
    "name": "linear_create_issue",
    "description": "Create a Linear issue via the Linear API. Requires LINEAR_API_KEY env var.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "team_key": {"type": "string", "description": "Linear team key (e.g. ENG)"},
        },
        "required": ["title", "description", "team_key"],
    },
}

_SLACK_SEND_MESSAGE_TOOL: dict[str, Any] = {
    "name": "slack_send_message",
    "description": "Send a Slack message via webhook. Requires SLACK_WEBHOOK_URL env var.",
    "input_schema": {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel name (informational only — webhook targets one channel)",
            },
            "text": {"type": "string", "description": "Message text"},
        },
        "required": ["text"],
    },
}

# --- Day 3 Agent submit tool specs ---

_SUBMIT_PERF_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_perf_review",
    "description": "Submit performance review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "object"}},
            "severity": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_STYLE_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_style_review",
    "description": "Submit style/lint review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "violations": {"type": "array", "items": {"type": "object"}},
            "auto_fixable": {"type": "boolean"},
        },
        "required": ["summary"],
    },
}

_SUBMIT_SPRINT_PLAN_TOOL: dict[str, Any] = {
    "name": "submit_sprint_plan",
    "description": "Submit a sprint plan with stories and estimates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "stories": {"type": "array", "items": {"type": "object"}},
            "total_points": {"type": "integer"},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goal", "stories"],
    },
}

_SUBMIT_BA_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_ba_result",
    "description": "Submit business analysis: user stories, acceptance criteria, edge cases.",
    "input_schema": {
        "type": "object",
        "properties": {
            "user_stories": {"type": "array", "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "edge_cases": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["user_stories", "summary"],
    },
}

_SUBMIT_MIGRATION_TOOL: dict[str, Any] = {
    "name": "submit_migration",
    "description": "Submit the generated migration file path and validation results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "migration_file": {"type": "string"},
            "is_reversible": {"type": "boolean"},
            "summary": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_SCHEMA_TOOL: dict[str, Any] = {
    "name": "submit_schema",
    "description": "Submit a schema design or review result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tables": {"type": "array", "items": {"type": "object"}},
            "normalization_issues": {"type": "array", "items": {"type": "string"}},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_AI_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_ai_result",
    "description": "Submit AI/ML engineering task results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "files_created": {"type": "array", "items": {"type": "string"}},
            "eval_results": {"type": "object"},
            "next_steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_CLEANUP_TOOL: dict[str, Any] = {
    "name": "submit_cleanup",
    "description": "Submit cleanup results: dead code removed, files deleted, imports organized.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "dead_code_removed": {"type": "array", "items": {"type": "string"}},
            "files_deleted": {"type": "array", "items": {"type": "string"}},
            "imports_cleaned": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_TECH_DEBT_TOOL: dict[str, Any] = {
    "name": "submit_tech_debt",
    "description": "Submit technical debt analysis findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "debt_items": {"type": "array", "items": {"type": "object"}},
            "priority_fixes": {"type": "array", "items": {"type": "string"}},
            "effort_estimate": {"type": "string"},
        },
        "required": ["summary"],
    },
}

# --- Day 3 agent-specific bash specs (restricted allowlists) ---

_MIGRATION_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run migration-related commands: alembic upgrade/downgrade, alembic revision, git diff.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_AI_ENGINEER_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run AI/ML commands: python script execution, pip install packages, model evaluation scripts.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_CLEANUP_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run cleanup commands: find dead code, check imports, ruff/isort checks.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

# --- Day 3 Agent Tool Lists ---

PERFORMANCE_REVIEWER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _FIND_SQL_TOOL,
    _RUN_SQL_TOOL,
    _EXPLAIN_QUERY_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _SUBMIT_PERF_REVIEW_TOOL,
]

STYLE_REVIEWER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_LINTER_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _SUBMIT_STYLE_REVIEW_TOOL,
]

SPRINT_PLANNER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _ESTIMATE_COMPLEXITY_TOOL,
    _SUBMIT_SPRINT_PLAN_TOOL,
]

BUSINESS_ANALYST_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _SUBMIT_BA_RESULT_TOOL,
]

MIGRATION_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _MIGRATION_BASH_TOOL_SPEC,
    _SUBMIT_MIGRATION_TOOL,
]

SCHEMA_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_SCHEMA_TOOL,
]

AI_ENGINEER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_PYTHON_SNIPPET_TOOL,
    _AI_ENGINEER_BASH_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _FETCH_URL_TOOL,
    _SUBMIT_AI_RESULT_TOOL,
]

CLEANUP_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _DEAD_CODE_DETECT_TOOL,
    _ORGANIZE_IMPORTS_TOOL,
    _DELETE_FILE_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _CLEANUP_BASH_TOOL_SPEC,
    _SUBMIT_CLEANUP_TOOL,
]

TECH_DEBT_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _RUN_LINTER_TOOL,
    _COVERAGE_REPORT_TOOL,
    _SUBMIT_TECH_DEBT_TOOL,
]

# --- Day 3 Handler Factories ---


def make_performance_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Performance Reviewer agent."""
    import subprocess as _sp
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    perf_result: dict[str, Any] = {}

    def pr_find_sql(inp: dict[str, Any]) -> str:
        keyword = str(inp.get("keyword", "")).upper() or "SELECT"
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if keyword in line.upper():
                    results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
        return "\n".join(results[:50]) or f"(no matches for {keyword})"

    def pr_run_sql(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip()
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        # Block destructive ops
        low = sql.lower()
        if any(
            k in low for k in ("drop ", "delete ", "truncate ", "update ", "insert ")
        ):
            return "[POLICY DENIED] Performance reviewer is read-only — use SELECT / EXPLAIN only"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def pr_explain_query(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip().rstrip(";")
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        try:
            r = _sp.run(
                [
                    "psql",
                    db_url,
                    "-c",
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql};",
                    "--no-psqlrc",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def pr_list_functions(inp: dict[str, Any]) -> str:
        pr_path = str(inp.get("path", "."))
        pr_results: list[str] = []
        for fp in (root / pr_path).rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if line.strip().startswith("def ") or line.strip().startswith(
                        "async def "
                    ):
                        pr_results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(pr_results[:100]) or "(none found)"

    def pr_submit(inp: dict[str, Any]) -> str:
        perf_result.update(inp)
        return "Performance review submitted"

    handlers["find_sql"] = pr_find_sql
    handlers["run_sql"] = pr_run_sql
    handlers["explain_query"] = pr_explain_query
    handlers["list_functions"] = pr_list_functions
    handlers["submit_perf_review"] = pr_submit
    handlers["_perf_result"] = perf_result
    return handlers


def make_style_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Style Reviewer agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    style_result: dict[str, Any] = {}

    def sr_run_linter(inp: dict[str, Any]) -> str:
        sr_path = str(inp.get("path", "."))
        try:
            r = _sp.run(
                ["python", "-m", "ruff", "check", sr_path, "--output-format=text"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no linting issues)"
        except Exception as e:
            return f"[ERROR] {e}"

    def sr_list_functions(inp: dict[str, Any]) -> str:
        sr_path = str(inp.get("path", "."))
        results: list[str] = []
        for fp in (root / sr_path).rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if line.strip().startswith("def ") or line.strip().startswith(
                        "async def "
                    ):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:100]) or "(none found)"

    def sr_list_classes(inp: dict[str, Any]) -> str:
        sr_path = str(inp.get("path", "."))
        results: list[str] = []
        for fp in (root / sr_path).rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if line.strip().startswith("class "):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:100]) or "(none found)"

    def sr_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if "TODO" in line or "FIXME" in line or "HACK" in line:
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(no TODOs found)"

    def sr_submit(inp: dict[str, Any]) -> str:
        style_result.update(inp)
        return "Style review submitted"

    handlers["run_linter"] = sr_run_linter
    handlers["list_functions"] = sr_list_functions
    handlers["list_classes"] = sr_list_classes
    handlers["find_todos"] = sr_find_todos
    handlers["submit_style_review"] = sr_submit
    handlers["_style_result"] = style_result
    return handlers


def make_sprint_planner_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Sprint Planner agent."""
    handlers = make_read_only_handlers(repo_path)
    sprint_result: dict[str, Any] = {}

    def sp_estimate_complexity(inp: dict[str, Any]) -> str:
        description = str(inp.get("description", ""))
        context_paths = list(inp.get("context_paths", []))
        # Heuristic: word count of description + number of context files
        word_count = len(description.split())
        file_count = len(context_paths)
        score = word_count + file_count * 10
        if score < 30:
            size = "XS"
        elif score < 80:
            size = "S"
        elif score < 200:
            size = "M"
        elif score < 500:
            size = "L"
        else:
            size = "XL"
        return f"Estimated complexity: {size} (word_count={word_count}, context_files={file_count}, score={score})"

    def sp_submit(inp: dict[str, Any]) -> str:
        sprint_result.update(inp)
        return "Sprint plan submitted"

    handlers["estimate_complexity"] = sp_estimate_complexity
    handlers["submit_sprint_plan"] = sp_submit
    handlers["_sprint_result"] = sprint_result
    return handlers


def make_business_analyst_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Business Analyst agent."""
    handlers = make_read_only_handlers(repo_path)
    ba_result: dict[str, Any] = {}

    def ba_submit(inp: dict[str, Any]) -> str:
        ba_result.update(inp)
        return "Business analysis submitted"

    handlers["submit_ba_result"] = ba_submit
    handlers["_ba_result"] = ba_result
    return handlers


def make_migration_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Migration Agent."""
    import subprocess as _sp
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    migration_result: dict[str, Any] = {}

    _MIGRATION_BASH_ALLOWLIST = (
        "alembic upgrade",
        "alembic downgrade",
        "alembic revision",
        "alembic history",
        "alembic current",
        "alembic heads",
        "git diff",
        "git status",
        "git log",
    )

    def mg_run_sql(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip()
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        low = sql.lower()
        if any(k in low for k in ("drop table", "truncate", "delete from")):
            return "[POLICY DENIED] Destructive SQL blocked in migration agent"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_inspect_schema(inp: dict[str, Any]) -> str:
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        tbl = inp.get("table")
        sql = f"\\d+ {tbl}" if tbl else "\\dt+"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        # Migration agent may only write to migrations/ or backend/migrations/
        if not (
            rel.startswith("migrations/")
            or rel.startswith("backend/migrations/")
            or rel.endswith(".py")
        ):
            return (
                f"[POLICY DENIED] Migration agent may only write migration files: {rel}"
            )
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _MIGRATION_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            r = _sp.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_submit(inp: dict[str, Any]) -> str:
        migration_result.update(inp)
        return "Migration submitted"

    handlers["run_sql"] = mg_run_sql
    handlers["inspect_schema"] = mg_inspect_schema
    handlers["write_file"] = mg_write_file
    handlers["bash"] = mg_bash
    handlers["submit_migration"] = mg_submit
    handlers["_migration_result"] = migration_result
    return handlers


def make_schema_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Schema Agent."""
    import subprocess as _sp
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    schema_result: dict[str, Any] = {}

    def sa_run_sql(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip()
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        low = sql.lower()
        if any(k in low for k in ("drop ", "delete ", "truncate ")):
            return "[POLICY DENIED] Schema agent cannot run destructive SQL"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def sa_inspect_schema(inp: dict[str, Any]) -> str:
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        tbl = inp.get("table")
        sql = f"\\d+ {tbl}" if tbl else "\\dt+"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def sa_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def sa_submit(inp: dict[str, Any]) -> str:
        schema_result.update(inp)
        return "Schema design submitted"

    handlers["run_sql"] = sa_run_sql
    handlers["inspect_schema"] = sa_inspect_schema
    handlers["write_file"] = sa_write_file
    handlers["submit_schema"] = sa_submit
    handlers["_schema_result"] = schema_result
    return handlers


def make_ai_engineer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for AI/ML Engineer agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    ai_result: dict[str, Any] = {}

    _AI_BASH_ALLOWLIST = (
        "python ",
        "python3 ",
        "pip install ",
        "pip show ",
        "pip list",
        "pytest ",
        "python -m ",
        "python3 -m ",
        "echo ",
        "cat ",
        "ls ",
    )

    def ae_run_python_snippet(inp: dict[str, Any]) -> str:
        code = str(inp["code"])
        try:
            r = _sp.run(
                ["python", "-c", code],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def ae_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _AI_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            r = _sp.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=120,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def ae_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def ae_fetch_url(inp: dict[str, Any]) -> str:
        import urllib.request as _ur

        url = str(inp["url"])
        try:
            with _ur.urlopen(url, timeout=10) as resp:
                body = resp.read(8192).decode("utf-8", errors="replace")
            return str(body[:2000])
        except Exception as e:
            return f"[ERROR] {e}"

    def ae_submit(inp: dict[str, Any]) -> str:
        ai_result.update(inp)
        return "AI engineering result submitted"

    handlers["run_python_snippet"] = ae_run_python_snippet
    handlers["bash"] = ae_bash
    handlers["write_file"] = ae_write_file
    handlers["fetch_url"] = ae_fetch_url
    handlers["submit_ai_result"] = ae_submit
    handlers["_ai_result"] = ai_result
    return handlers


def make_cleanup_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Cleanup Agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    cleanup_result: dict[str, Any] = {}

    _CLEANUP_BASH_ALLOWLIST = (
        "python -m ruff",
        "python -m isort",
        "python -m black",
        "find ",
        "grep ",
        "ls ",
        "cat ",
        "echo ",
        "python -m mypy",
    )

    def cu_dead_code_detect(inp: dict[str, Any]) -> str:
        cu_dir = str(inp.get("directory", "."))
        try:
            from app.repo_tools import ast_engine as _ae

            return _ae.detect_dead_code(str(root / cu_dir))
        except Exception as e:
            return f"[ERROR] {e}"

    def cu_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if any(t in line for t in ("TODO", "FIXME", "HACK", "XXX")):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(none found)"

    def cu_organize_imports(inp: dict[str, Any]) -> str:
        cu_path = str(inp["path"])
        if _is_protected_path(cu_path, repo_path):
            return f"[POLICY DENIED] Protected path: {cu_path}"
        try:
            r = _sp.run(
                ["python", "-m", "isort", cu_path, "--diff"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no changes needed)"
        except Exception as e:
            return f"[ERROR] {e}"

    def cu_delete_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        fp = root / rel
        if not fp.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            fp.unlink()
            return f"Deleted: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def cu_edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        old_s = inp["old_string"]
        new_s = inp["new_string"]
        fp = root / rel
        if not fp.exists():
            return f"[ERROR] File not found: {rel}"
        text = fp.read_text(encoding="utf-8")
        count = text.count(old_s)
        if count == 0:
            return "[ERROR] old_string not found"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        fp.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited: {rel}"

    def cu_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _CLEANUP_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            r = _sp.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def cu_submit(inp: dict[str, Any]) -> str:
        cleanup_result.update(inp)
        return "Cleanup submitted"

    handlers["dead_code_detect"] = cu_dead_code_detect
    handlers["find_todos"] = cu_find_todos
    handlers["organize_imports"] = cu_organize_imports
    handlers["delete_file"] = cu_delete_file
    handlers["edit_file"] = cu_edit_file
    handlers["bash"] = cu_bash
    handlers["submit_cleanup"] = cu_submit
    handlers["_cleanup_result"] = cleanup_result
    return handlers


def make_tech_debt_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Technical Debt Agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    tech_debt_result: dict[str, Any] = {}

    def td_list_functions(inp: dict[str, Any]) -> str:
        td_path = str(inp.get("path", "."))
        results: list[str] = []
        for fp in (root / td_path).rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if line.strip().startswith("def ") or line.strip().startswith(
                        "async def "
                    ):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:100]) or "(none found)"

    def td_list_classes(inp: dict[str, Any]) -> str:
        td_path = str(inp.get("path", "."))
        results: list[str] = []
        for fp in (root / td_path).rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if line.strip().startswith("class "):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:100]) or "(none found)"

    def td_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if any(t in line for t in ("TODO", "FIXME", "HACK", "XXX")):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(none found)"

    def td_run_linter(inp: dict[str, Any]) -> str:
        td_path = str(inp.get("path", "."))
        try:
            r = _sp.run(
                ["python", "-m", "ruff", "check", td_path, "--output-format=text"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no linting issues)"
        except Exception as e:
            return f"[ERROR] {e}"

    def td_coverage_report(inp: dict[str, Any]) -> str:
        try:
            r = _sp.run(
                ["python", "-m", "pytest", "--co", "-q", "--no-header"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def td_submit(inp: dict[str, Any]) -> str:
        tech_debt_result.update(inp)
        return "Tech debt analysis submitted"

    handlers["list_functions"] = td_list_functions
    handlers["list_classes"] = td_list_classes
    handlers["find_todos"] = td_find_todos
    handlers["run_linter"] = td_run_linter
    handlers["coverage_report"] = td_coverage_report
    handlers["submit_tech_debt"] = td_submit
    handlers["_tech_debt_result"] = tech_debt_result
    return handlers


# ===========================================================================
# Batch 15 — 34 new tools reaching the 190-tool vision
# ===========================================================================

# -- Git extras --
_GIT_TAG_TOOL: dict[str, Any] = {
    "name": "git_tag",
    "description": "Create, list, or delete git tags. action: 'list' (default), 'create', 'delete'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete"],
                "description": "Tag operation",
            },
            "name": {
                "type": "string",
                "description": "Tag name (required for create/delete)",
            },
            "message": {
                "type": "string",
                "description": "Annotated tag message (optional, create only)",
            },
        },
        "required": [],
    },
}
_GIT_LOG_FILE_TOOL: dict[str, Any] = {
    "name": "git_log_file",
    "description": "Show git commit history for a specific file. Returns commits that touched that file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "limit": {
                "type": "integer",
                "description": "Max commits to return (default: 10)",
            },
        },
        "required": ["path"],
    },
}
_SEMVER_BUMP_TOOL: dict[str, Any] = {
    "name": "semver_bump",
    "description": "Bump the project version (patch/minor/major) in pyproject.toml, package.json, or VERSION file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "part": {
                "type": "string",
                "enum": ["patch", "minor", "major"],
                "description": "Which part to bump",
            },
            "file": {
                "type": "string",
                "description": "Version file path (auto-detected if omitted)",
            },
        },
        "required": ["part"],
    },
}
_GIT_STASH_LIST_TOOL: dict[str, Any] = {
    "name": "git_stash_list",
    "description": "List all git stashes with their index and description.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# -- Process / System --
_LIST_PROCESSES_TOOL: dict[str, Any] = {
    "name": "list_processes",
    "description": "List running processes, optionally filtered by name. Returns PID, CPU%, MEM%, command.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Filter by process name (optional)",
            }
        },
        "required": [],
    },
}
_LIST_OPEN_PORTS_TOOL: dict[str, Any] = {
    "name": "list_open_ports",
    "description": "List TCP ports currently listening on this machine.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
_WAIT_FOR_PORT_TOOL: dict[str, Any] = {
    "name": "wait_for_port",
    "description": "Wait until a TCP port is open (useful after starting a server). Returns when port accepts connections or times out.",
    "input_schema": {
        "type": "object",
        "properties": {
            "port": {"type": "integer", "description": "TCP port number"},
            "host": {"type": "string", "description": "Hostname (default: localhost)"},
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default: 30)",
            },
        },
        "required": ["port"],
    },
}
_CHECK_URL_STATUS_TOOL: dict[str, Any] = {
    "name": "check_url_status",
    "description": "Check the HTTP status code of a URL. Returns status code, redirect chain, and response time. Does NOT return body.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to check"}},
        "required": ["url"],
    },
}
_CPU_PROFILE_TOOL: dict[str, Any] = {
    "name": "cpu_profile",
    "description": "Profile a Python script or module with cProfile and return the top N slowest functions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Python command to profile, e.g. 'python -m myapp'",
            },
            "top": {
                "type": "integer",
                "description": "Number of top functions to return (default: 20)",
            },
        },
        "required": ["command"],
    },
}

# -- File ops --
_ZIP_FILES_TOOL: dict[str, Any] = {
    "name": "zip_files",
    "description": "Zip a file or directory into an archive.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "File or directory to zip (relative to repo root)",
            },
            "output": {
                "type": "string",
                "description": "Output .zip file path (default: source + .zip)",
            },
        },
        "required": ["source"],
    },
}
_UNZIP_FILES_TOOL: dict[str, Any] = {
    "name": "unzip_files",
    "description": "Extract a .zip archive to a directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "archive": {
                "type": "string",
                "description": ".zip file path (relative to repo root)",
            },
            "dest": {
                "type": "string",
                "description": "Destination directory (default: archive directory)",
            },
        },
        "required": ["archive"],
    },
}
_MOVE_FILE_TOOL: dict[str, Any] = {
    "name": "move_file",
    "description": "Move a file or directory to a new path (mv semantics, can move across directories).",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Source path (relative to repo root)",
            },
            "dest": {
                "type": "string",
                "description": "Destination path (relative to repo root)",
            },
        },
        "required": ["source", "dest"],
    },
}
_HASH_FILE_TOOL: dict[str, Any] = {
    "name": "hash_file",
    "description": "Compute the SHA-256 hash of a file. Useful for integrity checking.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"}
        },
        "required": ["path"],
    },
}
_COUNT_LINES_TOOL: dict[str, Any] = {
    "name": "count_lines",
    "description": "Count lines in a file or all files in a directory matching a pattern.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path (relative to repo root)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern for directory mode (e.g. '**/*.py')",
            },
        },
        "required": ["path"],
    },
}

# -- Environment --
_READ_ENV_VAR_TOOL: dict[str, Any] = {
    "name": "read_env_var",
    "description": "Read the value of a specific environment variable from the running process. Returns [NOT SET] if absent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Environment variable name"}
        },
        "required": ["name"],
    },
}
_LIST_ENV_VARS_TOOL: dict[str, Any] = {
    "name": "list_env_vars",
    "description": "List all environment variable NAMES (not values) currently set. Use read_env_var to read a specific value.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
_ENV_DIFF_TOOL: dict[str, Any] = {
    "name": "env_diff",
    "description": "Compare .env.example with .env (or a named env file) to find missing or extra variables.",
    "input_schema": {
        "type": "object",
        "properties": {
            "example": {
                "type": "string",
                "description": "Path to example env file (default: .env.example)",
            },
            "actual": {
                "type": "string",
                "description": "Path to actual env file (default: .env)",
            },
        },
        "required": [],
    },
}

# -- Data format tools --
_JSON_QUERY_TOOL: dict[str, Any] = {
    "name": "json_query",
    "description": "Run a jq expression on a JSON file and return the result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON file path (relative to repo root)",
            },
            "query": {
                "type": "string",
                "description": "jq expression, e.g. '.users[].name'",
            },
        },
        "required": ["path", "query"],
    },
}
_YAML_VALIDATE_TOOL: dict[str, Any] = {
    "name": "yaml_validate",
    "description": "Validate a YAML file for syntax errors. Returns 'valid' or the parse error with line number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "YAML file path (relative to repo root)",
            }
        },
        "required": ["path"],
    },
}
_JSON_VALIDATE_TOOL: dict[str, Any] = {
    "name": "json_validate",
    "description": "Validate a JSON file for syntax errors. Returns 'valid' or the parse error with position.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON file path (relative to repo root)",
            }
        },
        "required": ["path"],
    },
}
_CSV_PREVIEW_TOOL: dict[str, Any] = {
    "name": "csv_preview",
    "description": "Preview the first N rows of a CSV file, showing column names and sample data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "CSV file path (relative to repo root)",
            },
            "rows": {
                "type": "integer",
                "description": "Number of rows to preview (default: 5)",
            },
        },
        "required": ["path"],
    },
}

# -- Code / Docs tools --
_GENERATE_DIAGRAM_TOOL: dict[str, Any] = {
    "name": "generate_diagram",
    "description": "Generate a Mermaid diagram definition (flowchart, sequence, ER) from a text description. Returns the mermaid code block.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What to diagram — components, flow, or relationships",
            },
            "kind": {
                "type": "string",
                "enum": ["flowchart", "sequence", "erDiagram", "classDiagram"],
                "description": "Diagram type (default: flowchart)",
            },
        },
        "required": ["description"],
    },
}
_EXPORT_MARKDOWN_TOOL: dict[str, Any] = {
    "name": "export_markdown",
    "description": "Render a Markdown file to HTML and save it. Returns the output HTML file path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Markdown file path (relative to repo root)",
            },
            "output": {
                "type": "string",
                "description": "Output HTML file path (default: same name + .html)",
            },
        },
        "required": ["path"],
    },
}
_FIND_UNUSED_IMPORTS_TOOL: dict[str, Any] = {
    "name": "find_unused_imports",
    "description": "Find unused imports in Python files using ruff or autoflake. Returns file:line:symbol for each unused import.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to check (default: repo root)",
            },
        },
        "required": [],
    },
}
_DEPS_OUTDATED_TOOL: dict[str, Any] = {
    "name": "deps_outdated",
    "description": "Check for outdated pip or npm dependencies. Returns package name, current version, and latest version.",
    "input_schema": {
        "type": "object",
        "properties": {
            "manager": {
                "type": "string",
                "enum": ["pip", "npm", "auto"],
                "description": "Package manager (default: auto-detect)",
            },
            "directory": {
                "type": "string",
                "description": "Directory to check (default: repo root)",
            },
        },
        "required": [],
    },
}
_LOC_STATS_TOOL: dict[str, Any] = {
    "name": "loc_stats",
    "description": "Lines-of-code statistics for the repo broken down by file extension/language.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory to scan (default: repo root)",
            },
        },
        "required": [],
    },
}

# -- Package management --
_NPM_INSTALL_TOOL: dict[str, Any] = {
    "name": "npm_install",
    "description": "Run npm install in a directory. Use to install Node.js dependencies.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory containing package.json (default: repo root)",
            },
            "package": {
                "type": "string",
                "description": "Optional specific package to install (e.g. 'lodash@4')",
            },
        },
        "required": [],
    },
}
_NPM_RUN_TOOL: dict[str, Any] = {
    "name": "npm_run",
    "description": "Run an npm script defined in package.json (e.g. build, test, lint).",
    "input_schema": {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Script name from package.json scripts",
            },
            "directory": {
                "type": "string",
                "description": "Directory containing package.json (default: repo root)",
            },
        },
        "required": ["script"],
    },
}
_PIP_INSTALL_TOOL: dict[str, Any] = {
    "name": "pip_install",
    "description": "Install a Python package in the current environment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "Package name with optional version, e.g. 'requests==2.31.0'",
            },
        },
        "required": ["package"],
    },
}
_PIP_LIST_TOOL: dict[str, Any] = {
    "name": "pip_list",
    "description": "List installed Python packages and their versions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Filter packages by name prefix (optional)",
            },
        },
        "required": [],
    },
}

# -- Utilities --
_CREATE_DIRECTORY_TOOL: dict[str, Any] = {
    "name": "create_directory",
    "description": "Create a directory (and any missing parents). Equivalent to mkdir -p.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to create (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}
_HTTP_REQUEST_TOOL: dict[str, Any] = {
    "name": "http_request",
    "description": "Make an HTTP request (GET/POST/PUT/DELETE) with custom headers and body. Returns status code and response body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
            "url": {"type": "string", "description": "Request URL"},
            "headers": {
                "type": "object",
                "description": "Request headers (key-value pairs)",
            },
            "body": {
                "type": "string",
                "description": "Request body (JSON string for POST/PUT)",
            },
        },
        "required": ["method", "url"],
    },
}
_BASE64_ENCODE_TOOL: dict[str, Any] = {
    "name": "base64_encode",
    "description": "Base64-encode a string or a file's contents. Useful for embedding assets or sending binary data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text string to encode (mutually exclusive with path)",
            },
            "path": {
                "type": "string",
                "description": "File path to encode (relative to repo root)",
            },
            "decode": {
                "type": "boolean",
                "description": "If true, decode base64 instead of encoding (default: false)",
            },
        },
        "required": [],
    },
}
_TEMPLATE_RENDER_TOOL: dict[str, Any] = {
    "name": "template_render",
    "description": "Render a Jinja2 template string or file with provided variables. Returns the rendered output.",
    "input_schema": {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": "Template string (mutually exclusive with path)",
            },
            "path": {
                "type": "string",
                "description": "Template file path (relative to repo root)",
            },
            "vars": {
                "type": "object",
                "description": "Variables to inject into the template",
            },
        },
        "required": [],
    },
}

CHAT_TOOLS = READ_ONLY_TOOLS + [
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _CHAT_BASH_TOOL,
    _APPEND_FILE_TOOL,
    _RENAME_FILE_TOOL,
    _COPY_FILE_TOOL,
    _DELETE_FILE_TOOL,
    _GIT_COMMIT_TOOL,
    _GIT_BRANCH_TOOL,
    _GIT_CHECKOUT_TOOL,
    _GIT_STASH_TOOL,
    _GIT_PULL_TOOL,
    _GIT_FETCH_TOOL,
    _GIT_RESTORE_TOOL,
    _GIT_PUSH_TOOL,
    _CREATE_BRANCH_TOOL,
    _RUN_TESTS_TOOL,
    _RUN_LINTER_TOOL,
    _SUBMIT_RESULT_TOOL,
    # Batch 1 — File/Editing extras
    _FIND_FILE_TOOL,
    _FORMAT_FILE_TOOL,
    _ORGANIZE_IMPORTS_TOOL,
    _INSERT_AT_LINE_TOOL,
    _REPLACE_FUNCTION_TOOL,
    _DELETE_LINES_TOOL,
    _APPLY_PATCH_TOOL_DEF,
    _COMPARE_FILES_TOOL,
    # Batch 2 — Terminal extras
    _RUN_BACKGROUND_TOOL_DEF,
    _KILL_PROCESS_TOOL,
    _RUN_PYTHON_SNIPPET_TOOL,
    _RUN_MAKE_TOOL,
    _FETCH_URL_TOOL,
    # Batch 3 — Git extras
    _GIT_MERGE_TOOL,
    _GIT_RESET_TOOL,
    _GIT_WORKTREE_TOOL,
    _CREATE_PR_TOOL,
    _GENERATE_COMMIT_MSG_TOOL,
    # Batch 4 — Testing extras
    _RUN_SINGLE_TEST_TOOL,
    _COVERAGE_REPORT_TOOL,
    _TYPE_CHECK_TOOL,
    # Batch 5 — Code Intelligence
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    # Batch 6 — Debug
    _READ_LOGS_TOOL,
    _ANALYZE_ERROR_TOOL,
    # Batch 7 — Database
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    # Batch 8 — Docker
    _DOCKER_PS_TOOL,
    _DOCKER_LOGS_TOOL,
    _DOCKER_EXEC_TOOL,
    _DOCKER_COMPOSE_TOOL,
    # Batch 9 — Security
    _SECRETS_SCAN_TOOL,
    # Batch 10 — AST Engine
    _PARSE_AST_TOOL,
    _IMPORT_GRAPH_TOOL,
    _CALL_GRAPH_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _RENAME_SYMBOL_TOOL,
    # Batch 11 — Git extras
    _GIT_REBASE_TOOL,
    _GIT_CHERRY_PICK_TOOL,
    # Batch 12 — Terminal extras
    _READ_OUTPUT_TOOL,
    _RUN_NODE_TOOL,
    _RUN_SCRIPT_TOOL,
    _DOCKER_BUILD_TOOL,
    _DOCKER_RESTART_TOOL,
    # Batch 13 — Smart search
    _FIND_ROUTE_TOOL,
    _FIND_API_TOOL,
    _FIND_SQL_TOOL,
    _FIND_TEST_TOOL,
    _FIND_CONFIG_TOOL,
    # Batch 14 — Monitoring
    _CPU_USAGE_TOOL,
    _MEMORY_USAGE_TOOL,
    _DISK_USAGE_TOOL,
    _HEALTH_CHECK_TOOL,
    _TASK_PROGRESS_TOOL,
    # Batch 15 — Editing extras
    _REPLACE_CLASS_TOOL,
    _UNDO_CHANGES_TOOL,
    _GENERATE_PATCH_TOOL,
    # Batch 16 — DB extras
    _EXPLAIN_QUERY_TOOL,
    _RUN_MIGRATION_TOOL,
    _SEED_DATABASE_TOOL,
    # Day 3A — Browser tools
    _BROWSER_OPEN_TOOL,
    _BROWSER_NAVIGATE_TOOL,
    _BROWSER_SCREENSHOT_TOOL,
    _BROWSER_READ_DOM_TOOL,
    _BROWSER_CLICK_TOOL,
    _BROWSER_TYPE_TOOL,
    _BROWSER_CLOSE_TOOL,
    # Day 3B — Memory tools
    _MEMORY_READ_TOOL,
    _MEMORY_WRITE_TOOL,
    _DECISION_LOG_APPEND_TOOL,
    _TASK_HISTORY_QUERY_TOOL,
    _KNOWN_ISSUES_READ_TOOL,
    _KNOWN_ISSUES_WRITE_TOOL,
    # Day 3C — Planning + docs tools
    _ESTIMATE_COMPLEXITY_TOOL,
    _SUMMARIZE_FOLDER_TOOL,
    _GENERATE_API_DOCS_TEXT_TOOL,
    _MERMAID_FROM_SCHEMA_TOOL,
    # Day 3G — MCP / External integrations
    _GITHUB_CREATE_ISSUE_TOOL,
    _GITHUB_LIST_PRS_TOOL,
    _GITHUB_COMMENT_TOOL,
    _LINEAR_CREATE_ISSUE_TOOL,
    _SLACK_SEND_MESSAGE_TOOL,
    # Day 2 Gap — Smart search
    _FIND_QUEUE_TOOL,
    _FIND_WORKER_TOOL,
    # Day 2 Gap — Advanced editing
    _INSERT_BEFORE_TOOL,
    _INSERT_AFTER_TOOL,
    _DELETE_BLOCK_TOOL,
    # Day 2 Gap — Documentation generation
    _GENERATE_CHANGELOG_TOOL,
    _SUMMARIZE_REPO_TOOL,
    _GENERATE_RELEASE_NOTES_TOOL,
    # Day 2 Gap — File types
    _READ_PDF_TOOL,
    _READ_IMAGE_TOOL,
    # Day 2 Gap — GitHub PR
    _GITHUB_CREATE_PR_TOOL,
    # Batch 15 — 34 new tools reaching the 190-tool vision
    # Git extras
    _GIT_TAG_TOOL,
    _GIT_LOG_FILE_TOOL,
    _SEMVER_BUMP_TOOL,
    _GIT_STASH_LIST_TOOL,
    # Process / System
    _LIST_PROCESSES_TOOL,
    _LIST_OPEN_PORTS_TOOL,
    _WAIT_FOR_PORT_TOOL,
    _CHECK_URL_STATUS_TOOL,
    _CPU_PROFILE_TOOL,
    # File ops
    _ZIP_FILES_TOOL,
    _UNZIP_FILES_TOOL,
    _MOVE_FILE_TOOL,
    _HASH_FILE_TOOL,
    _COUNT_LINES_TOOL,
    # Environment
    _READ_ENV_VAR_TOOL,
    _LIST_ENV_VARS_TOOL,
    _ENV_DIFF_TOOL,
    # Data format
    _JSON_QUERY_TOOL,
    _YAML_VALIDATE_TOOL,
    _JSON_VALIDATE_TOOL,
    _CSV_PREVIEW_TOOL,
    # Code / Docs
    _GENERATE_DIAGRAM_TOOL,
    _EXPORT_MARKDOWN_TOOL,
    _FIND_UNUSED_IMPORTS_TOOL,
    _DEPS_OUTDATED_TOOL,
    _LOC_STATS_TOOL,
    # Package management
    _NPM_INSTALL_TOOL,
    _NPM_RUN_TOOL,
    _PIP_INSTALL_TOOL,
    _PIP_LIST_TOOL,
    # Utilities
    _CREATE_DIRECTORY_TOOL,
    _HTTP_REQUEST_TOOL,
    _BASE64_ENCODE_TOOL,
    _TEMPLATE_RENDER_TOOL,
]


def _is_dangerous_command(command: str) -> bool:
    """Delegates to the centralized policy engine denylist."""
    return not check_command(command, strict=False).allowed


def _is_protected_path(path: str, worktree_path: str = "") -> bool:
    """Denylist + optional worktree containment check.

    Pass worktree_path (= repo_path in most handlers) to also block path
    traversal escapes like ../../../../tmp/pwned.txt.  Without worktree_path
    only the deny-list (.env, secrets, *.pem, etc.) is enforced.
    """
    if worktree_path:
        return not check_path_in_worktree(path, worktree_path).allowed
    return not check_path(path).allowed


def task_history_query(inp: dict[str, Any]) -> str:
    """Query recent task history from task_logs. Standalone (not repo-scoped) so any
    agent can reuse it, not just chat."""
    db_url = getattr(get_settings(), "database_url", "")
    if not db_url:
        return "[ERROR] DATABASE_URL not set"
    limit = int(inp.get("limit", 20))
    status_filter = inp.get("status")
    sql = "SELECT id, status, created_at FROM task_logs"
    if status_filter:
        sql += f" WHERE status = '{status_filter}'"
    sql += f" ORDER BY created_at DESC LIMIT {limit};"
    try:
        r = subprocess.run(
            ["psql", db_url, "-c", sql, "--no-psqlrc"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (r.stdout + r.stderr).strip() or "(no output)"
    except Exception as e:
        return f"[ERROR] {e}"


def make_chat_handlers(repo_path: str, session: Any = None) -> dict[str, Any]:
    """
    Full-access handlers for the interactive chat agent.
    session: ChatSession instance — used to request user confirmation for dangerous ops.
    If session is None, dangerous commands are blocked rather than confirmed.
    """
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    # Per-session background process registry — isolated so one session cannot
    # kill or read output from a different session's background process.
    _session_bg_procs: dict[int, "subprocess.Popen[str]"] = {}

    # ---- edit_file ----
    def edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot edit protected path: {rel}"
        old_s = inp["old_string"]
        new_s = inp["new_string"]
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            text = target.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Cannot read {rel}: {e}"
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}. Check for whitespace differences."
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel} — must be unique. Add more context."
        try:
            target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
            return f"Edited {rel}"
        except Exception as e:
            return f"[ERROR] Cannot write {rel}: {e}"

    # ---- write_file ----
    def write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(inp["content"], encoding="utf-8")
            return f"Written {rel} ({len(inp['content'])} bytes)"
        except Exception as e:
            return f"[ERROR] Cannot write {rel}: {e}"

    # ---- git_diff ----
    def git_diff(inp: dict[str, Any]) -> str:
        args = ["git", "diff", "--no-color"]
        staged = subprocess.run(
            ["git", "diff", "--cached", "--no-color"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        unstaged = subprocess.run(
            args + ([inp["file"]] if inp.get("file") else []),
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        out = ""
        if staged.stdout.strip():
            out += "=== STAGED ===\n" + staged.stdout
        if unstaged.stdout.strip():
            out += "=== UNSTAGED ===\n" + unstaged.stdout
        return out or "No changes."

    # ---- bash (with confirmation for dangerous commands) ----
    def bash(inp: dict[str, Any]) -> str:
        import asyncio
        import uuid

        command = inp["command"]
        cwd = inp.get("cwd") or repo_path

        if _is_dangerous_command(command):
            if session is None:
                return (
                    f"[BLOCKED] This command is potentially destructive: {command!r}\n"
                    "No confirmation mechanism available. Refusing to run."
                )
            action_id = str(uuid.uuid4())

            # We need to run the coroutine from within a sync handler
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're inside an async context — schedule and block
                    future = asyncio.run_coroutine_threadsafe(
                        session.request_confirmation(
                            action_id=action_id,
                            description="Run dangerous command",
                            details=command,
                        ),
                        loop,
                    )
                    approved = future.result(timeout=300)  # 5 min timeout
                else:
                    approved = loop.run_until_complete(
                        session.request_confirmation(
                            action_id=action_id,
                            description="Run dangerous command",
                            details=command,
                        )
                    )
            except Exception as exc:
                return f"[ERROR] Confirmation failed: {exc}"

            if not approved:
                return f"[DENIED] User declined to run: {command!r}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + (
                ("\n[stderr]\n" + result.stderr) if result.stderr else ""
            )
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out after 120s"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- delete_file ----
    def delete_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot delete protected path: {rel}"
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        if not target.is_file():
            return f"[ERROR] {rel} is not a file (use bash 'rm -rf' for directories)"
        try:
            target.unlink()
            return f"Deleted {rel}"
        except Exception as e:
            return f"[ERROR] Cannot delete {rel}: {e}"

    # ---- git_push (always requires confirmation) ----
    def git_push(inp: dict[str, Any]) -> str:
        import asyncio
        import uuid

        branch = inp.get("branch", "")
        remote = inp.get("remote", "origin")
        force = inp.get("force", False)

        if session is None:
            return "[BLOCKED] git_push always requires user confirmation; no session available."

        action_id = str(uuid.uuid4())
        cmd_preview = f"git push {remote} {branch}{'  --force' if force else ''}"

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    session.request_confirmation(
                        action_id=action_id,
                        description="Push commits to remote repository",
                        details=cmd_preview,
                    ),
                    loop,
                )
                approved = future.result(timeout=300)
            else:
                approved = loop.run_until_complete(
                    session.request_confirmation(
                        action_id=action_id,
                        description="Push commits to remote repository",
                        details=cmd_preview,
                    )
                )
        except Exception as exc:
            return f"[ERROR] Confirmation failed: {exc}"

        if not approved:
            return "[DENIED] User declined git push."

        cmd_parts = ["git", "push", remote]
        if branch:
            cmd_parts.append(branch)
        if force:
            cmd_parts.append("--force")

        try:
            result = subprocess.run(
                cmd_parts, cwd=repo_path, capture_output=True, text=True, timeout=60
            )
            out = result.stdout + result.stderr
            return out.strip() or "Push complete."
        except Exception as e:
            return f"[ERROR] git push failed: {e}"

    # ---- create_branch ----
    def create_branch(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        checkout = inp.get("checkout", True)
        from_branch = inp.get("from_branch", "")

        # Create the branch
        create_cmd = ["git", "branch", name]
        if from_branch:
            create_cmd.append(from_branch)

        try:
            result = subprocess.run(
                create_cmd, cwd=repo_path, capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"[ERROR] {result.stderr.strip()}"
        except Exception as e:
            return f"[ERROR] {e}"

        if checkout:
            try:
                result = subprocess.run(
                    ["git", "checkout", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return (
                        f"Branch created but checkout failed: {result.stderr.strip()}"
                    )
            except Exception as e:
                return f"Branch created but checkout failed: {e}"
            return f"Created and switched to branch: {name}"

        return f"Created branch: {name}"

    # ---- submit_result ----
    chat_result: dict[str, Any] = {}

    def submit_result(inp: dict[str, Any]) -> str:
        chat_result.update(inp)
        return f"Result submitted: {inp.get('status', 'done')}"

    # ---- append_file ----
    def append_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write(inp["content"])
            return f"Appended {len(inp['content'])} bytes to {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- rename_file ----
    def rename_file(inp: dict[str, Any]) -> str:
        from_rel = str(inp["from_path"])
        to_rel = str(inp["to_path"])
        if _is_protected_path(from_rel, repo_path) or _is_protected_path(
            to_rel, repo_path
        ):
            return "[POLICY DENIED] Protected path involved."
        src = root / from_rel
        dst = root / to_rel
        if not src.exists():
            return f"[ERROR] Source not found: {from_rel}"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return f"Moved {from_rel} → {to_rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- copy_file ----
    def copy_file(inp: dict[str, Any]) -> str:
        import shutil

        from_rel = str(inp["from_path"])
        to_rel = str(inp["to_path"])
        if _is_protected_path(to_rel, repo_path):
            return f"[POLICY DENIED] Protected destination: {to_rel}"
        src = root / from_rel
        dst = root / to_rel
        if not src.exists():
            return f"[ERROR] Source not found: {from_rel}"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            return f"Copied {from_rel} → {to_rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_commit ----
    def git_commit(inp: dict[str, Any]) -> str:
        message = str(inp["message"])
        files: list[str] = inp.get("files", [])
        try:
            if files == ["--all"] or files == ["-a"]:
                subprocess.run(
                    ["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True
                )
            else:
                for f in files:
                    subprocess.run(
                        ["git", "add", f],
                        cwd=repo_path,
                        check=True,
                        capture_output=True,
                    )
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return (result.stdout + result.stderr).strip()
        except subprocess.CalledProcessError as e:
            return f"[ERROR] git add failed: {e.stderr}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_branch ----
    def git_branch(inp: dict[str, Any]) -> str:
        action = str(inp.get("action", "list"))
        name = inp.get("name", "")
        try:
            if action == "list":
                r = subprocess.run(
                    ["git", "branch", "-a"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout or "(no branches)"
            elif action == "create":
                if not name:
                    return "[ERROR] name required for create"
                r = subprocess.run(
                    ["git", "branch", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout + r.stderr or f"Branch '{name}' created"
            elif action == "delete":
                if not name:
                    return "[ERROR] name required for delete"
                r = subprocess.run(
                    ["git", "branch", "-d", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout + r.stderr or f"Branch '{name}' deleted"
            return f"[ERROR] Unknown action: {action}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_checkout ----
    def git_checkout(inp: dict[str, Any]) -> str:
        target = str(inp["target"])
        file_path = inp.get("file", "")
        cmd = ["git", "checkout", target]
        if file_path:
            cmd = ["git", "checkout", target, "--", file_path]
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            out = (r.stdout + r.stderr).strip()
            return out or f"Checked out {target}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_stash ----
    def git_stash(inp: dict[str, Any]) -> str:
        action = str(inp.get("action", "push"))
        message = inp.get("message", "")
        cmd = ["git", "stash"]
        if action == "push":
            if message:
                cmd += ["push", "-m", message]
        elif action == "pop":
            cmd.append("pop")
        elif action == "list":
            cmd.append("list")
        elif action == "drop":
            cmd.append("drop")
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            return (r.stdout + r.stderr).strip() or f"git stash {action} complete"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_pull ----
    def git_pull(inp: dict[str, Any]) -> str:
        remote = str(inp.get("remote", "origin"))
        branch = str(inp.get("branch", ""))
        rebase = bool(inp.get("rebase", False))
        cmd = ["git", "pull"]
        if rebase:
            cmd.append("--rebase")
        cmd.append(remote)
        if branch:
            cmd.append(branch)
        try:
            r = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
            )
            return (r.stdout + r.stderr).strip() or "Pull complete"
        except subprocess.TimeoutExpired:
            return "[ERROR] git pull timed out after 60s"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_fetch ----
    def git_fetch(inp: dict[str, Any]) -> str:
        remote = str(inp.get("remote", "origin"))
        prune = bool(inp.get("prune", False))
        cmd = ["git", "fetch", remote]
        if prune:
            cmd.append("--prune")
        try:
            r = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
            )
            return (r.stdout + r.stderr).strip() or "Fetch complete"
        except subprocess.TimeoutExpired:
            return "[ERROR] git fetch timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_restore ----
    def git_restore(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        staged = bool(inp.get("staged", False))
        cmd = ["git", "restore"]
        if staged:
            cmd.append("--staged")
        cmd.append(rel)
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            out = (r.stdout + r.stderr).strip()
            return out or f"Restored {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- run_tests ----
    def run_tests(inp: dict[str, Any]) -> str:
        runner = str(inp.get("runner", "pytest"))
        path = str(inp.get("path", ""))
        flags = str(inp.get("flags", ""))

        if runner == "pytest":
            cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m pytest {path} {flags} --tb=short -q 2>&1 | head -100"
        elif runner == "npm_test":
            web_path = str(root.parent / "apps" / "web") if not path else path
            cmd = f"cd {web_path} && npm test {flags} 2>&1 | head -100"
        elif runner == "tsc":
            web_path = str(root.parent / "apps" / "web") if not path else path
            cmd = f"cd {web_path} && npx tsc --noEmit {flags} 2>&1 | head -100"
        else:
            return f"[ERROR] Unknown runner: {runner}"

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=180
            )
            out = (result.stdout + result.stderr)[:5000]
            return out.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Tests timed out after 3 minutes"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- run_linter ----
    def run_linter(inp: dict[str, Any]) -> str:
        tool = str(inp.get("tool", "all"))
        path = str(inp.get("path", ""))
        fix = bool(inp.get("fix", False))
        results: list[str] = []

        if tool in ("ruff", "all"):
            target = path or f"{repo_path}"
            fix_flag = "--fix" if fix else ""
            cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m ruff check {target} {fix_flag} 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            results.append(f"=== ruff ===\n{(r.stdout + r.stderr)[:2000] or 'clean'}")

        if tool in ("mypy", "all"):
            target = path or f"{repo_path}"
            cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m mypy {target} --ignore-missing-imports 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=90
            )
            results.append(f"=== mypy ===\n{(r.stdout + r.stderr)[:2000] or 'clean'}")

        if tool in ("tsc", "all"):
            web = str(root.parent / "apps" / "web")
            cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=90
            )
            results.append(f"=== tsc ===\n{(r.stdout + r.stderr)[:2000] or 'clean'}")

        if tool == "black":
            target = path or f"{repo_path}"
            cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m black {'--check' if not fix else ''} {target} 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            results.append(f"=== black ===\n{(r.stdout + r.stderr)[:2000]}")

        return "\n\n".join(results) if results else f"[ERROR] Unknown linter: {tool}"

    # =========================================================================
    # BATCH 1 — File / Editing extras
    # =========================================================================

    def find_file(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        ff_dir = str(inp.get("directory", ""))
        ff_root = root / ff_dir if ff_dir else root
        try:
            r = subprocess.run(
                [
                    "find",
                    str(ff_root),
                    "-name",
                    name,
                    "-not",
                    "-path",
                    "*/node_modules/*",
                    "-not",
                    "-path",
                    "*/__pycache__/*",
                    "-not",
                    "-path",
                    "*/.git/*",
                    "-not",
                    "-path",
                    "*/.venv/*",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            found = [ln for ln in r.stdout.splitlines() if ln.strip()]
            if not found:
                return f"(no files matching '{name}')"
            rel_paths = []
            for p in found[:100]:
                try:
                    rel_paths.append(str(Path(p).relative_to(root)))
                except ValueError:
                    rel_paths.append(p)
            return "\n".join(rel_paths)
        except subprocess.TimeoutExpired:
            return "[ERROR] find timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def format_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        formatter = str(inp.get("formatter", "auto"))
        fmt_target = root / rel
        if not fmt_target.exists():
            return f"[ERROR] File not found: {rel}"
        if formatter == "auto":
            formatter = "ruff" if fmt_target.suffix == ".py" else "prettier"
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        if formatter in ("ruff", "black"):
            cmd = f"{activate} && python -m {formatter} format {str(fmt_target)} 2>&1"
        elif formatter == "prettier":
            cmd = f"cd {repo_path} && npx prettier --write {str(fmt_target)} 2>&1"
        else:
            return f"[ERROR] Unknown formatter: {formatter}"
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30
        )
        return (r.stdout + r.stderr).strip() or f"Formatted {rel}"

    def organize_imports(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        oi_target = root / rel
        if not oi_target.exists():
            return f"[ERROR] File not found: {rel}"
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        cmd = (
            f"{activate} && python -m ruff check --select I --fix {str(oi_target)} 2>&1"
        )
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30
        )
        return (r.stdout + r.stderr).strip() or f"Imports organized in {rel}"

    def insert_at_line(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        line_num = int(inp["line"])
        content = str(inp["content"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        ial_target = root / rel
        if not ial_target.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            file_lines = ial_target.read_text(encoding="utf-8").splitlines(
                keepends=True
            )
            insert_at = max(0, line_num - 1) if line_num > 0 else len(file_lines)
            insert_at = min(insert_at, len(file_lines))
            ins_content = content if content.endswith("\n") else content + "\n"
            file_lines.insert(insert_at, ins_content)
            ial_target.write_text("".join(file_lines), encoding="utf-8")
            return f"Inserted at line {line_num} in {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def replace_function(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        func_name = str(inp["function_name"])
        new_code = str(inp["new_code"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        rf_target = root / rel
        if not rf_target.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            rf_lines = rf_target.read_text(encoding="utf-8").splitlines(keepends=True)
            rf_start = None
            rf_indent = 0
            for rf_i, rf_line in enumerate(rf_lines):
                rf_stripped = rf_line.strip()
                if rf_stripped.startswith(
                    f"def {func_name}("
                ) or rf_stripped.startswith(f"async def {func_name}("):
                    rf_start = rf_i
                    rf_indent = len(rf_line) - len(rf_line.lstrip())
                    break
            if rf_start is None:
                return f"[ERROR] Function '{func_name}' not found in {rel}"
            rf_end = len(rf_lines)
            for rf_j in range(rf_start + 1, len(rf_lines)):
                rf_jline = rf_lines[rf_j]
                if rf_jline.strip() == "":
                    continue
                rf_jind = len(rf_jline) - len(rf_jline.lstrip())
                if (
                    rf_jind <= rf_indent
                    and rf_jline.strip()
                    and not rf_jline.strip().startswith(("#", "@"))
                ):
                    rf_end = rf_j
                    break
            rf_new = new_code if new_code.endswith("\n") else new_code + "\n"
            rf_result = rf_lines[:rf_start] + [rf_new] + rf_lines[rf_end:]
            rf_target.write_text("".join(rf_result), encoding="utf-8")
            return f"Replaced '{func_name}' in {rel} (lines {rf_start + 1}-{rf_end})"
        except Exception as e:
            return f"[ERROR] {e}"

    def delete_lines(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        dl_start = int(inp["start_line"])
        dl_end = int(inp["end_line"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        dl_target = root / rel
        if not dl_target.exists():
            return f"[ERROR] File not found: {rel}"
        if dl_start < 1 or dl_end < dl_start:
            return f"[ERROR] Invalid line range: {dl_start}-{dl_end}"
        try:
            dl_lines = dl_target.read_text(encoding="utf-8").splitlines(keepends=True)
            total = len(dl_lines)
            if dl_start > total:
                return f"[ERROR] File only has {total} lines"
            dl_s = dl_start - 1
            dl_e = min(dl_end, total)
            deleted = dl_e - dl_s
            dl_target.write_text(
                "".join(dl_lines[:dl_s] + dl_lines[dl_e:]), encoding="utf-8"
            )
            return f"Deleted {deleted} lines ({dl_start}-{dl_end}) from {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def apply_patch(inp: dict[str, Any]) -> str:
        import os as _os
        import tempfile as _tempfile

        patch_content = str(inp["patch"])
        strip = int(inp.get("strip", 1))
        try:
            with _tempfile.NamedTemporaryFile(
                mode="w", suffix=".patch", delete=False
            ) as pf:
                pf.write(patch_content)
                pf_name = pf.name
        except Exception as e:
            return f"[ERROR] Cannot write patch file: {e}"
        try:
            r = subprocess.run(
                ["patch", f"-p{strip}", "--input", pf_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "Patch applied"
        except FileNotFoundError:
            return "[ERROR] 'patch' command not found"
        except subprocess.TimeoutExpired:
            return "[ERROR] patch timed out"
        except Exception as e:
            return f"[ERROR] {e}"
        finally:
            try:
                _os.unlink(pf_name)
            except Exception:
                pass

    def compare_files(inp: dict[str, Any]) -> str:
        rel_a = str(inp["path_a"])
        rel_b = str(inp["path_b"])
        context = int(inp.get("context", 3))
        cf_a = root / rel_a
        cf_b = root / rel_b
        if not cf_a.exists():
            return f"[ERROR] File not found: {rel_a}"
        if not cf_b.exists():
            return f"[ERROR] File not found: {rel_b}"
        r = subprocess.run(
            ["diff", f"-U{context}", str(cf_a), str(cf_b)],
            capture_output=True,
            text=True,
        )
        return r.stdout[:8000] or "Files are identical"

    # =========================================================================
    # BATCH 2 — Terminal extras
    # =========================================================================

    def run_background(inp: dict[str, Any]) -> str:
        rb_command = str(inp["command"])
        rb_cwd = str(inp.get("cwd") or repo_path)
        try:
            proc = subprocess.Popen(
                rb_command,
                shell=True,
                cwd=rb_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _session_bg_procs[proc.pid] = proc
            return f"Started background process PID {proc.pid}: {rb_command[:80]}"
        except Exception as e:
            return f"[ERROR] {e}"

    def kill_process(inp: dict[str, Any]) -> str:
        import os as _os
        import signal as _signal

        kp_pid = int(inp["pid"])
        kp_sig_name = str(inp.get("signal", "TERM"))
        sig_map = {
            "TERM": _signal.SIGTERM,
            "KILL": _signal.SIGKILL,
            "INT": _signal.SIGINT,
        }
        kp_sig = sig_map.get(kp_sig_name, _signal.SIGTERM)
        _session_bg_procs.pop(kp_pid, None)
        try:
            _os.kill(kp_pid, kp_sig)
            return f"Sent {kp_sig_name} to PID {kp_pid}"
        except ProcessLookupError:
            return f"[ERROR] No process with PID {kp_pid}"
        except Exception as e:
            return f"[ERROR] {e}"

    def run_python_snippet(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        code = str(inp["code"])
        ps_timeout = int(inp.get("timeout", 30))
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        cmd = f"{activate} && python3 -c {_shlex.quote(code)} 2>&1"
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=ps_timeout,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[ERROR] Python snippet timed out after {ps_timeout}s"
        except Exception as e:
            return f"[ERROR] {e}"

    def run_make(inp: dict[str, Any]) -> str:
        make_target = str(inp.get("target", ""))
        make_dir_rel = str(inp.get("directory", ""))
        make_dir = (root / make_dir_rel) if make_dir_rel else root
        makefile_exists = (make_dir / "Makefile").exists() or (
            make_dir / "makefile"
        ).exists()
        if not makefile_exists:
            return f"[ERROR] No Makefile found in {make_dir}"
        if not make_target:
            r = subprocess.run(
                ["make", "-pRrq"],
                cwd=str(make_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            tgts: list[str] = []
            for mk_line in r.stdout.splitlines():
                if (
                    mk_line
                    and not mk_line.startswith(("\t", "#", " "))
                    and ":" in mk_line
                ):
                    tgt = mk_line.split(":")[0].strip()
                    if tgt and not tgt.startswith(".") and " " not in tgt:
                        tgts.append(tgt)
            return (
                "Targets:\n" + "\n".join(sorted(set(tgts[:30])))
                if tgts
                else "Makefile found but targets not parseable"
            )
        try:
            r = subprocess.run(
                ["make", make_target],
                cwd=str(make_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            return (r.stdout + r.stderr)[:5000] or f"make {make_target} complete"
        except subprocess.TimeoutExpired:
            return f"[ERROR] make {make_target} timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def fetch_url(inp: dict[str, Any]) -> str:
        fu_url = str(inp["url"])
        fu_timeout = int(inp.get("timeout", 15))
        try:
            r = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-L",
                    "--max-time",
                    str(fu_timeout),
                    "--user-agent",
                    "Gridiron-Agent/1.0",
                    fu_url,
                ],
                capture_output=True,
                text=True,
                timeout=fu_timeout + 5,
            )
            return r.stdout[:10000] or r.stderr or "[empty response]"
        except subprocess.TimeoutExpired:
            return f"[ERROR] Request timed out after {fu_timeout}s"
        except FileNotFoundError:
            return "[ERROR] curl not found"
        except Exception as e:
            return f"[ERROR] {e}"

    # =========================================================================
    # BATCH 3 — Git extras
    # =========================================================================

    def git_merge(inp: dict[str, Any]) -> str:
        gm_branch = str(inp["branch"])
        gm_no_ff = bool(inp.get("no_ff", False))
        gm_squash = bool(inp.get("squash", False))
        gm_msg = str(inp.get("message", ""))
        gm_cmd = ["git", "merge"]
        if gm_no_ff:
            gm_cmd.append("--no-ff")
        if gm_squash:
            gm_cmd.append("--squash")
        if gm_msg:
            gm_cmd += ["-m", gm_msg]
        gm_cmd.append(gm_branch)
        try:
            r = subprocess.run(
                gm_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            return (r.stdout + r.stderr).strip() or f"Merged {gm_branch}"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_reset(inp: dict[str, Any]) -> str:
        gr_ref = str(inp.get("ref", "HEAD"))
        gr_mode = str(inp.get("mode", "mixed"))
        if gr_mode == "hard":
            return (
                "[BLOCKED] git reset --hard is destructive and requires confirmation. "
                "Use the bash tool if you're sure, or use mode=soft/mixed."
            )
        gr_cmd = ["git", "reset", f"--{gr_mode}", gr_ref]
        try:
            r = subprocess.run(
                gr_cmd, cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            return (r.stdout + r.stderr).strip() or f"Reset {gr_mode} to {gr_ref}"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_worktree(inp: dict[str, Any]) -> str:
        gw_action = str(inp.get("action", "list"))
        gw_path = str(inp.get("path", ""))
        gw_branch = str(inp.get("branch", ""))
        try:
            if gw_action == "list":
                r = subprocess.run(
                    ["git", "worktree", "list"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout or "(no worktrees)"
            elif gw_action == "add":
                if not gw_path or not gw_branch:
                    return "[ERROR] path and branch required for add"
                r = subprocess.run(
                    ["git", "worktree", "add", gw_path, gw_branch],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return (r.stdout + r.stderr).strip() or f"Created worktree at {gw_path}"
            elif gw_action == "remove":
                if not gw_path:
                    return "[ERROR] path required for remove"
                r = subprocess.run(
                    ["git", "worktree", "remove", gw_path],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return (r.stdout + r.stderr).strip() or f"Removed worktree at {gw_path}"
            return f"[ERROR] Unknown action: {gw_action}"
        except Exception as e:
            return f"[ERROR] {e}"

    def create_pr(inp: dict[str, Any]) -> str:
        pr_title = str(inp["title"])
        pr_body = str(inp.get("body", ""))
        pr_base = str(inp.get("base", "main"))
        pr_draft = bool(inp.get("draft", False))
        pr_cmd = ["gh", "pr", "create", "--title", pr_title, "--base", pr_base]
        if pr_body:
            pr_cmd += ["--body", pr_body]
        if pr_draft:
            pr_cmd.append("--draft")
        try:
            r = subprocess.run(
                pr_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            return (r.stdout + r.stderr).strip() or "PR created"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found — install with: sudo apt install gh"
        except Exception as e:
            return f"[ERROR] {e}"

    def generate_commit_msg(inp: dict[str, Any]) -> str:
        gcm_staged = bool(inp.get("staged_only", True))
        diff_args = ["diff", "--cached"] if gcm_staged else ["diff"]
        stat_args = diff_args + ["--stat"]
        r_stat = subprocess.run(
            ["git"] + stat_args, cwd=repo_path, capture_output=True, text=True
        )
        r_diff = subprocess.run(
            ["git"] + diff_args, cwd=repo_path, capture_output=True, text=True
        )
        stat = r_stat.stdout.strip()
        diff = r_diff.stdout[:3000]
        if not stat:
            return "[ERROR] No staged changes. Stage files with git_commit or git add first."
        return (
            f"=== Changed files ===\n{stat}\n\n"
            f"=== Diff (truncated to 3000 chars) ===\n{diff}\n\n"
            "Analyze the diff above and write a conventional commit message:\n"
            "Format: <type>(<scope>): <description>\n"
            "Types: feat, fix, docs, refactor, test, chore, style, perf"
        )

    # =========================================================================
    # BATCH 4 — Testing extras
    # =========================================================================

    def run_single_test(inp: dict[str, Any]) -> str:
        rst_kw = str(inp["keyword"])
        rst_file = str(inp.get("file", ""))
        rst_verbose = bool(inp.get("verbose", True))
        rst_vflag = "-v" if rst_verbose else "-q"
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        rst_path = rst_file if rst_file else "backend/tests/"
        cmd = f"{activate} && python -m pytest {rst_path} -k '{rst_kw}' {rst_vflag} --tb=short 2>&1 | head -100"
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=120,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Tests timed out after 2 minutes"
        except Exception as e:
            return f"[ERROR] {e}"

    def coverage_report(inp: dict[str, Any]) -> str:
        cov_path = str(inp.get("path", "backend/tests/"))
        cov_source = str(inp.get("source", "backend/app/"))
        cov_min = inp.get("min_coverage")
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        min_flag = f"--cov-fail-under={cov_min}" if cov_min else ""
        cmd = (
            f"{activate} && python -m pytest {cov_path} "
            f"--cov={cov_source} --cov-report=term-missing {min_flag} "
            f"--tb=no -q 2>&1 | tail -50"
        )
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=180,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Coverage run timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def type_check(inp: dict[str, Any]) -> str:
        tc_path = str(inp.get("path", ""))
        tc_strict = bool(inp.get("strict", False))
        tc_lang = str(inp.get("language", "both"))
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        tc_results: list[str] = []
        if tc_lang in ("python", "both"):
            py_path = tc_path or "backend/"
            strict_flag = "--strict" if tc_strict else "--ignore-missing-imports"
            cmd = (
                f"{activate} && python -m mypy {py_path} {strict_flag} 2>&1 | head -60"
            )
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=90,
            )
            tc_results.append(
                f"=== mypy ===\n{(r.stdout + r.stderr)[:3000] or 'clean'}"
            )
        if tc_lang in ("typescript", "both"):
            web = str(root.parent / "apps" / "web")
            cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -60"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=90
            )
            tc_results.append(f"=== tsc ===\n{(r.stdout + r.stderr)[:3000] or 'clean'}")
        return "\n\n".join(tc_results) if tc_results else "[ERROR] No language selected"

    # =========================================================================
    # BATCH 5 — Code Intelligence
    # =========================================================================

    def list_functions(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        lf_fp = root / rel
        if not lf_fp.exists():
            return f"[ERROR] File not found: {rel}"
        content = lf_fp.read_text(encoding="utf-8", errors="replace")
        lf_lines = content.splitlines()
        lf_results: list[str] = []
        for lf_i, lf_line in enumerate(lf_lines, 1):
            s = lf_line.strip()
            if s.startswith(("def ", "async def ")):
                sig = s.split(":")[0] if ":" in s else s
                lf_results.append(f"  L{lf_i}: {sig}")
            elif (
                s.startswith(
                    ("export function ", "export async function ", "function ")
                )
                and "(" in s
            ):
                lf_results.append(f"  L{lf_i}: {s[:120]}")
            elif s.startswith(("export const ", "const ")) and (
                "=>" in s or "= (" in s or "= async" in s
            ):
                lf_results.append(f"  L{lf_i}: {s[:120]}")
        if not lf_results:
            return f"(no function definitions found in {rel})"
        return f"Functions in {rel} ({len(lf_results)}):\n" + "\n".join(lf_results)

    def list_classes(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        lc_fp = root / rel
        if not lc_fp.exists():
            return f"[ERROR] File not found: {rel}"
        content = lc_fp.read_text(encoding="utf-8", errors="replace")
        lc_lines = content.splitlines()
        lc_results: list[str] = []
        lc_current: str | None = None
        lc_base_indent = 0
        for lc_i, lc_line in enumerate(lc_lines, 1):
            s = lc_line.strip()
            curr_indent = len(lc_line) - len(lc_line.lstrip())
            if s.startswith(("class ", "export class ", "export default class ")):
                lc_current = s.split("(")[0].split("{")[0].rstrip()
                lc_base_indent = curr_indent
                lc_results.append(f"\nL{lc_i}: {lc_current}")
            elif lc_current and curr_indent > lc_base_indent:
                if s.startswith(("def ", "async def ")):
                    lc_results.append(f"    L{lc_i}: {s.split(':')[0]}")
                elif (
                    s.startswith(
                        ("public ", "private ", "protected ", "async ", "static ")
                    )
                    and "(" in s
                ):
                    lc_results.append(f"    L{lc_i}: {s[:120]}")
            elif (
                lc_current
                and lc_line.strip()
                and curr_indent <= lc_base_indent
                and not s.startswith(("@", "#", "/"))
            ):
                lc_current = None
        if not lc_results:
            return f"(no class definitions found in {rel})"
        return f"Classes in {rel}:\n" + "\n".join(lc_results)

    def find_function_body(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        ffb_name = str(inp["function_name"])
        ffb_fp = root / rel
        if not ffb_fp.exists():
            return f"[ERROR] File not found: {rel}"
        ffb_lines = ffb_fp.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        ffb_start: int | None = None
        ffb_base = 0
        for ffb_i, ffb_line in enumerate(ffb_lines):
            s = ffb_line.strip()
            if s.startswith(f"def {ffb_name}(") or s.startswith(
                f"async def {ffb_name}("
            ):
                ffb_start = ffb_i
                ffb_base = len(ffb_line) - len(ffb_line.lstrip())
                break
        if ffb_start is None:
            return f"[ERROR] Function '{ffb_name}' not found in {rel}"
        ffb_end = len(ffb_lines)
        for ffb_j in range(ffb_start + 1, len(ffb_lines)):
            ffb_jline = ffb_lines[ffb_j]
            if ffb_jline.strip() == "":
                continue
            ffb_jind = len(ffb_jline) - len(ffb_jline.lstrip())
            if (
                ffb_jind <= ffb_base
                and ffb_jline.strip()
                and not ffb_jline.strip().startswith(("@", "#"))
            ):
                ffb_end = ffb_j
                break
        body = "".join(ffb_lines[ffb_start:ffb_end])
        return f"=== {ffb_name} (lines {ffb_start + 1}-{ffb_end}) ===\n{body}"

    # =========================================================================
    # BATCH 6 — Debug tools
    # =========================================================================

    def read_logs(inp: dict[str, Any]) -> str:
        rl_path = str(inp.get("path", ""))
        rl_lines = int(inp.get("lines", 50))
        rl_level = str(inp.get("level", "all"))
        out = ""
        if rl_path and ("/" in rl_path or rl_path.endswith(".log")):
            log_file = (
                root / rl_path if not Path(rl_path).is_absolute() else Path(rl_path)
            )
            if log_file.exists():
                r = subprocess.run(
                    ["tail", f"-{rl_lines}", str(log_file)],
                    capture_output=True,
                    text=True,
                )
                out = r.stdout
            else:
                return f"[ERROR] Log file not found: {rl_path}"
        elif rl_path:
            r = subprocess.run(
                ["journalctl", "-u", rl_path, f"-n{rl_lines}", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            out = r.stdout or r.stderr
        else:
            log_dirs = [root / "logs", root / "backend" / "logs", Path("/tmp")]
            found: list[Path] = []
            for ld in log_dirs:
                if ld.exists():
                    found.extend(ld.glob("*.log"))
            if not found:
                return "(no log files found — specify a path or service name)"
            newest = max(found, key=lambda p: p.stat().st_mtime)
            r = subprocess.run(
                ["tail", f"-{rl_lines}", str(newest)], capture_output=True, text=True
            )
            out = f"From {newest}:\n" + r.stdout
        if rl_level != "all":
            filtered = [
                line for line in out.splitlines() if rl_level.upper() in line.upper()
            ]
            out = "\n".join(filtered)
        return out[:5000] or "(no log entries)"

    def analyze_error(inp: dict[str, Any]) -> str:
        ae_error = str(inp["error"])
        ae_lines = ae_error.strip().splitlines()
        exception_line = ""
        for ae_line in reversed(ae_lines):
            if any(
                x in ae_line for x in ("Error:", "Exception:", "Warning:", "Traceback")
            ):
                exception_line = ae_line
                break
        frames: list[str] = []
        ae_i = 0
        while ae_i < len(ae_lines):
            ae_line = ae_lines[ae_i]
            if ae_line.strip().startswith("File ") and "line " in ae_line:
                if not any(
                    x in ae_line for x in ("site-packages", ".venv", "lib/python")
                ):
                    code_line = (
                        ae_lines[ae_i + 1].strip() if ae_i + 1 < len(ae_lines) else ""
                    )
                    frames.append(f"  {ae_line.strip()}\n    → {code_line}")
                ae_i += 2
            else:
                ae_i += 1
        ae_result = ["=== Error Analysis ==="]
        if exception_line:
            ae_result.append(f"Exception: {exception_line.strip()}")
        if frames:
            ae_result.append(f"\nRelevant frames ({len(frames)}):")
            ae_result.extend(frames[-5:])
        ae_low = ae_error.lower()
        suggestions: list[str] = []
        if "modulenotfounderror" in ae_low or "importerror" in ae_low:
            suggestions.append(
                "→ Missing dependency — run: pip install -r requirements.txt"
            )
        elif "attributeerror" in ae_low:
            suggestions.append(
                "→ Object doesn't have this attribute — check spelling and type"
            )
        elif "typeerror" in ae_low:
            suggestions.append("→ Wrong argument type/count — check function signature")
        elif "keyerror" in ae_low:
            suggestions.append(
                "→ Dictionary key not found — use .get() or check key exists"
            )
        elif "filenotfounderror" in ae_low:
            suggestions.append(
                "→ Path doesn't exist — verify path and working directory"
            )
        elif "connectionrefusederror" in ae_low or "connection refused" in ae_low:
            suggestions.append(
                "→ Service not running — check if DB/Redis/backend is started"
            )
        elif "syntaxerror" in ae_low:
            suggestions.append(
                "→ Python syntax error — check brackets, colons, indentation"
            )
        elif "valueerror" in ae_low:
            suggestions.append("→ Invalid value — validate input before passing it")
        if suggestions:
            ae_result.append("\nSuggestions:")
            ae_result.extend(suggestions)
        return "\n".join(ae_result)

    # =========================================================================
    # BATCH 7 — Database tools
    # =========================================================================

    def run_sql(inp: dict[str, Any]) -> str:
        rs_query = str(inp["query"])
        rs_params: list[str] = list(inp.get("params") or [])
        for rs_i, rs_p in enumerate(rs_params, 1):
            rs_query = rs_query.replace(f"${rs_i}", f"'{rs_p}'")
        rs_settings = get_settings()
        rs_db_url = getattr(rs_settings, "database_url", None)
        if not rs_db_url:
            return "[ERROR] DATABASE_URL not configured in settings"
        try:
            r = subprocess.run(
                ["psql", str(rs_db_url), "-c", rs_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except FileNotFoundError:
            return "[ERROR] psql not found — install postgresql-client"
        except subprocess.TimeoutExpired:
            return "[ERROR] Query timed out after 30s"
        except Exception as e:
            return f"[ERROR] {e}"

    def inspect_schema(inp: dict[str, Any]) -> str:
        is_table = str(inp.get("table", ""))
        is_settings = get_settings()
        is_db_url = getattr(is_settings, "database_url", None)
        if not is_db_url:
            return "[ERROR] DATABASE_URL not configured"
        if is_table:
            is_query = (
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                f"WHERE table_name = '{is_table}' ORDER BY ordinal_position"
            )
        else:
            is_query = (
                "SELECT table_name, pg_size_pretty(pg_total_relation_size(table_name::regclass)) AS size "
                "FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        try:
            r = subprocess.run(
                ["psql", str(is_db_url), "-c", is_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr)[:5000] or "(empty schema)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    # =========================================================================
    # BATCH 8 — Docker tools
    # =========================================================================

    def docker_ps(inp: dict[str, Any]) -> str:
        show_all = bool(inp.get("all", False))
        docker_cmd = [
            "docker",
            "ps",
            "--format",
            "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}",
        ]
        if show_all:
            docker_cmd.append("-a")
        try:
            r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=10)
            return (r.stdout + r.stderr)[:3000] or "(no containers)"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_logs(inp: dict[str, Any]) -> str:
        dl_container = str(inp["container"])
        dl_lines = int(inp.get("lines", 50))
        try:
            r = subprocess.run(
                ["docker", "logs", "--tail", str(dl_lines), dl_container],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (r.stdout + r.stderr)[:5000] or "(no logs)"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_exec(inp: dict[str, Any]) -> str:
        de_container = str(inp["container"])
        de_command = str(inp["command"])
        try:
            r = subprocess.run(
                ["docker", "exec", de_container, "sh", "-c", de_command],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_compose(inp: dict[str, Any]) -> str:
        dc_action = str(inp["action"])
        dc_services: list[str] = list(inp.get("services") or [])
        dc_detach = bool(inp.get("detach", True))
        dc_cmd = ["docker", "compose"]
        if dc_action == "up":
            dc_cmd.append("up")
            if dc_detach:
                dc_cmd.append("-d")
        elif dc_action in ("down", "restart", "build", "ps", "pull"):
            dc_cmd.append(dc_action)
        elif dc_action == "logs":
            dc_cmd += ["logs", "--tail=50"]
        else:
            return f"[ERROR] Unknown action: {dc_action}"
        dc_cmd.extend(dc_services)
        try:
            r = subprocess.run(
                dc_cmd, cwd=repo_path, capture_output=True, text=True, timeout=120
            )
            return (r.stdout + r.stderr)[
                :5000
            ] or f"docker compose {dc_action} complete"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except subprocess.TimeoutExpired:
            return f"[ERROR] docker compose {dc_action} timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    # =========================================================================
    # BATCH 9 — Security tools
    # =========================================================================

    def secrets_scan(inp: dict[str, Any]) -> str:
        ss_dir = str(inp.get("directory", ""))
        ss_root = (root / ss_dir) if ss_dir else root
        ss_patterns = [
            r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{4,}['\"]",
            r"(?i)(api[_-]?key|apikey|api[_-]?secret)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
            r"(?i)(secret[_-]?key|secretkey)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
            r"(?i)(access[_-]?token|auth[_-]?token)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
            r"(sk-[a-zA-Z0-9]{20,})",
            r"(AKIA[0-9A-Z]{16})",
            r"(ghp_[a-zA-Z0-9]{36})",
        ]
        ss_exclude = [
            "node_modules",
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "dist",
            "build",
            ".next",
        ]
        ss_findings: list[str] = []
        for ss_pat in ss_patterns:
            ss_cmd = ["grep", "-rn", "-E", ss_pat, str(ss_root)]
            for ex in ss_exclude:
                ss_cmd += ["--exclude-dir", ex]
            ss_cmd += [
                "--exclude",
                "*.env",
                "--exclude",
                ".env*",
                "--exclude",
                "*.example",
            ]
            try:
                r = subprocess.run(ss_cmd, capture_output=True, text=True, timeout=15)
                if r.stdout.strip():
                    ss_findings.append(r.stdout.strip())
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
        if not ss_findings:
            return "✅ No hardcoded secrets detected."
        return "⚠️  Potential secrets found:\n\n" + "\n\n".join(ss_findings)[:5000]

    handlers["edit_file"] = edit_file
    handlers["write_file"] = write_file
    handlers["git_diff"] = git_diff
    handlers["bash"] = bash
    handlers["append_file"] = append_file
    handlers["rename_file"] = rename_file
    handlers["copy_file"] = copy_file
    handlers["delete_file"] = delete_file
    handlers["git_commit"] = git_commit
    handlers["git_branch"] = git_branch
    handlers["git_checkout"] = git_checkout
    handlers["git_stash"] = git_stash
    handlers["git_pull"] = git_pull
    handlers["git_fetch"] = git_fetch
    handlers["git_restore"] = git_restore
    handlers["git_push"] = git_push
    handlers["create_branch"] = create_branch
    handlers["run_tests"] = run_tests
    handlers["run_linter"] = run_linter
    handlers["submit_result"] = submit_result
    # Batch 1
    handlers["find_file"] = find_file
    handlers["format_file"] = format_file
    handlers["organize_imports"] = organize_imports
    handlers["insert_at_line"] = insert_at_line
    handlers["replace_function"] = replace_function
    handlers["delete_lines"] = delete_lines
    handlers["apply_patch"] = apply_patch
    handlers["compare_files"] = compare_files
    # Batch 2
    handlers["run_background"] = run_background
    handlers["kill_process"] = kill_process
    handlers["run_python_snippet"] = run_python_snippet
    handlers["run_make"] = run_make
    handlers["fetch_url"] = fetch_url
    # Batch 3
    handlers["git_merge"] = git_merge
    handlers["git_reset"] = git_reset
    handlers["git_worktree"] = git_worktree
    handlers["create_pr"] = create_pr
    handlers["generate_commit_msg"] = generate_commit_msg
    # Batch 4
    handlers["run_single_test"] = run_single_test
    handlers["coverage_report"] = coverage_report
    handlers["type_check"] = type_check
    # Batch 5
    handlers["list_functions"] = list_functions
    handlers["list_classes"] = list_classes
    handlers["find_function_body"] = find_function_body
    # Batch 6
    handlers["read_logs"] = read_logs
    handlers["analyze_error"] = analyze_error
    # Batch 7
    handlers["run_sql"] = run_sql
    handlers["inspect_schema"] = inspect_schema
    # Batch 8
    handlers["docker_ps"] = docker_ps
    handlers["docker_logs"] = docker_logs
    handlers["docker_exec"] = docker_exec
    handlers["docker_compose"] = docker_compose
    # Batch 9
    handlers["secrets_scan"] = secrets_scan
    handlers["_chat_result"] = chat_result

    # =========================================================================
    # BATCH 10 — AST Engine (parse_ast, import_graph, call_graph, dead_code_detect,
    #             circular_dep_detect, rename_symbol)
    # =========================================================================

    def parse_ast_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import parse_file_ast

        return parse_file_ast(str(root / str(inp["path"])))

    def import_graph_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import build_import_graph

        return build_import_graph(str(root / str(inp["path"])))

    def call_graph_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import build_call_graph

        return build_call_graph(
            str(root / str(inp["path"])), str(inp.get("function_name", ""))
        )

    def dead_code_detect_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import detect_dead_code

        dcd_d = str(inp.get("directory", ""))
        return detect_dead_code(str(root / dcd_d) if dcd_d else repo_path)

    def circular_dep_detect_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import detect_circular_imports

        cdd_d = str(inp.get("directory", ""))
        return detect_circular_imports(str(root / cdd_d) if cdd_d else repo_path)

    def rename_symbol_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import rename_symbol as _rsym

        rs_d = str(inp.get("directory", ""))
        return _rsym(
            str(inp["old_name"]),
            str(inp["new_name"]),
            str(root / rs_d) if rs_d else repo_path,
            str(inp.get("file_pattern", "*.py")),
        )

    handlers["parse_ast"] = parse_ast_h
    handlers["import_graph"] = import_graph_h
    handlers["call_graph"] = call_graph_h
    handlers["dead_code_detect"] = dead_code_detect_h
    handlers["circular_dep_detect"] = circular_dep_detect_h
    handlers["rename_symbol"] = rename_symbol_h

    # =========================================================================
    # BATCH 11 — Git extras (git_rebase, git_cherry_pick)
    # =========================================================================

    def git_rebase_h(inp: dict[str, Any]) -> str:
        grb_onto = str(inp["onto"])
        if bool(inp.get("interactive", False)):
            return "[BLOCKED] Interactive rebase requires a TTY. Run 'git rebase -i' manually in a terminal."
        try:
            r = subprocess.run(
                ["git", "rebase", grb_onto],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] git rebase timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_cherry_pick_h(inp: dict[str, Any]) -> str:
        gcp_hash = str(inp["commit_hash"])
        gcp_cmd = ["git", "cherry-pick"]
        if bool(inp.get("no_commit", False)):
            gcp_cmd.append("--no-commit")
        gcp_cmd.append(gcp_hash)
        try:
            r = subprocess.run(
                gcp_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["git_rebase"] = git_rebase_h
    handlers["git_cherry_pick"] = git_cherry_pick_h

    # =========================================================================
    # BATCH 12 — Terminal extras (read_output, run_node, run_script, docker_build, docker_restart)
    # =========================================================================

    def read_output_h(inp: dict[str, Any]) -> str:
        import fcntl as _fcntl
        import os as _os

        ro_pid = int(inp["pid"])
        ro_max = int(inp.get("lines", 50))
        proc = _session_bg_procs.get(ro_pid)
        if proc is None:
            return f"[ERROR] No tracked background process with PID {ro_pid}"
        if proc.poll() is not None:
            return f"Process {ro_pid} has exited (code {proc.returncode})"
        out_lines: list[str] = []
        for stream in [proc.stdout, proc.stderr]:
            if stream is None:
                continue
            fd = stream.fileno()
            fl = _fcntl.fcntl(fd, _fcntl.F_GETFL)
            _fcntl.fcntl(fd, _fcntl.F_SETFL, fl | _os.O_NONBLOCK)
            try:
                chunk = stream.read(8192)
                if chunk:
                    out_lines.extend(chunk.splitlines())
            except (IOError, BlockingIOError, TypeError):
                pass
        return (
            "\n".join(out_lines[-ro_max:])
            if out_lines
            else f"(no output yet from PID {ro_pid})"
        )

    def run_node_h(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        rnd_code = str(inp["code"])
        rnd_timeout = int(inp.get("timeout", 30))
        node_chk = subprocess.run(["which", "node"], capture_output=True, text=True)
        if node_chk.returncode != 0:
            node_chk2 = subprocess.run(
                ["which", "nodejs"], capture_output=True, text=True
            )
            if node_chk2.returncode != 0:
                return "[ERROR] Node.js not found. Install Node.js first (e.g. nvm install --lts)."
        try:
            r = subprocess.run(
                f"node -e {_shlex.quote(rnd_code)} 2>&1",
                shell=True,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=rnd_timeout,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[ERROR] node timed out after {rnd_timeout}s"
        except Exception as e:
            return f"[ERROR] {e}"

    def run_script_h(inp: dict[str, Any]) -> str:
        rscr_rel = str(inp["path"])
        rscr_interp = str(inp.get("interpreter", "auto"))
        rscr_fp = root / rscr_rel
        if not rscr_fp.exists():
            return f"[ERROR] Script not found: {rscr_rel}"
        if rscr_interp == "auto":
            ext = rscr_fp.suffix
            rscr_interp = (
                "python3"
                if ext == ".py"
                else "node" if ext in (".js", ".mjs", ".cjs") else "bash"
            )
        try:
            r = subprocess.run(
                [rscr_interp, str(rscr_fp)],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                result += f"\n[exit {r.returncode}]"
            return result or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Script timed out after 120s"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_build_h(inp: dict[str, Any]) -> str:
        dbld_tag = str(inp["tag"])
        dbld_context = str(inp.get("context", "."))
        dbld_df = inp.get("dockerfile")
        dbld_ctx_path = str(root / dbld_context) if dbld_context != "." else repo_path
        dbld_cmd = ["docker", "build", "-t", dbld_tag]
        if dbld_df:
            dbld_cmd += ["-f", str(root / str(dbld_df))]
        dbld_cmd.append(dbld_ctx_path)
        try:
            r = subprocess.run(
                dbld_cmd, cwd=repo_path, capture_output=True, text=True, timeout=600
            )
            result = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                result += f"\n[exit {r.returncode}]"
            return result or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] docker build timed out after 600s"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_restart_h(inp: dict[str, Any]) -> str:
        drst_name = str(inp["container"])
        try:
            r = subprocess.run(
                ["docker", "restart", drst_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or f"Restarted {drst_name}"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["read_output"] = read_output_h
    handlers["run_node"] = run_node_h
    handlers["run_script"] = run_script_h
    handlers["docker_build"] = docker_build_h
    handlers["docker_restart"] = docker_restart_h

    # =========================================================================
    # BATCH 13 — Smart search (find_route, find_api, find_sql, find_test, find_config)
    # =========================================================================

    def find_route_h(inp: dict[str, Any]) -> str:
        frt_method = str(inp.get("method", "")).upper()
        frt_path_pat = str(inp.get("path_pattern", ""))
        if frt_method:
            pat = rf"@(router|app)\.{frt_method.lower()}\("
        else:
            pat = r"@(router|app)\.(get|post|put|delete|patch|head|options)\("
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        try:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-E",
                    pat,
                    repo_path,
                    "--include=*.py",
                    "--include=*.ts",
                ]
                + exclude,
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = r.stdout
            if frt_path_pat:
                lines = "\n".join(ln for ln in lines.splitlines() if frt_path_pat in ln)
            return (
                lines[:5000]
                if lines.strip()
                else "No routes found" + (f" for {frt_method}" if frt_method else "")
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def find_api_h(inp: dict[str, Any]) -> str:
        fapi_name = str(inp.get("name", ""))
        if fapi_name:
            pat = fapi_name
        else:
            pat = r"@(router|app)\.(get|post|put|delete|patch)\("
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        try:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-E",
                    pat,
                    repo_path,
                    "--include=*.py",
                    "--include=*.ts",
                ]
                + exclude,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (
                r.stdout[:5000]
                if r.stdout.strip()
                else "No API definitions found"
                + (f" matching '{fapi_name}'" if fapi_name else "")
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def find_sql_h(inp: dict[str, Any]) -> str:
        fsql_kw = str(inp.get("keyword", "")).upper()
        # Use -i for case-insensitive, -w for whole-word; avoid (?i) inline flag (not ERE)
        if fsql_kw:
            fsql_pat = fsql_kw
            fsql_flags = ["-rn", "-i", "-w"]
        else:
            fsql_pat = r"SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE"
            fsql_flags = ["-rn", "-i", "-E"]
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        try:
            r = subprocess.run(
                ["grep"]
                + fsql_flags
                + [
                    fsql_pat,
                    repo_path,
                    "--include=*.py",
                    "--include=*.sql",
                    "--include=*.ts",
                ]
                + exclude,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (
                r.stdout[:5000]
                if r.stdout.strip()
                else "No SQL statements found in codebase"
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def find_test_h(inp: dict[str, Any]) -> str:
        ftest_fn = str(inp["function_name"])
        patterns = [
            f"def test_{ftest_fn}",
            f"def test.*{ftest_fn}",
            f"test.*[\"'].*{ftest_fn}",
        ]
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        ftest_out: list[str] = []
        for pt in patterns:
            try:
                r = subprocess.run(
                    [
                        "grep",
                        "-rn",
                        "-E",
                        pt,
                        repo_path,
                        "--include=*.py",
                        "--include=*.ts",
                    ]
                    + exclude,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if r.stdout.strip():
                    ftest_out.append(r.stdout[:2000])
            except Exception:
                pass
        return (
            "\n".join(ftest_out)[:5000]
            if ftest_out
            else f"No tests found for '{ftest_fn}'"
        )

    def find_config_h(inp: dict[str, Any]) -> str:
        fcfg_key = str(inp["key"])
        patterns_to_try = [fcfg_key, fcfg_key.upper(), fcfg_key.lower()]
        include_globs = [
            "--include=*.env*",
            "--include=.env*",
            "--include=*.yaml",
            "--include=*.yml",
            "--include=*.toml",
            "--include=*.cfg",
            "--include=*.ini",
            "--include=config.py",
            "--include=settings.py",
        ]
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        fcfg_out: list[str] = []
        seen: set[str] = set()
        for pt in patterns_to_try:
            try:
                r = subprocess.run(
                    ["grep", "-rn", pt, repo_path] + include_globs + exclude,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                for ln in r.stdout.splitlines():
                    if ln not in seen:
                        seen.add(ln)
                        fcfg_out.append(ln)
            except Exception:
                pass
        return (
            "\n".join(fcfg_out)[:5000]
            if fcfg_out
            else f"'{fcfg_key}' not found in config files"
        )

    handlers["find_route"] = find_route_h
    handlers["find_api"] = find_api_h
    handlers["find_sql"] = find_sql_h
    handlers["find_test"] = find_test_h
    handlers["find_config"] = find_config_h

    # =========================================================================
    # BATCH 14 — Monitoring (cpu_usage, memory_usage, disk_usage, health_check, task_progress)
    # =========================================================================

    def cpu_usage_h(inp: dict[str, Any]) -> str:
        try:
            proc_stat = Path("/proc/stat")
            if proc_stat.exists():
                lines = proc_stat.read_text().splitlines()
                cpu_line = lines[0] if lines else ""
                fields = cpu_line.split()
                if len(fields) >= 5:
                    total = sum(int(f) for f in fields[1:])
                    idle = int(fields[4])
                    used_pct = round((total - idle) / total * 100, 1) if total else 0
                    return f"CPU: {used_pct}% used  (raw: {cpu_line})"
            r = subprocess.run(
                ["top", "-bn1"], capture_output=True, text=True, timeout=5
            )
            for ln in r.stdout.splitlines():
                if "Cpu" in ln or "cpu" in ln:
                    return f"CPU: {ln.strip()}"
            return "(could not read CPU usage)"
        except Exception as e:
            return f"[ERROR] {e}"

    def memory_usage_h(inp: dict[str, Any]) -> str:
        try:
            mem_info = Path("/proc/meminfo")
            if mem_info.exists():
                rows = mem_info.read_text().splitlines()[:8]
                return "\n".join(rows)
            r = subprocess.run(
                ["free", "-h"], capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() or "(no memory info)"
        except Exception as e:
            return f"[ERROR] {e}"

    def disk_usage_h(inp: dict[str, Any]) -> str:
        import shutil as _shu

        dsk_path = str(inp.get("path", "")) or repo_path
        try:
            u = _shu.disk_usage(dsk_path)
            gb = 1024**3
            pct = round(u.used / u.total * 100, 1) if u.total else 0
            return (
                f"Disk usage for {dsk_path}:\n"
                f"  Total: {u.total / gb:.1f} GB\n"
                f"  Used:  {u.used / gb:.1f} GB  ({pct}%)\n"
                f"  Free:  {u.free / gb:.1f} GB"
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def health_check_h(inp: dict[str, Any]) -> str:
        hc_svc = str(inp.get("service", "all"))
        settings = get_settings()
        hc_results: list[str] = []
        if hc_svc in ("all", "backend"):
            hc_port = getattr(settings, "port", 8000)
            try:
                r = subprocess.run(
                    [
                        "curl",
                        "-s",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        f"http://localhost:{hc_port}/health",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                code = r.stdout.strip()
                hc_results.append(
                    f"Backend (:{hc_port}/health): {'✅ UP' if code == '200' else f'⚠️ HTTP {code}'}"
                )
            except Exception:
                hc_port2 = getattr(settings, "port", 8000)
                hc_results.append(f"Backend (:{hc_port2}/health): ❌ unreachable")
        if hc_svc in ("all", "db"):
            db_url = getattr(settings, "database_url", "")
            if db_url:
                try:
                    r = subprocess.run(
                        ["pg_isready", "-d", db_url],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    hc_results.append(
                        f"Database: {'✅ UP' if r.returncode == 0 else '❌ DOWN'}"
                    )
                except Exception:
                    hc_results.append("Database: ❓ pg_isready not available")
            else:
                hc_results.append("Database: (DATABASE_URL not configured)")
        return "\n".join(hc_results) if hc_results else "No services checked"

    def task_progress_h(inp: dict[str, Any]) -> str:
        tprog_task_id = inp.get("task_id")
        tprog_limit = int(inp.get("limit", 10))
        settings = get_settings()
        tp_db = getattr(settings, "database_url", "")
        if not tp_db:
            return "[ERROR] DATABASE_URL not set"
        if tprog_task_id is not None:
            sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks WHERE id = {int(tprog_task_id)} LIMIT 1;"
        else:
            sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks ORDER BY created_at DESC LIMIT {tprog_limit};"
        try:
            r = subprocess.run(
                ["psql", tp_db, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr).strip() or "(no results)"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["cpu_usage"] = cpu_usage_h
    handlers["memory_usage"] = memory_usage_h
    handlers["disk_usage"] = disk_usage_h
    handlers["health_check"] = health_check_h
    handlers["task_progress"] = task_progress_h

    # =========================================================================
    # BATCH 15 — Editing extras (replace_class, undo_changes, generate_patch)
    # =========================================================================

    def replace_class_h(inp: dict[str, Any]) -> str:
        rcl_rel = str(inp["path"])
        rcl_name = str(inp["class_name"])
        rcl_new = str(inp["new_code"])
        if _is_protected_path(rcl_rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rcl_rel}"
        rcl_fp = root / rcl_rel
        if not rcl_fp.exists():
            return f"[ERROR] File not found: {rcl_rel}"
        try:
            rcl_lines = rcl_fp.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception as e:
            return f"[ERROR] {e}"
        rcl_start: int | None = None
        rcl_base_ind = 0
        for rcl_i, rcl_ln in enumerate(rcl_lines):
            s = rcl_ln.strip()
            if (
                s.startswith(f"class {rcl_name}(")
                or s.startswith(f"class {rcl_name}:")
                or s == f"class {rcl_name}"
            ):
                rcl_start = rcl_i
                rcl_base_ind = len(rcl_ln) - len(rcl_ln.lstrip())
                break
        if rcl_start is None:
            return f"[ERROR] Class '{rcl_name}' not found in {rcl_rel}"
        rcl_end = len(rcl_lines)
        for rcl_j in range(rcl_start + 1, len(rcl_lines)):
            rcl_jl = rcl_lines[rcl_j]
            if rcl_jl.strip() == "":
                continue
            rcl_ji = len(rcl_jl) - len(rcl_jl.lstrip())
            if (
                rcl_ji <= rcl_base_ind
                and rcl_jl.strip()
                and not rcl_jl.strip().startswith(("@", "#"))
            ):
                rcl_end = rcl_j
                break
        before = "".join(rcl_lines[:rcl_start])
        after = "".join(rcl_lines[rcl_end:])
        new_final = rcl_new if rcl_new.endswith("\n") else rcl_new + "\n"
        rcl_fp.write_text(before + new_final + after, encoding="utf-8")
        return f"Replaced class '{rcl_name}' in {rcl_rel} (was lines {rcl_start + 1}–{rcl_end})"

    def undo_changes_h(inp: dict[str, Any]) -> str:
        import asyncio
        import uuid as _uuid

        undo_rel = str(inp["path"])
        if _is_protected_path(undo_rel, repo_path):
            return f"[POLICY DENIED] Protected path: {undo_rel}"
        if session is None:
            return "[BLOCKED] undo_changes requires interactive session for safety confirmation"

        settings = get_settings()
        if settings.sentry_environment == "production":
            return (
                "[BLOCKED] undo_changes is disabled in the production environment. "
                "Run migrations in a non-production environment only."
            )

        cmd_preview = f"git checkout -- {undo_rel}"
        action_id = str(_uuid.uuid4())
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    session.request_confirmation(
                        action_id=action_id,
                        description="Discard all uncommitted changes to file",
                        details=cmd_preview,
                    ),
                    loop,
                )
                approved = fut.result(timeout=300)
            else:
                approved = loop.run_until_complete(
                    session.request_confirmation(
                        action_id=action_id,
                        description="Discard all uncommitted changes to file",
                        details=cmd_preview,
                    )
                )
        except Exception as exc:
            return f"[ERROR] Confirmation failed: {exc}"

        if not approved:
            return f"[DENIED] User declined undo_changes for: {undo_rel!r}"

        try:
            r = subprocess.run(
                ["git", "checkout", "--", undo_rel],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                return f"[ERROR] git checkout failed: {out}"
            return f"Restored {undo_rel} to last committed state"
        except Exception as exc:
            return f"[ERROR] {exc}"

    def generate_patch_h(inp: dict[str, Any]) -> str:
        import difflib

        gp_a = str(inp.get("content_a", ""))
        gp_b = str(inp.get("content_b", ""))
        gp_fn = str(inp.get("filename", "file"))
        diff = list(
            difflib.unified_diff(
                gp_a.splitlines(keepends=True),
                gp_b.splitlines(keepends=True),
                fromfile=f"a/{gp_fn}",
                tofile=f"b/{gp_fn}",
            )
        )
        return "".join(diff) if diff else "(no differences)"

    handlers["replace_class"] = replace_class_h
    handlers["undo_changes"] = undo_changes_h
    handlers["generate_patch"] = generate_patch_h

    # =========================================================================
    # BATCH 16 — DB extras (explain_query, run_migration, seed_database)
    # =========================================================================

    def explain_query_h(inp: dict[str, Any]) -> str:
        expq_sql = str(inp["query"]).strip().rstrip(";")
        settings = get_settings()
        expq_db = getattr(settings, "database_url", "")
        if not expq_db:
            return "[ERROR] DATABASE_URL not set"
        full_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {expq_sql};"
        try:
            r = subprocess.run(
                ["psql", expq_db, "-c", full_sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def run_migration_h(inp: dict[str, Any]) -> str:
        import asyncio
        import uuid as _uuid

        if session is None:
            return "[BLOCKED] run_migration requires interactive session for safety confirmation"

        settings = get_settings()
        if settings.sentry_environment == "production":
            return (
                "[BLOCKED] run_migration is disabled in the production environment. "
                "Run migrations in a non-production environment only."
            )

        direction = str(inp.get("direction", "upgrade")).strip()
        revision = str(
            inp.get("revision", "head" if direction == "upgrade" else "-1")
        ).strip()
        if direction not in ("upgrade", "downgrade"):
            return (
                f"[ERROR] direction must be 'upgrade' or 'downgrade', got {direction!r}"
            )

        cmd_args = ["alembic", direction, revision]
        cmd_preview = " ".join(cmd_args)
        action_id = str(_uuid.uuid4())

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    session.request_confirmation(
                        action_id=action_id,
                        description=f"Run Alembic migration: {direction} to {revision}",
                        details=cmd_preview,
                    ),
                    loop,
                )
                approved = fut.result(timeout=300)
            else:
                approved = loop.run_until_complete(
                    session.request_confirmation(
                        action_id=action_id,
                        description=f"Run Alembic migration: {direction} to {revision}",
                        details=cmd_preview,
                    )
                )
        except Exception as exc:
            return f"[ERROR] Confirmation failed: {exc}"

        if not approved:
            return f"[DENIED] User declined run_migration ({cmd_preview})"

        try:
            r = subprocess.run(
                cmd_args,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                return f"[ERROR] alembic {direction} failed:\n{out}"
            return f"Migration complete ({cmd_preview}):\n{out}"
        except Exception as exc:
            return f"[ERROR] {exc}"

    def seed_database_h(inp: dict[str, Any]) -> str:
        import asyncio
        import uuid as _uuid

        if session is None:
            return "[BLOCKED] seed_database requires interactive session for safety confirmation"

        settings = get_settings()
        if settings.sentry_environment == "production":
            return (
                "[BLOCKED] seed_database is disabled in the production environment. "
                "Seeding must only be run in development or staging."
            )

        script = str(inp.get("script", "backend/scripts/seed.py")).strip()
        if not (root / script).exists() and not (Path(repo_path) / script).exists():
            return f"[ERROR] Seed script not found: {script}"

        cmd_preview = f"python {script}"
        action_id = str(_uuid.uuid4())

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    session.request_confirmation(
                        action_id=action_id,
                        description=f"Run database seed script: {script}",
                        details=cmd_preview,
                    ),
                    loop,
                )
                approved = fut.result(timeout=300)
            else:
                approved = loop.run_until_complete(
                    session.request_confirmation(
                        action_id=action_id,
                        description=f"Run database seed script: {script}",
                        details=cmd_preview,
                    )
                )
        except Exception as exc:
            return f"[ERROR] Confirmation failed: {exc}"

        if not approved:
            return f"[DENIED] User declined seed_database ({script})"

        try:
            r = subprocess.run(
                ["python", script],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                return f"[ERROR] seed script failed:\n{out}"
            return f"Seed complete ({script}):\n{out}"
        except Exception as exc:
            return f"[ERROR] {exc}"

    handlers["explain_query"] = explain_query_h
    handlers["run_migration"] = run_migration_h
    handlers["seed_database"] = seed_database_h

    # =========================================================================
    # DAY 3A — Browser tools (Playwright)
    # =========================================================================

    def _browser_sid() -> str:
        return getattr(session, "session_id", None) or "__default__"

    def browser_open_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            result = _bd.browser_open(str(inp["url"]), session_id=_browser_sid())
            if result.get("status") == "blocked":
                return f"[BLOCKED] {result.get('error', 'URL blocked by SSRF guard')}"
            return f"Opened: {result['url']} — title: {result['title']}"
        except Exception as e:
            return f"[ERROR] {e}"

    def browser_navigate_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            result = _bd.browser_navigate(str(inp["url"]), session_id=_browser_sid())
            if "error" in result:
                return f"[BLOCKED] {result['error']}"
            return f"Navigated to: {result['url']} — title: {result['title']}"
        except Exception as e:
            return f"[ERROR] {e}"

    def browser_screenshot_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            path_out = _bd.browser_screenshot(
                inp.get("path"), session_id=_browser_sid()
            )
            return f"Screenshot saved: {path_out}"
        except Exception as e:
            return f"[ERROR] {e}"

    def browser_read_dom_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            return _bd.browser_read_dom(inp.get("selector"), session_id=_browser_sid())
        except Exception as e:
            return f"[ERROR] {e}"

    def browser_click_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            return _bd.browser_click(str(inp["selector"]), session_id=_browser_sid())
        except Exception as e:
            return f"[ERROR] {e}"

    def browser_type_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            return _bd.browser_type(
                str(inp["selector"]), str(inp["text"]), session_id=_browser_sid()
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def browser_close_h(inp: dict[str, Any]) -> str:
        try:
            from app.repo_tools import browser_driver as _bd

            return _bd.browser_close(session_id=_browser_sid())
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["browser_open"] = browser_open_h
    handlers["browser_navigate"] = browser_navigate_h
    handlers["browser_screenshot"] = browser_screenshot_h
    handlers["browser_read_dom"] = browser_read_dom_h
    handlers["browser_click"] = browser_click_h
    handlers["browser_type"] = browser_type_h
    handlers["browser_close"] = browser_close_h

    # =========================================================================
    # DAY 3B — Memory tools (flat JSON files per repo slug)
    # =========================================================================

    import json as _json_mem
    import hashlib as _hlib
    import fcntl as _fcntl

    _mem_slug = _hlib.md5(repo_path.encode()).hexdigest()[:8]
    _mem_dir = Path(__file__).parent.parent / "memory"
    _mem_dir.mkdir(exist_ok=True)
    _mem_store_path = _mem_dir / f"{_mem_slug}_store.json"
    _mem_decisions_path = _mem_dir / f"{_mem_slug}_decisions.jsonl"
    _mem_issues_path = _mem_dir / f"{_mem_slug}_known_issues.md"

    def _read_mem_store() -> dict[str, str]:
        if not _mem_store_path.exists():
            return {}
        try:
            return dict(_json_mem.loads(_mem_store_path.read_text(encoding="utf-8")))
        except Exception:
            return {}

    def _write_mem_store(store: dict[str, str]) -> None:
        with open(_mem_store_path, "w", encoding="utf-8") as _fh:
            _fcntl.flock(_fh, _fcntl.LOCK_EX)
            _json_mem.dump(store, _fh, indent=2)
            _fcntl.flock(_fh, _fcntl.LOCK_UN)

    def memory_read_h(inp: dict[str, Any]) -> str:
        key = str(inp["key"])
        store = _read_mem_store()
        val = store.get(key)
        return val if val is not None else f"(key '{key}' not found in memory)"

    def memory_write_h(inp: dict[str, Any]) -> str:
        key = str(inp["key"])
        value = str(inp["value"])
        store = _read_mem_store()
        store[key] = value
        _write_mem_store(store)
        return f"Memory written: {key}"

    def decision_log_append_h(inp: dict[str, Any]) -> str:
        import datetime as _dt

        entry = {
            "timestamp": _dt.datetime.utcnow().isoformat(),
            "decision": str(inp["decision"]),
            "reason": str(inp["reason"]),
            "alternatives": str(inp.get("alternatives", "")),
        }
        try:
            with open(_mem_decisions_path, "a", encoding="utf-8") as _fh:
                _fcntl.flock(_fh, _fcntl.LOCK_EX)
                _fh.write(_json_mem.dumps(entry) + "\n")
                _fcntl.flock(_fh, _fcntl.LOCK_UN)
            return f"Decision logged: {entry['decision'][:80]}"
        except Exception as e:
            return f"[ERROR] {e}"

    task_history_query_h = task_history_query

    def known_issues_read_h(inp: dict[str, Any]) -> str:
        if not _mem_issues_path.exists():
            return "(no known issues file yet)"
        return _mem_issues_path.read_text(encoding="utf-8")

    def known_issues_write_h(inp: dict[str, Any]) -> str:
        import datetime as _dt

        issue = str(inp["issue"])
        severity = str(inp.get("severity", "medium")).upper()
        line = (
            f"\n## [{severity}] {_dt.datetime.utcnow().strftime('%Y-%m-%d')}\n{issue}\n"
        )
        try:
            with open(_mem_issues_path, "a", encoding="utf-8") as _fh:
                _fcntl.flock(_fh, _fcntl.LOCK_EX)
                _fh.write(line)
                _fcntl.flock(_fh, _fcntl.LOCK_UN)
            return f"Known issue appended (severity: {severity})"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["memory_read"] = memory_read_h
    handlers["memory_write"] = memory_write_h
    handlers["decision_log_append"] = decision_log_append_h
    handlers["task_history_query"] = task_history_query_h
    handlers["known_issues_read"] = known_issues_read_h
    handlers["known_issues_write"] = known_issues_write_h

    # =========================================================================
    # DAY 3C — Planning + docs tools
    # =========================================================================

    def estimate_complexity_h(inp: dict[str, Any]) -> str:
        description = str(inp.get("description", ""))
        context_paths = list(inp.get("context_paths", []))
        word_count = len(description.split())
        file_count = len(context_paths)
        score = word_count + file_count * 10
        if score < 30:
            size = "XS"
        elif score < 80:
            size = "S"
        elif score < 200:
            size = "M"
        elif score < 500:
            size = "L"
        else:
            size = "XL"
        return f"Estimated complexity: {size} (word_count={word_count}, context_files={file_count}, score={score})"

    def summarize_folder_h(inp: dict[str, Any]) -> str:
        sf_path = str(inp.get("path", "."))
        exts = set(inp.get("extensions", [".py", ".ts", ".tsx"]))
        results: list[str] = []
        folder = root / sf_path
        if not folder.exists():
            return f"[ERROR] Path not found: {sf_path}"
        count = 0
        for fp in sorted(folder.rglob("*")):
            if not fp.is_file():
                continue
            if fp.suffix not in exts:
                continue
            if count >= 20:
                results.append("(truncated — 20 file limit)")
                break
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                n_lines = len(lines)
                n_funcs = sum(
                    1
                    for ln in lines
                    if ln.strip().startswith("def ")
                    or ln.strip().startswith("async def ")
                )
                n_classes = sum(1 for ln in lines if ln.strip().startswith("class "))
                rel = fp.relative_to(root)
                results.append(
                    f"**{rel}** — {n_lines} lines, {n_funcs} functions, {n_classes} classes"
                )
            except Exception as e:
                results.append(f"[ERROR reading {fp.name}] {e}")
            count += 1
        return "\n".join(results) if results else "(no matching files)"

    def generate_api_docs_text_h(inp: dict[str, Any]) -> str:
        import re as _re_docs

        route_path = str(inp["route_path"])
        fp = root / route_path
        if not fp.exists():
            return f"[ERROR] File not found: {route_path}"
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] {e}"
        lines = text.splitlines()
        endpoints: list[str] = []
        for i, line in enumerate(lines):
            m = _re_docs.match(
                r'\s*@\w+\.(get|post|put|patch|delete|options|head)\s*\("([^"]+)"', line
            )
            if m:
                method = m.group(1).upper()
                path_val = m.group(2)
                # Find the next def line
                func_name = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    fm = _re_docs.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[j])
                    if fm:
                        func_name = fm.group(1)
                        break
                endpoints.append(
                    f"### {method} {path_val}\n**Function:** `{func_name}`\n\n**Description:** _TODO_\n\n**Request:** _TODO_\n\n**Response:** _TODO_\n"
                )
        if not endpoints:
            return "(no FastAPI route decorators found)"
        return "\n".join(endpoints)

    def mermaid_from_schema_h(inp: dict[str, Any]) -> str:
        import subprocess as _sp_merm
        from app.config import get_settings as _gs_merm

        settings = _gs_merm()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        tbl = inp.get("table")
        sql = f"\\d {tbl}" if tbl else "\\dt+"
        try:
            r = _sp_merm.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            raw = (r.stdout + r.stderr).strip()
        except Exception as e:
            return f"[ERROR] {e}"
        # Build a basic Mermaid erDiagram from psql table listing
        lines = ["```mermaid", "erDiagram"]
        for row in raw.splitlines():
            parts = row.split("|")
            if len(parts) >= 2:
                tname = parts[1].strip()
                if (
                    tname
                    and not tname.startswith("-")
                    and tname not in ("Name", "Schema")
                ):
                    lines.append(f"    {tname} {{")
                    lines.append("        string id")
                    lines.append("    }")
        lines.append("```")
        return "\n".join(lines) if len(lines) > 3 else f"(raw schema)\n{raw}"

    handlers["estimate_complexity"] = estimate_complexity_h
    handlers["summarize_folder"] = summarize_folder_h
    handlers["generate_api_docs_text"] = generate_api_docs_text_h
    handlers["mermaid_from_schema"] = mermaid_from_schema_h

    # =========================================================================
    # DAY 3G — MCP / External integrations
    # =========================================================================

    import subprocess as _sp_mcp
    import os as _os_mcp

    def github_create_issue_h(inp: dict[str, Any]) -> str:
        title = str(inp["title"])
        body = str(inp["body"])
        labels = list(inp.get("labels", []))
        cmd = ["gh", "issue", "create", "--title", title, "--body", body]
        for lbl in labels:
            cmd += ["--label", lbl]
        try:
            r = _sp_mcp.run(
                cmd, capture_output=True, text=True, cwd=str(root), timeout=30
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found — install GitHub CLI"
        except Exception as e:
            return f"[ERROR] {e}"

    def github_list_prs_h(inp: dict[str, Any]) -> str:
        state = str(inp.get("state", "open"))
        try:
            r = _sp_mcp.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    state,
                    "--json",
                    "number,title,state,author",
                ],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def github_comment_h(inp: dict[str, Any]) -> str:
        number = int(inp["number"])
        body = str(inp["body"])
        kind = str(inp.get("kind", "issue"))
        subcmd = "pr" if kind == "pr" else "issue"
        try:
            r = _sp_mcp.run(
                ["gh", subcmd, "comment", str(number), "--body", body],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "Comment posted"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def linear_create_issue_h(inp: dict[str, Any]) -> str:
        import urllib.request as _ur_li
        import urllib.error as _ue_li

        api_key = _os_mcp.environ.get("LINEAR_API_KEY", "")
        if not api_key:
            return "[ERROR] LINEAR_API_KEY not set"
        title = str(inp["title"])
        description = str(inp["description"])
        team_key = str(inp["team_key"])
        # First resolve team key → team ID
        query = '{"query": "query { teams { nodes { id key } } }"}'
        try:
            req = _ur_li.Request(
                "https://api.linear.app/graphql",
                data=query.encode(),
                headers={"Content-Type": "application/json", "Authorization": api_key},
            )
            with _ur_li.urlopen(req, timeout=10) as resp:
                data = __import__("json").loads(resp.read())
            teams = data.get("data", {}).get("teams", {}).get("nodes", [])
            team_id = next((t["id"] for t in teams if t["key"] == team_key), None)
            if not team_id:
                return f"[ERROR] Team '{team_key}' not found in Linear"
            mut = __import__("json").dumps(
                {
                    "query": "mutation($title: String!, $desc: String!, $tid: String!) { issueCreate(input: {title: $title, description: $desc, teamId: $tid}) { issue { id identifier title } } }",
                    "variables": {"title": title, "desc": description, "tid": team_id},
                }
            )
            req2 = _ur_li.Request(
                "https://api.linear.app/graphql",
                data=mut.encode(),
                headers={"Content-Type": "application/json", "Authorization": api_key},
            )
            with _ur_li.urlopen(req2, timeout=10) as resp2:
                data2 = __import__("json").loads(resp2.read())
            issue = data2.get("data", {}).get("issueCreate", {}).get("issue", {})
            return f"Linear issue created: {issue.get('identifier', '?')} — {issue.get('title', title)}"
        except _ue_li.HTTPError as e:
            return f"[ERROR] Linear API {e.code}: {e.read().decode()[:200]}"
        except Exception as e:
            return f"[ERROR] {e}"

    def slack_send_message_h(inp: dict[str, Any]) -> str:
        import urllib.request as _ur_sl
        import urllib.error as _ue_sl

        webhook_url = _os_mcp.environ.get("SLACK_WEBHOOK_URL", "")
        if not webhook_url:
            return "[ERROR] SLACK_WEBHOOK_URL not set"
        text = str(inp["text"])
        payload = __import__("json").dumps({"text": text}).encode()
        try:
            req = _ur_sl.Request(
                webhook_url, data=payload, headers={"Content-Type": "application/json"}
            )
            with _ur_sl.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
            return f"Slack message sent: {body}"
        except _ue_sl.HTTPError as e:
            return f"[ERROR] Slack webhook {e.code}: {e.read().decode()[:200]}"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["github_create_issue"] = github_create_issue_h
    handlers["github_list_prs"] = github_list_prs_h
    handlers["github_comment"] = github_comment_h
    handlers["linear_create_issue"] = linear_create_issue_h
    handlers["slack_send_message"] = slack_send_message_h

    # ── Day 2 Gap handlers ─────────────────────────────────────────────────────

    def find_queue_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        patterns = [  # noqa: F841
            r"asyncio\.Queue",
            r"class.*Queue",
            r"BullMQ\|rq\.Queue\|celery\|dramatiq\|huey",
            r"Queue\(",
        ]
        results: list[str] = []
        try:
            pat = (
                r"asyncio\.Queue|class.*Queue|rq\.Queue|Queue\(|BullMQ|celery|dramatiq"
            )
            out = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.js",
                    "-E",
                    pat,
                    _rp,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = out.stdout.strip().splitlines()
            results = [
                ln for ln in lines if ".venv/" not in ln and "node_modules/" not in ln
            ][:30]
        except Exception as e:
            return f"[ERROR] find_queue: {e}"
        if not results:
            return "No queue patterns found."
        return "\n".join(results)

    def find_worker_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        try:
            pat = r"class.*Worker|@worker|celery\.task|\.delay\(|rq.*worker|dramatiq\.actor|Consumer"
            out = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.js",
                    "-E",
                    pat,
                    _rp,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = out.stdout.strip().splitlines()
            results = [
                ln for ln in lines if ".venv/" not in ln and "node_modules/" not in ln
            ][:30]
        except Exception as e:
            return f"[ERROR] find_worker: {e}"
        if not results:
            return "No worker patterns found."
        return "\n".join(results)

    def insert_before_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        pattern = str(inp["pattern"])
        content = str(inp["content"])
        fpath = root / path
        if _is_protected_path(path, repo_path):
            return f"[BLOCKED] {path} is a protected path"
        try:
            import re as _re_ib

            lines = fpath.read_text(encoding="utf-8").splitlines(keepends=True)
            new_lines: list[str] = []
            inserted = False
            for line in lines:
                if not inserted and _re_ib.search(pattern, line):
                    new_lines.append(
                        content if content.endswith("\n") else content + "\n"
                    )
                    inserted = True
                new_lines.append(line)
            if not inserted:
                return f"[WARN] Pattern '{pattern}' not found in {path}"
            fpath.write_text("".join(new_lines), encoding="utf-8")
            return f"Inserted {len(content.splitlines())} line(s) before pattern '{pattern}' in {path}"
        except Exception as e:
            return f"[ERROR] insert_before: {e}"

    def insert_after_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        pattern = str(inp["pattern"])
        content = str(inp["content"])
        fpath = root / path
        if _is_protected_path(path, repo_path):
            return f"[BLOCKED] {path} is a protected path"
        try:
            import re as _re_ia

            lines = fpath.read_text(encoding="utf-8").splitlines(keepends=True)
            new_lines: list[str] = []
            inserted = False
            for line in lines:
                new_lines.append(line)
                if not inserted and _re_ia.search(pattern, line):
                    new_lines.append(
                        content if content.endswith("\n") else content + "\n"
                    )
                    inserted = True
            if not inserted:
                return f"[WARN] Pattern '{pattern}' not found in {path}"
            fpath.write_text("".join(new_lines), encoding="utf-8")
            return f"Inserted {len(content.splitlines())} line(s) after pattern '{pattern}' in {path}"
        except Exception as e:
            return f"[ERROR] insert_after: {e}"

    def delete_block_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        start_pat = str(inp["start_pattern"])
        end_pat = str(inp["end_pattern"])
        fpath = root / path
        if _is_protected_path(path, repo_path):
            return f"[BLOCKED] {path} is a protected path"
        try:
            import re as _re_db

            lines = fpath.read_text(encoding="utf-8").splitlines(keepends=True)
            new_lines: list[str] = []
            in_block = False
            deleted = 0
            for line in lines:
                if not in_block and _re_db.search(start_pat, line):
                    in_block = True
                    deleted += 1
                    continue
                if in_block:
                    deleted += 1
                    if _re_db.search(end_pat, line):
                        in_block = False
                    continue
                new_lines.append(line)
            if deleted == 0:
                return f"[WARN] Block pattern not found in {path}"
            fpath.write_text("".join(new_lines), encoding="utf-8")
            return f"Deleted {deleted} lines between '{start_pat}' and '{end_pat}' in {path}"
        except Exception as e:
            return f"[ERROR] delete_block: {e}"

    def generate_changelog_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        from_ref = str(inp.get("from_ref", ""))
        to_ref = str(inp.get("to_ref", "HEAD"))
        try:
            if not from_ref:
                tags = subprocess.run(
                    ["git", "-C", _rp, "tag", "--sort=-version:refname"],
                    capture_output=True,
                    text=True,
                )
                tag_list = [t for t in tags.stdout.strip().splitlines() if t]
                from_ref = (
                    tag_list[1]
                    if len(tag_list) >= 2
                    else tag_list[0] if tag_list else ""
                )
            ref_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
            log = subprocess.run(
                [
                    "git",
                    "-C",
                    _rp,
                    "log",
                    ref_range,
                    "--pretty=format:%s (%an)",
                    "--no-merges",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            commits = log.stdout.strip().splitlines()
            if not commits:
                return f"No commits found between {from_ref or 'start'} and {to_ref}"
            sections: dict[str, list[str]] = {
                "Added": [],
                "Changed": [],
                "Fixed": [],
                "Other": [],
            }
            for c in commits:
                cl = c.lower()
                if cl.startswith(("feat:", "add ", "new ")):
                    sections["Added"].append(f"- {c}")
                elif cl.startswith(("fix:", "bug ", "patch ")):
                    sections["Fixed"].append(f"- {c}")
                elif cl.startswith(("refactor:", "chore:", "update ", "change ")):
                    sections["Changed"].append(f"- {c}")
                else:
                    sections["Other"].append(f"- {c}")
            import datetime as _dt

            lines_out = [
                f"## [Unreleased] — {_dt.date.today().isoformat()}",
                f"Changes from {from_ref or 'start'} to {to_ref}",
                "",
            ]
            for sec, items in sections.items():
                if items:
                    lines_out.append(f"### {sec}")
                    lines_out.extend(items)
                    lines_out.append("")
            return "\n".join(lines_out)
        except Exception as e:
            return f"[ERROR] generate_changelog: {e}"

    def summarize_repo_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        try:
            import os as _os_sr

            # File tree (3 levels)
            tree_lines: list[str] = []
            for dirpath, dirnames, filenames in _os_sr.walk(_rp):
                dirnames[:] = [
                    d
                    for d in sorted(dirnames)
                    if d not in (".git", ".venv", "node_modules", "__pycache__")
                ]
                depth = dirpath.replace(_rp, "").count(_os_sr.sep)
                if depth > 2:
                    continue
                indent = "  " * depth
                tree_lines.append(f"{indent}{_os_sr.path.basename(dirpath)}/")
                if depth < 2:
                    for f in sorted(filenames)[:10]:
                        tree_lines.append(f"{indent}  {f}")

            # Line counts by extension
            ext_counts: dict[str, int] = {}
            total_files = 0
            for dirpath, dirnames, filenames in _os_sr.walk(_rp):
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in (".git", ".venv", "node_modules", "__pycache__")
                ]
                for fname in filenames:
                    ext = _os_sr.path.splitext(fname)[1] or "other"
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    total_files += 1

            top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:8]

            # README excerpt
            readme_excerpt = ""
            for rname in ("README.md", "readme.md", "README.rst"):
                rpath = _os_sr.path.join(_rp, rname)
                if _os_sr.path.exists(rpath):
                    with open(rpath, encoding="utf-8", errors="ignore") as rf:
                        readme_excerpt = rf.read(800)
                    break

            summary = [
                f"## Repository Summary: {_os_sr.path.basename(_rp)}",
                f"Total files: {total_files}",
                "",
                "### Top file types",
            ]
            for ext, count in top_exts:
                summary.append(f"  {ext:10} {count}")
            summary += ["", "### Directory tree (3 levels)"] + tree_lines[:50]
            if readme_excerpt:
                summary += ["", "### README (first 800 chars)", readme_excerpt]
            return "\n".join(summary)
        except Exception as e:
            return f"[ERROR] summarize_repo: {e}"

    def generate_release_notes_h(inp: dict[str, Any]) -> str:
        version = str(inp["version"])
        _rp = str(inp.get("repo_path", repo_path))
        from_ref = str(inp.get("from_ref", ""))
        try:
            if not from_ref:
                tags = subprocess.run(
                    ["git", "-C", _rp, "tag", "--sort=-version:refname"],
                    capture_output=True,
                    text=True,
                )
                tag_list = [t for t in tags.stdout.strip().splitlines() if t]
                from_ref = tag_list[0] if tag_list else ""
            ref_range = f"{from_ref}..HEAD" if from_ref else "HEAD"
            log = subprocess.run(
                [
                    "git",
                    "-C",
                    _rp,
                    "log",
                    ref_range,
                    "--pretty=format:* %s",
                    "--no-merges",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            commits = log.stdout.strip()
            import datetime as _dt_rn

            notes = [
                f"# Release Notes — {version}",
                f"Released: {_dt_rn.date.today().isoformat()}",
                "",
                "## What's Changed",
                "",
                commits or "No commits found.",
                "",
                f"**Full Changelog:** {from_ref}...{version}" if from_ref else "",
            ]
            return "\n".join(notes)
        except Exception as e:
            return f"[ERROR] generate_release_notes: {e}"

    def read_pdf_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        max_pages = int(inp.get("max_pages", 20))
        fpath = Path(path) if Path(path).is_absolute() else root / path
        try:
            import pdfplumber as _pp

            pages_text: list[str] = []
            with _pp.open(str(fpath)) as pdf:
                for i, page in enumerate(pdf.pages[:max_pages]):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages_text.append(f"--- Page {i + 1} ---\n{text.strip()}")
            if not pages_text:
                return f"[WARN] No text extracted from {fpath} (may be image-only PDF)"
            return "\n\n".join(pages_text)
        except ImportError:
            return (
                "[ERROR] pdfplumber not installed. Run: pip install pdfplumber==0.11.10"
            )
        except Exception as e:
            return f"[ERROR] read_pdf: {e}"

    def read_image_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        fpath = Path(path) if Path(path).is_absolute() else root / path
        try:
            from PIL import Image as _PilImg
            import base64 as _b64
            import io as _io_img

            img = _PilImg.open(str(fpath))
            meta = {
                "format": img.format,
                "mode": img.mode,
                "size": f"{img.width}x{img.height}",
                "path": str(fpath),
            }
            # Generate a small thumbnail as base64 for inspection
            thumb = img.copy()
            thumb.thumbnail((256, 256))
            buf = _io_img.BytesIO()
            thumb.save(buf, format="PNG")
            b64_thumb = _b64.b64encode(buf.getvalue()).decode()
            return (
                f"Image: {meta['path']}\n"
                f"Format: {meta['format']} | Mode: {meta['mode']} | Size: {meta['size']}\n"
                f"Thumbnail (base64 PNG, 256x256): {b64_thumb[:200]}…"
            )
        except Exception as e:
            return f"[ERROR] read_image: {e}"

    def github_create_pr_h(inp: dict[str, Any]) -> str:
        title = str(inp["title"])
        body = str(inp["body"])
        base = str(inp.get("base", "main"))
        draft = bool(inp.get("draft", False))
        try:
            cmd = [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base,
            ]
            if draft:
                cmd.append("--draft")
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, cwd=repo_path
            )
            if out.returncode != 0:
                return f"[ERROR] gh pr create failed: {out.stderr[:400]}"
            return f"PR created: {out.stdout.strip()}"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found. Install: https://cli.github.com/"
        except Exception as e:
            return f"[ERROR] github_create_pr: {e}"

    handlers["find_queue"] = find_queue_h
    handlers["find_worker"] = find_worker_h
    handlers["insert_before"] = insert_before_h
    handlers["insert_after"] = insert_after_h
    handlers["delete_block"] = delete_block_h
    handlers["generate_changelog"] = generate_changelog_h
    handlers["summarize_repo"] = summarize_repo_h
    handlers["generate_release_notes"] = generate_release_notes_h
    handlers["read_pdf"] = read_pdf_h
    handlers["read_image"] = read_image_h
    handlers["github_create_pr"] = github_create_pr_h

    # ---- Batch 15 handlers ----

    def git_tag_h(inp: dict[str, Any]) -> str:
        action = str(inp.get("action", "list"))
        name = str(inp.get("name", ""))
        msg = str(inp.get("message", ""))
        try:
            if action == "list":
                r = subprocess.run(
                    ["git", "tag", "--sort=-creatordate"],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=15,
                )
                return r.stdout.strip() or "(no tags)"
            if action == "create":
                cmd = (
                    ["git", "tag", "-a", name, "-m", msg]
                    if msg
                    else ["git", "tag", name]
                )
                r = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=repo_path, timeout=15
                )
                return (
                    r.stdout.strip() or f"Tag '{name}' created"
                    if r.returncode == 0
                    else f"[ERROR] {r.stderr.strip()}"
                )
            if action == "delete":
                r = subprocess.run(
                    ["git", "tag", "-d", name],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=15,
                )
                return (
                    r.stdout.strip() or f"Tag '{name}' deleted"
                    if r.returncode == 0
                    else f"[ERROR] {r.stderr.strip()}"
                )
            return "[ERROR] Unknown action"
        except Exception as e:
            return f"[ERROR] git_tag: {e}"

    def git_log_file_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        limit = int(inp.get("limit", 10))
        try:
            r = subprocess.run(
                ["git", "log", f"--max-count={limit}", "--oneline", "--", path],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=15,
            )
            return r.stdout.strip() or f"(no commits found for {path})"
        except Exception as e:
            return f"[ERROR] git_log_file: {e}"

    def semver_bump_h(inp: dict[str, Any]) -> str:
        import re as _re

        part = str(inp["part"])
        version_file = str(inp.get("file", ""))
        candidates = (
            [version_file]
            if version_file
            else ["pyproject.toml", "package.json", "VERSION"]
        )
        for cand in candidates:
            fp = root / cand if cand else None
            if fp and fp.exists():
                text = fp.read_text(encoding="utf-8")
                pattern = r'(version\s*[=:]\s*["\']?)(\d+)\.(\d+)\.(\d+)(["\']?)'
                m = _re.search(pattern, text)
                if m:
                    major, minor, patch_v = (
                        int(m.group(2)),
                        int(m.group(3)),
                        int(m.group(4)),
                    )
                    if part == "major":
                        major, minor, patch_v = major + 1, 0, 0
                    elif part == "minor":
                        minor, patch_v = minor + 1, 0
                    else:
                        patch_v += 1
                    new_ver = f"{major}.{minor}.{patch_v}"
                    new_text = _re.sub(
                        pattern,
                        lambda x: f"{x.group(1)}{new_ver}{x.group(5)}",
                        text,
                        count=1,
                    )
                    fp.write_text(new_text, encoding="utf-8")
                    return f"Bumped version to {new_ver} in {cand}"
        return "[ERROR] No version file found (tried pyproject.toml, package.json, VERSION)"

    def git_stash_list_h(inp: dict[str, Any]) -> str:
        try:
            r = subprocess.run(
                ["git", "stash", "list"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=15,
            )
            return r.stdout.strip() or "(no stashes)"
        except Exception as e:
            return f"[ERROR] git_stash_list: {e}"

    def list_processes_h(inp: dict[str, Any]) -> str:
        name_filter = str(inp.get("filter", ""))
        try:
            r = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=10
            )
            lines = r.stdout.strip().splitlines()
            if name_filter:
                lines = [
                    ln
                    for ln in lines
                    if name_filter.lower() in ln.lower() or ln.startswith("USER")
                ]
            return "\n".join(lines[:50])
        except Exception as e:
            return f"[ERROR] list_processes: {e}"

    def list_open_ports_h(inp: dict[str, Any]) -> str:
        try:
            r = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                r = subprocess.run(
                    ["netstat", "-tlnp"], capture_output=True, text=True, timeout=10
                )
            return r.stdout.strip() or "(no open ports found)"
        except Exception as e:
            return f"[ERROR] list_open_ports: {e}"

    def wait_for_port_h(inp: dict[str, Any]) -> str:
        import socket as _socket
        import time as _time

        port = int(inp["port"])
        host = str(inp.get("host", "localhost"))
        timeout = int(inp.get("timeout", 30))
        start = _time.time()
        while _time.time() - start < timeout:
            try:
                with _socket.create_connection((host, port), timeout=1):
                    elapsed = round(_time.time() - start, 2)
                    return f"Port {host}:{port} is open (waited {elapsed}s)"
            except (ConnectionRefusedError, OSError):
                _time.sleep(0.5)
        return f"[TIMEOUT] Port {host}:{port} not open after {timeout}s"

    def check_url_status_h(inp: dict[str, Any]) -> str:
        import urllib.request as _req
        import time as _time

        url = str(inp["url"])
        try:
            start = _time.time()
            r = _req.urlopen(url, timeout=10)
            elapsed = round((_time.time() - start) * 1000)
            return f"HTTP {r.status} {r.reason} ({elapsed}ms) — {url}"
        except Exception as e:
            return f"[ERROR] check_url_status {url}: {e}"

    def cpu_profile_h(inp: dict[str, Any]) -> str:
        command = str(inp["command"])
        top = int(inp.get("top", 20))
        try:
            profiled = f"python -m cProfile -s cumulative -c 'import subprocess; subprocess.run({command!r}.split(), check=True)'"  # noqa: F841
            r = subprocess.run(
                ["python", "-m", "cProfile", "-s", "cumulative"] + command.split()[1:],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=60,
            )
            lines = (r.stdout + r.stderr).strip().splitlines()
            return "\n".join(lines[: top + 10])
        except Exception as e:
            return f"[ERROR] cpu_profile: {e}"

    def zip_files_h(inp: dict[str, Any]) -> str:
        import zipfile as _zf

        source = str(inp["source"])
        src_path = root / source
        output = str(inp.get("output", source.rstrip("/") + ".zip"))
        out_path = root / output
        try:
            with _zf.ZipFile(str(out_path), "w", _zf.ZIP_DEFLATED) as zf:
                if src_path.is_dir():
                    for f in src_path.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(root))
                else:
                    zf.write(src_path, src_path.relative_to(root))
            return f"Zipped to {output}"
        except Exception as e:
            return f"[ERROR] zip_files: {e}"

    def unzip_files_h(inp: dict[str, Any]) -> str:
        import zipfile as _zf

        archive = str(inp["archive"])
        dest = str(inp.get("dest", str((root / archive).parent)))
        arc_path = root / archive
        dest_path = root / dest if not (root / dest).is_absolute() else Path(dest)
        try:
            with _zf.ZipFile(str(arc_path), "r") as zf:
                zf.extractall(str(dest_path))
            return f"Extracted {archive} to {dest}"
        except Exception as e:
            return f"[ERROR] unzip_files: {e}"

    def move_file_h(inp: dict[str, Any]) -> str:
        import shutil as _shutil

        src = root / str(inp["source"])
        dst = root / str(inp["dest"])
        if _is_protected_path(str(inp["dest"]), repo_path):
            return f"[POLICY DENIED] Cannot move to protected path: {inp['dest']}"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            _shutil.move(str(src), str(dst))
            return f"Moved {inp['source']} → {inp['dest']}"
        except Exception as e:
            return f"[ERROR] move_file: {e}"

    def hash_file_h(inp: dict[str, Any]) -> str:
        import hashlib as _hl

        fpath = root / str(inp["path"])
        try:
            h = _hl.sha256()
            with open(fpath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return f"SHA-256 {inp['path']}: {h.hexdigest()}"
        except Exception as e:
            return f"[ERROR] hash_file: {e}"

    def count_lines_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        pattern = str(inp.get("pattern", "**/*"))
        target = root / path
        try:
            if target.is_file():
                count = sum(1 for _ in target.open(encoding="utf-8", errors="ignore"))
                return f"{path}: {count} lines"
            totals: dict[str, int] = {}
            for fp in target.glob(pattern):
                if fp.is_file():
                    ext = fp.suffix or "(no ext)"
                    n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                    totals[ext] = totals.get(ext, 0) + n
            rows = sorted(totals.items(), key=lambda x: -x[1])
            lines_out = "\n".join(f"{ext}: {n:,}" for ext, n in rows)
            return f"Lines by extension in {path}:\n{lines_out}\nTotal: {sum(totals.values()):,}"
        except Exception as e:
            return f"[ERROR] count_lines: {e}"

    def read_env_var_h(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        val = os.environ.get(name)
        return f"{name}={val}" if val is not None else f"{name}=[NOT SET]"

    def list_env_vars_h(inp: dict[str, Any]) -> str:
        names = sorted(os.environ.keys())
        return "\n".join(names)

    def env_diff_h(inp: dict[str, Any]) -> str:
        example_path = root / str(inp.get("example", ".env.example"))
        actual_path = root / str(inp.get("actual", ".env"))

        def _keys(fp: Path) -> set[str]:
            if not fp.exists():
                return set()
            keys: set[str] = set()
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    keys.add(line.split("=", 1)[0].strip())
            return keys

        example_keys = _keys(example_path)
        actual_keys = _keys(actual_path)
        missing = sorted(example_keys - actual_keys)
        extra = sorted(actual_keys - example_keys)
        lines = []
        if missing:
            lines.append(f"Missing in {inp.get('actual', '.env')} ({len(missing)}):")
            lines.extend(f"  - {k}" for k in missing)
        if extra:
            lines.append(
                f"Extra in {inp.get('actual', '.env')} (not in example, {len(extra)}):"
            )
            lines.extend(f"  + {k}" for k in extra)
        if not missing and not extra:
            lines.append("✅ No differences — .env matches .env.example")
        return "\n".join(lines)

    def json_query_h(inp: dict[str, Any]) -> str:
        fpath = root / str(inp["path"])
        query = str(inp["query"])
        try:
            r = subprocess.run(
                ["jq", query, str(fpath)], capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                return f"[ERROR] jq: {r.stderr.strip()}"
            return r.stdout.strip()
        except FileNotFoundError:
            import json as _json

            data = _json.loads(fpath.read_text(encoding="utf-8"))
            return f"(jq not installed) Raw JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        except Exception as e:
            return f"[ERROR] json_query: {e}"

    def yaml_validate_h(inp: dict[str, Any]) -> str:
        fpath = root / str(inp["path"])
        try:
            import yaml as _yaml

            with open(fpath, encoding="utf-8") as f:
                _yaml.safe_load(f)
            return f"✅ {inp['path']} is valid YAML"
        except ImportError:
            subprocess.run(
                ["python", "-c", f"import yaml; yaml.safe_load(open('{fpath}'))"],
                capture_output=True,
            )
            return "(pyyaml not available in this environment)"
        except Exception as e:
            return f"[INVALID YAML] {inp['path']}: {e}"

    def json_validate_h(inp: dict[str, Any]) -> str:
        import json as _json

        fpath = root / str(inp["path"])
        try:
            _json.loads(fpath.read_text(encoding="utf-8"))
            return f"✅ {inp['path']} is valid JSON"
        except Exception as e:
            return f"[INVALID JSON] {inp['path']}: {e}"

    def csv_preview_h(inp: dict[str, Any]) -> str:
        import csv as _csv

        fpath = root / str(inp["path"])
        rows_n = int(inp.get("rows", 5))
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                reader = _csv.reader(f)
                rows: list[list[str]] = []
                for i, row in enumerate(reader):
                    if i > rows_n:
                        break
                    rows.append(row)
            if not rows:
                return "(empty CSV)"
            header = rows[0]
            out = ["Columns: " + ", ".join(header)]
            for row in rows[1:]:
                out.append(" | ".join(row))
            return "\n".join(out)
        except Exception as e:
            return f"[ERROR] csv_preview: {e}"

    def generate_diagram_h(inp: dict[str, Any]) -> str:
        description = str(inp["description"])
        kind = str(inp.get("kind", "flowchart"))
        templates = {
            "flowchart": f"flowchart TD\n    %% {description}\n    A[Start] --> B[Process]\n    B --> C{{Decision}}\n    C -->|Yes| D[End]\n    C -->|No| B",
            "sequence": f"sequenceDiagram\n    %% {description}\n    participant A\n    participant B\n    A->>B: Request\n    B-->>A: Response",
            "erDiagram": f"erDiagram\n    %% {description}\n    ENTITY1 {{string id}}\n    ENTITY2 {{string id}}\n    ENTITY1 ||--o{{ ENTITY2 : has",
            "classDiagram": f"classDiagram\n    %% {description}\n    class MyClass {{\n        +String name\n        +method()\n    }}",
        }
        mermaid = templates.get(kind, templates["flowchart"])
        return f"```mermaid\n{mermaid}\n```\n\nNote: Customize the template above to match your actual {kind} structure."

    def export_markdown_h(inp: dict[str, Any]) -> str:
        fpath = root / str(inp["path"])
        output_name = str(inp.get("output", str(inp["path"]).replace(".md", ".html")))
        out_path = root / output_name
        try:
            text = fpath.read_text(encoding="utf-8")
            try:
                import markdown as _md

                html = _md.markdown(text, extensions=["fenced_code", "tables"])
            except ImportError:
                html = f"<pre>{text}</pre>"
            out_path.write_text(
                f"<!DOCTYPE html><html><body>{html}</body></html>", encoding="utf-8"
            )
            return f"Exported to {output_name}"
        except Exception as e:
            return f"[ERROR] export_markdown: {e}"

    def find_unused_imports_h(inp: dict[str, Any]) -> str:
        path = str(inp.get("path", "."))
        target = str(root / path)
        try:
            r = subprocess.run(
                ["python", "-m", "ruff", "check", "--select=F401", target],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=30,
            )
            return r.stdout.strip() or "✅ No unused imports found"
        except Exception as e:
            return f"[ERROR] find_unused_imports: {e}"

    def deps_outdated_h(inp: dict[str, Any]) -> str:
        manager = str(inp.get("manager", "auto"))
        directory = str(inp.get("directory", "."))
        target_dir = str(root / directory)
        if manager == "auto":
            has_pip = (root / "requirements.txt").exists() or (
                root / "pyproject.toml"
            ).exists()
            has_npm = (root / "package.json").exists()  # noqa: F841
            manager = "pip" if has_pip else "npm"
        try:
            if manager == "pip":
                r = subprocess.run(
                    ["pip", "list", "--outdated", "--format=columns"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            else:
                r = subprocess.run(
                    ["npm", "outdated"],
                    capture_output=True,
                    text=True,
                    cwd=target_dir,
                    timeout=60,
                )
            return r.stdout.strip() or "✅ All dependencies are up to date"
        except Exception as e:
            return f"[ERROR] deps_outdated: {e}"

    def loc_stats_h(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", "."))
        target = root / directory
        totals: dict[str, int] = {}
        try:
            for fp in target.rglob("*"):
                if fp.is_file() and not any(
                    p in str(fp)
                    for p in [".git", "__pycache__", "node_modules", ".venv"]
                ):
                    ext = fp.suffix or "(no ext)"
                    try:
                        n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                        totals[ext] = totals.get(ext, 0) + n
                    except Exception:
                        pass
            rows = sorted(totals.items(), key=lambda x: -x[1])[:20]
            out = "\n".join(f"{ext:15} {n:>8,}" for ext, n in rows)
            return f"{'Extension':15} {'Lines':>8}\n{'-'*25}\n{out}\n{'':15} {sum(totals.values()):>8,} total"
        except Exception as e:
            return f"[ERROR] loc_stats: {e}"

    def npm_install_h(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", "."))
        package = str(inp.get("package", ""))
        target_dir = str(root / directory)
        cmd = ["npm", "install"] + ([package] if package else [])
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, cwd=target_dir, timeout=120
            )
            return (r.stdout + r.stderr).strip()[-2000:] or "npm install complete"
        except Exception as e:
            return f"[ERROR] npm_install: {e}"

    def npm_run_h(inp: dict[str, Any]) -> str:
        script = str(inp["script"])
        directory = str(inp.get("directory", "."))
        target_dir = str(root / directory)
        try:
            r = subprocess.run(
                ["npm", "run", script],
                capture_output=True,
                text=True,
                cwd=target_dir,
                timeout=180,
            )
            return (r.stdout + r.stderr).strip()[-3000:] or f"npm run {script} complete"
        except Exception as e:
            return f"[ERROR] npm_run: {e}"

    def pip_install_h(inp: dict[str, Any]) -> str:
        package = str(inp["package"])
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", package],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return (r.stdout + r.stderr).strip()[-2000:]
        except Exception as e:
            return f"[ERROR] pip_install: {e}"

    def pip_list_h(inp: dict[str, Any]) -> str:
        name_filter = str(inp.get("filter", ""))
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=columns"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = r.stdout.strip().splitlines()
            if name_filter:
                lines = [
                    ln
                    for ln in lines
                    if name_filter.lower() in ln.lower() or ln.startswith("Package")
                ]
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] pip_list: {e}"

    def create_directory_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        if _is_protected_path(path, repo_path):
            return f"[POLICY DENIED] Cannot create directory in protected path: {path}"
        target = root / path
        try:
            target.mkdir(parents=True, exist_ok=True)
            return f"Created directory: {path}"
        except Exception as e:
            return f"[ERROR] create_directory: {e}"

    def http_request_h(inp: dict[str, Any]) -> str:
        import urllib.request as _req
        import urllib.error as _uerr

        method = str(inp["method"]).upper()
        url = str(inp["url"])
        headers = dict(inp.get("headers") or {})
        body = inp.get("body")
        try:
            data = body.encode("utf-8") if body else None
            req = _req.Request(url, data=data, method=method, headers=headers)
            with _req.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                text = raw.decode("utf-8", errors="replace")[:3000]
                return f"HTTP {resp.status} {resp.reason}\n{text}"
        except _uerr.HTTPError as e:
            return f"HTTP {e.code} {e.reason}"
        except Exception as e:
            return f"[ERROR] http_request: {e}"

    def base64_encode_h(inp: dict[str, Any]) -> str:
        import base64 as _b64

        decode = bool(inp.get("decode", False))
        text = inp.get("text")
        path = inp.get("path")
        try:
            if path:
                raw = (root / str(path)).read_bytes()
                if decode:
                    return _b64.b64decode(raw).decode("utf-8", errors="replace")
                return _b64.b64encode(raw).decode("ascii")
            if text:
                if decode:
                    return _b64.b64decode(str(text).encode("utf-8")).decode(
                        "utf-8", errors="replace"
                    )
                return _b64.b64encode(str(text).encode("utf-8")).decode("ascii")
            return "[ERROR] Provide either text or path"
        except Exception as e:
            return f"[ERROR] base64_encode: {e}"

    def template_render_h(inp: dict[str, Any]) -> str:
        template_str = inp.get("template")
        path = inp.get("path")
        variables = dict(inp.get("vars") or {})
        try:
            from jinja2 import Template as _Tpl

            if path:
                template_str = (root / str(path)).read_text(encoding="utf-8")
            if not template_str:
                return "[ERROR] Provide either template or path"
            return str(_Tpl(str(template_str)).render(**variables))
        except ImportError:
            src = (
                str(template_str)
                if template_str
                else ((root / str(path)).read_text(encoding="utf-8") if path else "")
            )
            if not src:
                return "[ERROR] jinja2 not installed and no template provided"
            for k, v in variables.items():
                src = src.replace("{{" + k + "}}", str(v)).replace(
                    "{{ " + k + " }}", str(v)
                )
            return src
        except Exception as e:
            return f"[ERROR] template_render: {e}"

    handlers["git_tag"] = git_tag_h
    handlers["git_log_file"] = git_log_file_h
    handlers["semver_bump"] = semver_bump_h
    handlers["git_stash_list"] = git_stash_list_h
    handlers["list_processes"] = list_processes_h
    handlers["list_open_ports"] = list_open_ports_h
    handlers["wait_for_port"] = wait_for_port_h
    handlers["check_url_status"] = check_url_status_h
    handlers["cpu_profile"] = cpu_profile_h
    handlers["zip_files"] = zip_files_h
    handlers["unzip_files"] = unzip_files_h
    handlers["move_file"] = move_file_h
    handlers["hash_file"] = hash_file_h
    handlers["count_lines"] = count_lines_h
    handlers["read_env_var"] = read_env_var_h
    handlers["list_env_vars"] = list_env_vars_h
    handlers["env_diff"] = env_diff_h
    handlers["json_query"] = json_query_h
    handlers["yaml_validate"] = yaml_validate_h
    handlers["json_validate"] = json_validate_h
    handlers["csv_preview"] = csv_preview_h
    handlers["generate_diagram"] = generate_diagram_h
    handlers["export_markdown"] = export_markdown_h
    handlers["find_unused_imports"] = find_unused_imports_h
    handlers["deps_outdated"] = deps_outdated_h
    handlers["loc_stats"] = loc_stats_h
    handlers["npm_install"] = npm_install_h
    handlers["npm_run"] = npm_run_h
    handlers["pip_install"] = pip_install_h
    handlers["pip_list"] = pip_list_h
    handlers["create_directory"] = create_directory_h
    handlers["http_request"] = http_request_h
    handlers["base64_encode"] = base64_encode_h
    handlers["template_render"] = template_render_h

    return handlers


# ---------------------------------------------------------------------------
# Day 9 — Fleet Enhancement Dashboard tools
#
# Shared by the 5 self-improvement agents (agent_performance_reviewer,
# agent_debugger, agent_advisor, knowledge_curator, quality_auditor). These
# agents target the Gridiron project's own codebase (settings.fleet_self_repo_path),
# not a user-connected repo.
#
# SCAN phase (autonomous, read-only): fleet_metrics_read, audit_log_read,
# task_history_query (already exists above), memory_search, memory_curate_read,
# submit_enhancement_request — writes a pending row, nothing else happens.
#
# APPLY phase (only after human approval on a specific request):
# memory_curate_write, git_commit_change — stages only the named files, never `-A`.
# ---------------------------------------------------------------------------


def _new_isolated_db_engine() -> Any:
    """A throwaway async engine, NOT the shared app.db.session singleton.

    Tool handlers are sync functions called from arbitrary contexts (a fleet
    agent's scan loop may call several DB tools in the same process run).
    asyncio.run() opens and tears down its own event loop per call; the shared
    engine/pool in app.db.session gets bound to whichever loop first touched
    it, so reusing it across multiple asyncio.run() calls raises
    "Future attached to a different loop". A fresh, disposed-after-use engine
    per call avoids that entirely — slightly less efficient, always correct.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings as _gs

    return create_async_engine(_gs().database_url, pool_pre_ping=True)


_FLEET_METRICS_READ_TOOL: dict[str, Any] = {
    "name": "fleet_metrics_read",
    "description": "Read real runtime performance data for an agent (or the whole fleet): recent runs, p50/p95 latency, average tool accuracy. Use this before claiming an agent is slow or unreliable — never guess.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Agent to inspect. Omit to see the most recent runs across all agents.",
            },
            "n": {
                "type": "integer",
                "description": "Max runs to consider (default 20).",
            },
        },
        "required": [],
    },
}


def fleet_metrics_read(inp: dict[str, Any]) -> str:
    from app.fleet.metrics import get_metrics_collector

    agent_name = str(inp.get("agent_name", "")).strip()
    n = int(inp.get("n", 20))
    collector = get_metrics_collector()

    if not agent_name:
        runs = collector.recent(n)
        if not runs:
            return "(no runs recorded yet)"
        lines = [
            f"{m.agent_name}: status={m.status} time={m.execution_time_ms:.0f}ms tokens_in={m.tokens_in} tokens_out={m.tokens_out}"
            for m in runs
        ]
        return "\n".join(lines)

    runs = collector.by_agent(agent_name, n)
    if not runs:
        return f"(no recorded runs for agent {agent_name!r})"
    p50 = collector.p50_latency_ms(agent_name)
    p95 = collector.p95_latency_ms(agent_name)
    accuracy = collector.avg_tool_accuracy(agent_name)
    failed = sum(1 for m in runs if m.status == "failed")
    lines = [
        f"agent: {agent_name}",
        f"runs considered: {len(runs)} (failed: {failed})",
        f"p50 latency: {p50:.0f}ms" if p50 is not None else "p50 latency: n/a",
        f"p95 latency: {p95:.0f}ms" if p95 is not None else "p95 latency: n/a",
        (
            f"avg tool accuracy: {accuracy:.2f}"
            if accuracy is not None
            else "avg tool accuracy: n/a"
        ),
    ]
    return "\n".join(lines)


_AUDIT_LOG_READ_TOOL: dict[str, Any] = {
    "name": "audit_log_read",
    "description": "Read the fleet audit trail: what actions ran, for which agent, with what outcome. Use this to diagnose failing agents from real evidence, not speculation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Filter to one agent. Omit for the most recent entries across all agents.",
            },
            "n": {
                "type": "integer",
                "description": "Max entries to return (default 50).",
            },
        },
        "required": [],
    },
}


def audit_log_read(inp: dict[str, Any]) -> str:
    from app.fleet.audit_log import get_audit_log

    agent_name = str(inp.get("agent_name", "")).strip()
    n = int(inp.get("n", 50))
    log = get_audit_log()
    entries = log.recent(max(n, 200))
    if agent_name:
        entries = [e for e in entries if e.agent_name == agent_name]
    entries = entries[-n:]
    if not entries:
        return f"(no audit entries{f' for agent {agent_name!r}' if agent_name else ''})"
    lines = [
        f"[{e.timestamp}] {e.agent_name} — {e.action_type} — outcome={e.outcome}"
        + (f" — {e.description}" if e.description else "")
        for e in entries
    ]
    return "\n".join(lines)


_SUBMIT_ENHANCEMENT_REQUEST_TOOL: dict[str, Any] = {
    "name": "submit_enhancement_request",
    "description": (
        "File a proposed enhancement for human review on the Fleet Dashboard. "
        "Call this only when you have real evidence for a genuine issue or improvement — "
        "an empty scan with nothing to report is a normal, expected outcome, not a failure. "
        "This only creates a pending request; nothing changes on disk until a human approves it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title, plain language."},
            "description": {
                "type": "string",
                "description": "Full explanation in plain, non-technical-jargon language — this is what the human reads to decide approve/reject.",
            },
            "category": {
                "type": "string",
                "enum": [
                    "performance",
                    "bug",
                    "orchestration",
                    "knowledge",
                    "quality",
                    "security",
                ],
            },
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {
                "type": "object",
                "description": "file:line citations, metrics, or other evidence backing this claim.",
            },
        },
        "required": ["title", "description", "category", "priority"],
    },
}


def make_submit_enhancement_request_handler(agent_name: str, trace_id: str = "") -> Any:
    def submit_enhancement_request(inp: dict[str, Any]) -> str:
        import asyncio

        async def _write() -> int:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import EnhancementRequest

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(
                    engine, expire_on_commit=False
                )() as session:
                    row = EnhancementRequest(
                        agent_name=agent_name,
                        title=str(inp["title"]),
                        description=str(inp["description"]),
                        category=str(inp["category"]),
                        priority=str(inp["priority"]),
                        evidence=dict(inp.get("evidence") or {}),
                        status="pending",
                        trace_id=trace_id or None,
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    return int(row.id)
            finally:
                await engine.dispose()

        try:
            req_id = asyncio.run(_write())
        except Exception as exc:
            return f"[ERROR] Could not file enhancement request: {exc}"

        try:
            from app.services.activity_stream import get_activity_registry

            stream = get_activity_registry().get_or_create("fleet-dashboard")
            stream.push(
                {
                    "type": "new_request",
                    "id": req_id,
                    "agentName": agent_name,
                    "title": str(inp["title"]),
                    "priority": str(inp["priority"]),
                    "category": str(inp["category"]),
                }
            )
        except Exception:
            pass  # dashboard notification is non-fatal — the row is already written

        return f"Enhancement request #{req_id} filed for human review."

    return submit_enhancement_request


_MEMORY_SEARCH_TOOL: dict[str, Any] = {
    "name": "memory_search",
    "description": "Semantic search over the fleet's persistent engineering memory (past task outcomes, architecture decisions, failures, lessons) — NOT the same as memory_read/memory_write (those are a different, per-repo scratch store).",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "top_k": {"type": "integer", "description": "Max results (default 5)."},
        },
        "required": ["query"],
    },
}


def memory_search(inp: dict[str, Any]) -> str:
    import asyncio

    query = str(inp.get("query", "")).strip()
    if not query:
        return "[ERROR] query is required"
    top_k = int(inp.get("top_k", 5))

    async def _search() -> list[dict[str, Any]]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.memory.store import query_similar_tasks

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await query_similar_tasks(
                    description=query, db=session, top_k=top_k
                )
        finally:
            await engine.dispose()

    try:
        results = asyncio.run(_search())
    except Exception as exc:
        return f"[ERROR] memory_search failed: {exc}"
    if not results:
        return "(no similar memories found)"
    lines = [
        f"[{r.get('similarity', 0):.2f}] task={r.get('task_id')} outcome={r.get('outcome')} — {str(r.get('summary', ''))[:200]}"
        for r in results
    ]
    return "\n".join(lines)


_MEMORY_CURATE_READ_TOOL: dict[str, Any] = {
    "name": "memory_curate_read",
    "description": "List engineering-memory entries for curation review (duplicates, stale entries, mis-categorized entries) — distinct from memory_search (similarity search) and from memory_read (unrelated per-repo scratch store).",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter: task | architecture | failure | learning. Omit for all.",
            },
            "limit": {"type": "integer", "description": "Max rows (default 20)."},
        },
        "required": [],
    },
}


def memory_curate_read(inp: dict[str, Any]) -> str:
    import asyncio

    category = str(inp.get("category", "")).strip()
    limit = int(inp.get("limit", 20))

    async def _list() -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import MemoryEmbedding

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                q = (
                    select(MemoryEmbedding)
                    .order_by(MemoryEmbedding.created_at.desc())
                    .limit(limit)
                )
                if category:
                    q = q.where(MemoryEmbedding.category == category)
                result = await session.execute(q)
                rows = result.scalars().all()
                return [
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "category": r.category,
                        "outcome": r.outcome,
                        "summary": r.summary[:200],
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
        finally:
            await engine.dispose()

    try:
        rows = asyncio.run(_list())
    except Exception as exc:
        return f"[ERROR] memory_curate_read failed: {exc}"
    if not rows:
        return "(no memory entries found)"
    return "\n".join(
        f"#{r['id']} [{r['category']}] {r['outcome']} ({r['created_at']}) — {r['summary']}"
        for r in rows
    )


_MEMORY_CURATE_WRITE_TOOL: dict[str, Any] = {
    "name": "memory_curate_write",
    "description": "Update a memory entry during curation (recategorize, or mark as a superseded duplicate by rewriting its summary to note the supersession). Precursor to the full versioned-lesson lifecycle — light-touch, not a rewrite of history.",
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "MemoryEmbedding row id."},
            "category": {
                "type": "string",
                "description": "New category, if recategorizing.",
            },
            "note": {
                "type": "string",
                "description": "Note to append to the summary, e.g. superseded-by info.",
            },
        },
        "required": ["id"],
    },
}


def memory_curate_write(inp: dict[str, Any]) -> str:
    import asyncio

    row_id = int(inp["id"])
    new_category = inp.get("category")
    note = inp.get("note")
    if not new_category and not note:
        return "[ERROR] provide category and/or note — nothing to update"

    async def _update() -> bool:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import MemoryEmbedding

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await session.get(MemoryEmbedding, row_id)
                if row is None:
                    return False
                if new_category:
                    row.category = str(new_category)
                if note:
                    row.summary = f"{row.summary}\n[curated] {note}"
                await session.commit()
                return True
        finally:
            await engine.dispose()

    try:
        found = asyncio.run(_update())
    except Exception as exc:
        return f"[ERROR] memory_curate_write failed: {exc}"
    if not found:
        return f"[ERROR] No memory entry with id={row_id}"
    return f"Memory entry #{row_id} updated."


_GIT_COMMIT_CHANGE_TOOL: dict[str, Any] = {
    "name": "git_commit_change",
    "description": "Stage exactly the named files (never all changes) and commit them. Only usable in the APPLY phase, after a human has approved this specific fix.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths (relative to repo root) to stage. Never pass a wildcard — list every file explicitly.",
            },
            "message": {"type": "string", "description": "Commit message."},
        },
        "required": ["files", "message"],
    },
}


def make_git_commit_change_handler(repo_path: str) -> Any:
    def git_commit_change(inp: dict[str, Any]) -> str:
        files = [str(f) for f in (inp.get("files") or [])]
        message = str(inp.get("message", "")).strip()
        if not files:
            return "[ERROR] files is required — list every file explicitly, never a wildcard"
        if not message:
            return "[ERROR] message is required"

        for f in files:
            result = check_path(f)
            if not result.allowed:
                return f"[POLICY DENIED] {f}: {result.reason}"

        try:
            add_result = subprocess.run(
                ["git", "add", "--"] + files,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if add_result.returncode != 0:
                return f"[ERROR] git add failed: {add_result.stderr.strip()}"
            commit_result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if commit_result.returncode != 0:
                return f"[ERROR] git commit failed: {(commit_result.stdout + commit_result.stderr).strip()}"
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            sha = sha_result.stdout.strip()
            return f"Committed {len(files)} file(s) as {sha[:12]}: {message}"
        except subprocess.TimeoutExpired:
            return "[ERROR] git operation timed out"
        except Exception as exc:
            return f"[ERROR] {exc}"

    return git_commit_change


def make_fleet_apply_handlers(repo_path: str) -> dict[str, Any]:
    """Shared APPLY-phase handler set for the 4 write-capable fleet-enhancement
    agents (agent_performance_reviewer, agent_debugger, knowledge_curator,
    quality_auditor) — only ever invoked after a human approves a specific
    enhancement request. read_file + write_file + edit_file + run_tests +
    git_commit_change, all scoped to repo_path (settings.fleet_self_repo_path)."""
    base = Path(repo_path)

    def write_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path(rel)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(inp["content"]), encoding="utf-8")
        return f"Written {rel}"

    def edit_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path(rel)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        target = base / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        old_s, new_s = str(inp["old_string"]), str(inp["new_string"])
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel} — must be unique"
        target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited {rel}"

    def run_tests_h(inp: dict[str, Any]) -> str:
        path = str(inp.get("path", "backend/tests/"))
        flags = str(inp.get("flags", ""))
        cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null; python -m pytest {path} {flags} -q --tb=short 2>&1 | tail -50"
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=180
            )
            return r.stdout or r.stderr or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] tests timed out"

    return {
        "read_file": make_read_only_handlers(repo_path)["read_file"],
        "write_file": write_file_h,
        "edit_file": edit_file_h,
        "run_tests": run_tests_h,
        "git_commit_change": make_git_commit_change_handler(repo_path),
    }


FLEET_APPLY_TOOLS = [
    READ_ONLY_TOOLS[0],
    _WRITE_FILE_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _RUN_TESTS_TOOL,
    _GIT_COMMIT_CHANGE_TOOL,
]

_FLEET_BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": "Run a diagnostic or check command (git log/blame/status, ps, grep, test/lint runners). Scoped by the same command-allowlist guardrail every bash-using agent uses — destructive/deploy commands are blocked regardless of role.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Command to run"}},
        "required": ["command"],
    },
}


def make_scoped_bash_handler(repo_path: str) -> Any:
    """Shared scoped-bash handler for fleet agents — check_command() guardrail,
    same pattern every other bash-using agent already follows."""

    def bash_h(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=60,
            )
            out = (result.stdout + result.stderr)[:4000]
            return out if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out after 60s"

    return bash_h
