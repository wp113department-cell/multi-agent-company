"""Dispatcher routing tests — subtask type → correct agent selection."""

from __future__ import annotations

import pytest

from app.pipeline.dispatcher import get_agent_for_type, dispatch_subtask

# ---- Routing table tests (pure, no agents called) ----


def test_backend_routes_to_backend_dev() -> None:
    assert get_agent_for_type("backend") == "backend_dev"


def test_frontend_routes_to_frontend_dev() -> None:
    assert get_agent_for_type("frontend") == "frontend_dev"


def test_test_type_routes_to_qa() -> None:
    assert get_agent_for_type("test") == "qa"


def test_docs_routes_to_backend_dev() -> None:
    assert get_agent_for_type("docs") == "backend_dev"


def test_unknown_type_defaults_to_backend_dev() -> None:
    assert get_agent_for_type("unknown_type") == "backend_dev"
    assert get_agent_for_type("") == "backend_dev"


# ---- dispatch_subtask structural tests ----


@pytest.mark.asyncio
async def test_dispatch_backend_subtask_calls_backend_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dispatch_subtask with type=backend calls run_backend_dev."""
    called_with: dict[str, object] = {}

    def fake_run_backend_dev(
        task_id: int,
        subtask_id: int,
        plan: str,
        worktree_path: str,
        repo_path: object = None,
        **kw: object,
    ) -> tuple[list[str], None]:
        called_with["task_id"] = task_id
        called_with["subtask_id"] = subtask_id
        called_with["agent"] = "backend_dev"
        return ["app/api/foo.py"], None

    monkeypatch.setattr("app.agents.backend_dev.run_backend_dev", fake_run_backend_dev)
    # dispatcher imports lazily, so patch at the source
    import app.agents.backend_dev as backend_dev_mod

    monkeypatch.setattr(backend_dev_mod, "run_backend_dev", fake_run_backend_dev)

    result = await dispatch_subtask(
        task_id=1,
        subtask={"id": 10, "type": "backend", "description": "Add GET /users endpoint"},
        worktree_path="/tmp/wt-1",
        plan="Implement GET /users",
        repo_path=None,
    )

    assert result["agent"] == "backend_dev"
    assert result["error"] is None
    assert "app/api/foo.py" in result["files_changed"]


@pytest.mark.asyncio
async def test_dispatch_frontend_subtask_calls_frontend_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dispatch_subtask with type=frontend calls run_frontend_dev."""
    called: list[str] = []

    def fake_run_frontend_dev(
        task_id: int,
        subtask_id: int,
        plan: str,
        worktree_path: str,
        repo_path: object = None,
        **kw: object,
    ) -> tuple[list[str], None]:
        called.append("frontend_dev")
        return ["apps/web/components/Users.tsx"], None

    import app.agents.frontend_dev as frontend_dev_mod

    monkeypatch.setattr(frontend_dev_mod, "run_frontend_dev", fake_run_frontend_dev)

    result = await dispatch_subtask(
        task_id=2,
        subtask={"id": 20, "type": "frontend", "description": "Add Users component"},
        worktree_path="/tmp/wt-2",
        plan="Create Users component",
    )

    assert result["agent"] == "frontend_dev"
    assert "apps/web/components/Users.tsx" in result["files_changed"]


@pytest.mark.asyncio
async def test_dispatch_test_subtask_calls_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    """dispatch_subtask with type=test calls run_qa directly (no dev agent)."""
    from app.agents.qa import QAResult

    def fake_run_qa(
        task_id: int,
        subtask_id: int,
        files_changed: list[str],
        worktree_path: str,
        **kw: object,
    ) -> QAResult:
        return QAResult(
            status="passed",
            tests_run=10,
            tests_passed=10,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="All tests passed",
        )

    import app.agents.qa as qa_mod

    monkeypatch.setattr(qa_mod, "run_qa", fake_run_qa)

    result = await dispatch_subtask(
        task_id=3,
        subtask={"id": 30, "type": "test", "description": "Run test suite"},
        worktree_path="/tmp/wt-3",
        plan="Run tests",
    )

    assert result["agent"] == "qa"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_dispatch_test_subtask_qa_failed_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.qa import QAResult

    def fake_run_qa(
        task_id: int,
        subtask_id: int,
        files_changed: list[str],
        worktree_path: str,
        **kw: object,
    ) -> QAResult:
        return QAResult(
            status="failed",
            tests_run=5,
            tests_passed=3,
            tests_failed=2,
            typecheck_clean=False,
            lint_clean=True,
            errors=["mypy: Type error in foo.py"],
            summary="2 tests failed",
        )

    import app.agents.qa as qa_mod

    monkeypatch.setattr(qa_mod, "run_qa", fake_run_qa)

    result = await dispatch_subtask(
        task_id=4,
        subtask={"id": 40, "type": "test"},
        worktree_path="/tmp/wt-4",
        plan="Run tests",
    )

    assert result["error"] is not None
    assert result["agent"] == "qa"
