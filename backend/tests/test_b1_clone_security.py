"""Verification batch B1, items #1/#2 (repo clone into a user-selected folder,
every operation confined to it) — regression tests for defects found by real
execution, not by reading code.

Defects proven live before the fix:

1. `git_service._validate_url` allowed an EMPTY hostname, so a "URL" such as
   `--upload-pack=touch /marker` passed the allowlist, reached `git clone` as
   an option and EXECUTED the command (argument injection -> RCE) — through
   POST /api/console/repos/clone, which needs only a normal login.
2. `git_clone_with_token` embedded the PAT in the clone URL, so git persisted
   it in plaintext in `<repo>/.git/config` (`remote.origin.url`) — readable by
   every agent working in that repo.
3. `workspace_service.assert_in_workspace` used a bare `startswith(parent)`,
   so `/home-evil` was "inside" `/home`.
4. POST /api/repo/clone (the main product route) never validated `dest_path`
   at all, accepted ANY https host, and derived the folder name from the URL
   unsanitised (`.../..` -> the parent directory).

These tests run real `git` against a real local HTTP git server that demands
Basic auth — they do not mock `_run_git`, which is why the pre-existing
`test_token_stripped_from_stderr` could never see defect 2.
"""

from __future__ import annotations

import base64
import http.server
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from app.config import reset_settings_cache


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
    monkeypatch.setenv("REPOS_DIR", str(tmp_path / "repos"))
    reset_settings_cache()
    yield
    reset_settings_cache()


def _git(*args: str, cwd: Path | None = None) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


class _AuthGitServer:
    """Dumb-HTTP git server that requires `Authorization: Basic <user:token>`."""

    def __init__(self, root: Path, token: str) -> None:
        self.seen_auth: list[str | None] = []
        outer = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a: Any, **kw: Any) -> None:
                super().__init__(*a, directory=str(root), **kw)

            def log_message(self, *a: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                got = self.headers.get("Authorization")
                outer.seen_auth.append(got)
                want = (
                    "Basic "
                    + base64.b64encode(f"x-access-token:{token}".encode()).decode()
                )
                if got != want:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="git"')
                    self.end_headers()
                    return
                super().do_GET()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/repo.git"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


TOKEN = "ghp_SECRETTOKEN123"


@pytest.fixture
def server(tmp_path):
    srv_root = tmp_path / "srv"
    srv_root.mkdir()
    _git("init", "-q", "--bare", "repo.git", cwd=srv_root)
    seed = tmp_path / "seed"
    _git("clone", "-q", str(srv_root / "repo.git"), str(seed))
    (seed / "a.txt").write_text("hi\n")
    _git("add", "a.txt", cwd=seed)
    _git("commit", "-qm", "init", cwd=seed)
    _git("push", "-q", "origin", "HEAD:refs/heads/master", cwd=seed)
    _git("symbolic-ref", "HEAD", "refs/heads/master", cwd=srv_root / "repo.git")
    _git("update-server-info", cwd=srv_root / "repo.git")
    srv = _AuthGitServer(srv_root, TOKEN)
    yield srv
    srv.close()


# ---------------------------------------------------------------------------
# Defect 1 — URL allowlist / argument injection
# ---------------------------------------------------------------------------

BAD_URLS = [
    "--upload-pack=touch /tmp/x",
    "-c core.sshCommand=x",
    "ext::sh -c id",
    "/etc",
    "file:///etc/passwd",
    "../../x",
    "",
    " https://github.com/a/b.git",
    "https://github.com/a/b.git\n--upload-pack=x",
    "https://github.com\\@evil.com/x",
    "https://user:pw@github.com/a/b.git",
    "http://github.com/a/b.git",  # cleartext to a real host
    "git://github.com/a/b.git",
    "git@github.com:a/b.git",
    "https://evil.example.com/x.git",
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_validate_url_rejects(url: str) -> None:
    from app.services.git_service import _validate_url

    with pytest.raises(ValueError):
        _validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/a/b.git",
        "https://gitlab.com/a/b",
        "https://bitbucket.org/a/b.git",
        "http://localhost:8080/t.git",
        "http://127.0.0.1:1/x",
    ],
)
def test_validate_url_accepts(url: str) -> None:
    from app.services.git_service import _validate_url

    _validate_url(url)


async def test_injected_url_never_executes_a_command(tmp_path) -> None:
    """The exact live PoC: an --upload-pack URL + a local repo as 'dest'."""
    from app.services import git_service

    local_repo = tmp_path / "victim.git"
    _git("init", "-q", "--bare", str(local_repo))
    marker = tmp_path / "PWNED"
    with pytest.raises(ValueError):
        await git_service.git_clone(f"--upload-pack=touch {marker}", str(local_repo))
    assert not marker.exists(), "injected option was executed"


