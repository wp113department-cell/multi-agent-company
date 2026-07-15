"""Bug Fix Agent — reads error tracebacks, locates root cause, patches code."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import BUG_FIX_TOOLS, make_bug_fix_handlers
from app.config import get_settings


@dataclass
class BugFixResult:
    root_cause: str = ""
    fix_summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_passed: bool = False
    tokens_in: int = 0
    tokens_out: int = 0


def run_bug_fix(
    task_id: int,
    error_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> BugFixResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_bug_fix_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — Bug Report\n\n"
                f"{error_description}\n\n"
                "Please: 1) Read the relevant files, 2) find the root cause, "
                "3) implement the minimal fix, 4) verify with git_diff, "
                "5) call submit_bug_fix with your findings."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="bug_fix",
        model=settings.model_coder,
        messages=messages,
        tools=BUG_FIX_TOOLS,
        tool_handlers=handlers,
        max_turns=25,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_bug_fix_result", {})
    return BugFixResult(
        root_cause=str(raw.get("root_cause", "")),
        fix_summary=str(raw.get("fix_summary", "")),
        files_changed=list(raw.get("files_changed", [])),
        tests_passed=bool(raw.get("tests_passed", False)),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
