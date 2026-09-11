"""find_file tool — tool_enhance.md productionization pass, tool #138
(2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_file
Old path: app/agents/tools.py (`_FIND_FILE_TOOL` schema dict) with TWO
    real, byte-identical implementations: `find_file` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (an exact copy of the same logic).
New path: app/tools/filesystem/find_file.py (this file) —
    `FIND_FILE_TOOL`, `find_file_handler`. BOTH real call sites now
    delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring `find_file`
    in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "find_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_find_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_file.md.
---------------------------------------------------------------------------

One real, severe finding — a worktree-boundary escape via `directory`
on BOTH real implementations, a genuine FILENAME/DIRECTORY-STRUCTURE
DISCLOSURE oracle (not file content, but the existence and full paths
of files anywhere on the host the process can read). `ff_root = root /
ff_dir if ff_dir else root` never checked whether `ff_dir` was already
absolute — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137 this initiative.
Proved live: `find_file({"name": "<marker>", "directory":
"/tmp/<outside dir>"})` genuinely returned the real, full absolute
path of a marker file placed entirely outside the intended worktree.

Fixed via a shared `find_file_handler()`: `directory` is validated
with `check_path_in_worktree()` before being used to build the `find`
search root, closing the finding. Both real call sites now delegate to
this one handler.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FIND_FILE_TOOL: dict[str, Any] = {
    "name": "find_file",
    "description": "Find files by name or glob pattern across the repository. Faster than list_files when you know the filename.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Filename or pattern to find (e.g. 'config.py', '*.json', 'test_*.py')",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search (default: repo root)",
            },
        },
        "required": ["name"],
    },
}


def find_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core find_file logic shared by both real call sites."""
    name = str(inp["name"])
    ff_dir = str(inp.get("directory", ""))

    if ff_dir:
        policy = check_path_in_worktree(ff_dir, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        ff_root = root / ff_dir
    else:
        ff_root = root

    try:
        r = subprocess.run(
            [
                "find",
                str(ff_root),
                "-name",
                name,
                "-not",
                "-path",
                "*/node_modules/*",
                "-not",
                "-path",
                "*/__pycache__/*",
                "-not",
                "-path",
                "*/.git/*",
                "-not",
                "-path",
                "*/.venv/*",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        found = [ln for ln in r.stdout.splitlines() if ln.strip()]
        if not found:
            return f"(no files matching '{name}')"
        rel_paths = []
        for p in found[:100]:
            try:
                rel_paths.append(str(Path(p).relative_to(root)))
            except ValueError:
                rel_paths.append(p)
        return "\n".join(rel_paths)
    except subprocess.TimeoutExpired:
        return "[ERROR] find timed out"
    except Exception as e:
        return f"[ERROR] {e}"
