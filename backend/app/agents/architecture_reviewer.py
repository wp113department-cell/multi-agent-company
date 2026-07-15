"""Architecture Reviewer Agent — import graphs, circular deps, layer separation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import ARCH_REVIEWER_TOOLS, make_arch_reviewer_handlers
from app.config import get_settings


@dataclass
class ArchReviewResult:
    verdict: str = "approved"
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    summary: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


def run_arch_review(
    task_id: int,
    focus: str = "",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> ArchReviewResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_arch_reviewer_handlers(repo)

    prompt = (
        f"Task #{task_id} — Architecture Review\n\n"
        "Review the structural integrity of the Python backend. "
        "Check for: circular imports, layer violations, dead code, "
        "hardcoded config outside config.py, and untyped state fields.\n"
    )
    if focus:
        prompt += f"\nFocus area: {focus}\n"
    prompt += "\nWhen done, call submit_arch_review with verdict, issues, recommendations, and summary."

    messages = [{"role": "user", "content": prompt}]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="architecture_reviewer",
        model=settings.model_coder,
        messages=messages,
        tools=ARCH_REVIEWER_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_arch_result", {})
    return ArchReviewResult(
        verdict=str(raw.get("verdict", "approved")),
        issues=list(raw.get("issues", [])),
        recommendations=list(raw.get("recommendations", [])),
        summary=str(raw.get("summary", "")),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
