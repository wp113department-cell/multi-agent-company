"""SQL Agent — runs queries, inspects schema, writes Alembic migrations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import SQL_AGENT_TOOLS, make_sql_agent_handlers
from app.config import get_settings


@dataclass
class SqlResult:
    action: str = ""
    result: str = ""
    files_written: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def run_sql_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> SqlResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_sql_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — SQL Task\n\n"
                f"{task_description}\n\n"
                "Steps: 1) Inspect schema to understand table structure, "
                "2) run or write the SQL as needed, "
                "3) call submit_sql_report with your action and result."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="sql_agent",
        model=settings.model_coder,
        messages=messages,
        tools=SQL_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_sql_result", {})
    return SqlResult(
        action=str(raw.get("action", "")),
        result=str(raw.get("result", "")),
        files_written=list(raw.get("files_written", [])),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
