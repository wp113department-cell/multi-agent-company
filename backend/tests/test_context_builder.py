"""Context builder tests — keyword scoring and relevance."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.repo_tools.scanner import index_repository
from app.repo_tools.context_builder import build_context


@pytest.fixture
def api_repo(tmp_path: Path) -> Path:
    (tmp_path / "routes.py").write_text(
        "def get_tasks(): pass\ndef create_task(): pass\ndef delete_task(): pass\n"
    )
    (tmp_path / "models.py").write_text("class Task:\n    id: int\n    title: str\n")
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


# ---------------------------------------------------------------------------
# Gap-closure (2026-07-23): build_context() used to derive dependency_chain/
# call_graph_edges from scanner.py's file-level import-graph heuristic even
# after a real, function-level cross-file call graph
# (app/repo_tools/cross_file_graph.py) was built and persisted to the DB —
# the DB-writing half of that gap-closure was done, but the runtime-
# consumption half (this function, what PM/Architect agents actually see)
# was not. Verifies the real engine is now what's actually used.
# ---------------------------------------------------------------------------


@pytest.fixture
def cross_file_call_repo(tmp_path: Path) -> Path:
    """Mirrors cross_file_graph.py's own test fixture — a real, known
    cross-file call: calculator.py's Calculator.sum() calls math_utils.py's
    add(). No import-line substring match would exist for this without
    real call resolution (the old heuristic only matched by module stem
    appearing in an import statement, which happens to also work here —
    the distinguishing test below is what actually proves which engine ran)."""
    (tmp_path / "math_utils.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n"
    )
    (tmp_path / "calculator.py").write_text(
        "from math_utils import add\n\n"
        "class Calculator:\n"
        "    def sum(self, a: int, b: int) -> int:\n"
        "        return add(a, b)\n"
    )
    return tmp_path


def test_dependency_chain_reflects_the_real_cross_file_call_graph(
    cross_file_call_repo: Path,
) -> None:
    idx = index_repository(str(cross_file_call_repo))
    ctx = build_context("compute a sum with the calculator", idx, use_cache=False)

    assert "calculator.py" in ctx.relevant_files
    assert "math_utils.py" in ctx.dependency_chain
    assert "math_utils.py" in ctx.call_graph_edges.get("calculator.py", [])

    with patch("app.repo_tools.context_builder.build_cross_file_graph") as mock_build:
        from app.repo_tools.cross_file_graph import CrossFileGraphResult

        mock_build.return_value = CrossFileGraphResult(call_edges=[], file_rank={})
        ctx2 = build_context("compute a sum with the calculator", idx, use_cache=False)

    mock_build.assert_called_once_with(idx)
    # With the real engine mocked out to return zero edges, the dependency
    # chain must come up empty — proving it's genuinely sourced from
    # build_cross_file_graph(), not silently falling back to the old
    # import-graph heuristic if this call were ever removed by mistake.
    assert ctx2.dependency_chain == []


def test_pagerank_boost_never_promotes_a_zero_score_file(
    cross_file_call_repo: Path,
) -> None:
    """The rank boost must only ever apply to files that already scored > 0
    from keyword/semantic matching — math_utils.py ranks highly (it's
    called into) but a query with zero token overlap with either file must
    still return no relevant files at all."""
    idx = index_repository(str(cross_file_call_repo))
    ctx = build_context("zzz_completely_unrelated_query_zzz", idx, use_cache=False)
    assert ctx.relevant_files == []
