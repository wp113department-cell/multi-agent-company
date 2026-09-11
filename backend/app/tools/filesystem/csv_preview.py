"""csv_preview tool — tool_enhance.md productionization pass, tool
#132 (2026-08-26... continued 2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: csv_preview
Old path: app/agents/tools.py (`_CSV_PREVIEW_TOOL` schema dict,
    `csv_preview_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/csv_preview.py (this file) —
    `CSV_PREVIEW_TOOL`, `csv_preview_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `csv_preview` in `allowed_tools` (plus interactive chat, newly —
    see finding #3).
Affected modules: app/agents/tools.py (`csv_preview_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's
    "csv_preview" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_csv_preview_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/csv_preview.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine ARBITRARY FILE READ.**
   `csv_preview_h` built `root / str(inp["path"])` without checking
   whether `path` was already absolute — the same `pathlib`-silently-
   discards-`root`-for-an-absolute-right-operand class already
   documented for tools #99/#107/#116/#120/#122/#127/#129 this
   initiative. Proved live: a `path` value outside the intended
   worktree was genuinely read, its header and row content returned
   verbatim.
2. **A real robustness gap — an uncaught crash on a non-numeric
   `rows`.** `int(inp.get("rows", 5))` was never wrapped in a
   `try/except`, matching the class already fixed for tools
   #78/#127/#130. Proved live: `rows="not_a_number"` raised an
   unhandled `ValueError`.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131.**
   `csv_preview` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: csv_preview"`.

Fixed via a shared `csv_preview_handler()`: `path` is validated with
`check_path_in_worktree()` before any filesystem access, closing
finding #1. `rows` conversion is now wrapped in `try/except` and
clamped to `[1, 200]`, closing finding #2. A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing finding
#3.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

CSV_PREVIEW_TOOL: dict[str, Any] = {
    "name": "csv_preview",
    "description": "Preview the first N rows of a CSV file, showing column names and sample data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "CSV file path (relative to repo root)",
            },
            "rows": {
                "type": "integer",
                "description": "Number of rows to preview (default: 5)",
            },
        },
        "required": ["path"],
    },
}


def csv_preview_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core csv_preview logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path` and the crash fix on `rows`."""
    rel = str(inp["path"])
    try:
        rows_n = max(1, min(int(inp.get("rows", 5)), 200))
    except (TypeError, ValueError):
        return f"[ERROR] rows must be an integer, got {inp.get('rows')!r}"

    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / rel
    try:
        with open(fpath, encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            rows: list[list[str]] = []
            for i, row in enumerate(reader):
                if i > rows_n:
                    break
                rows.append(row)
        if not rows:
            return "(empty CSV)"
        header = rows[0]
        out = ["Columns: " + ", ".join(header)]
        for row in rows[1:]:
            out.append(" | ".join(row))
        return "\n".join(out)
    except Exception as e:
        return f"[ERROR] csv_preview: {e}"
