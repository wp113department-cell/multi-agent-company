"""parse_ast tool — tool_enhance.md productionization pass, tool #83
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: parse_ast
Old path: app/agents/tools.py (`_PARSE_AST_TOOL` schema dict) with
    SEVEN separate real implementations, all one-line wrappers around
    the same shared `app.repo_tools.ast_engine.parse_file_ast()`
    utility: `bf_parse_ast` (`make_bug_fix_handlers`), `ar_parse_ast`
    (`make_arch_reviewer_handlers`), `rf_parse_ast`
    (`make_refactor_agent_handlers`), `rm_parse_ast`
    (`make_readme_agent_handlers`), `ad_parse_ast`
    (`make_api_docs_agent_handlers`), `parse_ast_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (a slightly longer but equally unprotected
    copy).
New path: app/tools/filesystem/parse_ast.py (this file) —
    `PARSE_AST_TOOL`, `parse_ast_handler`. ALL SEVEN real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 32 agents declare
    `parse_ast` in `allowed_tools`.
Affected modules: app/agents/tools.py (all seven closures now delegate
    to the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler). `app/repo_tools/ast_engine.py`'s
    own `parse_file_ast()` function is left completely untouched and
    still does the real AST parsing work — it is also used by several
    OTHER tools not in scope this turn (`import_graph`, `call_graph`,
    `dead_code_detect`, `circular_dep_detect`), so the worktree-
    boundary fix is applied at the `parse_ast`-specific call sites, not
    inside that shared lower-level utility.
Affected registries: none — app/fleet/tool_manifest.py's "parse_ast"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the seven handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_parse_ast_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/parse_ast.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings, identical across ALL SEVEN
real implementations (they are all thin, functionally-identical
one-liners around the same underlying utility, unlike tool #82's
`list_functions`, which had genuinely divergent bugs per
implementation).

1. **Worktree-boundary escape, on all seven implementations.** None
   called `check_path_in_worktree()` — `root / path` let `path`
   resolve to any absolute host path before being handed to
   `ast_engine.parse_file_ast()`. Proved live:
   `parse_ast({"path": "/tmp/outside/secret.py"})` genuinely returned
   a real structured JSON AST dump (function names, line numbers,
   arguments, decorators) of a Python file completely outside the
   repo, through multiple real call sites (`chat_agent.py`'s dispatch,
   `make_chat_handlers()`, `make_bug_fix_handlers()`,
   `make_arch_reviewer_handlers()`) — a richer disclosure primitive
   than tool #82's plain-text `list_functions`, since the AST dump
   includes decorators and full argument lists.

2. **An uncaught `PermissionError`, on all seven implementations —
   same class as tools #70/#72/#76/#82.** Neither each thin wrapper
   nor `ast_engine.parse_file_ast()`'s own internal `p.exists()` call
   is wrapped in a `try/except PermissionError`. Proved live with a
   real file inside a `chmod 000` parent directory.

Fixed via a shared `parse_ast_handler()`: `check_path_in_worktree()`
closes finding #1; wrapping the call to the existing, UNMODIFIED
`ast_engine.parse_file_ast()` in `try/except PermissionError` closes
finding #2 (returning `[ERROR] Permission denied: {rel}`, matching
this initiative's established convention). The actual AST-parsing
logic itself is reused verbatim from `ast_engine.parse_file_ast()` —
not reimplemented — since it was already correct and is shared by
other, out-of-scope tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.ast_engine import parse_file_ast

PARSE_AST_TOOL = {
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


def parse_ast_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core parse_ast logic shared by all seven real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    try:
        return parse_file_ast(str(root / rel))
    except PermissionError:
        return f"[ERROR] Permission denied: {rel}"
