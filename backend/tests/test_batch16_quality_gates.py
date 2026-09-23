"""AUDIT_Q_BATCH16 §90 gap-closure (2026-08-11) — security_reviewer and
architecture_reviewer wired as real, opt-in advisory gates into manager.py's
Dev->QA->Review pipeline (previously zero callers from any pipeline deciding
whether a normal task is "done").

AUDIT_Q_BATCH18 §24 High-priority #7 gap-closure (2026-08-12) — extended with
dependency_security_agent as a third concurrent gate, and real severity-based
blocking (security_architecture_gates_block_severities) so these gates can
actually flip subtask_status to "blocked", not just log findings nobody acts
on.
"""

from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

from app.agents.agent_result import AgentResult


def _result(
    status: str,
    findings: list | None = None,
    raw: dict | None = None,
    verified: bool = True,
) -> AgentResult:
    return AgentResult(
        summary=f"{status} summary",
        findings=findings or [],
        files_touched=[],
        verified=verified,
        requires_human_approval=False,
        tokens_in=10,
        tokens_out=20,
        status=status,
        raw=raw or {},
    )


def _patch_all_three(sec=None, arch=None, dep=None):
    """Returns a contextmanager patching all 3 gate entry points at once,
    each defaulting to a clean, non-blocking completed result."""
    from contextlib import ExitStack

    stack = ExitStack()
    mock_sec = stack.enter_context(
        patch(
            "app.agents.security_reviewer.run_security_review",
            return_value=sec if sec is not None else _result("completed"),
        )
    )
    mock_arch = stack.enter_context(
        patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=arch if arch is not None else _result("completed"),
        )
    )
    mock_dep = stack.enter_context(
        patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent",
            return_value=dep if dep is not None else _result("completed"),
        )
    )
    return stack, mock_sec, mock_arch, mock_dep