@pytest.mark.parametrize(
    "branch", ["--upload-pack=x", "-x", "a b", "a..b", "a\nb", "x;y", "/abs"]
)
async def test_bad_branch_rejected(tmp_path, branch: str) -> None:
    from app.services import git_service

    with pytest.raises(ValueError):
        await git_service.git_clone(
            "https://github.com/a/b.git", str(tmp_path / "d"), branch
        )


async def test_relative_or_escaping_dest_rejected(tmp_path) -> None:
    from app.services import git_service

    for dest in ("relative/dir", "-rf", "/etc/gridiron-x", str(tmp_path / ".." / "up")):
        with pytest.raises(ValueError):
            await git_service.git_clone("https://github.com/a/b.git", dest)


# ---------------------------------------------------------------------------
# Defect 2 — PAT must never be persisted in the cloned repo
# ---------------------------------------------------------------------------


async def test_token_clone_works_and_token_not_on_disk(tmp_path, server) -> None:
    from app.services import git_service

    dest = tmp_path / "work" / "cloned"
    dest.parent.mkdir()
    result = await git_service.git_clone_with_token(server.url, str(dest), TOKEN)
    assert result["ok"], result
    assert (dest / "a.txt").read_text() == "hi\n"
    # the server really received the credential (auth was not bypassed)
    assert any(h and h.startswith("Basic ") for h in server.seen_auth)
    # ... and it is nowhere in the cloned repository's own metadata
    for p in (dest / ".git").rglob("*"):
        if p.is_file() and p.stat().st_size < 1_000_000:
            data = p.read_bytes()
            assert TOKEN.encode() not in data, f"token persisted in {p}"
            assert base64.b64encode(f"x-access-token:{TOKEN}".encode()) not in data
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=dest, capture_output=True, text=True
    ).stdout.strip()
    assert remote == server.url


async def test_token_never_in_argv(tmp_path, server, monkeypatch) -> None:
    """argv is world-readable via ps/proc — the token must travel by env."""
    from app.services import git_service

    seen_args: list[list[str]] = []
    real = git_service._run_git

    async def spy(args, *a, **kw):
        seen_args.append(list(args))
        return await real(args, *a, **kw)

    monkeypatch.setattr(git_service, "_run_git", spy)
    dest = tmp_path / "w2"
    result = await git_service.git_clone_with_token(server.url, str(dest), TOKEN)
    assert result["ok"], result
    flat = " ".join(" ".join(a) for a in seen_args)
    assert TOKEN not in flat
    assert base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode() not in flat


async def test_userinfo_in_url_is_stripped_not_persisted(tmp_path, server) -> None:
    from app.services import git_service

    url_with_token = server.url.replace("http://", f"http://{TOKEN}@", 1)
    dest = tmp_path / "w3"
    result = await git_service.git_clone_with_token(url_with_token, str(dest), TOKEN)
    assert result["ok"], result
    assert TOKEN not in (dest / ".git" / "config").read_text()


async def test_wrong_token_fails_and_is_not_echoed(tmp_path, server) -> None:
    from app.services import git_service

    dest = tmp_path / "w4"
    bad = "ghp_WRONGTOKEN999"
    result = await git_service.git_clone_with_token(server.url, str(dest), bad)
    assert result["ok"] is False
    assert bad not in result["stderr"]
    assert (
        base64.b64encode(f"x-access-token:{bad}".encode()).decode()
        not in result["stderr"]
    )
    assert not (dest / ".git" / "config").exists()


async def test_wrong_token_fails_fast_even_with_a_password_helper(
    tmp_path, server, monkeypatch
) -> None:
    """Qoder cross-check SEC-05-101 (2026-10-02): with GIT_ASKPASS set (VS Code
    and desktop sessions set it), git asked that helper on the 401 and the
    clone hung forever (reproduced: killed after 90 s). git must never ask a
    helper; a wrong token has to fail fast."""
    import time

    from app.services import git_service

    helper = tmp_path / "never-answers.sh"
    helper.write_text("#!/bin/sh\nsleep 600\n")
    helper.chmod(0o755)
    monkeypatch.setenv("GIT_ASKPASS", str(helper))
    monkeypatch.setenv("SSH_ASKPASS", str(helper))

    started = time.monotonic()
    result = await git_service.git_clone_with_token(
        server.url, str(tmp_path / "w5"), "ghp_WRONGTOKEN999"
    )
    assert result["ok"] is False
    assert time.monotonic() - started < 30, "clone waited on the password helper"


# ---------------------------------------------------------------------------
# Defect 3 — workspace prefix confusion
# ---------------------------------------------------------------------------


