"""read_notebook tool — tool_enhance.md productionization pass, tool
#175 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_notebook
Old path: app/agents/tools.py (`_READ_NOTEBOOK_TOOL` schema dict,
    `read_notebook_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/read_notebook.py (this file) —
    `READ_NOTEBOOK_TOOL`, `read_notebook_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `read_notebook` in `allowed_tools` (plus interactive chat, newly
    — see finding #2).
Affected modules: app/agents/tools.py (`read_notebook_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "read_notebook" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_read_notebook_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_notebook.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle.** `read_notebook_h` built `root / path` without
   ever validating it stayed inside the worktree — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169/#170/#171/#174.
   Proved live: `read_notebook({"path": "/tmp/<outside .ipynb>"})`
   genuinely disclosed real code-cell source (including a hardcoded
   secret-shaped string) and markdown-cell content of a notebook
   entirely outside the intended worktree.
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174.**
   `read_notebook` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: read_notebook"`.

Fixed via a shared `read_notebook_handler()`: `path` is now validated
with `check_path_in_worktree()` before the file is ever read, closing
finding #1. A new `chat_agent.py` dispatch branch delegates to this
same shared handler, closing finding #2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

READ_NOTEBOOK_TOOL: dict[str, Any] = {
    "name": "read_notebook",
    "description": "Read a Jupyter notebook (.ipynb), returning each cell's type, source, and any text/error output — code and markdown cells in execution order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Notebook file path (relative to repo root)",
            },
            "max_cells": {
                "type": "integer",
                "description": "Maximum number of cells to include (default: 100)",
            },
        },
        "required": ["path"],
    },
}


def read_notebook_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core read_notebook logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path`."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    max_cells = int(inp.get("max_cells", 100))
    try:
        nb = json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[ERROR] read_notebook: {e}"
    cells = nb.get("cells", []) if isinstance(nb, dict) else []
    if not isinstance(cells, list) or not cells:
        return f"[ERROR] {path} has no readable 'cells' array (not a valid .ipynb?)"
    parts: list[str] = []
    for i, cell in enumerate(cells[:max_cells]):
        ctype = cell.get("cell_type", "unknown")
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        block = [f"--- Cell {i} ({ctype}) ---", str(source).rstrip()]
        for out_item in cell.get("outputs", []) or []:
            otype = out_item.get("output_type")
            if otype == "stream":
                text = out_item.get("text", "")
                if isinstance(text, list):
                    text = "".join(text)
                block.append(f"[output] {str(text).rstrip()}")
            elif otype == "error":
                block.append(
                    f"[error] {out_item.get('ename', '')}: {out_item.get('evalue', '')}"
                )
            elif otype in ("execute_result", "display_data"):
                text_out = out_item.get("data", {}).get("text/plain", "")
                if isinstance(text_out, list):
                    text_out = "".join(text_out)
                if text_out:
                    block.append(f"[result] {str(text_out).rstrip()}")
        parts.append("\n".join(block))
    remaining = len(cells) - min(len(cells), max_cells)
    result = f"Notebook: {path} ({len(cells)} cells)\n\n" + "\n\n".join(parts)
    if remaining > 0:
        result += f"\n\n[NOTICE] {remaining} additional cell(s) not shown (max_cells={max_cells})"
    return result
