"""Tests for git_service and workspace_service (Day 5A).

Uses the CRR2906 repo itself (which exists and is a git repo) for read-only tests.
Write tests use a temp directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

THIS_REPO = str(Path(__file__).parent.parent.parent)


@pytest.fixture(autouse=True)
def _reset_settings():
    from app.config import reset_settings_cache

    reset_settings_cache()  # noqa: E702
    yield
    reset_settings_cache()  # noqa: E702


# ---------------------------------------------------------------------------
# workspace_service
# ---------------------------------------------------------------------------


class TestWorkspaceService:
    def test_assert_in_workspace_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services import workspace_service

        result = workspace_service.assert_in_workspace(str(tmp_path))
        assert result.startswith(str(tmp_path.resolve()))

    def test_assert_in_workspace_denied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services import workspace_service

        with pytest.raises(ValueError, match="outside allowed"):
            workspace_service.assert_in_workspace("/etc/passwd")

    def test_list_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "subdir").mkdir()
        from app.services import workspace_service

        entries = workspace_service.list_directory(str(tmp_path))
        names = {e["name"] for e in entries}
        assert "a.py" in names
        assert "subdir" in names

    def test_is_git_repo_true(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", "/home")
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services import workspace_service

        # CRR2906 is a git repo — has .git directory
        assert workspace_service.is_git_repo(THIS_REPO)

    def test_is_git_repo_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services import workspace_service

        assert not workspace_service.is_git_repo(str(tmp_path))


# ---------------------------------------------------------------------------
# git_service — URL validation
# ---------------------------------------------------------------------------


class TestGitServiceUrlValidation:
    def test_valid_github_url(self):
        from app.services.git_service import _validate_url

        _validate_url(
            "https://github.com/anthropics/anthropic-sdk-python.git"
        )  # no raise

    def test_valid_gitlab_url(self):
        from app.services.git_service import _validate_url

        _validate_url("https://gitlab.com/user/repo.git")

    def test_blocked_unknown_host(self):
        from app.services.git_service import _validate_url

        with pytest.raises(ValueError, match="not in the git allowlist"):
            _validate_url("https://evil.example.com/bad.git")

    def test_localhost_allowed(self):
        from app.services.git_service import _validate_url

        _validate_url("http://localhost:8080/test.git")  # no raise

    def test_workspace_validation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import _validate_workspace

        with pytest.raises(ValueError, match="outside allowed"):
            _validate_workspace("/etc")


# ---------------------------------------------------------------------------
# git_service — async operations on real repo (read-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGitServiceReadOnly:
    async def test_git_status(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", "/home")
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_status

        result = await git_status(THIS_REPO)
        assert result["ok"] is True

    async def test_git_log(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", "/home")
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_log

        result = await git_log(THIS_REPO, limit=5)
        assert result["ok"] is True
        assert len(result["commits"]) >= 1
        assert "sha" in result["commits"][0]

    async def test_git_diff(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", "/home")
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_diff

        result = await git_diff(THIS_REPO, staged=False)
        assert result["ok"] is True  # diff may be empty string

    async def test_git_branch_list(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", "/home")
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_branch_list

        result = await git_branch_list(THIS_REPO)
        assert result["ok"] is True
        assert len(result["branches"]) >= 1


@pytest.mark.asyncio
class TestGitServiceWrite:
    async def test_git_add_blocks_absolute_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        from app.services.git_service import git_add

        with pytest.raises(ValueError, match="absolute path not allowed"):
            await git_add(str(tmp_path), ["/etc/passwd"])

    async def test_git_checkout_invalid_branch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        from app.services.git_service import git_checkout

        with pytest.raises(ValueError, match="Invalid branch name"):
            await git_checkout(str(tmp_path), "../../bad", create=True)

    async def test_commit_empty_message(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_commit

        with pytest.raises(ValueError, match="empty"):
            await git_commit(str(tmp_path), "   ")

    async def test_git_init_creates_real_repo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_init

        target = tmp_path / "new-repo"
        result = await git_init(str(target))
        assert result["ok"] is True
        assert (target / ".git").is_dir()

    async def test_git_init_outside_workspace_denied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_init

        with pytest.raises(ValueError, match="outside allowed"):
            await git_init("/etc/definitely-not-allowed")


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH18 §69 gap-closure — git_revert, the primitive
# app.fleet.enhancement_rollback's automatic quality-decline rollback needs.
# ---------------------------------------------------------------------------


async def _init_repo_with_commit(repo_path, filename: str, content: str) -> str:
    """Real git repo, one file, one commit. Returns that commit's SHA."""
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (Path(repo_path) / filename).write_text(content)
    subprocess.run(
        ["git", "add", filename], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha


@pytest.mark.asyncio
class TestGitRevert:
    async def test_revert_undoes_the_commit_content(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        await _init_repo_with_commit(tmp_path, "f.txt", "original\n")

        f = tmp_path / "f.txt"
        f.write_text("changed by enhancement\n")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True
        )
        commit = subprocess.run(
            ["git", "commit", "-m", "enhancement change"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        bad_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert commit.returncode == 0

        from app.services.git_service import git_revert

        result = await git_revert(str(tmp_path), bad_sha)

        assert result["ok"] is True
        assert result["revertCommitSha"]
        assert result["revertCommitSha"] != bad_sha
        assert f.read_text() == "original\n"

    async def test_revert_empty_sha_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        from app.services.git_service import git_revert

        with pytest.raises(ValueError, match="empty"):
            await git_revert(str(tmp_path), "   ")

    async def test_revert_conflict_aborts_cleanly(self, tmp_path, monkeypatch):
        """A revert that can't apply cleanly must leave the worktree in a
        normal (not half-reverting) state — proves the --abort safety net."""
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        first_sha = await _init_repo_with_commit(tmp_path, "f.txt", "line1\n")

        f = tmp_path / "f.txt"
        f.write_text("line1\nline2 from second commit\n")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "second"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # A third commit that overlaps the same line first_sha touched —
        # reverting first_sha now conflicts with the second commit's change.
        f.write_text("totally different line1\nline2 from second commit\n")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "third"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        from app.services.git_service import git_revert

        result = await git_revert(str(tmp_path), first_sha)

        assert result["ok"] is False
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""  # worktree clean, no stuck revert state
