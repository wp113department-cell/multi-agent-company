"""count_lines tool — tool_enhance.md productionization pass, tool
#129 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: count_lines
Old path: app/agents/tools.py (`_COUNT_LINES_TOOL` schema dict,
    `count_lines_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/count_lines.py (this file) —
    `COUNT_LINES_TOOL`, `count_lines_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `count_lines` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`count_lines_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "count_lines" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_count_lines_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/count_lines.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine ARBITRARY FILE/DIRECTORY
   READ.** `count_lines_h` built `root / path` without checking
   whether `path` was already absolute — the same `pathlib`-silently-
   discards-`root`-for-an-absolute-right-operand class already
   documented for tools #99/#107/#116/#120/#122/#127 this initiative.
   Proved live: `count_lines({"path": "/tmp/<outside file>"})`
   genuinely read a file outside the intended worktree and returned
   its real line count — a real disclosure oracle. In directory mode,
   this is worse: an absolute directory `path` combined with `pattern`
   would glob and read line counts for every matching file under an
   arbitrary host directory.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/#110/#112/#118/#120/#122/#126.**
   `count_lines` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: count_lines"`.

Fixed via a shared `count_lines_handler()`: `path` is validated with
`check_path_in_worktree()` before any filesystem access, closing
finding #1. A new `chat_agent.py` dispatch branch delegates to this
same shared handler, closing finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

COUNT_LINES_TOOL: dict[str, Any] = {
    "name": "count_lines",
    "description": "Count lines in a file or all files in a directory matching a pattern.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path (relative to repo root)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern for directory mode (e.g. '**/*.py')",
            },
        },
        "required": ["path"],
    },
}


def count_lines_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core count_lines logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path`."""
    path = str(inp["path"])
    pattern = str(inp.get("pattern", "**/*"))

    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / path
    try:
        if target.is_file():
            count = sum(1 for _ in target.open(encoding="utf-8", errors="ignore"))
            return f"{path}: {count} lines"
        totals: dict[str, int] = {}
        for fp in target.glob(pattern):
            if fp.is_file():
                ext = fp.suffix or "(no ext)"
                n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                totals[ext] = totals.get(ext, 0) + n
        rows = sorted(totals.items(), key=lambda x: -x[1])
        lines_out = "\n".join(f"{ext}: {n:,}" for ext, n in rows)
        return f"Lines by extension in {path}:\n{lines_out}\nTotal: {sum(totals.values()):,}"
    except Exception as e:
        return f"[ERROR] count_lines: {e}"
