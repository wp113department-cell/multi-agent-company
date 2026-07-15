"""README Agent — reads codebase structure and writes Markdown documentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import README_AGENT_TOOLS, make_readme_agent_handlers
from app.config import get_settings


@dataclass
class ReadmeResult:
    files_written: list[str] = field(default_factory=list)
    summary: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


def run_readme_agent(
    task_id: int,
    doc_request: str = "Write a comprehensive README.md for this project.",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> ReadmeResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_readme_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — Documentation Task\n\n"
                f"{doc_request}\n\n"
                "Steps: 1) Use get_file_tree to understand the project layout, "
                "2) read key files (main.py, config.py, requirements.txt, existing README), "
                "3) write Markdown documentation with write_file, "
                "4) call submit_docs with files_written and summary."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="readme_agent",
        model=settings.model_planner,
        messages=messages,
        tools=README_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=20,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_docs_result", {})
    return ReadmeResult(
        files_written=list(raw.get("files_written", [])),
        summary=str(raw.get("summary", "")),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
