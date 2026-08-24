"""git_status tool — tool_enhance.md productionization pass, tool #79
(2026-08-23).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_status
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[12]` schema dict and the
    `git_status` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate dispatch body, built on the
    shared `_git()` subprocess helper).
New path: app/tools/git/status.py (this file) — `GIT_STATUS_TOOL`,
    `git_status_handler`.
Affected agents: per tool_inventory.json, 39 agents declare
    `git_status` in `allowed_tools`. Every real caller — including
    `make_monitoring_agent_handlers()` / `make_scan_handlers()`'s
    autonomous infrastructure-health-scan agent, which reads
    `git_status` straight from the canonical `make_read_only_handlers()`
    with no override of its own — was affected equally by the finding
    below.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[12]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `git_status` closure now delegates to the fixed
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "git_status"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: the tracking table's "1 existing test file" is
    `test_audit_q_batch07_guardian_human_interaction.py`, which only
    asserts `"git_status" in handlers` (membership, not behavior) —
    verified directly, zero existing tests actually invoke this tool's
    real handler and exercise its output. `test_git_service.py` tests
    `app.services.git_service.git_status`, a completely separate
    function (same false-positive-adjacent shape as tool #78's
    finding). No sweep-run was needed; see
    tests/test_git_status_hardening.py for the new, real coverage.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_status.md.
---------------------------------------------------------------------------

No security vulnerability — this tool's schema takes zero input
(`"properties": {}`), so there is no LLM-controlled field to audit for
injection, worktree-escape, or any other class established so far in
this initiative.

One real, empirically-verified FUNCTIONALITY bug in the canonical
implementation (not present in `chat_agent.py`'s dispatch).

**The canonical implementation silently reports "(clean)" even when
`git status` genuinely failed**, because it returns `result.stdout or
"(clean)"` without ever checking `result.returncode`. Proved live: run
against a directory that is not a git repository at all —

```python
handlers["git_status"]({})
```

returned the literal string `"(clean)"`, even though the underlying
command actually failed with `fatal: not a git repository (or any of
the parent directories): .git`. This is a genuinely misleading result:
an agent (or a human relying on this tool's summary) would reasonably
conclude the working tree has no changes, when in fact the command
never ran successfully at all. `chat_agent.py`'s own dispatch, built on
the shared `_git()` helper (which combines stdout+stderr), already
surfaced the real error text correctly in the same scenario — the
canonical implementation was the less complete of the two here, the
opposite direction from tools #76/#77/#78 where `chat_agent.py`'s copy
was the one missing something.

Fixed via a shared `git_status_handler()`: now checks
`result.returncode != 0` and returns a clean `[ERROR] git status
failed: ...` message in that case, matching this initiative's
established error-surfacing convention (`git_log_handler`,
`file_info_handler`, etc.) instead of masking a real failure as a
false "clean" result.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_STATUS_TOOL = {
    "name": "git_status",
    "description": "Show current git working tree state: staged, modified, untracked files. Always run before committing or diffing.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def git_status_handler(root: Path) -> str:
    """Core git_status logic shared by both real call sites."""
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=10,
        )
        if result.returncode != 0:
            return f"[ERROR] git status failed: {result.stderr.strip()[:300]}"
        return result.stdout or "(clean)"
    except Exception as e:
        return f"[ERROR] {e}"
