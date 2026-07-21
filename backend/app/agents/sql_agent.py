"""SQL Agent — LangGraph StateGraph with schema-verification contract.

Verification contract:
  - verified_against_schema forced True only if inspect_schema ran this turn
  - is_destructive forced True if DROP/TRUNCATE/DELETE detected in query
  - Destructive ops require human approval
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import SQL_AGENT_TOOLS, make_sql_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "sql_agent",
    "description": "Writes and validates SQL queries and migrations against the live database schema.",
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
        "run_sql",
        "inspect_schema",
        "find_sql",
        "explain_query",
        "edit_file",
        "write_file",
        "submit_sql_report",
    ],
    "input_types": ["task_id", "task_description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["may write migration files"],
    "permissions": ["read_repo", "write_repo", "read_db"],
    "risk_level": "medium",
    "expected_verification": {"schema_inspected": "inspect_schema must run"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "inspect_schema": "schema_inspected",
        "run_sql": "sql_ran",
        "explain_query": "explain_ran",
    },
    reset_by=("write_file",),
    reset_keys=(),
    enforce_in_result={"verified_against_schema": "schema_inspected"},
    initial={"schema_inspected": False, "sql_ran": False, "explain_ran": False},
)

_DESTRUCTIVE_KEYWORDS = ("drop ", "truncate ", "delete from", "alter table")


def _is_destructive(query: str) -> bool:
    return any(k in query.lower() for k in _DESTRUCTIVE_KEYWORDS)


def run_sql_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_sql_agent_handlers(repo)

    message = (
        f"Task #{task_id} — SQL Task\n\n{task_description}\n\n"
        "Process:\n"
        "1. Call inspect_schema FIRST — learn the real tables, columns, and indexes.\n"
        "   Never reference a table or column you haven't just seen in inspect_schema output.\n"
        "2. Draft your query or migration against the inspected schema only.\n"
        "3. Run explain_query (EXPLAIN ANALYZE) to verify query plan before claiming it's optimal.\n"
        "4. For migrations: write to a migration file only; never run DROP/TRUNCATE/DELETE "
        "   directly — flag those as requiring human approval.\n"
        "5. Call submit_sql_report with query_or_migration, explain_plan_summary, "
        "   verified_against_schema (will be auto-enforced by graph), is_destructive, warnings.\n"
        "RULE: verified_against_schema will be forced False if you did not call inspect_schema."
    )

    requires_approval = _is_destructive(task_description)

    final_state = run_agent_graph(
        role_name="sql_agent",
        model=settings.model_coder,
        tools=SQL_AGENT_TOOLS,
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
        human_approval_required=requires_approval,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(
            raw.get("summary", raw.get("query_or_migration", "(no summary)")[:200])
        ),
        findings=list(raw.get("warnings", [])),
        files_touched=list(raw.get("files_written", [])),
        verified=bool(final_state["verification"].get("schema_inspected", False)),
        requires_human_approval=bool(
            raw.get("_requires_human_approval", requires_approval)
        ),
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status=(
            "needs_approval"
            if requires_approval
            else ("completed" if final_state["submitted"] else "blocked")
        ),
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
                    "sql_management",
                    "schema_analysis",
                    "query_optimization",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
