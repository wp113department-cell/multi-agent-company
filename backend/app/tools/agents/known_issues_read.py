"""known_issues_read tool — tool_enhance.md productionization pass,
tool #160 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: known_issues_read
Old path: app/agents/tools.py (`_KNOWN_ISSUES_READ_TOOL` schema dict,
    `known_issues_read_h` inside `make_chat_handlers()` — the one
    real implementation).
New path: app/tools/agents/known_issues_read.py (this file) —
    `KNOWN_ISSUES_READ_TOOL`, `known_issues_read_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `known_issues_read` in `allowed_tools` (plus interactive chat,
    newly — see the one real finding below).
Affected modules: app/agents/tools.py (`known_issues_read_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "known_issues_read" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_known_issues_read_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/known_issues_read.md.
---------------------------------------------------------------------------

The input schema is empty (no properties at all), and the file path
this tool reads (`known_issues_path`) is derived deterministically
from `repo_path` (an md5 slug of it) into a FIXED internal memory
directory (`app/memory/`) — never from any LLM-controlled input field.
No worktree-boundary-escape or injection surface exists here at all,
checked directly.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159.
`known_issues_read` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: known_issues_read"`.

Fixed via a shared `known_issues_read_handler()`; a new
`chat_agent.py` dispatch branch delegates to it, making
`known_issues_read` genuinely reachable from interactive chat for the
first time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

KNOWN_ISSUES_READ_TOOL: dict[str, Any] = {
    "name": "known_issues_read",
    "description": "Read the project's known issues file.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def known_issues_path(repo_path: str) -> Path:
    """The fixed, deterministic known-issues file path for a given
    repo — an md5 slug of `repo_path` inside the internal
    `app/memory/` directory, matching `known_issues_write_handler()`'s
    own derivation exactly so both read and write the same file."""
    mem_slug = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    mem_dir = Path(__file__).parent.parent.parent / "memory"
    mem_dir.mkdir(exist_ok=True)
    return mem_dir / f"{mem_slug}_known_issues.md"


def known_issues_read_handler(repo_path: str) -> str:
    """Core known_issues_read logic — the one real implementation,
    unchanged."""
    path = known_issues_path(repo_path)
    if not path.exists():
        return "(no known issues file yet)"
    return path.read_text(encoding="utf-8")
