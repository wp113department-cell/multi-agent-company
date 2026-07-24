"""Database Architect Agent — schema design, index recommendations, migration planning.

Verification contract:
  - schema_read: set True when existing models/migrations inspected via read_file or search_code
  - design_submitted: set True on submit_db_design call
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "database_architect",
    "description": "Reviews and designs database schemas: normalization, index recommendations, DDL generation, and migration sequencing.",
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
        "search_imports",
        "run_python_snippet",
        "submit_db_design",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "medium",
    "expected_verification": {
        "schema_read": "must inspect models and migrations before designing"
    },
    "dependencies": [],
}

_SUBMIT_DB_DESIGN_TOOL: dict[str, Any] = {
    "name": "submit_db_design",
    "description": "Submit the database design recommendations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "1-2 sentence overview"},
            "tables": {
                "type": "array",
                "description": "Table definitions or modifications",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["create", "modify", "drop", "index"],
                        },
                        "ddl": {"type": "string", "description": "SQL DDL statement"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "action", "rationale"],
                },
            },
            "indexes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string"},
                        "columns": {"type": "array", "items": {"type": "string"}},
                        "type": {
                            "type": "string",
                            "description": "btree, hash, gin, gist, brin",
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["table", "columns", "rationale"],
                },
            },
            "migration_notes": {"type": "array", "items": {"type": "string"}},
            "normalization_issues": {"type": "array", "items": {"type": "string"}},
            "performance_risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "tables"],
    },
}

_DB_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "run_python_snippet",
        "description": "Run a Python snippet (e.g., to inspect SQLAlchemy model metadata).",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    _SUBMIT_DB_DESIGN_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "schema_read",
        "search_code": "schema_read",
        "submit_db_design": "design_submitted",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"schema_read": "schema_read"},
    initial={"schema_read": False, "design_submitted": False},
)


def make_database_architect_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_db_design_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        n_tables = len(inp.get("tables", []))
        n_indexes = len(inp.get("indexes", []))
        return f"DB design submitted: {n_tables} table ops, {n_indexes} index recommendations."

    base["submit_db_design"] = submit_db_design_h
    base["_db_result"] = submitted
    return base


def run_database_architect(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_database_architect_handlers(repo)
    submitted = handlers["_db_result"]

    message = (
        f"Task #{task_id} — Database Architecture Review\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file to inspect existing SQLAlchemy models (backend/app/db/models.py) — MANDATORY.\n"
        "2. Use search_code to find raw SQL, foreign keys, and existing migration files.\n"
        "3. Evaluate:\n"
        "   - Normalization: identify 1NF/2NF/3NF violations\n"
        "   - Missing indexes on foreign keys and frequently queried columns\n"
        "   - N+1 query risks from relationship loading strategies\n"
        "   - Cascade rules (on_delete, on_update)\n"
        "   - Data types: prefer INTEGER over VARCHAR for PKs, TIMESTAMPTZ for dates\n"
        "4. Recommend specific indexes with type (btree/gin/gist) and rationale.\n"
        "5. Write DDL for any new tables or schema changes.\n"
        "6. Note migration sequencing concerns in migration_notes.\n"
        "7. Call submit_db_design with all recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="database_architect",
        model=settings.model_coder,
        tools=_DB_TOOLS,
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

    raw = submitted if submitted else final_state["result"]
    tables = raw.get("tables", [])
    indexes = raw.get("indexes", [])
    return AgentResult(
        summary=f"DB architecture: {len(tables)} table ops, {len(indexes)} index recommendations. {raw.get('summary', '')}",
        findings=(
            [
                {
                    "type": "table",
                    "name": t.get("name", "?"),
                    "action": t.get("action", "?"),
                    "rationale": t.get("rationale", ""),
                }
                for t in tables
            ]
            + [
                {
                    "type": "index",
                    "table": i.get("table", "?"),
                    "columns": i.get("columns", []),
                    "rationale": i.get("rationale", ""),
                }
                for i in indexes
            ]
        ),
        files_touched=[],
        verified=bool(final_state["verification"].get("schema_read", False)),
        requires_human_approval=len(tables) > 0,
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
                    "database_schema_design",
                    "index_recommendation",
                    "db_normalization_review",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
