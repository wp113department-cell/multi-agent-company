"""API Docs Agent — reads FastAPI routes and writes accurate API reference docs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import API_DOCS_AGENT_TOOLS, make_api_docs_agent_handlers
from app.config import get_settings


@dataclass
class ApiDocsResult:
    files_written: list[str] = field(default_factory=list)
    summary: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


def run_api_docs_agent(
    task_id: int,
    doc_request: str = "Document all API endpoints in docs/API.md.",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> ApiDocsResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_api_docs_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — API Documentation Task\n\n"
                f"{doc_request}\n\n"
                "Steps: 1) Use find_api to enumerate all route handlers, "
                "2) read each route file with read_file to get exact signatures, "
                "3) use parse_ast for Pydantic schema details, "
                "4) write Markdown docs with write_file, "
                "5) call submit_docs with files_written and summary."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="api_docs_agent",
        model=settings.model_planner,
        messages=messages,
        tools=API_DOCS_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_docs_result", {})
    return ApiDocsResult(
        files_written=list(raw.get("files_written", [])),
        summary=str(raw.get("summary", "")),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
