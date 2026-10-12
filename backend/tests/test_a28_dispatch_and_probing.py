"""Sol A28 (2026-10-09): the dispatcher enforces a ceiling on every tool
call, results have one shape, and the connections tools depend on are
checked for real (installed / connected / authorized / not set up).

Before: a handler that hung (a network call with no timeout of its own)
froze the whole task forever, and "availability" was only a static lookup.
No AI runs and no real service is called (GitHub answers are faked).
"""

from __future__ import annotations

import contextvars
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents import base_graph
from app.services import capabilities

# -- the dispatcher ceiling ---------------------------------------------------------


@pytest.fixture
def short_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "tool_call_ceiling_floor_seconds", 0.5)
    monkeypatch.setattr(
        base_graph, "_tool_call_ceiling", lambda name, inp: 0.5, raising=True
    )


def test_a_hung_tool_returns_a_timeout_instead_of_freezing_the_task(
    short_ceiling: None,
) -> None:
    def hangs(_: dict[str, Any]) -> str:
        time.sleep(3)
        return "finally"

    started = time.monotonic()
    out = base_graph._run_tool_with_retry(hangs, "read_file", {"path": "a.py"})
    assert time.monotonic() - started < 2.5
    assert out.startswith("[ERROR]") and "timed out" in out


def test_normal_results_errors_and_context_are_unchanged(short_ceiling: None) -> None:
    var: contextvars.ContextVar[str] = contextvars.ContextVar("trace", default="")
    var.set("trace-42")

    assert base_graph._run_tool_with_retry(lambda i: var.get(), "read_file", {}) == (
        "trace-42"
    )
    assert base_graph._run_tool_with_retry(lambda i: None, "read_file", {}) == (
        "(no output)"
    )

    def boom(_: dict[str, Any]) -> str:
        raise ValueError("bad input")

    assert base_graph._run_tool_with_retry(boom, "read_file", {}) == (
        "[ERROR] read_file raised: bad input"
    )


def test_the_ceiling_is_generous_and_respects_a_requested_timeout() -> None:
    assert base_graph._tool_call_ceiling("read_file", {}) >= 300
    assert base_graph._tool_call_ceiling("docker_build", {}) >= 4 * 300
    assert base_graph._tool_call_ceiling("run_tests", {"timeout": 900}) >= 960


# -- connections, checked for real -----------------------------------------------------


@pytest.fixture
def no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        capabilities, "check", lambda force=False: {"sandbox": False, "note": "x"}
    )


def _by_key(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {r["key"]: r for r in rows}


def test_missing_things_are_named_not_hidden(
    no_docker: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    rows = _by_key(capabilities.connections(None, None))
    assert rows["docker"]["status"] == "not_connected"
    assert rows["browser"]["status"] == "not_installed"
    assert rows["github"]["status"] == "not_configured"
    assert rows["slack"]["status"] == "not_configured"
    assert rows["ai"]["status"] == "not_configured"


@pytest.mark.parametrize(
    ("code", "status"),
    [(200, "ready"), (401, "not_authorized"), (502, "not_connected")],
)
def test_a_saved_github_token_is_verified_on_request(
    no_docker: None, code: int, status: str
) -> None:
    answer = MagicMock(status_code=code)
    answer.json.return_value = {"login": "owner"}
    with patch("httpx.get", return_value=answer) as get:
        rows = _by_key(capabilities.connections("ghp_x", "k", verify=True))
        unverified = _by_key(capabilities.connections("ghp_x", "k", verify=False))
    assert rows["github"]["status"] == status
    assert get.call_count == 1  # only the explicit check calls GitHub
    assert unverified["github"]["status"] == "ready"


def test_tool_groups_map_to_what_they_need() -> None:
    assert capabilities.requirement_for("docker_build") == "docker"
    assert capabilities.requirement_for("browser_open") == "browser"
    assert capabilities.requirement_for("github_create_pr") == "github"
    assert capabilities.requirement_for("slack_send_message") == "slack"
    assert capabilities.requirement_for("read_file") is None


def test_the_settings_endpoint_includes_connections(no_docker: None) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware import rbac

    app.dependency_overrides[rbac.require_authenticated] = lambda: "admin"
    try:
        with TestClient(app) as client:
            r = client.get("/api/settings/capabilities")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    keys = {c["key"] for c in r.json()["connections"]}
    assert {"docker", "browser", "github", "slack", "linear", "ai"} <= keys
