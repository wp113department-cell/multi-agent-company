"""parse_dockerfile tool #171 — tool_enhance.md productionization
pass (2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`parse_dockerfile_h` inside `make_chat_handlers`) —
same class as sibling tool #170 (`parse_docker_compose`).

1. Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle. `root/path` was never validated. Proved live: a
   real base image reference, exposed port, and build instruction
   from a Dockerfile outside the worktree were genuinely disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `parse_dockerfile_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.parse_dockerfile import (
    PARSE_DOCKERFILE_TOOL,
    parse_dockerfile_handler,
)

SECRET_DOCKERFILE = (
    "FROM internal-registry.example.com/secret-base:latest\n"
    "EXPOSE 9999\n"
    "RUN echo SECRET_BUILD_STEP\n"
)

PUBLIC_DOCKERFILE = 'FROM python:3.12\nEXPOSE 8000\nCMD ["python", "app.py"]\n'


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_parse_dockerfile_hardening", repo_path=repo)
    return ChatAgent(session)


def test_parse_dockerfile_tool_schema() -> None:
    assert PARSE_DOCKERFILE_TOOL["name"] == "parse_dockerfile"
    assert PARSE_DOCKERFILE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_parse_dockerfile_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("parse_dockerfile") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape structured content disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "Dockerfile.secret").write_text(SECRET_DOCKERFILE)

        out = parse_dockerfile_handler(
            worktree, str(worktree), {"path": str(outside / "Dockerfile.secret")}
        )
        assert "POLICY DENIED" in out
        assert "secret-base" not in out
        assert "SECRET_BUILD_STEP" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "Dockerfile.secret").write_text(SECRET_DOCKERFILE)

        out = parse_dockerfile_handler(
            worktree, str(worktree), {"path": "../Dockerfile.secret"}
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "Dockerfile.secret").write_text(SECRET_DOCKERFILE)

        handlers = make_chat_handlers(str(worktree))
        out = handlers["parse_dockerfile"]({"path": str(outside / "Dockerfile.secret")})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "Dockerfile.secret").write_text(SECRET_DOCKERFILE)

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "parse_dockerfile", {"path": str(outside / "Dockerfile.secret")}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(PUBLIC_DOCKERFILE)
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("parse_dockerfile", {"path": "Dockerfile"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "python:3.12" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree Dockerfile, both paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(PUBLIC_DOCKERFILE)
        out = parse_dockerfile_handler(tmp_path, str(tmp_path), {"path": "Dockerfile"})
        assert "python:3.12" in out
        assert "8000" in out
        assert "CMD" in out

    def test_make_chat_handlers_real_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(PUBLIC_DOCKERFILE)
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["parse_dockerfile"]({"path": "Dockerfile"})
        assert "python:3.12" in out

    def test_default_path_used_when_omitted(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(PUBLIC_DOCKERFILE)
        out = parse_dockerfile_handler(tmp_path, str(tmp_path), {})
        assert "python:3.12" in out

    def test_missing_file_error(self, tmp_path: Path) -> None:
        out = parse_dockerfile_handler(
            tmp_path, str(tmp_path), {"path": "NoSuchDockerfile"}
        )
        assert "[ERROR] File not found" in out

    def test_empty_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("")
        out = parse_dockerfile_handler(tmp_path, str(tmp_path), {"path": "Dockerfile"})
        assert "empty or unparseable Dockerfile" in out

    def test_multi_stage_line_continuation(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.12 AS builder\n"
            "RUN pip install \\\n"
            "    -r requirements.txt\n"
            "FROM python:3.12-slim\n"
            "EXPOSE 8000\n"
        )
        out = parse_dockerfile_handler(tmp_path, str(tmp_path), {"path": "Dockerfile"})
        assert "python:3.12 AS builder" in out
        assert "python:3.12-slim" in out
        assert "pip install -r requirements.txt" in out
