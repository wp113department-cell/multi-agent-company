"""AUDIT_Q_BATCH16 §91 gap-closure (2026-08-11) — architecture_drift.py:
real structural (circular-import/dead-code) counts diffed against a stored
baseline, reusing benchmark_manager's own storage + regression-report math.

Baseline rows ARE written to the real dev DB (agent_benchmarks table, keyed
"architecture_drift") — every test cleans up its own rows, following the
same pattern test_benchmark_manager.py already established.
"""

from __future__ import annotations

import asyncio

from app.fleet.architecture_drift import (
    _DRIFT_KEY,
    check_architecture_drift,
    compute_architecture_snapshot,
)


def _delete_drift_baseline() -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import AgentBenchmark

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(AgentBenchmark).where(
                        AgentBenchmark.agent_name == _DRIFT_KEY
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _write_module(tmp_path, name: str, source: str) -> None:
    (tmp_path / name).write_text(source)


class TestComputeArchitectureSnapshot:
    def test_none_for_nonexistent_directory(self, tmp_path) -> None:
        assert compute_architecture_snapshot(str(tmp_path / "does-not-exist")) is None

    def test_none_for_empty_directory(self, tmp_path) -> None:
        assert compute_architecture_snapshot(str(tmp_path)) is None

    def test_real_counts_from_a_clean_module(self, tmp_path) -> None:
        # "entry" is never called by anything in this file — the heuristic
        # (same as the pre-existing detect_dead_code()) can only see
        # in-directory call sites, so a genuine entry point is expected to
        # show up as "dead" here. "used" IS called, so it must not.
        _write_module(
            tmp_path,
            "clean.py",
            "def used():\n    return 1\n\ndef entry():\n    return used()\n",
        )
        snap = compute_architecture_snapshot(str(tmp_path))
        assert snap is not None
        assert snap.dead_code_count == 1
        assert snap.circular_import_count == 0

    def test_real_dead_code_count(self, tmp_path) -> None:
        _write_module(
            tmp_path,
            "unused.py",
            "def never_called():\n    return 1\n",
        )
        snap = compute_architecture_snapshot(str(tmp_path))
        assert snap is not None
        assert snap.dead_code_count == 1

    def test_real_import_edges_counted(self, tmp_path) -> None:
        # Mirrors test_day1_tools.py's own TestCircularDepDetect fixture
        # exactly (literal "app.b"/"app.a" — "app" is always in
        # local_roots regardless of the scanned directory's real name).
        # That existing test only asserts "doesn't crash", not a specific
        # cycle count, because module-key resolution for a synthetic
        # tmp_path (not a real "app/" package layout) is a known, pre-
        # existing heuristic limitation, not something this gap-closure
        # changes — this test asserts what IS reliably real here: a
        # non-zero import edge count from real ast.ImportFrom nodes.
        _write_module(tmp_path, "a.py", "from app.b import something\n")
        _write_module(tmp_path, "b.py", "from app.a import something\n")
        snap = compute_architecture_snapshot(str(tmp_path))
        assert snap is not None
        assert snap.total_import_edges >= 1


class TestCheckArchitectureDrift:
    def test_first_scan_has_no_baseline_and_is_not_a_regression(self, tmp_path) -> None:
        _delete_drift_baseline()
        try:
            _write_module(tmp_path, "clean.py", "def f():\n    return 1\n")
            report = check_architecture_drift(str(tmp_path))
            assert report is not None
            assert report.baseline_score is None
            assert report.is_regression is False
        finally:
            _delete_drift_baseline()

    def test_second_scan_diffs_against_first(self, tmp_path) -> None:
        _delete_drift_baseline()
        try:
            _write_module(tmp_path, "clean.py", "def f():\n    return 1\n")
            first = check_architecture_drift(str(tmp_path))
            assert first is not None

            # Introduce real dead code — a genuine regression in the
            # structural health score.
            _write_module(
                tmp_path, "newly_dead.py", "def never_called():\n    return 1\n"
            )
            second = check_architecture_drift(str(tmp_path))
            assert second is not None
            assert second.baseline_score == first.current_score
            assert second.current_score < second.baseline_score
            assert second.per_objective_delta["dead_code_count"] == 1.0
        finally:
            _delete_drift_baseline()

    def test_regression_flagged_when_drop_exceeds_threshold(self, tmp_path) -> None:
        _delete_drift_baseline()
        try:
            _write_module(tmp_path, "clean.py", "def f():\n    return 1\n")
            check_architecture_drift(str(tmp_path), regression_threshold=0.01)

            for i in range(5):
                _write_module(
                    tmp_path, f"dead_{i}.py", f"def never_called_{i}():\n    return 1\n"
                )
            report = check_architecture_drift(str(tmp_path), regression_threshold=0.01)
            assert report is not None
            assert report.is_regression is True
        finally:
            _delete_drift_baseline()

    def test_none_when_nothing_to_scan(self, tmp_path) -> None:
        assert check_architecture_drift(str(tmp_path / "missing")) is None
