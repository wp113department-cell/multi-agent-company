"""insert_before tool — tool_enhance.md productionization pass, tool
#48 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: insert_before
Old path: app/agents/tools.py (`_INSERT_BEFORE_TOOL` schema dict and
    the `insert_before_h` handler inside `make_chat_handlers()`) —
    already in CHAT_TOOLS but with NO app/agents/chat_agent.py dispatch.
New path: app/tools/filesystem/insert_before.py (this file) —
    `INSERT_BEFORE_TOOL`, `insert_before_handler`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists — same "advertised but never dispatched" bug class as
    tools #4/#6/#22/#25/#33/#44/#45/#46. Verified
    `CHAT_TOOLS.count("insert_before") == 1` directly before making any
    change.
Affected modules: app/agents/tools.py (schema re-export;
    `insert_before_h` now delegates to the shared handler),
    app/agents/chat_agent.py (NEW real dispatch branch).
Affected registries: none — app/fleet/tool_manifest.py's
    "insert_before" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_insert_before_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/insert_before.md.
---------------------------------------------------------------------------

Finding: identical shape to tool #46's `insert_after` (its exact
mirror-image sibling — insert BEFORE instead of AFTER a matching
pattern). `chat_agent.py` had zero dispatch branch for `insert_before`
despite it being advertised via `CHAT_TOOLS` — every real interactive
call would have hit "[ERROR] Unknown tool".

The handler's own worktree-boundary handling was ALREADY correct: it
calls `_is_protected_path(path, repo_path)` — passing `repo_path` as
`worktree_path` — enabling full `check_path_in_worktree()` containment
checking (tool #11's fix, re-verified here, not re-fixed).

**Deferred finding (documented, not fixed — same class already
deferred for tool #33's `delete_block` and tool #46's `insert_after`,
identical reasoning):** `pattern` is an LLM-controlled string passed
directly to `re.search(pattern, line)` once per line of the target
file, with no timeout. Python's stdlib `re` module has no timeout
primitive, so closing this needs real design work — logged here for its
own future turn, matching the two sibling reports exactly.

Fixed by adding a real `chat_agent.py` dispatch, delegating to the
existing, already-correct logic (moved here verbatim, not rewritten).
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

INSERT_BEFORE_TOOL: dict[str, object] = {
    "name": "insert_before",
    "description": "Insert lines of text immediately BEFORE the first line matching a pattern in a file.",
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


def insert_before_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Shared implementation used by both real call sites (chat_agent.py's
    dispatch and make_chat_handlers())."""
    path = str(inp["path"])
    pattern = str(inp["pattern"])
    content = str(inp["content"])
    if _is_protected_path(path, worktree_path):
        return f"[BLOCKED] {path} is a protected path"
    fpath = root / path
    try:
        text, nl_style = read_text_lf(fpath)
        lines = text.splitlines(keepends=True)
        new_lines: list[str] = []
        inserted = False
        for line in lines:
            if not inserted and re.search(pattern, line):
                new_lines.append(content if content.endswith("\n") else content + "\n")
                inserted = True
            new_lines.append(line)
        if not inserted:
            return f"[WARN] Pattern '{pattern}' not found in {path}"
        write_text_lf(fpath, "".join(new_lines), nl_style)
        return f"Inserted {len(content.splitlines())} line(s) before pattern '{pattern}' in {path}"
    except Exception as e:
        return f"[ERROR] insert_before: {e}"
