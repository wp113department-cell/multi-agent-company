"""rename_symbol tool — tool_enhance.md productionization pass, tool #23
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: rename_symbol
Old path: app/agents/tools.py (`_RENAME_SYMBOL_TOOL` schema dict; the
    validation logic below did not exist anywhere before this pass)
New path: app/tools/refactor/rename_symbol.py (this file) —
    `RENAME_SYMBOL_TOOL`, `validate_rename_symbol_directory`.
Affected agents: 2 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch and `refactor_agent` (via `rf_rename_symbol`).
    `make_chat_handlers`'s own `rename_symbol_h` is also reachable by any
    other agent declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `rf_rename_symbol`
    and `rename_symbol_h` both now call the shared validator before
    resolving `directory` — each site's own call into
    `app.repo_tools.ast_engine.rename_symbol` is otherwise untouched),
    app/agents/chat_agent.py (its real dispatch now calls the shared
    validator too).
Affected registries: none — app/fleet/tool_manifest.py's "rename_symbol"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["rename_symbol"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_rename_symbol_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/rename_symbol.md.
---------------------------------------------------------------------------

Real finding (severe — a proven, live cross-file rewrite outside the
repo): ALL 3 implementations resolved `directory` via `root / directory`
with ZERO worktree-boundary validation before passing it to
`app.repo_tools.ast_engine.rename_symbol()`, which `rglob()`s the given
directory for matching files and REWRITES every one that contains the
symbol. Proved directly, before writing any fix: a real file completely
outside the target repo (in a directory this test created and cleaned up
itself, never a real system path) had its contents rewritten by a
`rename_symbol` call with `directory` pointing outside the repo — a real,
live, multi-file arbitrary-rewrite primitive, broader in blast radius
than a single-file write bug since it recursively rewrites every
matching file under whatever directory it's pointed at.

Secondary, non-security finding: `make_chat_handlers`'s own
`rename_symbol_h` never passed `confirm_large_batch` through to the AST
engine at all, despite the schema documenting it as a real, LLM-settable
field — meaning that implementation could never apply a rename touching
more files than the safety threshold, even when the LLM explicitly
confirmed it should. Fixed as part of this same pass (fails safe, not a
security issue, but a real functionality gap against the tool's own
documented contract).
"""

from __future__ import annotations

from app.policy.engine import check_path_in_worktree


def validate_rename_symbol_directory(directory: str, worktree_path: str) -> str | None:
    """Returns a denial reason if `directory` would resolve outside
    `worktree_path`, else None. Empty/omitted `directory` means "repo
    root" and is always allowed, matching every real call site's own
    existing default-handling."""
    if not directory:
        return None
    result = check_path_in_worktree(directory, worktree_path)
    if not result.allowed:
        return result.reason
    return None


RENAME_SYMBOL_TOOL = {
    "name": "rename_symbol",
    "description": (
        "Rename a symbol (function, class, variable) across all matching files. "
        "For .py files, uses a token-based rename that skips occurrences inside "
        "string literals and comments (other file patterns use word-boundary regex). "
        "Shows each file changed and replacement count. If more files would be "
        "touched than the configured safety threshold, returns a no-write dry-run "
        "preview instead — pass confirm_large_batch=true to actually apply it. "
        "Always read the file first to confirm the symbol before renaming."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "old_name": {
                "type": "string",
                "description": "Current symbol name (must be a valid identifier)",
            },
            "new_name": {
                "type": "string",
                "description": "New symbol name (must be a valid identifier)",
            },
            "directory": {
                "type": "string",
                "description": "Root directory to rename within (default: repo root)",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern for files (default: *.py)",
            },
            "confirm_large_batch": {
                "type": "boolean",
                "description": "Set true to actually apply a rename that would touch more files than the safety threshold (otherwise a dry-run preview is returned instead)",
            },
        },
        "required": ["old_name", "new_name"],
    },
}
