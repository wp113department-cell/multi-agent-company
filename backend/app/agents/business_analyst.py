"""Business Analyst Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - requirements_read is forced to state["verification"]["requirements_read"]
  - read_file sets requirements_read to True; search_code sets code_searched
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import BUSINESS_ANALYST_TOOLS, make_business_analyst_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "requirements_read",
        "search_code": "code_searched",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"requirements_read": "requirements_read"},
    initial={"requirements_read": False, "code_searched": False},
)


def run_business_analyst(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_business_analyst_handlers(repo)

    message = (
        f"Task #{task_id} — Business Analysis\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Read any existing spec docs, README, or requirement files with read_file.\n"
        "2. Use search_code to understand what already exists in the codebase.\n"
        "3. Derive user stories from the actual requirements — never invent personas.\n"
        "4. Write acceptance criteria as testable statements (Given/When/Then).\n"
        "5. Identify edge cases from real code paths found by search_code.\n"
        "6. Call submit_ba_result with user_stories, acceptance_criteria, edge_cases, summary.\n"
        "   User stories must be grounded in the actual request and existing code."
    )

    final_state = run_agent_graph(
        role_name="business_analyst",
        model=settings.model_planner,
        tools=BUSINESS_ANALYST_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[
            {"user_stories": raw.get("user_stories", [])},
            {"acceptance_criteria": raw.get("acceptance_criteria", [])},
            {"edge_cases": raw.get("edge_cases", [])},
        ],
        files_touched=[],
        verified=bool(final_state["verification"].get("requirements_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
