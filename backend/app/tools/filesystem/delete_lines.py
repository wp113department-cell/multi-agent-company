"""delete_lines tool — tool_enhance.md productionization pass, tool #34
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: delete_lines
Old path: app/agents/tools.py (`_DELETE_LINES_TOOL` schema dict and the
    `delete_lines` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/filesystem/delete_lines.py (this file) —
    `DELETE_LINES_TOOL`, `delete_lines_handler`.
Affected agents: 1 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the shared handler directly).
Affected registries: none — app/fleet/tool_manifest.py's "delete_lines"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["delete_lines"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_delete_lines_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/delete_lines.md.
---------------------------------------------------------------------------

No new vulnerability found this turn. `delete_lines`'s worktree-boundary
check was already fixed for both real implementations during tool #11's
(`undo_changes`) cross-cutting audit — re-verified directly this turn
(a real absolute path outside the repo and a real `.env` denylist case
are both still rejected), not assumed. The two implementations were
already nearly identical (only the invalid-range error message's wording
differed) — merged onto one shared handler.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
from app.tools.filesystem._textio import (
    read_text_lf,
    write_text_lf,
)

DELETE_LINES_TOOL = {
    "name": "delete_lines",
    "description": "Delete a range of lines from a file (1-indexed, inclusive). Prefer edit_file for targeted changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to delete (1-indexed, inclusive)",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to delete (1-indexed, inclusive)",
            },
        },
        "required": ["path", "start_line", "end_line"],
    },
}


def delete_lines_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    rel = str(inp["path"])
    start = int(inp["start_line"])
    end = int(inp["end_line"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot write to protected path: {rel}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    if start < 1 or end < start:
        return f"[ERROR] Invalid line range: {start}-{end}"
    try:
        text, nl_style = read_text_lf(target)
        lines = text.splitlines(keepends=True)
        total = len(lines)
        if start > total:
            return f"[ERROR] File only has {total} lines"
        s = start - 1
        e = min(end, total)
        deleted = e - s
        write_text_lf(target, "".join(lines[:s] + lines[e:]), nl_style)
        return f"Deleted {deleted} lines ({start}-{end}) from {rel}"
    except Exception as ex:
        return f"[ERROR] {ex}"
