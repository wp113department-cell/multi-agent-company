"""Frontend Developer Agent — implements UI changes in an isolated worktree."""
from __future__ import annotations

import logging
import subprocess
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import CODER_TOOLS, make_coder_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


def _run_frontend_checks(worktree_path: str) -> str | None:
    """Run tsc --noEmit in the apps/web directory. Returns error output or None on success."""
    web_dir = f"{worktree_path}/apps/web"
    checks = [
        ["npx", "tsc", "--noEmit"],
    ]
    for cmd in checks:
        result = subprocess.run(cmd, cwd=web_dir, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            return (result.stdout + result.stderr)[:3000]
    return None


def run_frontend_dev(
    task_id: int,
    subtask_id: int,
    plan: str,
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> tuple[list[str], str | None]:
    """
    Run frontend developer agent with self-correction loop.

    Returns (files_changed, error). error is None on success.
    Tool list matches doc-07 matrix: Read + Edit/Write (worktree only) + Bash (typecheck/lint/test).
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries

    for attempt in range(max_retries):
        handlers = make_coder_handlers(worktree_path, repo)

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
                    f"Frontend Implementation Plan:\n{plan}\n\n"
                    "You are a frontend developer. Implement the plan in apps/web/.\n"
                    "Use TypeScript strict mode. API calls go through apps/web/lib/api.ts.\n"
                    "When done, call submit_patch with the list of files changed."
                ),
            }
        ]

        if attempt > 0:
            messages[0]["content"] += (
                f"\n\n[SELF-CORRECTION ATTEMPT {attempt}] "
                "Previous attempt failed TypeScript typecheck. Fix all type errors."
            )

        try:
            _, tokens_in, tokens_out, *_ = run_agent(
                role_name="frontend_dev",
                model=settings.model_coder,
                messages=messages,
                tools=CODER_TOOLS,
                tool_handlers=handlers,
                max_turns=30,
                on_heartbeat=on_heartbeat,
                on_tool_call=on_tool_call,
            )
        except Exception as e:
            logger.exception("Frontend dev agent failed on attempt %d for subtask %d", attempt + 1, subtask_id)
            if attempt == max_retries - 1:
                return [], f"Frontend dev agent error: {e}"
            continue

        patch_result = handlers.get("_patch_result", {})
        files_changed: list[str] = patch_result.get("files_changed", [])

        check_error = _run_frontend_checks(worktree_path)
        if check_error is None:
            logger.info(
                "Frontend dev done — subtask %d, attempt %d, %d files, in=%d out=%d",
                subtask_id, attempt + 1, len(files_changed), tokens_in, tokens_out,
            )
            return files_changed, None

        logger.warning("Frontend dev typecheck failed on attempt %d: %s", attempt + 1, check_error[:200])
        if attempt == max_retries - 1:
            return [], f"TypeScript errors persist after {max_retries} attempts:\n{check_error}"

    return [], f"Frontend dev blocked after {max_retries} attempts"
