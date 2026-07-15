"""Refactor Agent — extracts functions, renames symbols, eliminates duplication."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import REFACTOR_AGENT_TOOLS, make_refactor_agent_handlers
from app.config import get_settings


@dataclass
class RefactorResult:
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    breaking_changes: bool = False
    tokens_in: int = 0
    tokens_out: int = 0


def run_refactor_agent(
    task_id: int,
    refactor_instructions: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> RefactorResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_refactor_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — Refactoring Task\n\n"
                f"{refactor_instructions}\n\n"
                "Important: preserve all external interfaces (function signatures, "
                "return types). Make one logical change at a time and verify with "
                "git_diff after each step. When done, call submit_refactor_report."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="refactor_agent",
        model=settings.model_coder,
        messages=messages,
        tools=REFACTOR_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=25,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_refactor_result", {})
    return RefactorResult(
        summary=str(raw.get("summary", "")),
        files_changed=list(raw.get("files_changed", [])),
        breaking_changes=bool(raw.get("breaking_changes", False)),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
