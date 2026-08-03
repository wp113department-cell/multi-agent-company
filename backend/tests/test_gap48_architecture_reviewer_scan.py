"""Stage 2 Days 48-50 — architecture_reviewer wired into the periodic fleet
scan loop (answers.md Q35/Q36: "Dead code"/"Circular dependencies"/
"architecture" all PARTIAL — "tool exists and works, architecture_reviewer
only, on-demand... Plan: add architecture_reviewer's checks to
_fleet_agents_scan_loop()"). Also covers the real, pre-existing
submit_arch_review schema/consumer mismatch bug found and fixed while
building this (every real architecture-review finding was previously
silently discarded).
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agent_result import AgentResult
from app.agents.architecture_reviewer import (
    SCAN_TOOLS,
    _SUBMIT_ARCH_ENHANCEMENT_TOOL_SPEC,
    make_scan_handlers,
    run_arch_review,
    run_architecture_reviewer_scan,
)
from app.agents.tools import _SUBMIT_ARCH_REVIEW_TOOL
from app.config import get_settings
from app.db.models import EnhancementRequest


def _engine() -> object:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def test_submit_arch_review_schema_matches_role_prompt_contract() -> None:
    """Regression guard for the real bug this day fixed: the schema's
    property names must be exactly what roles/architecture_reviewer.md's
    own documented "Terminal tool contract" specifies and what
    run_arch_review() reads back — not the old, unused
    {verdict, issues, summary} shape."""
    props = set(_SUBMIT_ARCH_REVIEW_TOOL["input_schema"]["properties"].keys())
    assert props == {
        "structure_summary",
        "risks",
        "recommendations",
        "blast_radius",
        "import_graph_ran",
    }
    assert "verdict" not in props
    assert "issues" not in props


def test_run_arch_review_correctly_propagates_real_risks_end_to_end() -> None:
    """Proves the consuming code path (run_arch_review's own return-value
    construction) correctly reads the now-fixed field names against a
    final_state shaped exactly like a real submit_arch_review call would
    produce."""
    real_result = {
        "structure_summary": "12 modules, 1 real circular dependency found",
        "risks": [
            {
                "severity": "high",
                "description": "circular import between app.a and app.b",
                "evidence": [
                    "app/a.py:3 — imports app.b",
                    "app/b.py:5 — imports app.a",
                ],
            }
        ],
        "recommendations": ["extract shared types into app.c"],
        "blast_radius": ["app/a.py", "app/b.py"],
        "import_graph_ran": True,
    }
    final_state = {
        "result": real_result,
        "verification": {"import_graph_ran": True},
        "tokens_in": 100,
        "tokens_out": 50,
        "submitted": True,
    }
    with patch(
        "app.agents.architecture_reviewer.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.architecture_reviewer.make_arch_reviewer_handlers",
        return_value={},
    ):
        result = run_arch_review(task_id=1, focus="test")

    assert result.summary == "12 modules, 1 real circular dependency found"
    assert len(result.findings) == 1
    assert result.findings[0]["severity"] == "high"
    assert result.verified is True


def test_scan_tools_excludes_submit_arch_review_includes_enhancement_request() -> None:
    names = {t["name"] for t in SCAN_TOOLS}
    assert "submit_arch_review" not in names
    assert "submit_enhancement_request" in names
    # Real architecture analysis tools still present in scan mode.
    assert "import_graph" in names
    assert "circular_dep_detect" in names
    assert "dead_code_detect" in names


def test_scan_enhancement_tool_category_includes_architecture() -> None:
    categories = _SUBMIT_ARCH_ENHANCEMENT_TOOL_SPEC["input_schema"]["properties"][
        "category"
    ]["enum"]
    assert "architecture" in categories


def test_make_scan_handlers_includes_required_handlers(tmp_path: object) -> None:
    handlers = make_scan_handlers(str(tmp_path), trace_id="test-trace")
    for name in (
        "import_graph",
        "circular_dep_detect",
        "dead_code_detect",
        "call_graph",
        "submit_enhancement_request",
        "record_learning",
    ):
        assert name in handlers


def test_run_architecture_reviewer_scan_files_real_enhancement_request() -> None:
    """End-to-end (with a mocked LLM graph, real DB): the scan's own
    submit_enhancement_request handler, when actually invoked, writes a
    real EnhancementRequest row with category='architecture'.

    Deliberately a PLAIN sync test, not @pytest.mark.asyncio: the real
    submit_enhancement_request handler internally does its own
    asyncio.run() (make_submit_enhancement_request_handler's established
    pattern for a sync tool-handler needing a real DB write) — calling it
    from inside an already-running async test's event loop would raise
    "asyncio.run() cannot be called from a running event loop". Same
    documented hazard/workaround this codebase's own memory
    ([[feedback_asyncio_isolated_engine]]) and other test files
    (test_memory_archived_filter.py's retention test) already established."""
    import asyncio

    suffix = uuid.uuid4().hex[:8]
    title = f"gap48 real circular dependency {suffix}"

    def _fake_run_agent_graph(**kwargs: object) -> dict[str, object]:
        handlers = kwargs["tool_handlers"]
        assert isinstance(handlers, dict)
        # Simulate the LLM actually calling submit_enhancement_request once,
        # through the REAL handler — proving the handler is real and wired,
        # not just present in a dict.
        handlers["submit_enhancement_request"](
            {
                "title": title,
                "description": "app.a and app.b import each other",
                "category": "architecture",
                "priority": "medium",
                "evidence": {"files": ["app/a.py", "app/b.py"]},
            }
        )
        return {
            "result": {},
            "verification": {"scan_ran": True},
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
            "app.agents.architecture_reviewer.run_agent_graph",
            side_effect=_fake_run_agent_graph,
        ), patch(
            "app.agents.architecture_reviewer.get_settings", return_value=settings
        ):
            result = run_architecture_reviewer_scan(trace_id=f"gap48-{suffix}")

        assert isinstance(result, AgentResult)
        assert result.summary == "Architecture scan complete"
        assert result.verified is True

        row = asyncio.run(_verify_and_cleanup())
        assert row.category == "architecture"
        assert row.agent_name == "architecture_reviewer"
        assert row.status == "pending"
    finally:
        # Best-effort cleanup even if an assertion above failed before the
        # normal verify-and-cleanup path ran.
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


def test_fleet_agents_scan_loop_includes_architecture_reviewer() -> None:
    """Verify-real-callers guard: architecture_reviewer's scan must actually
    be wired into the real periodic loop, not just exist as an orphaned
    function nothing calls."""
    import app.main as main_module

    source = inspect.getsource(main_module._fleet_agents_scan_loop)
    assert "architecture_reviewer" in source
    assert "run_architecture_reviewer_scan" in source
