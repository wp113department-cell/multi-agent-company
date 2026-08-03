"""Stage 2 Day 49 — dependency_security_agent wired into the periodic fleet
scan loop (answers.md Q35 "Dependency conflicts": no dependency-related
agent runs autonomously). Also covers the real, pre-existing
submit_dependency_report schema/consumer mismatch bug found and fixed
along the way (the same bug class Day 48 found in submit_arch_review).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agent_result import AgentResult
from app.agents.dependency_security_agent import (
    _SCAN_SUBMIT_ENHANCEMENT_TOOL,
    _SCAN_TOOLS,
    make_scan_handlers,
    run_dependency_security_scan,
)
from app.agents.tools import _SUBMIT_DEPENDENCY_REPORT_TOOL
from app.config import get_settings
from app.db.models import EnhancementRequest


def _engine() -> object:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def test_submit_dependency_report_schema_matches_role_prompt_contract() -> None:
    """Regression guard for the real bug this day fixed: the schema's
    property names must be exactly what roles/dependency_agent.md's own
    documented "Terminal tool contract" specifies and what
    run_dependency_agent() reads back — not the old, unused
    {outdated, upgraded, issues} shape."""
    props = set(_SUBMIT_DEPENDENCY_REPORT_TOOL["input_schema"]["properties"].keys())
    assert props == {"dependencies", "summary", "files_changed", "manifest_read"}
    assert "outdated" not in props
    assert "upgraded" not in props


def test_run_dependency_agent_correctly_propagates_real_dependencies() -> None:
    """Proves run_dependency_agent()'s own return-value construction
    correctly reads the now-fixed field names against a final_state shaped
    exactly like a real submit_dependency_report call would produce."""
    from app.agents.dependency_agent import run_dependency_agent

    real_result = {
        "dependencies": [
            {
                "name": "fastapi",
                "current_version": "0.111.0",
                "latest_version": "0.112.0",
                "vulnerability_ids": [],
                "upgrade_recommended": True,
                "breaking_changes": "",
            }
        ],
        "summary": "1 dependency checked, 1 upgrade available",
        "files_changed": [],
        "manifest_read": True,
    }
    final_state = {
        "result": real_result,
        "verification": {"manifest_read": True},
        "tokens_in": 100,
        "tokens_out": 50,
        "submitted": True,
    }
    with patch(
        "app.agents.dependency_agent.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.dependency_agent.make_dependency_agent_handlers",
        return_value={},
    ):
        result = run_dependency_agent(task_id=1, task_description="test")

    assert result.summary == "1 dependency checked, 1 upgrade available"
    assert len(result.findings) == 1
    assert result.findings[0]["name"] == "fastapi"
    assert result.verified is True


def test_scan_tools_excludes_old_submit_includes_enhancement_request() -> None:
    names = {t["name"] for t in _SCAN_TOOLS}
    assert "submit_dependency_security_agent" not in names
    assert "submit_enhancement_request" in names


def test_scan_enhancement_tool_category_includes_security() -> None:
    categories = _SCAN_SUBMIT_ENHANCEMENT_TOOL["input_schema"]["properties"][
        "category"
    ]["enum"]
    assert "security" in categories


def test_make_scan_handlers_includes_required_handlers(tmp_path: object) -> None:
    handlers = make_scan_handlers(str(tmp_path), trace_id="test-trace")
    for name in ("bash", "read_file", "submit_enhancement_request", "record_learning"):
        assert name in handlers


def test_run_dependency_security_scan_files_real_enhancement_request() -> None:
    """End-to-end (mocked LLM graph, real DB): the scan's own
    submit_enhancement_request handler, when actually invoked, writes a
    real EnhancementRequest row with category='security'.

    Plain sync test — see test_gap48_architecture_reviewer_scan.py's
    identical test for why (the real handler does its own asyncio.run()
    internally)."""
    suffix = uuid.uuid4().hex[:8]
    title = f"gap49 real CVE finding {suffix}"

    def _fake_run_agent_graph(**kwargs: object) -> dict[str, object]:
        handlers = kwargs["tool_handlers"]
        assert isinstance(handlers, dict)
        handlers["submit_enhancement_request"](
            {
                "title": title,
                "description": "requests 2.25.0 has a known CVE, upgrade to 2.31.0",
                "category": "security",
                "priority": "medium",
                "evidence": {"package": "requests", "cve": "CVE-2023-32681"},
            }
        )
        return {
            "result": {},
            "verification": {"audited": True},
            "tokens_in": 10,
            "tokens_out": 5,
            "submitted": True,
        }

    settings = MagicMock()
    settings.model_coder = "sonnet-test"
    settings.model_router = "haiku-test"
    settings.fleet_self_repo_path = "."

    async def _verify_and_cleanup() -> EnhancementRequest:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = (
                    await session.execute(
                        select(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                ).scalar_one()
                await session.execute(
                    delete(EnhancementRequest).where(EnhancementRequest.title == title)
                )
                await session.commit()
                return row
        finally:
            await engine.dispose()

    try:
        with patch(
            "app.agents.dependency_security_agent.run_agent_graph",
            side_effect=_fake_run_agent_graph,
        ), patch(
            "app.agents.dependency_security_agent.get_settings",
            return_value=settings,
        ):
            result = run_dependency_security_scan(trace_id=f"gap49-{suffix}")

        assert isinstance(result, AgentResult)
        assert result.summary == "Dependency security scan complete"
        assert result.verified is True

        row = asyncio.run(_verify_and_cleanup())
        assert row.category == "security"
        assert row.agent_name == "dependency_security_agent"
        assert row.status == "pending"
    finally:

        async def _force_cleanup() -> None:
            engine = _engine()
            try:
                async with async_sessionmaker(
                    engine, expire_on_commit=False
                )() as session:
                    await session.execute(
                        delete(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_force_cleanup())


def test_fleet_agents_scan_loop_includes_dependency_security_agent() -> None:
    """Verify-real-callers guard: the scan must actually be wired into the
    real periodic loop, not just exist as an orphaned function."""
    import app.main as main_module

    source = inspect.getsource(main_module._fleet_agents_scan_loop)
    assert "dependency_security_agent" in source
    assert "run_dependency_security_scan" in source
