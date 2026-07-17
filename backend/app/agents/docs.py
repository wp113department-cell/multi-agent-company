"""Documentation Agent — writes .md files in worktree only. Triggered after epic approval.

Session 4 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: medium — writes .md files to worktree).
- Added _register() at module level.
- raw_text now populated via _last_assistant_text(final_state["messages"]).
- _build_docs_context helper unchanged.
- External interface (run_docs signature + return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import DOCS_TOOLS, make_docs_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "docs",
    "description": "Writes changelog and README updates to a worktree after epic implementation.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "write_file", "submit_docs",
    ],
    "input_types": ["epic_title", "epic_description", "files_changed", "diffs", "qa_summaries",
                    "worktree_path", "repo_path"],
    "output_types": ["DocsReport"],
    "side_effects": ["write_files"],
    "permissions": ["read_repo", "write_worktree"],
    "risk_level": "medium",
    "expected_verification": {},
    "dependencies": ["qa", "backend_dev", "frontend_dev"],
}

# ---------------------------------------------------------------------------
# Verification contract — write_file allowed; no bash-based check resets needed
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"write_file": "docs_written"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={},
)

# ---------------------------------------------------------------------------
# Result dataclass — unchanged from original
# ---------------------------------------------------------------------------

@dataclass
class DocsReport:
    files_written: list[str]
    summary: str
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Extract the last text response from the assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
    return ""


def _build_docs_context(
    epic_title: str,
    epic_description: str,
    files_changed: list[str],
    diffs: str,
    qa_summaries: list[str],
) -> str:
    files_list = "\n".join(f"- {f}" for f in files_changed) if files_changed else "(none)"
    qa_block = "\n\n".join(qa_summaries) if qa_summaries else "(no QA summaries)"
    diff_block = diffs[:6000] + ("..." if len(diffs) > 6000 else "") if diffs else "(no diff)"

    return f"""Epic: {epic_title}

Description:
{epic_description}

Files changed:
{files_list}

QA summaries:
{qa_block}

Diff (truncated to 6000 chars):
{diff_block}

Please write the changelog and any necessary README updates in the worktree.
Call submit_docs when finished with the list of files you wrote."""


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------

def run_docs(
    epic_title: str,
    epic_description: str,
    files_changed: list[str],
    diffs: str,
    qa_summaries: list[str],
    worktree_path: str,
    repo_path: str | None = None,
) -> tuple[DocsReport | None, str | None, int, int]:
    """Run the Documentation Agent in the given worktree.

    Returns (report, error, tokens_in, tokens_out). error is None on success.
    """
    settings = get_settings()
    effective_repo = repo_path or settings.target_repo_path
    handlers = make_docs_handlers(worktree_path, effective_repo)

    context = _build_docs_context(
        epic_title=epic_title,
        epic_description=epic_description,
        files_changed=files_changed,
        diffs=diffs,
        qa_summaries=qa_summaries,
    )

    try:
        final_state = run_agent_graph(
            role_name="docs",
            model=settings.model_router,
            tools=DOCS_TOOLS,
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=context,
            task_description=f"Documentation for: {epic_title}",
            repo_path=effective_repo,
            model_haiku=settings.model_router,
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            enable_lesson=True,
        )
    except Exception as exc:
        logger.exception("Docs agent failed")
        return None, f"Docs agent error: {exc}", 0, 0

    tokens_in = final_state.get("tokens_in", 0)
    tokens_out = final_state.get("tokens_out", 0)
    docs_result = handlers.get("_docs_result", {})
    final_text = _last_assistant_text(final_state.get("messages", []))

    if docs_result:
        report = DocsReport(
            files_written=list(docs_result.get("files_written", [])),
            summary=str(docs_result.get("summary", "")),
            raw_text=final_text or "",
        )
        return report, None, tokens_in, tokens_out

    report = DocsReport(
        files_written=[],
        summary="",
        raw_text=final_text or "Docs agent did not call submit_docs.",
    )
    return report, "Docs agent did not call submit_docs", tokens_in, tokens_out


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------

def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["documentation", "changelog_writing", "readme_update"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("docs")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
