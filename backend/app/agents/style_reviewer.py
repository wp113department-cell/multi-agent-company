"""Style Reviewer Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - lint_ran is forced to state["verification"]["lint_ran"]
  - run_linter sets lint_ran to True only if it exits without [ERROR]
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import STYLE_REVIEWER_TOOLS, make_style_reviewer_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={"run_linter": "lint_ran"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={"lint_ran": False},
)


def run_style_reviewer(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_style_reviewer_handlers(repo)

    message = (
        f"Task #{task_id} — Style / Lint Review\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Run run_linter on the target path — MANDATORY first step.\n"
        "2. Use read_file on files with violations to understand the context.\n"
        "3. Use list_functions / list_classes for naming convention review.\n"
        "4. Use find_todos to surface TODO/FIXME/HACK comments.\n"
        "5. Call submit_style_review with summary, violations list, auto_fixable flag.\n"
        "   Note: violations must come from actual linter output — never from memory."
    )

    final_state = run_agent_graph(
        role_name="style_reviewer",
        model=settings.model_coder,
        tools=STYLE_REVIEWER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=15,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=list(raw.get("violations", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("lint_ran", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
