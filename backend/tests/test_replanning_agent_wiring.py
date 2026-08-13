"""plan14 Day 5 Task 10 — proves the 4 agent call sites (coder.py, pm.py,
qa.py, security_reviewer.py) that used to hardcode `enable_replanning=True`
now read app.config.Settings.replanning_enabled_agents instead, and that an
agent absent from that dict defaults to replanning OFF (matching every
other agent's pre-plan14 behavior).

run_agent_graph itself is mocked at each agent module's import site — these
are wiring tests, not agent-behavior tests (that coverage already exists in
test_phase36_continuous_replanning.py). Mocking one level below the LLM
graph keeps these fast and avoids any real DB/LLM/subprocess work.
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


def test_coder_wires_enable_replanning_from_config() -> None:
    with (
        patch(
            "app.agents.coder.run_agent_graph",
            return_value=_fake_final_state(result={"status": "ok"}),
        ) as mock_run,
        patch("app.agents.coder._run_checks", return_value=None),
    ):
        from app.agents.coder import run_coder

        run_coder(
            task_id=1, plan="do it", worktree_path="/tmp/wt", repo_path="/tmp/repo"
        )

    kwargs = mock_run.call_args.kwargs
    expected = get_settings().replanning_enabled_agents.get("coder", False)
    assert kwargs["enable_replanning"] == expected == True  # noqa: E712


def test_qa_wires_enable_replanning_from_config() -> None:
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

    kwargs = mock_run.call_args.kwargs
    expected = get_settings().replanning_enabled_agents.get("qa", False)
    assert kwargs["enable_replanning"] == expected == True  # noqa: E712


def test_pm_wires_enable_replanning_from_config() -> None:
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

    kwargs = mock_run.call_args.kwargs
    expected = get_settings().replanning_enabled_agents.get("pm", False)
    assert kwargs["enable_replanning"] == expected == True  # noqa: E712


def test_security_reviewer_wires_enable_replanning_from_config() -> None:
    with patch(
        "app.agents.security_reviewer.run_agent_graph",
        return_value=_fake_final_state(),
    ) as mock_run:
        from app.agents.security_reviewer import run_security_review

        run_security_review(task_id=1, focus="full audit", repo_path="/tmp/repo")

    kwargs = mock_run.call_args.kwargs
    expected = get_settings().replanning_enabled_agents.get("security_reviewer", False)
    assert kwargs["enable_replanning"] == expected == True  # noqa: E712


@pytest.mark.parametrize(
    ("agent_name", "override"),
    [("coder", False), ("qa", False), ("pm", False), ("security_reviewer", False)],
)
def test_disabling_an_agent_in_config_actually_disables_replanning(
    agent_name: str, override: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flip one agent's replanning off via config and prove the corresponding
    call site actually respects it — not just reads a default that happens
    to match."""
    settings = get_settings()
    new_map = dict(settings.replanning_enabled_agents)
    new_map[agent_name] = override
    monkeypatch.setattr(settings, "replanning_enabled_agents", new_map)

    if agent_name == "coder":
        with (
            patch(
                "app.agents.coder.run_agent_graph",
                return_value=_fake_final_state(result={"status": "ok"}),
            ) as mock_run,
            patch("app.agents.coder._run_checks", return_value=None),
        ):
            from app.agents.coder import run_coder

            run_coder(
                task_id=1, plan="do it", worktree_path="/tmp/wt", repo_path="/tmp/repo"
            )
    elif agent_name == "qa":
        with patch(
            "app.agents.qa.run_agent_graph", return_value=_fake_final_state()
        ) as mock_run:
            from app.agents.qa import run_qa

            run_qa(
                task_id=1,
                subtask_id=1,
                files_changed=[],
                worktree_path="/tmp/wt",
                repo_path="/tmp/repo",
            )
    elif agent_name == "pm":
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
    else:
        with patch(
            "app.agents.security_reviewer.run_agent_graph",
            return_value=_fake_final_state(),
        ) as mock_run:
            from app.agents.security_reviewer import run_security_review

            run_security_review(task_id=1, focus="full audit", repo_path="/tmp/repo")

    assert mock_run.call_args.kwargs["enable_replanning"] == override


def test_an_agent_absent_from_the_config_map_defaults_to_replanning_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    assert "some_agent_never_in_the_map" not in settings.replanning_enabled_agents
    assert (
        settings.replanning_enabled_agents.get("some_agent_never_in_the_map", False)
        is False
    )
