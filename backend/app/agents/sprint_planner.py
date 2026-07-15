"""Sprint Planner Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - complexity_estimated is forced to state["verification"]["complexity_estimated"]
  - estimate_complexity sets it to True only if it exits without [ERROR]
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import SPRINT_PLANNER_TOOLS, make_sprint_planner_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={"estimate_complexity": "complexity_estimated"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
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
