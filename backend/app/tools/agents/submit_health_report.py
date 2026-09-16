"""submit_health_report tool — tool_enhance.md productionization pass,
tool #187 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_health_report
Old path: app/agents/tools.py (`_SUBMIT_HEALTH_REPORT_TOOL` schema
    dict, `submit_health_report` closure inside `make_devops_handlers()`
    — the one real implementation).
New path: app/tools/agents/submit_health_report.py (this file) —
    `SUBMIT_HEALTH_REPORT_TOOL`, `make_submit_health_report_handler`.
Affected agents: exactly 1 per tool_inventory.json — `devops`
    (`app/agents/devops.py`, via `run_devops()`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — same
    correct-and-intentional absence already established for sibling
    tools #66/#180-#186.
Affected modules: app/agents/tools.py (`make_devops_handlers()`'s
    inline `submit_health_report` closure now delegates to
    `make_submit_health_report_handler(health_result)`, mirroring the
    already-established `make_submit_docs_handler(docs_result)`
    pattern from tool #85 — the shared `bash` closure in the same
    factory function is untouched, out of scope for this tool's turn).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_health_report" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes — `tests/test_devops_agent.py`
    and `tests/test_session3_migration.py` both access this tool via
    `make_devops_handlers()`'s real `handlers["_health_result"]` export,
    which is preserved byte-for-byte. New tests added: see
    tests/test_submit_health_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_health_report.md.
---------------------------------------------------------------------------

IMPORTANT DIFFERENCE FROM SIBLING TOOLS #180-#186: this is NOT a dead
accumulator. `run_devops()` reads `handlers.get("_health_result", {})`
directly (`app/agents/devops.py`'s own `health_result =
handlers.get("_health_result", {})` line) — devops.py does NOT use
`run_agent_graph`'s generic `final_state["result"]` submit_* capture
at all for this agent. `health_result` is a real, live, genuinely
necessary result sink: confirmed by reading `run_devops()`'s full
body, which builds its returned `HealthReport` dataclass entirely from
this dict's `status`/`checks`/`summary` keys, with an explicit
"Agent spoke but never called submit_health_report" fallback path when
it's empty. No dead-code finding here — the opposite of tools
#180-#186's finding class.

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`status` is an enum,
`checks` is free-form structured data, `summary` is a string) — no
injection surface. `status`/`checks[].status` are both real JSON
Schema enums (`["healthy", "degraded", "unhealthy"]` /
`["ok", "warn", "fail"]`) enforced by the calling LLM API's tool-use
validation, not re-validated by the handler itself — consistent with
every other enum-typed submit_* schema in this codebase (e.g.
`submit_arch_review`'s `severity` enum), not a new gap.

No functional bug found. Modularized purely for consistency with the
already-established `make_submit_docs_handler`/`docs_result` pattern
(tool #85) — the factory takes the externally-owned `health_result`
dict (created and exported by `make_devops_handlers()`) rather than
owning it itself, preserving the exact existing contract every real
downstream consumer (`app/agents/devops.py::run_devops`) relies on.
"""

from __future__ import annotations

from typing import Any, Callable

SUBMIT_HEALTH_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_health_report",
    "description": "Submit the structured system health report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "status": {"type": "string", "enum": ["ok", "warn", "fail"]},
                        "detail": {"type": "string"},
                    },
                    "required": ["name", "status", "detail"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["status", "checks", "summary"],
    },
}


def make_submit_health_report_handler(
    health_result: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    """Core submit_health_report logic for the one real call site.

    `health_result` is the per-agent-instance dict `make_devops_handlers()`
    already creates and exposes as `handlers["_health_result"]` — this
    function does not own or create that dict, matching the existing
    contract `app/agents/devops.py::run_devops` relies on to build its
    real `HealthReport` return value.
    """

    def submit_health_report_handler(inp: dict[str, Any]) -> str:
        health_result.update(inp)
        return "Health report submitted"

    return submit_health_report_handler
