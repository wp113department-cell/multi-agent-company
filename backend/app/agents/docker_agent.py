"""Docker Agent — LangGraph StateGraph.

Verification contract:
  - build_verified forced True only when a docker_build tool call succeeds
  - write_file resets build_verified (Dockerfile changed → must rebuild)
  - High blast radius → human approval for structural changes
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import DOCKER_AGENT_TOOLS, make_docker_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "docker_agent",
    "description": "Inspects and modifies Docker configuration; always requires human approval.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "search_symbols",
        "get_file_tree",
        "git_log",
        "read_files",
        "file_exists",
        "file_info",
        "find_references",
        "find_todos",
        "search_imports",
        "git_status",
        "git_show",
        "git_blame",
        "analyze_file",
        "docker_ps",
        "docker_logs",
        "docker_exec",
        "docker_compose",
        "docker_build",
        "docker_restart",
        "edit_file",
        "write_file",
        "submit_docker_report",
    ],
    "input_types": ["task_id", "task_description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes Dockerfile/compose files", "may restart containers"],
    "permissions": ["read_repo", "write_repo", "docker_exec"],
    "risk_level": "high",
    "expected_verification": {"build_ran": "docker_build must run after edits"},
    "dependencies": [],
}

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
        task_id=str(task_id),
        role_name="docker_agent",
        model=settings.model_coder,
        tools=DOCKER_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=task_description,
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
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


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=[
                    "docker_management",
                    "container_operations",
                    "dockerfile_editing",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
