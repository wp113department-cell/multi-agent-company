"""Session 4 migration tests — pm, research, executive, docs (no real LLM calls).

Tests prove:
- All 4 agents import without errors and use run_agent_graph
- AGENT_CONTRACT in standard list format for all 4
- pm: risk_level=low, planning capability preserved (legacy superset)
- research: risk_level=low, research_enabled gate preserved
- executive: risk_level=medium (write_db), async interface unchanged, no tools
- docs: risk_level=medium (write_files), DocsReport dataclass unchanged
- _last_assistant_text in research/executive/docs correctly extracts final text
- pm_node returns blocked on exception and when no brief submitted
- pm_node uses final_state["result"] directly (no closure dependency)
- All 4 in capability_registry + agent_registry
- Fleet manager selects each by specific capability
"""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch


import app.agents.pm as pm_mod
import app.agents.research as rs_mod
import app.agents.executive as ex_mod
import app.agents.docs as dc_mod

from app.agents.pm import AGENT_CONTRACT as PM_CONTRACT, pm_node
from app.agents.research import AGENT_CONTRACT as RS_CONTRACT, run_research, ResearchReport
from app.agents.executive import (
    AGENT_CONTRACT as EX_CONTRACT, run_executive, _last_assistant_text as ex_last_text,
)
from app.agents.docs import AGENT_CONTRACT as DC_CONTRACT, run_docs, DocsReport, _build_docs_context


REQUIRED_CONTRACT_KEYS = {
    "name", "description", "allowed_tools", "input_types",
    "output_types", "side_effects", "permissions", "risk_level",
}

_SUBMIT_PRIVATE = {"submit_brief", "submit_research", "submit_docs"}


