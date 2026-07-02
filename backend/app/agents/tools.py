"""Standard tool definitions and handlers for agent use."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.policy.engine import check_command, check_path_in_worktree


# --- Tool specs (Anthropic input_schema format) ---

READ_ONLY_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file at the given path.",
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
        "description": "List files in a directory. Returns file paths relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory path (default: repo root)"},
                "pattern": {"type": "string", "description": "Glob pattern filter (e.g. '**/*.py')"},
            },
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern across the repository using grep.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex or string to search for"},
                "file_pattern": {"type": "string", "description": "File glob to restrict search (e.g. '*.py')"},
            },
            "required": ["pattern"],
        },
    },
]

CODER_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "write_file",
        "description": "Write content to a file (creates or overwrites). Only allowed inside the worktree.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to worktree root"},
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "bash",
        "description": "Run a shell command (allowlisted safe commands only).",
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
        "description": "Signal that implementation is complete. Provide the list of files changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files_changed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths that were created or modified",
                },
                "summary": {"type": "string", "description": "One-paragraph summary of what was implemented"},
            },
            "required": ["files_changed", "summary"],
        },
    },
]


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
        str_paths: list[str] = [str(p.relative_to(base)) for p in search_root.glob(pattern) if p.is_file()]
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

    return {"read_file": read_file, "list_files": list_files, "search_code": search_code}


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

    def submit_patch(inp: dict[str, Any]) -> str:
        patch_result["files_changed"] = inp.get("files_changed", [])
        patch_result["summary"] = inp.get("summary", "")
        return "Patch submitted"

    handlers["write_file"] = write_file
    handlers["bash"] = bash
    handlers["submit_patch"] = submit_patch
    handlers["_patch_result"] = patch_result  # caller reads this after run
    return handlers
