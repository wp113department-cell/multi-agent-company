"""find_unused_imports tool — tool_enhance.md productionization pass,
tool #141 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_unused_imports
Old path: app/agents/tools.py (`_FIND_UNUSED_IMPORTS_TOOL` schema
    dict, `find_unused_imports_h` inside `make_chat_handlers()` — the
    one real implementation).
New path: app/tools/execution/find_unused_imports.py (this file) —
    `FIND_UNUSED_IMPORTS_TOOL`, `find_unused_imports_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `find_unused_imports` in `allowed_tools` (plus interactive chat,
    newly — see finding #2).
Affected modules: app/agents/tools.py (`find_unused_imports_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "find_unused_imports" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_find_unused_imports_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_unused_imports.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine PARTIAL SOURCE CODE
   disclosure oracle, not just a filename leak.**
   `find_unused_imports_h` built `target = str(root / path)` without
   checking whether `path` was already absolute — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139
   this initiative. Because `ruff check`'s diagnostic output includes
   real surrounding SOURCE LINES (not just the flagged import line),
   this is a genuine partial file-content disclosure, not merely an
   existence/filename oracle. Proved live:
   `find_unused_imports({"path": "/tmp/<outside file>"})` genuinely
   returned real source lines — including unrelated code, not just the
   unused-import lines — from a file entirely outside the intended
   worktree.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140.**
   `find_unused_imports` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: find_unused_imports"`.

Fixed via a shared `find_unused_imports_handler()`: `path` is
validated with `check_path_in_worktree()` before being used to build
the `ruff` target, closing finding #1. A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

from app.tools.execution import safe_subprocess as subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FIND_UNUSED_IMPORTS_TOOL: dict[str, Any] = {
    "name": "find_unused_imports",
    "description": "Find unused imports in Python files using ruff or autoflake. Returns file:line:symbol for each unused import.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to check (default: repo root)",
            },
        },
        "required": [],
    },
}


def find_unused_imports_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core find_unused_imports logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path`."""
    path = str(inp.get("path", "."))
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = str(root / path)
    try:
        r = subprocess.run(
            ["python", "-m", "ruff", "check", "--select=F401", target],
            capture_output=True,
            text=True,
            cwd=worktree_path,
            timeout=30,
        )
        return r.stdout.strip() or "✅ No unused imports found"
    except Exception as e:
        return f"[ERROR] find_unused_imports: {e}"
