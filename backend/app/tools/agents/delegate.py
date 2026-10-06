"""delegate_to_agent tool — tool_enhance.md productionization pass,
tool #3 (2026-08-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: delegate_to_agent
Old path: app/agents/tools.py (`_DELEGATE_TO_AGENT_TOOL` schema dict and
    `make_delegate_to_agent_handler` — both previously lived in the
    14,000+ line app/agents/tools.py). The real safety/orchestration
    logic (depth/cycle/policy/budget/timeout, the actual `delegate()`
    entry point) already lived in its own module, app/agents/delegation.py
    — NOT moved here, since it was already properly separated and is not
    itself a "tool" (no schema, no handler signature); only the tool-
    layer wrapper is what this move relocates.
New path: app/tools/agents/delegate.py (this file) —
    `DELEGATE_TO_AGENT_TOOL`, `make_delegate_to_agent_handler`.

Affected agents: `bug_fix` (pre-existing real caller). `backend_dev` and
    `frontend_dev` (real gap found during this same audit, fixed
    alongside the move — see "Real gaps found" below): config.py's
    `delegation_allowed_matrix` already listed both as allowed source
    agents, but neither ever actually had the tool wired into its own
    handler set or `allowed_tools` — a real, silently-unreachable
    capability, not a security hole (the matrix + base_graph.py's
    dispatch-authorization gate from tool #2's pass already refuse an
    unadvertised/unauthorized call either way).
Affected modules: app/agents/tools.py (compatibility re-export),
    app/agents/bug_fix.py, app/agents/backend_dev.py,
    app/agents/frontend_dev.py (all three updated to import directly from
    this new module rather than via the compatibility shim, since all
    three were already being touched in this same pass).
Affected registries: none — app/fleet/tool_manifest.py's
    "delegate_to_agent" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: tests/test_delegation.py imports
    `make_delegate_to_agent_handler` directly from `app.agents.tools` —
    updated to import from this new module instead, since it's a real,
    direct consumer being kept in sync rather than left on the shim.

Runtime verification: PASS — see
    backend/docs/tool_productionization/delegate_to_agent.md.
---------------------------------------------------------------------------

Real gaps found while auditing (both fixed here, not just documented):

1. **Budget didn't actually decrement across multiple calls in one run.**
   config.py's own `delegation_default_budget_usd` docstring claims
   "every subsequent delegation in that chain draws down from this same
   allocation" — but the handler previously captured
   `budget_remaining_usd` once at construction time and reused it
   UNCHANGED on every call. An agent calling `delegate_to_agent` twice in
   the same run (nothing prevented this, up to
   `delegation_max_delegations_per_run`) got the same full budget both
   times, not a real running balance. Fixed via a mutable single-element
   list capturing the remaining budget (the same idiom this codebase's
   own `app/agents/base_graph.py` already uses for an equivalent
   "closure needs to rebind a value across calls" need), decremented by
   each call's real `outcome.cost_usd` after it returns.
2. **backend_dev/frontend_dev wiring gap** — see "Affected agents" above.
"""

from __future__ import annotations

from typing import Any, Callable

DELEGATE_TO_AGENT_TOOL: dict[str, Any] = {
    "name": "delegate_to_agent",
    "description": (
        "Delegate a specific, well-scoped sub-task to another agent by "
        "CAPABILITY (e.g. 'security_review', 'research_spike', "
        "'code_explanation', 'bug_fix') — never by agent name; the fleet "
        "resolves the concrete agent. Use only for genuinely separate work "
        "outside your own role (e.g. asking for a security review of code "
        "you just wrote), never to avoid doing your own task. Runs "
        "synchronously to completion or timeout; you get back a structured "
        "summary. Subject to a real depth limit, cycle detection, an "
        "explicit allowed-capability policy, and a shared budget — a "
        "denied or failed delegation returns an explanation, not an error "
        "you need to guess about."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target_capability": {
                "type": "string",
                "description": (
                    "The capability to delegate to, e.g. 'security_review'. If no "
                    "agent in the fleet has the capability you need, name it anyway "
                    "(a short snake_case name, e.g. 'csv_schema_inference'): when "
                    "allowed, a short-lived read-only specialist is created for it."
                ),
            },
            "objective": {
                "type": "string",
                "description": "A specific, well-scoped objective for the delegate.",
            },
            "context": {
                "type": "string",
                "description": "Relevant context the delegate needs (optional).",
            },
        },
        "required": ["target_capability", "objective"],
    },
}


def make_delegate_to_agent_handler(
    *,
    source_agent: str,
    task_id: str,
    repo_path: str,
    trace_id: str = "",
    ancestry: tuple[str, ...] = (),
    delegation_depth: int = 0,
    budget_remaining_usd: float | None = None,
) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for delegate_to_agent, closing over the
    calling agent's own real delegation context — ancestry/depth/budget —
    so cycle detection and the depth/budget limits in app.agents.delegation
    are enforced against the actual chain this specific call is part of,
    never a freshly-reset one. ancestry defaults to (source_agent,) — the
    calling agent is always the first link in its own chain.

    `budget_remaining_usd` is tracked in a mutable single-element list so
    a SECOND (or third, ...) call to the handler returned here — within
    the same agent run — sees the real remaining balance after the first
    call's actual cost, not the original starting figure again (a real
    bug found and fixed in this tool's second hardening pass; see this
    module's own docstring).
    """
    real_ancestry = ancestry or (source_agent,)
    remaining_budget: list[float | None] = [budget_remaining_usd]

    def _handler(inp: dict[str, Any]) -> str:
        target_capability = str(inp.get("target_capability", "")).strip()
        objective = str(inp.get("objective", "")).strip()
        context = str(inp.get("context", "")).strip()
        if not target_capability or not objective:
            return "[ERROR] target_capability and objective are required."

        from app.agents.delegation import DelegationError, DelegationRequest, delegate
        from app.config import get_settings

        budget = (
            remaining_budget[0]
            if remaining_budget[0] is not None
            else get_settings().delegation_default_budget_usd
        )
        request = DelegationRequest(
            source_agent=source_agent,
            target_capability=target_capability,
            objective=objective,
            context=context,
            ancestry=real_ancestry,
            delegation_depth=delegation_depth,
            budget_remaining_usd=budget,
            task_id=task_id,
            repo_path=repo_path,
            trace_id=trace_id,
        )
        try:
            outcome = delegate(request)
        except DelegationError as exc:
            return f"[POLICY DENIED] {exc}"

        remaining_budget[0] = budget - outcome.cost_usd

        if not outcome.success:
            return (
                f"[ERROR] Delegation to "
                f"{outcome.target_agent or target_capability} failed: {outcome.error}"
            )

        result = outcome.result
        assert result is not None
        return (
            f"Delegation to {outcome.target_agent} completed "
            f"(status={result.status}, verified={result.verified}, "
            f"cost=${outcome.cost_usd:.4f}).\nSummary: {result.summary}"
        )

    return _handler
