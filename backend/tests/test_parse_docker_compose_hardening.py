"""parse_docker_compose tool #170 — tool_enhance.md productionization
pass (2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`parse_docker_compose_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle. `root/path` was never validated. Proved live:
   real service names, images, exposed ports, and volume/secret-mount
   paths of a compose file outside the worktree were genuinely
   disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `parse_docker_compose_handler()`
using `check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.parse_docker_compose import (
    PARSE_DOCKER_COMPOSE_TOOL,
    parse_docker_compose_handler,
)

SECRET_COMPOSE = (
    "services:\n"
    "  admin-db:\n"
    "    image: internal-registry.example.com/secret-admin-db:latest\n"
    "    ports:\n"
    "      - '5432:5432'\n"
    "    volumes:\n"
    "      - /var/secrets/admin-creds:/creds\n"
)

PUBLIC_COMPOSE = (
    "services:\n"
    "  web:\n"
    "    image: nginx:latest\n"
    "    ports:\n"
    "      - '80:80'\n"
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_parse_docker_compose_hardening", repo_path=repo)
    return ChatAgent(session)


def test_parse_docker_compose_tool_schema() -> None:
    assert PARSE_DOCKER_COMPOSE_TOOL["name"] == "parse_docker_compose"
    assert PARSE_DOCKER_COMPOSE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_parse_docker_compose_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("parse_docker_compose") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape structured content disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret-compose.yml").write_text(SECRET_COMPOSE)

        out = parse_docker_compose_handler(
            worktree, str(worktree), {"path": str(outside / "secret-compose.yml")}
        )
        assert "POLICY DENIED" in out
        assert "admin-db" not in out
        assert "secret-admin-db" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret-compose.yml").write_text(SECRET_COMPOSE)

        out = parse_docker_compose_handler(
            worktree, str(worktree), {"path": "../secret-compose.yml"}
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret-compose.yml").write_text(SECRET_COMPOSE)

        handlers = make_chat_handlers(str(worktree))
        out = handlers["parse_docker_compose"]({"path": str(outside / "secret-compose.yml")})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret-compose.yml").write_text(SECRET_COMPOSE)

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "parse_docker_compose", {"path": str(outside / "secret-compose.yml")}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text(PUBLIC_COMPOSE)
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool(
                "parse_docker_compose", {"path": "docker-compose.yml"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "nginx" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree compose file, both paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_compose(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text(PUBLIC_COMPOSE)
        out = parse_docker_compose_handler(
            tmp_path, str(tmp_path), {"path": "docker-compose.yml"}
        )
        assert "web" in out
        assert "nginx:latest" in out

    def test_make_chat_handlers_real_compose(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text(PUBLIC_COMPOSE)
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["parse_docker_compose"]({"path": "docker-compose.yml"})
        assert "nginx:latest" in out

    def test_default_path_used_when_omitted(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text(PUBLIC_COMPOSE)
        out = parse_docker_compose_handler(tmp_path, str(tmp_path), {})
        assert "nginx:latest" in out

    def test_missing_file_error(self, tmp_path: Path) -> None:
        out = parse_docker_compose_handler(tmp_path, str(tmp_path), {"path": "nope.yml"})
        assert "[ERROR] File not found" in out

    def test_empty_compose_file(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("")
        out = parse_docker_compose_handler(
            tmp_path, str(tmp_path), {"path": "docker-compose.yml"}
        )
        assert "empty or invalid compose file" in out

    def test_no_services_key(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        out = parse_docker_compose_handler(
            tmp_path, str(tmp_path), {"path": "docker-compose.yml"}
        )
        assert "no services found" in out
