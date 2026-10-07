"""Cost modes — economy / balanced / quality (2026-09-29).

One setting that decides how much LLM work every agent run is allowed to do.
Measured before this existed: a 3-subtask task in the default pipeline made
~21 agent runs (PM + Opus architect + Opus decomposer, then dev + QA + reviewer
+ 3 LLM quality gates per subtask), and every run added planner, per-turn
reflection (on the agent's own model), critique and lesson calls — roughly
$20-40 per task.

A profile never removes a safety control: the sandbox, command/path policy,
scoped writes and human approvals are free (no LLM calls) and stay on in every
mode. It only turns off *optional* LLM calls and caps the model tier.

Resolution order: a per-task override (set by the task router via
`use_cost_mode()`, carried into worker threads by contextvars) wins over the
global `COST_MODE` setting. `asyncio.to_thread` copies the current context, so
agents run in threads see the override automatically.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from contextvars import ContextVar
from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class CostProfile:
    name: str
    # highest model tier an agent may use: "haiku" | "sonnet" | None (no cap)
    tier_cap: str | None
    planning: bool  # planner_node: 2 small Haiku calls at graph start
    reflection: bool  # reflection_node: one call on the agent's model EVERY turn
    critique: bool  # critique_node: one review call per submission
    replanning: bool  # replan_node: re-plans when reflection/critique keep failing
    lesson: bool  # post-run lesson extraction call
    llm_quality_gates: (
        bool  # manager's per-subtask security/architecture/dependency agents
    )
    max_turns_cap: int | None  # hard cap on main LLM turns per agent run


PROFILES: dict[str, CostProfile] = {
    "economy": CostProfile(
        name="economy",
        tier_cap="haiku",
        planning=False,
        reflection=False,
        critique=False,
        replanning=False,
        lesson=False,
        llm_quality_gates=False,
        max_turns_cap=15,
    ),
    "balanced": CostProfile(
        name="balanced",
        tier_cap="sonnet",
        planning=True,
        reflection=False,
        critique=True,
        replanning=False,
        lesson=True,
        llm_quality_gates=False,
        max_turns_cap=25,
    ),
    "quality": CostProfile(
        name="quality",
        tier_cap=None,
        planning=True,
        reflection=True,
        critique=True,
        replanning=True,
        lesson=True,
        llm_quality_gates=True,
        max_turns_cap=None,
    ),
}

_override: ContextVar[str | None] = ContextVar("gridiron_cost_mode", default=None)


def get_cost_profile() -> CostProfile:
    name = _override.get() or get_settings().cost_mode
    return PROFILES.get(name, PROFILES["quality"])


@contextlib.contextmanager
def use_cost_mode(name: str | None) -> Iterator[None]:
    """Run a block (and every agent it starts, including in to_thread workers)
    under a specific cost mode. None/unknown = leave the global setting."""
    if not name or name not in PROFILES:
        yield
        return
    token = _override.set(name)
    try:
        yield
    finally:
        _override.reset(token)


def cap_model(model: str, tier: str | None) -> str:
    """Apply the active profile's tier cap to a routed model."""
    cap = get_cost_profile().tier_cap
    if cap is None:
        return model
    s = get_settings()
    if cap == "haiku":
        return s.model_router
    if cap == "sonnet" and tier == "opus":
        return s.model_coder
    return model


# Per-task execution mode (UI redesign, 2026-10-07): the user picks Economy
# (default) or Max on each task; it maps onto the existing profiles above.
EXECUTION_MODE_PROFILE = {"economy": "economy", "max": "quality"}


def task_cost_mode(launch_fn: Any) -> Any:
    """Decorator for the task launch functions (first argument: task_id).

    Reads the task's `execution_mode` and runs the whole launch, including
    every agent it starts in worker threads, under the matching profile via
    `use_cost_mode()`. Works on both queue backends: the override is set
    inside the job itself, not by the request that enqueued it. A task that
    cannot be read keeps the global COST_MODE."""
    import functools

    @functools.wraps(launch_fn)
    async def wrapper(task_id: int, *args: Any, **kwargs: Any) -> Any:
        mode: str | None = None
        try:
            from app.db.models import DevTask
            from app.db.session import get_async_session

            async with get_async_session() as db:
                task = await db.get(DevTask, task_id)
                if task is not None:
                    mode = EXECUTION_MODE_PROFILE.get(str(task.execution_mode))
        except Exception:
            mode = None
        with use_cost_mode(mode):
            return await launch_fn(task_id, *args, **kwargs)

    return wrapper
