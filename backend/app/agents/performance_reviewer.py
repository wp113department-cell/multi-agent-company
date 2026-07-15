"""Performance Reviewer Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - query_explained is forced to state["verification"]["query_explained"]
  - explain_query sets query_explained to True only if it exits without [ERROR]
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import PERFORMANCE_REVIEWER_TOOLS, make_performance_reviewer_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={"explain_query": "query_explained"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={"query_explained": False},
)


def run_performance_reviewer(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_performance_reviewer_handlers(repo)

    message = (
        f"Task #{task_id} — Performance Review\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use find_sql to locate actual SQL queries in the codebase.\n"
        "2. Use explain_query on each significant query — MANDATORY before reporting.\n"
        "3. Use read_file to find hot loops, O(n^2) patterns, missing indexes.\n"
        "4. Use list_functions to identify large functions that may be performance bottlenecks.\n"
        "5. Call submit_perf_review with summary, findings, severity, recommendations.\n"
        "   Note: query_explained reflects whether explain_query actually ran."
    )

    final_state = run_agent_graph(
        role_name="performance_reviewer",
        model=settings.model_coder,
        tools=PERFORMANCE_REVIEWER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=list(raw.get("findings", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("query_explained", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
