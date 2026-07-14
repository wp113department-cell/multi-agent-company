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

    return {
        "read_file": read_file,
        "list_files": list_files,
        "search_code": search_code,
        "search_symbols": search_symbols,
        "get_file_tree": get_file_tree,
        "git_log": git_log,
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
