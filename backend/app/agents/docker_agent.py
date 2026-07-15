"""Docker Agent — container inspection, log analysis, image builds, compose management."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import DOCKER_AGENT_TOOLS, make_docker_agent_handlers
from app.config import get_settings


@dataclass
class DockerResult:
    action: str = ""
    outcome: str = ""
    files_written: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def run_docker_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> DockerResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_docker_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — Docker Task\n\n"
                f"{task_description}\n\n"
                "Steps: 1) Check running containers with docker_ps, "
                "2) read logs or Dockerfile as needed, "
                "3) diagnose or fix the issue, "
                "4) call submit_docker_report with action and outcome."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="docker_agent",
        model=settings.model_coder,
        messages=messages,
        tools=DOCKER_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_docker_result", {})
    return DockerResult(
        action=str(raw.get("action", "")),
        outcome=str(raw.get("outcome", "")),
        files_written=list(raw.get("files_written", [])),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
