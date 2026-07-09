"""Code Review Agent — reads diffs and produces structured findings. Read-only."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import REVIEWER_TOOLS, make_reviewer_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ReviewFinding:
    severity: str  # "blocking" | "non-blocking" | "suggestion"
    file: str
    line: int | None
    finding: str
    recommendation: str


@dataclass
class ReviewResult:
    verdict: str  # "approved" | "changes_required"
    findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""

    @property
    def blocking_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "blocking")

    @property
    def has_blocking(self) -> bool:
        return self.blocking_count > 0


def run_reviewer(
    task_id: int,
    subtask_id: int,
    diff: str,
    plan: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> ReviewResult:
    """
    Run code review agent.

    The reviewer has: read_file, list_files, search_code, submit_review.
    NO bash, NO write_file, NO edit_file — structurally absent from tool list.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    handlers = make_reviewer_handlers(repo)

    diff_preview = diff[:4000] if diff else "(no diff available)"

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
                f"Approved Implementation Plan:\n{plan}\n\n"
                f"Code Diff (first 4000 chars):\n{diff_preview}\n\n"
                "Review this implementation. Read any files you need to understand the context.\n"
                "Produce structured findings categorized as blocking, non-blocking, or suggestion.\n"
                "Call submit_review when done with all findings."
            ),
        }
    ]

    try:
        _, tokens_in, tokens_out, *_ = run_agent(
            role_name="reviewer",
            model=settings.model_coder,
            messages=messages,
            tools=REVIEWER_TOOLS,
            tool_handlers=handlers,
            max_turns=15,
            on_heartbeat=on_heartbeat,
            on_tool_call=on_tool_call,
        )
    except Exception as e:
        logger.exception("Reviewer agent failed for subtask %d", subtask_id)
        return ReviewResult(
            verdict="changes_required",
            findings=[ReviewFinding(
                severity="blocking",
                file="",
                line=None,
                finding=f"Reviewer agent error: {e}",
                recommendation="Investigate agent failure",
            )],
            summary=f"Reviewer agent error: {e}",
        )

    raw = handlers.get("_review_result", {})
    logger.info(
        "Review done — subtask %d, verdict=%s, in=%d out=%d",
        subtask_id, raw.get("verdict", "unknown"), tokens_in, tokens_out,
    )

    raw_findings: list[dict[str, Any]] = raw.get("findings", [])
    findings = [
        ReviewFinding(
            severity=str(f.get("severity", "suggestion")),
            file=str(f.get("file", "")),
            line=f.get("line"),
            finding=str(f.get("finding", "")),
            recommendation=str(f.get("recommendation", "")),
        )
        for f in raw_findings
    ]

    return ReviewResult(
        verdict=str(raw.get("verdict", "changes_required")),
        findings=findings,
        summary=str(raw.get("summary", "")),
    )
