"""insert_after tool — tool_enhance.md productionization pass, tool
#46 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: insert_after
Old path: app/agents/tools.py (`_INSERT_AFTER_TOOL` schema dict and the
    `insert_after_h` handler inside `make_chat_handlers()`) — already
    in CHAT_TOOLS but with NO app/agents/chat_agent.py dispatch.
New path: app/tools/filesystem/insert_after.py (this file) —
    `INSERT_AFTER_TOOL`, `insert_after_handler`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists — same "advertised but never dispatched" bug class as
    tools #4/#6/#22/#25/#33/#44/#45. Verified `CHAT_TOOLS.count(
    "insert_after") == 1` directly before making any change (lesson
    from tool #44's near-miss).
Affected modules: app/agents/tools.py (schema re-export;
    `insert_after_h` now delegates to the shared handler),
    app/agents/chat_agent.py (NEW real dispatch branch).
Affected registries: none — app/fleet/tool_manifest.py's
    "insert_after" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_insert_after_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/insert_after.md.
---------------------------------------------------------------------------

Finding: `chat_agent.py` had zero dispatch branch for `insert_after`
despite it being advertised via `CHAT_TOOLS` — every real interactive
call would have hit "[ERROR] Unknown tool".

The handler's own worktree-boundary handling was ALREADY correct: it
calls `_is_protected_path(path, repo_path)` — passing `repo_path` as
`worktree_path` — which per `_is_protected_path`'s own docstring
enables full `check_path_in_worktree()` containment checking (not just
the bare filename denylist). This is the same fix tool #11 already
applied here; re-verified, not re-fixed.

**Deferred finding (documented, not fixed — same class already
deferred for tool #33's `delete_block`, same reasoning applies
identically here):** `pattern` is an LLM-controlled string passed
directly to `re.search(pattern, line)` once per line of the target
file, with no timeout. Python's stdlib `re` module has no timeout
primitive, so closing this needs real design work (a subprocess-based
regex sandbox, `regex` module's timeout support, or a length/complexity
cap on `pattern`) rather than a small local patch — logged here for its
own future turn, exactly as tool #33's report already logs it for
`delete_block`'s identical `start_pattern`/`end_pattern` fields.

Fixed by adding a real `chat_agent.py` dispatch, delegating to the
existing, already-correct `insert_after_h` logic (moved here verbatim,
not rewritten) rather than either implementation duplicating it a
second time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path

INSERT_AFTER_TOOL: dict[str, object] = {
    "name": "insert_after",
    "description": "Insert lines of text immediately AFTER the first line matching a pattern in a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "pattern": {
                "type": "string",
                "description": "String or regex pattern to match",
            },
            "content": {
                "type": "string",
                "description": "Text to insert (can be multi-line)",
            },
        },
        "required": ["path", "pattern", "content"],
    },
}


def insert_after_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Shared implementation used by both real call sites (chat_agent.py's
    dispatch and make_chat_handlers())."""
    path = str(inp["path"])
    pattern = str(inp["pattern"])
    content = str(inp["content"])
    if _is_protected_path(path, worktree_path):
        return f"[BLOCKED] {path} is a protected path"
    fpath = root / path
    try:
        lines = fpath.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines: list[str] = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and re.search(pattern, line):
                new_lines.append(content if content.endswith("\n") else content + "\n")
                inserted = True
        if not inserted:
            return f"[WARN] Pattern '{pattern}' not found in {path}"
        fpath.write_text("".join(new_lines), encoding="utf-8")
        return f"Inserted {len(content.splitlines())} line(s) after pattern '{pattern}' in {path}"
    except Exception as e:
        return f"[ERROR] insert_after: {e}"
