"""Coder Agent — implements an approved plan inside a git worktree, with self-correction loop."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import CODER_TOOLS, make_coder_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


def _run_checks(worktree_path: str) -> str | None:
    """
    Run typecheck/lint/test in the worktree.
    Returns error output if any check fails, else None.
    """
    checks = [
        # Python: mypy + ruff
        ["python", "-m", "mypy", ".", "--ignore-missing-imports", "--no-error-summary"],
        ["python", "-m", "ruff", "check", "."],
    ]
    for cmd in checks:
        result = subprocess.run(cmd, cwd=worktree_path, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return (result.stdout + result.stderr)[:3000]
    return None


def run_coder(
    task_id: int,
    plan: str,
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> tuple[list[str], str | None, int, int]:
    """
    Run coder agent with self-correction loop.
    Returns (files_changed, error, tokens_in, tokens_out). error is None on success.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries
    total_in = 0
    total_out = 0

    for attempt in range(max_retries):
        handlers = make_coder_handlers(worktree_path, repo)

        messages = [
            {
                "role": "user",
                "content": (
                    f"Task ID: {task_id}\n\n"
                    f"Approved Implementation Plan:\n{plan}\n\n"
                    "Implement the plan exactly as described. "
                    "When done, call submit_patch with the list of files you changed."
                ),
            }
        ]

        if attempt > 0:
            messages[0]["content"] += (
                f"\n\n[RETRY {attempt}] Previous attempt failed checks. Fix the issues and try again."
            )

        try:
            _, tokens_in, tokens_out, *_ = run_agent(
                role_name="coder",
                model=settings.model_coder,
                messages=messages,
                tools=CODER_TOOLS,
                tool_handlers=handlers,
                max_turns=30,
                on_heartbeat=on_heartbeat,
                on_tool_call=on_tool_call,
            )
            total_in += tokens_in
            total_out += tokens_out
        except Exception as e:
            logger.exception("Coder agent failed on attempt %d", attempt + 1)
            if attempt == max_retries - 1:
                return [], f"Coder agent error: {e}", total_in, total_out
            continue

        patch_result = handlers.get("_patch_result", {})
        files_changed: list[str] = patch_result.get("files_changed", [])

        # Run checks
        try:
            check_error = _run_checks(worktree_path)
        except Exception as e:
            check_error = str(e)

        if check_error is None:
            logger.info(
                "Coder done — attempt %d, %d files changed, tokens_in=%d tokens_out=%d",
                attempt + 1,
                len(files_changed),
                total_in,
                total_out,
            )
            return files_changed, None, total_in, total_out

        logger.warning("Checks failed on attempt %d: %s", attempt + 1, check_error[:200])
        if attempt == max_retries - 1:
            return [], f"Checks still failing after {max_retries} attempts:\n{check_error}", total_in, total_out

        # Feed error back for next attempt
        messages.append({
            "role": "assistant",
            "content": f"Self-correction attempt {attempt + 1}: checks failed.\n{check_error}",
        })

    return [], f"Coder blocked after {max_retries} attempts", total_in, total_out
