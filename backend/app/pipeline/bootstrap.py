"""Blank Repo Bootstrap — Day 15.

Given an empty repo (no commits — either a bare `git init`ed directory or the
result of cloning a genuinely empty GitHub repo), scaffold a minimal initial
project structure and commit it before the normal PM->Architect->Decomposer
pipeline runs against it.

Pattern source: open-hands's app_conversation_service_base.py
run_setup_scripts()/clone_or_init_git_repo() — a fixed sequence of setup
phases with observable status, run before the agent's normal tools have
anything to work with. Adapted: this project's agents work against local
worktrees, not remote sandboxes, so the phases here are git-init -> scaffold
plan -> scaffold write -> commit, not remote-sandbox setup scripts.

A real, load-bearing constraint (verified against a real empty repo, not
assumed): `repo_tools.worktree.create_worktree()` runs `git worktree add -b
branch path`, which requires an existing commit to branch from — it fails
with "fatal: invalid reference: HEAD" against a zero-commit repo. Bootstrap
must therefore commit directly to the bare repo before any task worktree can
ever be created for it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.git_service import git_add, git_commit, git_init, git_log

logger = logging.getLogger(__name__)

_PROJECT_TYPES = ["web-app", "api", "cli", "library", "data-pipeline"]
_DEFAULT_PROJECT_TYPE = "web-app"

_SCAFFOLD_SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_scaffold_plan",
    "description": "Submit the proposed initial file/directory scaffold as structured JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "technical_approach": {"type": "string"},
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["path", "reason"],
                },
            },
        },
        "required": ["technical_approach", "files"],
    },
}


@dataclass
class BootstrapResult:
    bootstrapped: bool
    project_type: str = ""
    files_created: list[str] = field(default_factory=list)
    commit_sha: str | None = None
    error: str | None = None


def is_blank_repo(repo_path: str) -> bool:
    """True if repo_path has no commits yet — no `.git` at all, or a `.git`
    with zero commits (e.g. after cloning a genuinely empty GitHub repo)."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return result.returncode != 0 or not result.stdout.strip()


async def detect_project_type(task_description: str, model: str) -> str:
    """One Haiku call classifying the task into a known project type.
    Falls back to a deterministic default on any failure — never raises."""
    import anthropic

    from app.agents.base import get_effective_api_key

    prompt = (
        "What type of software project does this task describe? Respond with "
        f"ONLY one word from this exact list: {', '.join(_PROJECT_TYPES)}.\n\n"
        f"Task: {task_description[:500]}"
    )
    try:
        client = anthropic.Anthropic(api_key=get_effective_api_key())
        r = client.messages.create(
            model=model, max_tokens=10, messages=[{"role": "user", "content": prompt}]
        )
        text_blocks = []
        for b in r.content:
            if b.type == "text":
                text_blocks.append(b.text)
        answer = " ".join(text_blocks).strip().lower()
        for pt in _PROJECT_TYPES:
            if pt in answer:
                return pt
        return _DEFAULT_PROJECT_TYPE
    except Exception as exc:
        logger.warning("detect_project_type failed (non-fatal), using fallback: %s", exc)
        return _DEFAULT_PROJECT_TYPE


def run_scaffold_planning(
    repo_path: str, project_type: str, task_description: str
) -> dict[str, Any]:
    """Phase 2 — reuses the architect agent's identity (role_name='architect',
    roles/architect.md, settings.model_planner) with a scaffold-specific
    instruction instead of a PM brief. Sync — matches run_agent_graph()'s
    sync shape; call via asyncio.to_thread from async callers."""
    from app.agents.base_graph import VerificationConfig, run_agent_graph
    from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
    from app.config import get_settings

    settings = get_settings()
    handlers = make_read_only_handlers(repo_path)
    handlers["submit_scaffold_plan"] = lambda inp: "Scaffold plan submitted"

    verification_cfg = VerificationConfig(
        set_by={"submit_scaffold_plan": "plan_submitted"},
        reset_by=(),
        reset_keys=(),
        enforce_in_result={"plan_submitted": "plan_submitted"},
        initial={"plan_submitted": False},
    )

    initial_message = (
        "This is a BLANK repository — no commits exist yet.\n\n"
        f"Task the user wants to accomplish: {task_description}\n\n"
        f"Detected project type: {project_type}\n\n"
        "Propose a minimal, idiomatic initial file/directory scaffold for this "
        "project type (entry point, config, README, .gitignore, a minimal test "
        "if applicable). List each file to create and why, then call "
        "submit_scaffold_plan."
    )

    final_state = run_agent_graph(
        role_name="architect",
        model=settings.model_planner,
        tools=READ_ONLY_TOOLS + [_SCAFFOLD_SUBMIT_TOOL],
        tool_handlers=handlers,
        verification_cfg=verification_cfg,
        initial_message=initial_message,
        task_description=f"Blank-repo scaffold planning ({project_type})",
        repo_path=repo_path,
        model_haiku=settings.model_router,
        max_turns=15,
    )
    if not final_state.get("submitted"):
        raise RuntimeError("Architect did not submit a scaffold plan")
    result: dict[str, Any] = final_state.get("result", {})
    return {k: v for k, v in result.items() if not k.startswith("_")}


