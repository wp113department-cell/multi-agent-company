"""Tests for MASTER_AGENT_v2.md Phase 5.1 — manager.py's epic orchestration
converted to a real LangGraph StateGraph (build_epic_manager_graph()).

Scope decision (documented in manager.py itself too): only the epic-level
flow (cost check -> planning -> conflict check -> coding -> finalize) was
converted into graph nodes/edges. run_manager()'s own per-subtask retry
loop was deliberately left as a plain async function, called unchanged from
the "coding" node — it's the most heavily-tested part of this file (180+
tests across 13 modules, all still passing unmodified) and a poor
structural fit for LangGraph's node/edge model anyway.

The pending_cost_approval early-exit branch is already covered by
test_audit04_orchestration_fixes.py::test_run_epic_manager_releases_epic_slot_on_early_return
(still passing after this conversion). This file adds direct coverage for
the one other conditional-edge branch that had no prior end-to-end test:
the conflict-halt path, plus structural assertions on the graph itself.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.agents.manager import (
    EpicManagerState,
    build_epic_manager_graph,
    run_epic_manager,
)


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_epic() -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Epic

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            epic_id = str(uuid.uuid4())
            session.add(
                Epic(
                    epic_id=epic_id,
                    title="td phase51 epic manager graph test",
                    description="d",
                    status="pending",
                )
            )
            await session.commit()
            return epic_id
    finally:
        await engine.dispose()  # type: ignore[attr-defined]


async def _cleanup_epic(epic_id: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Epic

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            await session.execute(delete(DevTask).where(DevTask.epic_id == epic_id))
            await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
            await session.commit()
    finally:
        await engine.dispose()  # type: ignore[attr-defined]


class TestGraphStructure:
    def test_graph_compiles_with_the_5_expected_nodes(self) -> None:
        graph = build_epic_manager_graph()
        node_names = set(graph.get_graph().nodes.keys())
        for expected in {
            "cost_estimate",
            "planning",
            "conflict_check",
            "coding",
            "finalize",
        }:
            assert expected in node_names

    def test_state_is_a_typed_dict_with_the_expected_fields(self) -> None:
        # total=False TypedDict — just confirm the class exists with the
        # right annotated keys, matching what every node function reads.
        assert "epic_id" in EpicManagerState.__annotations__
        assert "db" in EpicManagerState.__annotations__
        assert "package" in EpicManagerState.__annotations__
        assert "manager_result" in EpicManagerState.__annotations__


class TestConflictHaltPath:
    async def test_run_epic_manager_halts_on_a_real_file_conflict_without_reaching_coding(
        self,
    ) -> None:
        """Drives run_epic_manager() all the way through cost_estimate ->
        planning -> conflict_check, with a real conflict, and confirms:
        (a) the returned EpicApprovalPackage matches exactly what the
        pre-conversion imperative code returned in this branch, (b) the
        epic's DB row is updated to status='halted' with the real conflict
        reason, and (c) run_manager (the "coding" node) is never reached —
        proving the conditional edge actually short-circuits the graph
        rather than merely returning early from a function body that still
        runs everything after it."""
        fake_estimate = AsyncMock(
            side_effect=[
                type(
                    "Estimate",
                    (),
                    {"estimated_cost_usd": 1.0, "requires_approval": False},
                )(),
                type(
                    "Estimate",
                    (),
                    {"estimated_cost_usd": 1.5, "requires_approval": False},
                )(),
            ]
        )
        fake_pipeline_result = {
            "subtasks": [
                {"id": 1, "type": "backend", "title": "t", "description": "d"}
            ],
            "task_description": "goal",
            "architect_plan": {
                "impacted_files": [{"path": "app/conflicting_file.py", "reason": "x"}]
            },
        }

        epic_id = await _make_epic()
        try:
            with patch(
                "app.pipeline.cost_controller.estimate_epic_cost", new=fake_estimate
            ), patch(
                "app.pipeline.graph.run_planning_pipeline",
                new=AsyncMock(return_value=fake_pipeline_result),
            ), patch(
                "app.pipeline.conflict_guard.check_file_conflicts",
                new=AsyncMock(
                    return_value="app/conflicting_file.py already claimed by epic X"
                ),
            ), patch(
                "app.agents.manager.run_manager",
                new=AsyncMock(side_effect=AssertionError("coding node must not run")),
            ) as mock_run_manager:
                from sqlalchemy.ext.asyncio import async_sessionmaker

                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        package = await asyncio.wait_for(
                            run_epic_manager(epic_id=epic_id, goal="goal", db=session),
                            timeout=10.0,
                        )
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

                mock_run_manager.assert_not_called()

            assert package.status == "halted"
            assert package.epic_id == epic_id
            assert package.subtask_results == []
            assert package.total_files_changed == []
            assert package.cost_actual_usd == 0.0
            assert package.halt_reason is not None
            assert "app/conflicting_file.py" in package.halt_reason

            # Real DB row reflects the halt too, not just the returned object.
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import Epic

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    row = (
                        await session.execute(
                            select(Epic).where(Epic.epic_id == epic_id)
                        )
                    ).scalar_one()
                    assert row.status == "halted"
                    assert row.halt_reason == package.halt_reason
            finally:
                await engine.dispose()  # type: ignore[attr-defined]
        finally:
            await _cleanup_epic(epic_id)
