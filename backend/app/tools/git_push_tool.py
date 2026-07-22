"""Git Push Workflow — Day 14.

Pattern sources (read before writing this file):
- repos/open-hands/openhands/app_server/integrations/github/service/prs.py —
  GitHubPRsMixin.create_pr(): POST {base}/repos/{repo}/pulls with
  {title, head, base, body, draft}, returns response['html_url']. Simple
  enough to implement directly against the real REST API.
- repos/aider/aider/repo.py — GitRepo.commit()'s real attribution mechanism
  is GIT_AUTHOR_NAME/GIT_COMMITTER_NAME env vars, which is exactly what
  app/services/git_service.py's existing git_commit() already does — reused,
  not reimplemented.

This module does NOT do git operations itself — app/services/git_service.py
(Day 5A) already has a full async, secure git-ops layer (host-allowlisted,
workspace-scoped, no shell=True, tokens scrubbed from logs). This module adds
exactly what's missing: a Haiku-generated commit message and real GitHub PR
creation via the REST API (the existing app/agents/tools.py git_push/
create_pr/github_create_pr are interactive chat-agent tools that shell out to
the gh CLI — a different, non-automatable-in-a-backend-service mechanism).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API error {status_code}: {message}")


@dataclass
class PushResult:
    pushed: bool
    pr_url: str | None
    pr_number: int | None
    error: str | None = None


def parse_repo_full_name(github_url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL (with or without .git suffix,
    with or without an embedded token). Raises ValueError if unparseable."""
    # Strip any embedded credentials (https://TOKEN@github.com/... or user:pass@)
    cleaned = re.sub(r"https://[^@/]+@", "https://", github_url.strip())
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?/?$", cleaned)
    if not match:
        raise ValueError(f"Could not parse owner/repo from GitHub URL: {github_url!r}")
    return f"{match.group(1)}/{match.group(2)}"


async def generate_commit_message(task_title: str, diff: str, model: str) -> str:
    """One Haiku call: (task_title, diff) -> a single-line conventional commit
    message for the PR title. Falls back to a deterministic message on any
    failure — never raises."""
    import anthropic

    from app.agents.base import get_effective_api_key

    prompt = (
        "Write a single-line conventional commit message (type(scope): description, "
        "under 72 chars) summarizing this change. Respond with ONLY the commit message "
        "line, no quotes, no explanation.\n\n"
        f"Task: {task_title[:200]}\n\nDiff (truncated):\n{diff[:3000]}"
    )
    try:
        client = anthropic.Anthropic(api_key=get_effective_api_key())
        r = client.messages.create(model=model, max_tokens=100, messages=[{"role": "user", "content": prompt}])
        text_blocks = []
        for b in r.content:
            if b.type == "text":
                text_blocks.append(b.text)
        message = " ".join(text_blocks).strip().splitlines()[0].strip() if text_blocks else ""
        return message or f"feat: {task_title[:60]}"
    except Exception as exc:
        logger.warning("generate_commit_message failed (non-fatal), using fallback: %s", exc)
        return f"feat: {task_title[:60]}"


async def create_github_pr(
    repo_full_name: str,
    source_branch: str,
    target_branch: str,
    title: str,
    body: str,
    token: str,
    draft: bool = True,
) -> dict[str, Any]:
    """POST {base}/repos/{repo}/pulls. Raises GitHubAPIError on failure —
    token is never included in the exception message or logged."""
    if not token:
        raise GitHubAPIError(401, "No GitHub token configured")

    settings = get_settings()
    url = f"{settings.github_api_base_url}/repos/{repo_full_name}/pulls"
    payload = {"title": title, "head": source_branch, "base": target_branch, "body": body, "draft": draft}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        try:
            detail = resp.json().get("message", resp.text[:300])
        except Exception:
            detail = resp.text[:300]
        raise GitHubAPIError(resp.status_code, detail)

    data = resp.json()
    return {"html_url": data["html_url"], "number": data["number"], "state": data.get("state", "open")}


async def push_and_create_pr(
    task_id: int,
    task_title: str,
    task_description: str,
    repo_path: str,
    github_url: str,
    token: str,
    base_branch: str = "main",
) -> PushResult:
    """Orchestrates: push the existing agent/task-{id} branch (already
    committed to by run_manager()'s commit step), then open a PR against it.
    Does not create the branch — worktree.create_worktree() already does
    that; this is push + PR only, matching what was actually missing."""
    from app.repo_tools.worktree import get_diff
    from app.services.git_service import git_push

    settings = get_settings()
    branch = f"agent/task-{task_id}"

    push_result = await git_push(repo_path, remote="origin", branch=branch)
    if not push_result["ok"]:
        return PushResult(pushed=False, pr_url=None, pr_number=None, error=push_result["stderr"][:500])

    diff = get_diff(task_id, repo_path)
    commit_message = await generate_commit_message(task_title, diff, settings.model_router)

    try:
        repo_full_name = parse_repo_full_name(github_url)
        pr = await create_github_pr(
            repo_full_name=repo_full_name,
            source_branch=branch,
            target_branch=base_branch,
            title=commit_message,
            body=task_description[:2000],
            token=token,
            draft=True,
        )
        return PushResult(pushed=True, pr_url=pr["html_url"], pr_number=pr["number"])
    except (GitHubAPIError, ValueError) as exc:
        logger.warning("PR creation failed for task %d: %s", task_id, exc)
        return PushResult(pushed=True, pr_url=None, pr_number=None, error=str(exc))
