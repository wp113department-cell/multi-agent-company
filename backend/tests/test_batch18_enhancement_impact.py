"""AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — "Autonomous Quality
Improvement" was missing pre-change impact simulation. Tests
app.fleet.enhancement_impact.simulate_enhancement_impact directly (pure,
no DB) plus its wiring into make_submit_enhancement_request_handler.
"""

from __future__ import annotations

from app.fleet.enhancement_impact import simulate_enhancement_impact


class TestSimulateEnhancementImpact:
    def test_no_citations_returns_empty_report(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        report = simulate_enhancement_impact(
            str(tmp_path), "This is a vague description with no file citation", {}
        )
        assert report["total_target_files"] == 0
        assert report["total_affected_files"] == 0
        assert report["targets"] == {}

    def test_finds_real_referencing_files(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        target = tmp_path / "widget.py"
        target.write_text("def widget():\n    pass\n")
        caller = tmp_path / "user_of_widget.py"
        caller.write_text("from widget import widget\nwidget()\n")

        report = simulate_enhancement_impact(
            str(tmp_path), "Found a bug in widget.py:1", {}
        )

        assert report["total_target_files"] == 1
        assert "widget.py" in report["targets"]
        assert "user_of_widget.py" in report["targets"]["widget.py"]

    def test_evidence_dict_is_also_scanned(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        (tmp_path / "helper.py").write_text("x = 1\n")
        report = simulate_enhancement_impact(
            str(tmp_path),
            "no file mentioned here",
            {"citations": ["helper.py:1"]},
        )
        assert report["total_target_files"] == 1
        assert "helper.py" in report["targets"]

    def test_empty_repo_root_is_safe_noop(self) -> None:
        report = simulate_enhancement_impact("", "see foo.py:1", {})
        assert report == {
            "targets": {},
            "total_target_files": 0,
            "total_affected_files": 0,
        }

    def test_nonexistent_repo_root_is_safe_noop(self) -> None:
        report = simulate_enhancement_impact("/not/a/real/path/xyz", "see foo.py:1", {})
        assert report == {
            "targets": {},
            "total_target_files": 0,
            "total_affected_files": 0,
        }


class TestSubmitEnhancementRequestHandlerWiring:
    def test_handler_persists_impact_simulation(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Real DB round trip — mirrors test_day9_fleet_agents.py's own
        established pattern for this exact handler
        (test_submit_enhancement_request_writes_row), extended to assert
        the new impact_simulation column this batch adds."""
        import asyncio
        from typing import Any

        from app.agents.tools import make_submit_enhancement_request_handler
        from app.db.models import EnhancementRequest
        from tests.test_day9_fleet_agents import (
            _cleanup_enhancement_requests,
            _with_isolated_session,
        )

        (tmp_path / "buggy.py").write_text("def f():\n    pass\n")
        caller = tmp_path / "caller.py"
        caller.write_text("from buggy import f\nf()\n")

        handler = make_submit_enhancement_request_handler(
            "test_agent_impact_sim", repo_path=str(tmp_path)
        )
        result = handler(
            {
                "title": "fix buggy.py",
                "description": "buggy.py:1 has an issue",
                "category": "bug",
                "priority": "low",
                "evidence": {},
            }
        )
        assert "filed for human review" in result

        async def _fetch(session: Any) -> EnhancementRequest | None:
            from sqlalchemy import select

            r = await session.execute(
                select(EnhancementRequest).where(
                    EnhancementRequest.agent_name == "test_agent_impact_sim"
                )
            )
            return r.scalars().first()

        row = asyncio.run(_with_isolated_session(_fetch))
        try:
            assert row is not None
            assert row.impact_simulation is not None
            assert row.impact_simulation["total_target_files"] == 1
            assert "buggy.py" in row.impact_simulation["targets"]
            assert "caller.py" in row.impact_simulation["targets"]["buggy.py"]
        finally:
            if row is not None:
                asyncio.run(_cleanup_enhancement_requests([row.id]))
