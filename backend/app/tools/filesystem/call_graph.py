"""call_graph tool — tool_enhance.md productionization pass, tool #93
(2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: call_graph
Old path: app/agents/tools.py (`_CALL_GRAPH_TOOL` schema dict) with
    FIVE separate real implementations, all thin wrappers around the
    same shared `app.repo_tools.ast_engine.build_call_graph()`
    utility: `bf_call_graph` (`make_bug_fix_handlers`), `ar_call_graph`
    (`make_arch_reviewer_handlers`), `rf_call_graph`
    (`make_refactor_agent_handlers`), `call_graph_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (a slightly longer but equally unprotected
    copy). The exact sibling tool to tool #83's `parse_ast` — same
    finding classes, same underlying `ast_engine` module, same fix
    shape.
New path: app/tools/filesystem/call_graph.py (this file) —
    `CALL_GRAPH_TOOL`, `call_graph_handler`. ALL FIVE real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 4 agents declare
    `call_graph` in `allowed_tools`.
Affected modules: app/agents/tools.py (all four of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler). `app/repo_tools/
    ast_engine.py`'s own `build_call_graph()`/`get_call_edges()` are
    left completely untouched and still do the real AST-walk work —
    `get_call_edges()` is also used by `generate_diagram_h` (a
    separate, out-of-scope tool), so the worktree-boundary fix is
    applied at the `call_graph`-specific call sites, not inside that
    shared lower-level utility — the same reasoning already
    established for tool #83's `parse_ast`.
Affected registries: none — app/fleet/tool_manifest.py's "call_graph"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the four handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_call_graph_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/call_graph.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings, identical across ALL FIVE
real implementations — the exact same finding classes already
established for tool #83's `parse_ast` (same underlying `ast_engine`
module, same unguarded `p.exists()` shape inside `get_call_edges()`).

1. **Worktree-boundary escape, on all five implementations.** None
   called `check_path_in_worktree()` — `root / path` let `path`
   resolve to any absolute host path before being handed to
   `ast_engine.build_call_graph()`. Proved live:
   `call_graph({"path": "/tmp/outside/secret.py"})` genuinely returned
   a real call graph (caller names, line numbers, and every function
   each one calls) of a Python file completely outside the repo,
   through multiple real call sites (`chat_agent.py`'s dispatch,
   `make_chat_handlers()`, `make_bug_fix_handlers()`).

2. **An uncaught `PermissionError`, on all five implementations —
   same class as tools #70/#72/#76/#82/#83.** Neither each thin
   wrapper nor `ast_engine.get_call_edges()`'s own internal
   `p.exists()` call is wrapped in a `try/except PermissionError`.
   Proved live with a real file inside a `chmod 000` parent directory.

Fixed via a shared `call_graph_handler()`: `check_path_in_worktree()`
closes finding #1; wrapping the call to the existing, UNMODIFIED
`ast_engine.build_call_graph()` in `try/except PermissionError` closes
finding #2 (returning `[ERROR] Permission denied: {rel}`, matching
this initiative's established convention). The actual call-graph-
building logic itself is reused verbatim from `ast_engine.
build_call_graph()` — not reimplemented — since it was already correct
and is shared by other, out-of-scope tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.ast_engine import build_call_graph

CALL_GRAPH_TOOL = {
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


def call_graph_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core call_graph logic shared by all five real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    function_name = str(inp.get("function_name", ""))
    try:
        return build_call_graph(str(root / rel), function_name)
    except PermissionError:
        return f"[ERROR] Permission denied: {rel}"