def test_workspace_prefix_sibling_is_outside(tmp_path) -> None:
    from app.services import git_service, workspace_service

    sibling = str(tmp_path) + "-evil"
    with pytest.raises(ValueError):
        workspace_service.assert_in_workspace(sibling)
    with pytest.raises(ValueError):
        git_service._validate_workspace(sibling)
    # the parent itself and real children are still fine
    workspace_service.assert_in_workspace(str(tmp_path))
    workspace_service.assert_in_workspace(str(tmp_path / "child" / "deep"))


# ---------------------------------------------------------------------------
# Defect 4 — POST /api/repo/clone (main product route)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import repo as repo_api
    from app.main import app

    calls: list[tuple] = []

    async def fake_clone(*args: Any, **kw: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(repo_api, "_clone_and_activate", fake_clone)
    c = TestClient(app)
    c.calls = calls  # type: ignore[attr-defined]
    return c


@pytest.mark.parametrize(
    "payload",
    [
        {"github_url": "https://evil.example.com/x/y.git"},  # host not allowlisted
        {"github_url": "https://github.com/x/.."},  # traversal via derived name
        {"github_url": "https://github.com/x/y.git", "dest_path": "/etc/gridiron-b1"},
        {"github_url": "https://github.com/x/y.git", "dest_path": "relative/path"},
        {"github_url": "https://github.com/x/y.git", "branch": "--upload-pack=x"},
        {"github_url": "http://github.com/x/y.git"},
        {"github_url": "https://user:pw@github.com/x/y.git"},
    ],
)
def test_route_rejects_unsafe_clone_requests(client, payload) -> None:
    r = client.post("/api/repo/clone", json=payload)
    assert r.status_code == 400, r.text
    assert client.calls == [], "a clone was scheduled for a rejected request"


def test_route_accepts_safe_request_default_dest(client, tmp_path) -> None:
    r = client.post(
        "/api/repo/clone", json={"github_url": "https://github.com/x/safe.git"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["localPath"] == str(tmp_path / "repos" / "safe")
    assert len(client.calls) == 1


def test_route_accepts_dest_inside_workspace(client, tmp_path) -> None:
    dest = str(tmp_path / "mine" / "proj")
    r = client.post(
        "/api/repo/clone",
        json={"github_url": "https://github.com/x/ok2.git", "dest_path": dest},
    )
    assert r.status_code == 200, r.text
    assert r.json()["localPath"] == dest


# ---------------------------------------------------------------------------
# Defect 5 — option injection through checkout / push / pull / revert
# (console routes; checkout+push need approver, pull needs only a login)
# ---------------------------------------------------------------------------


def _mk_repo_with_local_remote(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(bare))
    repo = tmp_path / "repo"
    _git("clone", "-q", str(bare), str(repo))
    (repo / "f.txt").write_text("v1\n")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-qm", "c1", cwd=repo)
    _git("branch", "-M", "master", cwd=repo)
    _git("push", "-q", "origin", "master", cwd=repo)
    return repo, bare


@pytest.mark.parametrize(
    "branch", ["-f", "--force", "--detach", "--orphan", "-B", "--ours", "--"]
)
async def test_checkout_option_injection_rejected_and_work_preserved(
    tmp_path, branch: str
) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    (repo / "f.txt").write_text("UNCOMMITTED WORK\n")
    with pytest.raises(ValueError):
        await git_service.git_checkout(str(repo), branch)
    # `checkout -f` used to pass the old regex and silently discard this:
    assert (repo / "f.txt").read_text() == "UNCOMMITTED WORK\n"


async def test_checkout_legit_branches_still_work(tmp_path) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    r = await git_service.git_checkout(str(repo), "feature/x-1.2", create=True)
    assert r["ok"], r


@pytest.mark.parametrize("remote", ["--force", "--receive-pack=touch X", "-o", "a b"])
async def test_push_remote_option_injection_rejected(tmp_path, remote: str) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    marker = tmp_path / "PWNED_PUSH"
    remote = remote.replace("touch X", f"touch {marker}")
    with pytest.raises(ValueError):
        await git_service.git_push(str(repo), remote)
    assert not marker.exists()


@pytest.mark.parametrize("branch", ["--force", "--delete", "-f", "--all", "a..b"])
async def test_push_branch_option_injection_rejected(tmp_path, branch: str) -> None:
    """branch='--force' turned a normal push into a force-push."""
    from app.services import git_service

    repo, bare = _mk_repo_with_local_remote(tmp_path)
    (repo / "f.txt").write_text("v2\n")
    _git("commit", "-qam", "c2", cwd=repo)
    with pytest.raises(ValueError):
        await git_service.git_push(str(repo), "origin", branch)


async def test_push_legit_to_local_remote_still_works(tmp_path) -> None:
    from app.services import git_service

    repo, bare = _mk_repo_with_local_remote(tmp_path)
    (repo / "f.txt").write_text("v2\n")
    _git("commit", "-qam", "c2", cwd=repo)
    r = await git_service.git_push(str(repo), "origin", "master")
    assert r["ok"], r
    tip = subprocess.run(
        ["git", "rev-parse", "master"], cwd=bare, capture_output=True, text=True
    ).stdout.strip()
    local = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert tip == local


async def test_push_refuses_remote_on_non_allowlisted_host(tmp_path) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    _git("remote", "set-url", "origin", "https://evil.example.com/x.git", cwd=repo)
    with pytest.raises(ValueError, match="allowlist"):
        await git_service.git_push(str(repo), "origin", "master")


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c id",
        "--upload-pack=x",
        "ftp://github.com/a/b",
        "git@evil.example.com:a/b.git",
    ],
)
def test_remote_url_validator_rejects(url: str) -> None:
    from app.services.git_service import _validate_remote_url

    with pytest.raises(ValueError):
        _validate_remote_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:a/b.git",
        "ssh://git@github.com/a/b.git",
        "https://TOKEN@github.com/a/b.git",  # legacy repo cloned with a token URL
        "/srv/git/repo.git",
        "../origin.git",
    ],
)
def test_remote_url_validator_accepts_real_world_remotes(url: str) -> None:
    from app.services.git_service import _validate_remote_url

    _validate_remote_url(url)


