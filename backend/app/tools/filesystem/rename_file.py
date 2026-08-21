"""rename_file tool — tool_enhance.md productionization pass, tool
#56 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: rename_file
Old path: app/agents/tools.py (`_RENAME_FILE_TOOL` schema dict and the
    `rename_file` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body — already correct,
    near-identical logic to the tools.py handler).
New path: app/tools/filesystem/rename_file.py (this file) —
    `RENAME_FILE_TOOL`, `rename_file_handler`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other
    agent declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; handler now
    delegates to the shared implementation), app/agents/chat_agent.py
    (dispatch now delegates to the same shared implementation instead
    of duplicating it).
Affected registries: none — app/fleet/tool_manifest.py's "rename_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_rename_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/rename_file.md.
---------------------------------------------------------------------------

No new vulnerability found. Both real implementations were already
correct: `_is_protected_path(from_path, repo_path)` and
`_is_protected_path(to_path, repo_path)` are both called with
`repo_path` passed as `worktree_path`, enabling full
`check_path_in_worktree()` containment checking on BOTH sides — the
worktree-boundary fix already applied here during tool #11's
cross-cutting audit (2026-08-17), confirmed still present and
re-verified live (rejects an absolute outside-repo path on either
`from_path` or `to_path`). `CHAT_TOOLS.count("rename_file") == 1`
verified — no duplicate-advertisement risk.

This turn is pure modularization/consolidation: the two previously
independently-maintained, near-identical copies of this handler
(differing only in a trailing period and a try/except wrapper) are now
one shared function, closing the risk of them silently drifting apart
in the future.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path

RENAME_FILE_TOOL = {
    "name": "rename_file",
    "description": "Rename or move a file within the repository. Cannot move outside the repo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_path": {
                "type": "string",
                "description": "Current file path relative to repo root",
            },
            "to_path": {
                "type": "string",
                "description": "New file path relative to repo root",
            },
        },
        "required": ["from_path", "to_path"],
    },
}


def rename_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Shared implementation used by both real call sites (chat_agent.py's
    dispatch and make_chat_handlers())."""
    from_rel = str(inp["from_path"])
    to_rel = str(inp["to_path"])
    if _is_protected_path(from_rel, worktree_path) or _is_protected_path(
        to_rel, worktree_path
    ):
        return "[POLICY DENIED] Protected path involved."
    src = root / from_rel
    dst = root / to_rel
    if not src.exists():
        return f"[ERROR] Source not found: {from_rel}"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return f"Moved {from_rel} → {to_rel}"
    except Exception as e:
        return f"[ERROR] {e}"
