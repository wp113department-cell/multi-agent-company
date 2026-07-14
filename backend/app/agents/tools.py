"""Standard tool definitions and handlers for agent use."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.policy.engine import check_command, check_path_in_worktree


# --- Tool specs (Anthropic input_schema format) ---

READ_ONLY_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the full contents of a file. Always read a file before editing it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the repo root"},
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
                "directory": {"type": "string", "description": "Directory path (default: repo root)"},
                "pattern": {"type": "string", "description": "Glob pattern filter (e.g. '**/*.py', '**/*.ts')"},
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
                "pattern": {"type": "string", "description": "Regex or literal string to search for"},
                "file_pattern": {"type": "string", "description": "Limit search to files matching this glob (e.g. '*.py', '*.ts')"},
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
                "name": {"type": "string", "description": "Symbol name or partial name to search for (e.g. 'get_task', 'DevTask', 'fetchTasks')"},
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
                "directory": {"type": "string", "description": "Starting directory (default: repo root)"},
                "max_depth": {"type": "integer", "description": "Max depth to show, 1-4 (default: 3)"},
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
                "count": {"type": "integer", "description": "Number of commits to show (default: 10, max: 30)"},
                "file": {"type": "string", "description": "Optional: show only commits that touched this file"},
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
                "path": {"type": "string", "description": "File or directory path relative to repo root"},
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
                "path": {"type": "string", "description": "File path relative to repo root"},
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
                "symbol": {"type": "string", "description": "Symbol name to find usages of (e.g. 'get_task', 'DevTask', 'fetchTasks')"},
                "file_pattern": {"type": "string", "description": "Limit to files matching this glob (e.g. '*.py', '*.ts')"},
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
                "directory": {"type": "string", "description": "Directory to search (default: repo root)"},
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
                "module": {"type": "string", "description": "Module/package name to search (e.g. 'fastapi', 'asyncpg', 'useState')"},
                "file_pattern": {"type": "string", "description": "Limit to file type (e.g. '*.py', '*.ts')"},
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
                "ref": {"type": "string", "description": "Commit hash, tag, or relative ref like HEAD~2 (default: HEAD)"},
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
                "path": {"type": "string", "description": "File path relative to repo root"},
                "start_line": {"type": "integer", "description": "First line to blame (optional)"},
                "end_line": {"type": "integer", "description": "Last line to blame (optional)"},
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
                "path": {"type": "string", "description": "File path relative to repo root (.py, .ts, .tsx supported)"},
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
                "path": {"type": "string", "description": "File path relative to the worktree root"},
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
                "path": {"type": "string", "description": "File path relative to worktree root"},
                "content": {"type": "string", "description": "Complete file content to write"},
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
                "file": {"type": "string", "description": "Optional: show diff for a specific file only"},
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
                "summary": {"type": "string", "description": "One-paragraph summary of what was implemented and verified"},
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
        "required": ["status", "tests_run", "tests_passed", "tests_failed", "typecheck_clean", "lint_clean", "errors", "summary"],
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
                        "severity": {"type": "string", "enum": ["blocking", "non-blocking", "suggestion"]},
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
            "command": {"type": "string", "description": "Read-only health check command"},
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


def _is_qa_command_allowed(cmd: str) -> bool:
    stripped = cmd.strip()
    return any(stripped.startswith(p) for p in _QA_ALLOWED_PREFIXES)


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
            patterns += [f"def {name}", f"async def {name}", f"function {name}", f"const {name} ="]
        if kind in ("class", "all"):
            patterns += [f"class {name}", f"interface {name}", f"type {name} ="]
        results: list[str] = []
        for pat in patterns:
            try:
                result = subprocess.run(
                    ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.tsx", pat, str(base)],
                    capture_output=True, text=True, timeout=10,
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
        _SKIP = {"__pycache__", "node_modules", ".next", ".venv", "venv", ".git", "dist", "build", ".mypy_cache"}
        lines: list[str] = [directory or "."]

        def _tree(path: Path, depth: int, prefix: str) -> None:
            if depth > max_depth:
                return
            try:
                items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return
            items = [i for i in items if i.name not in _SKIP and not i.name.startswith(".")]
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
        cmd = ["git", "log", f"--oneline", f"-{count}", "--no-merges"]
        if file_filter:
            cmd.extend(["--", file_filter])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(base), timeout=15)
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
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
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
                ["grep", "-rn", "-E", f"({pattern}):", str(search_root),
                 "--include=*.py", "--include=*.ts", "--include=*.tsx",
                 "--include=*.js", "--include=*.md"],
                capture_output=True, text=True, timeout=15,
            )
            out = result.stdout[:5000]
            return out if out.strip() else "(no TODOs found)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Search timed out"

    def search_imports(inp: dict[str, Any]) -> str:
        module = inp["module"]
        file_pattern = inp.get("file_pattern", "")
        patterns = [f"import {module}", f"from {module}", f'require("{module}")', f"require('{module}')"]
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
                capture_output=True, text=True, cwd=str(base), timeout=10,
            )
            return result.stdout or "(clean)"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_show(inp: dict[str, Any]) -> str:
        ref = str(inp.get("ref", "HEAD"))
        try:
            result = subprocess.run(
                ["git", "show", "--stat", "--no-color", ref],
                capture_output=True, text=True, cwd=str(base), timeout=15,
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
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(base), timeout=15)
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
            elif any(stripped.startswith(p) for p in (
                "export function ", "export async function ", "export class ",
                "export const ", "export default ", "export interface ", "export type ",
                "function ", "const ", "class ", "interface ", "type ",
            )) and ("=" in stripped or "(" in stripped or "{" in stripped):
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
                cmd, shell=True, capture_output=True, text=True, cwd=worktree_path, timeout=60
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
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=worktree_path, timeout=15)
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
        if not _is_qa_command_allowed(cmd):
            return f"[POLICY DENIED] QA agent may only run test/build commands. Got: {cmd!r}"
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=worktree_path, env=_env_with_venv, timeout=120,
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

    def _is_devops_command_allowed(cmd: str) -> bool:
        settings = get_settings()
        allowed_prefixes = tuple(p.strip() for p in settings.devops_bash_allowlist.split(",") if p.strip())
        stripped = cmd.strip()
        return any(stripped.startswith(prefix) for prefix in allowed_prefixes)

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        if not _is_devops_command_allowed(cmd):
            return f"[POLICY DENIED] DevOps agent may only run read-only health-check commands. Got: {cmd!r}"
        # also run v1 policy check
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30
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
RESEARCH_TOOLS = [READ_ONLY_TOOLS[0], READ_ONLY_TOOLS[1], READ_ONLY_TOOLS[2], _SUBMIT_RESEARCH_TOOL]


def make_research_handlers(repo_path: str) -> dict[str, Any]:
    """Research agent: read-only + web_search placeholder + submit_research. No write, no bash."""
    handlers = make_read_only_handlers(repo_path)
    research_result: dict[str, Any] = {}

    def web_search(inp: dict[str, Any]) -> str:
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
            "summary": {"type": "string", "description": "Brief summary of documentation changes"},
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
                "path": {"type": "string", "description": "File path relative to the worktree root (must be *.md or docs/**)"},
                "content": {"type": "string", "description": "Full file content to write"},
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
            "path": {"type": "string", "description": "File path relative to repo root"},
            "reason": {"type": "string", "description": "Why this file is being deleted"},
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
            "branch": {"type": "string", "description": "Branch to push (defaults to current branch)"},
            "remote": {"type": "string", "description": "Remote name (default: origin)"},
            "force": {"type": "boolean", "description": "Force push (default: false — requires extra confirmation)"},
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
            "name": {"type": "string", "description": "Branch name (e.g. 'feat/add-login')"},
            "checkout": {"type": "boolean", "description": "Switch to the new branch after creating it (default: true)"},
            "from_branch": {"type": "string", "description": "Base branch (default: current HEAD)"},
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
            "cwd": {"type": "string", "description": "Working directory override (default: repo root)"},
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
            "summary": {"type": "string", "description": "What was accomplished, files changed, commands run"},
            "status": {"type": "string", "enum": ["done", "blocked"], "description": "done = complete, blocked = hit a wall and need help"},
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
            "path": {"type": "string", "description": "File path relative to repo root"},
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
            "from_path": {"type": "string", "description": "Current file path relative to repo root"},
            "to_path": {"type": "string", "description": "New file path relative to repo root"},
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
            "from_path": {"type": "string", "description": "Source file path relative to repo root"},
            "to_path": {"type": "string", "description": "Destination file path relative to repo root"},
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
            "message": {"type": "string", "description": "Commit message (use conventional commits: feat/fix/docs/refactor: description)"},
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
            "name": {"type": "string", "description": "Branch name (required for create/delete)"},
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
            "target": {"type": "string", "description": "Branch name or commit hash to checkout"},
            "file": {"type": "string", "description": "If provided, restore only this file (git checkout -- file)"},
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
            "message": {"type": "string", "description": "Optional label for the stash (push only)"},
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
            "remote": {"type": "string", "description": "Remote name (default: origin)"},
            "branch": {"type": "string", "description": "Branch to pull (default: current branch)"},
            "rebase": {"type": "boolean", "description": "Use --rebase instead of merge (default: false)"},
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
            "remote": {"type": "string", "description": "Remote name (default: origin)"},
            "prune": {"type": "boolean", "description": "Remove stale remote-tracking refs (default: false)"},
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
            "path": {"type": "string", "description": "File path to restore (relative to repo root)"},
            "staged": {"type": "boolean", "description": "Unstage staged changes instead of discarding working tree changes (default: false)"},
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
            "path": {"type": "string", "description": "Specific test file or directory to run (optional)"},
            "flags": {"type": "string", "description": "Extra flags to pass to the test runner (e.g. '-v -x -k test_name')"},
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
            "path": {"type": "string", "description": "Path to lint (default: backend/ or apps/web/)"},
            "fix": {"type": "boolean", "description": "Auto-fix issues where possible (ruff only, default: false)"},
        },
        "required": [],
    },
}

CHAT_TOOLS = READ_ONLY_TOOLS + [
    {
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
                "old_string": {"type": "string", "description": "Exact text to replace (must be unique in file)"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
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
    },
    {
        "name": "git_diff",
        "description": "Show current unstaged and staged diff. Optionally limit to one file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Limit to this file (optional)"},
            },
            "required": [],
        },
    },
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
]

# Commands that require user confirmation before running
_DANGEROUS_PATTERNS = [
    "rm -rf",
    "rm -r",
    "git push",
    "git reset --hard",
    "git clean -f",
    "docker push",
    "docker rm",
    "kubectl delete",
    "kubectl apply",
    "systemctl",
    "sudo",
    "pip uninstall",
    "npm uninstall",
    "DROP TABLE",
    "DELETE FROM",
    "truncate",
    "mkfs",
    "dd if=",
    "> /dev/",
    "shutdown",
    "reboot",
]

_PROTECTED_PATHS = {".env", "secrets/", ".github/workflows/", ".git/"}


def _is_dangerous_command(command: str) -> bool:
    low = command.lower()
    return any(p.lower() in low for p in _DANGEROUS_PATTERNS)


def _is_protected_path(path: str) -> bool:
    return any(path.startswith(p) or path == p.rstrip("/") for p in _PROTECTED_PATHS)


def make_chat_handlers(repo_path: str, session: Any = None) -> dict[str, Any]:
    """
    Full-access handlers for the interactive chat agent.
    session: ChatSession instance — used to request user confirmation for dangerous ops.
    If session is None, dangerous commands are blocked rather than confirmed.
    """
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    # ---- edit_file ----
    def edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
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
        if _is_protected_path(rel):
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
            cwd=repo_path, capture_output=True, text=True,
        )
        unstaged = subprocess.run(
            args + ([inp["file"]] if inp.get("file") else []),
            cwd=repo_path, capture_output=True, text=True,
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
                    import concurrent.futures
                    future = asyncio.run_coroutine_threadsafe(
                        session.request_confirmation(
                            action_id=action_id,
                            description=f"Run dangerous command",
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
            output = result.stdout + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
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
        if _is_protected_path(rel):
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
                import concurrent.futures
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
            result = subprocess.run(cmd_parts, cwd=repo_path, capture_output=True, text=True, timeout=60)
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
            result = subprocess.run(create_cmd, cwd=repo_path, capture_output=True, text=True)
            if result.returncode != 0:
                return f"[ERROR] {result.stderr.strip()}"
        except Exception as e:
            return f"[ERROR] {e}"

        if checkout:
            try:
                result = subprocess.run(
                    ["git", "checkout", name],
                    cwd=repo_path, capture_output=True, text=True,
                )
                if result.returncode != 0:
                    return f"Branch created but checkout failed: {result.stderr.strip()}"
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
        if _is_protected_path(rel):
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
        if _is_protected_path(from_rel) or _is_protected_path(to_rel):
            return f"[POLICY DENIED] Protected path involved."
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
        if _is_protected_path(to_rel):
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
                subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
            else:
                for f in files:
                    subprocess.run(["git", "add", f], cwd=repo_path, check=True, capture_output=True)
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path, capture_output=True, text=True,
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
                r = subprocess.run(["git", "branch", "-a"], cwd=repo_path, capture_output=True, text=True)
                return r.stdout or "(no branches)"
            elif action == "create":
                if not name:
                    return "[ERROR] name required for create"
                r = subprocess.run(["git", "branch", name], cwd=repo_path, capture_output=True, text=True)
                return r.stdout + r.stderr or f"Branch '{name}' created"
            elif action == "delete":
                if not name:
                    return "[ERROR] name required for delete"
                r = subprocess.run(["git", "branch", "-d", name], cwd=repo_path, capture_output=True, text=True)
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
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=60)
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
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=60)
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
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
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
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            results.append(f"=== ruff ===\n{(r.stdout + r.stderr)[:2000] or 'clean'}")

        if tool in ("mypy", "all"):
            target = path or f"{repo_path}"
            cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m mypy {target} --ignore-missing-imports 2>&1 | head -50"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
            results.append(f"=== mypy ===\n{(r.stdout + r.stderr)[:2000] or 'clean'}")

        if tool in ("tsc", "all"):
            web = str(root.parent / "apps" / "web")
            cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -50"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
            results.append(f"=== tsc ===\n{(r.stdout + r.stderr)[:2000] or 'clean'}")

        if tool == "black":
            target = path or f"{repo_path}"
            cmd = f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m black {'--check' if not fix else ''} {target} 2>&1 | head -50"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            results.append(f"=== black ===\n{(r.stdout + r.stderr)[:2000]}")

        return "\n\n".join(results) if results else f"[ERROR] Unknown linter: {tool}"

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
    handlers["_chat_result"] = chat_result
    return handlers
