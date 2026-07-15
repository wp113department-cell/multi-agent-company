"""Docker Agent — LangGraph StateGraph.

Verification contract:
  - build_verified forced True only when a docker_build tool call succeeds
  - write_file resets build_verified (Dockerfile changed → must rebuild)
  - High blast radius → human approval for structural changes
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import DOCKER_AGENT_TOOLS, make_docker_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "docker_ps": "container_inspected",
        "docker_logs": "logs_read",
        "docker_build": "build_ran",
    },
    reset_by=("write_file", "edit_file"),
    reset_keys=("build_ran",),
    enforce_in_result={"build_verified": "build_ran"},
    initial={"container_inspected": False, "logs_read": False, "build_ran": False},
)


def run_docker_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_docker_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Docker Task\n\n{task_description}\n\n"
        "Process:\n"
        "1. Use read_file to inspect existing Dockerfile/docker-compose files.\n"
        "2. Use search_code to find the actual entrypoint, ports, env vars used.\n"
        "3. Use docker_ps / docker_logs to understand the current container state.\n"
        "4. Draft the minimal change — base image versions must come from the existing file "
        "   or the running container, never assumed from memory.\n"
        "5. After writing files, run docker_build to verify it actually builds.\n"
        "6. Call submit_docker_report with files_changed, build_verified (auto-enforced), "
        "   summary, warnings.\n"
        "RULE: build_verified will be forced False if docker_build did not run after your edits."
    )

    final_state = run_agent_graph(
        role_name="docker_agent",
        model=settings.model_coder,
        tools=DOCKER_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        human_approval_required=True,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=list(raw.get("warnings", [])),
        files_touched=list(raw.get("files_changed", [])),
        verified=bool(final_state["verification"].get("build_ran", False)),
        requires_human_approval=True,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="needs_approval" if final_state["submitted"] else "blocked",
        raw=raw,
    )
