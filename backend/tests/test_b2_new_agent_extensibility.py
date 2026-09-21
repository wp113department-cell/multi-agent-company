"""Verification batch B2, items #373/#374 — a new agent joins the fleet by adding a
module (AGENT_CONTRACT + one run_* entry point) + role file + model entry, with ZERO
edits to the manager, dispatcher or the specialized-agents router. A synthetic module
stands in for the file, so nothing is written into app/agents."""

from __future__ import annotations

import sys
import types

import pytest

from app.api import specialized_agents as sa
from app.fleet.agent_registry import AgentRegistry
from app.fleet.capability_registry import AgentCapability, CapabilityRegistry
from app.fleet.fleet_manager import FleetManager
from app.fleet.metrics import MetricsCollector

NAME = "zz_b2_probe_agent"


def _module(*, contract: bool = True, runs: int = 1) -> types.ModuleType:
    mod = types.ModuleType(f"app.agents.{NAME}")
    if contract:
        mod.AGENT_CONTRACT = {"name": NAME, "capabilities": ["probe_capability"]}  # type: ignore[attr-defined]
    for i in range(runs):
        fn_name = "run_probe" if i == 0 else f"run_probe_{i}"

        def fn(task_id, description, repo_path=None):  # noqa: ANN001
            return "ran"

        fn.__name__ = fn_name
        fn.__module__ = mod.__name__
        setattr(mod, fn_name, fn)
    return mod


@pytest.fixture(autouse=True)
def _clean():
    sa._DISCOVERY_CACHE.pop(NAME, None)
    yield
    sys.modules.pop(f"app.agents.{NAME}", None)
    sa._DISCOVERY_CACHE.pop(NAME, None)


def test_a_module_with_a_contract_and_one_run_function_is_dispatchable(
    monkeypatch,
) -> None:
    monkeypatch.setitem(sys.modules, f"app.agents.{NAME}", _module())
    fn = sa._discover_agent_fn(NAME)
    assert fn is not None and fn.__name__ == "run_probe"
    assert sa._agent_is_dispatchable(NAME)
    assert sa._load_agent_fn(NAME)(1, "d") == "ran"


@pytest.mark.parametrize(
    "mod",
    [_module(contract=False), _module(runs=2), _module(runs=0)],
    ids=["no-contract", "ambiguous-two-run-functions", "no-run-function"],
)
def test_it_never_guesses(mod, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, f"app.agents.{NAME}", mod)
    assert sa._discover_agent_fn(NAME) is None
    assert not sa._agent_is_dispatchable(NAME)
    with pytest.raises(ValueError):
        sa._load_agent_fn(NAME)


def test_scan_and_apply_pairs_are_reserved_and_never_auto_dispatched(
    monkeypatch,
) -> None:
    mod = types.ModuleType(f"app.agents.{NAME}")
    mod.AGENT_CONTRACT = {"name": NAME}  # type: ignore[attr-defined]
    for n in ("run_x_scan", "run_x_apply"):
        f = lambda *a, **k: None  # noqa: E731
        f.__name__, f.__module__ = n, mod.__name__
        setattr(mod, n, f)
    monkeypatch.setitem(sys.modules, f"app.agents.{NAME}", mod)
    assert sa._discover_agent_fn(NAME) is None


@pytest.mark.parametrize(
    "name",
    [
        ".",
        "..",
        "...",
        "a..b",
        ".x",
        "x.",
        "a b",
        "a\x00b",
        "pm.py",
        "-",
        "x" * 300,
        "tools.write_file",
        "os",
        "sys",
        "__init__",
    ],
)
def test_hostile_agent_names_never_raise_and_never_resolve(name) -> None:
    assert sa._discover_agent_fn(name) is None
    assert sa._agent_is_dispatchable(name) is False


def test_the_fleet_dispatches_a_new_capability_with_no_manager_change() -> None:
    cr, ar = CapabilityRegistry(), AgentRegistry()
    cr.register(
        AgentCapability(
            name=NAME,
            description="d",
            tools=[],
            input_types=["t"],
            output_types=["o"],
            capabilities=["probe_capability"],
        )
    )
    fm = FleetManager(cr, ar, MetricsCollector())
    out = fm.dispatch("probe_capability", "t1", {})
    assert out["status"] == "dispatched" and out["agent_name"] == NAME
