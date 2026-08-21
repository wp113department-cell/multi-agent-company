"""npm_run tool — tool_enhance.md productionization pass, tool
#54 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: npm_run
Old path: app/agents/tools.py (`_NPM_RUN_TOOL` schema dict and the
    `npm_run_h` handler inside `make_chat_handlers()`).
New path: app/tools/execution/npm_run.py (this file) — `NPM_RUN_TOOL`,
    `validate_npm_run_directory`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch (real, reachable — already wired up before
    this turn) and `make_chat_handlers`'s own `npm_run_h` (previously
    ALSO real and reachable, with the identical bug, unlike its
    `npm_install`/`pip_install` siblings which are already blocked —
    now blocked too, for consistency; see below).
Affected modules: app/agents/tools.py (schema re-export;
    `npm_run_h` now unconditionally blocked, matching
    `npm_install_h`/`pip_install_h`'s existing precedent in this same
    file), app/agents/chat_agent.py (real dispatch now validates
    `directory`).
Affected registries: none — app/fleet/tool_manifest.py's "npm_run"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_npm_run_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/npm_run.md.
---------------------------------------------------------------------------

Real, severe finding (identical shape to tool #53's `npm_install`
finding, arguably worse here since NEITHER real implementation had a
confirmation gate at all): both implementations built `target_dir =
str(root / directory)` with zero validation that `directory` stays
inside the repo. Proved live, through `make_chat_handlers`'s own
`npm_run` — no confirmation dialog stood between the call and real
code execution:

```python
handlers["npm_run"]({"script": "build", "directory": "/tmp/td_npmrun_outside"})
```

where `/tmp/td_npmrun_outside/package.json` had a `build` script of
`"touch /tmp/td_npmrun_PWNED_marker"` — genuinely executed, confirmed
via the marker file's real existence afterward.

Fixed via a shared `validate_npm_run_directory()` chokepoint
(`check_path_in_worktree`, same mechanism as tool #53's
`validate_npm_install_directory`) used by `chat_agent.py`'s real
dispatch.

**Also fixed a second, real inconsistency**: `make_chat_handlers`'s own
`npm_run_h` had zero real one-shot caller (grepped: not in any agent's
`allowed_tools`) and produces a real side effect (arbitrary script
execution) — the exact same shape `npm_install_h`/`pip_install_h`
already handle by being unconditionally `[BLOCKED]` in this same file,
for lack of any safe confirmation channel for a one-shot agent.
`npm_run_h` was apparently missed when that policy was applied during
tool #4's earlier pass; this turn brings it in line with its own
siblings rather than leaving the inconsistency in place.

The real dispatch's own no-confirmation-gate design (unlike
`npm_install`) is kept, but is now actually safe: its original
reasoning — "running a package.json script (build/test/lint) is
lower-risk than installing arbitrary new dependencies" — is only true
once `directory` is genuinely constrained to the real repo (this fix);
under that constraint, `npm run` can only ever execute a script already
defined in this repo's own, presumably-reviewed `package.json`, the
same trust level `run_tests`/`run_make` already operate at without a
confirmation dialog.
"""

from __future__ import annotations

from app.policy.engine import check_path_in_worktree

NPM_RUN_TOOL: dict[str, object] = {
    "name": "npm_run",
    "description": "Run an npm script defined in package.json (e.g. build, test, lint).",
    "input_schema": {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Script name from package.json scripts",
            },
            "directory": {
                "type": "string",
                "description": "Directory containing package.json (default: repo root)",
            },
        },
        "required": ["script"],
    },
}


def validate_npm_run_directory(directory: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `directory` escapes the repo, else
    None."""
    result = check_path_in_worktree(directory, worktree_path)
    if not result.allowed:
        return f"[ERROR] {result.reason}"
    return None
