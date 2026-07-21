"""Tests for Day 9 fleet self-improvement agents: contracts, role files, tools,
and the two-phase (SCAN autonomous / APPLY human-approved) execution model.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_BACKEND = Path(__file__).parent.parent
_ROLES_DIR = _BACKEND / "roles"

_DAY9_MODULES = [
    "app.agents.agent_performance_reviewer",
    "app.agents.agent_debugger",
    "app.agents.agent_advisor",
    "app.agents.knowledge_curator",
    "app.agents.quality_auditor",
]

_REQUIRED_CONTRACT_KEYS = [
    "name", "description", "allowed_tools", "input_types", "output_types",
    "side_effects", "permissions", "risk_level", "expected_verification", "dependencies",
]

_ROLE_SPECIFIC_SECTIONS = (
    "Non-Responsibilities", "Success Criteria", "Failure Conditions",
    "Output Contract", "Quality Gates", "Edge Cases", "Escalation",
)


def _load(module_name: str) -> Any:
    if module_name in sys.modules:
        return sys.modules[module_name]
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# AGENT_CONTRACT shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY9_MODULES)
def test_agent_contract_exists_and_complete(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "AGENT_CONTRACT")
    contract = mod.AGENT_CONTRACT
    for key in _REQUIRED_CONTRACT_KEYS:
        assert key in contract, f"{module_name} AGENT_CONTRACT missing '{key}'"
    assert len(contract["allowed_tools"]) > 0
    assert contract["risk_level"] in ("low", "medium", "high")


@pytest.mark.parametrize("module_name", _DAY9_MODULES)
def test_agent_contract_name_matches_module(module_name: str) -> None:
    mod = _load(module_name)
    short_name = module_name.split(".")[-1]
    assert mod.AGENT_CONTRACT["name"] == short_name


# ---------------------------------------------------------------------------
# Role files — inherits _GLOBAL_STANDARDS.md + 7 role-specific sections
# (same bar as every other agent, verified by test_day8_role_prompts.py's
# auto-discovery too; this file adds Day-9-specific coverage explicitly)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY9_MODULES)
def test_role_file_exists_and_complete(module_name: str) -> None:
    from app.agents.base import load_role

    short_name = module_name.split(".")[-1]
    role_path = _ROLES_DIR / f"{short_name}.md"
    assert role_path.exists(), f"missing role file for {short_name}"

    composed = load_role(short_name)
    assert "Global Agent Standards" in composed
    for section in _ROLE_SPECIFIC_SECTIONS:
        assert section in composed, f"{short_name}.md missing section '{section}'"


# ---------------------------------------------------------------------------
# VerificationConfig — non-empty, no dead enforce keys
# ---------------------------------------------------------------------------

_CFG_NAMES = ["_SCAN_CFG", "_APPLY_CFG"]


@pytest.mark.parametrize("module_name", _DAY9_MODULES)
def test_verification_configs_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    found_any = False
    for cfg_name in _CFG_NAMES:
        cfg = getattr(mod, cfg_name, None)
        if cfg is None:
            continue
        found_any = True
        assert cfg.set_by, f"{module_name}.{cfg_name}.set_by must not be empty"
        assert cfg.enforce_in_result, f"{module_name}.{cfg_name}.enforce_in_result must not be empty"
        # no dead enforce keys: every enforced verification key must be produced by set_by
        sb_values = set(cfg.set_by.values())
        for enforced_key in cfg.enforce_in_result.values():
            assert enforced_key in sb_values, (
                f"{module_name}.{cfg_name} enforces {enforced_key!r} but no tool in "
                f"set_by ever produces it"
            )
    assert found_any, f"{module_name} has neither _SCAN_CFG nor _APPLY_CFG"


def test_agent_advisor_has_no_apply_phase() -> None:
    """agent_advisor is scan-only by design (docs/DAY9_PLAN.md) — purely advisory,
    never writes code."""
    mod = _load("app.agents.agent_advisor")
    assert not hasattr(mod, "_APPLY_CFG")
    assert not hasattr(mod, "run_agent_advisor_apply")


# ---------------------------------------------------------------------------
# _register() + capability_registry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY9_MODULES)
def test_register_function_exists_and_registered(module_name: str) -> None:
    mod = _load(module_name)
    assert callable(mod._register)

    from app.fleet.capability_registry import get_capability_registry

    short_name = module_name.split(".")[-1]
    entry = get_capability_registry().get(short_name)
    assert entry is not None, f"{short_name} not in capability_registry"
    assert len(entry.capabilities) > 0


def test_day9_capability_tags_unique() -> None:
    from app.fleet.capability_registry import get_capability_registry

    reg = get_capability_registry()
    all_tags: dict[str, str] = {}
    for cap in reg.all():
        for tag in cap.capabilities:
            if tag in all_tags and all_tags[tag] != cap.name:
                pytest.fail(f"Duplicate capability tag {tag!r}: {all_tags[tag]!r} and {cap.name!r}")
            all_tags[tag] = cap.name


def test_all_5_agents_in_agent_models_json() -> None:
    import json

    path = _BACKEND / "app" / "fleet" / "agent_models.json"
    data = json.loads(path.read_text())
    for module_name in _DAY9_MODULES:
        short_name = module_name.split(".")[-1]
        assert short_name in data, f"{short_name} missing from agent_models.json"
        assert data[short_name]["tier"] == "sonnet"


# ---------------------------------------------------------------------------
# SCAN/APPLY run functions — mocked run_agent_graph
# ---------------------------------------------------------------------------

def _fake_state(**kwargs: Any) -> dict[str, Any]:
    return {
        "result": {"summary": "mocked"},
        "verification": {
            "metrics_read": True, "diagnosed": True, "history_read": True,
            "memory_searched": True, "scan_ran": True, "committed": True, "tests_run": True,
            "curated": True,
        },
        "submitted": True,
        "tokens_in": 10,
        "tokens_out": 20,
        **kwargs,
    }


@pytest.mark.parametrize("module_name,scan_fn", [
    ("app.agents.agent_performance_reviewer", "run_agent_performance_reviewer_scan"),
    ("app.agents.agent_debugger", "run_agent_debugger_scan"),
    ("app.agents.agent_advisor", "run_agent_advisor_scan"),
    ("app.agents.knowledge_curator", "run_knowledge_curator_scan"),
    ("app.agents.quality_auditor", "run_quality_auditor_scan"),
])
def test_scan_fn_returns_agent_result(module_name: str, scan_fn: str) -> None:
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, scan_fn)
    with patch(f"{module_name}.run_agent_graph", return_value=_fake_state()):
        result = fn(trace_id="test-trace")

    assert isinstance(result, AgentResult)
    assert result.status == "completed"


@pytest.mark.parametrize("module_name,scan_fn", [
    ("app.agents.agent_performance_reviewer", "run_agent_performance_reviewer_scan"),
    ("app.agents.agent_debugger", "run_agent_debugger_scan"),
    ("app.agents.agent_advisor", "run_agent_advisor_scan"),
    ("app.agents.knowledge_curator", "run_knowledge_curator_scan"),
    ("app.agents.quality_auditor", "run_quality_auditor_scan"),
])
def test_scan_fn_handles_empty_scan(module_name: str, scan_fn: str) -> None:
    """A scan that finds nothing (submitted=False) is a normal, successful outcome —
    not an error — per every Day 9 role prompt's explicit instruction."""
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, scan_fn)
    with patch(f"{module_name}.run_agent_graph", return_value=_fake_state(submitted=False)):
        result = fn(trace_id="test-trace")

    assert isinstance(result, AgentResult)
    assert result.status == "completed"


