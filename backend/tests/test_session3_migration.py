"""Session 3 migration tests — reviewer, qa, devops (no real LLM calls).

Tests prove:
- All 3 agents import without errors
- AGENT_CONTRACT in standard format (input_types/output_types as lists)
- reviewer: risk_level=low, no side effects, returns ReviewResult dataclass
- qa: risk_level=low, side_effects=[execute_bash], returns QAResult dataclass
- devops: risk_level=low, side_effects=[execute_bash], returns HealthReport dataclass
- All 3 use run_agent_graph (not run_agent)
- External interfaces unchanged
- All 3 appear in capability_registry + agent_registry on import
- qa: AGENT_CONTRACT updated from old dict format to standard list format
- devops: _last_assistant_text extracts text from final state messages correctly
- Fleet manager selects each agent by its specific capability
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch


import app.agents.reviewer as rv_mod
import app.agents.qa as qa_mod
import app.agents.devops as dv_mod

from app.agents.reviewer import (
    AGENT_CONTRACT as RV_CONTRACT,
    run_reviewer,
    ReviewResult,
    ReviewFinding,
)
from app.agents.qa import AGENT_CONTRACT as QA_CONTRACT, run_qa, QAResult
from app.agents.devops import (
    AGENT_CONTRACT as DV_CONTRACT,
    run_devops,
    HealthReport,
    _last_assistant_text,
)

REQUIRED_CONTRACT_KEYS = {
    "name",
    "description",
    "allowed_tools",
    "input_types",
    "output_types",
    "side_effects",
    "permissions",
    "risk_level",
}

_SUBMIT_PRIVATE = {"submit_review", "submit_qa_result", "submit_health_report"}


# ---------------------------------------------------------------------------
# AGENT_CONTRACT structure
# ---------------------------------------------------------------------------


class TestReviewerContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(RV_CONTRACT.keys())

    def test_name(self) -> None:
        assert RV_CONTRACT["name"] == "reviewer"

    def test_risk_level_low(self) -> None:
        assert RV_CONTRACT["risk_level"] == "low"

    def test_no_side_effects(self) -> None:
        assert RV_CONTRACT["side_effects"] == []

    def test_no_write_tools(self) -> None:
        write_tools = {"write_file", "edit_file", "delete_file", "bash"}
        used = write_tools & set(RV_CONTRACT["allowed_tools"])
        assert used == set(), f"reviewer has disallowed tools: {used}"

    def test_submit_review_in_allowed_tools(self) -> None:
        assert "submit_review" in RV_CONTRACT["allowed_tools"]

    def test_input_types_are_list(self) -> None:
        assert isinstance(RV_CONTRACT["input_types"], list)

    def test_output_types_are_list(self) -> None:
        assert isinstance(RV_CONTRACT["output_types"], list)

    def test_depends_on_coder_agents(self) -> None:
        deps = RV_CONTRACT["dependencies"]
        assert any(d in deps for d in ["coder", "backend_dev", "frontend_dev"])


class TestQaContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(QA_CONTRACT.keys())

    def test_name(self) -> None:
        assert QA_CONTRACT["name"] == "qa"

    def test_risk_level_low(self) -> None:
        assert QA_CONTRACT["risk_level"] == "low"

    def test_side_effects_has_execute_bash(self) -> None:
        assert "execute_bash" in QA_CONTRACT["side_effects"]

    def test_no_write_tools(self) -> None:
        write_tools = {"write_file", "edit_file", "delete_file"}
        used = write_tools & set(QA_CONTRACT["allowed_tools"])
        assert used == set(), f"qa has write tools: {used}"

    def test_bash_in_allowed_tools(self) -> None:
        assert "bash" in QA_CONTRACT["allowed_tools"]

    def test_input_types_are_list_not_dict(self) -> None:
        # Old format used dict {"task_id": "int", ...}; new format is list
        assert isinstance(QA_CONTRACT["input_types"], list)
        assert "task_id" in QA_CONTRACT["input_types"]

    def test_output_types_are_list_not_dict(self) -> None:
        assert isinstance(QA_CONTRACT["output_types"], list)

    def test_execute_tests_permission(self) -> None:
        assert "execute_tests" in QA_CONTRACT["permissions"]


class TestDevopsContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(DV_CONTRACT.keys())

    def test_name(self) -> None:
        assert DV_CONTRACT["name"] == "devops"

    def test_risk_level_low(self) -> None:
        assert DV_CONTRACT["risk_level"] == "low"

    def test_side_effects_has_execute_bash(self) -> None:
        assert "execute_bash" in DV_CONTRACT["side_effects"]

    def test_no_write_tools(self) -> None:
        write_tools = {"write_file", "edit_file", "delete_file"}
        used = write_tools & set(DV_CONTRACT["allowed_tools"])
        assert used == set(), f"devops has write tools: {used}"

    def test_submit_health_report_in_allowed_tools(self) -> None:
        assert "submit_health_report" in DV_CONTRACT["allowed_tools"]

    def test_input_types_are_list(self) -> None:
        assert isinstance(DV_CONTRACT["input_types"], list)


# ---------------------------------------------------------------------------
# Migration complete — uses run_agent_graph
# ---------------------------------------------------------------------------


class TestMigrationComplete:
    def _imports_run_agent(self, mod: Any) -> bool:
        import ast
        import textwrap

        src = textwrap.dedent(inspect.getsource(mod))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "run_agent" and alias.asname != "run_agent_graph":
                        return True
        return False

    def test_reviewer_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(rv_mod)

    def test_qa_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(qa_mod)

    def test_devops_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(dv_mod)

    def test_reviewer_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(rv_mod)

    def test_qa_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(qa_mod)

    def test_devops_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(dv_mod)


# ---------------------------------------------------------------------------
# External interface unchanged
# ---------------------------------------------------------------------------


class TestExternalInterfaceUnchanged:
    def test_run_reviewer_signature(self) -> None:
        sig = inspect.signature(run_reviewer)
        params = list(sig.parameters.keys())
        assert params[:4] == ["task_id", "subtask_id", "diff", "plan"]

    def test_run_reviewer_compat_params(self) -> None:
        sig = inspect.signature(run_reviewer)
        assert "on_heartbeat" in sig.parameters
        assert "on_tool_call" in sig.parameters

    def test_run_qa_signature(self) -> None:
        sig = inspect.signature(run_qa)
        params = list(sig.parameters.keys())
        assert params[:4] == ["task_id", "subtask_id", "files_changed", "worktree_path"]

    def test_run_qa_compat_params(self) -> None:
        sig = inspect.signature(run_qa)
        assert "on_heartbeat" in sig.parameters
        assert "on_tool_call" in sig.parameters

    def test_run_devops_signature(self) -> None:
        sig = inspect.signature(run_devops)
        assert "repo_path" in sig.parameters
        assert "task_description" in sig.parameters

    def test_review_result_dataclass_preserved(self) -> None:
        r = ReviewResult(verdict="approved", summary="LGTM")
        assert r.verdict == "approved"
        assert r.blocking_count == 0
        assert not r.has_blocking

    def test_review_finding_dataclass_preserved(self) -> None:
        f = ReviewFinding(
            severity="blocking",
            file="src/auth.py",
            line=42,
            finding="SQL injection",
            recommendation="Use parameterized queries",
        )
        assert f.severity == "blocking"

    def test_qa_result_dataclass_preserved(self) -> None:
        r = QAResult(
            status="passed",
            tests_run=10,
            tests_passed=10,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
        )
        assert r.status == "passed"

    def test_health_report_dataclass_preserved(self) -> None:
        r = HealthReport(status="healthy", checks=[], summary="All good")
        assert r.status == "healthy"


# ---------------------------------------------------------------------------
# devops _last_assistant_text helper
# ---------------------------------------------------------------------------


class TestLastAssistantText:
    def test_extracts_string_content(self) -> None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "System is healthy."},
        ]
        assert _last_assistant_text(messages) == "System is healthy."

    def test_extracts_from_content_list(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "All checks passed."},
                    {"type": "tool_use", "id": "123"},
                ],
            },
        ]
        assert _last_assistant_text(messages) == "All checks passed."

    def test_returns_last_assistant_if_multiple(self) -> None:
        messages = [
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Follow up"},
            {"role": "assistant", "content": "Final response"},
        ]
        assert _last_assistant_text(messages) == "Final response"

    def test_returns_empty_string_if_no_assistant(self) -> None:
        messages = [{"role": "user", "content": "Hello"}]
        assert _last_assistant_text(messages) == ""

    def test_returns_empty_string_on_empty_messages(self) -> None:
        assert _last_assistant_text([]) == ""


# ---------------------------------------------------------------------------
# Capability registry auto-registration
# ---------------------------------------------------------------------------


class TestCapabilityRegistryRegistration:
    def test_reviewer_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        assert get_capability_registry().get("reviewer") is not None

    def test_qa_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        assert get_capability_registry().get("qa") is not None

    def test_devops_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        assert get_capability_registry().get("devops") is not None

    def test_reviewer_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get("reviewer")
        assert cap is not None
        assert "code_review" in cap.capabilities

    def test_qa_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get("qa")
        assert cap is not None
        assert "testing" in cap.capabilities

    def test_devops_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get("devops")
        assert cap is not None
        assert "health_check" in cap.capabilities

    def test_all_three_are_low_risk(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        r = get_capability_registry()
        for name in ["reviewer", "qa", "devops"]:
            cap = r.get(name)
            assert cap is not None
            assert cap.risk_level == "low", f"{name} should be low risk"


# ---------------------------------------------------------------------------
# Agent registry auto-registration
# ---------------------------------------------------------------------------


class TestAgentRegistryRegistration:
    def test_reviewer_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry

        assert get_agent_registry().get("reviewer") is not None

    def test_qa_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry

        assert get_agent_registry().get("qa") is not None

    def test_devops_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry

        assert get_agent_registry().get("devops") is not None


# ---------------------------------------------------------------------------
# Fleet manager selection
# ---------------------------------------------------------------------------


class TestFleetManagerSelection:
    def test_selects_reviewer(self) -> None:
        from app.fleet.fleet_manager import FleetManager

        plan = FleetManager().select("code_review")
        assert plan is not None
        assert plan.agent_name == "reviewer"

    def test_selects_reviewer_by_diff_analysis(self) -> None:
        from app.fleet.fleet_manager import FleetManager

        plan = FleetManager().select("diff_analysis")
        assert plan is not None
        assert plan.agent_name == "reviewer"

    def test_selects_qa_by_testing(self) -> None:
        from app.fleet.fleet_manager import FleetManager

        plan = FleetManager().select("testing")
        assert plan is not None
        assert plan.agent_name == "qa"

    def test_selects_qa_by_lint_check(self) -> None:
        from app.fleet.fleet_manager import FleetManager

        plan = FleetManager().select("lint_check")
        assert plan is not None
        assert plan.agent_name == "qa"

    def test_selects_devops_by_health_check(self) -> None:
        from app.fleet.fleet_manager import FleetManager

        plan = FleetManager().select("health_check")
        assert plan is not None
        assert plan.agent_name == "devops"

    def test_selects_devops_by_system_monitoring(self) -> None:
        from app.fleet.fleet_manager import FleetManager

        plan = FleetManager().select("system_monitoring")
        assert plan is not None
        assert plan.agent_name == "devops"


# ---------------------------------------------------------------------------
# Tool manifest compliance
# ---------------------------------------------------------------------------


class TestToolManifestCompliance:
    def _shared_tools(self, contract: dict[str, Any]) -> list[str]:
        return [t for t in contract["allowed_tools"] if t not in _SUBMIT_PRIVATE]

    def test_reviewer_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for tool in self._shared_tools(RV_CONTRACT):
            assert (
                tool in TOOL_MANIFEST
            ), f"reviewer uses {tool!r} — not in TOOL_MANIFEST"

    def test_qa_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for tool in self._shared_tools(QA_CONTRACT):
            assert tool in TOOL_MANIFEST, f"qa uses {tool!r} — not in TOOL_MANIFEST"

    def test_devops_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for tool in self._shared_tools(DV_CONTRACT):
            assert tool in TOOL_MANIFEST, f"devops uses {tool!r} — not in TOOL_MANIFEST"


# ---------------------------------------------------------------------------
# run_reviewer behavior (mocked run_agent_graph)
# ---------------------------------------------------------------------------

_BASE_STATE: dict[str, Any] = {
    "messages": [],
    "verification": {},
    "result": {},
    "turns": 2,
    "submitted": True,
    "requires_human_approval": False,
    "tokens_in": 800,
    "tokens_out": 150,
}


class TestRunReviewerBehavior:
    @patch("app.agents.reviewer.run_agent_graph")
    @patch("app.agents.reviewer.make_reviewer_handlers")
    def test_returns_review_result_on_success(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        review_raw: dict[str, Any] = {
            "verdict": "approved",
            "findings": [
                {
                    "severity": "suggestion",
                    "file": "src/auth.py",
                    "line": 10,
                    "finding": "Use f-string",
                    "recommendation": "Minor style",
                },
            ],
            "summary": "Looks good",
        }
        handlers_dict = {"_review_result": review_raw, "submit_review": lambda x: None}
        mock_handlers.return_value = handlers_dict
        mock_graph.return_value = _BASE_STATE

        result = run_reviewer(1, 1, "diff here", "plan here")
        assert isinstance(result, ReviewResult)
        assert result.verdict == "approved"
        assert len(result.findings) == 1
        assert result.findings[0].severity == "suggestion"

    @patch("app.agents.reviewer.run_agent_graph", side_effect=RuntimeError("API down"))
    @patch("app.agents.reviewer.make_reviewer_handlers")
    def test_returns_blocking_finding_on_exception(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_handlers.return_value = {"_review_result": {}}
        result = run_reviewer(1, 1, "diff", "plan")
        assert result.verdict == "changes_required"
        assert result.has_blocking
        assert result.findings[0].severity == "blocking"

    @patch("app.agents.reviewer.run_agent_graph")
    @patch("app.agents.reviewer.make_reviewer_handlers")
    def test_returns_changes_required_when_no_review_submitted(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_handlers.return_value = {"_review_result": {}}
        mock_graph.return_value = {**_BASE_STATE, "submitted": False}
        result = run_reviewer(1, 1, "diff", "plan")
        # Empty _review_result → default verdict is "changes_required"
        assert result.verdict == "changes_required"


# ---------------------------------------------------------------------------
# run_qa behavior (mocked run_agent_graph)
# ---------------------------------------------------------------------------


class TestRunQaBehavior:
    @patch("app.agents.qa.run_agent_graph")
    @patch("app.agents.qa.make_qa_handlers")
    def test_returns_qa_result_on_success(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        qa_raw: dict[str, Any] = {
            "status": "passed",
            "tests_run": 42,
            "tests_passed": 42,
            "tests_failed": 0,
            "typecheck_clean": True,
            "lint_clean": True,
            "errors": [],
            "summary": "All 42 tests passed",
        }
        mock_handlers.return_value = {"_qa_result": qa_raw}
        mock_graph.return_value = _BASE_STATE

        result = run_qa(1, 1, ["src/auth.py"], "/tmp/wt")
        assert isinstance(result, QAResult)
        assert result.status == "passed"
        assert result.tests_run == 42
        assert result.typecheck_clean is True

    @patch("app.agents.qa.run_agent_graph", side_effect=RuntimeError("API down"))
    @patch("app.agents.qa.make_qa_handlers")
    def test_returns_failed_result_on_exception(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_handlers.return_value = {"_qa_result": {}}
        result = run_qa(1, 1, [], "/tmp/wt")
        assert result.status == "failed"
        assert len(result.errors) > 0

    @patch("app.agents.qa.run_agent_graph")
    @patch("app.agents.qa.make_qa_handlers")
    def test_returns_failed_when_no_qa_submitted(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_handlers.return_value = {"_qa_result": {}}
        mock_graph.return_value = {**_BASE_STATE, "submitted": False}
        result = run_qa(1, 1, [], "/tmp/wt")
        # Empty _qa_result → defaults to failed / zeros
        assert result.status == "failed"
        assert result.tests_run == 0


# ---------------------------------------------------------------------------
# run_devops behavior (mocked run_agent_graph)
# ---------------------------------------------------------------------------


class TestRunDevopsBehavior:
    @patch("app.agents.devops.run_agent_graph")
    @patch("app.agents.devops.make_devops_handlers")
    def test_returns_health_report_on_success(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        health_raw: dict[str, Any] = {
            "status": "healthy",
            "checks": [{"name": "db", "status": "ok"}],
            "summary": "All systems nominal",
        }
        mock_handlers.return_value = {"_health_result": health_raw}
        mock_graph.return_value = {
            **_BASE_STATE,
            "messages": [{"role": "assistant", "content": "Everything looks healthy."}],
        }

        report, error, tokens_in, tokens_out = run_devops()
        assert error is None
        assert report is not None
        assert report.status == "healthy"
        assert tokens_in == 800

    @patch("app.agents.devops.run_agent_graph")
    @patch("app.agents.devops.make_devops_handlers")
    def test_returns_unknown_when_no_submit(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_handlers.return_value = {"_health_result": {}}
        mock_graph.return_value = {
            **_BASE_STATE,
            "messages": [
                {"role": "assistant", "content": "No health report available."}
            ],
        }
        report, error, _, _ = run_devops()
        assert error is None
        assert report is not None
        assert report.status == "unknown"
        assert "No health report available." in report.summary

    @patch("app.agents.devops.run_agent_graph", side_effect=RuntimeError("Timeout"))
    @patch("app.agents.devops.make_devops_handlers")
    def test_returns_error_on_exception(
        self, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_handlers.return_value = {"_health_result": {}}
        report, error, tokens_in, tokens_out = run_devops()
        assert report is None
        assert error is not None
        assert "DevOps agent error" in error
        assert tokens_in == 0
