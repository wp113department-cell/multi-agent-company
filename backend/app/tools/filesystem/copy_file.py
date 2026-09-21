"""copy_file tool — tool_enhance.md productionization pass, tool #128
(2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: copy_file
Old path: app/agents/tools.py (`_COPY_FILE_TOOL` schema dict) with TWO
    real, nearly-identical implementations: `copy_file` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/filesystem/copy_file.py (this file) —
    `COPY_FILE_TOOL`, `copy_file_handler`. BOTH real call sites now
    delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `copy_file` in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "copy_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_copy_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/copy_file.md.
---------------------------------------------------------------------------

Worktree-boundary validation on both `from_path` and `to_path` was
ALREADY correct on both real implementations
(`_is_protected_path(rel, repo_path)`, which — given `worktree_path` —
already performs full worktree-containment checking, not just the
filename denylist) — fixed 2026-08-17 during tool #11's (`undo_changes`)
cross-cutting audit, confirmed still correct here by direct inspection,
not assumed.

One real finding this turn — a robustness gap: `chat_agent.py`'s
dispatch had NO `try/except` around `dst.parent.mkdir()`/
`shutil.copy2()`, unlike `make_chat_handlers()`'s own implementation,
which already wraps the same operations. Proved live: copying into a
read-only destination directory raised an uncaught `PermissionError`
straight out of the dispatch (verified via `chmod 500` on a real
directory, not simulated).

Fixed via a shared `copy_file_handler()`: the entire filesystem
operation is wrapped in `try/except`, matching the already-correct
`make_chat_handlers()` design. Both real call sites now delegate to
this one handler.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path


def destination_exists(path: Path) -> bool:
    """True if `path` exists or is a (possibly dangling) symlink."""
    return path.exists() or path.is_symlink()


COPY_FILE_TOOL: dict[str, Any] = {
    "name": "copy_file",
    "description": "Copy a file to a new location within the repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_path": {
                "type": "string",
                "description": "Source file path relative to repo root",
            },
            "to_path": {
                "type": "string",
                "description": "Destination file path relative to repo root",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Replace the destination if it already exists (default false: refuses). In the interactive chat this asks the user to confirm.",
            },
        },
        "required": ["from_path", "to_path"],
    },
}


def copy_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core copy_file logic shared by both real call sites."""
    from_rel = str(inp["from_path"])
    to_rel = str(inp["to_path"])
    if _is_protected_path(from_rel, worktree_path):
        return f"[POLICY DENIED] Protected source: {from_rel}"
    if _is_protected_path(to_rel, worktree_path):
        return f"[POLICY DENIED] Protected destination: {to_rel}"
    src = root / from_rel
    dst = root / to_rel
    if not src.exists():
        return f"[ERROR] Source not found: {from_rel}"
    final_dst = dst / src.name if dst.is_dir() else dst
    dest_label = to_rel
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
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return f"Copied {from_rel} → {to_rel}"
    except Exception as e:
        return f"[ERROR] {e}"
