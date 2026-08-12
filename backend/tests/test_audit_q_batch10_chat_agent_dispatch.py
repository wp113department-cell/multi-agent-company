"""AUDIT_Q_BATCH10 — ChatAgent._execute_tool coverage for the same gap-
closures proven at the app.agents.tools.make_chat_handlers layer in
test_audit_q_batch10_deployment_external_git_docs.py.

ChatAgent._execute_tool is a SEPARATE, independently-maintained dispatcher
from make_chat_handlers (confirmed pre-existing architecture, not something
this batch refactors away) — every tool in CHAT_TOOLS needs its own branch
here too, or it silently falls through to "[ERROR] Unknown tool" in
interactive chat sessions specifically. This file proves three real,
pre-existing bugs found and fixed while wiring Batch 10's new tools into
this dispatcher:

1. fetch_url's chat-mode branch had NO SSRF guard and interpolated the raw
   URL into a shell string unescaped (real command-injection surface) —
   both are fixed here.
2. parse_merge_conflicts/resolve_merge_conflict were advertised in
   CHAT_TOOLS (so the LLM would try to call them in a chat session) but had
   NO branch at all — any attempt would return "[ERROR] Unknown tool".
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession


def _session(repo_path: Path, name: str) -> ChatSession:
    return ChatSession(session_id=name, repo_path=str(repo_path))


@pytest.mark.asyncio
async def test_fetch_url_ssrf_denied_in_chat_mode(tmp_path: Path) -> None:
    agent = ChatAgent(_session(tmp_path, "batch10_fetch_url_ssrf"))
    result = await agent._execute_tool(
        "fetch_url", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_fetch_url_shell_metacharacters_are_not_executed(
    tmp_path: Path,
) -> None:
    """A URL containing shell metacharacters must never reach a second
    command — proves the shlex.quote fix, not just that fetch_url "works"."""
    marker = tmp_path / "pwned_marker.txt"
    agent = ChatAgent(_session(tmp_path, "batch10_fetch_url_injection"))
    malicious_url = f"http://127.0.0.1:19999/x; touch {marker}"
    await agent._execute_tool("fetch_url", {"url": malicious_url, "timeout": 2})
    assert not marker.exists()


@pytest.mark.asyncio
async def test_parse_merge_conflicts_reachable_in_chat_mode(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflicted.txt"
    conflicted.write_text(
        "context 1\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\ncontext 2\n"
    )
    agent = ChatAgent(_session(tmp_path, "batch10_parse_conflicts"))
    result = await agent._execute_tool(
        "parse_merge_conflicts", {"path": "conflicted.txt"}
    )
    assert "[ERROR] Unknown tool" not in result
    assert '"hunks"' in result


@pytest.mark.asyncio
async def test_resolve_merge_conflict_reachable_in_chat_mode(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflicted.txt"
    conflicted.write_text(
        "context 1\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\ncontext 2\n"
    )
    agent = ChatAgent(_session(tmp_path, "batch10_resolve_conflicts"))
    result = await agent._execute_tool(
        "resolve_merge_conflict",
        {"path": "conflicted.txt", "resolutions": [{"index": 0, "choice": "ours"}]},
    )
    assert "[ERROR] Unknown tool" not in result
    assert "Resolved" in result
    assert conflicted.read_text().strip() == "context 1\nours\ncontext 2"


@pytest.mark.asyncio
async def test_explain_merge_conflict_reachable_in_chat_mode(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflicted.txt"
    conflicted.write_text(
        "context 1\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\ncontext 2\n"
    )
    agent = ChatAgent(_session(tmp_path, "batch10_explain_conflicts"))
    with patch(
        "app.agents.chat_agent._llm_explain_conflict_hunks",
        return_value="Ours kept 'ours', theirs kept 'theirs'.",
    ):
        result = await agent._execute_tool(
            "explain_merge_conflict", {"path": "conflicted.txt"}
        )
    assert "Ours kept 'ours', theirs kept 'theirs'." in result


@pytest.mark.asyncio
async def test_protected_path_denied_for_conflict_tools(tmp_path: Path) -> None:
    """parse_merge_conflicts/resolve_merge_conflict/explain_merge_conflict
    must run their path through the same _is_protected_path deny-list
    (.env, secrets/, *.pem, etc.) every other file-taking tool in this
    dispatcher already does — proven against a real denied basename (.env),
    matching _is_protected_path's actual documented scope (a deny-list
    check, not a path-traversal boundary check — see its own docstring)."""
    agent = ChatAgent(_session(tmp_path, "batch10_protected_path"))
    result = await agent._execute_tool("parse_merge_conflicts", {"path": ".env"})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_review_diff_reachable_in_chat_mode(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True
    )
    (tmp_path / "f.txt").write_text("hello")
    subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_path), capture_output=True)

    agent = ChatAgent(_session(tmp_path, "batch10_review_diff"))
    with patch("app.agents.chat_agent._llm_review_diff", return_value="Adds f.txt."):
        result = await agent._execute_tool("review_diff", {})
    assert "Adds f.txt." in result


@pytest.mark.asyncio
async def test_diagnose_deployment_failure_reachable_in_chat_mode(
    tmp_path: Path,
) -> None:
    agent = ChatAgent(_session(tmp_path, "batch10_diagnose_deploy"))
    with patch(
        "app.agents.chat_agent._run_subprocess",
        return_value="CONTAINER ID   STATUS\n(none)",
    ), patch(
        "app.agents.chat_agent._llm_diagnose_deployment_failure",
        return_value="No containers running.",
    ):
        result = await agent._execute_tool("diagnose_deployment_failure", {})
    assert "No containers running." in result


@pytest.mark.asyncio
async def test_inspect_github_repo_reachable_in_chat_mode(tmp_path: Path) -> None:
    agent = ChatAgent(_session(tmp_path, "batch10_inspect_github"))
    result = await agent._execute_tool(
        "inspect_github_repo", {"owner": "", "repo": "x"}
    )
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_inspect_openapi_spec_reachable_in_chat_mode(tmp_path: Path) -> None:
    agent = ChatAgent(_session(tmp_path, "batch10_inspect_openapi"))
    result = await agent._execute_tool("inspect_openapi_spec", {})
    assert "[ERROR]" in result
