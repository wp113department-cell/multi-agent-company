"""loc_stats tool — tool_enhance.md productionization pass, tool
#166 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: loc_stats
Old path: app/agents/tools.py (`_LOC_STATS_TOOL` schema dict,
    `loc_stats_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/loc_stats.py (this file) —
    `LOC_STATS_TOOL`, `loc_stats_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `loc_stats` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`loc_stats_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's "loc_stats"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_loc_stats_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/loc_stats.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine LINE-COUNT-STATISTICS
   DISCLOSURE oracle.** `loc_stats_h` built `root / directory` without
   ever validating it stayed inside the worktree — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158.
   Proved live: `loc_stats({"directory": "/tmp/<outside dir>"})`
   genuinely disclosed real per-file-extension line-count statistics
   for a directory entirely outside the intended worktree — a
   real structure/metadata disclosure primitive (not raw content, but
   a genuine oracle revealing the real composition of a directory the
   caller has no business seeing).
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165.**
   `loc_stats` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: loc_stats"`.

Fixed via a shared `loc_stats_handler()`: `directory` is now
validated with `check_path_in_worktree()` before any filesystem
traversal, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

LOC_STATS_TOOL: dict[str, Any] = {
    "name": "loc_stats",
    "description": "Lines-of-code statistics for the repo broken down by file extension/language.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory to scan (default: repo root)",
            },
        },
        "required": [],
    },
}


def loc_stats_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core loc_stats logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `directory`."""
    directory = str(inp.get("directory", "."))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / directory
    totals: dict[str, int] = {}
    try:
        for fp in target.rglob("*"):
            if fp.is_file() and not any(
                p in str(fp) for p in [".git", "__pycache__", "node_modules", ".venv"]
            ):
                ext = fp.suffix or "(no ext)"
                try:
                    n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                    totals[ext] = totals.get(ext, 0) + n
                except Exception:
                    pass
        rows = sorted(totals.items(), key=lambda x: -x[1])[:20]
        out = "\n".join(f"{ext:15} {n:>8,}" for ext, n in rows)
        return f"{'Extension':15} {'Lines':>8}\n{'-' * 25}\n{out}\n{'':15} {sum(totals.values()):>8,} total"
    except Exception as e:
        return f"[ERROR] loc_stats: {e}"
