"""generate_patch tool — tool_enhance.md productionization pass,
tool #147 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: generate_patch
Old path: app/agents/tools.py (`_GENERATE_PATCH_TOOL` schema dict)
    with TWO real, identical implementations: `generate_patch_h`
    (inside `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    separate dispatch.
New path: app/tools/filesystem/generate_patch.py (this file) —
    `GENERATE_PATCH_TOOL`, `generate_patch_handler`. BOTH real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `generate_patch` in `allowed_tools` (plus interactive chat, which
    already had a real, correctly-matching dispatch — unlike most
    other tools this initiative, this one was never missing its
    dispatch branch).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "generate_patch" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_generate_patch_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/generate_patch.md.
---------------------------------------------------------------------------

No LLM-controlled filesystem path anywhere in this tool's input schema
(only three strings: `content_a`, `content_b`, `filename`, all pure
in-memory `difflib.unified_diff()` inputs) — the worktree-boundary-
escape class established repeatedly this initiative does not apply
here: there is no filesystem access of any kind in either real
implementation, checked directly. No shell-injection risk either — no
subprocess is invoked anywhere in this tool.

No real bug found: both real implementations were confirmed, by direct
code comparison, to be byte-for-byte behaviorally identical (same
`difflib.unified_diff()` call, same `fromfile`/`tofile` header
convention, same "(no differences)" fallback for an empty diff), and
`generate_patch` was already correctly dispatched on both real access
paths — unlike most tools this initiative, chat_agent.py was never
missing this dispatch branch. The only real issue was maintenance
drift risk from two independently-hand-maintained copies of the same
logic; consolidated into this one shared handler per the mandatory
modularization rule for this initiative.
"""

from __future__ import annotations

import difflib
from typing import Any

GENERATE_PATCH_TOOL: dict[str, Any] = {
    "name": "generate_patch",
    "description": (
        "Generate a unified diff patch from two text contents using Python's difflib. "
        "Useful for previewing changes before applying them. Does NOT modify any files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content_a": {
                "type": "string",
                "description": "Original file content (the 'before' version)",
            },
            "content_b": {
                "type": "string",
                "description": "New file content (the 'after' version)",
            },
            "filename": {
                "type": "string",
                "description": "Filename shown in the patch header (default: 'file')",
            },
        },
        "required": ["content_a", "content_b"],
    },
}


def generate_patch_handler(inp: dict[str, Any]) -> str:
    """Core generate_patch logic shared by both real call sites — a
    pure in-memory unified diff, no filesystem access."""
    content_a = str(inp.get("content_a", ""))
    content_b = str(inp.get("content_b", ""))
    filename = str(inp.get("filename", "file"))
    diff = list(
        difflib.unified_diff(
            content_a.splitlines(keepends=True),
            content_b.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )
    return "".join(diff) if diff else "(no differences)"
