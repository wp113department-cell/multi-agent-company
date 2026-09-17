"""parse_merge_conflicts tool — tool_enhance.md productionization
pass, tool #228 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: parse_merge_conflicts
Old path: app/agents/tools.py (`_PARSE_MERGE_CONFLICTS_TOOL` schema
    dict) with TWO real, near-identical implementations:
    `parse_merge_conflicts` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch — the same
    "two real implementations" shape already found and fixed on the
    sibling tool #136 (`explain_merge_conflict`).
New path: app/tools/git/parse_merge_conflicts.py (this file) —
    `PARSE_MERGE_CONFLICTS_TOOL`, `parse_merge_conflicts_handler`.
    BOTH real call sites now delegate to this one shared handler.
Affected agents: this tool is in `CHAT_TOOLS`, dispatched via
    `ChatAgent._execute_tool()` for interactive chat — confirmed via
    membership check.
Affected modules: app/agents/tools.py (its own closure now delegates
    to the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "parse_merge_conflicts" entry (if present) is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_parse_merge_conflicts_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/parse_merge_conflicts.md.
---------------------------------------------------------------------------

Worktree-boundary validation was ALREADY correct on both real
implementations (`check_path_in_worktree(rel, repo_path)` in the
tools.py closure, `_is_protected_path(pmc_rel, repo)` in
chat_agent.py's dispatch — both perform full worktree-containment
checking given a worktree path) — fixed 2026-08-17 during tool #11's
(`undo_changes`) cross-cutting audit (per this tool's own tracking-row
note), confirmed still correct here by direct inspection and
re-verified live below, not assumed.

Two real findings, proved live against BOTH implementations before
any fix:

1. `rel = str(inp["path"])` used bare dict indexing in both real call
   sites — a genuinely missing `path` key raised an uncaught
   `KeyError: 'path'`.
2. Neither implementation wrapped `target.read_text()` in a
   `try`/`except` — the same class already fixed for tools
   #70/#72/#76/#135/#136. Proved live with TWO separate real crash
   inputs: a directory passed as `path` raised an uncaught
   `IsADirectoryError`, and a file with invalid UTF-8 bytes raised an
   uncaught `UnicodeDecodeError`.

Fixed via a shared `parse_merge_conflicts_handler()`: `path` is read
via `.get()` with an explicit presence check, and the whole read+parse
operation is wrapped in `try`/`except`. `_parse_conflict_markers` is
imported directly from its own existing home,
`app.agents.conflict_resolution` — matching tool #136's own
established import pattern, a neutral, non-circular module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.conflict_resolution import _parse_conflict_markers
from app.policy.engine import check_path_in_worktree

PARSE_MERGE_CONFLICTS_TOOL: dict[str, Any] = {
    "name": "parse_merge_conflicts",
    "description": "Parse a file's real <<<<<<</=======/>>>>>>> conflict markers into structured hunks (ours/theirs text, labels, line ranges) — read this before deciding how to resolve a conflicted file, never guess resolution from raw marker text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Conflicted file, relative to repo root",
            },
        },
        "required": ["path"],
    },
}


def parse_merge_conflicts_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core parse_merge_conflicts logic shared by both real call
    sites (the make_chat_handlers() closure and chat_agent.py's own
    interactive dispatch). `path` is now read via `.get()` with an
    explicit presence check, and the file read is now wrapped in its
    own try/except — closing this module's own two documented
    uncaught-crash findings."""
    if "path" not in inp:
        return "[ERROR] path is required"
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {rel}: {policy.reason}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ERROR] Could not read {rel}: {e}"
    hunks = _parse_conflict_markers(text)
    if not hunks:
        return f"No conflict markers found in {rel}."
    import json as _json

    return _json.dumps({"path": rel, "hunks": hunks}, indent=2)
