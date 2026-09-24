"""docker_build tool #18 — tool_enhance.md productionization pass
(2026-08-17).

Real, empirically-verified finding (severe — a proven host-file
exfiltration primitive): ALL 3 implementations built their `docker
build` command from `context`/`dockerfile` (both LLM-controlled) with
ZERO worktree-boundary validation. Proved directly, before writing any
fix: a real `docker build` with `context` set to an absolute path
outside the target repo succeeded, and a file from that outside
directory was extracted from the resulting image — a real,
empirically-verified arbitrary-host-file-read-and-exfiltrate chain (see
docs/tool_productionization/docker_build.md for the full proof
transcript).

Tests that need a real `docker` binary/daemon are marked and skipped if
unavailable — matching this codebase's own convention for
infra-dependent tests.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.docker_build import (
    DOCKER_BUILD_TOOL,
    validate_docker_build_inputs,
)

_HAS_DOCKER = shutil.which("docker") is not None

pytestmark = pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_docker_build_hardening", repo_path=repo)
    return ChatAgent(session)


def test_docker_build_tool_schema_requires_tag() -> None:
    assert DOCKER_BUILD_TOOL["name"] == "docker_build"
    assert DOCKER_BUILD_TOOL["input_schema"]["required"] == ["tag"]


# ---------------------------------------------------------------------------
# Pure validator tests (no docker needed)
# ---------------------------------------------------------------------------


def test_validator_allows_default_context_and_no_dockerfile(tmp_path: Path) -> None:
    assert validate_docker_build_inputs(".", None, str(tmp_path)) is None


def test_validator_allows_relative_in_repo_context(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    assert validate_docker_build_inputs("sub", None, str(tmp_path)) is None


def test_validator_rejects_absolute_context_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_context"
    error = validate_docker_build_inputs(str(outside), None, str(tmp_path))
    assert error is not None
    assert "context" in error


def test_validator_rejects_dotdot_context_traversal(tmp_path: Path) -> None:
    error = validate_docker_build_inputs("../../etc", None, str(tmp_path))
    assert error is not None
    assert "context" in error


def test_validator_rejects_absolute_dockerfile_outside_repo(tmp_path: Path) -> None:
    error = validate_docker_build_inputs(".", "/etc/passwd", str(tmp_path))
    assert error is not None
    assert "dockerfile" in error


def test_validator_allows_relative_in_repo_dockerfile(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile.custom").write_text("FROM scratch\n")
    assert validate_docker_build_inputs(".", "Dockerfile.custom", str(tmp_path)) is None


# ---------------------------------------------------------------------------
# The real, proven exploit — verified closed against a real docker build
# ---------------------------------------------------------------------------


def _make_outside_context(tmp_path: Path) -> Path:
    outside = tmp_path.parent / f"td_docker_outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("SECRET_HOST_FILE_CONTENT_MARKER")
    (outside / "Dockerfile").write_text("FROM scratch\nCOPY secret.txt /leaked.txt\n")
    return outside


@pytest.mark.asyncio
async def test_chat_agent_docker_build_rejects_context_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _make_outside_context(tmp_path)
    agent = _agent(str(repo))
    try:
        result = await agent._execute_tool(
            "docker_build", {"tag": "td-exploit-proof:latest", "context": str(outside)}
        )
        assert result.startswith("[POLICY DENIED]")
    finally:
        subprocess.run(
            ["docker", "rmi", "td-exploit-proof:latest"], capture_output=True
        )


def test_make_chat_handlers_docker_build_rejects_context_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _make_outside_context(tmp_path)
    handlers = make_chat_handlers(str(repo))
    try:
        result = handlers["docker_build"](
            {"tag": "td-exploit-proof2:latest", "context": str(outside)}
        )
        assert result.startswith("[POLICY DENIED]")
    finally:
        subprocess.run(
            ["docker", "rmi", "td-exploit-proof2:latest"], capture_output=True
        )


def test_dk_docker_build_rejects_context_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_docker_agent_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _make_outside_context(tmp_path)
    handlers = make_docker_agent_handlers(str(repo))
    try:
        result = handlers["docker_build"](
            {"tag": "td-exploit-proof3:latest", "context": str(outside)}
        )
        assert result.startswith("[POLICY DENIED]")
    finally:
        subprocess.run(
            ["docker", "rmi", "td-exploit-proof3:latest"], capture_output=True
        )


# ---------------------------------------------------------------------------
# Regression — a real, legitimate in-repo build must keep working
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_docker_build_legit_in_repo_build_still_works(
    tmp_path: Path,
) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    agent = _agent(str(tmp_path))
    tag = "td-legit-build-test:latest"
    try:
        result = await agent._execute_tool("docker_build", {"tag": tag})
        assert not result.startswith("[POLICY DENIED]")
        inspect = subprocess.run(
            ["docker", "image", "inspect", tag], capture_output=True
        )
        assert inspect.returncode == 0, "image was not actually built"
    finally:
        subprocess.run(["docker", "rmi", tag], capture_output=True)
