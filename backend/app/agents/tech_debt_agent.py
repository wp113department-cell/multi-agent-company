"""Technical Debt Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - lint_ran is forced to state["verification"]["lint_ran"]
  - run_linter sets lint_ran; coverage_report sets coverage_checked
  - Read-only agent — no reset_by
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import TECH_DEBT_AGENT_TOOLS, make_tech_debt_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_linter": "lint_ran",
        "coverage_report": "coverage_checked",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
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
