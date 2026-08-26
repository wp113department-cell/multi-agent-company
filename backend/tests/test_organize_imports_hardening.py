"""organize_imports tool #115 — tool_enhance.md productionization pass
(2026-08-26).

Three real, empirically-verified findings, on THREE real implementations
(`cu_organize_imports` in `make_cleanup_agent_handlers`, `organize_imports`
inside `make_chat_handlers`, and `chat_agent.py`'s own dispatch):

1. A genuine, direct shell-injection (arbitrary command execution) on
   `chat_agent.py`'s dispatch — the LLM-controlled `path` field was
   interpolated completely unquoted into an f-string `shell=True`
   command.
2. A worktree-boundary escape that is a genuine ARBITRARY FILE
   MODIFICATION (not just a read) on both `chat_agent.py`'s dispatch
   and `organize_imports` (`make_chat_handlers`) — neither validated
   `path` before `root / path`, and this tool's whole purpose is
   running `ruff --fix`, which rewrites the target in place.
3. `cu_organize_imports` used a completely different tool (`isort
   --diff`, preview-only) than the one the schema documents (`ruff`,
   which actually applies the fix) — a real functionality-divergence
   from its own documented contract. Its worktree-boundary handling
   was already correct.

All three are now closed via a single shared `organize_imports_handler()`
(list-args subprocess only, `check_path_in_worktree()` validation, real
`ruff check --select I --fix`), used identically by all three real call
sites.

Both live-exploit proofs behind these tests were originally reproduced
against fully isolated `/tmp` scratch directories, never against this
project's own checkout (a first, unsafe attempt at proving finding #1
accidentally caused `ruff --fix` to run against the real project
directory when an injected payload left no valid target argument —
caught immediately via `git status`, confirmed as pure import
reordering with no logic change, and fully reverted via `git checkout
--` before any commit). Every test below that could plausibly cause a
real file mutation uses `tmp_path`/`tmp_repo` fixtures exclusively.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_cleanup_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.organize_imports import (
    ORGANIZE_IMPORTS_TOOL,
    organize_imports_handler,
)

INJECTION_PAYLOAD = "; touch /tmp/PWNED_ORGANIZE_IMPORTS_HARDENING; echo x"


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_organize_imports_hardening", repo_path=repo)
    return ChatAgent(session)


def test_organize_imports_tool_schema() -> None:
    assert ORGANIZE_IMPORTS_TOOL["name"] == "organize_imports"
    assert ORGANIZE_IMPORTS_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_organize_imports_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("organize_imports") == 1


# ---------------------------------------------------------------------------
# Finding #1 — shell-injection RCE (chat_agent.py's dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_shell_injection(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_ORGANIZE_IMPORTS_HARDENING"
    payload = f"; touch {marker}; echo x"
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("organize_imports", {"path": payload})
    assert "File not found" in result
    assert not marker.exists()


def test_handler_closes_shell_injection_directly(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_HANDLER_DIRECT"
    payload = f"; touch {marker}; echo x"
    result = organize_imports_handler(tmp_path, str(tmp_path), {"path": payload})
    assert "File not found" in result
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Finding #2 — worktree-escape arbitrary file modification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("make_cleanup_agent_handlers", make_cleanup_agent_handlers),
    ],
)
def test_all_factories_close_worktree_escape_write(
    tmp_path: Path, factory_name: str, factory: Any
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_secret.py"
    outside.write_text("import os\nimport sys\nimport json\n")

    handlers = factory(str(repo))
    result = handlers["organize_imports"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result, f"{factory_name} did not close the escape"
    # The outside file must be genuinely untouched, not just an error message.
    assert outside.read_text() == "import os\nimport sys\nimport json\n"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_worktree_escape_write(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_secret.py"
    outside.write_text("import os\nimport sys\nimport json\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("organize_imports", {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert outside.read_text() == "import os\nimport sys\nimport json\n"


# ---------------------------------------------------------------------------
# Finding #3 — cu_organize_imports now genuinely applies the fix
# (previously: isort --diff, preview-only, never wrote anything)
# ---------------------------------------------------------------------------


def test_cu_organize_imports_now_genuinely_applies_the_fix(tmp_path: Path) -> None:
    target = tmp_path / "unsorted.py"
    target.write_text("import os\nimport sys\nimport json\n")

    handlers = make_cleanup_agent_handlers(str(tmp_path))
    result = handlers["organize_imports"]({"path": "unsorted.py"})

    assert "fixed" in result.lower()
    # Real proof it's applied, not previewed: the file content changed.
    assert target.read_text() == "import json\nimport os\nimport sys\n"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths
# ---------------------------------------------------------------------------


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = organize_imports_handler(tmp_path, str(tmp_path), {"path": "missing.py"})
    assert result == "[ERROR] File not found: missing.py"


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_cleanup_agent_handlers],
)
def test_all_factories_genuinely_organize_a_real_file(
    tmp_path: Path, factory: Any
) -> None:
    target = tmp_path / "messy.py"
    target.write_text("import os\nimport sys\nimport json\n")

    handlers = factory(str(tmp_path))
    result = handlers["organize_imports"]({"path": "messy.py"})

    assert "[ERROR]" not in result
    assert target.read_text() == "import json\nimport os\nimport sys\n"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_genuinely_organizes_a_real_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "messy.py"
    target.write_text("import os\nimport sys\nimport json\n")

    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("organize_imports", {"path": "messy.py"})

    assert "[ERROR]" not in result
    assert target.read_text() == "import json\nimport os\nimport sys\n"
