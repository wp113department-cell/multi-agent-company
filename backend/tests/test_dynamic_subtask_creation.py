"""plan14 follow-on #2 — Dynamic Subtask Creation.

The highest-risk item in the backlog per its own audit ("genuine risk of
destabilizing an existing, working invariant if rushed"): subtasks were
created exactly once, up front, and app.agents.manager.run_manager()
computed its dispatch waves once, assuming a static, complete list. This
covers, with real execution:
  1. app.pipeline.dynamic_subtasks.validate_and_build_subtask — pure policy
     validation (allow-matrix, depth cap, count cap, duplicate-work).
  2. reserve_files_for_proposal — real Postgres file-lock reservation,
     including the "don't self-conflict against this epic's own already-
     held files" case.
  3. integrate_proposals — the orchestration combining both.
  4. app.agents.tools.make_propose_subtask_handler — the tool handler's own
     shape validation.
  5. End-to-end through app.agents.manager.run_manager(): the default
     (feature disabled) path is unchanged, and a real proposal gets
     integrated and dispatched in a LATER wave when enabled — including the
     halt-boundary invariant (a proposal made in a wave that triggers an
     epic halt must never be scheduled).
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import EpicFileLock
from app.pipeline.dynamic_subtasks import (
    integrate_proposals,
    reserve_files_for_proposal,
    validate_and_build_subtask,
)
from app.tools.agents.propose_subtask import make_propose_subtask_handler


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _proposal(**overrides: Any) -> dict[str, Any]:
    base = {
        "type": "backend",
        "title": "Add missing validation",
        "description": "Validate the new field before saving.",
        "files_to_edit": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    settings = get_settings()
    assert settings.dynamic_subtask_creation_enabled_agents == {}
    assert settings.dynamic_subtask_max_per_epic == 5
    assert settings.dynamic_subtask_max_depth == 2
    assert settings.dynamic_subtask_allowed_matrix == {
        "backend_dev": ["backend", "test"],
        "frontend_dev": ["frontend", "test"],
    }


# ---------------------------------------------------------------------------
# validate_and_build_subtask — pure policy validation
# ---------------------------------------------------------------------------


def test_valid_proposal_is_built() -> None:
    built, reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert reason == ""
    assert built is not None
    assert built["type"] == "backend"
    assert built["depends_on"] == [0]
    assert built["dynamically_created"] is True
    assert built["proposed_by"] == "backend_dev"


def test_invalid_type_rejected() -> None:
    built, reason = validate_and_build_subtask(
        _proposal(type="database"),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "invalid subtask type" in reason


def test_empty_title_rejected() -> None:
    built, reason = validate_and_build_subtask(
        _proposal(title=""),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "title" in reason


def test_non_list_files_to_edit_rejected() -> None:
    built, reason = validate_and_build_subtask(
        _proposal(files_to_edit="a.py"),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "files_to_edit" in reason


def test_disallowed_type_for_proposing_agent_rejected() -> None:
    """backend_dev's allow-matrix entry is ["backend", "test"] by default —
    proposing a frontend subtask must be rejected."""
    built, reason = validate_and_build_subtask(
        _proposal(type="frontend"),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "not allowed to propose" in reason


def test_unknown_proposing_agent_rejected() -> None:
    """An agent absent from dynamic_subtask_allowed_matrix entirely (empty
    allow-list) must be rejected, not silently permitted."""
    built, reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="some_unregistered_agent",
    )
    assert built is None
    assert "not allowed to propose" in reason


def test_count_cap_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "dynamic_subtask_max_per_epic", 2)
    built, reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=2,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "dynamic_subtask_max_per_epic" in reason


def test_count_at_cap_minus_one_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "dynamic_subtask_max_per_epic", 2)
    built, reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=1,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is not None
    assert reason == ""


def test_depth_cap_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "dynamic_subtask_max_depth", 1)
    # parent is already at depth 1 -> child would be depth 2, exceeding cap
    built, reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 1},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "spawn depth" in reason


def test_depth_at_cap_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "dynamic_subtask_max_depth", 1)
    built, reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is not None
    assert reason == ""


def test_duplicate_title_rejected() -> None:
    built, reason = validate_and_build_subtask(
        _proposal(title="Existing Subtask"),
        subtasks=[{"title": "existing subtask", "files_to_edit": []}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "duplicate" in reason


def test_duplicate_files_to_edit_rejected() -> None:
    built, reason = validate_and_build_subtask(
        _proposal(title="A different title", files_to_edit=["a.py", "b.py"]),
        subtasks=[{"title": "unrelated", "files_to_edit": ["a.py", "b.py"]}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is None
    assert "duplicate" in reason


def test_no_dependency_cycle_possible_by_construction() -> None:
    """A proposal can only ever reference its own (already-existing) parent
    index — never a forward or self reference — so a dependency cycle is
    structurally impossible, not something that needs runtime detection."""
    built, _reason = validate_and_build_subtask(
        _proposal(),
        subtasks=[{"title": "original"}],
        spawn_depth={0: 0},
        dynamic_count_so_far=0,
        parent_idx=0,
        parent_agent_name="backend_dev",
    )
    assert built is not None
    assert built["depends_on"] == [0]


# ---------------------------------------------------------------------------
# reserve_files_for_proposal — real Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_files_for_proposal_succeeds_for_new_files() -> None:
    engine = _engine()
    epic_id = f"epic-dst-{uuid.uuid4().hex[:8]}"
    file_path = f"dst_test_{uuid.uuid4().hex[:8]}.py"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await reserve_files_for_proposal([file_path], epic_id, session)
            await session.commit()
            assert result is None
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(EpicFileLock).where(EpicFileLock.epic_id == epic_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_files_for_proposal_skips_already_epic_held_files() -> None:
    """Re-passing a file this SAME epic already holds must NOT self-conflict
    against reserve_epic_files()'s file_path-only unique constraint."""
    engine = _engine()
    epic_id = f"epic-dst-{uuid.uuid4().hex[:8]}"
    file_path = f"dst_test_{uuid.uuid4().hex[:8]}.py"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            first = await reserve_files_for_proposal([file_path], epic_id, session)
            await session.commit()
            assert first is None

            second = await reserve_files_for_proposal([file_path], epic_id, session)
            await session.commit()
            assert second is None, "re-reserving an already-held file must be a no-op"
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(EpicFileLock).where(EpicFileLock.epic_id == epic_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_files_for_proposal_conflicts_with_another_epic() -> None:
    engine = _engine()
    epic_a = f"epic-dst-a-{uuid.uuid4().hex[:8]}"
    epic_b = f"epic-dst-b-{uuid.uuid4().hex[:8]}"
    file_path = f"dst_test_{uuid.uuid4().hex[:8]}.py"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            first = await reserve_files_for_proposal([file_path], epic_a, session)
            await session.commit()
            assert first is None

            second = await reserve_files_for_proposal([file_path], epic_b, session)
            await session.commit()
            assert second is not None
            assert "conflict" in second.lower()
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(EpicFileLock).where(EpicFileLock.epic_id.in_([epic_a, epic_b]))
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_files_for_proposal_empty_list_is_noop() -> None:
    engine = _engine()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await reserve_files_for_proposal([], "some-epic", session)
        assert result is None
    await engine.dispose()


# ---------------------------------------------------------------------------
# integrate_proposals — orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integrate_proposals_appends_valid_proposal() -> None:
    subtasks: list[dict[str, Any]] = [{"title": "original", "files_to_edit": []}]
    spawn_depth = {0: 0}
    proposal = _proposal()
    proposal["_parent_subtask_idx"] = 0

    new_indices, new_count = await integrate_proposals(
        [proposal],
        subtasks=subtasks,
        spawn_depth=spawn_depth,
        dynamic_count=0,
        epic_id=None,
        db=None,
        parent_agent_names={0: "backend_dev"},
    )
    assert new_indices == [1]
    assert new_count == 1
    assert len(subtasks) == 2
    assert subtasks[1]["title"] == proposal["title"]
    assert subtasks[1]["id"] == 2
    assert spawn_depth[1] == 1


@pytest.mark.asyncio
async def test_integrate_proposals_rejects_invalid_parent_idx() -> None:
    subtasks: list[dict[str, Any]] = [{"title": "original", "files_to_edit": []}]
    proposal = _proposal()
    proposal["_parent_subtask_idx"] = 99  # out of range

    new_indices, new_count = await integrate_proposals(
        [proposal],
        subtasks=subtasks,
        spawn_depth={0: 0},
        dynamic_count=0,
        epic_id=None,
        db=None,
        parent_agent_names={0: "backend_dev"},
    )
    assert new_indices == []
    assert new_count == 0
    assert len(subtasks) == 1


@pytest.mark.asyncio
async def test_integrate_proposals_rejects_when_files_declared_but_no_db() -> None:
    subtasks: list[dict[str, Any]] = [{"title": "original", "files_to_edit": []}]
    proposal = _proposal(files_to_edit=["a.py"])
    proposal["_parent_subtask_idx"] = 0

    new_indices, new_count = await integrate_proposals(
        [proposal],
        subtasks=subtasks,
        spawn_depth={0: 0},
        dynamic_count=0,
        epic_id=None,  # no epic_id -> cannot reserve
        db=None,
        parent_agent_names={0: "backend_dev"},
    )
    assert new_indices == []
    assert new_count == 0


@pytest.mark.asyncio
async def test_integrate_proposals_accepts_no_files_declared_without_db() -> None:
    """A proposal with an empty files_to_edit needs no lock at all, so a
    missing db/epic_id must not block it."""
    subtasks: list[dict[str, Any]] = [{"title": "original", "files_to_edit": []}]
    proposal = _proposal(files_to_edit=[])
    proposal["_parent_subtask_idx"] = 0

    new_indices, new_count = await integrate_proposals(
        [proposal],
        subtasks=subtasks,
        spawn_depth={0: 0},
        dynamic_count=0,
        epic_id=None,
        db=None,
        parent_agent_names={0: "backend_dev"},
    )
    assert new_indices == [1]
    assert new_count == 1


@pytest.mark.asyncio
async def test_integrate_proposals_reserves_real_files_via_db() -> None:
    engine = _engine()
    epic_id = f"epic-dst-{uuid.uuid4().hex[:8]}"
    file_path = f"dst_test_{uuid.uuid4().hex[:8]}.py"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            subtasks: list[dict[str, Any]] = [
                {"title": "original", "files_to_edit": []}
            ]
            proposal = _proposal(files_to_edit=[file_path])
            proposal["_parent_subtask_idx"] = 0

            new_indices, new_count = await integrate_proposals(
                [proposal],
                subtasks=subtasks,
                spawn_depth={0: 0},
                dynamic_count=0,
                epic_id=epic_id,
                db=session,
                parent_agent_names={0: "backend_dev"},
            )
            assert new_indices == [1]
            assert new_count == 1

            result = await session.execute(
                select(EpicFileLock).where(EpicFileLock.epic_id == epic_id)
            )
            locked = {row.file_path for row in result.scalars().all()}
            assert file_path in locked
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(EpicFileLock).where(EpicFileLock.epic_id == epic_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_integrate_proposals_count_cap_applies_within_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two proposals in the SAME batch, cap=1 — only the first should be
    accepted; dynamic_count must be threaded correctly across iterations
    within one integrate_proposals() call, not just across calls."""
    settings = get_settings()
    monkeypatch.setattr(settings, "dynamic_subtask_max_per_epic", 1)

    subtasks: list[dict[str, Any]] = [{"title": "original", "files_to_edit": []}]
    p1 = _proposal(title="first")
    p1["_parent_subtask_idx"] = 0
    p2 = _proposal(title="second")
    p2["_parent_subtask_idx"] = 0

    new_indices, new_count = await integrate_proposals(
        [p1, p2],
        subtasks=subtasks,
        spawn_depth={0: 0},
        dynamic_count=0,
        epic_id=None,
        db=None,
        parent_agent_names={0: "backend_dev"},
    )
    assert new_indices == [1]
    assert new_count == 1
    assert len(subtasks) == 2


# ---------------------------------------------------------------------------
# propose_subtask tool handler — shape validation
# ---------------------------------------------------------------------------


def test_handler_appends_valid_proposal_to_sink() -> None:
    sink: list[dict[str, Any]] = []
    handler = make_propose_subtask_handler(sink)
    result = handler(
        {
            "type": "backend",
            "title": "Add rate limiting",
            "description": "Add rate limiting to the new endpoint.",
            "reason": "Discovered the endpoint has no rate limiting.",
        }
    )
    assert "recorded" in result.lower()
    assert len(sink) == 1
    assert sink[0]["title"] == "Add rate limiting"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "invalid_type"),
        ("title", ""),
        ("description", ""),
        ("reason", ""),
    ],
)
def test_handler_rejects_missing_or_invalid_required_fields(
    field: str, value: str
) -> None:
    sink: list[dict[str, Any]] = []
    handler = make_propose_subtask_handler(sink)
    inp = {
        "type": "backend",
        "title": "Add rate limiting",
        "description": "Add rate limiting to the new endpoint.",
        "reason": "Discovered the endpoint has no rate limiting.",
    }
    inp[field] = value
    result = handler(inp)
    assert result.startswith("[ERROR]")
    assert sink == []


def test_handler_rejects_non_list_files_to_edit() -> None:
    sink: list[dict[str, Any]] = []
    handler = make_propose_subtask_handler(sink)
    result = handler(
        {
            "type": "backend",
            "title": "x",
            "description": "y",
            "reason": "z",
            "files_to_edit": "not_a_list.py",
        }
    )
    assert result.startswith("[ERROR]")
    assert sink == []


# ---------------------------------------------------------------------------
# End-to-end through run_manager() — real git worktree, mocked dev/qa/
# reviewer (same convention tests/test_gap11_14_fleet_manager_dispatch.py
# already established for this exact function).
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


def _init_repo_with_worktree(tmp_path: Path, task_id: int) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "test@test.com"], cwd=repo)
    _run_git(["config", "user.name", "Test User"], cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _run_git(["add", "README.md"], cwd=repo)
    _run_git(["commit", "-q", "-m", "initial commit"], cwd=repo)

    branch = f"agent/task-{task_id}"
    worktree = tmp_path / f"wt-{task_id}"
    _run_git(["worktree", "add", "-q", "-b", branch, str(worktree)], cwd=repo)
    return repo, worktree


def _passing_qa() -> Any:
    from app.agents.qa import QAResult

    return QAResult(
        status="passed",
        tests_run=1,
        tests_passed=1,
        tests_failed=0,
        typecheck_clean=True,
        lint_clean=True,
        summary="ok",
        tokens_in=20,
        tokens_out=10,
    )


def _approved_review() -> Any:
    from app.agents.reviewer import ReviewResult

    return ReviewResult(verdict="approved", summary="ok", tokens_in=15, tokens_out=5)


def test_feature_disabled_by_default_never_wires_the_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dynamic_subtask_creation_enabled_agents is {} by default — the real
    regression proof: run_backend_dev must be called with
    subtask_proposal_sink=None, exactly as it always was before this
    feature existed."""
    from app.agents.manager import run_manager

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_501
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    with (
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.agents.qa.run_qa", return_value=_passing_qa()),
        patch("app.agents.reviewer.run_reviewer", return_value=_approved_review()),
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        mock_backend_dev.return_value = (["feature.py"], None, 100, 50)

        asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[{"id": 1, "type": "backend", "title": "Add feature"}],
                worktree_path=str(worktree),
                plan="Add a feature",
                repo_path=str(repo),
            )
        )

    _, kwargs = mock_backend_dev.call_args
    assert kwargs.get("subtask_proposal_sink") is None


def test_proposed_subtask_is_integrated_and_dispatched_in_a_later_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real end-to-end property: an agent's propose_subtask call
    actually results in a NEW subtask being dispatched (dev->QA->review)
    within the SAME run_manager() call, after the wave that proposed it."""
    from app.agents.manager import run_manager

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))
    monkeypatch.setattr(
        get_settings(),
        "dynamic_subtask_creation_enabled_agents",
        {"backend_dev": True},
    )

    task_id = 999_502
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    call_count = 0

    def _backend_dev_side_effect(**kwargs: Any) -> tuple[list[str], None, int, int]:
        nonlocal call_count
        call_count += 1
        sink = kwargs.get("subtask_proposal_sink")
        # Only the FIRST (original) subtask proposes — the dynamically
        # created one must not also propose, or this would loop forever
        # under a real LLM; here we just don't append on the second call.
        if sink is not None and call_count == 1:
            sink.append(
                {
                    "type": "backend",
                    "title": "Follow-up: add missing test",
                    "description": "Add a test for the new feature.",
                    "files_to_edit": [],
                }
            )
        return ([f"feature_{call_count}.py"], None, 100, 50)

    with (
        patch(
            "app.agents.backend_dev.run_backend_dev",
            side_effect=_backend_dev_side_effect,
        ) as mock_backend_dev,
        patch("app.agents.qa.run_qa", return_value=_passing_qa()),
        patch("app.agents.reviewer.run_reviewer", return_value=_approved_review()),
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[{"id": 1, "type": "backend", "title": "Add feature"}],
                worktree_path=str(worktree),
                plan="Add a feature",
                repo_path=str(repo),
            )
        )

    assert (
        mock_backend_dev.call_count == 2
    ), "the dynamically-proposed subtask must have been dispatched too"
    assert len(result["results"]) == 2
    assert result["dynamic_subtasks_created"] == 1
    titles = {r["type"] for r in result["results"]}
    assert titles == {"backend"}


def test_halted_epic_never_dispatches_a_pending_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proposal made by a subtask in the SAME wave where the epic halts
    (blocked_count >= max_epic_failures) must never be scheduled — matching
    the pre-existing 'stop before starting the next wave' halt semantics."""
    from app.agents.manager import run_manager

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))
    monkeypatch.setattr(
        get_settings(),
        "dynamic_subtask_creation_enabled_agents",
        {"backend_dev": True},
    )
    monkeypatch.setattr(get_settings(), "manager_max_epic_failures", 1)
    monkeypatch.setattr(get_settings(), "manager_max_subtask_retries", 1)

    task_id = 999_503
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    def _backend_dev_side_effect(**kwargs: Any) -> tuple[list[str], str, int, int]:
        sink = kwargs.get("subtask_proposal_sink")
        if sink is not None:
            sink.append(
                {
                    "type": "backend",
                    "title": "Should never run",
                    "description": "x",
                    "files_to_edit": [],
                }
            )
        # Dev agent itself fails -> subtask ends up blocked -> epic halts
        # (max_epic_failures=1) in the SAME wave the proposal was made.
        return ([], "simulated dev failure", 10, 5)

    with (
        patch(
            "app.agents.backend_dev.run_backend_dev",
            side_effect=_backend_dev_side_effect,
        ) as mock_backend_dev,
        patch("app.agents.qa.run_qa", return_value=_passing_qa()),
        patch("app.agents.reviewer.run_reviewer", return_value=_approved_review()),
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[{"id": 1, "type": "backend", "title": "Add feature"}],
                worktree_path=str(worktree),
                plan="Add a feature",
                repo_path=str(repo),
            )
        )

    assert result["status"] == "halted"
    assert (
        mock_backend_dev.call_count == 1
    ), "the halt must prevent the proposed follow-up from ever dispatching"
    assert result["dynamic_subtasks_created"] == 0


