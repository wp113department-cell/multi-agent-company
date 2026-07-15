"""Security Reviewer Agent — OWASP scan, secrets detection, injection analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import SECURITY_REVIEWER_TOOLS, make_security_reviewer_handlers
from app.config import get_settings


@dataclass
class SecurityResult:
    severity: str = "none"
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def run_security_review(
    task_id: int,
    focus: str = "",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> SecurityResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_security_reviewer_handlers(repo)

    prompt = (
        f"Task #{task_id} — Security Review\n\n"
        "Perform a thorough security review of the codebase. "
        "Cover: secrets/credentials, SQL injection, authentication gaps, "
        "unsafe subprocess usage, path traversal, and CORS configuration.\n"
    )
    if focus:
        prompt += f"\nFocus area: {focus}\n"
    prompt += "\nWhen done, call submit_security_report with all findings."

    messages = [{"role": "user", "content": prompt}]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="security_reviewer",
        model=settings.model_coder,
        messages=messages,
        tools=SECURITY_REVIEWER_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_security_result", {})
    return SecurityResult(
        severity=str(raw.get("severity", "none")),
        findings=list(raw.get("findings", [])),
        recommendations=list(raw.get("recommendations", [])),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
