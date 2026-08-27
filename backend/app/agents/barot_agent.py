"""barot_agent — just-in-time meta-agent ("the brain").

When fleet_manager.select() finds no static agent for a required
capability, it offers the gap to try_fill_capability_gap() before falling
back to its existing None-return (which independently continues to feed the
scheduled capability_gap.py/agent_advisor.py advisory scan, unchanged).
barot_agent decides whether it can safely attempt the gap, and if so, plans
a minimal real tool profile via one Claude API call and hands off to
TemporaryAgentPool (app/agents/temporary_agent.py) to actually spawn, run,
and later scrap a temporary_agent instance.

barot_agent never executes a task itself — it only plans, spawns, and later
(via the pool) tears down. Follows the same module-level AGENT_CONTRACT +
_register() convention every other agent in this directory uses, so the
rest of the fleet sees it as a normal agent, with one deliberate difference:
capabilities=[] — barot_agent declares no task capability of its own, so
find_by_capability() can never return it, which is the structural
mechanism that makes it impossible for barot_agent to ever select itself as
a gap-filler for its own gap.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.agents.base_graph import VerificationConfig

logger = logging.getLogger(__name__)

# Set for the duration of a temporary_agent's own execution (by
# app.agents.temporary_agent.run_temporary_agent, which runs on its own
# dedicated worker thread — contextvars are thread-local by default, so this
# only ever reads True on the same thread that set it). Checked first in
# try_fill_capability_gap() as a belt-and-suspenders guard against any
# future tool that might, directly or indirectly, re-enter
# fleet_manager.select() from inside a temp agent's own run — independent
# of and in addition to the hard tool denylist below.
TEMP_AGENT_EXECUTION: ContextVar[bool] = ContextVar(
    "barot_agent_temp_agent_execution", default=False
)

# Hard-enforced regardless of what the planning LLM "chooses" — a temp
# agent must never be able to trigger another synthesis.
_DENYLISTED_TOOLS = {"delegate_to_agent", "propose_subtask"}


# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "barot_agent",
    "description": (
        "Just-in-time meta-agent: when no static agent covers a required "
        "capability, plans a minimal real tool/model profile via the "
        "Claude API and synthesizes a short-lived temporary_agent to fill "
        "the gap. Never executes a task itself."
    ),
    "allowed_tools": [],
    "input_types": ["capability_gap"],
    "output_types": ["DispatchPlan"],
    "side_effects": ["spawn_temporary_agent"],
    "permissions": [],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": [],
}

# barot_agent never calls run_agent_graph() itself — it only plans and
# spawns, never submits reviewable work of its own — so there is nothing
# for a real per-tool verification gate to track here. Declared anyway
# (matching every other real agent module's own convention of a module-
# level VerificationConfig) so barot_agent is honestly, structurally
# indistinguishable from any other agent to the rest of the fleet.
_VERIFICATION_CFG = VerificationConfig()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@dataclass
class ToolProfilePlan:
    tool_names: list[str] = field(default_factory=list)
    briefing: str = ""
    model_used: str = ""
    failure_reason: str | None = None

    @classmethod
    def failed(cls, reason: str) -> "ToolProfilePlan":
        return cls(tool_names=[], briefing="", model_used="", failure_reason=reason)

    @property
    def ok(self) -> bool:
        return bool(self.tool_names) and bool(self.briefing) and not self.failure_reason


@dataclass
class BarotDecision:
    attempted: bool
    success: bool
    agent_name: str | None
    reason: str


_PLAN_TOOL_PROFILE_TOOL: dict[str, Any] = {
    "name": "plan_tool_profile",
    "description": "Report the minimal tool subset and task briefing for a "
    "temporary_agent instance.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The minimal subset of the CANDIDATE TOOLS "
                "listed above needed for this task. Only names from that "
                "exact list — never invent a tool name.",
            },
            "briefing": {
                "type": "string",
                "description": "A short, concrete brief telling the "
                "temporary_agent what to do and how to use its granted "
                "tools for this specific task.",
            },
        },
        "required": ["tool_names", "briefing"],
    },
}

_PLANNING_SYSTEM_PROMPT = (
    "You are barot_agent, the planning component of a fleet orchestration "
    "system. A task needs a capability no permanent agent declares. Your "
    "only job is to choose the minimal real tool subset a short-lived "
    "worker needs, and write it a short task briefing. You are never the "
    "one executing the task — you only plan. Choose tool_names ONLY from "
    "the CANDIDATE TOOLS list you are given in the user message — never "
    "invent, guess, or assume a tool exists beyond that list. Choose the "
    "smallest set that could plausibly complete the task; do not grant "
    "tools 'just in case'. You must always call plan_tool_profile exactly "
    "once with your answer."
)


def _candidate_tool_catalog() -> list[tuple[str, str]]:
    """Real, existing read-only tool names + their manifest purpose — the
    only tools this version of temporary_agent can ever be granted
    (default_tool_scope='planned'). Sourced live from READ_ONLY_TOOLS +
    tool_manifest, never a hardcoded list that could drift out of sync."""
    from app.agents.tools import READ_ONLY_TOOLS
    from app.fleet.tool_manifest import get_manifest

    catalog: list[tuple[str, str]] = []
    for spec in READ_ONLY_TOOLS:
        name = spec["name"]
        entry = get_manifest(name)
        purpose = entry.purpose if entry is not None else spec.get("description", "")
        catalog.append((name, purpose))
    return catalog


def _validate_tool_names(names: list[Any]) -> list[str]:
    """Cross-checks every requested name against the real tool registry
    (tool_discovery.check_availability) and drops anything denylisted or
    not a string. Silently narrows rather than failing the whole request —
    matches tool_discovery.filter_runtime_tools()'s own "never adds, only
    narrows" philosophy."""
    from app.fleet.tool_discovery import check_availability

    valid: list[str] = []
    for name in names:
        if not isinstance(name, str):
            continue
        if name in _DENYLISTED_TOOLS:
            continue
        if not check_availability(name):
            continue
        if name not in valid:
            valid.append(name)
    return valid


