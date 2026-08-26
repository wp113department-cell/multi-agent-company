"""compare_files tool — tool_enhance.md productionization pass, tool
#127 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: compare_files
Old path: app/agents/tools.py (`_COMPARE_FILES_TOOL` schema dict) with
    TWO real, byte-identical implementations: `compare_files` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (an exact copy of the same logic).
New path: app/tools/filesystem/compare_files.py (this file) —
    `COMPARE_FILES_TOOL`, `compare_files_handler`. BOTH real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `compare_files` in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "compare_files" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_compare_files_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/compare_files.md.
---------------------------------------------------------------------------

Two real findings, on BOTH real implementations (byte-identical).

1. **Severe — a worktree-boundary escape that is a genuine TWO-FILE
   ARBITRARY READ.** Neither implementation validated `path_a`/
   `path_b` before `root / path_a` — the same `pathlib`-silently-
   discards-`root`-for-an-absolute-right-operand class already
   documented for tools #99/#107/#116/#120/#122 this initiative, but
   doubled here since the tool's whole purpose is to disclose the
   CONTENT of two files side by side. Proved live: `compare_files({
   "path_a": "/tmp/outside1.txt", "path_b": "/tmp/outside2.txt"})`
   genuinely produced a real unified diff of two files entirely
   outside the intended worktree, disclosing both files' full content.
2. **A real robustness gap — an uncaught crash on a non-numeric
   `context`.** `int(inp.get("context", 3))` was never wrapped in a
   `try/except`, matching the class already fixed for tool #78's
   `git_log` (`count`). Proved live: `context="not_a_number"` raised
   an unhandled `ValueError` straight out of the handler.

Fixed via a shared `compare_files_handler()`: both `path_a` and
`path_b` are validated with `check_path_in_worktree()` before any
filesystem access, closing finding #1. `context` conversion is now
wrapped in `try/except` and clamped to `[0, 50]`, closing finding #2.
Both real call sites now delegate to this one handler.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

COMPARE_FILES_TOOL: dict[str, Any] = {
    "name": "compare_files",
    "description": "Show a unified diff between two files. Useful for comparing versions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path_a": {
                "type": "string",
                "description": "First file path relative to repo root",
            },
            "path_b": {
                "type": "string",
                "description": "Second file path relative to repo root",
            },
            "context": {
                "type": "integer",
                "description": "Lines of context around changes (default: 3)",
            },
        },
        "required": ["path_a", "path_b"],
    },
}


def compare_files_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core compare_files logic shared by both real call sites."""
    rel_a = str(inp["path_a"])
    rel_b = str(inp["path_b"])
    try:
        context = max(0, min(int(inp.get("context", 3)), 50))
    except (TypeError, ValueError):
        return f"[ERROR] context must be an integer, got {inp.get('context')!r}"

    policy_a = check_path_in_worktree(rel_a, worktree_path)
    if not policy_a.allowed:
        return f"[POLICY DENIED] {policy_a.reason}"
    policy_b = check_path_in_worktree(rel_b, worktree_path)
    if not policy_b.allowed:
        return f"[POLICY DENIED] {policy_b.reason}"

    cf_a = root / rel_a
    cf_b = root / rel_b
    if not cf_a.exists():
        return f"[ERROR] File not found: {rel_a}"
    if not cf_b.exists():
        return f"[ERROR] File not found: {rel_b}"
    r = subprocess.run(
        ["diff", f"-U{context}", str(cf_a), str(cf_b)],
        capture_output=True,
        text=True,
    )
    return r.stdout[:8000] or "Files are identical"
