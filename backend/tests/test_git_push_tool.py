"""Day 14 — app/tools/git_push_tool.py: commit-message generation + real
GitHub PR creation via the REST API. Does not test git operations directly —
app/services/git_service.py (Day 5A) already has its own dedicated test
coverage (tests/test_git_service.py) for git_add/git_commit/git_push; this
module only adds what was missing on top of that.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.git_push_tool import (
    GitHubAPIError,
    PushResult,
    create_github_pr,
    generate_commit_message,
    parse_repo_full_name,
    push_and_create_pr,
)


class TestParseRepoFullName:
    def test_plain_https_url(self) -> None:
        assert parse_repo_full_name("https://github.com/owner/repo") == "owner/repo"

    def test_https_url_with_git_suffix(self) -> None:
        assert parse_repo_full_name("https://github.com/owner/repo.git") == "owner/repo"

    def test_https_url_with_embedded_token(self) -> None:
        assert (
            parse_repo_full_name("https://ghp_abc123@github.com/owner/repo.git")
            == "owner/repo"
        )

    def test_ssh_url(self) -> None:
        assert parse_repo_full_name("git@github.com:owner/repo.git") == "owner/repo"

    def test_trailing_slash(self) -> None:
        assert parse_repo_full_name("https://github.com/owner/repo/") == "owner/repo"

    def test_unparseable_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_repo_full_name("not a url at all")


class TestCreateGithubPr:
    @pytest.mark.asyncio
    async def test_success_returns_html_url_and_number(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "html_url": "https://github.com/owner/repo/pull/42",
            "number": 42,
            "state": "open",
        }
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__.return_value = mock_client

            pr = await create_github_pr(
                "owner/repo", "agent/task-1", "main", "feat: test", "body", "faketoken"
            )

        assert pr == {
            "html_url": "https://github.com/owner/repo/pull/42",
            "number": 42,
            "state": "open",
        }
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer faketoken"
        assert call_kwargs["json"]["draft"] is True

    @pytest.mark.asyncio
    async def test_no_token_raises_401_without_calling_api(self) -> None:
        with patch("httpx.AsyncClient") as MockClient:
            with pytest.raises(GitHubAPIError) as exc_info:
                await create_github_pr("owner/repo", "b", "main", "t", "b", "")
            MockClient.assert_not_called()
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_github_error_response_raises_with_status_and_message(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"message": "Validation Failed"}
        mock_response.text = "Validation Failed"
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__.return_value = mock_client

            with pytest.raises(GitHubAPIError) as exc_info:
                await create_github_pr("owner/repo", "b", "main", "t", "b", "tok")

        assert exc_info.value.status_code == 422
        assert "Validation Failed" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_token_never_appears_in_raised_exception(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"message": "Bad credentials"}
        mock_response.text = "Bad credentials"
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__.return_value = mock_client

            with pytest.raises(GitHubAPIError) as exc_info:
                await create_github_pr(
                    "owner/repo", "b", "main", "t", "b", "super-secret-token-value"
                )

        assert "super-secret-token-value" not in str(exc_info.value)


class TestGenerateCommitMessage:
    @pytest.mark.asyncio
    @patch("app.agents.base.get_effective_api_key", return_value="test-key")
    @patch("anthropic.Anthropic")
    async def test_returns_llm_generated_message(
        self, mock_anthropic_cls: Any, _key: Any
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="feat(api): add hello endpoint")]
        )
        mock_anthropic_cls.return_value = mock_client

        message = await generate_commit_message(
            "Add hello endpoint", "diff --git a/x b/x", "claude-haiku-4-5-20251001"
        )
        assert message == "feat(api): add hello endpoint"

    @pytest.mark.asyncio
    @patch("app.agents.base.get_effective_api_key", return_value="test-key")
    @patch("anthropic.Anthropic")
    async def test_falls_back_on_llm_failure(
        self, mock_anthropic_cls: Any, _key: Any
    ) -> None:
        mock_anthropic_cls.side_effect = RuntimeError("API down")

        message = await generate_commit_message(
            "Add hello endpoint", "diff", "claude-haiku-4-5-20251001"
        )
        assert message == "feat: Add hello endpoint"

    @pytest.mark.asyncio
    @patch("app.agents.base.get_effective_api_key", return_value="test-key")
    @patch("anthropic.Anthropic")
    async def test_falls_back_on_empty_llm_response(
        self, mock_anthropic_cls: Any, _key: Any
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(content=[])
        mock_anthropic_cls.return_value = mock_client

        message = await generate_commit_message(
            "Add hello endpoint", "diff", "claude-haiku-4-5-20251001"
        )
        assert message == "feat: Add hello endpoint"


class TestPushAndCreatePr:
    @pytest.mark.asyncio
    async def test_full_success_path(self) -> None:
        with patch("app.services.git_service.git_push") as mock_push, patch(
            "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
        ), patch(
            "app.tools.git_push_tool.generate_commit_message",
            return_value="feat: add x",
        ) as mock_msg, patch(
            "app.tools.git_push_tool.create_github_pr"
        ) as mock_create_pr:
            mock_push.return_value = {"ok": True, "stdout": "", "stderr": ""}
            mock_create_pr.return_value = {
                "html_url": "https://github.com/owner/repo/pull/7",
                "number": 7,
                "state": "open",
            }

            result = await push_and_create_pr(
                task_id=42,
                task_title="Add x",
                task_description="desc",
                repo_path="/repo",
                github_url="https://github.com/owner/repo",
                token="tok",
            )

        assert result == PushResult(
            pushed=True,
            pr_url="https://github.com/owner/repo/pull/7",
            pr_number=7,
            error=None,
        )
        mock_push.assert_called_once_with(
            "/repo", remote="origin", branch="agent/task-42"
        )
        mock_msg.assert_called_once()
        mock_create_pr.assert_called_once()
        assert mock_create_pr.call_args.kwargs["repo_full_name"] == "owner/repo"
        assert mock_create_pr.call_args.kwargs["source_branch"] == "agent/task-42"

    @pytest.mark.asyncio
    async def test_push_failure_returns_error_without_attempting_pr(self) -> None:
        with patch("app.services.git_service.git_push") as mock_push, patch(
            "app.tools.git_push_tool.create_github_pr"
        ) as mock_create_pr:
            mock_push.return_value = {
                "ok": False,
                "stdout": "",
                "stderr": "remote rejected",
            }

            result = await push_and_create_pr(
                task_id=42,
                task_title="Add x",
                task_description="desc",
                repo_path="/repo",
                github_url="https://github.com/owner/repo",
                token="tok",
            )

        assert result.pushed is False
        assert result.pr_url is None
        assert "remote rejected" in (result.error or "")
        mock_create_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_pr_creation_failure_still_reports_pushed_true(self) -> None:
        """Push succeeded (real work is on the remote) even if PR creation
        fails afterward — the caller (approvals dispatch) needs to know the
        push itself landed, distinct from the PR step failing."""
        with patch("app.services.git_service.git_push") as mock_push, patch(
            "app.repo_tools.worktree.get_diff", return_value=""
        ), patch(
            "app.tools.git_push_tool.generate_commit_message", return_value="feat: x"
        ), patch(
            "app.tools.git_push_tool.create_github_pr"
        ) as mock_create_pr:
            mock_push.return_value = {"ok": True, "stdout": "", "stderr": ""}
            mock_create_pr.side_effect = GitHubAPIError(401, "Bad credentials")

            result = await push_and_create_pr(
                task_id=42,
                task_title="Add x",
                task_description="desc",
                repo_path="/repo",
                github_url="https://github.com/owner/repo",
                token="badtok",
            )

        assert result.pushed is True
        assert result.pr_url is None
        assert "Bad credentials" in (result.error or "")

    @pytest.mark.asyncio
    async def test_unparseable_github_url_reports_error(self) -> None:
        with patch("app.services.git_service.git_push") as mock_push, patch(
            "app.repo_tools.worktree.get_diff", return_value=""
        ), patch(
            "app.tools.git_push_tool.generate_commit_message", return_value="feat: x"
        ):
            mock_push.return_value = {"ok": True, "stdout": "", "stderr": ""}

            result = await push_and_create_pr(
                task_id=42,
                task_title="Add x",
                task_description="desc",
                repo_path="/repo",
                github_url="not-a-github-url",
                token="tok",
            )

        assert result.pushed is True
        assert result.pr_url is None
        assert "Could not parse" in (result.error or "")
