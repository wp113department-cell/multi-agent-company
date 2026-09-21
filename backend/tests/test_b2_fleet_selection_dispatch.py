"""Verification batch B2, items #52-#57 (agent selection: capability, tools,
workload, health/success, tenure, confidence), #54 (workload) and #374 (a new
agent becomes dispatchable from data alone).

Real registries, no mocks of the scoring. Defect proven under a thread stress
test before the fix: FleetManager.dispatch() = select() (availability CHECK) then
start_task() (mark running) — two steps — so two concurrent dispatchers could both
be handed the same single-flight agent (1 in 400 rounds of 6 concurrent dispatches).
"""

from __future__ import annotations

import logging
import threading

import pytest

from app.config import get_settings
from app.fleet.agent_registry import AgentRegistry
from app.fleet.capability_registry import AgentCapability, CapabilityRegistry
from app.fleet.fleet_manager import FleetManager
from app.fleet.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def _no_gap_filling(monkeypatch):
    monkeypatch.setattr(get_settings(), "barot_agent_enabled", False)
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def cap(name: str, caps=("code",), **kw) -> AgentCapability:
    return AgentCapability(
        name=name,
        description=name,
        tools=["read_file"],
        input_types=["t"],
        output_types=["o"],
        capabilities=list(caps),
        **kw,
    )


def fresh(*caps: AgentCapability) -> tuple[FleetManager, AgentRegistry]:
    cr, ar = CapabilityRegistry(), AgentRegistry()
    for c in caps:
        cr.register(c)
        ar.register(c.name)
    return FleetManager(cr, ar, MetricsCollector()), ar


def pick(fm: FleetManager) -> str | None:
    plan = fm.select("code")
    return plan.agent_name if plan else None


def test_capability_matching_and_unknown_capability() -> None:
    fm, _ = fresh(cap("A"), cap("doc_agent", caps=("docs",)))
    assert pick(fm) == "A"
    assert fm.select("docs").agent_name == "doc_agent"
    assert fm.select("nonexistent") is None


def test_workload_busy_agents_are_skipped_and_all_busy_declines() -> None:
    fm, ar = fresh(cap("A"), cap("B"))
    ar.start_task("A", "t1")
    assert pick(fm) == "B"
    ar.start_task("B", "t2")
    assert pick(fm) is None


def test_health_and_lifecycle_exclusions() -> None:
    fm, ar = fresh(cap("A"), cap("B"))
    ar.get("A").health = "unhealthy"
    assert pick(fm) == "B"
    fm, ar = fresh(cap("A"), cap("B"))
    ar.disable("A", "maintenance")
    assert pick(fm) == "B"
    ar.retire("B", "gone")
    assert pick(fm) is None
    ar.reactivate("A")
    assert pick(fm) == "A"


@pytest.mark.parametrize(
    "setup, expected",
    [
        (lambda ar, cr: setattr(ar.get("A"), "health", "degraded"), "B"),
        (lambda ar, cr: setattr(ar.get("A"), "error_count", 3), "B"),
        (lambda ar, cr: setattr(ar.get("A"), "avg_confidence", 0.3), "B"),
        (lambda ar, cr: setattr(ar.get("B"), "total_runs", 200), "B"),  # tenure
        (lambda ar, cr: setattr(cr.get("A"), "success_rate", 0.4), "B"),
    ],
)
def test_scoring_factors_rank_as_documented(setup, expected) -> None:
    fm, ar = fresh(cap("A"), cap("B"))
    setup(ar, fm._caps)
    assert pick(fm) == expected


def test_tool_availability_check_skips_an_agent_declaring_an_unresolvable_tool() -> (
    None
):
    fm, _ = fresh(cap("A"), cap("B"))
    fm._caps.get("A").tools = ["totally_fake_tool"]
    assert fm.select("code", verify_tool_availability=True).agent_name == "B"
    assert fm.select("code").agent_name in ("A", "B")  # opt-in only


def test_prefer_low_risk_skips_high_risk_agents() -> None:
    fm, _ = fresh(cap("A", risk_level="high"), cap("B", risk_level="low"))
    assert fm.select("code", prefer_low_risk=True).agent_name == "B"


def test_a_new_agent_is_dispatchable_from_data_alone() -> None:
    fm, _ = fresh(cap("A"))
    fm._caps.register(cap("brand_new_agent", caps=("quantum_docs",)))
    out = fm.dispatch("quantum_docs", "t1", {})
    assert out["status"] == "dispatched" and out["agent_name"] == "brand_new_agent"


def test_dispatch_marks_running_and_second_caller_is_declined() -> None:
    fm, ar = fresh(cap("A"))
    assert fm.dispatch("code", "t1", {})["status"] == "dispatched"
    assert ar.get("A").current_task_id == "t1"
    assert fm.dispatch("code", "t2", {})["status"] == "no_agent_available"
    fm.complete("A")
    assert fm.dispatch("code", "t3", {})["status"] == "dispatched"


def test_try_start_task_is_an_atomic_claim() -> None:
    ar = AgentRegistry()
    ar.register("A")
    assert ar.try_start_task("A", "t1") is not None
    assert ar.try_start_task("A", "t2") is None
    assert (
        ar.get("A").current_task_id == "t1"
    ), "the loser must not overwrite the winner's task"


def test_dispatch_survives_a_stale_selection() -> None:
    """A caller whose select() result went stale (another caller claimed the agent
    in between) must NOT be handed the same agent."""
    fm, ar = fresh(cap("A"))
    real_select = fm.select
    calls = {"n": 0}

    def stale_then_real(*a, **kw):
        calls["n"] += 1
        plan = real_select(*a, **kw)
        if calls["n"] == 1:
            ar.start_task("A", "someone-else")  # claimed between select and start
        return plan

    fm.select = stale_then_real  # type: ignore[method-assign]
    out = fm.dispatch("code", "mine", {})
    assert out["status"] == "no_agent_available"
    assert ar.get("A").current_task_id == "someone-else"


def test_concurrent_dispatch_never_double_books_one_agent() -> None:
    n_threads, rounds = 6, 300
    for _ in range(rounds):
        fm, _ar = fresh(cap("A"))
        barrier = threading.Barrier(n_threads)
        results: list[str] = []

        def worker(i: int) -> None:
            barrier.wait()
            results.append(fm.dispatch("code", f"t{i}", {})["status"])

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert results.count("dispatched") == 1, results


def test_concurrent_dispatch_spreads_across_agents_without_overlap() -> None:
    for _ in range(150):
        fm, _ar = fresh(cap("A"), cap("B"))
        barrier = threading.Barrier(6)
        out: list[dict] = []

        def worker(i: int) -> None:
            barrier.wait()
            out.append(fm.dispatch("code", f"t{i}", {}))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        got = [o["agent_name"] for o in out if o["status"] == "dispatched"]
        assert sorted(got) == ["A", "B"], got
