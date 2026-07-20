"""Business Analyst Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - requirements_read is forced to state["verification"]["requirements_read"]
  - read_file sets requirements_read to True; search_code sets code_searched
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import BUSINESS_ANALYST_TOOLS, make_business_analyst_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "business_analyst",
    "description": "Derives user stories, acceptance criteria, and edge cases from existing requirements and codebase.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "submit_ba_result",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {"requirements_read": "read_file must run before submit"},
    "dependencies": [],
}

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


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------

def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["business_analysis", "requirement_extraction", "requirements_story_drafting"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
