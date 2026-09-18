"""temporary_agent — the short-lived worker barot_agent synthesizes to fill a
capability gap, plus the central pool/lifecycle manager that owns every live
instance.

Not a static, permanent agent module like the other ~86 files in this
directory: there is no fixed AGENT_CONTRACT or _register() call here,
because there is no single "temporary_agent" capability entry — each spawn
gets its own uniquely-named AgentCapability/AgentInstance, registered and
deregistered at runtime by TemporaryAgentPool. See app/agents/barot_agent.py
for the planning/guardrail logic that decides WHAT to spawn; this module is
only concerned with HOW a spawn is built, run, and torn down.

Design notes (see the barot_agent plan doc for the full rationale):
- role_name doubles as the identity key for capability_registry,
  agent_registry, ModelRouter, dynamic_agent_runtime, and the AgentRun.
  agent_type column (via run_agent_graph's own chokepoint) — it must be
  globally unique per spawn, which is what the naming pattern guarantees.
- load_role(role_name) (app/agents/base.py) hard-requires a real
  roles/{role_name}.md file; there is no system-prompt override anywhere in
  the execution engine. We satisfy this by copying the single static,
  human-reviewed roles/temporary_agent.md template to a per-instance
  filename at spawn and deleting it at teardown — zero changes to the
  shared base_graph.py/base.py.
- A running run_agent_graph() call is a plain blocking call and cannot be
  forcibly killed (no such primitive exists anywhere in this codebase or in
  Python). TTL enforcement therefore tears down registry state (capability
  entry, agent-registry entry, model-router override, role file, pool slot)
  immediately, freeing the slot — while any still-running execution thread
  (owned by whoever actually invoked run_temporary_agent — see below) is
  abandoned; its eventual result, if any, is simply never surfaced.
- TemporaryAgentPool.spawn() only REGISTERS a temp agent (capability_
  registry, agent_registry, ModelRouter override, dynamic_agent_runtime) —
  it never executes the task itself. Execution happens later, through the
  exact same path any other agent's dispatch goes through: whoever calls
  fleet_manager.dispatch() and gets back a DispatchPlan is responsible for
  resolving and invoking the agent function (specialized_agents.py's
  dispatch endpoint does this via a background task; delegation.py's
  adapter path does it inline) — resolved via dynamic_agent_runtime's
  fallback. This mirrors FleetManager.dispatch()'s own documented contract
  ("does NOT actually call the agent") and avoids a real double-execution
  bug an earlier version of this module had (spawn() eagerly starting a
  worker thread AND the real dispatch caller separately invoking the same
  resolved function again).
"""

from __future__ import annotations

import functools
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.agents.agent_result import AgentResult

logger = logging.getLogger(__name__)

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------------------
# submit_temporary_agent_result — a static tool spec + handler, always
# appended to every spawn's granted tools. Never offered to barot_agent's
# planning call as a choice (mirrors how no real agent's LLM "picks" its own
# bespoke submit_* tool — see security_reviewer.py's submit_security_report).
# ---------------------------------------------------------------------------

SUBMIT_TEMPORARY_AGENT_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_temporary_agent_result",
    "description": (
        "Submit the final result of your task. Always call this before "
        "finishing, even if you could only partially complete the task with "
        "the tools you were granted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What you did and what the outcome was.",
            },
            "status": {
                "type": "string",
                "enum": ["completed", "blocked"],
                "description": "'completed' if you finished the task, "
                "'blocked' if your granted tools were insufficient.",
            },
            "files_touched": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths of any files you read or modified that "
                "are directly relevant to the result.",
            },
        },
        "required": ["summary", "status"],
    },
}


def _make_submit_temporary_agent_result_handler() -> Callable[[dict[str, Any]], str]:
    def _handler(inp: dict[str, Any]) -> str:
        return "Result submitted."

    return _handler


# ---------------------------------------------------------------------------
# Tool/handler resolution — reuses the real make_read_only_handlers bundle
# and filters both the spec list and the handler dict down to the requested
# subset. Never adds a tool that wasn't already requested (defense in depth
# alongside barot_agent._validate_tool_names).
# ---------------------------------------------------------------------------


