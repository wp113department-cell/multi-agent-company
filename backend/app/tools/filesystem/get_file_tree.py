"""get_file_tree tool — tool_enhance.md productionization pass, tool
#67 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: get_file_tree
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[4]` schema dict and the
    `get_file_tree` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a SEPARATE, unprotected inline dispatch
    body).
New path: app/tools/filesystem/get_file_tree.py (this file) —
    `GET_FILE_TREE_TOOL`, `get_file_tree_handler`.
Affected agents: per tool_inventory.json, 79 agents declare
    `get_file_tree` in `allowed_tools` — same shape as tool #65
    (`read_file`), NOT 79 separate implementations: every
    `run_agent_graph`-based agent and `make_chat_handlers()` reach it
    through the same canonical `make_read_only_handlers()` factory;
    only `chat_agent`'s own interactive dispatch was a genuinely
    separate, unprotected duplicate.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[4]` now points
    at the shared schema constant — kept at the exact same list index,
    since `RESEARCH_TOOLS` indexes into `READ_ONLY_TOOLS` positionally;
    `make_read_only_handlers()`'s own `get_file_tree` closure now
    delegates to the shared handler), app/agents/chat_agent.py (its
    real dispatch now calls the same shared, protected handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "get_file_tree" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["get_file_tree"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_get_file_tree_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/get_file_tree.md.
---------------------------------------------------------------------------

Real, empirically-verified finding: `chat_agent.py`'s real dispatch had
ZERO worktree-boundary validation on `directory` — `root / directory`
silently discards `root` when the value is an absolute path (the same
pathlib bug class as tools #10/#11/#18/#23/#43/#59/#61/#62/#64/#65).
Proved live: `get_file_tree({"directory": "/etc", "max_depth": 1})`
through `ChatAgent._execute_tool` genuinely returned the real directory
structure of `/etc` — an information-disclosure primitive (filenames
and directory layout of an arbitrary host location, though not file
contents). The canonical `make_read_only_handlers()` implementation was
NOT exploitable by this payload — already correctly rejected it.

Fixed by extracting the canonical, already-correct logic into a shared
`get_file_tree_handler()` here, and switching both real call sites onto
it — the 300-line output cap and the max_depth clamp (1-4) were already
identical between both original implementations, so no behavior changes
beyond closing the boundary gap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

GET_FILE_TREE_TOOL = {
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
}

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


def get_file_tree_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core get_file_tree logic shared by both real call sites."""
    directory = str(inp.get("directory", ""))
    max_depth = min(int(inp.get("max_depth", 3)), 4)

    if directory:
        policy = check_path_in_worktree(directory, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"

    start = root / directory if directory else root
    if not start.exists():
        return f"[ERROR] Directory not found: {directory}"

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