@pytest.mark.parametrize("remote", ["--upload-pack=touch X", "--rebase", "-f", "a b"])
async def test_pull_remote_option_injection_rejected(tmp_path, remote: str) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    marker = tmp_path / "PWNED_PULL"
    remote = remote.replace("touch X", f"touch {marker}")
    with pytest.raises(ValueError):
        await git_service.git_pull(str(repo), remote)
    assert not marker.exists()


async def test_pull_legit_remote_still_works(tmp_path) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    r = await git_service.git_pull(str(repo), "origin")
    assert r["ok"], r


@pytest.mark.parametrize("sha", ["--abort", "--no-commit", "-m1", "a b", "--continue"])
async def test_revert_option_injection_rejected(tmp_path, sha: str) -> None:
    from app.services import git_service

    repo, _ = _mk_repo_with_local_remote(tmp_path)
    with pytest.raises(ValueError):
        await git_service.git_revert(str(repo), sha)


# ---------------------------------------------------------------------------
# Defect 4b — the real background clone/pull (DB + real git + auth server)
# ---------------------------------------------------------------------------


async def test_background_clone_and_pull_use_env_credentials_not_url(
    tmp_path, server, monkeypatch
) -> None:
    from sqlalchemy import delete, select

    from app.api import repo as repo_api
    from app.db.models import Repo
    from app.db.session import get_async_session

    monkeypatch.setattr(repo_api, "_active_repo_path", None)
    dest = tmp_path / "bg" / "cloned"
    async with get_async_session() as db:
        row = Repo(
            github_url=server.url,
            name="cloned",
            local_path=str(dest),
            status="cloning",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        repo_id = row.id
    try:
        # 1) fresh clone of a repo that REQUIRES auth
        await repo_api._clone_and_activate(repo_id, server.url, str(dest), None, TOKEN)
        async with get_async_session() as db:
            st = (await db.execute(select(Repo).where(Repo.id == repo_id))).scalar_one()
            assert st.status == "ready", st.error_msg
        assert (dest / "a.txt").exists()
        for p in (dest / ".git").rglob("*"):
            if p.is_file() and p.stat().st_size < 1_000_000:
                assert TOKEN.encode() not in p.read_bytes(), f"token on disk: {p}"
        # 2) re-trigger on an existing clone = `git pull`, must still authenticate
        server.seen_auth.clear()
        await repo_api._clone_and_activate(repo_id, server.url, str(dest), None, TOKEN)
        assert any(h and h.startswith("Basic ") for h in server.seen_auth)
        # 3) wrong token => status=error and the token never lands in the DB row
        bad = "ghp_BADTOKEN456"
        async with get_async_session() as db:
            row2 = Repo(
                github_url=server.url + "?x=2",
                name="c2",
                local_path=str(tmp_path / "bg" / "c2"),
                status="cloning",
            )
            db.add(row2)
            await db.commit()
            await db.refresh(row2)
            id2 = row2.id
        await repo_api._clone_and_activate(
            id2, server.url, str(tmp_path / "bg" / "c2"), None, bad
        )
        async with get_async_session() as db:
            st2 = (await db.execute(select(Repo).where(Repo.id == id2))).scalar_one()
            assert st2.status == "error"
            assert bad not in (st2.error_msg or "")
    finally:
        async with get_async_session() as db:
            await db.execute(delete(Repo).where(Repo.github_url.like(server.url + "%")))
            await db.commit()