@pytest.mark.parametrize("module_name,apply_fn", [
    ("app.agents.agent_performance_reviewer", "run_agent_performance_reviewer_apply"),
    ("app.agents.agent_debugger", "run_agent_debugger_apply"),
    ("app.agents.knowledge_curator", "run_knowledge_curator_apply"),
    ("app.agents.quality_auditor", "run_quality_auditor_apply"),
])
def test_apply_fn_returns_agent_result(module_name: str, apply_fn: str) -> None:
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, apply_fn)
    with patch(f"{module_name}.run_agent_graph", return_value=_fake_state()):
        result = fn(request_id=1, description="approved fix", trace_id="test-trace")

    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert result.verified is True


@pytest.mark.parametrize("module_name,apply_fn", [
    ("app.agents.agent_performance_reviewer", "run_agent_performance_reviewer_apply"),
    ("app.agents.agent_debugger", "run_agent_debugger_apply"),
    ("app.agents.knowledge_curator", "run_knowledge_curator_apply"),
    ("app.agents.quality_auditor", "run_quality_auditor_apply"),
])
def test_apply_fn_blocked_when_not_verified(module_name: str, apply_fn: str) -> None:
    """If the agent never actually committed/curated (verification key false), the
    apply phase must report status=blocked, never a false 'completed'."""
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, apply_fn)
    unverified = _fake_state()
    unverified["verification"] = {k: False for k in unverified["verification"]}
    with patch(f"{module_name}.run_agent_graph", return_value=unverified):
        result = fn(request_id=1, description="approved fix", trace_id="test-trace")

    assert isinstance(result, AgentResult)
    assert result.status == "blocked"
    assert result.verified is False


