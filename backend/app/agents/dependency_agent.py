"""Dependency Upgrade Agent — audits Python/Node deps for outdated versions and CVEs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import DEPENDENCY_AGENT_TOOLS, make_dependency_agent_handlers
from app.config import get_settings


@dataclass
class DependencyResult:
    outdated: list[str] = field(default_factory=list)
    upgraded: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def run_dependency_agent(
    task_id: int,
    task_description: str = "Audit all dependencies for outdated versions and known vulnerabilities.",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> DependencyResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_dependency_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — Dependency Audit\n\n"
                f"{task_description}\n\n"
                "Steps: 1) Read requirements.txt and package.json, "
                "2) run pip list and npm audit to check for outdated/vulnerable packages, "
                "3) check latest versions with pip index versions for key packages, "
                "4) update safe patch/minor upgrades with edit_file, "
                "5) call submit_dependency_report with outdated, upgraded, and issues."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="dependency_agent",
        model=settings.model_coder,
        messages=messages,
        tools=DEPENDENCY_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_dependency_result", {})
    return DependencyResult(
        outdated=list(raw.get("outdated", [])),
        upgraded=list(raw.get("upgraded", [])),
        issues=list(raw.get("issues", [])),
        files_changed=list(raw.get("files_changed", [])),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
