"""QA Agent — runs tests and checks in a worktree. No write access."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import QA_TOOLS, make_qa_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class QAResult:
    status: str  # "passed" | "failed"
    tests_run: int
    tests_passed: int
    tests_failed: int
    typecheck_clean: bool
    lint_clean: bool
    errors: list[str] = field(default_factory=list)
    summary: str = ""


def run_qa(
    task_id: int,
    subtask_id: int,
    files_changed: list[str],
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> QAResult:
    """
    Run QA agent against the worktree.

    The QA agent has: read_file, list_files, search_code, bash (test commands only),
    submit_qa_result. NO write_file, NO edit_file — structurally absent from tool list.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    handlers = make_qa_handlers(worktree_path, repo)

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
                f"Files changed by developer: {', '.join(files_changed) or '(none listed)'}\n\n"
                "Run the test suite and all checks:\n"
                "1. Run pytest (or npm test for frontend changes)\n"
                "2. Run mypy typecheck\n"
                "3. Run ruff lint\n"
                "Capture all output. Then call submit_qa_result with the structured results."
            ),
        }
    ]

    try:
        _, tokens_in, tokens_out, *_ = run_agent(
            role_name="qa",
            model=settings.model_router,
            messages=messages,
            tools=QA_TOOLS,
            tool_handlers=handlers,
            max_turns=20,
            on_heartbeat=on_heartbeat,
            on_tool_call=on_tool_call,
        )
    except Exception as e:
        logger.exception("QA agent failed for subtask %d", subtask_id)
        return QAResult(
            status="failed",
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            typecheck_clean=False,
            lint_clean=False,
            errors=[f"QA agent error: {e}"],
            summary=f"QA agent error: {e}",
        )

    raw = handlers.get("_qa_result", {})
    logger.info(
        "QA done — subtask %d, status=%s, in=%d out=%d",
        subtask_id, raw.get("status", "unknown"), tokens_in, tokens_out,
    )

    return QAResult(
        status=str(raw.get("status", "failed")),
        tests_run=int(raw.get("tests_run", 0)),
        tests_passed=int(raw.get("tests_passed", 0)),
        tests_failed=int(raw.get("tests_failed", 0)),
        typecheck_clean=bool(raw.get("typecheck_clean", False)),
        lint_clean=bool(raw.get("lint_clean", False)),
        errors=list(raw.get("errors", [])),
        summary=str(raw.get("summary", "")),
    )
