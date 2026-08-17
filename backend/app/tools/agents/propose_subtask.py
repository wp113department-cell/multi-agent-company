"""propose_subtask tool — tool_enhance.md productionization pass, tool #7
(2026-08-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: propose_subtask
Old path: app/agents/tools.py (`PROPOSE_SUBTASK_TOOL` schema dict and
    `make_propose_subtask_handler` — both previously lived in the
    14,000+ line app/agents/tools.py)
New path: app/tools/agents/propose_subtask.py (this file) —
    `PROPOSE_SUBTASK_TOOL`, `make_propose_subtask_handler`.

Affected agents: `backend_dev` (pre-existing real caller) and
    `frontend_dev` (real gap found during this audit, fixed alongside the
    move — see "Real gap found" below): config.py's
    `dynamic_subtask_allowed_matrix` already listed `frontend_dev` as an
    allowed proposer, and `app/agents/manager.py`'s own comment
    explicitly named frontend_dev wiring as pending ("a trivial,
    identical-shape follow-up" to backend_dev's) — never actually done
    until this pass.
Affected modules: app/agents/tools.py (compatibility re-export),
    app/agents/backend_dev.py, app/agents/frontend_dev.py (both updated
    to import directly from this new module), app/agents/manager.py
    (the `propose_sink` gating condition generalized from
    `selected_agent_name == "backend_dev"` to a lookup keyed by whichever
    agent was actually selected, so it now covers both real callers
    without a second hardcoded branch).
Affected registries: none — app/fleet/tool_manifest.py's
    "propose_subtask" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes beyond the real frontend_dev gap
    fix itself (2 new end-to-end tests added to
    tests/test_dynamic_subtask_creation.py, mirroring the pre-existing
    backend_dev ones) — every real test accesses this tool via
    `make_propose_subtask_handler(sink)` directly, and the import path
    update was mechanical.

Runtime verification: PASS — see
    backend/docs/tool_productionization/propose_subtask.md.
---------------------------------------------------------------------------

The real validation/integration logic this tool's proposals flow into
(`app.pipeline.dynamic_subtasks.integrate_proposals` — allow-matrix,
duplicate-work, depth/count limits, file-lock reservation) already lived
in its own separate module before this pass and did not need moving;
this handler deliberately does only cheap shape validation (see its own
docstring below) — the real policy checks need epic-wide state this
handler has no visibility into.
"""

from __future__ import annotations

from typing import Any, Callable

PROPOSE_SUBTASK_TOOL: dict[str, Any] = {
    "name": "propose_subtask",
    "description": (
        "Propose a NEW follow-up subtask to be created and dispatched after "
        "this one completes — use when you discover necessary work that "
        "wasn't in the original plan (e.g. a companion piece, a missed "
        "case, or a test that should exist). This does not run anything "
        "itself: the epic manager validates every proposal (allowed-type "
        "policy, duplicate-work check, file-lock availability, spawn-depth "
        "and per-epic count limits) before it is ever scheduled, and a "
        "proposal may be rejected. You will not be told the outcome — "
        "continue and finish your own current subtask regardless."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["backend", "frontend", "test", "docs"],
                "description": "What kind of subtask this is — same vocabulary the original plan's subtasks use.",
            },
            "title": {"type": "string", "description": "A short, specific title."},
            "description": {
                "type": "string",
                "description": "What needs to be done, specific enough for another agent to implement without further context.",
            },
            "files_to_edit": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files this subtask is expected to touch (best guess — used for conflict/lock checking).",
            },
            "reason": {
                "type": "string",
                "description": "Why this follow-up work is needed — what you discovered that the original plan didn't cover.",
            },
        },
        "required": ["type", "title", "description", "reason"],
    },
}


def make_propose_subtask_handler(
    sink: list[dict[str, Any]],
) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for propose_subtask. `sink` is a plain
    list owned by the ONE _dispatch_one_subtask call this handler was built
    for (see app.agents.manager) — appending to it here is safe with no
    locking because that call's own dev-agent run is the only thing that
    ever touches this particular list, and it runs to completion inside a
    single asyncio.to_thread() worker before anything else reads it.

    Deliberately does only cheap SHAPE validation (required fields present,
    `type` is a real value, files_to_edit is a list of strings) — the real
    policy checks (allow-matrix, duplicate-work, depth/count limits,
    file-lock reservation) need epic-wide state this handler has no
    visibility into, and run later, once per wave boundary, in
    app.pipeline.dynamic_subtasks.integrate_proposals(). A proposal
    accepted here is NOT yet a guarantee it will ever be scheduled."""

    def _handler(inp: dict[str, Any]) -> str:
        subtask_type = str(inp.get("type", "")).strip()
        title = str(inp.get("title", "")).strip()
        description = str(inp.get("description", "")).strip()
        files_to_edit = inp.get("files_to_edit") or []
        reason = str(inp.get("reason", "")).strip()

        if subtask_type not in {"backend", "frontend", "test", "docs"}:
            return (
                "[ERROR] type must be one of backend/frontend/test/docs, "
                f"got {subtask_type!r}."
            )
        if not title:
            return "[ERROR] title is required."
        if not description:
            return "[ERROR] description is required."
        if not reason:
            return "[ERROR] reason is required."
        if not isinstance(files_to_edit, list) or not all(
            isinstance(f, str) for f in files_to_edit
        ):
            return "[ERROR] files_to_edit must be a list of strings."

        sink.append(
            {
                "type": subtask_type,
                "title": title,
                "description": description,
                "files_to_edit": [str(f) for f in files_to_edit],
                "reason": reason,
            }
        )
        return (
            f"Proposal recorded: {title!r}. It will be reviewed and "
            "validated by the epic manager — continue your own current "
            "subtask now."
        )

    return _handler
