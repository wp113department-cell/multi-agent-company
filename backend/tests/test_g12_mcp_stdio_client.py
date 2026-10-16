"""G12 (2026-10-16): the MCP server, driven by the official MCP client over
real stdio (`python -m app.mcp.server` as a child process).

Real bugs this found: the server answered the `notifications/initialized`
notification (with id null) and did not support `ping`, so the official
client failed on its first keep-alive; a failing tool came back as an
internal protocol error instead of a tool result the model can read.

Exposure: the server only speaks over stdio — it opens no network port, so
only a program the local user starts can reach it, with that user's
rights. Each call's repo_path must resolve under TARGET_REPO_PATH,
REPOS_DIR or WORKTREES_DIR.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from mcp.shared.exceptions import MCPError  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    src = BACKEND / "tests" / "fixtures" / "demo-repo"
    dst = tmp_path / "repo"
    dst.mkdir()
    shutil.copy(src / "demo_module.py", dst)
    (dst / "tests").mkdir()
    shutil.copy(src / "tests" / "test_demo.py", dst / "tests")
    return dst


def _run(repo: Path, body: Callable[[ClientSession], Awaitable[Any]]) -> Any:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        cwd=str(BACKEND),
        env={
            **os.environ,
            "TARGET_REPO_PATH": str(repo),
            "VOYAGE_API_KEY": "",
            "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
        },
    )

    async def main() -> Any:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 30)
                return await asyncio.wait_for(body(session), 60)

    return asyncio.run(main())


def _text(result: Any) -> Any:
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def test_handshake_ping_and_tool_list(repo: Path) -> None:
    async def body(s: ClientSession) -> Any:
        await s.send_ping()  # failed before: "Unknown method: ping"
        return [t.name for t in (await s.list_tools()).tools]

    assert sorted(_run(repo, body)) == sorted(
        [
            "index_repository",
            "search_symbols",
            "build_context",
            "query_dependencies",
            "semantic_search",
            "get_file_summary",
        ]
    )


def test_every_tool_works_through_the_real_client(repo: Path) -> None:
    async def body(s: ClientSession) -> dict[str, Any]:
        return {
            "index": _text(await s.call_tool("index_repository", {})),
            "symbols": _text(await s.call_tool("search_symbols", {"query": "mult"})),
            "context": _text(
                await s.call_tool("build_context", {"task_description": "greet users"})
            ),
            "deps": _text(
                await s.call_tool(
                    "query_dependencies", {"file_path": "tests/test_demo.py"}
                )
            ),
            "search": _text(await s.call_tool("semantic_search", {"query": "greet"})),
            "summary": _text(
                await s.call_tool("get_file_summary", {"file_path": "demo_module.py"})
            ),
        }

    r = _run(repo, body)
    assert r["index"]["files"] == 2
    assert {m["name"] for m in r["symbols"]} == {"multiply", "test_multiply_integers"}
    assert "demo_module.py" in r["context"]["relevant_files"]
    assert r["deps"]["file"] == "tests/test_demo.py"
    assert r["search"]["results"][0]["file"] == "demo_module.py"
    assert {s["name"] for s in r["summary"]["symbols"]} >= {"greet", "multiply"}


def test_a_path_outside_the_allowed_roots_is_refused(repo: Path) -> None:
    async def body(s: ClientSession) -> Any:
        return await s.call_tool("index_repository", {"repo_path": "/etc"})

    result = _run(repo, body)
    assert result.is_error
    assert "does not resolve under any configured allowed root" in (
        result.content[0].text
    )


def test_bad_calls_are_invalid_params(repo: Path) -> None:
    async def body(s: ClientSession) -> list[int]:
        codes = []
        for name, args in (("build_context", {}), ("no_such_tool", {})):
            try:
                await s.call_tool(name, args)
            except MCPError as exc:
                codes.append(exc.error.code)
        return codes

    assert _run(repo, body) == [-32602, -32602]
