"""delete_file tool — tool_enhance.md productionization pass, tool #17
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: delete_file
Old path: app/agents/tools.py (`_DELETE_FILE_TOOL` schema dict, and the
    `delete_file`/`cu_delete_file` handlers inside `make_chat_handlers()`
    and `make_cleanup_agent_handlers()`) + app/agents/chat_agent.py
    (inline dispatch body)
New path: app/tools/filesystem/delete_file.py (this file) —
    `DELETE_FILE_TOOL`, `delete_file_handler`.
Affected agents: 2 per tool_inventory.json — `chat_agent` (real,
    confirmation-gated) and `cleanup_agent` (real, one-shot, no
    confirmation channel — see app/agents/base_graph.py's own
    per-tool-confirmation gap, out of scope for this tool's own turn).
Affected modules: app/agents/tools.py (compatibility re-export, both
    `delete_file` in `make_chat_handlers()` and `cu_delete_file` in
    `make_cleanup_agent_handlers()` now delegate to the shared handler),
    app/agents/chat_agent.py (its real dispatch now calls
    `delete_file_handler` after its own existence/is-file/confirm gate).
Affected registries: none — app/fleet/tool_manifest.py's "delete_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["delete_file"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_delete_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/delete_file.md.
---------------------------------------------------------------------------

No new path-escape vulnerability found this turn — `delete_file`'s
worktree-boundary check was already fixed for all 3 real implementations
during tool #11's (`undo_changes`) cross-cutting audit.

Real AGENT ALIGNMENT finding (a genuine schema/implementation mismatch,
not a security bug): `DELETE_FILE_TOOL`'s own schema has always required
a `reason` field ("Why this file is being deleted") — `"required":
["path", "reason"]` — but NONE of the 3 pre-existing handlers ever read
`inp["reason"]` at all. The LLM is told this is mandatory information a
human reviewer needs, and it was silently discarded every time. Fixed:
`chat_agent.py`'s real confirmation dialog now shows the reason to the
human approving the deletion (the actual point of asking for it), and
the returned success message for all 3 real call sites now includes it
too, so a one-shot agent's own transcript (`cleanup_agent`'s only real
audit trail, since it has no confirmation channel at all) captures why a
file was deleted, not just that it was.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path

DELETE_FILE_TOOL = {
    "name": "delete_file",
    "description": (
        "Permanently delete a file from the repository. "
        "Cannot delete .env*, secrets/**, or .github/workflows/**. "
        "Always confirm with the user before deleting important files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "reason": {
                "type": "string",
                "description": "Why this file is being deleted",
            },
        },
        "required": ["path", "reason"],
    },
}


def delete_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core delete_file logic shared by every real call site. Callers that
    need a pre-delete confirmation gate (chat_agent.py's real dispatch)
    run their own existence/is-file checks and confirm() call first and
    only reach this function once approved — this function still
    re-checks the worktree/denylist and existence itself, so it is safe
    to call directly, not just as a second layer.

    `reason` (required by the schema, previously silently discarded by
    every implementation) is now included in the success message so a
    one-shot agent's own transcript — its only real audit trail, since it
    has no human-confirmation channel — captures why the file was
    deleted, not just that it was."""
    rel = str(inp["path"])
    reason = str(inp.get("reason", "")).strip()
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot delete protected path: {rel}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    if not target.is_file():
        return f"[ERROR] {rel} is not a file (use bash 'rm -rf' for directories)"
    try:
        target.unlink()
    except Exception as e:
        return f"[ERROR] Cannot delete {rel}: {e}"
    return f"Deleted {rel} (reason: {reason})" if reason else f"Deleted {rel}"
