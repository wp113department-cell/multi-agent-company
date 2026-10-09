"""Sol A31 (2026-10-09): capability health checks — what the code sandbox
can actually do, checked by starting the toolchain image once (cached),
shown on the Settings page instead of a tool failing mid-task."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import capabilities


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.policy import sandbox

    capabilities.reset_cache()
    monkeypatch.setattr(sandbox, "_docker_available", lambda: True)
    yield
    capabilities.reset_cache()


def _probe(
    monkeypatch: pytest.MonkeyPatch, stdout: str, rc: int = 0
) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, rc, stdout, "boom" if rc else "")

    monkeypatch.setattr(capabilities.subprocess, "run", fake)
    return calls


def test_reports_what_the_toolchain_has(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _probe(monkeypatch, "has:python3\nhas:node\nhas:pnpm\nhas:git\n")
    r = capabilities.check()
    assert r["sandbox"] is True
    assert r["programs"]["python3"] and r["programs"]["pnpm"]
    assert r["programs"]["gh"] is False and r["browsers"] is False
    argv = calls[0]
    # the probe itself is a locked-down sandbox run, never the host
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in argv and "--read-only" in argv
    assert argv[argv.index("--user") + 1] == "10001:10001"


def test_browsers_are_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    _probe(monkeypatch, "has:python3\nhas:browsers /ms-playwright/chromium-1\n")
    assert capabilities.check()["browsers"] is True


def test_no_docker_means_no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.policy import sandbox

    monkeypatch.setattr(sandbox, "_docker_available", lambda: False)
    calls = _probe(monkeypatch, "")
    r = capabilities.check()
    assert r["sandbox"] is False and "not reachable" in r["note"] and calls == []


def test_an_image_that_will_not_start_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _probe(monkeypatch, "", rc=125)
    r = capabilities.check()
    assert r["sandbox"] is False and "could not start" in r["note"]


def test_the_check_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _probe(monkeypatch, "has:python3\n")
    capabilities.check()
    capabilities.check()
    assert len(calls) == 1
    capabilities.check(force=True)
    assert len(calls) == 2


def test_settings_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _probe(monkeypatch, "has:python3\nhas:node\n")
    with TestClient(app) as client:
        body = client.get("/api/settings/capabilities").json()
    assert body["sandbox"] is True and body["programs"]["node"] is True
    assert body["labels"]["gh"] == "GitHub CLI"
