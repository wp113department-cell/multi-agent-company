"""edit_file tool — tool_enhance.md productionization pass, tool #13
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: edit_file (the generic, unscoped variant — not the dependency/
    requirements-file-only variant used by the dependency agent, which
    keeps its own distinct scoping; see "Deliberately left untouched")
Old path: app/agents/tools.py (`_EDIT_FILE_TOOL_SPEC` schema dict, the
    duplicate schema in `CODER_TOOLS`, and the edit logic duplicated
    inline across `_make_edit_file_handler`, `make_chat_handlers()`'s own
    `edit_file`, and `make_fleet_apply_handlers()`'s `edit_file_h`)
New path: app/tools/filesystem/edit_file.py (this file) —
    `EDIT_FILE_TOOL`, `edit_file_handler`.
Affected agents: 19 per tool_inventory.json — every agent built on
    `make_chat_handlers()`, every agent using `_make_edit_file_handler`
    (4 factories), the 4 fleet self-enhancement agents via
    `make_fleet_apply_handlers()`, and `chat_agent`'s own interactive
    dispatch.
Affected modules: app/agents/tools.py (compatibility re-export + delegates
    `_make_edit_file_handler`/`make_chat_handlers`'s edit_file to the
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls `edit_file_handler` directly).
Affected registries: none — app/fleet/tool_manifest.py's "edit_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every real test accesses this
    tool via `handlers["edit_file"](...)` or `ChatAgent._execute_tool`,
    both unchanged externally, and the message format (`"Edited {rel}"`)
    was already consistent across every implementation before this move.

Deliberately left untouched (audited during this turn, found already
correctly guarded, NOT modularized to avoid unnecessary rewrite of
working, tested code):
- `make_coder_handlers`'s `edit_file` (tools.py line ~1575) — generic,
  already uses `check_path_in_worktree` correctly.
- `make_dependency_agent_handlers`'s `dep_edit_file` — restricts to
  `_DEP_EDITABLE` filenames (requirements.txt/package.json/...), a real,
  intentional policy difference, not accidental duplication.
- `make_cleanup_agent_handlers`'s `cu_edit_file` — generic but already
  correctly guarded (`_is_protected_path(rel, repo_path)`).
- `make_fleet_apply_handlers`'s `edit_file_h` — already correctly guarded
  (fixed during tool #11's cross-cutting audit: `check_path(rel)` swapped
  for `check_path_in_worktree(rel, repo_path)`). NOT modularized here
  because, unlike write_file's fleet_apply equivalent, its role-prompt
  and plain-file branches share the same count/replace logic across two
  different read sources (prompt_registry vs. disk) and two different
  write destinations (`_propose_and_deploy_role_prompt` vs. disk) — not a
  clean drop-in for the shared handler without a riskier restructure for
  comparatively little benefit (4 agents).

Runtime verification: PASS — see
    backend/docs/tool_productionization/edit_file.md.
---------------------------------------------------------------------------

No new vulnerability found this turn. `edit_file`'s own severe bug —
`chat_agent.py`'s real dispatch having NO protected-path check at all,
not even the denylist — was already found and fixed during tool #11's
(`undo_changes`) cross-cutting audit. This turn's own audit of every
OTHER real edit_file implementation found all of them already correctly
guarded; this turn's job was modularizing the now-correct generic
variant, not finding a new bug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
from app.tools.filesystem._textio import (
    read_text_lf,
    write_text_lf,
)

EDIT_FILE_TOOL = {
    "name": "edit_file",
    "description": (
        "Make a targeted edit to a file by replacing an exact string. "
        "PREFER this over write_file for modifying existing files — it is safer because "
        "it only changes the specified region and fails if the text is not found. "
        "old_string must be unique in the file. Read the file first if unsure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the worktree root",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to find and replace. Must appear exactly once in the file.",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text. Can be empty string to delete old_string.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
}


def edit_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core edit_file logic shared by every generic (unscoped) real call
    site. Callers with their own extra scoping policy (dependency-files-
    only, ...) run their own check first and only reach this function once
    that check has already passed — this function still re-checks the
    worktree/denylist itself (`_is_protected_path`), so it is safe to call
    directly, not just as a second layer.

    Unlike write_file, no confirmation gate is needed here — a unique
    old_string -> new_string replacement is inherently safer (git-diffable,
    fails loudly if the text isn't found or isn't unique) and is left
    ungated everywhere in this codebase, matching how coding agents
    normally operate without per-edit confirmation."""
    rel = str(inp["path"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot write to protected path: {rel}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        text, nl_style = read_text_lf(target)
    except Exception as e:
        return f"[ERROR] Cannot read {rel}: {e}"
    # Match/replace on LF text, write back in the file's own newline style
    # (a CRLF file used to be silently rewritten as LF).
    old_s = str(inp["old_string"]).replace("\r\n", "\n")
    new_s = str(inp["new_string"]).replace("\r\n", "\n")
    count = text.count(old_s)
    if count == 0:
        return (
            f"[ERROR] old_string not found in {rel}. Check for whitespace differences."
        )
    if count > 1:
        return f"[ERROR] old_string appears {count} times in {rel} — must be unique. Add more context."
    try:
        write_text_lf(target, text.replace(old_s, new_s, 1), nl_style)
        return f"Edited {rel}"
    except Exception as e:
        return f"[ERROR] Cannot write {rel}: {e}"