def make_temporary_agent_tools_and_handlers(
    *, tool_names: list[str], scope: str, repo_path: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Builds the (tools, tool_handlers) pair for a temporary_agent spawn.

    scope == "planned": hard-capped to the real read-only bundle regardless
    of what tool_names contains — write/bash tools are dropped even if
    somehow requested, since "planned" scope has no worktree to safely back
    them against.

    scope == "full": not implemented in this version (see
    Settings.barot_agent_default_tool_scope's own docstring) — raises
    NotImplementedError so a misconfiguration fails loudly at spawn time
    rather than silently granting nothing.
    """
    if scope == "full":
        raise NotImplementedError(
            "temporary_agent scope='full' (write/bash tools backed by an "
            "ephemeral worktree) is not implemented in this version — set "
            "barot_agent_default_tool_scope='planned' or leave it at its "
            "default."
        )
    if scope != "planned":
        raise ValueError(f"Unknown temporary_agent tool scope: {scope!r}")

    from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers

    all_handlers = make_read_only_handlers(repo_path)
    requested = set(tool_names)

    filtered_specs = [t for t in READ_ONLY_TOOLS if t["name"] in requested]
    filtered_handlers = {
        name: fn for name, fn in all_handlers.items() if name in requested
    }

    filtered_specs.append(SUBMIT_TEMPORARY_AGENT_RESULT_TOOL)
    filtered_handlers["submit_temporary_agent_result"] = (
        _make_submit_temporary_agent_result_handler()
    )

    return filtered_specs, filtered_handlers


def _derive_risk_level(tool_names: list[str]) -> str:
    """Max risk level across granted tools, via tool_manifest — the same
    risk vocabulary/mechanism real agents' hand-set risk_level is drawn
    from, never trusting the planning LLM's own self-assessment."""
    from app.fleet.tool_manifest import get_manifest

    worst = "low"
    for name in tool_names:
        entry = get_manifest(name)
        if entry is None:
            continue
        if _RISK_ORDER.get(entry.risk_level, 0) > _RISK_ORDER.get(worst, 0):
            worst = entry.risk_level
    return worst


# ---------------------------------------------------------------------------
# TempAgentSlot / TemporaryAgentPool
# ---------------------------------------------------------------------------


@dataclass
class TempAgentSlot:
    role_name: str
    task_id: str
    required_capability: str
    granted_tools: list[str]
    model: str
    repo_path: str
    spawned_at: datetime
    ttl_deadline: datetime
    scrapped: bool = False
    scrap_reason: str | None = None

    def seconds_remaining(self) -> float:
        return max(
            0.0, (self.ttl_deadline - datetime.now(timezone.utc)).total_seconds()
        )


class TemporaryAgentPool:
    """Owned exclusively by barot_agent — deliberately NOT
    agent_registry.available()/.running(), since those mix in all ~86 real
    agents. One Lock (not RLock — no re-entrant call pattern here) guards
    only in-memory dict mutation; it is never held across a call into
    capability_registry/agent_registry/ModelRouter/the filesystem, mirroring
    why AgentRegistry.fail_task() fires its own notification outside its own
    lock (agent_registry.py)."""

    def __init__(self, max_concurrent: int | None = None) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, TempAgentSlot] = {}
        self._max_concurrent_override = max_concurrent

    def _max_concurrent(self) -> int:
        if self._max_concurrent_override is not None:
            return self._max_concurrent_override
        from app.config import get_settings

        return get_settings().barot_agent_max_concurrent_temp_agents

    def has_capacity(self) -> bool:
        """Fast-path check used before doing the (expensive) Claude planning
        call. Not authoritative on its own — spawn() re-checks atomically
        under the lock to close the check-then-act race."""
        with self._lock:
            return len(self._slots) < self._max_concurrent()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            slots = list(self._slots.values())
        return [
            {
                "role_name": s.role_name,
                "task_id": s.task_id,
                "required_capability": s.required_capability,
                "granted_tools": list(s.granted_tools),
                "model": s.model,
                "spawned_at": s.spawned_at.isoformat(),
                "ttl_deadline": s.ttl_deadline.isoformat(),
                "seconds_remaining": s.seconds_remaining(),
            }
            for s in slots
        ]

    def spawn(
        self,
        *,
        task_id: str,
        required_capability: str,
        task_description: str,
        briefing: str,
        tool_names: list[str],
        model: str,
        repo_path: str,
    ) -> TempAgentSlot | None:
        """Atomically re-checks capacity and, if there's room, reserves a
        slot and wires the instance into every registry a real agent uses —
        capability_registry, agent_registry (in SLEEP/available state, same
        as any freshly-registered real agent), ModelRouter's override table,
        and dynamic_agent_runtime. Returns None (and cleans up any partial
        registration) on any failure — never raises.

        Deliberately does NOT execute the task itself. That happens later,
        exactly like any other agent, when whatever called
        fleet_manager.dispatch() resolves and invokes the function this
        registers into dynamic_agent_runtime (run_temporary_agent, bound to
        this spawn's specifics via functools.partial). This mirrors
        FleetManager.dispatch()'s own documented contract ("does NOT
        actually call the agent — that is the caller's responsibility") —
        barot_agent's spawn() must not special-case that by calling it
        eagerly itself, or a real caller that also invokes the resolved
        function (as specialized_agents.py's dispatch endpoint does via
        background_tasks) would run it twice."""
        from app.config import get_settings

        settings = get_settings()
        role_name = self._generate_name(
            task_id=task_id, required_capability=required_capability
        )

        with self._lock:
            if len(self._slots) >= self._max_concurrent():
                return None
            # Reserve the slot immediately (under the same lock as the
            # capacity check) so a second concurrent spawn() can't also
            # pass the check above before this one finishes registering.
            placeholder = TempAgentSlot(
                role_name=role_name,
                task_id=task_id,
                required_capability=required_capability,
                granted_tools=list(tool_names),
                model=model,
                repo_path=repo_path,
                spawned_at=datetime.now(timezone.utc),
                ttl_deadline=datetime.now(timezone.utc)
                + timedelta(minutes=settings.barot_agent_temp_agent_ttl_minutes),
            )
            self._slots[role_name] = placeholder

        try:
            self._write_role_file(role_name)

            risk_level = _derive_risk_level(tool_names)
            from app.fleet.capability_registry import AgentCapability, register
            from app.fleet.agent_registry import get_agent_registry
            from app.fleet.model_router import get_model_router
            from app.fleet.dynamic_agent_runtime import register_runtime_agent_fn

            register(
                AgentCapability(
                    name=role_name,
                    description=(
                        f"Just-in-time temporary agent synthesized by "
                        f"barot_agent for capability {required_capability!r} "
                        f"(task {task_id})."
                    ),
                    tools=list(tool_names),
                    input_types=["task_id", "description", "repo_path"],
                    output_types=["AgentResult"],
                    capabilities=[required_capability],
                    dependencies=[],
                    risk_level=risk_level,
                    requires_worktree=False,
                    requires_db=False,
                )
            )
            get_agent_registry().register(
                role_name,
                is_temporary=True,
                spawned_by="barot_agent",
                task_id=task_id,
                ttl_deadline=placeholder.ttl_deadline.isoformat(),
            )
            get_model_router().set_override(role_name, model=model)

            # repo_path is deliberately NOT pre-bound here — every real
            # caller of the resolved runtime function (specialized_agents.py,
            # delegation.py) supplies (task_id, description, repo_path)
            # positionally, per dynamic_agent_runtime.RuntimeAgentFn's
            # shape, with its OWN properly-resolved repo_path (this spawn's
            # own repo_path argument may be empty/unknown at gap-fill-
            # decision time — see fleet_manager.select()'s own docstring).
            bound_run_fn = functools.partial(
                run_temporary_agent,
                role_name=role_name,
                tool_names=list(tool_names),
                model=model,
                briefing=briefing,
                required_capability=required_capability,
                # The specific pool instance that spawned this slot — never
                # the global singleton by assumption — so self-scrap always
                # targets whichever pool actually owns this slot (matters
                # for isolated-pool tests, and is simply more correct: this
                # spawn's lifecycle belongs to the pool that created it).
                pool=self,
            )
            register_runtime_agent_fn(role_name, bound_run_fn)

            return placeholder
        except Exception:
            logger.exception(
                "barot_agent: failed to fully spawn temporary agent %s — rolling back",
                role_name,
            )
            self.scrap(role_name, reason="spawn_failed")
            return None

    def scrap(self, role_name: str, reason: str) -> None:
        """Central teardown — idempotent (safe to call twice from a racing
        TTL-sweep vs. natural-completion path). Never raises."""
        with self._lock:
            slot = self._slots.pop(role_name, None)
        if slot is None:
            return

        from app.fleet.capability_registry import deregister as deregister_capability
        from app.fleet.agent_registry import get_agent_registry
        from app.fleet.model_router import get_model_router
        from app.fleet.dynamic_agent_runtime import unregister_runtime_agent_fn
        from app.fleet.audit_log import audit

        try:
            deregister_capability(role_name)
        except Exception:
            logger.debug("scrap(%s): capability deregister failed", role_name, exc_info=True)
        try:
            get_agent_registry().deregister(role_name)
        except Exception:
            logger.debug("scrap(%s): agent_registry deregister failed", role_name, exc_info=True)
        try:
            get_model_router().clear_override(role_name)
        except Exception:
            logger.debug("scrap(%s): model_router clear_override failed", role_name, exc_info=True)
        try:
            unregister_runtime_agent_fn(role_name)
        except Exception:
            logger.debug("scrap(%s): dynamic_agent_runtime unregister failed", role_name, exc_info=True)
        try:
            self._role_file_path(role_name).unlink(missing_ok=True)
        except Exception:
            logger.debug("scrap(%s): role file cleanup failed", role_name, exc_info=True)

        slot.scrapped = True
        slot.scrap_reason = reason
        try:
            audit(
                "temporary_agent_scrapped",
                "barot_agent",
                f"Scrapped temporary agent {role_name!r} (reason={reason})",
                task_id=slot.task_id or None,
                details={
                    "role_name": role_name,
                    "required_capability": slot.required_capability,
                    "reason": reason,
                },
            )
        except Exception:
            logger.debug("scrap(%s): audit log failed", role_name, exc_info=True)

        logger.info(
            "barot_agent: scrapped temporary agent %s (reason=%s)", role_name, reason
        )

    def sweep_expired(self) -> list[str]:
        """Called by the TTL sweep loop (app/main.py). Returns the
        role_names torn down this sweep."""
        now = datetime.now(timezone.utc)
        with self._lock:
            expired = [
                name
                for name, slot in self._slots.items()
                if slot.ttl_deadline <= now
            ]
        for name in expired:
            self.scrap(name, reason="ttl_exceeded")
        return expired

    def _generate_name(self, *, task_id: str, required_capability: str) -> str:
        from app.config import get_settings

        pattern = get_settings().barot_agent_temp_agent_naming_pattern
        short_uuid = uuid.uuid4().hex[:8]
        try:
            return pattern.format(
                task_id=task_id, short_uuid=short_uuid, capability=required_capability
            )
        except (KeyError, IndexError):
            logger.warning(
                "barot_agent: barot_agent_temp_agent_naming_pattern %r is "
                "invalid — falling back to the built-in default pattern",
                pattern,
            )
            return f"temporary_agent-{task_id}-{short_uuid}"

    def _role_file_path(self, role_name: str) -> Path:
        from app.agents.base import _ROLES_DIR

        return _ROLES_DIR / f"{role_name}.md"

    def _write_role_file(self, role_name: str) -> None:
        from app.agents.base import _ROLES_DIR

        template_path = _ROLES_DIR / "temporary_agent.md"
        content = template_path.read_text(encoding="utf-8")
        self._role_file_path(role_name).write_text(content, encoding="utf-8")


_pool: TemporaryAgentPool | None = None
_pool_lock = threading.Lock()


def get_temporary_agent_pool() -> TemporaryAgentPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = TemporaryAgentPool()
    return _pool


def reset_temporary_agent_pool() -> None:
    """Test-only: reset the singleton."""
    global _pool
    _pool = None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_temporary_agent(
    task_id: int,
    description: str,
    repo_path: str = "",
    *,
    role_name: str,
    tool_names: list[str],
    model: str,
    briefing: str,
    required_capability: str,
    pool: "TemporaryAgentPool",
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    """The function registered per-instance into dynamic_agent_runtime — a
    bound functools.partial per spawn closes over role_name/tool_names/
    model/briefing/required_capability/pool so this one function body
    serves every spawned instance. Matches the (task_id, description,
    repo_path) shape specialized_agents.py's dispatch and delegation.py's
    adapters already expect (pool is bound at spawn time, not part of that
    positional call shape). Never raises — errors become status="failed",
    exactly like every other real agent's own run_* function.

    Fleet-OS flags (planning/memory/reflection/critique) are off: a
    temporary_agent is single-shot, with no self-improvement machinery of
    its own to opt into.

    Self-contained cleanup: always scraps its own slot, on the SAME pool
    instance that spawned it (never a hardcoded global singleton — matters
    for isolated-pool tests, and is simply correct: this spawn's lifecycle
    belongs to whichever pool created it), in a finally block on the way
    out, regardless of who invoked this function or on which thread (a
    FastAPI background task, delegation.py's own worker thread, or a direct
    call) — so a completed task frees its slot immediately, not only at
    TTL. Idempotent against a racing TTL sweep that scrapped the slot first
    (TemporaryAgentPool.scrap() is itself idempotent)."""
    from app.agents.barot_agent import TEMP_AGENT_EXECUTION

    # Belt-and-suspenders anti-recursion guard (see barot_agent.py's module
    # docstring) — set for the lifetime of this call on THIS thread only,
    # always reset in the finally block below regardless of outcome.
    _token = TEMP_AGENT_EXECUTION.set(True)
    try:
        return _run_temporary_agent_inner(
            task_id,
            description,
            repo_path,
            role_name=role_name,
            tool_names=tool_names,
            model=model,
            briefing=briefing,
            required_capability=required_capability,
        )
    finally:
        TEMP_AGENT_EXECUTION.reset(_token)
        pool.scrap(role_name, reason="completed")


def _run_temporary_agent_inner(
    task_id: int,
    description: str,
    repo_path: str,
    *,
    role_name: str,
    tool_names: list[str],
    model: str,
    briefing: str,
    required_capability: str,
) -> AgentResult:
    from app.agents.base_graph import VerificationConfig, run_agent_graph
    from app.fleet.audit_log import audit

    effective_repo_path = repo_path or ""

    try:
        tools, handlers = make_temporary_agent_tools_and_handlers(
            tool_names=tool_names, scope="planned", repo_path=effective_repo_path
        )
    except Exception as exc:
        logger.exception("temporary_agent %s: failed to build tools/handlers", role_name)
        return AgentResult(
            summary=f"temporary_agent setup failed: {exc}",
            findings=[],
            files_touched=[],
            verified=False,
            requires_human_approval=False,
            tokens_in=0,
            tokens_out=0,
            status="failed",
            raw={},
        )

    initial_message = (
        f"Task #{task_id} — {description}\n\n"
        f"Briefing from barot_agent (capability gap: {required_capability!r}):\n"
        f"{briefing}\n\n"
        f"You have been granted exactly these tools: "
        f"{', '.join(sorted(tool_names))}. Use only these — no others exist "
        f"for this task."
    )

    try:
        final_state = run_agent_graph(
            task_id=str(task_id),
            role_name=role_name,
            model=model,
            tools=tools,
            tool_handlers=handlers,
            verification_cfg=VerificationConfig(),
            initial_message=initial_message,
            task_description=f"Just-in-time capability fill: {required_capability} — task {task_id}",
            repo_path=effective_repo_path,
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_critique=False,
            enable_replanning=False,
            max_turns=12,
        )
    except Exception as exc:
        logger.exception("temporary_agent %s: run_agent_graph raised", role_name)
        try:
            audit(
                "temporary_agent_run_failed",
                role_name,
                f"temporary_agent run raised: {exc}",
                task_id=str(task_id),
                outcome="failure",
            )
        except Exception:
            pass
        return AgentResult(
            summary=f"temporary_agent error: {exc}",
            findings=[],
            files_touched=[],
            verified=False,
            requires_human_approval=False,
            tokens_in=0,
            tokens_out=0,
            status="failed",
            raw={},
        )

    submitted = bool(final_state.get("submitted"))
    raw = final_state.get("result") or {}
    files_touched = list(raw.get("files_touched", []))

    if not submitted:
        return AgentResult(
            summary="temporary_agent did not call submit_temporary_agent_result "
            "within the turn limit",
            findings=[],
            files_touched=files_touched,
            verified=False,
            requires_human_approval=False,
            tokens_in=final_state.get("tokens_in", 0),
            tokens_out=final_state.get("tokens_out", 0),
            status="blocked",
            raw=raw,
        )

    status = str(raw.get("status", "completed"))
    if status not in ("completed", "blocked"):
        status = "completed"

    return AgentResult(
        summary=str(raw.get("summary", "temporary_agent completed with no summary")),
        findings=[],
        files_touched=files_touched,
        verified=submitted,
        requires_human_approval=False,
        tokens_in=final_state.get("tokens_in", 0),
        tokens_out=final_state.get("tokens_out", 0),
        status=status,
        raw=raw,
    )