class TestRunAdvisoryQualityGates:
    def test_runs_all_three_gates_and_sums_tokens(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, mock_sec, mock_arch, mock_dep = _patch_all_three(
            sec=_result("completed", [{"finding": "x"}])
        )
        with stack:
            tokens_in, tokens_out, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        mock_sec.assert_called_once()
        mock_arch.assert_called_once()
        mock_dep.assert_called_once()
        assert tokens_in == 30  # 10 * 3
        assert tokens_out == 60  # 20 * 3
        assert block_reason is None

    def test_one_gate_failing_does_not_lose_the_others(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        with patch(
            "app.agents.security_reviewer.run_security_review",
            side_effect=RuntimeError("boom"),
        ), patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=_result("completed"),
        ), patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent",
            return_value=_result("completed"),
        ):
            tokens_in, tokens_out, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert tokens_in == 20  # arch + dep
        assert tokens_out == 40
        assert block_reason is None

    def test_critical_security_finding_blocks(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three(
            sec=_result("completed", raw={"severity": "critical"})
        )
        with stack:
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert block_reason is not None
        assert "security_reviewer" in block_reason

    def test_medium_security_finding_does_not_block(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three(
            sec=_result("completed", raw={"severity": "medium"})
        )
        with stack:
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert block_reason is None

    def test_high_architecture_risk_blocks(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three(
            arch=_result(
                "completed",
                findings=[{"severity": "high", "description": "tight coupling"}],
            )
        )
        with stack:
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert block_reason is not None
        assert "architecture_reviewer" in block_reason

    def test_verified_dependency_vulnerabilities_block(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three(
            dep=_result(
                "completed",
                raw={"vulnerable_package_count": 2, "total_vuln_count": 3},
                verified=True,
            )
        )
        with stack:
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert block_reason is not None
        assert "dependency_security_agent" in block_reason

    def test_unverified_dependency_vulnerabilities_do_not_block(self) -> None:
        """An unverified (audited=False) claim is never load-bearing —
        same invariant AgentResult.verified enforces everywhere else."""
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three(
            dep=_result(
                "completed",
                raw={"vulnerable_package_count": 2},
                verified=False,
            )
        )
        with stack:
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert block_reason is None

    def test_empty_block_severities_restores_pure_advisory_behavior(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates
        from app.config import get_settings

        stack, *_ = _patch_all_three(
            sec=_result("completed", raw={"severity": "critical"})
        )
        with stack, patch.object(
            get_settings(), "security_architecture_gates_block_severities", []
        ):
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )

        assert block_reason is None


class TestPerformanceRegressionGate:
    """T2-B5 (2026-09-22, GRIDIRON_PARTIAL #456 "Performance checks
    (broad, not just role-prompt deploys)") — the fourth gate,
    regression_detector.check_agent()'s existing regression math (until
    now only ever consulted at role-PROMPT deploy time), extended to
    subtask-level dev-agent checks."""

    def test_no_agent_name_skips_the_regression_check_entirely(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three()
        with stack, patch(
            "app.fleet.regression_detector.get_regression_detector"
        ) as mock_get_rd:
            asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None
                )
            )
        mock_get_rd.assert_not_called()

    def test_a_real_measured_regression_blocks(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates
        from app.fleet.regression_detector import RegressionGate

        stack, *_ = _patch_all_three()
        fake_gate = RegressionGate(
            agent_name="backend_dev",
            blocked=True,
            reason="benchmark_score dropped 0.400 (baseline=0.900)",
            report=Mock(),
        )
        with stack, patch(
            "app.fleet.regression_detector.get_regression_detector"
        ) as mock_get_rd:
            mock_get_rd.return_value.check_agent.return_value = fake_gate
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1,
                    subtask_id=1,
                    repo="/tmp/x",
                    epic_id=None,
                    db=None,
                    agent_name="backend_dev",
                )
            )
        mock_get_rd.return_value.check_agent.assert_called_once_with("backend_dev")
        assert block_reason is not None
        assert "0.400" in block_reason

    def test_no_regression_does_not_block(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates
        from app.fleet.regression_detector import RegressionGate

        stack, *_ = _patch_all_three()
        fake_gate = RegressionGate(
            agent_name="backend_dev", blocked=False, reason="no regression detected", report=Mock()
        )
        with stack, patch(
            "app.fleet.regression_detector.get_regression_detector"
        ) as mock_get_rd:
            mock_get_rd.return_value.check_agent.return_value = fake_gate
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1,
                    subtask_id=1,
                    repo="/tmp/x",
                    epic_id=None,
                    db=None,
                    agent_name="backend_dev",
                )
            )
        assert block_reason is None

    def test_regression_check_failure_is_non_fatal(self) -> None:
        from app.agents.manager import _run_advisory_quality_gates

        stack, *_ = _patch_all_three()
        with stack, patch(
            "app.fleet.regression_detector.get_regression_detector",
            side_effect=RuntimeError("boom"),
        ):
            _, _, block_reason = asyncio.run(
                _run_advisory_quality_gates(
                    task_id=1,
                    subtask_id=1,
                    repo="/tmp/x",
                    epic_id=None,
                    db=None,
                    agent_name="backend_dev",
                )
            )
        assert block_reason is None


class TestRunManagerAdvisoryGateWiring:
    def test_can_still_be_disabled_via_config(self) -> None:
        """T2-B5 (2026-09-22, GRIDIRON_PARTIAL #453/#455) flipped
        enable_security_architecture_gates's DEFAULT to True (the safety
        net these gates needed — a real self-correction retry through the
        dev agent before blocking — now exists; see
        TestSecurityArchitectureGateRetry below). This test used to prove
        the (then-default) disabled behavior; it now proves the opt-OUT
        path still genuinely disables the gates, an operator who explicitly
        doesn't want them still sees zero calls."""
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
            "app.agents.security_reviewer.run_security_review"
        ) as mock_sec, patch(
            "app.agents.architecture_reviewer.run_arch_review"
        ) as mock_arch, patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent"
        ) as mock_dep, patch.object(
            get_settings(), "enable_security_architecture_gates", False
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
        mock_dep.assert_not_called()

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
        ) as mock_arch, patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent",
            return_value=_result("completed"),
        ) as mock_dep, patch.object(
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

        # No blocking-severity findings from any gate: a completed subtask
        # stays completed.
        assert result["status"] == "completed"
        mock_sec.assert_called_once()
        mock_arch.assert_called_once()
        mock_dep.assert_called_once()
        # 0 (dev) + 0 (qa) + 0 (reviewer) + 10+20 (sec) + 10+20 (arch) + 10+20 (dep)
        assert result["tokens_in"] == 30
        assert result["tokens_out"] == 60

    def test_critical_finding_blocks_the_subtask(self) -> None:
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
            return_value=_result(
                "completed",
                findings=["hardcoded credential in config.py"],
                raw={"severity": "critical"},
            ),
        ), patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=_result("completed"),
        ), patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent",
            return_value=_result("completed"),
        ), patch.object(
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
                    task_id=999_103,
                    subtasks=[
                        {"id": 1, "type": "backend", "title": "t", "description": "d"}
                    ],
                    worktree_path="/tmp/does-not-need-to-exist",
                    plan="plan",
                    repo_path="/home/pc-117/Documents/CRR2906",
                )
            )

        assert result["status"] == "blocked"

    def test_a_fixable_gate_finding_gets_a_real_retry_and_then_succeeds(self) -> None:
        """T2-B5 (2026-09-22, GRIDIRON_PARTIAL #453/#455) — the actual new
        capability: before this, ANY blocking gate finding halted the
        subtask immediately with zero self-correction attempt. Now a gate
        finding is fed back into the SAME retry loop reviewer findings
        already use — the dev agent gets a real second attempt, and if the
        underlying issue is genuinely fixed, the subtask completes instead
        of blocking on a since-resolved finding."""
        from app.agents.manager import run_manager
        from app.agents.qa import QAResult
        from app.agents.reviewer import ReviewResult
        from app.config import get_settings

        vulnerable = _result(
            "completed",
            raw={"vulnerable_package_count": 1},
            verified=True,
        )
        clean = _result("completed", raw={"vulnerable_package_count": 0}, verified=True)

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
        ), patch(
            "app.agents.architecture_reviewer.run_arch_review",
            return_value=_result("completed"),
        ), patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent",
            side_effect=[vulnerable, clean],
        ) as mock_dep, patch.object(
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
                    task_id=999_104,
                    subtasks=[
                        {"id": 1, "type": "backend", "title": "t", "description": "d"}
                    ],
                    worktree_path="/tmp/does-not-need-to-exist",
                    plan="plan",
                    repo_path="/home/pc-117/Documents/CRR2906",
                )
            )

        assert result["status"] == "completed"
        assert mock_dep.call_count == 2  # one per attempt — real re-check, not a fluke
        assert mock_backend_dev.call_count == 2  # the dev agent got a real second attempt
