"""submit_patch tool — tool_enhance.md productionization pass, tool
#92 (2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_patch
Old path: app/agents/tools.py — a single `submit_patch` closure inside
    `make_coder_handlers()`. Not duplicated anywhere else.
New path: app/tools/agents/submit_patch.py (this file) —
    `SUBMIT_PATCH_TOOL`, `make_submit_patch_handler`.
Affected agents: per tool_inventory.json, 5 agents declare
    `submit_patch` in `allowed_tools` (all real callers reach it
    through `make_coder_handlers()` — `coder.py`, `backend_dev.py`,
    `frontend_dev.py`, `mobile_dev.py`). Confirmed NOT in `CHAT_TOOLS`
    — intentional, a batch-agent final-answer tool, never exposed to
    the interactive chat session; `app/agents/chat_agent.py` correctly
    has no dispatch branch for it.
Affected modules: app/agents/tools.py (`make_coder_handlers()`'s
    closure delegates to the shared handler factory).
Affected registries: none — app/fleet/tool_manifest.py's "submit_patch"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — zero existing tests invoke the
    real handler directly (all either mock `make_coder_handlers()`
    entirely, per `test_session2_migration.py`, or check tool-name
    membership/contract scoping). New tests added: see
    tests/test_submit_patch_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_patch.md.
---------------------------------------------------------------------------

No security vulnerability found in this handler itself: it is a pure
in-memory result sink, identical in shape to tool #85's `submit_docs`
— `patch_result["files_changed"] = ...` / `patch_result["summary"] =
...`, no file I/O, no subprocess, no path handling. Each real caller's
`patch_result` dict is freshly created per `make_coder_handlers()`
invocation — no cross-session or cross-agent leakage is possible.

**Unlike tool #85's `submit_docs`, `files_changed` here DOES have a
real, consequential downstream consumer** — traced to
`app/api/agents.py`, which passes it directly to
`app.services.git_service.git_add()`. That function was independently
audited and confirmed ALREADY SAFE: it rejects absolute paths
(`os.path.isabs()`), places all paths after a `--` pathspec separator
(closing the flag-collision class established elsewhere in this
initiative), and git's own `git add -- <path>` additionally refuses
any path outside the repository on its own — verified live with a
real `../<outside-file>` relative-traversal attempt, producing `fatal:
... is outside repository at '<repo>'`, the same class of
already-safe external-tool-boundary refusal established for tools
#27/#78/#80/#81/#90's own pathspec fields. No fix was needed at this
downstream layer since it was already correct; this handler's own
docstring documents the trace for future readers so the next person
auditing `submit_patch` doesn't have to re-derive it. `summary` was
also traced and confirmed to have no downstream consumer at all across
all four real callers (`coder.py`, `backend_dev.py`, `frontend_dev.py`,
`mobile_dev.py`) — a harmlessly-unused field, same shape as tool #85's
`DocsReport.files_written`.

Extracted verbatim (no behavior change) purely for modularization —
matches this initiative's mandatory per-tool modularization rule even
when no vulnerability was found.
"""

from __future__ import annotations

from typing import Any, Callable

SUBMIT_PATCH_TOOL = {
    "name": "submit_patch",
    "description": "Signal that implementation is complete. Call this ONLY after all tests pass.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths that were created or modified",
            },
            "summary": {
                "type": "string",
                "description": "One-paragraph summary of what was implemented and verified",
            },
        },
        "required": ["files_changed", "summary"],
    },
}


def make_submit_patch_handler(
    patch_result: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    """Core submit_patch logic — the single real implementation, now
    just relocated out of app/agents/tools.py.

    `patch_result` is the per-agent-instance dict `make_coder_handlers()`
    already creates and exposes as `handlers["_patch_result"]` — this
    function does not own or create that dict, matching the existing
    contract every real downstream consumer (`coder.py`,
    `backend_dev.py`, `frontend_dev.py`, `mobile_dev.py`) relies on.
    """

    def submit_patch_handler(inp: dict[str, Any]) -> str:
        patch_result["files_changed"] = inp.get("files_changed", [])
        patch_result["summary"] = inp.get("summary", "")
        return "Patch submitted"

    return submit_patch_handler
