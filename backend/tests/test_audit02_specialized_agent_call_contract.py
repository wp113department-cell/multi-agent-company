"""Production audit 02 (2026-09-29) — /api/specialized-agents call contract.

Reproduced before the fix (evidence script
What_is/AUDIT_REPORT/evidence/agent_api_bind_check.py): 16 of the 80 agent
names this router advertised could never run. _agent_call_kwargs always sent
task_id + the description as the "second parameter", so
run_devops(repo_path, task_description) / run_research(task_description, ...)
got an unexpected task_id, and pipeline-internal agents (qa, reviewer,
backend_dev, docs, ...) were missing required context — the background task
raised TypeError after the endpoint had already answered "queued".
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import patch

import pytest

from app.api import specialized_agents as sa
from app.fleet import capability_registry as cr
from tests.test_b7_auth_and_agent_authorization import (  # noqa: F401 — fixtures
    auth,
    client,
    prod_like,
)

cr.ensure_all_agents_registered()
ALL_NAMES = sorted(set(sa._REGISTRY) | set(sa._discoverable_agent_names()))
PIPELINE_ONLY = {
    "backend_dev",
    "frontend_dev",
    "mobile_dev",
    "coder",
    "qa",
    "qa_agent",
    "reviewer",
    "reviewer_agent",
    "docs",
    "docs_agent",
    "planner",
    "executive",
    "executive_agent",
}


def test_every_agent_is_either_callable_or_refused_up_front() -> None:
    """No advertised name may be in the old 'queued, then TypeError' state."""
    for name in ALL_NAMES:
        fn = sa._load_agent_fn(name)
        err = sa._standalone_run_error(name)
        if err is None:
            inspect.signature(fn).bind(**sa._agent_call_kwargs(fn, 1, "d", "/r"))
            assert not inspect.iscoroutinefunction(fn), name
        else:
            assert name in PIPELINE_ONLY, f"{name} unexpectedly refused: {err}"


def test_devops_and_research_now_get_their_real_parameters() -> None:
    from app.agents.devops import run_devops
    from app.agents.research import run_research

    assert sa._agent_call_kwargs(run_devops, 7, "check health", "/r") == {
        "task_id": 7,
        "task_description": "check health",
        "repo_path": "/r",
    }
    assert sa._agent_call_kwargs(run_research, 7, "what is X", "/r") == {
        "task_id": 7,
        "task_description": "what is X",
        "repo_path": "/r",
    }


def test_legacy_second_parameter_convention_still_works() -> None:
    """readme_agent's second parameter is `doc_request` (Day 53 fix) — unchanged."""
    from app.agents.readme_agent import run_readme_agent

    kw = sa._agent_call_kwargs(run_readme_agent, 3, "write a readme", "/r")
    assert kw["doc_request"] == "write a readme" and kw["task_id"] == 3


def test_listing_only_advertises_runnable_agents(client: Any) -> None:  # noqa: F811
    r = client.get("/api/specialized-agents/agents", headers=auth("approver"))
    assert r.status_code == 200
    listed = set(r.json()["agents"])
    assert "devops" in listed and "research_agent" in listed
    assert not (listed & PIPELINE_ONLY)


@pytest.mark.parametrize("name", ["qa", "reviewer", "backend_dev", "executive_agent"])
def test_pipeline_only_agent_is_refused_with_422_not_queued(
    client: Any,  # noqa: F811
    name: str,
) -> None:
    for path in ("run", "run-sync"):
        r = client.post(
            f"/api/specialized-agents/{name}/{path}",
            json={"task_id": 1, "description": "x"},
            headers=auth("approver"),
        )
        assert r.status_code == 422, (path, r.text)
        assert "pipeline" in r.text or "async entry point" in r.text


def test_devops_run_threads_task_id_into_the_graph() -> None:
    """The real run_devops, graph intercepted: task_id now reaches
    run_agent_graph (Day 18 activity-stream convention)."""
    import app.agents.devops as devops

    seen: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"messages": [], "tokens_in": 0, "tokens_out": 0}

    with patch.object(devops, "run_agent_graph", side_effect=_capture):
        fn = sa._load_agent_fn("devops")
        asyncio.run(
            asyncio.to_thread(fn, **sa._agent_call_kwargs(fn, 4242, "health", "/tmp"))
        )
    assert seen["task_id"] == "4242"


def test_every_registered_agent_has_an_explicit_model_route() -> None:
    """Production audit 02: 13 registered agents had no agent_models.json row
    and silently resolved through DEFAULT. Keep routing explicit."""
    from app.fleet.model_router import ModelRouter

    router = ModelRouter()
    registered = {e.name for e in cr._registry.all()}
    missing = sorted(registered - set(router.all_agents()))
    assert missing == [], missing
