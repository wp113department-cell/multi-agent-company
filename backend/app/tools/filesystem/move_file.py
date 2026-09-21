"""move_file tool — tool_enhance.md productionization pass, tool
#52 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: move_file
Old path: app/agents/tools.py (`_MOVE_FILE_TOOL` schema dict and the
    `move_file_h` handler inside `make_chat_handlers()`) — already in
    CHAT_TOOLS but with NO app/agents/chat_agent.py dispatch.
New path: app/tools/filesystem/move_file.py (this file) —
    `MOVE_FILE_TOOL`, `move_file_handler`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists — same "advertised but never dispatched" bug class as
    tools #4/#6/#22/#25/#33/#44/#45/#46/#48/#50/#51. Verified
    `CHAT_TOOLS.count("move_file") == 1` directly before making any
    change.
Affected modules: app/agents/tools.py (schema re-export;
    `move_file_h` now calls the shared, hardened handler),
    app/agents/chat_agent.py (NEW real dispatch branch).
Affected registries: none — app/fleet/tool_manifest.py's "move_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_move_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/move_file.md.
---------------------------------------------------------------------------

Real, severe finding (same class as tool #11's `copy_file` finding —
"never validated `from_path` at all... a real cross-repo exfiltration
primitive" — but worse here, since a MOVE also deletes the original):
the only real implementation validated `dest` via
`_is_protected_path(dest, repo_path)` (already correctly enforcing
`check_path_in_worktree()` containment, since `repo_path` is passed as
`worktree_path` — re-verified live, an absolute outside-repo `dest` is
correctly rejected), but **`source` was never validated at all**.

Proved live: `source="/tmp/td_movefile_outside/secret.txt"` (an
absolute path to a real file completely outside the target repo) with
`dest="exfiltrated.txt"` succeeded — `shutil.move()` genuinely relocated
the file into the repo, and **the original file at its source location
was destroyed** (confirmed via a real empty-directory listing
afterward). This is a real arbitrary-file exfiltration primitive that
is also destructive at the source — strictly worse than `copy_file`'s
already-fixed finding, since `copy_file` at least leaves the original
file intact.

Fixed via a shared `move_file_handler()` that validates BOTH `source`
and `dest` through `_is_protected_path(..., repo_path)` before ever
calling `shutil.move()`, mirroring the exact fix already applied to
`copy_file`'s `from_path`/`to_path` pair during tool #11's cross-cutting
audit.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path


def destination_exists(path: Path) -> bool:
    """True if `path` exists or is a (possibly dangling) symlink."""
    return path.exists() or path.is_symlink()


MOVE_FILE_TOOL: dict[str, object] = {
    "name": "move_file",
    "description": "Move a file or directory to a new path (mv semantics, can move across directories).",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Source path (relative to repo root)",
            },
            "dest": {
                "type": "string",
                "description": "Destination path (relative to repo root)",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Replace the destination if it already exists (default false: refuses). In the interactive chat this asks the user to confirm.",
            },
        },
        "required": ["source", "dest"],
    },
}


def move_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Shared implementation used by both real call sites (chat_agent.py's
    dispatch and make_chat_handlers())."""
    source = str(inp["source"])
    dest = str(inp["dest"])
    if _is_protected_path(source, worktree_path):
        return f"[POLICY DENIED] Cannot move from protected path: {source}"
    if _is_protected_path(dest, worktree_path):
        return f"[POLICY DENIED] Cannot move to protected path: {dest}"
    src_path = root / source
    dst_path = root / dest
    try:
        final_dst = dst_path / src_path.name if dst_path.is_dir() else dst_path
        dest_label = dest
        # Refuse to silently clobber an existing destination (Path.rename and
        # shutil.copy2/move overwrite without a word — proved live: chat's
        # move/rename/copy replaced an existing file with NO confirmation, unlike
        # write_file). Interactive chat asks the user first and then passes
        # overwrite=true; a caller that passes it explicitly takes responsibility.
        if destination_exists(final_dst) and inp.get("overwrite") is not True:
            return (
                f"[ERROR] Destination already exists: {dest_label} — refusing to "
                "overwrite it silently. Pass overwrite=true to replace it "
                "(the interactive chat asks the user to confirm first)."
            )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return f"Moved {source} → {dest}"
    except Exception as e:
        return f"[ERROR] move_file: {e}"
