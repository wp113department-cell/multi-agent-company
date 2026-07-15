"""Schema Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - schema_inspected is forced to state["verification"]["schema_inspected"]
  - inspect_schema sets it; write_file resets it (schema may have changed)
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import SCHEMA_AGENT_TOOLS, make_schema_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={"inspect_schema": "schema_inspected"},
    reset_by=("write_file",),
    reset_keys=("schema_inspected",),
    enforce_in_result={"schema_inspected": "schema_inspected"},
    initial={"schema_inspected": False},
)


def run_schema_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_schema_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Schema Design / Review\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Run inspect_schema to read the ACTUAL current database schema — MANDATORY.\n"
        "   All table names, columns, types, and constraints come from this output only.\n"
        "2. Read existing SQLAlchemy model files with read_file to see ORM definitions.\n"
        "3. Analyze normalization, indexing strategy, and foreign key constraints.\n"
        "4. If proposing a new design, write the schema DDL or updated model to a file.\n"
        "5. After writing, re-run inspect_schema if you need to verify the new state.\n"
        "6. Call submit_schema with summary, tables (actual from inspection), "
        "normalization_issues, files_written.\n"
        "   schema_inspected in the result is enforced by the graph."
    )

    final_state = run_agent_graph(
        role_name="schema_agent",
        model=settings.model_coder,
        tools=SCHEMA_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[{"tables": raw.get("tables", []), "normalization_issues": raw.get("normalization_issues", [])}],
        files_touched=list(raw.get("files_written", [])),
        verified=bool(final_state["verification"].get("schema_inspected", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
