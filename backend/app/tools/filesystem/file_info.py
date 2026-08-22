"""file_info tool — tool_enhance.md productionization pass, tool #72
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: file_info
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[8]` schema dict and the
    `file_info` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a SEPARATE, unprotected inline dispatch
    body).
New path: app/tools/filesystem/file_info.py (this file) —
    `FILE_INFO_TOOL`, `file_info_handler`.
Affected agents: per tool_inventory.json, 69 agents declare `file_info`
    in `allowed_tools` — same shape as tools #65/#67/#68/#70/#71, NOT
    69 separate implementations: every `run_agent_graph`-based agent
    and `make_chat_handlers()` reach it through the same canonical
    `make_read_only_handlers()` factory; only `chat_agent`'s own
    interactive dispatch was a genuinely separate, unprotected
    duplicate.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[8]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `file_info` closure now delegates to the shared
    handler), app/agents/chat_agent.py (its real dispatch now calls the
    same shared, protected handler).
Affected registries: none — app/fleet/tool_manifest.py's "file_info"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["file_info"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_file_info_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/file_info.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape, `chat_agent.py`'s dispatch only.** Zero
   `check_path_in_worktree()` call. Proved live:
   `file_info({"path": "/etc/passwd"})` through
   `ChatAgent._execute_tool` genuinely returned the real size, type,
   line count, and last-modified time of a host file completely
   outside the repo — a real metadata-disclosure primitive (the same
   pathlib bug class as tools #10/#11/#18/#23/#43/#59/#61/#62/#64/#65/
   #67/#68/#69/#70/#71). Since `stat()` only requires execute
   permission on parent directories (not read permission on the file
   itself), this can disclose size/mtime for files whose CONTENT the
   caller could never read directly — a real, if narrower, oracle even
   for permission-restricted paths.

2. **An uncaught `PermissionError`, on BOTH implementations, including
   the canonical one — the same finding class as tool #70
   (`file_exists`)'s finding #2, independently discovered here.**
   Neither wraps `p.exists()`/`p.stat()` in a try/except. Proved live
   with a real file inside a `chmod 000` parent directory: both
   implementations raised the same uncaught `PermissionError`.

Fixed via a shared `file_info_handler()`: `check_path_in_worktree()`
closes finding #1; a `try/except PermissionError` around the whole
stat-and-read sequence closes finding #2, returning a clear
`[ERROR] Permission denied: {rel}` — matching this tool's own existing
`[ERROR]`-prefixed error-reporting style (unlike `file_exists`'s
narrower 3-state contract, `file_info` already reports errors this
way, so a dedicated permission-denied message is the more informative,
consistent choice here rather than reusing `file_exists`'s
graceful-degrade-to-`"not_found"` pattern).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FILE_INFO_TOOL = {
    "name": "file_info",
    "description": "Get metadata about a file: size in bytes, line count, last modified time, and language detected from extension.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
        },
        "required": ["path"],
    },
}


def file_info_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core file_info logic shared by both real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    p = root / rel
    try:
        if not p.exists():
            return f"[ERROR] Not found: {rel}"

        stat = p.stat()
        size = stat.st_size
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(
            timespec="seconds"
        )
        kind = "directory" if p.is_dir() else "file"
        lines = ""
        if p.is_file():
            try:
                lines = f"\nlines: {len(p.read_text(encoding='utf-8', errors='replace').splitlines())}"
            except Exception:
                pass
        ext = p.suffix or "(no extension)"
        return f"path: {rel}\ntype: {kind}\nsize: {size} bytes\nextension: {ext}{lines}\nmodified: {mtime}"
    except PermissionError:
        return f"[ERROR] Permission denied: {rel}"
