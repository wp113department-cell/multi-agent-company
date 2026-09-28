"""#66 (2026-09-28, GRIDIRON_PARTIAL "Switch tools mid-run") — the audit's
own IMPLEMENTATION PLAN required defining a concrete, real state signal
before writing any code, and named a specific illustrative example: "a
reviewer-flagged security issue unlocks a specialized security_scan tool."
Built exactly that: manager.py's own security_reviewer gate-block signal
(never model-authored text — _gate_block_reason's own deterministic
message) sets security_scan_unlocked=True for the NEXT dev-agent retry
attempt, which adds the real, existing secrets_scan tool (the same one
security_reviewer itself already has) to that one attempt's tool list.

Two tiers: (1) unit-level — run_backend_dev/run_frontend_dev actually add
the tool+handler when the flag is set, and don't when it isn't (mirrors
test_gap11_14_agent_critique.py's own established mocked-run_agent_graph
pattern); (2) manager-level — the real end-to-end trigger: a genuine
security_reviewer gate block sets the flag for the very next attempt, and
only that one.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.agent_result import AgentResult
from app.agents.qa import QAResult
from app.agents.reviewer import ReviewResult

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
    s.delegation_default_budget_usd = 5.0
    return s


# ---------------------------------------------------------------------------
# Unit-level: does the tool/handler actually get added when the flag is set?
# ---------------------------------------------------------------------------


def test_backend_dev_default_does_not_include_secrets_scan() -> None:
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
            task_id=1, subtask_id=2, plan="Do X", worktree_path="/tmp/wt",
            repo_path="/tmp/repo",
        )
    kwargs = mock_run.call_args_list[0][1]
    tool_names = {t["name"] for t in kwargs["tools"]}
    assert "secrets_scan" not in tool_names
    assert "secrets_scan" not in kwargs["tool_handlers"]


def test_backend_dev_unlocked_includes_secrets_scan_tool_and_handler() -> None:
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
            task_id=1, subtask_id=2, plan="Do X", worktree_path="/tmp/wt",
            repo_path="/tmp/repo", security_scan_unlocked=True,
        )
    kwargs = mock_run.call_args_list[0][1]
    tool_names = {t["name"] for t in kwargs["tools"]}
    assert "secrets_scan" in tool_names
    assert "secrets_scan" in kwargs["tool_handlers"]
    assert "[SECURITY TOOL UNLOCKED]" in kwargs["initial_message"]


def test_frontend_dev_default_does_not_include_secrets_scan() -> None:
    with (
        patch(
            "app.agents.frontend_dev.run_agent_graph",
            return_value=_MINIMAL_FINAL_STATE,
        ) as mock_run,
        patch("app.agents.frontend_dev.get_settings", return_value=_mock_settings()),
        patch("app.agents.frontend_dev.make_coder_handlers", return_value={}),
        patch("app.agents.frontend_dev._run_frontend_checks", return_value=None),
    ):
        from app.agents.frontend_dev import run_frontend_dev

        run_frontend_dev(
            task_id=1, subtask_id=2, plan="Do X", worktree_path="/tmp/wt",
            repo_path="/tmp/repo",
        )
    kwargs = mock_run.call_args_list[0][1]
    tool_names = {t["name"] for t in kwargs["tools"]}
    assert "secrets_scan" not in tool_names


def test_frontend_dev_unlocked_includes_secrets_scan_tool_and_handler() -> None:
    with (
        patch(
            "app.agents.frontend_dev.run_agent_graph",
            return_value=_MINIMAL_FINAL_STATE,
        ) as mock_run,
        patch("app.agents.frontend_dev.get_settings", return_value=_mock_settings()),
        patch("app.agents.frontend_dev.make_coder_handlers", return_value={}),
        patch("app.agents.frontend_dev._run_frontend_checks", return_value=None),
    ):
        from app.agents.frontend_dev import run_frontend_dev

        run_frontend_dev(
            task_id=1, subtask_id=2, plan="Do X", worktree_path="/tmp/wt",
            repo_path="/tmp/repo", security_scan_unlocked=True,
        )
    kwargs = mock_run.call_args_list[0][1]
    tool_names = {t["name"] for t in kwargs["tools"]}
    assert "secrets_scan" in tool_names
    assert "secrets_scan" in kwargs["tool_handlers"]


# ---------------------------------------------------------------------------
# Manager-level: the real end-to-end trigger
# ---------------------------------------------------------------------------


def _patch_common():
    from contextlib import ExitStack

    from app.config import get_settings

    stack = ExitStack()
    mocks = {}
    mocks["backend_dev"] = stack.enter_context(
        patch("app.agents.backend_dev.run_backend_dev")
    )
    mocks["qa"] = stack.enter_context(patch("app.agents.qa.run_qa"))
    mocks["reviewer"] = stack.enter_context(patch("app.agents.reviewer.run_reviewer"))
    stack.enter_context(
        patch("app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x")
    )
    stack.enter_context(
        patch(
            "app.services.git_service.git_add",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        )
    )
    stack.enter_context(
        patch(
            "app.services.git_service.git_commit",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        )
    )
    stack.enter_context(patch("app.event_bus.bus.publish_event"))
    # tests/conftest.py sets ENABLE_SECURITY_ARCHITECTURE_GATES=false as the
    # test-env default (so the large pre-existing test suite that never
    # mocks security_reviewer/architecture_reviewer/dependency_security_agent
    # doesn't make real Anthropic calls) — these #66 tests exist specifically
    # to exercise gate-triggered behavior, so they opt back in explicitly,
    # same as test_batch16_quality_gates.py already does.
    stack.enter_context(
        patch.object(get_settings(), "enable_security_architecture_gates", True)
    )
    return stack, mocks


def _sec_result(severity: str) -> AgentResult:
    return AgentResult(
        summary="sec review",
        findings=[],
        files_touched=[],
        verified=True,
        status="completed",
        raw={"severity": severity},
    )


def test_security_gate_block_unlocks_the_tool_on_the_very_next_attempt(
    tmp_path,
) -> None:
    from app.agents.manager import run_manager

    stack, mocks = _patch_common()
    with stack, patch(
        "app.agents.security_reviewer.run_security_review",
        return_value=_sec_result("critical"),
    ), patch(
        "app.agents.architecture_reviewer.run_arch_review",
        return_value=AgentResult(summary="ok", status="completed"),
    ), patch(
        "app.agents.dependency_security_agent.run_dependency_security_agent",
        return_value=AgentResult(summary="ok", status="completed"),
    ):
        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].return_value = QAResult(
            status="passed", tests_run=1, tests_passed=1, tests_failed=0,
            typecheck_clean=True, lint_clean=True, summary="ok",
        )
        mocks["reviewer"].return_value = ReviewResult(
            verdict="approved", summary="looks good"
        )

        asyncio.run(
            run_manager(
                task_id=999_501,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
            )
        )

    assert mocks["backend_dev"].call_count == 2
    first_call_kwargs = mocks["backend_dev"].call_args_list[0].kwargs
    second_call_kwargs = mocks["backend_dev"].call_args_list[1].kwargs
    assert first_call_kwargs["security_scan_unlocked"] is False
    assert second_call_kwargs["security_scan_unlocked"] is True


def test_non_security_gate_block_never_unlocks_the_tool(tmp_path) -> None:
    from app.agents.manager import run_manager

    stack, mocks = _patch_common()
    with stack, patch(
        "app.agents.security_reviewer.run_security_review",
        return_value=AgentResult(summary="ok", status="completed"),
    ), patch(
        "app.agents.architecture_reviewer.run_arch_review",
        return_value=AgentResult(
            summary="arch",
            status="completed",
            findings=[{"severity": "critical", "risk": "bad coupling"}],
        ),
    ), patch(
        "app.agents.dependency_security_agent.run_dependency_security_agent",
        return_value=AgentResult(summary="ok", status="completed"),
    ):
        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].return_value = QAResult(
            status="passed", tests_run=1, tests_passed=1, tests_failed=0,
            typecheck_clean=True, lint_clean=True, summary="ok",
        )
        mocks["reviewer"].return_value = ReviewResult(
            verdict="approved", summary="looks good"
        )

        asyncio.run(
            run_manager(
                task_id=999_502,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
            )
        )

    for call in mocks["backend_dev"].call_args_list:
        assert call.kwargs["security_scan_unlocked"] is False


def test_unlock_does_not_persist_past_an_unrelated_later_attempt(tmp_path) -> None:
    """A QA failure (unrelated) on attempt 0, then a real security gate
    block on attempt 1, proves the unlock tracks the ATTEMPT that actually
    triggered it (set on attempt 2, not left over/absent incorrectly)."""
    from app.agents.manager import run_manager
    from app.config import get_settings

    stack, mocks = _patch_common()
    call_count = {"n": 0}

    def _security_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _sec_result("critical")
        return AgentResult(summary="ok", status="completed")

    with stack, patch.object(
        get_settings(), "manager_max_subtask_retries", 3
    ), patch(
        "app.agents.security_reviewer.run_security_review",
        side_effect=_security_side_effect,
    ), patch(
        "app.agents.architecture_reviewer.run_arch_review",
        return_value=AgentResult(summary="ok", status="completed"),
    ), patch(
        "app.agents.dependency_security_agent.run_dependency_security_agent",
        return_value=AgentResult(summary="ok", status="completed"),
    ):
        qa_call_count = {"n": 0}

        def _qa_side_effect(*args, **kwargs):
            qa_call_count["n"] += 1
            if qa_call_count["n"] == 1:
                return QAResult(
                    status="failed", tests_run=1, tests_passed=0, tests_failed=1,
                    typecheck_clean=True, lint_clean=True, summary="fail",
                    errors=["boom"],
                )
            return QAResult(
                status="passed", tests_run=1, tests_passed=1, tests_failed=0,
                typecheck_clean=True, lint_clean=True, summary="ok",
            )

        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].side_effect = _qa_side_effect
        mocks["reviewer"].return_value = ReviewResult(
            verdict="approved", summary="looks good"
        )

        asyncio.run(
            run_manager(
                task_id=999_503,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
            )
        )

    # calls[0] (attempt 0): initial state, no unlock. Attempt 0 fails QA
    # (unrelated to security) before ever reaching the gate, so calls[1]
    # (attempt 1) correctly still carries no unlock. Attempt 1 then trips
    # the REAL security gate, so calls[2] (attempt 2) correctly carries the
    # unlock — proving it's set from the attempt that actually triggered
    # it, not left over from something earlier or applied preemptively.
    calls = mocks["backend_dev"].call_args_list
    assert len(calls) == 3
    assert calls[0].kwargs["security_scan_unlocked"] is False
    assert calls[1].kwargs["security_scan_unlocked"] is False
    assert calls[2].kwargs["security_scan_unlocked"] is True