def _make_final_state(
    result: dict[str, Any] | None = None,
    submitted: bool = True,
    tokens_in: int = 500,
    tokens_out: int = 100,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "messages": messages or [],
        "verification": {},
        "result": result or {},
        "turns": 2,
        "submitted": submitted,
        "requires_human_approval": False,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


# ---------------------------------------------------------------------------
# AGENT_CONTRACT structure
# ---------------------------------------------------------------------------

class TestPmContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(PM_CONTRACT.keys())

    def test_name(self) -> None:
        assert PM_CONTRACT["name"] == "pm"

    def test_risk_level_low(self) -> None:
        assert PM_CONTRACT["risk_level"] == "low"

    def test_no_side_effects(self) -> None:
        assert PM_CONTRACT["side_effects"] == []

    def test_input_types_are_list(self) -> None:
        assert isinstance(PM_CONTRACT["input_types"], list)

    def test_output_types_are_list(self) -> None:
        assert isinstance(PM_CONTRACT["output_types"], list)

    def test_no_write_tools(self) -> None:
        write_tools = {"write_file", "edit_file", "bash"}
        used = write_tools & set(PM_CONTRACT["allowed_tools"])
        assert used == set(), f"pm has disallowed tools: {used}"

    def test_submit_brief_in_allowed_tools(self) -> None:
        assert "submit_brief" in PM_CONTRACT["allowed_tools"]


class TestResearchContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(RS_CONTRACT.keys())

    def test_name(self) -> None:
        assert RS_CONTRACT["name"] == "research"

    def test_risk_level_low(self) -> None:
        assert RS_CONTRACT["risk_level"] == "low"

    def test_no_side_effects(self) -> None:
        assert RS_CONTRACT["side_effects"] == []

    def test_submit_research_in_allowed_tools(self) -> None:
        assert "submit_research" in RS_CONTRACT["allowed_tools"]

    def test_no_write_or_bash_tools(self) -> None:
        dangerous = {"write_file", "edit_file", "bash"}
        used = dangerous & set(RS_CONTRACT["allowed_tools"])
        assert used == set(), f"research has dangerous tools: {used}"


class TestExecutiveContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(EX_CONTRACT.keys())

    def test_name(self) -> None:
        assert EX_CONTRACT["name"] == "executive"

    def test_risk_level_medium(self) -> None:
        assert EX_CONTRACT["risk_level"] == "medium"

    def test_side_effects_include_write_db(self) -> None:
        assert "write_db" in EX_CONTRACT["side_effects"]

    def test_no_tools(self) -> None:
        assert EX_CONTRACT["allowed_tools"] == []

    def test_output_includes_goal_id_and_epic_ids(self) -> None:
        assert "goal_id" in EX_CONTRACT["output_types"]
        assert "epic_ids" in EX_CONTRACT["output_types"]


class TestDocsContract:
    def test_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(DC_CONTRACT.keys())

    def test_name(self) -> None:
        assert DC_CONTRACT["name"] == "docs"

    def test_risk_level_medium(self) -> None:
        assert DC_CONTRACT["risk_level"] == "medium"

    def test_side_effects_include_write_files(self) -> None:
        assert "write_files" in DC_CONTRACT["side_effects"]

    def test_write_file_in_allowed_tools(self) -> None:
        assert "write_file" in DC_CONTRACT["allowed_tools"]

    def test_submit_docs_in_allowed_tools(self) -> None:
        assert "submit_docs" in DC_CONTRACT["allowed_tools"]

    def test_no_bash_tool(self) -> None:
        assert "bash" not in DC_CONTRACT["allowed_tools"]


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

    def test_pm_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(pm_mod)

    def test_research_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(rs_mod)

    def test_executive_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(ex_mod)

    def test_docs_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(dc_mod)

    def test_pm_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(pm_mod)

    def test_executive_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(ex_mod)

    def test_docs_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(dc_mod)


# ---------------------------------------------------------------------------
# External interface unchanged
# ---------------------------------------------------------------------------

class TestExternalInterfaceUnchanged:
    def test_pm_node_takes_state(self) -> None:
        assert "state" in inspect.signature(pm_node).parameters

    def test_run_research_signature(self) -> None:
        sig = inspect.signature(run_research)
        params = list(sig.parameters.keys())
        assert params[0] == "task_description"

    def test_run_executive_is_async(self) -> None:
        import asyncio
        assert asyncio.iscoroutinefunction(run_executive)

    def test_run_executive_signature(self) -> None:
        sig = inspect.signature(run_executive)
        assert "goal_text" in sig.parameters
        assert "db" in sig.parameters

    def test_run_docs_signature(self) -> None:
        sig = inspect.signature(run_docs)
        params = list(sig.parameters.keys())
        assert params[:3] == ["epic_title", "epic_description", "files_changed"]

    def test_research_report_dataclass_preserved(self) -> None:
        r = ResearchReport(
            findings=["finding 1"],
            relevant_libraries=[{"name": "httpx"}],
            recommended_approach="Use httpx",
            risks=["rate limits"],
        )
        assert r.recommended_approach == "Use httpx"
        assert r.raw_text == ""

    def test_docs_report_dataclass_preserved(self) -> None:
        r = DocsReport(files_written=["CHANGELOG.md"], summary="Updated changelog")
        assert r.files_written == ["CHANGELOG.md"]

    def test_build_docs_context_preserved(self) -> None:
        ctx = _build_docs_context("Epic A", "Desc", ["src/a.py"], "diff here", ["qa ok"])
        assert "Epic A" in ctx
        assert "src/a.py" in ctx
        assert "diff here" in ctx


# ---------------------------------------------------------------------------
# _last_assistant_text (shared by research/executive/docs)
# ---------------------------------------------------------------------------

class TestLastAssistantText:
    def test_extracts_string_content(self) -> None:
        messages = [{"role": "assistant", "content": "Report done."}]
        assert ex_last_text(messages) == "Report done."

    def test_extracts_from_content_list(self) -> None:
        messages = [{"role": "assistant", "content": [
            {"type": "text", "text": "Findings: X"},
        ]}]
        assert ex_last_text(messages) == "Findings: X"

    def test_returns_empty_when_no_assistant(self) -> None:
        assert ex_last_text([{"role": "user", "content": "hi"}]) == ""

    def test_returns_last_of_multiple(self) -> None:
        messages = [
            {"role": "assistant", "content": "first"},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "last"},
        ]
        assert ex_last_text(messages) == "last"


# ---------------------------------------------------------------------------
# Capability registry auto-registration
# ---------------------------------------------------------------------------

