"""circular_dep_detect tool — tool_enhance.md productionization pass,
tool #97 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: circular_dep_detect
Old path: app/agents/tools.py (`_CIRCULAR_DEP_DETECT_TOOL` schema dict)
    with THREE real implementations: `ar_circular_dep`
    (`make_arch_reviewer_handlers`), `circular_dep_detect_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/filesystem/circular_dep_detect.py (this file) —
    `CIRCULAR_DEP_DETECT_TOOL`, `circular_dep_detect_handler`. ALL
    THREE real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 3 agents declare
    `circular_dep_detect` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler). `app/repo_tools/
    ast_engine.py`'s own `detect_circular_imports()`/
    `_find_circular_import_cycles()` are left completely untouched and
    still do the real cycle-detection work — the same reasoning
    already established for tool #94's `dead_code_detect` (same
    `ast_engine` module, same directory-rglob shape), also used by
    `app/fleet/architecture_drift.py`.
Affected registries: none — app/fleet/tool_manifest.py's
    "circular_dep_detect" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_circular_dep_detect_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/circular_dep_detect.md.
---------------------------------------------------------------------------

Exact sibling shape to tool #94's `dead_code_detect` (same `ast_engine`
module, same directory-rglob-walk shape, same PermissionError-
swallowing behavior — checked directly, not assumed to transfer).

1. **Worktree-boundary escape, on all three implementations.** None
   called `check_path_in_worktree()` — `root / directory` let
   `directory` resolve to any absolute host path before being handed
   to `ast_engine.detect_circular_imports()`. Proved live: a directory
   outside the repo containing a genuine circular-import pair
   (`app/a.py` doing `import app.b`, `app/b.py` doing `import app.a`)
   produced a real, correctly-detected cycle report
   (`app.a → app.b → app.a`) through the raw utility function — the
   same disclosure class as tool #94.

**Checked, confirmed NOT reproducible here (matching tool #94, not
tools #83/#93): an uncaught `PermissionError`.**
`_find_circular_import_cycles()`'s own internal `d.rglob("*.py")` call
silently swallows `PermissionError` when it cannot read a
subdirectory's contents during traversal, returning `None` (surfaced
as `"(no .py files found)"`) rather than raising. Verified directly
with a real `chmod 000` directory. No fix needed for this class here.

Fixed via a shared `circular_dep_detect_handler()`:
`check_path_in_worktree()` closes the worktree-escape finding. The
actual cycle-detection logic itself is reused verbatim from
`ast_engine.detect_circular_imports()` — not reimplemented — since it
was already correct and is shared by other, out-of-scope tools/modules
(`app/fleet/architecture_drift.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.ast_engine import detect_circular_imports

CIRCULAR_DEP_DETECT_TOOL = {
    "name": "circular_dep_detect",
    "description": "Detect circular local import chains in a Python package directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: repo root)",
            },
        },
        "required": [],
    },
}


def circular_dep_detect_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core circular_dep_detect logic shared by all three real call sites."""
    directory = str(inp.get("directory", ""))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / directory if directory else root
    return detect_circular_imports(str(target))
