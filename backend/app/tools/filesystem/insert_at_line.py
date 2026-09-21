"""insert_at_line tool — tool_enhance.md productionization pass, tool
#47 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: insert_at_line
Old path: app/agents/tools.py (`_INSERT_AT_LINE_TOOL` schema dict and
    the `insert_at_line` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body — already correct,
    identical logic to the tools.py handler).
New path: app/tools/filesystem/insert_at_line.py (this file) —
    `INSERT_AT_LINE_TOOL`, `insert_at_line_handler`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other
    agent declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; handler now
    delegates to the shared implementation), app/agents/chat_agent.py
    (dispatch now delegates to the same shared implementation instead
    of duplicating it).
Affected registries: none — app/fleet/tool_manifest.py's
    "insert_at_line" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_insert_at_line_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/insert_at_line.md.
---------------------------------------------------------------------------

No security vulnerability found: both real implementations were
already identical and already correct on the security axis —
`_is_protected_path(path, repo_path)` is called with `repo_path` passed
as `worktree_path`, enabling full `check_path_in_worktree()`
containment checking — the worktree-boundary fix already applied here
during tool #11's cross-cutting audit (2026-08-17), confirmed still
present and re-verified live (rejects both `.env` and an absolute
outside-repo path). `CHAT_TOOLS.count("insert_at_line") == 1` verified
— no duplicate-advertisement risk.

**Real, empirically-proven functionality bug found instead** (both
implementations, identical): the schema documents `line: 0` as "Use 0
to prepend," but the original logic —
`insert_at = max(0, line_num - 1) if line_num > 0 else len(file_lines)`
— sent `line_num <= 0` to `len(file_lines)`, i.e. the END of the file,
the exact opposite of the documented contract. Proved live: inserting
with `line=0` into a real 2-line file placed the new content AFTER
both existing lines instead of before them. Fixed: `line_num <= 0` now
maps to `insert_at = 0` (a genuine prepend); a `line_num` exceeding the
file's length still clamps to the end (unchanged, sensible existing
behavior, not part of the bug).

This turn is otherwise pure modularization/consolidation: the two
previously independently-maintained, byte-for-byte-identical copies of
this handler are now one shared function, closing the risk of them
silently drifting apart in the future (the exact failure mode multiple
earlier tools in this initiative found between their own real
implementations).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
from app.tools.filesystem._textio import (
    read_text_lf,
    write_text_lf,
)

INSERT_AT_LINE_TOOL = {
    "name": "insert_at_line",
    "description": "Insert content at a specific line number in a file. Existing content shifts down.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "line": {
                "type": "integer",
                "description": "1-indexed line to insert before. Use 0 to prepend.",
            },
            "content": {"type": "string", "description": "Content to insert"},
        },
        "required": ["path", "line", "content"],
    },
}


def insert_at_line_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Shared implementation used by both real call sites (chat_agent.py's
    dispatch and make_chat_handlers())."""
    rel = str(inp["path"])
    line_num = int(inp["line"])
    content = str(inp["content"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot write to protected path: {rel}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        text, nl_style = read_text_lf(target)
        file_lines = text.splitlines(keepends=True)
        insert_at = min(line_num - 1, len(file_lines)) if line_num > 0 else 0
        ins_content = content if content.endswith("\n") else content + "\n"
        file_lines.insert(insert_at, ins_content)
        write_text_lf(target, "".join(file_lines), nl_style)
        return f"Inserted at line {line_num} in {rel}"
    except Exception as e:
        return f"[ERROR] {e}"