# ---------------------------------------------------------------------------
# tool_enhance.md productionization pass, tool #7 (2026-08-16) — the real
# gap this closes: config.py's dynamic_subtask_allowed_matrix already
# listed "frontend_dev": ["frontend", "test"] as real, intended policy,
# and app/agents/manager.py's own comment explicitly named frontend_dev
# wiring as pending ("a trivial, identical-shape follow-up") — never
# actually done until now. Mirrors the two backend_dev tests immediately
# above exactly, proving frontend_dev genuinely got the same real
# capability, not just a config/schema entry with no working code behind
# it.
# ---------------------------------------------------------------------------


def test_frontend_dev_feature_disabled_by_default_never_wires_the_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.manager import run_manager

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_504
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    with (
        patch("app.agents.frontend_dev.run_frontend_dev") as mock_frontend_dev,
        patch("app.agents.qa.run_qa", return_value=_passing_qa()),
        patch("app.agents.reviewer.run_reviewer", return_value=_approved_review()),
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        mock_frontend_dev.return_value = (["Component.tsx"], None, 100, 50)

        asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[{"id": 1, "type": "frontend", "title": "Add component"}],
                worktree_path=str(worktree),
                plan="Add a component",
                repo_path=str(repo),
            )
        )

    _, kwargs = mock_frontend_dev.call_args
    assert kwargs.get("subtask_proposal_sink") is None