# ---------------------------------------------------------------------------
# New shared tools — fleet_metrics_read / audit_log_read (in-process, no DB)
# ---------------------------------------------------------------------------

def test_fleet_metrics_read_empty() -> None:
    from app.agents.tools import fleet_metrics_read

    out = fleet_metrics_read({"agent_name": "nonexistent_agent_xyz"})
    assert "no recorded runs" in out


def test_fleet_metrics_read_with_data() -> None:
    from app.agents.tools import fleet_metrics_read
    from app.fleet.metrics import get_metrics_collector

    m = get_metrics_collector().start_run("test_metrics_agent")
    m.execution_time_ms = 123.0
    m.finish("completed")

    out = fleet_metrics_read({"agent_name": "test_metrics_agent"})
    assert "test_metrics_agent" in out or "runs considered" in out


def test_audit_log_read_filters_by_agent() -> None:
    from app.agents.tools import audit_log_read
    from app.fleet.audit_log import get_audit_log

    get_audit_log().append("test_action", "agent_a_xyz", "did a thing")
    get_audit_log().append("test_action", "agent_b_xyz", "did another thing")

    out = audit_log_read({"agent_name": "agent_a_xyz", "n": 10})
    assert "agent_a_xyz" in out
    assert "agent_b_xyz" not in out


# ---------------------------------------------------------------------------
# New shared tools — DB-backed (real DB, matches this project's existing
# convention of testing against the live dev Postgres; cleans up after itself)
# ---------------------------------------------------------------------------

