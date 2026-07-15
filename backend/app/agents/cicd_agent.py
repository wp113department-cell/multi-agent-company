"""CI/CD Agent — GitHub Actions workflow analysis, build failure diagnosis, workflow authoring."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import CICD_AGENT_TOOLS, make_cicd_agent_handlers
from app.config import get_settings


@dataclass
class CicdResult:
    analysis: str = ""
    files_written: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def run_cicd_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> CicdResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_cicd_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — CI/CD Task\n\n"
                f"{task_description}\n\n"
                "If diagnosing a failure: read the workflow file, check git log, "
                "trace the root cause.\n"
                "If creating a workflow: read the project structure, write the YAML.\n"
                "When done, call submit_cicd_report with analysis and any files_written."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="cicd_agent",
        model=settings.model_coder,
        messages=messages,
        tools=CICD_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_cicd_result", {})
    return CicdResult(
        analysis=str(raw.get("analysis", "")),
        files_written=list(raw.get("files_written", [])),
        recommendations=list(raw.get("recommendations", [])),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
