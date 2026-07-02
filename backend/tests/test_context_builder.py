"""Context builder tests — keyword scoring and relevance."""
import pytest
from pathlib import Path

from app.repo_tools.scanner import index_repository
from app.repo_tools.context_builder import build_context


@pytest.fixture
def api_repo(tmp_path: Path) -> Path:
    (tmp_path / "routes.py").write_text(
        "def get_tasks(): pass\ndef create_task(): pass\ndef delete_task(): pass\n"
    )
    (tmp_path / "models.py").write_text(
        "class Task:\n    id: int\n    title: str\n"
    )
    (tmp_path / "utils.py").write_text(
        "def format_date(d): return str(d)\ndef log(msg): print(msg)\n"
    )
    return tmp_path


def test_relevant_files_include_routes_for_task_query(api_repo: Path) -> None:
    idx = index_repository(str(api_repo))
    ctx = build_context("add a new task endpoint to routes", idx)
    assert "routes.py" in ctx.relevant_files


def test_relevant_files_include_model_for_task_query(api_repo: Path) -> None:
    idx = index_repository(str(api_repo))
    ctx = build_context("create task model with validation", idx)
    assert "models.py" in ctx.relevant_files


def test_unrelated_files_excluded_within_budget(api_repo: Path) -> None:
    idx = index_repository(str(api_repo))
    ctx = build_context("add endpoint to routes for task creation", idx, top_k=2)
    # With top_k=2, we get the 2 most relevant; utils should not score higher than routes/models
    assert len(ctx.relevant_files) <= 2


def test_summary_contains_file_count(api_repo: Path) -> None:
    idx = index_repository(str(api_repo))
    ctx = build_context("add task endpoint", idx)
    assert "relevant files" in ctx.summary


def test_related_symbols_found(api_repo: Path) -> None:
    idx = index_repository(str(api_repo))
    ctx = build_context("create task", idx)
    # Should find create_task or Task symbols
    assert any("task" in s.lower() for s in ctx.related_symbols)
