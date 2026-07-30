"""Gap-closure Days 11-14 (Stage 1.1, answers.md) — proves `enable_critique=True`
is now real and wired for exactly the 5 highest-output-risk agents named in
the plan (coder, backend_dev, frontend_dev, qa, reviewer), and — the negative
control that makes this a precise, scoped rollout rather than an accidental
fleet-wide flip — still OFF (the base_graph.py default, False) for an
unrelated agent (devops) that was never named for this rollout.

Before this, `enable_critique`/`enable_replanning` had zero real call sites
anywhere in app/agents/*.py passing True — confirmed by grep — matching the
plan's own baseline claim ("0/72 agents have this enabled") exactly.

Reuses test_day1_agent_flags.py's own established mocked-LLM pattern (no
network, no DB, no API key needed) rather than inventing a new one.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

_MINIMAL_FINAL_STATE: dict[str, Any] = {
    "messages": [{"role": "assistant", "content": [{"type": "text", "text": "done"}]}],
    "submitted": True,
    "result": {"status": "ok", "summary": "ok"},
    "requires_human_approval": False,
    "verification": {},
    "tokens_in": 10,
    "tokens_out": 5,
    "turns": 1,
    "trace_id": "test-trace",
    "status": "done",
}


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.model_planner = "haiku-test"
    s.model_coder = "sonnet-test"
    s.model_router = "haiku-test"
    s.target_repo_path = "/tmp/test-repo"
    s.devops_bash_allowlist = ""
    return s


def _captured_kwargs(mock_run: MagicMock) -> dict[str, Any]:
    assert mock_run.call_count >= 1, "run_agent_graph was never called"
    kwargs: dict[str, Any] = mock_run.call_args_list[0][1]
    return kwargs


def test_coder_enables_critique() -> None:
    with (
        patch(
            "app.agents.coder.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.coder.get_settings", return_value=_mock_settings()),
        patch("app.agents.coder.make_coder_handlers", return_value={}),
    ):
        from app.agents.coder import run_coder

        run_coder(
            task_id=7, plan="Write code", worktree_path="/tmp/wt", repo_path="/tmp/repo"
        )
    kwargs = _captured_kwargs(mock_run)
    assert kwargs.get("enable_critique") is True


def test_backend_dev_enables_critique() -> None:
    with (
        patch(
            "app.agents.backend_dev.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.backend_dev.get_settings", return_value=_mock_settings()),
        patch("app.agents.backend_dev.make_coder_handlers", return_value={}),
        patch("app.agents.backend_dev._run_backend_checks", return_value=None),
    ):
        from app.agents.backend_dev import run_backend_dev

        run_backend_dev(
            task_id=1,
            subtask_id=2,
            plan="Do X",
            worktree_path="/tmp/wt",
            repo_path="/tmp/repo",
        )
    kwargs = _captured_kwargs(mock_run)
    assert kwargs.get("enable_critique") is True


def test_frontend_dev_enables_critique() -> None:
    with (
        patch(
            "app.agents.frontend_dev.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.frontend_dev.get_settings", return_value=_mock_settings()),
        patch("app.agents.frontend_dev.make_coder_handlers", return_value={}),
        patch("app.agents.frontend_dev._run_frontend_checks", return_value=None),
    ):
        from app.agents.frontend_dev import run_frontend_dev

        run_frontend_dev(
            task_id=1,
            subtask_id=3,
            plan="Build UI",
            worktree_path="/tmp/wt",
            repo_path="/tmp/repo",
        )
    kwargs = _captured_kwargs(mock_run)
    assert kwargs.get("enable_critique") is True


def test_qa_enables_critique() -> None:
    with (
        patch(
            "app.agents.qa.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.qa.get_settings", return_value=_mock_settings()),
        patch("app.agents.qa.make_qa_handlers", return_value={}),
    ):
        from app.agents.qa import run_qa

        run_qa(
            task_id=1,
            subtask_id=5,
            files_changed=["a.py"],
            worktree_path="/tmp/wt",
            repo_path="/tmp/repo",
        )
    kwargs = _captured_kwargs(mock_run)
    assert kwargs.get("enable_critique") is True


def test_reviewer_enables_critique() -> None:
    with (
        patch(
            "app.agents.reviewer.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.reviewer.get_settings", return_value=_mock_settings()),
        patch("app.agents.reviewer.make_reviewer_handlers", return_value={}),
    ):
        from app.agents.reviewer import run_reviewer

        run_reviewer(
            task_id=1, subtask_id=4, diff="+ line", plan="ok", repo_path="/tmp/repo"
        )
    kwargs = _captured_kwargs(mock_run)
    assert kwargs.get("enable_critique") is True


def test_devops_still_has_critique_off_negative_control() -> None:
    """devops was never named in the Days 11-14 rollout — this is the
    control proving the flip was precisely scoped to the 5 named agents,
    not an accidental fleet-wide default change."""
    with (
        patch(
            "app.agents.devops.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.devops.get_settings", return_value=_mock_settings()),
        patch("app.agents.devops.make_devops_handlers", return_value={}),
    ):
        from app.agents.devops import run_devops

        run_devops(task_description="Check system health", repo_path="/tmp/repo")
    kwargs = _captured_kwargs(mock_run)
    assert kwargs.get("enable_critique") is not True


def test_coder_does_not_override_max_critique_retries() -> None:
    """Confirms coder relies on build_agent_graph's own default
    (max_critique_retries=1) rather than a wider, unbounded value — matching
    the plan's own stated bound ("bounded, not blind")."""
    with (
        patch(
            "app.agents.coder.run_agent_graph", return_value=_MINIMAL_FINAL_STATE
        ) as mock_run,
        patch("app.agents.coder.get_settings", return_value=_mock_settings()),
        patch("app.agents.coder.make_coder_handlers", return_value={}),
    ):
        from app.agents.coder import run_coder

        run_coder(
            task_id=7, plan="Write code", worktree_path="/tmp/wt", repo_path="/tmp/repo"
        )
    kwargs = _captured_kwargs(mock_run)
    assert "max_critique_retries" not in kwargs
