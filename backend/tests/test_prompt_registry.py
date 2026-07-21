"""Day 11 — prompt_registry.py: versioned role prompts with an approval
lifecycle (draft -> in_review -> approved -> deployed -> superseded) and
regression-gated deploy.

Every test uses a role_name prefixed td_pr_ that does not correspond to a real
production role, and cleans up both its DB rows and its roles/*.md file in a
try/finally — writing to the real roles/ directory is the whole point of this
module, so tests must not leave residue there.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.fleet.benchmark_manager import get_benchmark_manager
from app.fleet.metrics import get_metrics_collector
from app.fleet.prompt_registry import (
    InvalidTransition,
    PromptRegistry,
    _role_file_path,
    get_prompt_registry,
)
from app.fleet.regression_detector import DeploymentBlocked

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
                await session.execute(delete(PromptVersion).where(PromptVersion.role_name == role_name))
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
                await session.execute(delete(AgentBenchmark).where(AgentBenchmark.agent_name == agent_name))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_role_file_path_blocks_path_traversal() -> None:
    with pytest.raises(ValueError, match="resolves outside"):
        _role_file_path("../../etc/passwd")


def test_propose_creates_version_1_in_draft_status() -> None:
    role_name = "td_pr_propose"
    try:
        pr = PromptRegistry()
        v1 = pr.propose(role_name, "Version 1 content", proposed_by="tester")
        assert v1.version_number == 1
        assert v1.status == "draft"
        assert v1.parent_version_id is None
    finally:
        _cleanup(role_name)


def test_propose_is_a_no_op_when_content_matches_deployed() -> None:
    role_name = "td_pr_noop"
    try:
        pr = PromptRegistry()
        v1 = pr.propose(role_name, "Same content", proposed_by="tester")
        pr.submit_for_review(v1.id)
        pr.approve(v1.id, "human1")
        pr.deploy(v1.id)

        v2 = pr.propose(role_name, "Same content", proposed_by="tester")
        assert v2.id == v1.id  # returned the existing deployed row, not a new version
    finally:
        _cleanup(role_name)


def test_illegal_transition_raises_before_any_state_changes() -> None:
    role_name = "td_pr_illegal"
    try:
        pr = PromptRegistry()
        v1 = pr.propose(role_name, "content", proposed_by="tester")
        with pytest.raises(InvalidTransition):
            pr.approve(v1.id, "human1")  # draft -> approved is not a legal jump
        with pytest.raises(InvalidTransition):
            pr.deploy(v1.id)  # draft -> deployed is not a legal jump
    finally:
        _cleanup(role_name)


def test_full_lifecycle_deploy_writes_real_role_file() -> None:
    role_name = "td_pr_full_lifecycle"
    try:
        pr = PromptRegistry()
        v1 = pr.propose(role_name, "Deployed content v1", proposed_by="tester")
        pr.submit_for_review(v1.id)
        approved = pr.approve(v1.id, "human1")
        assert approved.status == "approved"
        assert approved.approved_by == "human1"

        deployed = pr.deploy(v1.id)
        assert deployed.status == "deployed"
        assert deployed.deployed_at is not None

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert role_file.read_text(encoding="utf-8") == "Deployed content v1"
        assert pr.get_deployed(role_name).id == v1.id
    finally:
        _cleanup(role_name)


def test_deploying_a_new_version_supersedes_the_prior_deployed_version() -> None:
    role_name = "td_pr_supersede"
    try:
        pr = PromptRegistry()
        v1 = pr.propose(role_name, "v1", proposed_by="tester")
        pr.submit_for_review(v1.id)
        pr.approve(v1.id, "human1")
        pr.deploy(v1.id)

        v2 = pr.propose(role_name, "v2", proposed_by="tester")
        pr.submit_for_review(v2.id)
        pr.approve(v2.id, "human1")
        pr.deploy(v2.id)

        history = pr.get_history(role_name)
        by_version = {h.version_number: h.status for h in history}
        assert by_version[1] == "superseded"
        assert by_version[2] == "deployed"

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert role_file.read_text(encoding="utf-8") == "v2"
    finally:
        _cleanup(role_name)


def test_rollback_restores_prior_superseded_version_content() -> None:
    role_name = "td_pr_rollback"
    try:
        pr = PromptRegistry()
        v1 = pr.propose(role_name, "original content", proposed_by="tester")
        pr.submit_for_review(v1.id)
        pr.approve(v1.id, "human1")
        pr.deploy(v1.id)

        v2 = pr.propose(role_name, "bad content", proposed_by="tester")
        pr.submit_for_review(v2.id)
        pr.approve(v2.id, "human1")
        pr.deploy(v2.id)

        restored = pr.rollback(role_name)
        assert restored.version_number == 1
        assert restored.status == "deployed"

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert role_file.read_text(encoding="utf-8") == "original content"

        history = pr.get_history(role_name)
        by_version = {h.version_number: h.status for h in history}
        assert by_version[1] == "deployed"
        assert by_version[2] == "superseded"
    finally:
        _cleanup(role_name)


def test_rollback_with_no_superseded_version_raises() -> None:
    role_name = "td_pr_rollback_none"
    try:
        with pytest.raises(ValueError, match="No superseded version"):
            PromptRegistry().rollback(role_name)
    finally:
        _cleanup(role_name)


def test_deploy_is_blocked_by_regression_detector() -> None:
    """deploy() looks up regression_detector.get_regression_detector() via a
    local import each call, so this seeds the REAL process-singleton
    MetricsCollector/BenchmarkManager (what get_regression_detector() actually
    wraps in production) rather than trying to monkeypatch a local import."""
    role_name = "td_pr_regression_gated"
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

        pr = PromptRegistry()
        v1 = pr.propose(role_name, "content", proposed_by="tester")
        pr.submit_for_review(v1.id)
        pr.approve(v1.id, "human1")

        with pytest.raises(DeploymentBlocked):
            pr.deploy(v1.id)

        # version must still be "approved", not silently flipped to deployed
        history = pr.get_history(role_name)
        assert history[0].status == "approved"

        role_file = _ROLES_DIR / f"{role_name}.md"
        assert not role_file.exists()  # never wrote the file
    finally:
        _cleanup(role_name)
        _delete_benchmarks(role_name)


def test_get_prompt_registry_returns_singleton() -> None:
    assert get_prompt_registry() is get_prompt_registry()
