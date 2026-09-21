"""write_file tool — tool_enhance.md productionization pass, tool #12
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: write_file (the generic, unscoped variant — not the *.md/docs/**-only
    variant used by doc-generation agents, which keeps its own distinct
    schema/handler; see "Deliberately left untouched" below)
Old path: app/agents/tools.py (`_WRITE_FILE_TOOL_SPEC` schema dict, the
    duplicate schema at line ~856, and the write logic duplicated inline
    across `_make_write_file_handler`, `make_chat_handlers()`'s own
    `write_file`, and `make_fleet_apply_handlers()`'s `write_file_h`)
New path: app/tools/filesystem/write_file.py (this file) —
    `WRITE_FILE_TOOL`, `write_file_handler`.
Affected agents: ~60 per tool_inventory.json — every agent built on
    `make_chat_handlers()` (~35 one-shot batch agents), every agent using
    `_make_write_file_handler` (5 factories: gap-closure Day2 handler
    sets), the 4 fleet self-enhancement agents via
    `make_fleet_apply_handlers()`, and `chat_agent`'s own interactive
    dispatch (all 1 real user-facing agent).
Affected modules: app/agents/tools.py (compatibility re-export + delegates
    `_make_write_file_handler`/`make_chat_handlers`'s write_file/
    `make_fleet_apply_handlers`'s write_file_h's non-role-prompt branch to
    the shared handler), app/agents/chat_agent.py (its real dispatch now
    calls `write_file_handler` after its own existence/confirm gate
    instead of duplicating the write logic inline).
Affected registries: none — app/fleet/tool_manifest.py's "write_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every real test accesses this
    tool via `handlers["write_file"](...)` or `ChatAgent._execute_tool`,
    both unchanged externally. New tests added: see
    tests/test_write_file_hardening.py.

Deliberately left untouched (audited during this turn, found already
correctly guarded, NOT modularized to avoid unnecessary rewrite of
working, tested code for tools with genuinely different scoping policies
layered on top of the base write):
- `make_coder_handlers`'s `write_file` (tools.py line ~1559) — generic,
  already uses `check_path_in_worktree` correctly.
- `make_doc_generator_handlers`'s `dg_write_file` / `make_docs_handlers`'s
  `write_file` / `make_readme_agent_handlers`'s `rm_write_file` /
  `make_api_docs_agent_handlers`'s `ad_write_file` — all four restrict
  writes to `*.md` / `docs/**` on top of the same worktree check; this is
  a real, intentional policy difference from the generic tool (reflected
  in DOCS_TOOLS' own distinct schema description at tools.py line ~2371),
  not accidental duplication.
- `make_migration_agent_handlers`'s `mg_write_file` — restricts to
  `migrations/`/`backend/migrations/`/`*.py`, same rationale.
- `make_schema_architect_handlers`'s `sa_write_file` /
  `make_ai_engineer_handlers`'s `ae_write_file` — generic but already
  correctly guarded (`_is_protected_path(rel, repo_path)`).

Runtime verification: PASS — see
    backend/docs/tool_productionization/write_file.md.
---------------------------------------------------------------------------

Real finding (full detail in the tool #11/undo_changes report,
docs/tool_productionization/undo_changes.md — this tool's own severest
bug was found and fixed during that tool's cross-cutting audit, not this
one): `chat_agent.py`'s real dispatch called `_is_protected_path(rel)`
WITHOUT its `worktree_path` argument, so an absolute or `../`-traversing
`path` reached this write completely unvalidated — proved directly with a
real file written outside the target repo, with zero confirmation gate
(the confirm-on-overwrite branch only fires when the target already
exists). Already fixed as of that tool's turn; this turn's own audit of
every OTHER real write_file implementation in the codebase found no
further instances of the same bug (see "Deliberately left untouched"
above) — this turn's job was modularizing the now-correct code, not
finding a new vulnerability.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
from app.tools.filesystem._textio import adapt_to_style, existing_newline_style

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": (
        "Write full content to a file (creates or completely overwrites). "
        "Use edit_file instead when modifying an existing file. "
        "Only use write_file for NEW files or when you need to fully replace a file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to worktree root",
            },
            "content": {
                "type": "string",
                "description": "Complete file content to write",
            },
        },
        "required": ["path", "content"],
    },
}


def write_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core write_file logic shared by every generic (unscoped) real call
    site. Callers with their own extra scoping policy (docs-only,
    migrations-only, ...) run their own check first and only reach this
    function once that check has already passed — this function still
    re-checks the worktree/denylist itself (`_is_protected_path`) so it is
    safe to call directly, not just as a second layer.

    Callers that need a pre-write confirmation gate (chat_agent.py's real
    dispatch, when the target already exists) run that gate themselves
    before calling this — this function performs the write unconditionally
    once called."""
    rel = str(inp["path"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot write to protected path: {rel}"
    content = str(inp["content"])
    target = root / rel
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Overwriting a CRLF file with LF content keeps the file CRLF (no
        # whole-file line-ending churn); new files are written exactly as given.
        data = adapt_to_style(content, existing_newline_style(target))
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(data)
        return f"Written {rel} ({len(data.encode('utf-8'))} bytes)"
    except Exception as e:
        return f"[ERROR] Cannot write {rel}: {e}"
