"""
Day 1 — 13 Migrated Agents: Enable Flags Unit Tests
=====================================================
Verifies that every agent passes enable_planning/memory/reflection/lesson=True
plus task_description, repo_path, and model_haiku to run_agent_graph().

All tests are pure unit tests (mocked LLM) — no network, no DB, no API key needed.
"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_FINAL_STATE: dict[str, Any] = {
    "messages": [{"role": "assistant", "content": [{"type": "text", "text": "done"}]}],
    "submitted": True,
    "result": {"plan": "test plan", "status": "ok", "subtasks": [{"id": 1, "type": "code", "description": "x"}],
               "technical_approach": "ok", "impacted_files": [], "risks": [], "risk_level": "low",
               "verdict": "approved", "findings": [], "summary": "ok",
               "tests_run": 1, "tests_passed": 1, "tests_failed": 0, "status_detail": "passed",
               "checks": [], "health_score": 1.0,
               "goal_id": "g1", "epics": ["Build feature"],
               "files_written": [], "raw_text": "done",
               "findings_count": 0, "research_summary": "done", "relevant_libraries": [],
               "recommended_approach": "ok", "raw_text2": ""},
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
    s.executive_max_epics_per_goal = 5
    s.devops_bash_allowlist = ""
    return s


def _captured_kwargs(mock_run: MagicMock) -> dict[str, Any]:
    """Return the kwargs of the first run_agent_graph call."""
    assert mock_run.call_count >= 1, "run_agent_graph was never called"
    return mock_run.call_args_list[0][1]


def _assert_all_flags(kwargs: dict[str, Any], agent_name: str) -> None:
    for flag in ("enable_planning", "enable_memory", "enable_reflection", "enable_lesson"):
        assert kwargs.get(flag) is True, f"{agent_name}: {flag} must be True, got {kwargs.get(flag)}"
    assert kwargs.get("task_description"), f"{agent_name}: task_description must be non-empty"
    assert kwargs.get("repo_path"), f"{agent_name}: repo_path must be set"
    assert kwargs.get("model_haiku"), f"{agent_name}: model_haiku must be set"


# ---------------------------------------------------------------------------
# Tests — one class per agent
# ---------------------------------------------------------------------------

class TestArchitectFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.architect.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.architect.get_settings", return_value=_mock_settings()), \
             patch("app.agents.architect.make_read_only_handlers", return_value={}):
            from app.agents.architect import architect_node
            from app.pipeline.state import PipelineState
            state: PipelineState = {"task_title": "Add login page", "task_description": "desc",
                                     "repo_path": "/tmp/repo", "stage": "architect",
                                     "pm_brief": {}, "memory_context": ""}  # type: ignore[typeddict-item]
            architect_node(state)
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "architect")
        assert kwargs["task_description"] == "Add login page"


class TestDecomposerFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.decomposer.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.decomposer.get_settings", return_value=_mock_settings()), \
             patch("app.agents.decomposer.make_read_only_handlers", return_value={}):
            from app.agents.decomposer import decomposer_node
            from app.pipeline.state import PipelineState
            state: PipelineState = {"task_title": "Build auth", "task_description": "desc",
                                     "repo_path": "/tmp/repo", "stage": "decomposer",
                                     "pm_brief": {}, "architect_plan": {}, "memory_context": ""}  # type: ignore[typeddict-item]
            decomposer_node(state)
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "decomposer")
        assert kwargs["task_description"] == "Build auth"


class TestPlannerFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.planner.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.planner.get_settings", return_value=_mock_settings()), \
             patch("app.agents.planner.make_read_only_handlers", return_value={}):
            from app.agents.planner import run_planner
            run_planner(task_id=1, title="Implement caching", description="Cache layer", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "planner")
        assert kwargs["task_description"] == "Implement caching"


class TestPmFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.pm.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.pm.get_settings", return_value=_mock_settings()), \
             patch("app.agents.pm.make_read_only_handlers", return_value={}):
            from app.agents.pm import pm_node
            from app.pipeline.state import PipelineState
            state: PipelineState = {"task_title": "Auth feature", "task_description": "Add JWT auth",
                                     "repo_path": "/tmp/repo", "stage": "pm", "memory_context": ""}  # type: ignore[typeddict-item]
            pm_node(state)
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "pm")
        assert kwargs["task_description"] == "Add JWT auth"


class TestBackendDevFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.backend_dev.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.backend_dev.get_settings", return_value=_mock_settings()), \
             patch("app.agents.backend_dev.make_coder_handlers", return_value={}), \
             patch("app.agents.backend_dev._run_backend_checks", return_value=None):
            from app.agents.backend_dev import run_backend_dev
            run_backend_dev(task_id=1, subtask_id=2, plan="Do X", worktree_path="/tmp/wt", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "backend_dev")
        assert "subtask 2" in kwargs["task_description"]


class TestFrontendDevFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.frontend_dev.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.frontend_dev.get_settings", return_value=_mock_settings()), \
             patch("app.agents.frontend_dev.make_coder_handlers", return_value={}), \
             patch("app.agents.frontend_dev._run_frontend_checks", return_value=None):
            from app.agents.frontend_dev import run_frontend_dev
            run_frontend_dev(task_id=1, subtask_id=3, plan="Build UI", worktree_path="/tmp/wt", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "frontend_dev")
        assert "subtask 3" in kwargs["task_description"]


class TestCoderFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.coder.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.coder.get_settings", return_value=_mock_settings()), \
             patch("app.agents.coder.make_coder_handlers", return_value={}):
            from app.agents.coder import run_coder
            run_coder(task_id=7, plan="Write code", worktree_path="/tmp/wt", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "coder")
        assert "task 7" in kwargs["task_description"]


class TestReviewerFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.reviewer.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.reviewer.get_settings", return_value=_mock_settings()), \
             patch("app.agents.reviewer.make_reviewer_handlers", return_value={}):
            from app.agents.reviewer import run_reviewer
            run_reviewer(task_id=1, subtask_id=4, diff="+ line", plan="ok", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "reviewer")
        assert "subtask 4" in kwargs["task_description"]

    def test_verification_cfg_set_by(self) -> None:
        import app.agents.reviewer as mod
        assert mod._VERIFICATION_CFG.set_by == {"git_diff": "diff_reviewed"}


class TestQaFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.qa.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.qa.get_settings", return_value=_mock_settings()), \
             patch("app.agents.qa.make_qa_handlers", return_value={}):
            from app.agents.qa import run_qa
            run_qa(task_id=1, subtask_id=5, files_changed=["a.py"], worktree_path="/tmp/wt", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "qa")
        assert "subtask 5" in kwargs["task_description"]


class TestDevopsFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.devops.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.devops.get_settings", return_value=_mock_settings()), \
             patch("app.agents.devops.make_devops_handlers", return_value={}):
            from app.agents.devops import run_devops
            run_devops(task_description="Check system health", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "devops")
        assert kwargs["task_description"] == "Check system health"

    def test_verification_cfg_set_by(self) -> None:
        import app.agents.devops as mod
        assert mod._VERIFICATION_CFG.set_by == {"bash": "checks_run"}


class TestResearchFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.research.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.research.get_settings", return_value=_mock_settings()), \
             patch("app.agents.research.make_research_handlers", return_value={}):
            from app.agents.research import run_research
            run_research(task_description="Research caching libraries", repo_path="/tmp/repo")
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "research")
        assert kwargs["task_description"] == "Research caching libraries"


class TestExecutiveFlags:
    def test_flags_and_kwargs(self) -> None:
        import asyncio

        async def _async_flush() -> None:
            return None

        with patch("app.agents.executive.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.executive.get_settings", return_value=_mock_settings()):
            from app.agents.executive import run_executive
            db_mock = MagicMock()
            db_mock.flush = _async_flush
            db_mock.add = MagicMock()

            async def _run() -> None:
                await run_executive("Build a login system for our app", db_mock)

            asyncio.run(_run())
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "executive")
        assert "Goal breakdown" in kwargs["task_description"]

    def test_task_description_truncated(self) -> None:
        import asyncio

        async def _async_flush() -> None:
            return None

        with patch("app.agents.executive.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.executive.get_settings", return_value=_mock_settings()):
            from app.agents.executive import run_executive
            long_goal = "A" * 200
            db_mock = MagicMock()
            db_mock.flush = _async_flush
            db_mock.add = MagicMock()

            async def _run() -> None:
                await run_executive(long_goal, db_mock)

            asyncio.run(_run())
        kwargs = _captured_kwargs(mock_run)
        # task_description contains at most 80 chars of goal_text
        assert len(kwargs["task_description"]) <= len("Goal breakdown: ") + 80


class TestDocsFlags:
    def test_flags_and_kwargs(self) -> None:
        with patch("app.agents.docs.run_agent_graph", return_value=_MINIMAL_FINAL_STATE) as mock_run, \
             patch("app.agents.docs.get_settings", return_value=_mock_settings()), \
             patch("app.agents.docs.make_docs_handlers", return_value={}):
            from app.agents.docs import run_docs
            run_docs(
                epic_title="Authentication Epic",
                epic_description="Add JWT auth",
                files_changed=["auth.py"],
                diffs="+ import jwt",
                qa_summaries=["Tests passed"],
                worktree_path="/tmp/wt",
                repo_path="/tmp/repo",
            )
        kwargs = _captured_kwargs(mock_run)
        _assert_all_flags(kwargs, "docs")
        assert "Authentication Epic" in kwargs["task_description"]

    def test_verification_cfg_set_by(self) -> None:
        import app.agents.docs as mod
        assert mod._VERIFICATION_CFG.set_by == {"write_file": "docs_written"}


# ===========================================================================
# VerificationConfig enforce_in_result — must be non-empty for tool-using agents
# ===========================================================================

_TOOL_AGENTS = [
    ("app.agents.backend_dev", "checks_run"),
    ("app.agents.frontend_dev", "checks_run"),
    ("app.agents.coder", "checks_run"),
    ("app.agents.reviewer", "diff_reviewed"),
    ("app.agents.qa", "tests_run"),
    ("app.agents.devops", "checks_run"),
    ("app.agents.docs", "docs_written"),
]


class TestDay1VerificationEnforce:
    """enforce_in_result must be non-empty so the graph actually checks the result."""

    @pytest.mark.parametrize("module_path,expected_key", _TOOL_AGENTS)
    def test_enforce_in_result_non_empty(self, module_path: str, expected_key: str) -> None:
        mod = importlib.import_module(module_path)
        cfg = mod._VERIFICATION_CFG
        assert len(cfg.enforce_in_result) > 0, (
            f"{module_path}: enforce_in_result is empty — "
            "agent can submit without verification being checked"
        )
        assert expected_key in cfg.enforce_in_result, (
            f"{module_path}: expected key {expected_key!r} not in enforce_in_result={cfg.enforce_in_result}"
        )
