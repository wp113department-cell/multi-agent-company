"""dead_code_detect tool — tool_enhance.md productionization pass,
tool #94 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: dead_code_detect
Old path: app/agents/tools.py (`_DEAD_CODE_DETECT_TOOL` schema dict)
    with FOUR real implementations: `ar_dead_code`
    (`make_arch_reviewer_handlers`), `cu_dead_code_detect`
    (`make_cleanup_agent_handlers`), `dead_code_detect_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/filesystem/dead_code_detect.py (this file) —
    `DEAD_CODE_DETECT_TOOL`, `dead_code_detect_handler`. ALL FOUR real
    call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 4 agents declare
    `dead_code_detect` in `allowed_tools`.
Affected modules: app/agents/tools.py (all three of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler). `app/repo_tools/
    ast_engine.py`'s own `detect_dead_code()`/`_find_dead_code()` are
    left completely untouched and still do the real heuristic scan —
    the same reasoning already established for tools #83/#93's
    `ast_engine` reuse.
Affected registries: none — app/fleet/tool_manifest.py's
    "dead_code_detect" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_dead_code_detect_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/dead_code_detect.md.
---------------------------------------------------------------------------

One real, empirically-verified finding — a DIFFERENT shape from
siblings tools #83/#93 (`parse_ast`/`call_graph`, same `ast_engine`
module): checked for the identical "uncaught PermissionError" class
those two turns established and confirmed it does NOT reproduce here.

1. **Worktree-boundary escape, on all four implementations.** None
   called `check_path_in_worktree()` — `root / directory` let
   `directory` resolve to any absolute host path before being handed
   to `ast_engine.detect_dead_code()`. Proved live:
   `dead_code_detect({"directory": "/tmp/outside"})` genuinely
   returned real function names and line references from a directory
   completely outside the repo, through multiple real call sites
   (`chat_agent.py`'s dispatch, `make_chat_handlers()`,
   `make_arch_reviewer_handlers()`).

**Checked, confirmed NOT reproducible here (unlike tools #83/#93): an
uncaught `PermissionError`.** `detect_dead_code()`'s own internal
`_find_dead_code()` calls `Path(directory).rglob("*.py")` — verified
directly (not assumed) that Python's `pathlib.Path.rglob()` silently
swallows `PermissionError` when it cannot read a subdirectory's
contents during traversal, returning an empty result rather than
raising. A real `chmod 000` directory produced the (mildly misleading,
but not a security issue, and a pre-existing `ast_engine.py` behavior
out of scope for this tool's own turn) message `"(no .py files
found)"` instead of an exception or a permission-denied error. No fix
needed for this class here.

Fixed via a shared `dead_code_detect_handler()`:
`check_path_in_worktree()` closes the worktree-escape finding. The
actual dead-code-detection logic itself is reused verbatim from
`ast_engine.detect_dead_code()` — not reimplemented — since it was
already correct and is shared by other, out-of-scope tools/modules
(e.g. `app/fleet/architecture_drift.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.ast_engine import detect_dead_code

DEAD_CODE_DETECT_TOOL = {
    "name": "dead_code_detect",
    "description": (
        "Heuristically detect public Python functions defined in a directory that are never called "
        "anywhere in that directory. Results are indicative — external callers are not visible."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (relative to repo root, default: repo root)",
            },
        },
        "required": [],
    },
}


def dead_code_detect_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core dead_code_detect logic shared by all four real call sites."""
    directory = str(inp.get("directory", ""))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / directory if directory else root
    return detect_dead_code(str(target))
