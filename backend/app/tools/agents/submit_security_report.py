"""submit_security_report tool — tool_enhance.md productionization
pass, tool #197 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_security_report
Old path: app/agents/tools.py (`_SUBMIT_SECURITY_REPORT_TOOL` schema
    dict, `sec_submit` inside `make_security_reviewer_handlers()` —
    the one real implementation).
New path: app/tools/agents/submit_security_report.py (this file) —
    `SUBMIT_SECURITY_REPORT_TOOL`, `submit_security_report_handler`.
Affected agents: exactly 1 per tool_inventory.json —
    `security_reviewer` (`app/agents/security_reviewer.py`, via
    `run_security_reviewer()`). Deliberately NOT in `CHAT_TOOLS` —
    confirmed via `CHAT_TOOLS` membership check — same correct-and-
    intentional absence already established for sibling tools
    #66/#180-#186/#188-#192/#194/#196. Also note: a completely
    UNRELATED agent, `security_architect.py`, coincidentally exports
    its own local dict under the identically-named key
    `handlers["_security_result"]` (for its own, different tool
    `submit_threat_model`, built on `make_chat_handlers()` as its
    base) — verified this is a separate closure in a separate
    factory function, not a real reader of this tool's
    `security_result` dict; several tests matched by a naive grep for
    `_security_result` (`test_day4_agents.py`, `test_gap_agents.py`,
    `test_day4_agent_contracts.py`) actually test
    `security_architect.py`, not this tool — confirmed by reading
    each, not assumed. `quality_auditor.py` also builds a scan-scoped
    variant of `SECURITY_REVIEWER_TOOLS` that explicitly excludes
    `submit_security_report` (pre-existing, documented design,
    mirroring `monitoring_agent.py`'s own scan-mode pattern) —
    confirmed still correct, untouched.
Affected modules: app/agents/tools.py (`sec_submit` delegates to the
    shared handler; the local `security_result` dict accumulator and
    `handlers["_security_result"]` export are removed — see finding).
    `make_security_reviewer_handlers()`'s other handlers
    (`secrets_scan`, `find_sql`, `find_config`, `find_api`,
    `find_route`) are each their own separately-productionized tool
    (already GREEN_FLAGGED as tools #89/#90/#91/#99/#102) —
    deliberately untouched here, out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_security_report" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestSecurityReviewerHandlers::
    test_submit_stores_result` asserted directly on the now-removed
    `h["_security_result"]` dict (an internal implementation detail,
    not real production behavior — see finding). Updated to assert on
    the handler's real return value instead, preserving the test's
    actual intent (verify a real submission succeeds) without relying
    on dead internal state. New tests added: see
    tests/test_submit_security_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_security_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`severity` is an enum,
`findings`/`recommendations` are string arrays — the agent's real
security scanning already happened via its own separately gated
`secrets_scan`/`find_sql`/`find_config`/`find_api`/`find_route`
handlers before this tool is ever called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196: **dead-code accumulator, never actually
read.** `sec_submit`'s original body did `security_result.update(inp)`,
and the factory separately exported `handlers["_security_result"] =
security_result` — but grepping the entire production codebase found
zero real readers (the only same-named key anywhere else belongs to
the unrelated `security_architect.py` agent, a different closure
entirely — see migration report above). The tool's real, functioning
result-capture mechanism lives entirely in `app/agents/base_graph.py`'s
generic tool-execution node (`tool_name.startswith("submit_")` →
captures `dict(tu_input)` directly into `state["result"]`), confirmed
by reading `security_reviewer.py`'s own `raw = final_state["result"]`
lines — used on BOTH its normal-completion path and its
turn-limit-exhausted retry-giveup path — which is what real production
code actually consumes, completely independent of
`security_result`/`_security_result`.

Fixed by removing the dead `security_result` dict and
`_security_result` export entirely — `submit_security_report_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Security report
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_SECURITY_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_security_report",
    "description": "Submit security review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low", "none"],
            },
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["severity", "findings", "recommendations"],
    },
}


def submit_security_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Security report submitted"
