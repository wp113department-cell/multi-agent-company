"""find_unused_imports tool #141 — tool_enhance.md productionization
pass (2026-09-11).

Two real, empirically-verified findings, on the one real
implementation (`find_unused_imports_h` inside `make_chat_handlers`,
plus `app/agents/chat_agent.py`'s dispatch, which never existed until
this turn):

1. A worktree-boundary escape that is a genuine PARTIAL SOURCE CODE
   disclosure oracle, not just a filename leak — `root / path` was
   never validated, and ruff's diagnostic output includes real
   surrounding source lines. Proved live: real code (including
   unrelated lines, not just the flagged import) was genuinely
   disclosed from a file outside the intended worktree.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `find_unused_imports_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.find_unused_imports import (
    FIND_UNUSED_IMPORTS_TOOL,
    find_unused_imports_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_find_unused_imports_hardening", repo_path=repo)
    return ChatAgent(session)


def test_find_unused_imports_tool_schema() -> None:
    assert FIND_UNUSED_IMPORTS_TOOL["name"] == "find_unused_imports"
    assert FIND_UNUSED_IMPORTS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_find_unused_imports_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_unused_imports") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape partial source code disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("import os\nimport sys\n\nSECRET_MARKER = 1\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["find_unused_imports"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "SECRET_MARKER" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("import os\nimport sys\n\nSECRET_MARKER = 1\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "find_unused_imports", {"path": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert "SECRET_MARKER" not in result


def test_handler_closes_path_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("import os\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = find_unused_imports_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "unused.py").write_text("import os\n\nprint('hi')\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "find_unused_imports", {"path": "unused.py"}
    )
    assert "Unknown tool" not in result
    assert "os" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_finds_a_real_unused_import(tmp_path: Path) -> None:
    (tmp_path / "unused.py").write_text("import os\n\nprint('hi')\n")
    result = find_unused_imports_handler(
        tmp_path, str(tmp_path), {"path": "unused.py"}
    )
    assert "F401" in result
    assert "`os` imported but unused" in result


def test_handler_reports_clean_file(tmp_path: Path) -> None:
    """Real ruff CLI behavior: it always prints something to stdout
    (either the findings, or "All checks passed!") -- the handler's
    own "No unused imports found" fallback for empty stdout is
    inherited, unmodified, dead-in-practice code from the original
    implementation; not this tool's own turn's finding to change."""
    (tmp_path / "clean.py").write_text("import os\n\nprint(os.getcwd())\n")
    result = find_unused_imports_handler(
        tmp_path, str(tmp_path), {"path": "clean.py"}
    )
    assert "[ERROR]" not in result
    assert "F401" not in result


def test_handler_defaults_to_repo_root(tmp_path: Path) -> None:
    (tmp_path / "unused.py").write_text("import sys\n\nprint('hi')\n")
    result = find_unused_imports_handler(tmp_path, str(tmp_path), {})
    assert "F401" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_finds_a_real_unused_import(
    tmp_path: Path,
) -> None:
    (tmp_path / "unused.py").write_text("import os\n\nprint('hi')\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "find_unused_imports", {"path": "unused.py"}
    )
    assert "F401" in result
