"""MCP server unit tests — JSON-RPC handling without stdio."""

import json
import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _patch_env() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://x:x@localhost/x",
        "ANTHROPIC_API_KEY": "sk-ant-dummy",
        "TARGET_REPO_PATH": ".",
    }
    import app.config as cfg

    cfg._settings = None
    with patch.dict(os.environ, env, clear=False):
        yield
    cfg._settings = None


def _call(method: str, params: dict) -> dict:
    from app.mcp.server import _handle

    return _handle(method, params)


def test_initialize_returns_protocol_version() -> None:
    result = _call("initialize", {})
    assert result["protocolVersion"] == "2024-11-05"
    assert "tools" in result["capabilities"]


def test_tools_list_returns_known_tools() -> None:
    result = _call("tools/list", {})
    names = [t["name"] for t in result["tools"]]
    assert "index_repository" in names
    assert "search_symbols" in names
    assert "build_context" in names
    assert "query_dependencies" in names


def test_index_repository_returns_counts(tmp_path) -> None:
    # audit_v1.md 4.2 #4: _get_repo() now validates repo_path resolves
    # under a configured allowed root (target_repo_path/repos_dir/
    # worktrees_dir) — REPOS_DIR is set here to tmp_path's own parent so
    # this synthetic test repo is a legitimately-configured root, the same
    # way a real deployment would configure where its repos live, rather
    # than relying on an arbitrary unconfigured path being silently
    # accepted like before this fix.
    import app.config as cfg

    (tmp_path / "hello.py").write_text("def hello(): pass\n")
    with patch.dict(os.environ, {"REPOS_DIR": str(tmp_path.parent)}):
        cfg._settings = None
        result = _call(
            "tools/call",
            {"name": "index_repository", "arguments": {"repo_path": str(tmp_path)}},
        )
    cfg._settings = None
    data = json.loads(result["content"][0]["text"])
    assert data["files"] == 1
    assert data["symbols"] >= 1


def test_search_symbols_finds_function(tmp_path) -> None:
    import app.config as cfg

    (tmp_path / "math.py").write_text("def calculate(x): return x * 2\n")
    with patch.dict(os.environ, {"REPOS_DIR": str(tmp_path.parent)}):
        cfg._settings = None
        result = _call(
            "tools/call",
            {
                "name": "search_symbols",
                "arguments": {"query": "calculate", "repo_path": str(tmp_path)},
            },
        )
    cfg._settings = None
    matches = json.loads(result["content"][0]["text"])
    assert any(m["name"] == "calculate" for m in matches)


def test_get_repo_denies_path_outside_allowed_roots() -> None:
    """audit_v1.md 4.2 #4 — the actual exploit case: an MCP client
    specifying repo_path="/etc" (or a traversal) used to make the server
    scan and return path/symbol-name info from arbitrary host directories."""
    from app.mcp.server import McpRepoPathDenied, _get_repo

    with pytest.raises(McpRepoPathDenied):
        _get_repo({"repo_path": "/etc"})
    with pytest.raises(McpRepoPathDenied):
        _get_repo({"repo_path": "../../../../etc"})


def test_unknown_method_returns_error() -> None:
    result = _call("nonexistent/method", {})
    assert "error" in result


def test_unknown_tool_returns_error() -> None:
    result = _call("tools/call", {"name": "does_not_exist", "arguments": {}})
    assert "error" in result
