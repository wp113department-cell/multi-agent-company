"""plan14 Day 5 Task 10, updated by T2-B1 (2026-09-22, GRIDIRON_PARTIAL #47/#65/#106/#117):
the 4 agent call sites (coder.py, pm.py, qa.py, security_reviewer.py) used to each explicitly read
`settings.replanning_enabled_agents.get("<name>", False)` and pass the result to `run_agent_graph`.

That only ever worked for those 4 agents — the other ~85 real `run_agent_graph()` callers never
passed `enable_replanning` at all, so "fleet-wide default" was unreachable without editing every
one of them. Now `run_agent_graph`'s own `enable_replanning: bool | None = None` parameter resolves
the real fleet default itself (True unless a specific agent is opted out in config) when the caller
passes nothing — so these 4 agents (and the other ~85) now correctly omit the argument entirely and
let `run_agent_graph` do the one, single resolution.

`run_agent_graph` itself is mocked at each agent module's import site for the wiring checks below
(these prove the CALL SITE no longer overrides the fleet default) — the resolution logic itself is
tested directly against the real function in `test_run_agent_graph_replanning_default_resolution`
below, and its end-to-end graph behavior already has separate coverage in
test_phase36_continuous_replanning.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.config import get_settings


def _fake_final_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "tokens_in": 1,
        "tokens_out": 1,
        "submitted": True,
        "result": {},
        "verification": {},
        "confidence": 0.8,
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    "agent_name,run_fn_path,call",
    [
        (
            "coder",
            "app.agents.coder.run_agent_graph",
            lambda: __import__("app.agents.coder", fromlist=["run_coder"]).run_coder(
                task_id=1, plan="do it", worktree_path="/tmp/wt", repo_path="/tmp/repo"
            ),
        ),
    ],
)
def test_coder_no_longer_overrides_enable_replanning_at_its_own_call_site(
    agent_name, run_fn_path, call
) -> None:
    with (
        patch(
            run_fn_path, return_value=_fake_final_state(result={"status": "ok"})
        ) as mock_run,
        patch("app.agents.coder._run_checks", return_value=None),
    ):
        call()
    assert "enable_replanning" not in mock_run.call_args.kwargs


def test_qa_no_longer_overrides_enable_replanning_at_its_own_call_site() -> None:
    with patch(
        "app.agents.qa.run_agent_graph", return_value=_fake_final_state()
    ) as mock_run:
        from app.agents.qa import run_qa

        run_qa(
            task_id=1,
            subtask_id=1,
            files_changed=["a.py"],
            worktree_path="/tmp/wt",
            repo_path="/tmp/repo",
        )
    assert "enable_replanning" not in mock_run.call_args.kwargs


def test_pm_no_longer_overrides_enable_replanning_at_its_own_call_site() -> None:
    with patch(
        "app.agents.pm.run_agent_graph", return_value=_fake_final_state()
    ) as mock_run:
        from app.agents.pm import pm_node

        pm_node(
            {
                "task_title": "t",
                "task_description": "d",
                "repo_path": "/tmp/repo",
                "task_id": 1,
            }
        )
    assert "enable_replanning" not in mock_run.call_args.kwargs


def test_security_reviewer_no_longer_overrides_enable_replanning_at_its_own_call_site() -> (
    None
):
    with patch(
        "app.agents.security_reviewer.run_agent_graph", return_value=_fake_final_state()
    ) as mock_run:
        from app.agents.security_reviewer import run_security_review

        run_security_review(task_id=1, focus="full audit", repo_path="/tmp/repo")
    assert "enable_replanning" not in mock_run.call_args.kwargs


# ---------------------------------------------------------------------------
# The real resolution logic, tested directly against run_agent_graph (not
# through an agent-level mock, which would bypass it entirely)
# ---------------------------------------------------------------------------


def _run_agent_graph_kwargs_seen(
    monkeypatch: pytest.MonkeyPatch, **call_kwargs: Any
) -> dict[str, Any]:
    """Calls the real run_agent_graph up to (but not including) building the real graph —
    captures what it resolved enable_critique/enable_replanning to before passing them on.
    """
    from app.agents import base_graph

    seen: dict[str, Any] = {}

    def fake_build_agent_graph(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise RuntimeError("stop before building a real graph")

    monkeypatch.setattr(base_graph, "build_agent_graph", fake_build_agent_graph)
    try:
        base_graph.run_agent_graph(
            role_name=call_kwargs.pop("role_name", "some_agent_never_in_the_map"),
            model="claude-haiku-4-5-20251001",
            tools=[],
            tool_handlers={},
            verification_cfg=base_graph.VerificationConfig(),
            initial_message="do a task",
            **call_kwargs,
        )
    except RuntimeError:
        pass
    return seen


def test_an_agent_absent_from_config_now_gets_replanning_and_critique_on_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual T2-B1 change: an agent NOT mentioned in config gets the new fleet
    default (True), not the old off-by-default behavior."""
    settings = get_settings()
    assert "some_agent_never_in_the_map" not in settings.replanning_enabled_agents
    assert "some_agent_never_in_the_map" not in settings.critique_enabled_agents

    seen = _run_agent_graph_kwargs_seen(monkeypatch)
    assert seen["enable_replanning"] is True
    assert seen["enable_critique"] is True


def test_an_agent_explicitly_opted_out_in_config_stays_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config.py's dicts are now an exception list — an agent explicitly set to False there
    stays off even though the fleet default is now True."""
    settings = get_settings()
    monkeypatch.setattr(settings, "replanning_enabled_agents", {"coder": False})
    monkeypatch.setattr(settings, "critique_enabled_agents", {"coder": False})

    seen = _run_agent_graph_kwargs_seen(monkeypatch, role_name="coder")
    assert seen["enable_replanning"] is False
    assert seen["enable_critique"] is False

    # a different, unmentioned agent is unaffected and still gets the fleet default
    seen_other = _run_agent_graph_kwargs_seen(monkeypatch, role_name="some_other_agent")
    assert seen_other["enable_replanning"] is True
    assert seen_other["enable_critique"] is True


def test_an_explicit_argument_always_wins_over_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """temporary_agent.py (and any future caller) can still pass an explicit True/False —
    that must never be overridden by the config-driven fleet default."""
    settings = get_settings()
    monkeypatch.setattr(settings, "replanning_enabled_agents", {})
    monkeypatch.setattr(settings, "critique_enabled_agents", {})

    seen = _run_agent_graph_kwargs_seen(
        monkeypatch, enable_replanning=False, enable_critique=False
    )
    assert seen["enable_replanning"] is False
    assert seen["enable_critique"] is False
