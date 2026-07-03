"""Documentation Agent — writes .md files in worktree only. Triggered after epic approval."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.agents.base import run_agent
from app.agents.tools import DOCS_TOOLS, make_docs_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DocsReport:
    files_written: list[str]
    summary: str
    raw_text: str = ""


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

    The agent reads context about the epic and writes changelog / README updates
    to the worktree. Changes stay in the worktree until human approval.

    Returns (report, error, tokens_in, tokens_out).
    """
    settings = get_settings()
    effective_repo = repo_path or settings.target_repo_path

    handlers = make_docs_handlers(worktree_path, effective_repo)
    docs_result = handlers["_docs_result"]

    context = _build_docs_context(
        epic_title=epic_title,
        epic_description=epic_description,
        files_changed=files_changed,
        diffs=diffs,
        qa_summaries=qa_summaries,
    )

    final_text, tokens_in, tokens_out = run_agent(
        role_name="docs",
        model=settings.model_router,
        messages=[{"role": "user", "content": context}],
        tools=DOCS_TOOLS,
        tool_handlers=handlers,
    )

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
