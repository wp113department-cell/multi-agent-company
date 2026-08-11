"""AUDIT_Q_BATCH16 §90 gap-closure (2026-08-11) — security_reviewer and
architecture_reviewer wired as real, opt-in, non-blocking advisory gates
into manager.py's Dev->QA->Review pipeline (previously zero callers from
any pipeline deciding whether a normal task is "done").
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.agents.agent_result import AgentResult


def _result(status: str, findings: list[dict] | None = None) -> AgentResult:
    return AgentResult(
        summary=f"{status} summary",
        findings=findings or [],
        files_touched=[],
        verified=True,
        requires_human_approval=False,
        tokens_in=10,
        tokens_out=20,
        status=status,
        raw={},
    )


class TestRunAdvisoryQualityGates:
    def test_runs_both_gates_and_sums_tokens(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        with patch(
            "app.agents.security_reviewer.run_security_review",
            return_value=_result("completed", [{"finding": "x"}]),
        ) as mock_sec, patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=_result("completed"),
        ) as mock_arch:
            tokens_in, tokens_out = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        mock_sec.assert_called_once()
        mock_arch.assert_called_once()
        assert tokens_in == 20  # 10 + 10
        assert tokens_out == 40  # 20 + 20

    def test_one_gate_failing_does_not_lose_the_other(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        with patch(
            "app.agents.security_reviewer.run_security_review",
            side_effect=RuntimeError("boom"),
        ), patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=_result("completed"),
        ):
            tokens_in, tokens_out = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert tokens_in == 10
        assert tokens_out == 20


class TestRunManagerAdvisoryGateWiring:
    def test_disabled_by_default_gates_never_called(self) -> None:
        from app.agents.manager import run_manager
        from app.agents.qa import QAResult
        from app.agents.reviewer import ReviewResult

        with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
            "app.agents.qa.run_qa"
        ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
            "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
        ), patch(
            "app.services.git_service.git_add",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        ), patch(
            "app.services.git_service.git_commit",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        ), patch(
            "app.agents.security_reviewer.run_security_review"
        ) as mock_sec, patch(
            "app.agents.architecture_reviewer.run_arch_review"
        ) as mock_arch:
            mock_backend_dev.return_value = (["app/api/hello.py"], None, 0, 0)
            mock_qa.return_value = QAResult(
                status="passed",
                tests_run=1,
                tests_passed=1,
                tests_failed=0,
                typecheck_clean=True,
                lint_clean=True,
                summary="ok",
            )
            mock_reviewer.return_value = ReviewResult(
                verdict="approved", summary="looks good"
            )

            result = asyncio.run(
                run_manager(
                    task_id=999_101,
                    subtasks=[
                        {"id": 1, "type": "backend", "title": "t", "description": "d"}
                    ],
                    worktree_path="/tmp/does-not-need-to-exist",
                    plan="plan",
                    repo_path="/home/pc-117/Documents/CRR2906",
                )
            )

        assert result["status"] == "completed"
        mock_sec.assert_not_called()
        mock_arch.assert_not_called()

    def test_enabled_via_settings_gates_run_after_completion(self) -> None:
        from app.agents.manager import run_manager
        from app.agents.qa import QAResult
        from app.agents.reviewer import ReviewResult
        from app.config import get_settings

        with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
            "app.agents.qa.run_qa"
        ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
            "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
        ), patch(
            "app.services.git_service.git_add",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        ), patch(
            "app.services.git_service.git_commit",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        ), patch(
            "app.agents.security_reviewer.run_security_review",
            return_value=_result("completed"),
        ) as mock_sec, patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=_result("completed"),
        ) as mock_arch, patch.object(
            get_settings(), "enable_security_architecture_gates", True
        ):
            mock_backend_dev.return_value = (["app/api/hello.py"], None, 0, 0)
            mock_qa.return_value = QAResult(
                status="passed",
                tests_run=1,
                tests_passed=1,
                tests_failed=0,
                typecheck_clean=True,
                lint_clean=True,
                summary="ok",
            )
            mock_reviewer.return_value = ReviewResult(
                verdict="approved", summary="looks good"
            )

            result = asyncio.run(
                run_manager(
                    task_id=999_102,
                    subtasks=[
                        {"id": 1, "type": "backend", "title": "t", "description": "d"}
                    ],
                    worktree_path="/tmp/does-not-need-to-exist",
                    plan="plan",
                    repo_path="/home/pc-117/Documents/CRR2906",
                )
            )

        # Advisory-only: a completed subtask stays completed regardless of
        # what the gates report.
        assert result["status"] == "completed"
        mock_sec.assert_called_once()
        mock_arch.assert_called_once()
        # 0 (dev) + 0 (qa) + 0 (reviewer) + 10+20 (sec) + 10+20 (arch)
        assert result["tokens_in"] == 20
        assert result["tokens_out"] == 40
