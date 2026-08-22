"""file_exists tool — tool_enhance.md productionization pass, tool #70
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: file_exists
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[7]` schema dict and the
    `file_exists` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a SEPARATE, unprotected inline dispatch
    body).
New path: app/tools/filesystem/file_exists.py (this file) —
    `FILE_EXISTS_TOOL`, `file_exists_handler`.
Affected agents: per tool_inventory.json, 76 agents declare
    `file_exists` in `allowed_tools` — same shape as tools #65/#67/#68,
    NOT 76 separate implementations: every `run_agent_graph`-based agent
    and `make_chat_handlers()` reach it through the same canonical
    `make_read_only_handlers()` factory; only `chat_agent`'s own
    interactive dispatch was a genuinely separate, unprotected
    duplicate.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[7]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `file_exists` closure now delegates to the shared
    handler), app/agents/chat_agent.py (its real dispatch now calls the
    same shared, protected handler).
Affected registries: none — app/fleet/tool_manifest.py's "file_exists"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["file_exists"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_file_exists_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/file_exists.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape, `chat_agent.py`'s dispatch only.** Zero
   `check_path_in_worktree()` call — a real existence-probing oracle
   (same pathlib bug class as tools #10/#11/#18/#23/#43/#59/#61/#62/
   #64/#65/#67/#68/#69). Proved live: `file_exists({"path":
   "/etc/passwd"})` through `ChatAgent._execute_tool` genuinely
   returned `"file"` — confirming the real existence and type of a
   host file completely outside the repo. The canonical implementation
   was NOT exploitable by this payload — already correctly rejected it.

2. **An uncaught `PermissionError`, on BOTH implementations, including
   the canonical one.** Neither wraps `p.is_file()`/`p.is_dir()` in a
   try/except. Proved live: `file_exists({"path": "/root/.ssh/id_rsa"})`
   raised a real, uncaught `PermissionError` (`os.stat()` denied) —
   through the real graph-node call path this becomes the same class
   of information-disclosure-via-error-message finding as tool #68
   (`list_files`): the resulting `[ERROR]` text embeds the exact
   absolute path being probed, AND reveals that the path exists but is
   permission-restricted (an oracle state the tool's own documented
   3-state contract — file/directory/not_found — never intends to
   expose). This gap exists in the canonical implementation too, since
   a legitimately permission-restricted file INSIDE the repo (e.g. one
   accidentally committed with restrictive mode bits) would trigger it
   there as well.

Fixed via a shared `file_exists_handler()`: `check_path_in_worktree()`
closes finding #1; a `try/except PermissionError: return "not_found"`
around the stat calls closes finding #2, matching the EXISTING
precedent this same tool family already established —
`get_file_tree_handler()`'s own tree-walk already treats a
permission-denied subdirectory as "nothing to show" (`except
PermissionError: return`) rather than crashing; this applies the
identical graceful-degradation philosophy here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FILE_EXISTS_TOOL = {
    "name": "file_exists",
    "description": "Check whether a file or directory exists before reading or editing it. Returns true/false with type (file/directory/not_found).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path relative to repo root",
            },
        },
        "required": ["path"],
    },
}


def file_exists_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core file_exists logic shared by both real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    p = root / rel
    try:
        if p.is_file():
            return "file"
        if p.is_dir():
            return "directory"
    except PermissionError:
        return "not_found"
    return "not_found"
