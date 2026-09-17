"""resolve_merge_conflict tool — tool_enhance.md productionization
pass, tool #229 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: resolve_merge_conflict
Old path: app/agents/tools.py (`_RESOLVE_MERGE_CONFLICT_TOOL` schema
    dict) with TWO real, near-identical implementations:
    `resolve_merge_conflict` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch — the same
    "two real implementations" shape already found and fixed on
    sibling tools #136 (`explain_merge_conflict`) and #228
    (`parse_merge_conflicts`).
New path: app/tools/git/resolve_merge_conflict.py (this file) —
    `RESOLVE_MERGE_CONFLICT_TOOL`, `resolve_merge_conflict_handler`.
    BOTH real call sites now delegate to this one shared handler.
Affected agents: this tool is in `CHAT_TOOLS`, dispatched via
    `ChatAgent._execute_tool()` for interactive chat — confirmed via
    membership check.
Affected modules: app/agents/tools.py (its own closure now delegates
    to the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected tests: none required changes. New tests added: see
    tests/test_resolve_merge_conflict_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/resolve_merge_conflict.md.
---------------------------------------------------------------------------

Worktree-boundary validation was ALREADY correct on both real
implementations (`check_path_in_worktree(rel, repo_path)` /
`_is_protected_path(rmc_rel, repo)`) — fixed 2026-08-17 during tool
#11's (`undo_changes`) cross-cutting audit, confirmed still correct
here by direct inspection.

FOUR real, separate uncaught-crash paths, proved live against BOTH
implementations before any fix — worse than sibling tool #228's two:

1. `rel = str(inp["path"])` used bare dict indexing — a genuinely
   missing `path` key raised an uncaught `KeyError: 'path'`.
2. `idx = int(entry["index"])` inside the resolutions loop ALSO used
   bare dict indexing — a resolution entry genuinely missing its
   `index` key raised an uncaught `KeyError: 'index'`.
3. The same `int(entry["index"])` coercion had no guard against a
   malformed value — `{"index": "not-a-number", "choice": "ours"}`
   raised an uncaught `ValueError`.
4. Neither implementation wrapped `target.read_text()` (nor
   `target.write_text()`) in a `try`/`except` — a directory passed as
   `path` raised an uncaught `IsADirectoryError`.

Fixed via a shared `resolve_merge_conflict_handler()`: `path` is read
via an explicit presence check; each resolution entry's `index` is
read via `.get()` inside its own `try`/`except (TypeError, ValueError,
KeyError)`, returning a clean, hunk-specific error naming which entry
failed; and the whole read+apply+write operation is wrapped in
`try`/`except`. `_apply_conflict_resolutions` is imported directly
from its own existing home, `app.agents.conflict_resolution` —
matching the sibling tools' established import pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.conflict_resolution import _apply_conflict_resolutions
from app.policy.engine import check_path_in_worktree

RESOLVE_MERGE_CONFLICT_TOOL: dict[str, Any] = {
    "name": "resolve_merge_conflict",
    "description": "Resolve specific conflict hunks in a file (by index, from parse_merge_conflicts) by keeping 'ours', 'theirs', or 'custom' merged content. Hunks not named in resolutions are left untouched and reported back as still unresolved.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Conflicted file, relative to repo root",
            },
            "resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Hunk index from parse_merge_conflicts",
                        },
                        "choice": {
                            "type": "string",
                            "enum": ["ours", "theirs", "custom"],
                        },
                        "custom_content": {
                            "type": "string",
                            "description": "Required when choice='custom' — the exact merged content for this hunk",
                        },
                    },
                    "required": ["index", "choice"],
                },
            },
        },
        "required": ["path", "resolutions"],
    },
}


def resolve_merge_conflict_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core resolve_merge_conflict logic shared by both real call
    sites (the make_chat_handlers() closure and chat_agent.py's own
    interactive dispatch). `path` and each resolution entry's `index`
    are now read via explicit presence checks / their own try/except,
    and the file read+write is now wrapped in try/except — closing
    this module's own four documented uncaught-crash findings."""
    if "path" not in inp:
        return "[ERROR] path is required"
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {rel}: {policy.reason}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    raw_resolutions = inp.get("resolutions") or []
    if not raw_resolutions:
        return "[ERROR] resolutions is required — at least one {index, choice}"
    resolutions: dict[int, dict[str, Any]] = {}
    for entry in raw_resolutions:
        if "index" not in entry:
            return "[ERROR] each resolution needs an 'index'"
        try:
            idx = int(entry["index"])
        except (TypeError, ValueError) as exc:
            return f"[ERROR] invalid numeric index {entry.get('index')!r}: {exc}"
        choice = str(entry.get("choice", ""))
        if choice == "custom" and "custom_content" not in entry:
            return f"[ERROR] hunk {idx}: choice='custom' requires custom_content"
        resolutions[idx] = entry
    try:
        text = target.read_text(encoding="utf-8")
        new_text, applied, unresolved = _apply_conflict_resolutions(text, resolutions)
        target.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return f"[ERROR] Could not resolve conflicts in {rel}: {e}"
    if unresolved:
        return (
            f"Resolved {len(applied)} hunk(s) in {rel}. "
            f"Still unresolved (markers left intact): {unresolved}"
        )
    return f"Resolved all {len(applied)} conflict hunk(s) in {rel}."
