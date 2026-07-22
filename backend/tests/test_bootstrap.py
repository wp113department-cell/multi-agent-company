"""Day 15 — Blank Repo Bootstrap.

is_blank_repo()/detect_project_type() tested directly. bootstrap()'s
orchestration tested against a REAL temp git repo (real git_init/git_add/
git_commit — the actual point of this feature is that a real commit lands),
with run_scaffold_planning()/run_coder() mocked at their bootstrap.py import
site since they're independently a full LLM-agent-graph run each (already
covered by architect.py/coder.py's own test coverage) — this file is about
bootstrap's phase orchestration and git mechanics, not re-testing agent
internals.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.bootstrap import BootstrapResult, is_blank_repo


@pytest.fixture(autouse=True)
def _reset_settings():
    from app.config import reset_settings_cache

    reset_settings_cache()  # noqa: E702
    yield
    reset_settings_cache()  # noqa: E702


# ---------------------------------------------------------------------------
# is_blank_repo
# ---------------------------------------------------------------------------


class TestIsBlankRepo:
    def test_true_for_directory_with_no_git_at_all(self, tmp_path):
        assert is_blank_repo(str(tmp_path)) is True

    def test_true_for_git_init_with_zero_commits(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        assert is_blank_repo(str(tmp_path)) is True

    def test_false_for_repo_with_a_real_commit(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True
        )
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)
        assert is_blank_repo(str(tmp_path)) is False

    def test_nonexistent_path_is_blank(self, tmp_path):
        assert is_blank_repo(str(tmp_path / "does-not-exist")) is True


# ---------------------------------------------------------------------------
# detect_project_type
# ---------------------------------------------------------------------------


class TestDetectProjectType:
    async def test_parses_valid_type_from_response(self):
        from app.pipeline.bootstrap import detect_project_type

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = type(
                "R", (), {"content": [type("B", (), {"type": "text", "text": "cli"})()]}
            )()
            mock_anthropic.return_value.messages.create.return_value = mock_response
            result = await detect_project_type("Build a command-line tool", "haiku")
        assert result == "cli"

    async def test_falls_back_on_exception(self):
        from app.pipeline.bootstrap import detect_project_type

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")):
            result = await detect_project_type("Build something", "haiku")
        assert result == "web-app"

    async def test_falls_back_when_response_has_no_matching_type(self):
        from app.pipeline.bootstrap import detect_project_type

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = type(
                "R",
                (),
                {"content": [type("B", (), {"type": "text", "text": "unknown-thing"})()]},
            )()
            mock_anthropic.return_value.messages.create.return_value = mock_response
            result = await detect_project_type("???", "haiku")
        assert result == "web-app"


# ---------------------------------------------------------------------------
# bootstrap() orchestration
# ---------------------------------------------------------------------------


class TestBootstrap:
    async def test_noop_when_repo_not_blank(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True
        )
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)

        from app.pipeline.bootstrap import bootstrap

        with patch("app.pipeline.bootstrap.run_scaffold_planning") as mock_plan:
            result = await bootstrap(1, str(tmp_path), "some task")
        assert result.bootstrapped is False
        assert result.error is None
        mock_plan.assert_not_called()

    async def test_full_success_creates_real_commit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        repo = tmp_path / "blank-repo"
        repo.mkdir()

        from app.pipeline.bootstrap import bootstrap

        def _fake_coder(task_id, plan, worktree_path, repo_path):
            (repo / "main.py").write_text("print('hello')\n")
            return (["main.py"], None, 100, 50)

        with patch(
            "app.pipeline.bootstrap.detect_project_type",
            new=AsyncMock(return_value="cli"),
        ), patch(
            "app.pipeline.bootstrap.run_scaffold_planning",
            return_value={"technical_approach": "minimal CLI", "files": [{"path": "main.py", "reason": "entry point"}]},
        ), patch("app.agents.coder.run_coder", side_effect=_fake_coder):
            result = await bootstrap(1, str(repo), "Build a CLI tool")

        assert result.bootstrapped is True
        assert result.project_type == "cli"
        assert result.files_created == ["main.py"]
        assert result.commit_sha is not None
        assert result.error is None
        assert (repo / ".git").is_dir()

        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
        )
        assert "chore: initial scaffold by gridiron" in log.stdout

    async def test_scaffold_planning_failure_is_non_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        repo = tmp_path / "blank-repo"
        repo.mkdir()

        from app.pipeline.bootstrap import bootstrap

        with patch(
            "app.pipeline.bootstrap.detect_project_type",
            new=AsyncMock(return_value="api"),
        ), patch(
            "app.pipeline.bootstrap.run_scaffold_planning",
            side_effect=RuntimeError("architect never submitted"),
        ):
            result = await bootstrap(1, str(repo), "Build an API")

        assert result.bootstrapped is False
        assert result.error is not None
        assert "Scaffold planning failed" in result.error
        # No commit should exist — the repo is still blank
        assert is_blank_repo(str(repo)) is True

    async def test_coder_error_is_non_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        repo = tmp_path / "blank-repo"
        repo.mkdir()

        from app.pipeline.bootstrap import bootstrap

        with patch(
            "app.pipeline.bootstrap.detect_project_type",
            new=AsyncMock(return_value="library"),
        ), patch(
            "app.pipeline.bootstrap.run_scaffold_planning",
            return_value={"technical_approach": "x", "files": []},
        ), patch(
            "app.agents.coder.run_coder",
            return_value=([], "Coder agent error: rate limited", 0, 0),
        ):
            result = await bootstrap(1, str(repo), "Build a library")

        assert result.bootstrapped is False
        assert result.error == "Coder agent error: rate limited"

    async def test_coder_no_files_is_non_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        repo = tmp_path / "blank-repo"
        repo.mkdir()

        from app.pipeline.bootstrap import bootstrap

        with patch(
            "app.pipeline.bootstrap.detect_project_type",
            new=AsyncMock(return_value="data-pipeline"),
        ), patch(
            "app.pipeline.bootstrap.run_scaffold_planning",
            return_value={"technical_approach": "x", "files": []},
        ), patch("app.agents.coder.run_coder", return_value=([], None, 0, 0)):
            result = await bootstrap(1, str(repo), "Build a pipeline")

        assert result.bootstrapped is False
        assert result.error == "Scaffold write produced no files"

    async def test_uses_explicit_project_type_without_detection_call(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        repo = tmp_path / "blank-repo"
        repo.mkdir()

        from app.pipeline.bootstrap import bootstrap

        def _fake_coder(task_id, plan, worktree_path, repo_path):
            (repo / "index.html").write_text("<html></html>")
            return (["index.html"], None, 10, 10)

        with patch("app.pipeline.bootstrap.detect_project_type") as mock_detect, patch(
            "app.pipeline.bootstrap.run_scaffold_planning",
            return_value={"technical_approach": "x", "files": []},
        ), patch("app.agents.coder.run_coder", side_effect=_fake_coder):
            result = await bootstrap(1, str(repo), "Build a site", project_type="web-app")

        mock_detect.assert_not_called()
        assert result.bootstrapped is True
        assert result.project_type == "web-app"

    async def test_db_none_does_not_crash_logging(self, tmp_path, monkeypatch):
        """bootstrap() must work with db=None (e.g. called before a DB session
        is available) — logging is best-effort, never required."""
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        repo = tmp_path / "blank-repo"
        repo.mkdir()

        from app.pipeline.bootstrap import bootstrap

        with patch(
            "app.pipeline.bootstrap.detect_project_type",
            new=AsyncMock(return_value="cli"),
        ), patch(
            "app.pipeline.bootstrap.run_scaffold_planning",
            side_effect=RuntimeError("boom"),
        ):
            result = await bootstrap(1, str(repo), "task", db=None)
        assert result.bootstrapped is False
