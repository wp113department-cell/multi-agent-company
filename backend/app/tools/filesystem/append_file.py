"""append_file tool — tool_enhance.md productionization pass, tool #26
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: append_file
Old path: app/agents/tools.py (`_APPEND_FILE_TOOL` schema dict and the
    `append_file` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/filesystem/append_file.py (this file) —
    `APPEND_FILE_TOOL`, `append_file_handler`.
Affected agents: 1 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch (the only agent that actually declares this
    tool; `make_chat_handlers`'s own copy is unreachable by any real
    one-shot agent today, kept for defense-in-depth/consistency, matching
    this initiative's own precedent for tools.py handlers with no
    current real caller).
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the shared handler directly).
Affected registries: none — app/fleet/tool_manifest.py's "append_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["append_file"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_append_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/append_file.md.
---------------------------------------------------------------------------

No new vulnerability found this turn. `append_file`'s worktree-boundary
check was already fixed for both real implementations during tool #11's
(`undo_changes`) cross-cutting audit — re-verified directly this turn
(a real absolute path outside the repo and a real `.env` denylist case
are both still rejected), not assumed. `chat_agent.py`'s dispatch had no
`try`/`except` around the actual write (unlike `make_chat_handlers`'s own
copy) — not a live bug (a top-level `except Exception` in
`ChatAgent._execute_tool_node` already catches any exception and
surfaces it as a clean `[ERROR] Tool ... failed: ...` string, confirmed
by reading that call site directly), but the shared handler now wraps
the write in `try`/`except` for a more specific, tool-authored error
message on a real disk error, matching `make_chat_handlers`'s own prior
behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
from app.tools.filesystem._textio import adapt_to_style, existing_newline_style

APPEND_FILE_TOOL = {
    "name": "append_file",
    "description": "Append content to the end of an existing file. Creates the file if it doesn't exist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "content": {"type": "string", "description": "Content to append"},
        },
        "required": ["path", "content"],
    },
}


def append_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    rel = str(inp["path"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot write to protected path: {rel}"
    target = root / rel
    content = str(inp["content"])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Append in the existing file's own newline style (LF text appended to a
        # CRLF file used to leave it with mixed line endings).
        data = adapt_to_style(content, existing_newline_style(target))
        with open(target, "a", encoding="utf-8", newline="") as f:
            f.write(data)
        return f"Appended {len(content)} bytes to {rel}"
    except Exception as e:
        return f"[ERROR] {e}"
