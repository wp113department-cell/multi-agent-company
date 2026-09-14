"""generate_api_docs_text tool — tool_enhance.md productionization
pass, tool #144 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: generate_api_docs_text
Old path: app/agents/tools.py (`_GENERATE_API_DOCS_TEXT_TOOL` schema
    dict, `generate_api_docs_text_h` inside `make_chat_handlers()` —
    the one real implementation).
New path: app/tools/filesystem/generate_api_docs_text.py (this file)
    — `GENERATE_API_DOCS_TEXT_TOOL`, `generate_api_docs_text_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `generate_api_docs_text` in `allowed_tools` (plus interactive
    chat, newly — see finding #2).
Affected modules: app/agents/tools.py (`generate_api_docs_text_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "generate_api_docs_text" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_generate_api_docs_text_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/generate_api_docs_text.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine ROUTE/FUNCTION-NAME
   disclosure oracle.** `generate_api_docs_text_h` built `root /
   route_path` without checking whether `route_path` was already
   absolute — the same `pathlib`-silently-discards-`root`-for-an-
   absolute-right-operand class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143
   this initiative. Proved live:
   `generate_api_docs_text({"route_path": "/tmp/<outside file>"})`
   genuinely disclosed a real route decorator's path AND the handler
   function's name from a file entirely outside the intended
   worktree — a real capability/structure-disclosure primitive, even
   though it's not full raw file content.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142.**
   `generate_api_docs_text` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: generate_api_docs_text"`.

Fixed via a shared `generate_api_docs_text_handler()`: `route_path` is
validated with `check_path_in_worktree()` before any filesystem
access, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

GENERATE_API_DOCS_TEXT_TOOL: dict[str, Any] = {
    "name": "generate_api_docs_text",
    "description": "Parse a FastAPI route file and return a structured markdown template of all endpoints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "route_path": {
                "type": "string",
                "description": "Relative path to the FastAPI router file",
            }
        },
        "required": ["route_path"],
    },
}


def generate_api_docs_text_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core generate_api_docs_text logic — the one real
    implementation, reused unchanged in behavior except for the
    worktree-boundary check now applied to `route_path`."""
    route_path = str(inp["route_path"])
    policy = check_path_in_worktree(route_path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fp = root / route_path
    if not fp.exists():
        return f"[ERROR] File not found: {route_path}"
    try:
        text = fp.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ERROR] {e}"

    lines = text.splitlines()
    endpoints: list[str] = []
    for i, line in enumerate(lines):
        m = re.match(
            r'\s*@\w+\.(get|post|put|patch|delete|options|head)\s*\("([^"]+)"', line
        )
        if m:
            method = m.group(1).upper()
            path_val = m.group(2)
            func_name = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                fm = re.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[j])
                if fm:
                    func_name = fm.group(1)
                    break
            endpoints.append(
                f"### {method} {path_val}\n**Function:** `{func_name}`\n\n"
                f"**Description:** _TODO_\n\n**Request:** _TODO_\n\n"
                f"**Response:** _TODO_\n"
            )
    if not endpoints:
        return "(no FastAPI route decorators found)"
    return "\n".join(endpoints)
