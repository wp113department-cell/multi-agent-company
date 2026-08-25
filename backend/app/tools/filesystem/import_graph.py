"""import_graph tool — tool_enhance.md productionization pass, tool #95
(2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: import_graph
Old path: app/agents/tools.py (`_IMPORT_GRAPH_TOOL` schema dict) with
    FOUR real implementations, all thin one-liners around the same
    shared `app.repo_tools.ast_engine.build_import_graph()` utility:
    `ar_import_graph` (`make_arch_reviewer_handlers`),
    `rf_import_graph` (`make_refactor_agent_handlers`),
    `import_graph_h` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/filesystem/import_graph.py (this file) —
    `IMPORT_GRAPH_TOOL`, `import_graph_handler`. ALL FOUR real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 4 agents declare
    `import_graph` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler). `app/repo_tools/
    ast_engine.py`'s own `build_import_graph()` is left completely
    untouched and still does the real AST work — the same reasoning
    already established for tools #83/#93/#94's `ast_engine` reuse.
Affected registries: none — app/fleet/tool_manifest.py's
    "import_graph" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_import_graph_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/import_graph.md.
---------------------------------------------------------------------------

Exact same two finding classes as tool #83's `parse_ast` (same
underlying `ast_engine` module, same single-file-read shape — unlike
tool #94's `dead_code_detect`, which walks a directory and does NOT
share the PermissionError class).

1. **Worktree-boundary escape, on all four implementations.** None
   called `check_path_in_worktree()` — `root / path` let `path`
   resolve to any absolute host path before being handed to
   `ast_engine.build_import_graph()`. Proved live:
   `import_graph({"path": "/tmp/outside/secret.py"})` genuinely
   returned a real import list (modules + imported symbols) of a
   Python file completely outside the repo.

2. **An uncaught `PermissionError`, on all four implementations — same
   class as tools #70/#72/#76/#82/#83/#93.** `ast_engine.
   build_import_graph()`'s own internal `p.read_text()` call is not
   wrapped in a `try/except PermissionError`. Proved live with a real
   file inside a `chmod 000` parent directory (raised
   `PermissionError`, confirmed NOT the rglob-swallows-it behavior
   documented for tool #94 — this function reads a single given file
   path directly, it never walks a directory).

Fixed via a shared `import_graph_handler()`: `check_path_in_worktree()`
closes finding #1; wrapping the call to the existing, UNMODIFIED
`ast_engine.build_import_graph()` in `try/except PermissionError`
closes finding #2. The actual import-extraction logic itself is reused
verbatim — not reimplemented — since it was already correct and is
shared by other, out-of-scope tools (`import_graph` is itself the only
consumer of `build_import_graph()`, but the underlying `ast_engine`
module is shared broadly).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.ast_engine import build_import_graph

IMPORT_GRAPH_TOOL = {
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


def import_graph_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core import_graph logic shared by all four real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    try:
        return build_import_graph(str(root / rel))
    except PermissionError:
        return f"[ERROR] Permission denied: {rel}"
