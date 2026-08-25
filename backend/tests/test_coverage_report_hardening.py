"""coverage_report tool #104 — tool_enhance.md productionization pass
(2026-08-25).

THREE real, empirically-verified findings:

1. The most severe functionality bug: `pytest-cov` was never an
   installed project dependency — 2 of 3 real implementations
   hard-failed every call with a pytest usage error, and the 3rd
   (`td_coverage_report`) silently ran `pytest --collect-only` instead
   of measuring coverage, ignoring `path`/`source`/`min_coverage`
   entirely. Fixed by adding `pytest-cov` as a real dependency.
2. The most severe SECURITY finding: a genuine, direct shell-injection
   on `chat_agent.py`'s dispatch — `path`/`source`/`min_coverage` were
   interpolated completely unquoted into a `shell=True` command.
3. Worktree-boundary escape + flag-collision on `path` (a flag-shaped
   or absolute value could redirect pytest to collect and EXECUTE
   arbitrary files outside the repo).

Fixed via a shared `coverage_report_handler()` using list-args
subprocess calls only (no `shell=True` anywhere), a real `path`/
`source` validator, and a real `min_coverage` type check.

All tests here use real files/subprocess calls on disk — nothing is
mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_tech_debt_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.coverage_report import COVERAGE_REPORT_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_coverage_report_hardening", repo_path=str(repo))
    return ChatAgent(session)


def _write_test_with_source(repo: Path) -> None:
    (repo / "mymodule.py").write_text(
        "def covered():\n    return 1\n\n\ndef uncovered():\n    return 2\n"
    )
    (repo / "test_mymodule.py").write_text(
        "from mymodule import covered\n\n\ndef test_covered():\n    assert covered() == 1\n"
    )


def test_coverage_report_tool_schema() -> None:
    assert COVERAGE_REPORT_TOOL["name"] == "coverage_report"
    assert COVERAGE_REPORT_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_coverage_report_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("coverage_report") == 1


# ---------------------------------------------------------------------------
# Finding #1 — pytest-cov was never installed (real functionality bug)
# ---------------------------------------------------------------------------


def test_pytest_cov_is_actually_installed() -> None:
    import pytest_cov  # noqa: F401


def test_handler_produces_real_coverage_data_not_collection_only(tmp_path: Path) -> None:
    _write_test_with_source(tmp_path)
    handlers = make_tech_debt_agent_handlers(str(tmp_path))
    result = handlers["coverage_report"]({"path": ".", "source": "."})
    assert "coverage" in result.lower()
    assert "mymodule.py" in result
    assert "unrecognized arguments" not in result.lower()


# ---------------------------------------------------------------------------
# Finding #2 — genuine shell injection (chat_agent.py dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_shell_injection_via_path(tmp_path: Path) -> None:
    marker = tmp_path.parent / "coverage_report_hardening_PWNED_marker.txt"
    if marker.exists():
        marker.unlink()
    agent = _agent(tmp_path)
    payload = f"; touch {marker}; echo x"
    result = await agent._execute_tool("coverage_report", {"path": payload})
    assert not marker.exists(), "shell injection must not execute a real command"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Finding #3 — worktree escape + flag-collision on `path`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_directory_outside_repo(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("coverage_report", {"path": "/etc"})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_rejects_flag_shaped_path(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("coverage_report", {"path": "--rootdir=/etc"})
    assert "[ERROR]" in result
    assert "flag" in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("tech_debt", make_tech_debt_agent_handlers),
    ],
)
def test_both_factories_reject_directory_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["coverage_report"]({"path": "/etc"})
    assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"


# ---------------------------------------------------------------------------
# Regression — invalid min_coverage + legitimate usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_invalid_min_coverage(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "coverage_report", {"min_coverage": "not-a-number"}
    )
    assert "[ERROR]" in result
    assert "min_coverage" in result


@pytest.mark.asyncio
async def test_chat_agent_produces_real_coverage_report(tmp_path: Path) -> None:
    _write_test_with_source(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "coverage_report", {"path": ".", "source": "."}
    )
    assert "mymodule.py" in result
    assert "unrecognized arguments" not in result.lower()


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_tech_debt_agent_handlers],
)
def test_both_factories_produce_real_coverage_report(tmp_path: Path, factory) -> None:
    _write_test_with_source(tmp_path)
    handlers = factory(str(tmp_path))
    result = handlers["coverage_report"]({"path": ".", "source": "."})
    assert "mymodule.py" in result
    assert "unrecognized arguments" not in result.lower()