async def bootstrap(
    task_id: int,
    repo_path: str,
    task_description: str,
    project_type: str | None = None,
    db: Any = None,
) -> BootstrapResult:
    """Full 4-phase blank-repo bootstrap. No-op (bootstrapped=False, no error)
    if the repo already has commits. Every phase is logged via append_log
    (task detail page's existing log stream — no new frontend work needed).
    Any phase failure returns bootstrapped=False with .error set rather than
    raising, so a bootstrap failure degrades to running the normal pipeline
    against whatever state the repo ended up in."""
    from app.db.repository import append_log

    async def _log(message: str) -> None:
        if db is not None:
            try:
                await append_log(db, task_id, "bootstrap", message)
            except Exception:
                logger.debug("append_log failed during bootstrap (non-fatal)", exc_info=True)

    if not is_blank_repo(repo_path):
        return BootstrapResult(bootstrapped=False)

    from app.config import get_settings

    ptype = project_type or await detect_project_type(
        task_description, get_settings().model_router
    )
    await _log(f"Blank repo detected — bootstrapping as project_type={ptype}")

    import os

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        init_result = await git_init(repo_path)
        if not init_result["ok"]:
            err = f"git init failed: {init_result['stderr'][:300]}"
            await _log(err)
            return BootstrapResult(bootstrapped=False, project_type=ptype, error=err)

    await _log("Running scaffold planning (architect agent)")
    try:
        scaffold_plan = await asyncio.to_thread(
            run_scaffold_planning, repo_path, ptype, task_description
        )
    except Exception as exc:
        err = f"Scaffold planning failed: {exc}"
        await _log(err)
        return BootstrapResult(bootstrapped=False, project_type=ptype, error=err)

    await _log("Writing scaffold files (coder agent)")
    from app.agents.coder import run_coder

    files_changed, coder_error, _tok_in, _tok_out = await asyncio.to_thread(
        run_coder,
        task_id,
        json.dumps(scaffold_plan, indent=2),
        repo_path,  # worktree_path — no separate worktree exists yet
        repo_path,  # repo_path
    )
    if coder_error:
        await _log(f"Scaffold write failed: {coder_error}")
        return BootstrapResult(bootstrapped=False, project_type=ptype, error=coder_error)
    if not files_changed:
        err = "Scaffold write produced no files"
        await _log(err)
        return BootstrapResult(bootstrapped=False, project_type=ptype, error=err)

    add_result = await git_add(repo_path, files_changed)
    if not add_result["ok"]:
        err = f"git add failed: {add_result['stderr'][:300]}"
        await _log(err)
        return BootstrapResult(
            bootstrapped=False, project_type=ptype, files_created=files_changed, error=err
        )

    commit_result = await git_commit(
        repo_path,
        "chore: initial scaffold by gridiron",
        author_name="Gridiron Bootstrap",
        author_email="bootstrap@gridiron.local",
    )
    if not commit_result["ok"]:
        err = f"git commit failed: {commit_result['stderr'][:300]}"
        await _log(err)
        return BootstrapResult(
            bootstrapped=False, project_type=ptype, files_created=files_changed, error=err
        )

    log_result = await git_log(repo_path, limit=1)
    commits = log_result.get("commits", [])
    commit_sha = commits[0]["sha"] if commits else None

    await _log(f"Bootstrap complete — {len(files_changed)} files, commit {commit_sha}")
    return BootstrapResult(
        bootstrapped=True,
        project_type=ptype,
        files_created=files_changed,
        commit_sha=commit_sha,
    )
