"""Technical Debt Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - lint_ran is forced to state["verification"]["lint_ran"]
  - run_linter sets lint_ran; coverage_report sets coverage_checked
  - Read-only agent — no reset_by
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import TECH_DEBT_AGENT_TOOLS, make_tech_debt_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "tech_debt_agent",
    "description": "Audits codebase for technical debt: lint violations, test coverage gaps, oversized functions, TODO density.",
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
        "list_functions",
        "list_classes",
        "run_linter",
        "coverage_report",
        "submit_tech_debt",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {"lint_ran": "run_linter must execute before submit"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_linter": "lint_ran",
        "coverage_report": "coverage_checked",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"lint_ran": "lint_ran"},
    initial={"lint_ran": False, "coverage_checked": False},
)


def run_tech_debt_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_tech_debt_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Technical Debt Analysis\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Run run_linter on the codebase — MANDATORY first step.\n"
        "2. Run coverage_report to identify untested modules.\n"
        "3. Use list_functions / list_classes to find overly large functions (>50 lines).\n"
        "4. Use find_todos to surface all TODO/FIXME/HACK markers.\n"
        "5. Use search_code for known patterns: duplicated logic, magic numbers, missing types.\n"
        "6. Prioritize findings by blast radius: things touched frequently rank higher.\n"
        "7. Call submit_tech_debt with summary, debt_items (each with file+line+severity), "
        "priority_fixes, effort_estimate.\n"
        "   All debt items must come from actual tool output — never from training data recall."
    )

    final_state = run_agent_graph(
        role_name="tech_debt_agent",
        model=settings.model_coder,
        tools=TECH_DEBT_AGENT_TOOLS,
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
        findings=list(raw.get("debt_items", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("lint_ran", False)),
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
                    "technical_debt_analysis",
                    "code_quality_assessment",
                    "coverage_analysis",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
