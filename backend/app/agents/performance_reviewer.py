"""Performance Reviewer Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - query_explained is forced to state["verification"]["query_explained"]
  - explain_query sets query_explained to True only if it exits without [ERROR]
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    PERFORMANCE_REVIEWER_TOOLS,
    make_performance_reviewer_handlers,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "performance_reviewer",
    "description": "Reviews codebase for performance issues: slow SQL queries, O(n²) loops, missing indexes, memory leaks.",
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
        "find_sql",
        "run_sql",
        "explain_query",
        "list_functions",
        "submit_perf_review",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo", "read_db"],
    "risk_level": "low",
    "expected_verification": {
        "query_explained": "explain_query must run before submit"
    },
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={"explain_query": "query_explained"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"query_explained": "query_explained"},
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
        findings=list(raw.get("findings", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("query_explained", False)),
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
                    "performance_review",
                    "query_analysis",
                    "bottleneck_detection",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
