"""Sprint Planner Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - complexity_estimated is forced to state["verification"]["complexity_estimated"]
  - estimate_complexity sets it to True only if it exits without [ERROR]
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import SPRINT_PLANNER_TOOLS, make_sprint_planner_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "sprint_planner",
    "description": "Breaks features into sprint-ready user stories with complexity estimates and acceptance criteria.",
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
        "estimate_complexity",
        "submit_sprint_plan",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {
        "complexity_estimated": "estimate_complexity must run before submit"
    },
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={"estimate_complexity": "complexity_estimated"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"complexity_estimated": "complexity_estimated"},
    initial={"complexity_estimated": False},
)


def run_sprint_planner(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_sprint_planner_handlers(repo)

    message = (
        f"Task #{task_id} — Sprint Planning\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file / search_code to understand the actual codebase scope.\n"
        "2. Use estimate_complexity on each proposed story — MANDATORY.\n"
        "3. Break the request into user stories with acceptance criteria.\n"
        "4. Order by priority and dependency, not arbitrary sequence.\n"
        "5. Call submit_sprint_plan with goal, stories (each with estimate and acceptance criteria), "
        "total_points, and risks.\n"
        "   Story point estimates must come from estimate_complexity calls, not guesses."
    )

    final_state = run_agent_graph(
        role_name="sprint_planner",
        model=settings.model_planner,
        tools=SPRINT_PLANNER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = final_state["result"]
    stories = list(raw.get("stories", []))
    return AgentResult(
        summary=str(raw.get("goal", raw.get("summary", "(no summary)"))),
        findings=stories,
        files_touched=[],
        verified=bool(final_state["verification"].get("complexity_estimated", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
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
                    "sprint_planning",
                    "complexity_estimation",
                    "story_decomposition",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
