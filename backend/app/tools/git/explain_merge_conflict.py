"""explain_merge_conflict tool — tool_enhance.md productionization
pass, tool #136 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: explain_merge_conflict
Old path: app/agents/tools.py (`_EXPLAIN_MERGE_CONFLICT_TOOL` schema
    dict) with TWO real, near-identical implementations:
    `explain_merge_conflict` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/git/explain_merge_conflict.py (this file) —
    `EXPLAIN_MERGE_CONFLICT_TOOL`, `explain_merge_conflict_handler`.
    BOTH real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `explain_merge_conflict` in `allowed_tools` (plus interactive
    chat).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "explain_merge_conflict" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_explain_merge_conflict_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/explain_merge_conflict.md.
---------------------------------------------------------------------------

Worktree-boundary validation was ALREADY correct on both real
implementations (`check_path_in_worktree(rel, repo_path)` /
`_is_protected_path(emc_rel, repo)`, both of which perform full
worktree-containment checking given `worktree_path`) — fixed
2026-08-17 during tool #11's (`undo_changes`) cross-cutting audit,
confirmed still correct here by direct inspection and re-verified
live below, not assumed.

One real finding — a robustness gap: neither implementation wrapped
`target.read_text()` in a `try/except`, same class already fixed for
tools #70/#72/#76/#135. Proved live with a real `chmod 000` file: a
genuine `PermissionError` propagated straight out of both real
handlers.

Fixed via a shared `explain_merge_conflict_handler()`: the whole
read+parse operation is now wrapped in `try/except`. `_llm_generate_
text()`-backed conflict explanation (`_llm_explain_conflict_hunks()`
in `app/agents/tools.py`, shared by several OTHER out-of-scope tools'
prompt-generation helpers too) is deliberately left in place and
passed into this handler as an injected `explain_fn` callable rather
than relocated — avoiding both a circular import (this module would
otherwise need to import from `app.agents.tools`, which imports this
module) and any out-of-scope change to the broadly-shared
`_llm_generate_text()` utility. `_parse_conflict_markers` is imported
directly from its own existing home, `app.agents.conflict_resolution`
— already a neutral, non-circular module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.agents.conflict_resolution import _parse_conflict_markers
from app.policy.engine import check_path_in_worktree

EXPLAIN_MERGE_CONFLICT_TOOL = {
    "name": "explain_merge_conflict",
    "description": "Parse a file's real conflict markers (like parse_merge_conflicts) and generate a plain-English explanation of what 'ours' vs 'theirs' actually changed in each hunk and why they conflict. Does not resolve anything — read before deciding, or use standalone to understand a conflict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Conflicted file, relative to repo root",
            },
        },
        "required": ["path"],
    },
}


def explain_merge_conflict_handler(
    root: Path,
    worktree_path: str,
    inp: dict[str, Any],
    explain_fn: Callable[[str, list[dict[str, Any]]], str],
) -> str:
    """Core explain_merge_conflict logic shared by both real call
    sites. `explain_fn` is the LLM-backed explanation generator
    (`_llm_explain_conflict_hunks` in app.agents.tools), injected by
    the caller to avoid a circular import."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {rel}: {policy.reason}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ERROR] Could not read {rel}: {e}"
    hunks = _parse_conflict_markers(text)
    if not hunks:
        return f"No conflict markers found in {rel}."
    return explain_fn(rel, hunks)