async def _with_isolated_session(coro_fn: Any) -> Any:
    """Run coro_fn(session) against a fresh, disposed-after-use engine — never the
    shared app.db.session singleton. Mirrors app.agents.tools._new_isolated_db_engine:
    repeated asyncio.run() calls in the same process (as pytest does across test
    functions) bind the shared engine's pool to whichever loop touched it first,
    so reusing it here would hit the exact 'attached to a different loop' bug this
    module's own tests exist to catch in the tools themselves."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.agents.tools import _new_isolated_db_engine

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await coro_fn(session)
    finally:
        await engine.dispose()


async def _cleanup_enhancement_requests(ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.db.models import EnhancementRequest

    if not ids:
        return

    async def _do(session: Any) -> None:
        await session.execute(delete(EnhancementRequest).where(EnhancementRequest.id.in_(ids)))
        await session.commit()

    await _with_isolated_session(_do)


def test_submit_enhancement_request_writes_row() -> None:
    from app.agents.tools import make_submit_enhancement_request_handler
    from app.db.models import EnhancementRequest

    handler = make_submit_enhancement_request_handler("test_agent_xyz", trace_id="pytest-trace")
    result = handler({
        "title": "pytest title", "description": "pytest description",
        "category": "bug", "priority": "low", "evidence": {"k": "v"},
    })
    assert "filed for human review" in result

    async def _fetch(session: Any) -> EnhancementRequest | None:
        from sqlalchemy import select
        r = await session.execute(
            select(EnhancementRequest).where(EnhancementRequest.agent_name == "test_agent_xyz")
        )
        return r.scalars().first()

    row = asyncio.run(_with_isolated_session(_fetch))
    try:
        assert row is not None
        assert row.status == "pending"
        assert row.title == "pytest title"
    finally:
        if row is not None:
            asyncio.run(_cleanup_enhancement_requests([row.id]))


def test_submit_enhancement_request_repeated_calls_same_process() -> None:
    """Regression test for the asyncio-loop-reuse bug found 2026-07-21: calling any
    of the Day 9 DB tools more than once in the same process must not raise
    'Future attached to a different loop'."""
    from app.agents.tools import make_submit_enhancement_request_handler

    handler = make_submit_enhancement_request_handler("test_agent_xyz2", trace_id="pytest-trace-2")
    r1 = handler({"title": "a", "description": "a", "category": "bug", "priority": "low", "evidence": {}})
    r2 = handler({"title": "b", "description": "b", "category": "bug", "priority": "low", "evidence": {}})

    import re
    ids = [int(m.group(1)) for r in (r1, r2) if (m := re.search(r"#(\d+)", r))]
    try:
        assert "[ERROR]" not in r1
        assert "[ERROR]" not in r2
    finally:
        asyncio.run(_cleanup_enhancement_requests(ids))


def test_memory_curate_write_updates_row() -> None:
    from app.agents.tools import memory_curate_write
    from app.db.models import MemoryEmbedding

    async def _seed(session: Any) -> int:
        row = MemoryEmbedding(
            task_id="pytest-task", outcome="completed", category="task",
            description="d", summary="s", files_changed=[],
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return int(row.id)

    async def _fetch_summary(session: Any, row_id: int) -> str:
        row = await session.get(MemoryEmbedding, row_id)
        assert row is not None
        return row.summary

    async def _delete(session: Any, row_id: int) -> None:
        row = await session.get(MemoryEmbedding, row_id)
        if row is not None:
            await session.delete(row)
            await session.commit()

    row_id = asyncio.run(_with_isolated_session(_seed))
    try:
        result = memory_curate_write({"id": row_id, "note": "pytest curated"})
        assert "updated" in result
        summary = asyncio.run(_with_isolated_session(lambda s: _fetch_summary(s, row_id)))
        assert "pytest curated" in summary
    finally:
        asyncio.run(_with_isolated_session(lambda s: _delete(s, row_id)))


def test_memory_curate_write_missing_id() -> None:
    from app.agents.tools import memory_curate_write

    result = memory_curate_write({"id": 999999999, "note": "x"})
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# git_commit_change — isolated scratch repo, never touches the real project
# ---------------------------------------------------------------------------

def test_git_commit_change_stages_only_named_files(tmp_path: Path) -> None:
    import subprocess

    from app.agents.tools import make_git_commit_change_handler

    repo = tmp_path / "scratch_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\n")
    (repo / "b.txt").write_text("world\n")
    subprocess.run(["git", "add", "a.txt", "b.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)

    (repo / "a.txt").write_text("hello\nchanged\n")
    (repo / "b.txt").write_text("world\nchanged\n")

    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": ["a.txt"], "message": "update a only"})
    assert "Committed 1 file" in result

    status = subprocess.run(["git", "status", "--short"], cwd=repo, capture_output=True, text=True)
    assert "b.txt" in status.stdout  # still unstaged/modified
    assert "a.txt" not in status.stdout  # committed, no longer dirty


def test_git_commit_change_blocks_protected_path(tmp_path: Path) -> None:
    from app.agents.tools import make_git_commit_change_handler

    handler = make_git_commit_change_handler(str(tmp_path))
    result = handler({"files": [".env"], "message": "should be blocked"})
    assert "[POLICY DENIED]" in result


def test_git_commit_change_requires_explicit_files() -> None:
    from app.agents.tools import make_git_commit_change_handler

    handler = make_git_commit_change_handler(".")
    result = handler({"files": [], "message": "no files"})
    assert "[ERROR]" in result
