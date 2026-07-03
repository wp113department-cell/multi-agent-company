"""Tests for Documentation Agent — .ts write denied, .md write allowed."""
from __future__ import annotations

import os
import tempfile

import pytest

from app.agents.tools import make_docs_handlers, DOCS_TOOLS


# ---- Tool list ----

def test_docs_tools_has_write_file() -> None:
    """DOCS_TOOLS must include write_file."""
    names = [t["name"] for t in DOCS_TOOLS]
    assert "write_file" in names


def test_docs_tools_has_submit_docs() -> None:
    """DOCS_TOOLS must include submit_docs."""
    names = [t["name"] for t in DOCS_TOOLS]
    assert "submit_docs" in names


def test_docs_tools_has_no_bash() -> None:
    """DOCS_TOOLS must NOT include bash."""
    names = [t["name"] for t in DOCS_TOOLS]
    assert "bash" not in names


def test_docs_tools_has_no_submit_patch() -> None:
    """DOCS_TOOLS must NOT include submit_patch."""
    names = [t["name"] for t in DOCS_TOOLS]
    assert "submit_patch" not in names


# ---- Policy enforcement in write_file handler ----

def _make_handlers(worktree: str) -> dict:  # type: ignore[type-arg]
    return make_docs_handlers(worktree_path=worktree, repo_path=worktree)


def test_docs_write_md_file_allowed() -> None:
    """Docs agent CAN write a .md file in the worktree."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        result = handlers["write_file"]({"path": "docs/changelog/2026-07-03-epic.md", "content": "# Change\n"})
        assert "Written" in result
        written_path = os.path.join(wt, "docs/changelog/2026-07-03-epic.md")
        assert os.path.exists(written_path)


def test_docs_write_readme_allowed() -> None:
    """Docs agent CAN write README.md."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        result = handlers["write_file"]({"path": "README.md", "content": "# Updated\n"})
        assert "Written" in result


def test_docs_write_ts_file_denied() -> None:
    """Docs agent CANNOT write a .ts file — policy denied."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        result = handlers["write_file"]({"path": "apps/web/lib/api.ts", "content": "export const x = 1"})
        assert "POLICY DENIED" in result
        # File must NOT be created
        assert not os.path.exists(os.path.join(wt, "apps/web/lib/api.ts"))


def test_docs_write_py_file_denied() -> None:
    """Docs agent CANNOT write a .py file."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        result = handlers["write_file"]({"path": "backend/app/main.py", "content": "x = 1"})
        assert "POLICY DENIED" in result


def test_docs_write_json_file_denied() -> None:
    """Docs agent CANNOT write a .json file."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        result = handlers["write_file"]({"path": "package.json", "content": "{}"})
        assert "POLICY DENIED" in result


def test_docs_submit_docs_stores_result() -> None:
    """submit_docs handler stores the result in _docs_result."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        handlers["submit_docs"]({
            "files_written": ["docs/changelog/test.md"],
            "summary": "Added changelog entry",
        })
        result = handlers["_docs_result"]
        assert result["files_written"] == ["docs/changelog/test.md"]
        assert result["summary"] == "Added changelog entry"


def test_docs_write_under_docs_dir_allowed() -> None:
    """Docs agent CAN write under docs/ even without .md extension."""
    with tempfile.TemporaryDirectory() as wt:
        handlers = _make_handlers(wt)
        result = handlers["write_file"]({"path": "docs/architecture/overview.md", "content": "# Arch\n"})
        assert "Written" in result
