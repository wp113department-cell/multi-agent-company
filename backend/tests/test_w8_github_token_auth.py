"""W8 (2026-10-19): private GitHub repos work with the app's own token.

Found by the live W8 run against real GitHub repos: the delivery push sent no
token at all, and a private repo added without typing a token was cloned
with none, so both worked only on a machine already logged in to GitHub
(the developer's `gh` credential helper) and failed on every server and in
Docker. Now both send the app's GitHub token as a host-scoped header with
other credential helpers switched off, and never to a host that is not
GitHub. Live result after the fix: private clone, push + PR (draft), and a
PR into a `develop` default branch all passed with no machine login.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from unittest.mock import patch

import pytest

from app.services import git_service
from tests.test_w6_target_branch import _push, github_task  # noqa: F401

TOKEN = "github_pat_test_not_real"


def _header(env: dict[str, str] | None) -> str:
    return (env or {}).get("GIT_CONFIG_VALUE_0", "")


@pytest.mark.parametrize(
    "url",
    ["https://github.com/o/r", "https://github.com/o/r.git"],
)
def test_the_github_token_is_sent_to_github(url: str) -> None:
    env = git_service.github_auth_env(url, TOKEN)
    basic = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    assert _header(env) == f"Authorization: Basic {basic}"
    # the machine's own logins (e.g. gh) are not consulted
    assert env and env["GIT_CONFIG_KEY_1"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_1"] == ""


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/o/r",
        "https://github.com.evil.example/o/r",
        "http://github.com/o/r",
        "git@github.com:o/r.git",
    ],
)
def test_the_github_token_never_goes_to_another_host(url: str) -> None:
    assert git_service.github_auth_env(url, TOKEN) is None


def test_push_authenticates_with_the_token_and_hides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    async def fake_run_git(
        args: list[str], cwd: Any = None, timeout: float = 0, env: Any = None
    ) -> tuple[int, str, str]:
        calls.append((args, env))
        if args[:2] == ["remote", "get-url"]:
            return 0, "https://github.com/o/r\n", ""
        return 128, "", f"denied for {TOKEN}"

    monkeypatch.setattr(git_service, "_validate_workspace", lambda *_a, **_k: None)
    monkeypatch.setattr(git_service, "_run_git", fake_run_git)
    result = asyncio.run(
        git_service.git_push("/repo", "origin", "agent/task-1", token=TOKEN)
    )
    push_args, push_env = calls[-1]
    assert push_args == ["push", "origin", "agent/task-1"]
    assert _header(push_env).startswith("Authorization: Basic ")
    assert TOKEN not in result["stderr"]


def test_delivery_uses_the_repositorys_own_token_first(github_task) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    from app.db.models import DevTask
    from app.db.repository import set_setting
    from app.security.credential_vault import scoped_credential_key
    from tests.test_w6_target_branch import _db

    task_id, _ = github_task

    async def scoped(s):  # type: ignore[no-untyped-def]
        task = await s.get(DevTask, task_id)
        await set_setting(
            s, scoped_credential_key("github_token", task.repo_id), "repo-token"
        )
        await s.commit()

    _db(scoped)
    assert _push(task_id)["token"] == "repo-token"


def test_a_private_repo_is_cloned_with_the_saved_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    seen: dict[str, Any] = {}

    async def fake_clone(*_a: Any, **kw: Any) -> int:
        seen.update(kw)
        raise RuntimeError("stop after the clone call")

    monkeypatch.setattr(get_settings(), "github_token", TOKEN)
    monkeypatch.setattr("app.db.repository.get_setting", _no_saved_setting)
    with patch("app.api.projects._clone_for_project", side_effect=fake_clone):
        with TestClient(app, raise_server_exceptions=False) as client:
            for url in ("https://github.com/o/private", "https://gitlab.com/o/r"):
                client.post(
                    "/api/projects",
                    json={"name": "w8", "setup": "github_existing", "github_url": url},
                )
                seen[url] = seen.pop("token", "missing")
    assert seen["https://github.com/o/private"] == TOKEN
    assert seen["https://gitlab.com/o/r"] is None


async def _no_saved_setting(*_a: Any, **_k: Any) -> None:
    return None