def test_frontend_dev_proposed_subtask_is_integrated_and_dispatched_in_a_later_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.manager import run_manager

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))
    monkeypatch.setattr(
        get_settings(),
        "dynamic_subtask_creation_enabled_agents",
        {"frontend_dev": True},
    )

    task_id = 999_505
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    call_count = 0

    def _frontend_dev_side_effect(**kwargs: Any) -> tuple[list[str], None, int, int]:
        nonlocal call_count
        call_count += 1
        sink = kwargs.get("subtask_proposal_sink")
        if sink is not None and call_count == 1:
            sink.append(
                {
                    "type": "frontend",
                    "title": "Follow-up: add missing test",
                    "description": "Add a test for the new component.",
                    "files_to_edit": [],
                }
            )
        return ([f"Component_{call_count}.tsx"], None, 100, 50)

    with (
        patch(
            "app.agents.frontend_dev.run_frontend_dev",
            side_effect=_frontend_dev_side_effect,
        ) as mock_frontend_dev,
        patch("app.agents.qa.run_qa", return_value=_passing_qa()),
        patch("app.agents.reviewer.run_reviewer", return_value=_approved_review()),
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[{"id": 1, "type": "frontend", "title": "Add component"}],
                worktree_path=str(worktree),
                plan="Add a component",
                repo_path=str(repo),
            )
        )

    assert (
        mock_frontend_dev.call_count == 2
    ), "the dynamically-proposed subtask must have been dispatched too"
    assert len(result["results"]) == 2
    assert result["dynamic_subtasks_created"] == 1
    titles = {r["type"] for r in result["results"]}
    assert titles == {"frontend"}
