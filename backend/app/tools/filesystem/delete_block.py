"""delete_block tool — tool_enhance.md productionization pass, tool #33
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: delete_block
Old path: app/agents/tools.py (`_DELETE_BLOCK_TOOL` schema dict and the
    `delete_block_h` handler inside `make_chat_handlers()` — no
    chat_agent.py dispatch existed at all before this pass)
New path: app/tools/filesystem/delete_block.py (this file) —
    `DELETE_BLOCK_TOOL`, `delete_block_handler`.
Affected agents: 1 per tool_inventory.json. `delete_block` is advertised
    in `CHAT_TOOLS` (chat_agent's own tool list), so `chat_agent` is one
    of them — but its real dispatch never had a branch for it (same
    class as tools #22/#25/#32); every real call fell through to the
    generic "[ERROR] Unknown tool: delete_block" response.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (gains a
    real dispatch branch for the first time).
Affected registries: none — app/fleet/tool_manifest.py's "delete_block"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["delete_block"](...)`. New tests added: see
    tests/test_delete_block_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/delete_block.md.
---------------------------------------------------------------------------

Real finding: "advertised but never dispatched" (same class as tools
#22/#25/#32) — verified directly, a real call returned the generic
"[ERROR] Unknown tool: delete_block" fallback.

The existing implementation's worktree-boundary check was already
correct (`_is_protected_path(path, repo_path)`, worktree argument
present) — re-verified directly this turn, not assumed.

Deferred finding (documented, not fixed this turn): `start_pattern`/
`end_pattern` are LLM-controlled regexes passed straight to
`re.search()` per line, with no timeout — Python's stdlib `re` module has
no built-in ReDoS (catastrophic backtracking) protection, and unlike
every subprocess-based grep-pattern tool in this codebase (which at
least has a hard subprocess timeout as a backstop), an in-process
`re.search()` call has no such backstop at all. A sufficiently
pathological pattern against a sufficiently long line could hang the
worker thread indefinitely. Not fixed here because a real fix (a
regex-execution timeout) has no clean stdlib primitive in Python and
would need either a separate-process/thread-with-timeout wrapper or a
third-party dependency (e.g. the `regex` module's timeout support) —
real design work belonging to its own turn, not a one-line addition.
Logged here rather than silently ignored.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
from app.tools.filesystem._textio import (
    read_text_lf,
    write_text_lf,
)

DELETE_BLOCK_TOOL: dict[str, Any] = {
    "name": "delete_block",
    "description": "Delete all lines between (inclusive) start_pattern and end_pattern in a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "start_pattern": {
                "type": "string",
                "description": "Pattern marking the start of the block to delete",
            },
            "end_pattern": {
                "type": "string",
                "description": "Pattern marking the end of the block to delete",
            },
        },
        "required": ["path", "start_pattern", "end_pattern"],
    },
}


def delete_block_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    path = str(inp["path"])
    start_pat = str(inp["start_pattern"])
    end_pat = str(inp["end_pattern"])
    if _is_protected_path(path, worktree_path):
        return f"[BLOCKED] {path} is a protected path"
    fpath = root / path
    try:
        text, nl_style = read_text_lf(fpath)
        lines = text.splitlines(keepends=True)
        new_lines: list[str] = []
        in_block = False
        deleted = 0
        for line in lines:
            if not in_block and re.search(start_pat, line):
                in_block = True
                deleted += 1
                continue
            if in_block:
                deleted += 1
                if re.search(end_pat, line):
                    in_block = False
                continue
            new_lines.append(line)
        if deleted == 0:
            return f"[WARN] Block pattern not found in {path}"
        if in_block:
            # end_pattern never matched after the last start_pattern: this used to
            # silently delete everything to end-of-file and report success.
            return (
                f"[ERROR] end_pattern {end_pat!r} was not found after the block "
                f"starting at pattern {start_pat!r} in {path} — nothing was deleted. "
                "Fix end_pattern (or use delete_lines with an explicit range)."
            )
        write_text_lf(fpath, "".join(new_lines), nl_style)
        return (
            f"Deleted {deleted} lines between '{start_pat}' and '{end_pat}' in {path}"
        )
    except Exception as e:
        return f"[ERROR] delete_block: {e}"