def _extract_tool_use_input(response: Any, tool_name: str) -> dict[str, Any] | None:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(getattr(block, "input", {}) or {})
    return None


def _audit_planning_call(
    *,
    task_id: str,
    capability_gap: str,
    chosen_tools: list[str],
    chosen_model: str,
    outcome: str,
) -> None:
    try:
        from app.fleet.audit_log import audit

        audit(
            "barot_agent_plan",
            "barot_agent",
            f"Planned tool profile for capability gap {capability_gap!r} "
            f"(task {task_id!r}): {outcome}",
            task_id=task_id or None,
            details={
                "capability_gap": capability_gap,
                "chosen_tools": chosen_tools,
                "chosen_model": chosen_model,
                "outcome": outcome,
            },
            outcome="success" if outcome == "success" else "failure",
        )
    except Exception:
        logger.debug("barot_agent: audit log failed (non-fatal)", exc_info=True)


def _plan_tool_profile(
    *, task_id: str, required_capability: str, task_description: str
) -> ToolProfilePlan:
    """One Claude API call (per attempted model) that asks the model to
    choose a minimal, real tool subset plus a task briefing. Tries
    settings.barot_agent_model, then settings.barot_agent_fallback_models
    in order, on any failure or unusable response. Never raises."""
    from app.agents.base_graph import _call_anthropic, _make_client
    from app.config import get_settings

    settings = get_settings()
    models_to_try = [settings.barot_agent_model, *settings.barot_agent_fallback_models]
    catalog = _candidate_tool_catalog()
    catalog_text = "\n".join(f"- {name}: {purpose}" for name, purpose in catalog)

    user_message = (
        f"Capability gap: {required_capability!r}\n"
        f"Task #{task_id}: {task_description}\n\n"
        f"CANDIDATE TOOLS (choose only from this list):\n{catalog_text}"
    )

    last_reason = "no models configured"
    for model in models_to_try:
        if not model:
            continue
        try:
            client = _make_client()
            response = _call_anthropic(
                client,
                model=model,
                max_tokens=1024,
                system=[{"type": "text", "text": _PLANNING_SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": user_message}],
                tools=[_PLAN_TOOL_PROFILE_TOOL],
                tool_choice={"type": "tool", "name": "plan_tool_profile"},
            )
        except Exception as exc:
            logger.warning("barot_agent: planning call failed on model %s: %s", model, exc)
            last_reason = f"api_error: {exc}"
            _audit_planning_call(
                task_id=task_id,
                capability_gap=required_capability,
                chosen_tools=[],
                chosen_model=model,
                outcome=last_reason,
            )
            continue

        parsed = _extract_tool_use_input(response, "plan_tool_profile")
        if parsed is None:
            last_reason = "no plan_tool_profile tool_use in response"
            _audit_planning_call(
                task_id=task_id,
                capability_gap=required_capability,
                chosen_tools=[],
                chosen_model=model,
                outcome=last_reason,
            )
            continue

        tool_names = _validate_tool_names(parsed.get("tool_names", []))
        briefing = str(parsed.get("briefing", "")).strip()

        if not tool_names or not briefing:
            last_reason = "empty tool_names or briefing after validation"
            _audit_planning_call(
                task_id=task_id,
                capability_gap=required_capability,
                chosen_tools=tool_names,
                chosen_model=model,
                outcome=last_reason,
            )
            continue

        _audit_planning_call(
            task_id=task_id,
            capability_gap=required_capability,
            chosen_tools=tool_names,
            chosen_model=model,
            outcome="success",
        )
        return ToolProfilePlan(tool_names=tool_names, briefing=briefing, model_used=model)

    return ToolProfilePlan.failed(last_reason)


# ---------------------------------------------------------------------------
# Entry point — called by fleet_manager.select() right before it would
# otherwise return None.
# ---------------------------------------------------------------------------


def try_fill_capability_gap(
    *,
    required_capability: str,
    task_id: str,
    task_description: str,
    repo_path: str,
    requested_side_effects: list[str] | None = None,
) -> BarotDecision:
    """Never raises. Returns a BarotDecision — success=True means the
    caller (fleet_manager._decline_or_fill_gap) should re-run select();
    anything else means the caller must return None exactly as before."""
    from app.config import get_settings

    settings = get_settings()

    if not settings.barot_agent_enabled:
        return BarotDecision(False, False, None, "barot_agent_disabled")

    if not required_capability:
        return BarotDecision(False, False, None, "empty_capability")

    if TEMP_AGENT_EXECUTION.get():
        return BarotDecision(False, False, None, "recursion_blocked")

    if not task_id or not task_description:
        return BarotDecision(False, False, None, "missing_task_context")

    from app.agents.temporary_agent import get_temporary_agent_pool

    pool = get_temporary_agent_pool()
    if not pool.has_capacity():
        return BarotDecision(False, False, None, "at_capacity")

    try:
        plan = _plan_tool_profile(
            task_id=task_id,
            required_capability=required_capability,
            task_description=task_description,
        )
    except Exception:
        logger.exception("barot_agent: _plan_tool_profile raised unexpectedly")
        return BarotDecision(True, False, None, "planning_exception")

    if not plan.ok:
        return BarotDecision(True, False, None, plan.failure_reason or "planning_failed")

    try:
        slot = pool.spawn(
            task_id=task_id,
            required_capability=required_capability,
            task_description=task_description,
            briefing=plan.briefing,
            tool_names=plan.tool_names,
            model=plan.model_used,
            repo_path=repo_path,
        )
    except Exception:
        logger.exception("barot_agent: pool.spawn raised unexpectedly")
        return BarotDecision(True, False, None, "spawn_exception")

    if slot is None:
        return BarotDecision(True, False, None, "spawn_declined")

    return BarotDecision(True, True, slot.role_name, "spawned")


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                # Deliberately empty — see module docstring. This is what
                # makes find_by_capability() structurally unable to ever
                # return barot_agent itself as a gap-filler target.
                capabilities=[],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
