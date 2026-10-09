"""Sol A01/A11, Batch 1 rest (2026-10-09): the chat's run_migration and
seed_database ran repository code (alembic's env.py, the seed script) in a
raw host shell with the platform's own environment — including the
platform's DATABASE_URL. They now run like the DevOps migration agent: in
the toolchain sandbox, with DATABASE_URL set to the TARGET project's
database (MIGRATION_DATABASE_URL), and refuse when none is configured.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import chat_agent

TARGET = "postgresql://app:pw@target-db:5432/shop"


@pytest.fixture
def sandbox_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from app.config import get_settings
    from app.tools.execution import bash

    calls: list[dict[str, Any]] = []

    def fake(command: str, cwd: str, **kw: Any) -> tuple[str, str, int, bool]:
        calls.append({"command": command, "cwd": cwd, **kw})
        return "done", "", 0, False

    monkeypatch.setattr(bash, "_run_bash_command", fake)
    monkeypatch.setattr(get_settings(), "migration_database_url", TARGET)
    return calls


def test_runs_in_the_sandbox_with_the_target_database(
    sandbox_calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    from app.config import get_settings

    out = chat_agent._run_repo_db_command("alembic upgrade head", str(tmp_path))
    assert out == "done"
    call = sandbox_calls[0]
    assert call["command"] == "alembic upgrade head" and call["cwd"] == str(tmp_path)
    assert call["extra_env"] == {"DATABASE_URL": TARGET}
    assert call["image"] == get_settings().bash_sandbox_toolchain_image
    assert call["extra_env"]["DATABASE_URL"] != get_settings().database_url


def test_refused_without_a_target_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.config import get_settings
    from app.tools.execution import bash

    monkeypatch.setattr(get_settings(), "migration_database_url", "")
    ran: list[Any] = []
    monkeypatch.setattr(bash, "_run_bash_command", lambda *a, **k: ran.append(a))
    out = chat_agent._run_repo_db_command("alembic upgrade head", str(tmp_path))
    assert out.startswith("[POLICY DENIED]") and ran == []


def _agent(repo: Path) -> Any:
    from app.models.chat import ChatSession

    session = ChatSession(session_id="a01-chat-db", repo_path=str(repo))
    return chat_agent.ChatAgent(session)


@pytest.mark.asyncio
async def test_chat_migration_and_seed_never_use_the_host_shell(
    sandbox_calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "seed.py").write_text("print('seed')\n")
    agent = _agent(tmp_path)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=True)),
        patch.object(
            chat_agent, "_run_subprocess", side_effect=AssertionError("host shell")
        ),
    ):
        mig = await agent._execute_tool(
            "run_migration", {"direction": "upgrade", "revision": "head"}
        )
        seed = await agent._execute_tool("seed_database", {"script": "scripts/seed.py"})
    assert mig == "done" and seed == "done"
    assert [c["command"] for c in sandbox_calls] == [
        "alembic upgrade head",
        "python3 scripts/seed.py",
    ]
    assert all(c["extra_env"] == {"DATABASE_URL": TARGET} for c in sandbox_calls)
