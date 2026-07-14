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

# ---------------------------------------------------------------------------
# MODULE-LEVEL BACKGROUND PROCESS REGISTRY (used by run_background/kill_process)
# ---------------------------------------------------------------------------

_BACKGROUND_PROCESSES: dict[int, "subprocess.Popen[str]"] = {}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 1: File / Editing extras
# ---------------------------------------------------------------------------

_FIND_FILE_TOOL = {
    "name": "find_file",
    "description": "Find files by name or glob pattern across the repository. Faster than list_files when you know the filename.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Filename or pattern to find (e.g. 'config.py', '*.json', 'test_*.py')"},
            "directory": {"type": "string", "description": "Directory to search (default: repo root)"},
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
            "path": {"type": "string", "description": "File path relative to repo root"},
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
            "path": {"type": "string", "description": "Python file path relative to repo root"},
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
            "path": {"type": "string", "description": "File path relative to repo root"},
            "line": {"type": "integer", "description": "1-indexed line to insert before. Use 0 to prepend."},
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
            "path": {"type": "string", "description": "Python file path relative to repo root"},
            "function_name": {"type": "string", "description": "Name of the function or method to replace"},
            "new_code": {"type": "string", "description": "Complete new function code (def line + body, properly indented)"},
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
            "path": {"type": "string", "description": "File path relative to repo root"},
            "start_line": {"type": "integer", "description": "First line to delete (1-indexed, inclusive)"},
            "end_line": {"type": "integer", "description": "Last line to delete (1-indexed, inclusive)"},
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
            "patch": {"type": "string", "description": "Unified diff string (output of git diff or diff -u)"},
            "strip": {"type": "integer", "description": "Strip N leading path components (like patch -pN, default: 1)"},
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
            "path_a": {"type": "string", "description": "First file path relative to repo root"},
            "path_b": {"type": "string", "description": "Second file path relative to repo root"},
            "context": {"type": "integer", "description": "Lines of context around changes (default: 3)"},
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
            "command": {"type": "string", "description": "Shell command to run in background"},
            "cwd": {"type": "string", "description": "Working directory (default: repo root)"},
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
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
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
            "target": {"type": "string", "description": "Make target to run (e.g. 'test', 'build', 'lint'). Leave empty to list."},
            "directory": {"type": "string", "description": "Directory containing Makefile (default: repo root)"},
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
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 15)"},
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
            "branch": {"type": "string", "description": "Branch name to merge into current branch"},
            "no_ff": {"type": "boolean", "description": "Create a merge commit even for fast-forwards (default: false)"},
            "squash": {"type": "boolean", "description": "Squash all commits into one (default: false)"},
            "message": {"type": "string", "description": "Commit message for the merge (optional)"},
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
            "ref": {"type": "string", "description": "Ref to reset to (e.g. 'HEAD~1', commit hash). Default: HEAD"},
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
            "path": {"type": "string", "description": "Path for the new worktree (required for add)"},
            "branch": {"type": "string", "description": "Branch for the new worktree (required for add)"},
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
            "base": {"type": "string", "description": "Base branch to merge into (default: main)"},
            "draft": {"type": "boolean", "description": "Create as draft PR (default: false)"},
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
            "staged_only": {"type": "boolean", "description": "Use only staged changes (default: true)"},
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
            "keyword": {"type": "string", "description": "Test name or keyword to match (-k flag for pytest)"},
            "file": {"type": "string", "description": "Specific test file to run (optional)"},
            "verbose": {"type": "boolean", "description": "Show verbose output (default: true)"},
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
            "path": {"type": "string", "description": "Path to run tests on (default: backend/tests/)"},
            "source": {"type": "string", "description": "Source directory to measure coverage for (default: backend/app/)"},
            "min_coverage": {"type": "integer", "description": "Fail if coverage is below this percentage (optional)"},
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
            "path": {"type": "string", "description": "Path to check (default: backend/ for Python, apps/web/ for TS)"},
            "strict": {"type": "boolean", "description": "Use --strict mode for mypy (default: false)"},
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
            "path": {"type": "string", "description": "File path relative to repo root (.py, .ts, .tsx supported)"},
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
            "path": {"type": "string", "description": "File path relative to repo root (.py, .ts, .tsx supported)"},
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
            "path": {"type": "string", "description": "File path relative to repo root"},
            "function_name": {"type": "string", "description": "Name of the function or method to extract"},
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
            "path": {"type": "string", "description": "Log file path, or service name (e.g. 'uvicorn', 'postgresql')"},
            "lines": {"type": "integer", "description": "Number of recent lines to return (default: 50)"},
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
            "error": {"type": "string", "description": "Error message or full traceback to analyze"},
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
            "table": {"type": "string", "description": "Specific table name to inspect (default: list all tables)"},
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
            "all": {"type": "boolean", "description": "Show all containers including stopped ones (default: false)"},
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
            "lines": {"type": "integer", "description": "Number of recent log lines (default: 50)"},
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
            "command": {"type": "string", "description": "Command to run inside the container"},
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
            "detach": {"type": "boolean", "description": "Run in background for 'up' (default: true)"},
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
            "directory": {"type": "string", "description": "Directory to scan (default: entire repo)"},
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

    # =========================================================================
    # BATCH 1 — File / Editing extras
    # =========================================================================

    def find_file(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        ff_dir = str(inp.get("directory", ""))
        ff_root = root / ff_dir if ff_dir else root
        try:
            r = subprocess.run(
                ["find", str(ff_root), "-name", name,
                 "-not", "-path", "*/node_modules/*",
                 "-not", "-path", "*/__pycache__/*",
                 "-not", "-path", "*/.git/*",
                 "-not", "-path", "*/.venv/*"],
                capture_output=True, text=True, timeout=15,
            )
            found = [l for l in r.stdout.splitlines() if l.strip()]
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
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30)
        return (r.stdout + r.stderr).strip() or f"Formatted {rel}"

    def organize_imports(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        oi_target = root / rel
        if not oi_target.exists():
            return f"[ERROR] File not found: {rel}"
        activate = f"source {repo_path}/.venv/bin/activate 2>/dev/null || true"
        cmd = f"{activate} && python -m ruff check --select I --fix {str(oi_target)} 2>&1"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30)
        return (r.stdout + r.stderr).strip() or f"Imports organized in {rel}"

    def insert_at_line(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        line_num = int(inp["line"])
        content = str(inp["content"])
        if _is_protected_path(rel):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        ial_target = root / rel
        if not ial_target.exists():
            return f"[ERROR] File not found: {rel}"
        try:
            file_lines = ial_target.read_text(encoding="utf-8").splitlines(keepends=True)
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
        if _is_protected_path(rel):
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
                if rf_stripped.startswith(f"def {func_name}(") or rf_stripped.startswith(f"async def {func_name}("):
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
                if rf_jind <= rf_indent and rf_jline.strip() and not rf_jline.strip().startswith(("#", "@")):
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
        if _is_protected_path(rel):
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
            dl_target.write_text("".join(dl_lines[:dl_s] + dl_lines[dl_e:]), encoding="utf-8")
            return f"Deleted {deleted} lines ({dl_start}-{dl_end}) from {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def apply_patch(inp: dict[str, Any]) -> str:
        import os as _os
        import tempfile as _tempfile
        patch_content = str(inp["patch"])
        strip = int(inp.get("strip", 1))
        try:
            with _tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as pf:
                pf.write(patch_content)
                pf_name = pf.name
        except Exception as e:
            return f"[ERROR] Cannot write patch file: {e}"
        try:
            r = subprocess.run(
                ["patch", f"-p{strip}", "--input", pf_name],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
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
            capture_output=True, text=True,
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
                rb_command, shell=True, cwd=rb_cwd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            _BACKGROUND_PROCESSES[proc.pid] = proc
            return f"Started background process PID {proc.pid}: {rb_command[:80]}"
        except Exception as e:
            return f"[ERROR] {e}"

    def kill_process(inp: dict[str, Any]) -> str:
        import os as _os
        import signal as _signal
        kp_pid = int(inp["pid"])
        kp_sig_name = str(inp.get("signal", "TERM"))
        sig_map = {"TERM": _signal.SIGTERM, "KILL": _signal.SIGKILL, "INT": _signal.SIGINT}
        kp_sig = sig_map.get(kp_sig_name, _signal.SIGTERM)
        _BACKGROUND_PROCESSES.pop(kp_pid, None)
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
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=ps_timeout)
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[ERROR] Python snippet timed out after {ps_timeout}s"
        except Exception as e:
            return f"[ERROR] {e}"

    def run_make(inp: dict[str, Any]) -> str:
        make_target = str(inp.get("target", ""))
        make_dir_rel = str(inp.get("directory", ""))
        make_dir = (root / make_dir_rel) if make_dir_rel else root
        makefile_exists = (make_dir / "Makefile").exists() or (make_dir / "makefile").exists()
        if not makefile_exists:
            return f"[ERROR] No Makefile found in {make_dir}"
        if not make_target:
            r = subprocess.run(["make", "-pRrq"], cwd=str(make_dir), capture_output=True, text=True, timeout=10)
            tgts: list[str] = []
            for mk_line in r.stdout.splitlines():
                if mk_line and not mk_line.startswith(("\t", "#", " ")) and ":" in mk_line:
                    tgt = mk_line.split(":")[0].strip()
                    if tgt and not tgt.startswith(".") and " " not in tgt:
                        tgts.append(tgt)
            return "Targets:\n" + "\n".join(sorted(set(tgts[:30]))) if tgts else "Makefile found but targets not parseable"
        try:
            r = subprocess.run(["make", make_target], cwd=str(make_dir), capture_output=True, text=True, timeout=120)
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
                ["curl", "-s", "-L", "--max-time", str(fu_timeout),
                 "--user-agent", "Gridiron-Agent/1.0", fu_url],
                capture_output=True, text=True, timeout=fu_timeout + 5,
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
            r = subprocess.run(gm_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30)
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
            r = subprocess.run(gr_cmd, cwd=repo_path, capture_output=True, text=True, timeout=10)
            return (r.stdout + r.stderr).strip() or f"Reset {gr_mode} to {gr_ref}"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_worktree(inp: dict[str, Any]) -> str:
        gw_action = str(inp.get("action", "list"))
        gw_path = str(inp.get("path", ""))
        gw_branch = str(inp.get("branch", ""))
        try:
            if gw_action == "list":
                r = subprocess.run(["git", "worktree", "list"], cwd=repo_path, capture_output=True, text=True)
                return r.stdout or "(no worktrees)"
            elif gw_action == "add":
                if not gw_path or not gw_branch:
                    return "[ERROR] path and branch required for add"
                r = subprocess.run(
                    ["git", "worktree", "add", gw_path, gw_branch],
                    cwd=repo_path, capture_output=True, text=True, timeout=30,
                )
                return (r.stdout + r.stderr).strip() or f"Created worktree at {gw_path}"
            elif gw_action == "remove":
                if not gw_path:
                    return "[ERROR] path required for remove"
                r = subprocess.run(
                    ["git", "worktree", "remove", gw_path],
                    cwd=repo_path, capture_output=True, text=True,
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
            r = subprocess.run(pr_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr).strip() or "PR created"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found — install with: sudo apt install gh"
        except Exception as e:
            return f"[ERROR] {e}"

    def generate_commit_msg(inp: dict[str, Any]) -> str:
        gcm_staged = bool(inp.get("staged_only", True))
        diff_args = ["diff", "--cached"] if gcm_staged else ["diff"]
        stat_args = diff_args + ["--stat"]
        r_stat = subprocess.run(["git"] + stat_args, cwd=repo_path, capture_output=True, text=True)
        r_diff = subprocess.run(["git"] + diff_args, cwd=repo_path, capture_output=True, text=True)
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
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=120)
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
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=180)
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
            cmd = f"{activate} && python -m mypy {py_path} {strict_flag} 2>&1 | head -60"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=90)
            tc_results.append(f"=== mypy ===\n{(r.stdout + r.stderr)[:3000] or 'clean'}")
        if tc_lang in ("typescript", "both"):
            web = str(root.parent / "apps" / "web")
            cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -60"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
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
            elif s.startswith(("export function ", "export async function ", "function ")) and "(" in s:
                lf_results.append(f"  L{lf_i}: {s[:120]}")
            elif s.startswith(("export const ", "const ")) and ("=>" in s or "= (" in s or "= async" in s):
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
                elif s.startswith(("public ", "private ", "protected ", "async ", "static ")) and "(" in s:
                    lc_results.append(f"    L{lc_i}: {s[:120]}")
            elif lc_current and lc_line.strip() and curr_indent <= lc_base_indent and not s.startswith(("@", "#", "/")):
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
        ffb_lines = ffb_fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        ffb_start: int | None = None
        ffb_base = 0
        for ffb_i, ffb_line in enumerate(ffb_lines):
            s = ffb_line.strip()
            if s.startswith(f"def {ffb_name}(") or s.startswith(f"async def {ffb_name}("):
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
            if ffb_jind <= ffb_base and ffb_jline.strip() and not ffb_jline.strip().startswith(("@", "#")):
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
            log_file = root / rl_path if not Path(rl_path).is_absolute() else Path(rl_path)
            if log_file.exists():
                r = subprocess.run(["tail", f"-{rl_lines}", str(log_file)], capture_output=True, text=True)
                out = r.stdout
            else:
                return f"[ERROR] Log file not found: {rl_path}"
        elif rl_path:
            r = subprocess.run(
                ["journalctl", "-u", rl_path, f"-n{rl_lines}", "--no-pager"],
                capture_output=True, text=True, timeout=10,
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
            r = subprocess.run(["tail", f"-{rl_lines}", str(newest)], capture_output=True, text=True)
            out = f"From {newest}:\n" + r.stdout
        if rl_level != "all":
            filtered = [line for line in out.splitlines() if rl_level.upper() in line.upper()]
            out = "\n".join(filtered)
        return out[:5000] or "(no log entries)"

    def analyze_error(inp: dict[str, Any]) -> str:
        ae_error = str(inp["error"])
        ae_lines = ae_error.strip().splitlines()
        exception_line = ""
        for ae_line in reversed(ae_lines):
            if any(x in ae_line for x in ("Error:", "Exception:", "Warning:", "Traceback")):
                exception_line = ae_line
                break
        frames: list[str] = []
        ae_i = 0
        while ae_i < len(ae_lines):
            ae_line = ae_lines[ae_i]
            if ae_line.strip().startswith("File ") and "line " in ae_line:
                if not any(x in ae_line for x in ("site-packages", ".venv", "lib/python")):
                    code_line = ae_lines[ae_i + 1].strip() if ae_i + 1 < len(ae_lines) else ""
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
            suggestions.append("→ Missing dependency — run: pip install -r requirements.txt")
        elif "attributeerror" in ae_low:
            suggestions.append("→ Object doesn't have this attribute — check spelling and type")
        elif "typeerror" in ae_low:
            suggestions.append("→ Wrong argument type/count — check function signature")
        elif "keyerror" in ae_low:
            suggestions.append("→ Dictionary key not found — use .get() or check key exists")
        elif "filenotfounderror" in ae_low:
            suggestions.append("→ Path doesn't exist — verify path and working directory")
        elif "connectionrefusederror" in ae_low or "connection refused" in ae_low:
            suggestions.append("→ Service not running — check if DB/Redis/backend is started")
        elif "syntaxerror" in ae_low:
            suggestions.append("→ Python syntax error — check brackets, colons, indentation")
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
                capture_output=True, text=True, timeout=30,
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
                capture_output=True, text=True, timeout=10,
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
            "docker", "ps",
            "--format", "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}",
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
                capture_output=True, text=True, timeout=15,
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
                capture_output=True, text=True, timeout=30,
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
            r = subprocess.run(dc_cmd, cwd=repo_path, capture_output=True, text=True, timeout=120)
            return (r.stdout + r.stderr)[:5000] or f"docker compose {dc_action} complete"
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
        ss_exclude = ["node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next"]
        ss_findings: list[str] = []
        for ss_pat in ss_patterns:
            ss_cmd = ["grep", "-rn", "-E", ss_pat, str(ss_root)]
            for ex in ss_exclude:
                ss_cmd += ["--exclude-dir", ex]
            ss_cmd += ["--exclude", "*.env", "--exclude", ".env*", "--exclude", "*.example"]
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
    return handlers
