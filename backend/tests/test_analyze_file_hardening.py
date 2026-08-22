"""analyze_file tool #76 — tool_enhance.md productionization pass
(2026-08-22).

Three real, empirically-verified findings, all fixed at the shared
`analyze_file_handler()` in `app.tools.filesystem.analyze_file`:

1. Worktree-boundary escape, on BOTH implementations, INCLUDING the
   canonical `make_read_only_handlers()` factory — the widest blast
   radius of any finding in the low-risk tier so far (every real
   caller, not just chat_agent.py's own dispatch, was exposed). Proved
   live: `analyze_file({"path": "/etc/passwd"})` genuinely analyzed a
   real host file's content outside the repo.
2. An uncaught `PermissionError`, on both implementations — same class
   as tools #70/#72. Proved live with a real file inside a `chmod 000`
   parent directory.
3. A real functionality-parity gap: `chat_agent.py`'s dispatch missed
   plain (non-exported) TypeScript `function `/`const `/`interface `/
   `type ` definitions that the canonical implementation already
   detected.

All tests here use real files/permissions on disk — nothing is mocked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.analyze_file import ANALYZE_FILE_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_analyze_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_analyze_file_tool_schema_requires_path() -> None:
    assert ANALYZE_FILE_TOOL["name"] == "analyze_file"
    assert ANALYZE_FILE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_only_tools_index_fifteen_is_still_analyze_file() -> None:
    assert READ_ONLY_TOOLS[15]["name"] == "analyze_file"


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (both real implementations,
# including the canonical factory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_analyze_file_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "analyze_file_hardening_secret.txt"
    outside.write_text("import secret_module\ndef secret_function():\n    pass\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("analyze_file", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "secret_function" not in result
    finally:
        outside.unlink()


def test_canonical_read_only_handlers_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    """The canonical implementation itself was vulnerable this time —
    verify it's now fixed too, not just chat_agent.py's copy."""
    outside = tmp_path.parent / "analyze_file_hardening_secret2.txt"
    outside.write_text("import secret_module\n")
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["analyze_file"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "secret_module" not in result
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_analyze_file_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "analyze_file", {"path": "../../../../../../etc/passwd"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught PermissionError (both real implementations)
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_parent_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    inner = restricted / "inner.py"
    inner.write_text("import secret_module\n")
    original_mode = restricted.stat().st_mode
    restricted.chmod(0)
    try:
        yield "restricted_dir/inner.py"
    finally:
        restricted.chmod(original_mode)


@pytest.mark.asyncio
async def test_chat_agent_analyze_file_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("analyze_file", {"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


def test_canonical_read_only_handlers_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["analyze_file"]({"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Finding #3 — functionality parity: non-exported TS/JS forms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_analyze_file_detects_non_exported_ts_forms(
    tmp_path: Path,
) -> None:
    """chat_agent.py's dispatch previously missed these entirely."""
    (tmp_path / "target.ts").write_text(
        "interface Foo {}\nconst bar = 1;\ntype Baz = string;\nfunction qux() {}\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("analyze_file", {"path": "target.ts"})
    assert "interface Foo" in result
    assert "const bar" in result
    assert "type Baz" in result
    assert "function qux" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_analyze_file_reports_real_python_structure(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text(
        "import os\nfrom pathlib import Path\n\n\ndef real_function():\n    pass\n\n\nclass RealClass:\n    pass\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("analyze_file", {"path": "target.py"})
    assert "import os" in result
    assert "real_function" in result
    assert "RealClass" in result


@pytest.mark.asyncio
async def test_chat_agent_analyze_file_missing_file_errors_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("analyze_file", {"path": "ghost.py"})
    assert "[ERROR]" in result


def test_canonical_read_only_handlers_reports_real_python_structure(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function():\n    pass\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["analyze_file"]({"path": "target.py"})
    assert "real_function" in result


def test_make_chat_handlers_analyze_file_reports_real_python_structure(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function():\n    pass\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["analyze_file"]({"path": "target.py"})
    assert "real_function" in result


def test_analyze_file_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("analyze_file") == 1
