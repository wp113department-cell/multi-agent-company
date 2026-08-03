"""Stage 2 Day 50 — prompt_registry.deploy() gets a real caller (answers.md
Q35/Q36/Phase-6 finding #8): "Several fully-built, tested subsystems are
dormant (never called in production): prompt_registry.py's draft->review->
approve->deploy->rollback lifecycle... Plan: wire an API endpoint (or the
knowledge_curator apply path) through prompt_registry.propose()/deploy()
instead of raw file writes, so the built machinery is actually load-bearing."

This wires the real, existing path: make_fleet_apply_handlers()'s
write_file/edit_file handlers (shared by knowledge_curator, agent_debugger,
agent_performance_reviewer, quality_auditor's APPLY phases — the only real
production code that ever touches roles/*.md) now route role-prompt writes
through prompt_registry.propose()->submit_for_review()->approve()->deploy()
instead of a raw disk write, making the regression gate genuinely
load-bearing for the one real path that reaches it.

Every test uses a role_name prefixed td_pr_gap50_ (not a real production
role) and cleans up both its DB rows and its roles/*.md file, matching
test_prompt_registry.py's established convention.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from app.agents.tools import _role_prompt_name, make_fleet_apply_handlers
from app.fleet.benchmark_manager import get_benchmark_manager
from app.fleet.metrics import get_metrics_collector
from app.fleet.prompt_registry import get_prompt_registry

_ROLES_DIR = Path(__file__).parent.parent / "roles"


def _cleanup(role_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import PromptVersion

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(PromptVersion).where(PromptVersion.role_name == role_name)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())
    role_file = _ROLES_DIR / f"{role_name}.md"
    if role_file.exists():
        role_file.unlink()


def _delete_benchmarks(agent_name: str) -> None:
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
                        AgentBenchmark.agent_name == agent_name
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_role_prompt_name_matches_only_top_level_roles_md_files() -> None:
    assert _role_prompt_name("roles/coder.md") == "coder"
    assert _role_prompt_name("roles/sub/coder.md") is None
    assert _role_prompt_name("roles/coder.txt") is None
    assert _role_prompt_name("app/agents/tools.py") is None
    assert _role_prompt_name("coder.md") is None


def test_write_file_to_role_prompt_path_routes_through_prompt_registry(
    tmp_path: object,
) -> None:
    role_name = "td_pr_gap50_write"
    try:
        handlers = make_fleet_apply_handlers(
            str(tmp_path), agent_name="td_pr_gap50_write"
        )
        msg = handlers["write_file"](
            {"path": f"roles/{role_name}.md", "content": "Gap50 v1 content"}
        )
        assert "Deployed" in msg
        assert f"{role_name}.md" in msg

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert role_file.read_text(encoding="utf-8") == "Gap50 v1 content"

        deployed = get_prompt_registry().get_deployed(role_name)
        assert deployed is not None
        assert deployed.status == "deployed"
        assert deployed.proposed_by == "td_pr_gap50_write"
        assert deployed.content == "Gap50 v1 content"
    finally:
        _cleanup(role_name)


def test_write_file_to_role_prompt_path_is_a_noop_when_unchanged(
    tmp_path: object,
) -> None:
    role_name = "td_pr_gap50_noop"
    try:
        handlers = make_fleet_apply_handlers(
            str(tmp_path), agent_name="td_pr_gap50_noop"
        )
        first = handlers["write_file"](
            {"path": f"roles/{role_name}.md", "content": "same content"}
        )
        assert "Deployed" in first

        second = handlers["write_file"](
            {"path": f"roles/{role_name}.md", "content": "same content"}
        )
        assert "No change" in second

        history = get_prompt_registry().get_history(role_name)
        assert len(history) == 1  # no new version created for the identical write
    finally:
        _cleanup(role_name)


def test_edit_file_to_role_prompt_path_routes_through_prompt_registry_v2(
    tmp_path: object,
) -> None:
    role_name = "td_pr_gap50_edit"
    try:
        handlers = make_fleet_apply_handlers(
            str(tmp_path), agent_name="td_pr_gap50_edit"
        )
        handlers["write_file"](
            {"path": f"roles/{role_name}.md", "content": "line one\nline two\n"}
        )

        msg = handlers["edit_file"](
            {
                "path": f"roles/{role_name}.md",
                "old_string": "line two",
                "new_string": "line two edited",
            }
        )
        assert "Deployed" in msg

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert role_file.read_text(encoding="utf-8") == "line one\nline two edited\n"

        history = get_prompt_registry().get_history(role_name)
        by_version = {h.version_number: h.status for h in history}
        assert by_version == {1: "superseded", 2: "deployed"}
    finally:
        _cleanup(role_name)


def test_write_file_to_non_role_prompt_path_is_a_raw_disk_write_unchanged(
    tmp_path: object,
) -> None:
    """Regression guard: only roles/<name>.md is redirected — every other
    write_file/edit_file target (docs, source, config) must behave exactly
    as before, since the other 4 agents sharing this handler set write
    plenty of non-prompt files too."""
    handlers = make_fleet_apply_handlers(str(tmp_path), agent_name="td_pr_gap50_raw")
    msg = handlers["write_file"]({"path": "docs/notes.md", "content": "hello"})
    assert msg == "Written docs/notes.md"
    assert (Path(str(tmp_path)) / "docs/notes.md").read_text(
        encoding="utf-8"
    ) == "hello"


def test_deploy_blocked_by_regression_gate_surfaces_blocked_message_and_no_write(
    tmp_path: object,
) -> None:
    role_name = "td_pr_gap50_regressed"
    try:
        collector = get_metrics_collector()
        bm = get_benchmark_manager()

        m_good = collector.start_run(role_name, trace_id=f"{role_name}-g1")
        m_good.verification_pct = 1.0
        good = bm.run_benchmark(role_name)
        bm.store_baseline(role_name, good)

        m_bad = collector.start_run(role_name, trace_id=f"{role_name}-b1")
        m_bad.verification_pct = 0.0
        m_bad.reflection_unsatisfied = 1

        handlers = make_fleet_apply_handlers(
            str(tmp_path), agent_name="td_pr_gap50_regressed"
        )
        msg = handlers["write_file"](
            {"path": f"roles/{role_name}.md", "content": "regressed content"}
        )
        assert "[BLOCKED]" in msg

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert not role_file.exists()

        history = get_prompt_registry().get_history(role_name)
        assert history[0].status == "approved"  # advanced but never deployed
    finally:
        _cleanup(role_name)
        _delete_benchmarks(role_name)


@pytest.mark.parametrize(
    "module_path,func_name,expected_agent_name",
    [
        # knowledge_curator's apply phase goes through its own
        # make_apply_handlers() wrapper, not make_fleet_apply_handlers
        # directly — introspect that wrapper instead.
        ("app.agents.knowledge_curator", "make_apply_handlers", "knowledge_curator"),
        ("app.agents.agent_debugger", "run_agent_debugger_apply", "agent_debugger"),
        (
            "app.agents.agent_performance_reviewer",
            "run_agent_performance_reviewer_apply",
            "agent_performance_reviewer",
        ),
        ("app.agents.quality_auditor", "run_quality_auditor_apply", "quality_auditor"),
    ],
)
def test_all_four_apply_phase_callers_pass_their_own_agent_name(
    module_path: str, func_name: str, expected_agent_name: str
) -> None:
    """Verify-real-callers guard: each of the 4 write-capable fleet agents'
    APPLY phase must pass its own agent_name into make_fleet_apply_handlers
    (not the default), so prompt_registry attribution (proposed_by/
    approved_by) is accurate — not just that the wiring exists somewhere."""
    import importlib

    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    assert func is not None, f"{func_name} not found in {module_path}"
    source = inspect.getsource(func)
    assert "make_fleet_apply_handlers" in source
    assert f'agent_name="{expected_agent_name}"' in source