class TestCapabilityRegistryRegistration:
    def test_pm_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("pm") is not None

    def test_research_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("research") is not None

    def test_executive_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("executive") is not None

    def test_docs_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("docs") is not None

    def test_pm_has_planning_capability(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("pm")
        assert cap is not None
        assert "planning" in cap.capabilities

    def test_pm_has_legacy_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("pm")
        assert cap is not None
        assert "requirement_analysis" in cap.capabilities
        assert "goal_extraction" in cap.capabilities

    def test_executive_is_medium_risk(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("executive")
        assert cap is not None
        assert cap.risk_level == "medium"

    def test_docs_is_medium_risk(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("docs")
        assert cap is not None
        assert cap.risk_level == "medium"


# ---------------------------------------------------------------------------
# Agent registry auto-registration
# ---------------------------------------------------------------------------

class TestAgentRegistryRegistration:
    def test_pm_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("pm") is not None

    def test_research_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("research") is not None

    def test_executive_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("executive") is not None

    def test_docs_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("docs") is not None


# ---------------------------------------------------------------------------
# Fleet manager selection
# ---------------------------------------------------------------------------

class TestFleetManagerSelection:
    def test_selects_pm_by_planning(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("planning")
        assert plan is not None
        assert plan.agent_name == "pm"

    def test_selects_pm_by_requirement_analysis(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("requirement_analysis")
        assert plan is not None
        assert plan.agent_name == "pm"

    def test_selects_research_by_web_search(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("web_search")
        assert plan is not None
        assert plan.agent_name == "research"

    def test_selects_executive_by_epic_generation(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("epic_generation")
        assert plan is not None
        assert plan.agent_name == "executive"

    def test_selects_docs_by_documentation(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("documentation")
        assert plan is not None
        assert plan.agent_name == "docs"

    def test_selects_docs_by_changelog_writing(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("changelog_writing")
        assert plan is not None
        assert plan.agent_name == "docs"


# ---------------------------------------------------------------------------
# Tool manifest compliance (shared tools only)
# ---------------------------------------------------------------------------

class TestToolManifestCompliance:
    def _shared_tools(self, contract: dict[str, Any]) -> list[str]:
        return [t for t in contract["allowed_tools"] if t not in _SUBMIT_PRIVATE]

    def test_pm_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST
        for tool in self._shared_tools(PM_CONTRACT):
            assert tool in TOOL_MANIFEST, f"pm uses {tool!r} — not in TOOL_MANIFEST"

    def test_research_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST
        for tool in self._shared_tools(RS_CONTRACT):
            assert tool in TOOL_MANIFEST, f"research uses {tool!r} — not in TOOL_MANIFEST"

    def test_docs_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST
        for tool in [t for t in DC_CONTRACT["allowed_tools"] if t not in {"submit_docs"}]:
            assert tool in TOOL_MANIFEST, f"docs uses {tool!r} — not in TOOL_MANIFEST"


# ---------------------------------------------------------------------------
# pm_node behavior (mocked run_agent_graph)
# ---------------------------------------------------------------------------

_BRIEF = {
    "goals": ["Add login"],
    "constraints": ["Must use JWT"],
    "acceptance_criteria": ["User can log in"],
    "out_of_scope": ["OAuth providers"],
}


class TestPmNodeBehavior:
    @patch("app.agents.pm.run_agent_graph")
    @patch("app.agents.pm.make_read_only_handlers")
    def test_returns_brief_on_success(self, mock_handlers: Any, mock_graph: Any) -> None:
        mock_handlers.return_value = {"submit_brief": lambda x: "ok"}
        mock_graph.return_value = _make_final_state(result=_BRIEF, submitted=True)

        state = {
            "task_title": "Add auth",
            "task_description": "Implement login flow",
            "repo_path": "/tmp/repo",
        }
        result = pm_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "architect"
        assert result["pm_brief"] == _BRIEF

    @patch("app.agents.pm.run_agent_graph")
    @patch("app.agents.pm.make_read_only_handlers")
    def test_returns_blocked_when_not_submitted(self, mock_handlers: Any, mock_graph: Any) -> None:
        mock_handlers.return_value = {"submit_brief": lambda x: "ok"}
        mock_graph.return_value = _make_final_state(result={}, submitted=False)

        state = {"task_title": "T", "task_description": "D", "repo_path": "/tmp"}
        result = pm_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "blocked"

    @patch("app.agents.pm.run_agent_graph", side_effect=RuntimeError("timeout"))
    @patch("app.agents.pm.make_read_only_handlers")
    def test_returns_blocked_on_exception(self, mock_handlers: Any, mock_graph: Any) -> None:
        mock_handlers.return_value = {"submit_brief": lambda x: "ok"}
        state = {"task_title": "T", "task_description": "D", "repo_path": "/tmp"}
        result = pm_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "blocked"
        assert "PM Agent failed" in result["error"]

    @patch("app.agents.pm.run_agent_graph")
    @patch("app.agents.pm.make_read_only_handlers")
    def test_memory_block_included_when_present(self, mock_handlers: Any, mock_graph: Any) -> None:
        mock_handlers.return_value = {"submit_brief": lambda x: "ok"}
        mock_graph.return_value = _make_final_state(result=_BRIEF, submitted=True)

        state = {
            "task_title": "T", "task_description": "D",
            "repo_path": "/tmp", "memory_context": "prior lessons here",
        }
        pm_node(state)  # type: ignore[arg-type]
        call_kwargs = mock_graph.call_args[1]
        assert "prior lessons here" in call_kwargs["initial_message"]


# ---------------------------------------------------------------------------
# run_research behavior
# ---------------------------------------------------------------------------

class TestRunResearchBehavior:
    @patch("app.agents.research.get_settings")
    def test_returns_disabled_when_not_enabled(self, mock_settings: Any) -> None:
        mock_settings.return_value = MagicMock(research_enabled=False)
        report, error, tokens_in, _ = run_research("find stuff")
        assert report is None
        assert "disabled" in error.lower()
        assert tokens_in == 0

    @patch("app.agents.research.run_agent_graph")
    @patch("app.agents.research.make_research_handlers")
    @patch("app.agents.research.get_settings")
    def test_returns_report_on_success(
        self, mock_settings: Any, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_settings.return_value = MagicMock(
            research_enabled=True, model_router="haiku", target_repo_path="/repo"
        )
        research_raw = {
            "findings": ["Use FastAPI"],
            "relevantLibraries": [{"name": "fastapi"}],
            "recommendedApproach": "REST with FastAPI",
            "risks": ["rate limits"],
        }
        mock_handlers.return_value = {"_research_result": research_raw}
        mock_graph.return_value = _make_final_state(
            messages=[{"role": "assistant", "content": "Found FastAPI pattern."}]
        )

        report, error, tokens_in, _ = run_research("research FastAPI")
        assert error is None
        assert report is not None
        assert "Use FastAPI" in report.findings
        assert report.raw_text == "Found FastAPI pattern."

    @patch("app.agents.research.run_agent_graph", side_effect=RuntimeError("timeout"))
    @patch("app.agents.research.make_research_handlers")
    @patch("app.agents.research.get_settings")
    def test_returns_fallback_on_exception(
        self, mock_settings: Any, mock_handlers: Any, mock_graph: Any
    ) -> None:
        mock_settings.return_value = MagicMock(
            research_enabled=True, model_router="haiku", target_repo_path="/repo"
        )
        mock_handlers.return_value = {"_research_result": {}}
        report, error, tokens_in, _ = run_research("research something")
        assert report is not None
        assert error is not None
        assert tokens_in == 0


# ---------------------------------------------------------------------------
# run_docs behavior
# ---------------------------------------------------------------------------

class TestRunDocsBehavior:
    @patch("app.agents.docs.run_agent_graph")
    @patch("app.agents.docs.make_docs_handlers")
    def test_returns_report_on_success(self, mock_handlers: Any, mock_graph: Any) -> None:
        docs_raw = {"files_written": ["CHANGELOG.md"], "summary": "Updated changelog"}
        mock_handlers.return_value = {"_docs_result": docs_raw}
        mock_graph.return_value = _make_final_state(
            messages=[{"role": "assistant", "content": "Documentation written."}]
        )

        report, error, tokens_in, _ = run_docs(
            "Epic A", "Desc", ["src/a.py"], "diff", ["qa ok"], "/tmp/wt"
        )
        assert error is None
        assert report is not None
        assert report.files_written == ["CHANGELOG.md"]
        assert report.raw_text == "Documentation written."

    @patch("app.agents.docs.run_agent_graph")
    @patch("app.agents.docs.make_docs_handlers")
    def test_returns_error_when_no_submit(self, mock_handlers: Any, mock_graph: Any) -> None:
        mock_handlers.return_value = {"_docs_result": {}}
        mock_graph.return_value = _make_final_state(
            messages=[{"role": "assistant", "content": "I forgot to call submit."}]
        )
        report, error, _, _ = run_docs("Epic", "D", [], "", [], "/tmp/wt")
        assert error == "Docs agent did not call submit_docs"
        assert report is not None
        assert report.raw_text == "I forgot to call submit."

    @patch("app.agents.docs.run_agent_graph", side_effect=RuntimeError("API down"))
    @patch("app.agents.docs.make_docs_handlers")
    def test_returns_none_on_exception(self, mock_handlers: Any, mock_graph: Any) -> None:
        mock_handlers.return_value = {"_docs_result": {}}
        report, error, tokens_in, _ = run_docs("E", "D", [], "", [], "/tmp/wt")
        assert report is None
        assert error is not None
        assert tokens_in == 0
