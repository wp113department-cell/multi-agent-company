"""Migration Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - schema_inspected is forced to state["verification"]["schema_inspected"]
  - inspect_schema sets schema_inspected; write_file resets migration_applied
  - bash (alembic) sets migration_applied
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import MIGRATION_AGENT_TOOLS, make_migration_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "inspect_schema": "schema_inspected",
        "bash": "migration_applied",
    },
    reset_by=("write_file",),
    reset_keys=("migration_applied",),
    enforce_in_result={"schema_inspected": "schema_inspected"},
    initial={"schema_inspected": False, "migration_applied": False},
)


def run_migration_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_migration_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Database Migration\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Run inspect_schema to see the ACTUAL current schema — MANDATORY first step.\n"
        "   The graph forces schema_inspected=False until this runs.\n"
        "2. Read existing migration files with read_file to understand current Alembic state.\n"
        "3. Write the new migration file to backend/migrations/ using write_file.\n"
        "   Note: writing resets migration_applied to False.\n"
        "4. Verify with 'alembic history' and 'alembic current' via bash.\n"
        "5. For reversible migrations, ensure both upgrade() and downgrade() are correct.\n"
        "6. Call submit_migration with migration_file, is_reversible, summary, warnings.\n"
        "   schema_inspected in the result is enforced by the graph — must be True."
    )

    final_state = run_agent_graph(
        role_name="migration_agent",
        model=settings.model_coder,
        tools=MIGRATION_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[{"migration_file": raw.get("migration_file", ""), "is_reversible": raw.get("is_reversible", False)}],
        files_touched=[raw.get("migration_file", "")] if raw.get("migration_file") else [],
        verified=bool(final_state["verification"].get("schema_inspected", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
