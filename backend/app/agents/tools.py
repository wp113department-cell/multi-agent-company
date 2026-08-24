"""Standard tool definitions and handlers for agent use."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from app.agents.conflict_resolution import (
    _apply_conflict_resolutions as _apply_conflict_resolutions,
    _parse_conflict_markers as _parse_conflict_markers,
)
from app.agents.output_parsers import parse_diagnostic_summary
from app.agents.tool_security import (
    _docker_container_risk_reason as _docker_container_risk_reason,
    _extract_patch_target_paths as _extract_patch_target_paths,
    _is_dangerous_command as _is_dangerous_command,
    _is_protected_path as _is_protected_path,
    _mask_secret_value as _mask_secret_value,
    _redact_secrets_in_text as _redact_secrets_in_text,
    _scan_content_for_secrets as _scan_content_for_secrets,
    _scan_directory_for_secrets as _scan_directory_for_secrets,
    _shell_metachar_reason as _shell_metachar_reason,
    _ssrf_denial_reason as _ssrf_denial_reason,
)
from app.config import get_settings
from app.policy.engine import (
    check_allowlisted_command,
    check_command,
    check_command_stays_in_boundary,
    check_path_in_worktree,
)

# tool_enhance.md productionization pass, tool #1 (bash), 2026-08-15 — the
# FIRST step of this file's own gradual modularization (§7/§8). Real
# migration report: app/tools/execution/bash.py's own module docstring.
# Compatibility shim (§9): every name below still resolves via
# `from app.agents.tools import X` exactly as before this move — owner =
# this productionization pass, reason = avoid a repo-wide mechanical edit
# across every agent file that imports these names for a move that doesn't
# change behavior, migration target = agent files import directly from
# app.tools.execution.bash at a later, separate, per-caller-verified pass,
# removal condition = every real caller individually confirmed migrated.
from app.tools.execution.bash import (
    DEPENDENCY_AUDIT_ALLOWED_PREFIXES as DEPENDENCY_AUDIT_ALLOWED_PREFIXES,
    DEPENDENCY_AUDIT_BASH_TOOL as DEPENDENCY_AUDIT_BASH_TOOL,
    INFRA_DRY_RUN_ALLOWED_PREFIXES as INFRA_DRY_RUN_ALLOWED_PREFIXES,
    INFRA_DRY_RUN_BASH_TOOL as INFRA_DRY_RUN_BASH_TOOL,
    LOAD_TEST_ALLOWED_PREFIXES as LOAD_TEST_ALLOWED_PREFIXES,
    LOAD_TEST_BASH_TOOL as LOAD_TEST_BASH_TOOL,
    TEST_RUNNER_ALLOWED_PREFIXES as TEST_RUNNER_ALLOWED_PREFIXES,
    TEST_RUNNER_BASH_TOOL as TEST_RUNNER_BASH_TOOL,
    _FLEET_BASH_TOOL as _FLEET_BASH_TOOL,
    _run_bash_command as _run_bash_command,
    make_dependency_audit_bash_handler as make_dependency_audit_bash_handler,
    make_infra_dry_run_bash_handler as make_infra_dry_run_bash_handler,
    make_load_test_bash_handler as make_load_test_bash_handler,
    make_scoped_bash_handler as make_scoped_bash_handler,
    make_test_runner_bash_handler as make_test_runner_bash_handler,
)
from app.tools.browser.browser_tools import (
    BROWSER_CLICK_TOOL as _BROWSER_CLICK_TOOL,
    BROWSER_CLOSE_TOOL as _BROWSER_CLOSE_TOOL,
    BROWSER_NAVIGATE_TOOL as _BROWSER_NAVIGATE_TOOL,
    BROWSER_OPEN_TOOL as _BROWSER_OPEN_TOOL,
    BROWSER_READ_DOM_TOOL as _BROWSER_READ_DOM_TOOL,
    BROWSER_SCREENSHOT_TOOL as _BROWSER_SCREENSHOT_TOOL,
    BROWSER_TYPE_TOOL as _BROWSER_TYPE_TOOL,
    browser_click_handler as browser_click_handler,
    browser_close_handler as browser_close_handler,
    browser_navigate_handler as browser_navigate_handler,
    browser_open_handler as browser_open_handler,
    browser_read_dom_handler as browser_read_dom_handler,
    browser_screenshot_handler as browser_screenshot_handler,
    browser_type_handler as browser_type_handler,
)
from app.tools.agents.delegate import (
    DELEGATE_TO_AGENT_TOOL as _DELEGATE_TO_AGENT_TOOL,
    make_delegate_to_agent_handler as make_delegate_to_agent_handler,
)
from app.tools.agents.memory_write import (
    MEMORY_WRITE_TOOL as _MEMORY_WRITE_TOOL,
    write_memory_key as write_memory_key,
)
from app.tools.agents.propose_subtask import (
    PROPOSE_SUBTASK_TOOL as PROPOSE_SUBTASK_TOOL,
    make_propose_subtask_handler as make_propose_subtask_handler,
)
from app.tools.agents.record_learning import (
    RECORD_LEARNING_TOOL as RECORD_LEARNING_TOOL,
    make_record_learning_handler as make_record_learning_handler,
)
from app.tools.agents.submit_docs import (
    SUBMIT_DOCS_TOOL,
    make_submit_docs_handler,
)
from app.tools.database.migration import (
    RUN_MIGRATION_TOOL as _RUN_MIGRATION_TOOL,
    run_migration_handler as run_migration_handler,
    validate_run_migration_inputs as validate_run_migration_inputs,
)
from app.tools.database.seed import (
    SEED_DATABASE_TOOL as _SEED_DATABASE_TOOL,
    seed_database_handler as seed_database_handler,
    validate_seed_database_script as validate_seed_database_script,
)
from app.tools.execution.parallel import (
    RUN_PARALLEL_COMMANDS_TOOL as _RUN_PARALLEL_COMMANDS_TOOL,
    run_parallel_commands_handler as run_parallel_commands_handler,
)
from app.tools.database.sql import (
    RUN_SQL_TOOL as _RUN_SQL_TOOL,
    run_sql_handler as run_sql_handler,
)
from app.tools.execution.docker_build import (
    DOCKER_BUILD_TOOL as _DOCKER_BUILD_TOOL,
    validate_docker_build_inputs as validate_docker_build_inputs,
)
from app.tools.execution.docker_compose import (
    DOCKER_COMPOSE_TOOL as _DOCKER_COMPOSE_TOOL,
    build_docker_compose_command as build_docker_compose_command,
)
from app.tools.execution.fetch_url import (
    FETCH_URL_TOOL,
    fetch_url_handler,
)
from app.tools.execution.docker_exec import (
    DOCKER_EXEC_TOOL as _DOCKER_EXEC_TOOL,
    build_docker_exec_command as build_docker_exec_command,
)
from app.tools.execution.docker_restart import (
    DOCKER_RESTART_TOOL as _DOCKER_RESTART_TOOL,
    build_docker_restart_command as build_docker_restart_command,
)
from app.tools.execution.kill_process import (
    KILL_PROCESS_TOOL as _KILL_PROCESS_TOOL,
)
from app.tools.execution.npm_install import (
    NPM_INSTALL_TOOL as _NPM_INSTALL_TOOL,
)
from app.tools.execution.npm_run import (
    NPM_RUN_TOOL as _NPM_RUN_TOOL,
)
from app.tools.execution.pip_install import (
    PIP_INSTALL_TOOL as _PIP_INSTALL_TOOL,
)
from app.tools.execution.python_snippet import (
    RUN_PYTHON_SNIPPET_TOOL as _RUN_PYTHON_SNIPPET_TOOL,
    run_python_snippet_handler as run_python_snippet_handler,
)
from app.tools.execution.run_background import (
    RUN_BACKGROUND_TOOL,
    validate_run_background_cwd as validate_run_background_cwd,
)
from app.tools.execution.run_make import (
    RUN_MAKE_TOOL,
    run_make_handler,
)
from app.tools.execution.run_node import (
    RUN_NODE_TOOL,
    run_node_handler,
)
from app.tools.execution.run_script import (
    RUN_SCRIPT_TOOL,
    run_script_handler,
)
from app.tools.execution.run_single_test import (
    RUN_SINGLE_TEST_TOOL,
    run_single_test_handler,
)
from app.tools.execution.run_tests import (
    RUN_TESTS_TOOL as _RUN_TESTS_TOOL,
    run_tests_handler as run_tests_handler,
)
from app.tools.filesystem.append_file import (
    APPEND_FILE_TOOL as _APPEND_FILE_TOOL,
    append_file_handler as append_file_handler,
)
from app.tools.filesystem.delete_block import (
    DELETE_BLOCK_TOOL as _DELETE_BLOCK_TOOL,
    delete_block_handler as delete_block_handler,
)
from app.tools.filesystem.delete_lines import (
    DELETE_LINES_TOOL as _DELETE_LINES_TOOL,
    delete_lines_handler as delete_lines_handler,
)
from app.tools.filesystem.apply_patch import (
    APPLY_PATCH_TOOL as _APPLY_PATCH_TOOL_DEF,
    apply_patch_handler as apply_patch_handler,
)
from app.tools.filesystem.delete_file import (
    DELETE_FILE_TOOL as _DELETE_FILE_TOOL,
    delete_file_handler as delete_file_handler,
)
from app.tools.filesystem.edit_file import (
    EDIT_FILE_TOOL as _EDIT_FILE_TOOL,
    edit_file_handler as edit_file_handler,
)
from app.tools.filesystem.insert_after import (
    INSERT_AFTER_TOOL as _INSERT_AFTER_TOOL,
    insert_after_handler as insert_after_handler,
)
from app.tools.filesystem.insert_at_line import (
    INSERT_AT_LINE_TOOL as _INSERT_AT_LINE_TOOL,
    insert_at_line_handler as insert_at_line_handler,
)
from app.tools.filesystem.insert_before import (
    INSERT_BEFORE_TOOL as _INSERT_BEFORE_TOOL,
    insert_before_handler as insert_before_handler,
)
from app.tools.filesystem.analyze_file import (
    ANALYZE_FILE_TOOL,
    analyze_file_handler,
)
from app.tools.filesystem.find_api import (
    FIND_API_TOOL as _FIND_API_TOOL,
    find_api_handler,
)
from app.tools.filesystem.find_route import (
    FIND_ROUTE_TOOL as _FIND_ROUTE_TOOL,
    find_route_handler,
)
from app.tools.filesystem.file_exists import (
    FILE_EXISTS_TOOL,
    file_exists_handler,
)
from app.tools.filesystem.file_info import (
    FILE_INFO_TOOL,
    file_info_handler,
)
from app.tools.filesystem.find_references import (
    FIND_REFERENCES_TOOL,
    find_references_handler,
)
from app.tools.filesystem.find_todos import (
    FIND_TODOS_TOOL,
    find_todos_handler,
)
from app.tools.filesystem.search_imports import (
    SEARCH_IMPORTS_TOOL,
    search_imports_handler,
)
from app.tools.filesystem.get_file_tree import (
    GET_FILE_TREE_TOOL,
    get_file_tree_handler,
)
from app.tools.filesystem.list_classes import (
    LIST_CLASSES_TOOL,
    list_classes_handler,
)
from app.tools.filesystem.list_files import (
    LIST_FILES_TOOL,
    list_files_handler,
)
from app.tools.filesystem.list_functions import (
    LIST_FUNCTIONS_TOOL,
    list_functions_handler,
)
from app.tools.filesystem.parse_ast import (
    PARSE_AST_TOOL,
    parse_ast_handler,
)
from app.tools.filesystem.search_code import (
    SEARCH_CODE_TOOL,
    search_code_handler,
)
from app.tools.filesystem.search_symbols import (
    SEARCH_SYMBOLS_TOOL,
    search_symbols_handler,
)
from app.tools.filesystem.read_file import (
    READ_FILE_TOOL,
    read_file_handler,
)
from app.tools.filesystem.read_files import (
    READ_FILES_TOOL,
    read_files_handler,
)
from app.tools.filesystem.move_file import (
    MOVE_FILE_TOOL as _MOVE_FILE_TOOL,
    move_file_handler as move_file_handler,
)
from app.tools.filesystem.rename_file import (
    RENAME_FILE_TOOL as _RENAME_FILE_TOOL,
    rename_file_handler as rename_file_handler,
)
from app.tools.filesystem.replace_class import (
    REPLACE_CLASS_TOOL as _REPLACE_CLASS_TOOL,
    replace_class_handler as replace_class_handler,
)
from app.tools.filesystem.replace_function import (
    REPLACE_FUNCTION_TOOL as _REPLACE_FUNCTION_TOOL,
    replace_function_handler as replace_function_handler,
)
from app.tools.filesystem.semver_bump import (
    SEMVER_BUMP_TOOL,
    semver_bump_handler as semver_bump_handler,
)
from app.tools.filesystem.sync_files import (
    SYNC_FILES_TOOL,
    sync_files_handler,
)
from app.tools.filesystem.write_file import (
    WRITE_FILE_TOOL as _WRITE_FILE_TOOL,
    write_file_handler as write_file_handler,
)
from app.tools.git.blame import (
    GIT_BLAME_TOOL,
    git_blame_handler,
)
from app.tools.git.checkout import (
    GIT_CHECKOUT_TOOL as _GIT_CHECKOUT_TOOL,
    validate_git_checkout_inputs as validate_git_checkout_inputs,
)
from app.tools.git.cherry_pick import (
    GIT_CHERRY_PICK_TOOL as _GIT_CHERRY_PICK_TOOL,
    validate_git_cherry_pick_inputs as validate_git_cherry_pick_inputs,
)
from app.tools.git.commit import (
    GIT_COMMIT_TOOL as _GIT_COMMIT_TOOL,
    stage_and_commit as stage_and_commit,
)
from app.tools.git.create_branch import (
    CREATE_BRANCH_TOOL as _CREATE_BRANCH_TOOL,
    validate_create_branch_inputs as validate_create_branch_inputs,
)
from app.tools.git.diff import (
    GIT_DIFF_TOOL,
    git_diff_handler,
)
from app.tools.git.github_comment import (
    GITHUB_COMMENT_TOOL as _GITHUB_COMMENT_TOOL,
    github_comment_command as github_comment_command,
)
from app.tools.git.github_create_issue import (
    GITHUB_CREATE_ISSUE_TOOL as _GITHUB_CREATE_ISSUE_TOOL,
    github_create_issue_command as github_create_issue_command,
)
from app.tools.git.log import (
    GIT_LOG_TOOL,
    git_log_handler,
)
from app.tools.git.merge import (
    GIT_MERGE_TOOL as _GIT_MERGE_TOOL,
    validate_git_merge_inputs as validate_git_merge_inputs,
)
from app.tools.git.pull import (
    GIT_PULL_TOOL as _GIT_PULL_TOOL,
    validate_git_pull_inputs as validate_git_pull_inputs,
)
from app.tools.git.pull_request import (
    CREATE_PR_TOOL as _CREATE_PR_TOOL,
    GITHUB_CREATE_PR_TOOL as _GITHUB_CREATE_PR_TOOL,
    create_pr_handler as create_pr_handler,
)
from app.tools.git.push import (
    GIT_PUSH_TOOL as _GIT_PUSH_TOOL,
    git_push_handler as git_push_handler,
)
from app.tools.git.rebase import (
    GIT_REBASE_TOOL as _GIT_REBASE_TOOL,
    validate_git_rebase_inputs as validate_git_rebase_inputs,
)
from app.tools.git.reset import (
    GIT_RESET_TOOL as _GIT_RESET_TOOL,
    git_reset_handler as git_reset_handler,
)
from app.tools.git.restore import GIT_RESTORE_TOOL as _GIT_RESTORE_TOOL
from app.tools.git.show import (
    GIT_SHOW_TOOL,
    git_show_handler,
)
from app.tools.git.status import (
    GIT_STATUS_TOOL,
    git_status_handler,
)
from app.tools.git.stash import (
    GIT_STASH_TOOL as _GIT_STASH_TOOL,
    validate_git_stash_action as validate_git_stash_action,
)
from app.tools.git.tag import (
    GIT_TAG_TOOL,
    git_tag_handler as git_tag_handler,
)
from app.tools.git.worktree import (
    GIT_WORKTREE_TOOL as _GIT_WORKTREE_TOOL,
    validate_git_worktree_inputs as validate_git_worktree_inputs,
)
from app.tools.integrations.linear_create_issue import (
    LINEAR_CREATE_ISSUE_TOOL as _LINEAR_CREATE_ISSUE_TOOL,
    create_linear_issue as create_linear_issue,
)
from app.tools.integrations.slack_send_message import (
    SLACK_SEND_MESSAGE_TOOL,
    send_slack_message,
)
from app.tools.integrations.web_search import (
    WEB_SEARCH_TOOL,
    web_search_handler as web_search_handler,
)
from app.tools.refactor.rename_symbol import (
    RENAME_SYMBOL_TOOL as _RENAME_SYMBOL_TOOL,
    validate_rename_symbol_directory as validate_rename_symbol_directory,
)

# mypy --strict flags a renaming `as` import (`X as _X`) as not
# "explicitly exported" when another module imports the name directly
# from app.agents.tools. A plain module-level assignment IS recognized
# as a genuine definition here. tool_enhance.md productionization
# pass, tool #86 (2026-08-24) — _LIST_FUNCTIONS_TOOL/_PARSE_AST_TOOL
# were a pre-existing gap from tools #82/#83, caught and fixed
# alongside _FETCH_URL_TOOL's identical issue (missed then because a
# per-file mypy check on the new module alone doesn't follow imports
# to external CONSUMERS of app.agents.tools). Tool #88 (2026-08-24)
# applied the lesson proactively for _WEB_SEARCH_TOOL, then ran a
# COMPREHENSIVE `mypy app/agents/` sweep (not just tools.py) that
# surfaced three more pre-existing instances from even earlier tools:
# _SUBMIT_DOCS_TOOL (tool #85), _GIT_TAG_TOOL (tool #22),
# _SEMVER_BUMP_TOOL (tool #25) — all fixed together here rather than
# left for a future turn to rediscover one at a time.
_FETCH_URL_TOOL = FETCH_URL_TOOL
_LIST_FUNCTIONS_TOOL = LIST_FUNCTIONS_TOOL
_PARSE_AST_TOOL = PARSE_AST_TOOL
_WEB_SEARCH_TOOL = WEB_SEARCH_TOOL
_SUBMIT_DOCS_TOOL = SUBMIT_DOCS_TOOL
_SEMVER_BUMP_TOOL = SEMVER_BUMP_TOOL
_GIT_TAG_TOOL = GIT_TAG_TOOL


# ---------------------------------------------------------------------------
# Cross-platform venv-activation snippet — Stage 4 Tier 3 (2026-08-05,
# answer2.md Q1: "Windows support is real but incomplete... POSIX-only
# shell patterns still hardcoded"). 11 real call sites in this file built
# their own command string as `f"cd {repo_path} && source .venv/bin/
# activate 2>/dev/null || true && <cmd>"` (or the equivalent `activate =
# f"source {repo_path}/.venv/bin/activate ..."` form) — every one of the
# tools that run pytest/ruff/mypy/black. subprocess.run(cmd, shell=True)
# invokes cmd.exe on Windows, not bash, so `source`/`.venv/bin/activate`/
# `2>/dev/null` are all syntactically meaningless there. One prior comment
# in this file (near the run_tests_h handler) already described this as
# "degrades safely on both shells" — true in the sense that it never
# crashed on Windows (`|| true` swallowed the unrecognized-command error),
# but the venv was silently never actually activated there, which is a
# real, different problem (wrong/missing interpreter, wrong installed
# packages) from "crashes."
# ---------------------------------------------------------------------------


def _venv_activate_snippet() -> str:
    """Returns a shell snippet that activates `.venv` in the current
    directory, for the current platform — chain explicitly:
    `f"cd {repo_path} && {_venv_activate_snippet()} && <command>"`.
    Never raises, never blocks: both branches degrade to "activation
    silently skipped" if `.venv` doesn't exist, matching this codebase's
    own established `2>/dev/null || true` degrade-safely convention exactly
    (Windows: `2>nul` is cmd.exe's equivalent null-redirect; `(... || ver
    >nul)` is cmd.exe's equivalent of `|| true` — `ver` always succeeds and
    discards its own output, there being no simpler always-succeeding
    builtin in cmd.exe the way POSIX shells have `true`).
    """
    if sys.platform == "win32":
        return ".venv\\Scripts\\activate.bat 2>nul || ver>nul"
    return "source .venv/bin/activate 2>/dev/null || true"


# Stage 4 Tier 3 (2026-08-05, answer2.md Q17) — real, bounded structured
# pattern-detection over raw docker_logs output (previously returned
# completely unparsed, per that finding). Mirrors this same file's own
# established analyze_error() convention exactly (real pattern list,
# "=== X Analysis ===" formatted summary prepended to the real content, not
# replacing it). Docker containers run arbitrary applications with no fixed
# log schema, so this is deliberately pattern/keyword detection, not a
# claim of full structured (e.g. JSON) log parsing for every possible
# container.
_DOCKER_LOG_ERROR_PATTERNS = (
    "error",
    "exception",
    "fatal",
    "panic",
    "traceback",
    "failed",
)
_DOCKER_LOG_WARNING_PATTERNS = ("warn",)
_DOCKER_LOG_CRASH_PATTERNS = (
    "oomkilled",
    "out of memory",
    "sigkill",
    "sigsegv",
    "segmentation fault",
    "core dumped",
    "exit code 1",
    "exit code 137",
)


def _summarize_docker_log_patterns(raw_log: str) -> str:
    lines = raw_log.splitlines()
    error_lines = [
        ln for ln in lines if any(p in ln.lower() for p in _DOCKER_LOG_ERROR_PATTERNS)
    ]
    warning_lines = [
        ln
        for ln in lines
        if any(p in ln.lower() for p in _DOCKER_LOG_WARNING_PATTERNS)
        and ln not in error_lines
    ]
    crash_lines = [
        ln for ln in lines if any(p in ln.lower() for p in _DOCKER_LOG_CRASH_PATTERNS)
    ]

    if not error_lines and not warning_lines and not crash_lines:
        return ""

    parts = ["=== Docker Log Analysis ==="]
    if crash_lines:
        parts.append(f"Crash/OOM signatures ({len(crash_lines)}):")
        parts.extend(f"  {ln.strip()}" for ln in crash_lines[:5])
    if error_lines:
        parts.append(f"Error/exception lines ({len(error_lines)}):")
        parts.extend(f"  {ln.strip()}" for ln in error_lines[:5])
    if warning_lines:
        parts.append(f"Warning lines ({len(warning_lines)}):")
        parts.extend(f"  {ln.strip()}" for ln in warning_lines[:5])
    parts.append("--- raw log below ---\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §19/§20/§40 — shared LLM-generation helper for tool-level
# "generate X" capabilities (commit messages, PR descriptions, diff reviews,
# conflict explanations, URL summaries, deployment diagnosis). Every prior
# instance of these ("generate_commit_msg" etc.) only returned raw git/log
# data and left the actual generation implicit — delegated to whichever
# agent happened to call the tool next turn, per the audit's own finding.
# This gives each of those tools a REAL, independently-testable generation
# step, reusing the same client/circuit-breaker path run_agent_graph()
# itself uses (_make_client/_call_anthropic in base_graph.py) rather than
# constructing a second, unprotected Anthropic client — matching the
# `_merge_via_llm` pattern already established in app/fleet/versioned_memory.py.
# Every call site treats "" as "generation unavailable" and falls back to
# its own pre-existing, non-LLM behavior — never a fake/invented result.
# ---------------------------------------------------------------------------


def _llm_generate_text(
    prompt: str, *, max_tokens: int = 600, model: str | None = None
) -> str:
    """One-shot LLM text generation. Never raises — returns "" on any failure
    (missing/invalid API key, network error, rate limit) so every caller can
    degrade gracefully instead of crashing the tool call."""
    try:
        from app.agents.base_graph import (
            _call_anthropic,
            _make_client,
            _serialize_content,
            _text_from_content,
        )

        client = _make_client()
        r = _call_anthropic(
            client,
            model=model or get_settings().model_router,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return _text_from_content(_serialize_content(r.content)).strip()
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "_llm_generate_text: generation call failed", exc_info=True
        )
        return ""


def _llm_generate_commit_message(stat: str, diff: str) -> str:
    prompt = (
        "Write a git commit message for the real staged changes below. "
        "Respond with ONLY the commit message text — no preamble, no markdown "
        "code fences, no labels.\n\n"
        "Format: <type>(<scope>): <description>\n"
        "Types: feat, fix, docs, refactor, test, chore, style, perf. Add a body "
        "only if the change needs more than one line of explanation, grounded "
        "strictly in the diff below — never invent changes not shown.\n\n"
        f"=== Changed files ===\n{stat}\n\n=== Diff (truncated) ===\n{diff}"
    )
    return _llm_generate_text(prompt, max_tokens=300)


# _llm_generate_pr_description moved to app/tools/git/pull_request.py as
# generate_pr_description() — tool_enhance.md productionization pass,
# tool #2 (2026-08-15). See that module's TOOL PATH MIGRATION REPORT.


def _llm_review_diff(stat: str, diff: str) -> str:
    prompt = (
        "Review the real git diff below. Produce a concise, structured review "
        "with exactly these sections:\n"
        "1. Summary — what changed, in plain English (2-4 sentences).\n"
        "2. Risk callouts — anything that looks unsafe, untested, or likely to "
        "break something. Only real, specific observations grounded in the "
        "diff below — never an invented issue.\n"
        "3. Notable omissions — e.g. missing tests for new logic, if evident "
        "from the diff alone.\n"
        "Cite actual file names and describe the actual change, not generic "
        "advice.\n\n"
        f"=== Changed files ===\n{stat}\n\n=== Diff ===\n{diff}"
    )
    return _llm_generate_text(prompt, max_tokens=900)


def _llm_explain_conflict_hunks(path: str, hunks: list[dict[str, Any]]) -> str:
    import json as _json

    prompt = (
        f"The file {path} has real, unresolved git merge conflicts. Below is "
        "structured hunk data (ours/theirs text, line ranges) already parsed "
        "from the real conflict markers. Explain, in plain English, what each "
        "hunk's conflict actually is — what 'ours' changed vs what 'theirs' "
        "changed, and why they conflict — grounded strictly in the hunk "
        "content below. Do not recommend a resolution; only explain.\n\n"
        f"{_json.dumps(hunks, indent=2)}"
    )
    result = _llm_generate_text(prompt, max_tokens=700)
    return result or f"[ERROR] Could not generate an explanation for {path}."


def _llm_summarize_url_content(url: str, content: str) -> str:
    prompt = (
        f"Summarize the real page content fetched from {url} below. Focus on "
        "what the page is about and any concrete facts, APIs, or instructions "
        "it contains — 3-6 sentences, grounded strictly in the text below, "
        "never invented.\n\n"
        f"{content[:10000]}"
    )
    return _llm_generate_text(prompt, max_tokens=400)


def _llm_diagnose_deployment_failure(context: str) -> str:
    prompt = (
        "You are diagnosing a real deployment/container failure. Below is "
        "real gathered state (docker ps / docker logs / docker inspect). "
        "Identify:\n"
        "1. What actually failed — cite the exact error line(s).\n"
        "2. The most likely root cause, grounded only in the evidence below.\n"
        "3. A concrete next diagnostic step or fix to try.\n"
        "If the evidence is insufficient to reach a conclusion, say so "
        "explicitly rather than guessing.\n\n"
        f"{context}"
    )
    result = _llm_generate_text(prompt, max_tokens=700)
    return result or "[ERROR] Diagnosis generation failed — see raw state above."


# --- Tool specs (Anthropic input_schema format) ---

# tool_enhance.md productionization pass, tool #65 (2026-08-22) —
# READ_ONLY_TOOLS[0] moved to app/tools/filesystem/read_file.py as
# READ_FILE_TOOL. Kept at the SAME list index deliberately: RESEARCH_TOOLS
# (below) and other bundles index into READ_ONLY_TOOLS positionally.
READ_ONLY_TOOLS = [
    READ_FILE_TOOL,
    # tool_enhance.md productionization pass, tool #68 (2026-08-22) —
    # moved to app/tools/filesystem/list_files.py as LIST_FILES_TOOL.
    # Kept at the SAME list index deliberately: RESEARCH_TOOLS indexes
    # into READ_ONLY_TOOLS positionally.
    LIST_FILES_TOOL,
    # tool_enhance.md productionization pass, tool #69 (2026-08-22) —
    # moved to app/tools/filesystem/search_code.py as SEARCH_CODE_TOOL.
    # Kept at the SAME list index deliberately: RESEARCH_TOOLS indexes
    # into READ_ONLY_TOOLS positionally.
    SEARCH_CODE_TOOL,
    # tool_enhance.md productionization pass, tool #73 (2026-08-22) —
    # moved to app/tools/filesystem/search_symbols.py as
    # SEARCH_SYMBOLS_TOOL. No new vulnerability — see that module's
    # docstring for the full audit.
    SEARCH_SYMBOLS_TOOL,
    # tool_enhance.md productionization pass, tool #67 (2026-08-22) —
    # moved to app/tools/filesystem/get_file_tree.py as GET_FILE_TREE_TOOL.
    # Kept at the SAME list index deliberately: RESEARCH_TOOLS indexes
    # into READ_ONLY_TOOLS positionally (READ_ONLY_TOOLS[4] is expected
    # to be get_file_tree — see the comment near RESEARCH_TOOLS below).
    GET_FILE_TREE_TOOL,
    # tool_enhance.md productionization pass, tool #78 (2026-08-23) —
    # moved to app/tools/git/log.py as GIT_LOG_TOOL. See that module's
    # docstring — an uncaught ValueError/TypeError on a non-numeric
    # `count`, on BOTH real implementations; `file` already safe by
    # construction (`--` separator + git's own outside-repo refusal,
    # both verified live).
    GIT_LOG_TOOL,
    # ---- Enhanced search & analysis tools (non-destructive) ----
    # tool_enhance.md productionization pass, tool #71 (2026-08-22) —
    # moved to app/tools/filesystem/read_files.py as READ_FILES_TOOL.
    READ_FILES_TOOL,
    # tool_enhance.md productionization pass, tool #70 (2026-08-22) —
    # moved to app/tools/filesystem/file_exists.py as FILE_EXISTS_TOOL.
    FILE_EXISTS_TOOL,
    # tool_enhance.md productionization pass, tool #72 (2026-08-22) —
    # moved to app/tools/filesystem/file_info.py as FILE_INFO_TOOL.
    FILE_INFO_TOOL,
    # tool_enhance.md productionization pass, tool #74 (2026-08-22) —
    # moved to app/tools/filesystem/find_references.py as
    # FIND_REFERENCES_TOOL. No new vulnerability — see that module's
    # docstring for the full audit.
    FIND_REFERENCES_TOOL,
    # tool_enhance.md productionization pass, tool #77 (2026-08-23) —
    # moved to app/tools/filesystem/find_todos.py as FIND_TODOS_TOOL.
    # See that module's docstring — like tool #76's analyze_file, the
    # CANONICAL implementation itself, not just chat_agent.py's copy,
    # had the worktree-escape bug.
    FIND_TODOS_TOOL,
    # tool_enhance.md productionization pass, tool #75 (2026-08-22) —
    # moved to app/tools/filesystem/search_imports.py as
    # SEARCH_IMPORTS_TOOL. No new vulnerability — see that module's
    # docstring for the full audit.
    SEARCH_IMPORTS_TOOL,
    # tool_enhance.md productionization pass, tool #79 (2026-08-23) —
    # moved to app/tools/git/status.py as GIT_STATUS_TOOL. See that
    # module's docstring — no security vulnerability (zero-input
    # schema), but a real functionality bug: this implementation
    # silently reported "(clean)" even when `git status` genuinely
    # failed, never checking returncode.
    GIT_STATUS_TOOL,
    # tool_enhance.md productionization pass, tool #80 (2026-08-23) —
    # moved to app/tools/git/show.py as GIT_SHOW_TOOL. See that
    # module's docstring — the MOST SEVERE finding in the low-risk
    # tier so far: `ref` was flag-collision vulnerable to git's own
    # `--output=<path>` flag, a silent arbitrary-file-write primitive,
    # on BOTH real implementations.
    GIT_SHOW_TOOL,
    # tool_enhance.md productionization pass, tool #81 (2026-08-23) —
    # moved to app/tools/git/blame.py as GIT_BLAME_TOOL. See that
    # module's docstring — same flag-collision class as tool #80's
    # git_show (path had no `--` separator), checked and confirmed
    # lower severity here (no --output-equivalent flag exists for git
    # blame), fixed defensively anyway per this initiative's
    # consistent policy.
    GIT_BLAME_TOOL,
    # tool_enhance.md productionization pass, tool #76 (2026-08-22) —
    # moved to app/tools/filesystem/analyze_file.py as ANALYZE_FILE_TOOL.
    # See that module's docstring — this was the first READ_ONLY_TOOLS
    # tool where the CANONICAL implementation itself, not just
    # chat_agent.py's copy, had the worktree-escape bug.
    ANALYZE_FILE_TOOL,
]

# ---------------------------------------------------------------------------
# record_learning — MASTER_AGENT_v2.md Phase 1.4. A single, explicit,
# agent-controlled write path into shared fleet memory, distinct from the
# automatic post-run hook (app/memory/hooks.py). The automatic hook captures
# every run's outcome regardless of whether anything unusual happened; this
# tool lets an agent flag a *specific* non-obvious finding mid-run — the kind
# of thing a generic outcome summary would not surface (a root cause, a
# workaround, a gotcha another agent working on a similar task would want).
# ---------------------------------------------------------------------------

# moved to app/tools/agents/record_learning.py — tool_enhance.md
# productionization pass, tool #66 (2026-08-22). No fix required (see
# that module's own docstring for the full audit) — pure modularization.
# RECORD_LEARNING_TOOL / make_record_learning_handler imported below,
# same names, so every existing reference in this file keeps working
# unchanged.


# ---------------------------------------------------------------------------
# record_preference — AUDIT_Q_BATCH15 §74/§113 gap-closure (2026-08-11). A
# human-stated coding-style/naming/tooling/testing preference had no
# dedicated write path anywhere — it would have been shoehorned into
# record_learning above (whose embed_learning_signal target is documented as
# a *fleet self-improvement* signal, not a per-project human preference) or
# lost entirely. Chat is the direct human-facing conversational surface
# where a preference is naturally stated ("always use f-strings", "prefer
# pytest fixtures"), so this is wired into CHAT_TOOLS; retrieval
# (memory_hook_node) applies to every agent regardless of which surface
# wrote the preference.
# ---------------------------------------------------------------------------

RECORD_PREFERENCE_TOOL: dict[str, Any] = {
    "name": "record_preference",
    "description": (
        "Record a stated human preference (coding style, naming convention, "
        "testing approach, tooling choice, workflow) so future work in this "
        "project applies it without being re-told. Use this only for a real "
        "preference the user actually expressed, not an inferred guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "preference": {
                "type": "string",
                "description": "The preference itself, in the user's own terms.",
            },
            "scope": {
                "type": "string",
                "description": "Short label for what this preference governs, e.g. "
                "'style', 'naming', 'testing', 'tooling', 'workflow'.",
            },
        },
        "required": ["preference"],
    },
}


def make_record_preference_handler(
    task_id: str = "chat",
) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for record_preference. task_id defaults
    to a synthetic "chat" marker (mirrors record_learning's "fleet-{agent}"
    synthetic task_id convention) since a stated preference isn't tied to
    one specific DevTask."""

    def _handler(inp: dict[str, Any]) -> str:
        preference = str(inp.get("preference", "")).strip()
        if not preference:
            return "[ERROR] preference is required."
        scope = str(inp.get("scope", "")).strip() or "general"

        from app.memory.store import embed_preference_sync

        stored = embed_preference_sync(
            task_id=task_id, preference=preference, scope=scope
        )
        return "Recorded." if stored else "[ERROR] failed to record preference."

    return _handler


# ---------------------------------------------------------------------------
# request_clarification — MASTER_AGENT_v2.md Phase 5.3. Real, but scoped to
# what base_graph.py (the graph every worker agent besides pm/architect/
# decomposer runs on) can actually support today: it has no checkpointer or
# interrupt()/Command(resume=...) machinery of its own (that only exists in
# app/pipeline/graph.py's separate pm->architect->decomposer pipeline — a
# genuinely different graph). A true mid-run pause/resume for base_graph.py
# agents is graph-level work (Phase 5.1/5.5's territory, not a single tool).
# This is the real, working version that fits the existing shape instead:
# the agent ends its run cleanly (status="needs_clarification", not a silent
# hang or a crash) after recording a real PendingApproval row through the
# same table/mechanism app/fleet/approval_gate.py already uses for the
# pm/architect/decomposer pipeline's own human_review pause — a caller that
# re-dispatches the agent with the human's answer folded into a fresh
# initial_message is how "resume" works for this graph shape.
# ---------------------------------------------------------------------------

REQUEST_CLARIFICATION_TOOL: dict[str, Any] = {
    "name": "request_clarification",
    "description": (
        "Use ONLY when the task is genuinely underspecified and continuing would "
        "mean guessing at something a human should decide — not for every minor "
        "judgment call (a reasonable, disclosed assumption is almost always "
        "better than stopping to ask). Ends this run; a human or upstream agent "
        "answers, and a future run receives that answer in its task context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific, genuine blocker — not a vague 'is this ok?'",
            },
            "context": {
                "type": "string",
                "description": "What you already tried/considered, so the answer doesn't have to re-derive it.",
            },
            # AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) — "Present options
            # (multi-choice): NO" / "Recommend choices: PARTIAL — no
            # structured recommendation field." Optional and additive: a
            # human/upstream-agent reviewer answering via
            # app.fleet.approval_gate's existing PendingApproval row now
            # sees these as structured fields (not just prose buried in
            # `context`), without changing this tool's "ends the run, a
            # future run receives the answer" scope at all.
            "options": {
                "type": "array",
                "description": "Optional: 2-5 distinct choices, if the blocker is genuinely 'pick one of these'.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
            },
            "recommended_option": {
                "type": "string",
                "description": "Optional: id of the option you'd recommend, if any.",
            },
        },
        "required": ["question"],
    },
}


def make_request_clarification_handler(
    agent_name: str, task_id: str = ""
) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for request_clarification, scoped to the
    calling agent's own name and task so the recorded row is correctly
    attributed and findable by a real human/upstream-agent review flow."""

    def _handler(inp: dict[str, Any]) -> str:
        question = str(inp.get("question", "")).strip()
        if not question:
            return "[ERROR] question is required."
        context = str(inp.get("context", "")).strip()
        options = inp.get("options") or None
        recommended_option = inp.get("recommended_option") or None

        from app.fleet.approval_gate import request_human_input

        try:
            request_human_input(
                kind="clarification",
                details={
                    "question": question,
                    "context": context,
                    "options": options,
                    "recommended_option": recommended_option,
                },
                agent_name=agent_name,
                thread_id=f"clarify-{task_id or 'notask'}-{agent_name}",
                task_id=int(task_id) if str(task_id).isdigit() else None,
                blocking=False,
                description=f"{agent_name} requested clarification: {question[:200]}",
            )
        except Exception as exc:
            return f"[ERROR] failed to record clarification request: {exc}"
        return "Clarification request recorded. Ending this run to await an answer."

    return _handler


CODER_TOOLS = READ_ONLY_TOOLS + [
    # moved to app/tools/filesystem/edit_file.py as EDIT_FILE_TOOL —
    # tool_enhance.md productionization pass, tool #13 (2026-08-17).
    _EDIT_FILE_TOOL,
    # moved to app/tools/filesystem/write_file.py as WRITE_FILE_TOOL —
    # tool_enhance.md productionization pass, tool #12 (2026-08-17).
    _WRITE_FILE_TOOL,
    # tool_enhance.md productionization pass, tool #84 (2026-08-24) —
    # moved to app/tools/git/diff.py as GIT_DIFF_TOOL. See that
    # module's docstring — `file` had no `--` separator in 3 of the 4
    # real implementations (not this agent's own — make_coder_handlers
    # was already safe), a silent arbitrary-file-write via git's own
    # --output=<path> flag, same class as tool #80's git_show.
    GIT_DIFF_TOOL,
    {
        "name": "bash",
        "description": "Run a shell command (allowlisted safe commands only). Use for running tests, typecheck, and lint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "submit_patch",
        "description": "Signal that implementation is complete. Call this ONLY after all tests pass.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files_changed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths that were created or modified",
                },
                "summary": {
                    "type": "string",
                    "description": "One-paragraph summary of what was implemented and verified",
                },
            },
            "required": ["files_changed", "summary"],
        },
    },
    RECORD_LEARNING_TOOL,
]

# QA Agent: read + bash (test/build only, no write)
_QA_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run test or build commands only. Allowed: pytest, mypy, ruff, tsc, npm test/build/lint. "
        "No write operations, no deploy commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Test/build command to run"},
        },
        "required": ["command"],
    },
}

_SUBMIT_QA_TOOL = {
    "name": "submit_qa_result",
    "description": "Submit the final QA result after all checks are complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["passed", "failed"]},
            "tests_run": {"type": "integer"},
            "tests_passed": {"type": "integer"},
            "tests_failed": {"type": "integer"},
            "typecheck_clean": {"type": "boolean"},
            "lint_clean": {"type": "boolean"},
            "errors": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": [
            "status",
            "tests_run",
            "tests_passed",
            "tests_failed",
            "typecheck_clean",
            "lint_clean",
            "errors",
            "summary",
        ],
    },
}

# QA has read tools + bash (test only) + submit_qa_result. NO write_file, NO edit.
QA_TOOLS = READ_ONLY_TOOLS + [_QA_BASH_TOOL, _SUBMIT_QA_TOOL, RECORD_LEARNING_TOOL]

_SUBMIT_REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the structured code review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["blocking", "non-blocking", "suggestion"],
                        },
                        "file": {"type": "string"},
                        "line": {"type": ["integer", "null"]},
                        "finding": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["severity", "file", "finding", "recommendation"],
                },
            },
            "verdict": {"type": "string", "enum": ["approved", "changes_required"]},
            "summary": {"type": "string"},
        },
        "required": ["findings", "verdict", "summary"],
    },
}

# Reviewer has read tools ONLY + submit_review. NO bash, NO write, NO edit.
REVIEWER_TOOLS = READ_ONLY_TOOLS + [_SUBMIT_REVIEW_TOOL, RECORD_LEARNING_TOOL]

_DEVOPS_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run read-only health-check commands only. Allowed prefixes come from config DEVOPS_BASH_ALLOWLIST. "
        "No write, no deploy, no remote push, no credential access."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Read-only health check command",
            },
        },
        "required": ["command"],
    },
}

_SUBMIT_HEALTH_REPORT_TOOL = {
    "name": "submit_health_report",
    "description": "Submit the structured system health report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "status": {"type": "string", "enum": ["ok", "warn", "fail"]},
                        "detail": {"type": "string"},
                    },
                    "required": ["name", "status", "detail"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["status", "checks", "summary"],
    },
}

# DevOps: read tools + allowlisted bash + submit_health_report. NO write_file.
DEVOPS_TOOLS = READ_ONLY_TOOLS + [
    _DEVOPS_BASH_TOOL,
    _SUBMIT_HEALTH_REPORT_TOOL,
    RECORD_LEARNING_TOOL,
]

# Allowed QA bash commands (prefix checks)
_QA_ALLOWED_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m mypy",
    "python -m ruff",
    "python3 -m pytest",
    "python3 -m mypy",
    "python3 -m ruff",
    "npx tsc",
    "npm test",
    "npm run",
    "cat ",
    "head ",
    "git diff",
    "git log",
    "git status",
)


# test_runner/load_test/dependency_audit/infra_dry_run bash tool specs +
# handlers moved to app/tools/execution/bash.py (tool_enhance.md
# productionization pass, tool #1, 2026-08-15) — imported at the top of
# this file for backward compatibility. See that module's own docstring
# for the full TOOL PATH MIGRATION REPORT.


# --- Tool handlers ---


def make_read_only_handlers(repo_path: str) -> dict[str, Any]:
    base = Path(repo_path)

    # tool_enhance.md productionization pass, tool #65 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation; this implementation already had it)
    # lives in the shared read_file_handler() itself; see that
    # function's own module docstring.
    def read_file(inp: dict[str, Any]) -> str:
        return read_file_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #68 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch could raise an
    # uncaught ValueError that leaked an absolute host file path via the
    # resulting error message) lives in the shared list_files_handler()
    # itself; see that function's own module docstring.
    def list_files(inp: dict[str, Any]) -> str:
        return list_files_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #69 (2026-08-22) — the
    # real fix (a flag-shaped `pattern` reaching grep's own argument
    # parser, on BOTH real implementations) lives in the shared
    # search_code_handler() itself; see that function's own module
    # docstring.
    def search_code(inp: dict[str, Any]) -> str:
        return search_code_handler(base, inp)

    # tool_enhance.md productionization pass, tool #73 (2026-08-22) — no
    # new vulnerability; the shared search_symbols_handler() itself
    # documents the full audit in its own module docstring.
    def search_symbols(inp: dict[str, Any]) -> str:
        return search_symbols_handler(base, inp)

    # tool_enhance.md productionization pass, tool #67 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation; this implementation already had it)
    # lives in the shared get_file_tree_handler() itself; see that
    # function's own module docstring.
    def get_file_tree(inp: dict[str, Any]) -> str:
        return get_file_tree_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #78 (2026-08-23) — the
    # real fix (an uncaught ValueError/TypeError on a non-numeric
    # `count`, on both real implementations) lives in the shared
    # git_log_handler() itself; see that function's own module
    # docstring.
    def git_log(inp: dict[str, Any]) -> str:
        return git_log_handler(base, inp)

    # tool_enhance.md productionization pass, tool #71 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation on any path in the batch) lives in
    # the shared read_files_handler() itself; see that function's own
    # module docstring.
    def read_files(inp: dict[str, Any]) -> str:
        return read_files_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #70 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation, and both implementations had an
    # uncaught PermissionError) lives in the shared file_exists_handler()
    # itself; see that function's own module docstring.
    def file_exists(inp: dict[str, Any]) -> str:
        return file_exists_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #72 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation, and both implementations had an
    # uncaught PermissionError) lives in the shared file_info_handler()
    # itself; see that function's own module docstring.
    def file_info(inp: dict[str, Any]) -> str:
        return file_info_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #74 (2026-08-22) — no
    # new vulnerability; the shared find_references_handler() itself
    # documents the full audit in its own module docstring.
    def find_references(inp: dict[str, Any]) -> str:
        return find_references_handler(base, inp)

    # tool_enhance.md productionization pass, tool #77 (2026-08-23) — the
    # real fix (this implementation itself had ZERO worktree-boundary
    # validation on `directory`, same class as tool #76's analyze_file)
    # lives in the shared find_todos_handler() itself; see that
    # function's own module docstring.
    def find_todos(inp: dict[str, Any]) -> str:
        return find_todos_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #75 (2026-08-22) — no
    # new vulnerability; the shared search_imports_handler() itself
    # documents the full audit in its own module docstring.
    def search_imports(inp: dict[str, Any]) -> str:
        return search_imports_handler(base, inp)

    # tool_enhance.md productionization pass, tool #79 (2026-08-23) — the
    # real fix (this implementation silently reported "(clean)" even
    # when `git status` genuinely failed) lives in the shared
    # git_status_handler() itself; see that function's own module
    # docstring.
    def git_status(inp: dict[str, Any]) -> str:
        return git_status_handler(base)

    # tool_enhance.md productionization pass, tool #80 (2026-08-23) — the
    # real fix (this implementation had ZERO validation of `ref`,
    # exploitable via git's own --output=<path> flag for a silent
    # arbitrary-file-write) lives in the shared git_show_handler()
    # itself; see that function's own module docstring.
    def git_show(inp: dict[str, Any]) -> str:
        return git_show_handler(base, inp)

    # tool_enhance.md productionization pass, tool #81 (2026-08-23) — the
    # real fix (this implementation had ZERO validation of `path`,
    # same flag-collision class as tool #80's git_show) lives in the
    # shared git_blame_handler() itself; see that function's own
    # module docstring.
    def git_blame(inp: dict[str, Any]) -> str:
        return git_blame_handler(base, inp)

    # tool_enhance.md productionization pass, tool #76 (2026-08-22) — the
    # real fix (this implementation itself had ZERO worktree-boundary
    # validation, an uncaught PermissionError, and chat_agent.py's
    # separate copy had a real functionality-parity gap) lives in the
    # shared analyze_file_handler() itself; see that function's own
    # module docstring.
    def analyze_file(inp: dict[str, Any]) -> str:
        return analyze_file_handler(base, repo_path, inp)

    return {
        "read_file": read_file,
        "read_files": read_files,
        "list_files": list_files,
        "search_code": search_code,
        "search_symbols": search_symbols,
        "get_file_tree": get_file_tree,
        "git_log": git_log,
        "file_exists": file_exists,
        "file_info": file_info,
        "find_references": find_references,
        "find_todos": find_todos,
        "search_imports": search_imports,
        "git_status": git_status,
        "git_show": git_show,
        "git_blame": git_blame,
        "analyze_file": analyze_file,
    }


def make_coder_handlers(
    worktree_path: str, repo_path: str, extra_env: dict[str, str] | None = None
) -> dict[str, Any]:
    """extra_env (Day 17 — Credential Vault): custom secrets merged into the
    bash tool's subprocess env — e.g. a third-party API key a task's code
    integrates with. Never database/deploy credentials — see
    docs/DAY17_PLAN.md. Values never appear in tool output or logs; only the
    subprocess itself sees them."""
    handlers = make_read_only_handlers(repo_path)
    wt = Path(worktree_path)
    patch_result: dict[str, Any] = {}

    def write_file(inp: dict[str, Any]) -> str:
        rel_path = inp["path"]
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        target = wt / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written: {rel_path}"

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        # Gap-closure (Audit 05 fix, SEC-05-005): the denylist alone doesn't
        # stop `cd /outside/the/worktree && <anything>` — cwd= below only
        # sets the *starting* directory. See check_command_stays_in_boundary's
        # own docstring for what this does and doesn't cover.
        boundary_policy = check_command_stays_in_boundary(cmd, worktree_path)
        if not boundary_policy.allowed:
            return f"[POLICY DENIED] {boundary_policy.reason}"
        timeout = get_settings().bash_tool_timeout_seconds.get("coder", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, worktree_path, timeout=timeout, extra_env=extra_env
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:4000]
        return out if out else "(no output)"

    def edit_file(inp: dict[str, Any]) -> str:
        rel_path = str(inp["path"])
        old_string = str(inp["old_string"])
        new_string = str(inp["new_string"])
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        target = wt / rel_path
        if not target.exists():
            return f"[ERROR] File not found: {rel_path}. Use write_file to create a new file."
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Cannot read {rel_path}: {e}"
        if old_string not in content:
            return f"[ERROR] old_string not found in {rel_path}. The exact text was not present."
        count = content.count(old_string)
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel_path}. Provide more context to make it unique."
        target.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Edited {rel_path}"

    # tool_enhance.md productionization pass, tool #84 (2026-08-24) — this
    # implementation was already safe (already used a `--` separator);
    # unified onto the shared git_diff_handler() anyway for the more
    # complete staged+unstaged output; see that function's own module
    # docstring.
    def git_diff(inp: dict[str, Any]) -> str:
        return git_diff_handler(wt, inp)

    def submit_patch(inp: dict[str, Any]) -> str:
        patch_result["files_changed"] = inp.get("files_changed", [])
        patch_result["summary"] = inp.get("summary", "")
        return "Patch submitted"

    handlers["edit_file"] = edit_file
    handlers["git_diff"] = git_diff
    handlers["write_file"] = write_file
    handlers["bash"] = bash
    handlers["submit_patch"] = submit_patch
    handlers["_patch_result"] = patch_result  # caller reads this after run
    return handlers


def make_qa_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    """QA agent: read-only + bash (test/build only) + submit_qa_result. No writes."""
    handlers = make_read_only_handlers(repo_path)
    qa_result: dict[str, Any] = {}

    # Prepend venv bin dir so `python`, `pytest`, `mypy`, `ruff` resolve correctly.
    _venv_bin = str(Path(sys.executable).parent)
    _env_with_venv = os.environ.copy()
    _env_with_venv["PATH"] = _venv_bin + ":" + _env_with_venv.get("PATH", "")

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _QA_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("qa", 120)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            worktree_path,
            timeout=timeout,
            extra_env=None if settings.bash_sandbox_enabled else _env_with_venv,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("qa"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:6000]
        return out if out else "(no output)"

    def submit_qa_result(inp: dict[str, Any]) -> str:
        qa_result.update(inp)
        return "QA result submitted"

    handlers["bash"] = bash
    handlers["submit_qa_result"] = submit_qa_result
    handlers["_qa_result"] = qa_result  # caller reads this after run
    return handlers


def make_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Reviewer agent: read-only only + submit_review. No bash, no writes."""
    handlers = make_read_only_handlers(repo_path)
    review_result: dict[str, Any] = {}

    def submit_review(inp: dict[str, Any]) -> str:
        review_result.update(inp)
        return "Review submitted"

    handlers["submit_review"] = submit_review
    handlers["_review_result"] = review_result  # caller reads this after run
    return handlers


def make_devops_handlers(repo_path: str) -> dict[str, Any]:
    """DevOps agent: read-only + allowlisted bash (health checks only) + submit_health_report. No write."""
    from app.config import get_settings

    handlers = make_read_only_handlers(repo_path)
    health_result: dict[str, Any] = {}

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        settings = get_settings()
        devops_prefixes = settings.devops_bash_allowlist_tuple
        policy = check_allowlisted_command(cmd, devops_prefixes)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        timeout = settings.bash_tool_timeout_seconds.get("devops", 30)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("devops"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:4000]
        return out if out else "(no output)"

    def submit_health_report(inp: dict[str, Any]) -> str:
        health_result.update(inp)
        return "Health report submitted"

    handlers["bash"] = bash
    handlers["submit_health_report"] = submit_health_report
    handlers["_health_result"] = health_result  # caller reads this after run
    return handlers


# ---- Phase 6 — Research Agent tools ----

# tool_enhance.md productionization pass, tool #88 (2026-08-24) — moved
# to app/tools/integrations/web_search.py as WEB_SEARCH_TOOL (imported
# above, aliased to _WEB_SEARCH_TOOL after the import block). No
# vulnerability found — see that module's docstring.

_SUBMIT_RESEARCH_TOOL = {
    "name": "submit_research",
    "description": "Submit the final research report with findings, library recommendations, approach, and risks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key findings from the research",
            },
            "relevantLibraries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "rationale"],
                },
            },
            "recommendedApproach": {"type": "string"},
            "risks": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["findings", "relevantLibraries", "recommendedApproach", "risks"],
    },
}

# Research agent: minimal read tools + submit_research only (no AST tools, no web_search placeholder).
# Kept small to stay within free-tier TPM limits — the agent can read files and search code.
# MASTER_AGENT_v2.md Phase 4 Item 1 gap-closure (2026-07-30) — research.py's own role file explicitly
# says "read the codebase, explore existing patterns" (general code exploration), but it was missing 2
# of the 3 tools Phase 4's own checklist names for "read broadly": get_file_tree and find_references.
# Both handlers already existed (make_research_handlers -> make_read_only_handlers wires every
# READ_ONLY_TOOLS handler regardless of schema exposure — same dead-contract shape Step 2 already fixed
# elsewhere), so this is a 2-line schema addition, not new capability — kept minimal, not the full
# READ_ONLY_TOOLS bundle, to respect the original TPM-budget intent above.
RESEARCH_TOOLS = [
    READ_ONLY_TOOLS[0],
    READ_ONLY_TOOLS[1],
    READ_ONLY_TOOLS[2],
    READ_ONLY_TOOLS[4],  # get_file_tree
    READ_ONLY_TOOLS[9],  # find_references
    _WEB_SEARCH_TOOL,
    _SUBMIT_RESEARCH_TOOL,
    RECORD_LEARNING_TOOL,
]


def make_research_handlers(repo_path: str) -> dict[str, Any]:
    """Research agent: read-only + web_search placeholder + submit_research. No write, no bash."""
    handlers = make_read_only_handlers(repo_path)
    research_result: dict[str, Any] = {}

    def submit_research(inp: dict[str, Any]) -> str:
        research_result.update(inp)
        return "Research report submitted"

    # tool_enhance.md productionization pass, tool #88 (2026-08-24) — the
    # real logic now lives in web_search_handler(); see that
    # function's own module docstring.
    handlers["web_search"] = web_search_handler
    handlers["submit_research"] = submit_research
    handlers["_research_result"] = research_result  # caller reads this after run
    return handlers


# ---- Phase 6 — Docs Agent tools ----

# tool_enhance.md productionization pass, tool #85 (2026-08-24) — moved
# to app/tools/agents/submit_docs.py as SUBMIT_DOCS_TOOL (imported
# above as _SUBMIT_DOCS_TOOL). See that module's docstring — no
# security vulnerability, no functional bug; all four real
# implementations were already-correct, functionally identical
# in-memory sinks, now unified for maintainability.


# ---------------------------------------------------------------------------
# Gap-closure Day 53 (Stage 2, answers.md Q41: "Architecture docs"/"Agent
# docs"/"Tool docs"/"Migration guides" all NOT FOUND — no generator at all).
# Repo research (repos/aider/aider/repomap.py): aider builds its repo map
# from real tree-sitter-parsed symbols, never from guessing — the same
# "introspect the real thing, don't ask the LLM to guess" principle applies
# here: each of these 3 tools returns real, directly-introspected data
# (the actual capability_registry, the actual tool specs in this very
# module, the actual Alembic migration files' real revision/down_revision
# via AST parsing) for the LLM to write UP, not to invent from scratch.
# ---------------------------------------------------------------------------

_LIST_REGISTERED_AGENTS_TOOL = {
    "name": "list_registered_agents",
    "description": "Real introspection of every registered agent's capability contract (name, description, tools, capabilities, risk_level, dependencies) from the actual fleet capability_registry — not a guess from file names.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_LIST_TOOL_SPECS_TOOL = {
    "name": "list_all_tool_specs",
    "description": "Real introspection of every distinct tool schema defined in this codebase (name + description), deduplicated by name — not a guess from grepping.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_LIST_MIGRATIONS_TOOL = {
    "name": "list_migrations",
    "description": "Real introspection of every Alembic migration file under backend/migrations/versions/ — file name, revision id, down_revision, and the file's own module docstring, extracted via AST parsing (the file is never executed) — not a guess from file names alone.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def list_registered_agents(inp: dict[str, Any]) -> str:
    import json as _json

    from app.fleet.capability_registry import (
        ensure_all_agents_registered,
        get_capability_registry,
    )

    ensure_all_agents_registered()
    entries = get_capability_registry().all()
    data = [
        {
            "name": e.name,
            "description": e.description,
            "tools": e.tools,
            "input_types": e.input_types,
            "output_types": e.output_types,
            "capabilities": e.capabilities,
            "risk_level": e.risk_level,
            "dependencies": e.dependencies,
        }
        for e in sorted(entries, key=lambda e: e.name)
    ]
    return _json.dumps(data, indent=2)


def list_all_tool_specs(inp: dict[str, Any]) -> str:
    import json as _json
    import sys

    module = sys.modules[__name__]
    seen: dict[str, str] = {}
    for attr_name in dir(module):
        val = getattr(module, attr_name)
        if isinstance(val, dict) and "name" in val and "input_schema" in val:
            seen[str(val["name"])] = str(val.get("description", ""))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "name" in item and "input_schema" in item:
                    seen[str(item["name"])] = str(item.get("description", ""))
    data = [{"name": n, "description": d} for n, d in sorted(seen.items())]
    return _json.dumps(data, indent=2)


def list_migrations(inp: dict[str, Any]) -> str:
    import ast as _ast_mod
    import json as _json

    versions_dir = (
        Path(__file__).resolve().parent.parent.parent / "migrations" / "versions"
    )
    if not versions_dir.exists():
        return "[]"
    results: list[dict[str, Any]] = []
    for path in sorted(versions_dir.glob("*.py")):
        try:
            tree = _ast_mod.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        docstring = _ast_mod.get_docstring(tree) or ""
        revision: Any = None
        down_revision: Any = None
        for node in tree.body:
            # Alembic's generated files use annotated assignments
            # (`revision: str = "001"`), not plain `Assign` — handle both.
            targets: list[_ast_mod.expr] = []
            value: _ast_mod.expr | None = None
            if isinstance(node, _ast_mod.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, _ast_mod.AnnAssign) and node.value is not None:
                targets = [node.target]
                value = node.value
            for target in targets:
                if not isinstance(target, _ast_mod.Name) or not isinstance(
                    value, _ast_mod.Constant
                ):
                    continue
                if target.id == "revision":
                    revision = value.value
                if target.id == "down_revision":
                    down_revision = value.value
        results.append(
            {
                "file": path.name,
                "revision": revision,
                "down_revision": down_revision,
                "docstring": docstring.strip()[:300],
            }
        )
    return _json.dumps(results, indent=2)


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §19 "Generate deployment guides for THIS project: NO — no
# deployment_guide_agent.py or equivalent exists". list_deploy_artifacts is
# the real grounding-data tool deployment_guide_doc_agent uses instead of
# guessing which deploy files exist: a real filesystem check against
# repo_path's own actual deployment files (Dockerfiles, compose files, CI
# workflows, systemd units, k8s/terraform if present) — never invented, and
# never a full recursive tree walk (would hit node_modules/.venv/repos/).
# Bound to repo_path via a closure factory, matching this file's own
# established convention (_make_write_file_handler(root) above) rather than
# module-level like list_migrations, because unlike Alembic migrations
# (always this app's own backend/migrations/), deploy artifacts live in
# whichever repo_path the calling agent is scoped to.
# ---------------------------------------------------------------------------

_LIST_DEPLOY_ARTIFACTS_TOOL = {
    "name": "list_deploy_artifacts",
    "description": "Real filesystem discovery of this project's actual deployment-relevant files: Dockerfiles, docker-compose files, Procfile, .github/workflows/*.yml, scripts/systemd/*.service|.timer, and k8s/terraform manifests if present. Read each with read_file before writing a deployment guide — never invent a deploy mechanism this project doesn't actually have.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_DEPLOY_ARTIFACT_GLOBS: tuple[str, ...] = (
    "Dockerfile",
    "*/Dockerfile",
    "*/*/Dockerfile",
    "Dockerfile.*",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "Procfile",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "scripts/systemd/*.service",
    "scripts/systemd/*.timer",
    "k8s/*.yaml",
    "k8s/*.yml",
    "kubernetes/*.yaml",
    "kubernetes/*.yml",
    "terraform/*.tf",
    "Vagrantfile",
)


def make_list_deploy_artifacts_handler(
    repo_path: str,
) -> Callable[[dict[str, Any]], str]:
    root = Path(repo_path)

    def list_deploy_artifacts(inp: dict[str, Any]) -> str:
        import json as _json

        found: list[str] = []
        seen: set[str] = set()
        for pattern in _DEPLOY_ARTIFACT_GLOBS:
            for p in sorted(root.glob(pattern)):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(root))
                if rel not in seen:
                    seen.add(rel)
                    found.append(rel)
        return _json.dumps({"deploy_artifacts": found}, indent=2)

    return list_deploy_artifacts


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §20 "Inspect external GitHub repos: NO — all GitHub tooling
# operates on the local repo's own remote via `gh` CLI, not arbitrary
# external repos". inspect_github_repo is the real gap-fill: real,
# read-only GitHub REST data (via `gh api`, GET only — never a write
# endpoint) for any owner/repo, not just this project's own remote. No
# repo_path needed, so this is a standalone function like list_migrations
# above, not a repo_path-bound closure.
# ---------------------------------------------------------------------------

_INSPECT_GITHUB_REPO_TOOL = {
    "name": "inspect_github_repo",
    "description": "Real, read-only inspection of an arbitrary external GitHub repository via the GitHub REST API (never a write endpoint) — distinct from create_pr/github_* tools, which only operate on this project's own remote. action='info' returns real repo metadata (description, language, stars, default branch, topics); 'list_files' lists real directory contents at path; 'read_file' returns a real file's decoded content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner/org"},
            "repo": {"type": "string", "description": "Repository name"},
            "action": {
                "type": "string",
                "enum": ["info", "list_files", "read_file"],
                "description": "What to inspect (default: info)",
            },
            "path": {
                "type": "string",
                "description": "Path within the repo (for list_files/read_file; default: repo root)",
            },
        },
        "required": ["owner", "repo"],
    },
}


def inspect_github_repo(inp: dict[str, Any]) -> str:
    import json as _json
    import re as _re

    owner = str(inp.get("owner", "")).strip()
    repo_name = str(inp.get("repo", "")).strip()
    action = str(inp.get("action", "info")).strip()
    path = str(inp.get("path", "")).strip()
    ident_re = _re.compile(r"^[A-Za-z0-9._-]+$")
    if not owner or not repo_name:
        return "[ERROR] owner and repo are required"
    if not ident_re.match(owner) or not ident_re.match(repo_name):
        return "[ERROR] owner/repo must be simple GitHub identifiers (letters, digits, '.', '_', '-')"

    if action == "info":
        endpoint = f"repos/{owner}/{repo_name}"
    elif action in ("list_files", "read_file"):
        clean_path = path.lstrip("/")
        if ".." in clean_path.split("/"):
            return "[ERROR] path may not contain '..'"
        endpoint = f"repos/{owner}/{repo_name}/contents/{clean_path}"
    else:
        return (
            f"[ERROR] Unknown action: {action!r}. Use info, list_files, or read_file."
        )

    try:
        r = subprocess.run(
            ["gh", "api", endpoint], capture_output=True, text=True, timeout=20
        )
    except FileNotFoundError:
        return "[ERROR] gh CLI not found — install with: sudo apt install gh"
    except subprocess.TimeoutExpired:
        return "[ERROR] GitHub API request timed out"
    except Exception as e:
        return f"[ERROR] {e}"
    if r.returncode != 0:
        return f"[ERROR] gh api {endpoint} failed: {(r.stderr or r.stdout)[:500]}"

    try:
        data = _json.loads(r.stdout)
    except _json.JSONDecodeError:
        return r.stdout[:5000]

    if action == "info":
        summary = {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "default_branch": data.get("default_branch"),
            "language": data.get("language"),
            "stargazers_count": data.get("stargazers_count"),
            "open_issues_count": data.get("open_issues_count"),
            "topics": data.get("topics"),
            "license": (data.get("license") or {}).get("name"),
            "homepage": data.get("homepage"),
            "archived": data.get("archived"),
        }
        return _json.dumps(summary, indent=2)
    if action == "list_files":
        if isinstance(data, list):
            files = [
                {"name": e.get("name"), "type": e.get("type"), "path": e.get("path")}
                for e in data
            ]
            return _json.dumps(files, indent=2)
        return _json.dumps(data, indent=2)
    # action == "read_file"
    if (
        isinstance(data, dict)
        and data.get("encoding") == "base64"
        and data.get("content")
    ):
        import base64 as _b64

        try:
            content = _b64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception as e:
            return f"[ERROR] Could not decode file content: {e}"
        return content[:20000]
    return "[ERROR] Path is not a readable file (it may be a directory)"


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §20 "Inspect APIs (OpenAPI/Swagger): NO — zero references".
# Real JSON/YAML structural parsing of an OpenAPI/Swagger document (never
# regex/text scraping) — either fetched from a URL (reusing fetch_url's own
# SSRF guard) or supplied directly as spec_text (e.g. already read from a
# local file via read_file, keeping this standalone rather than repo_path-
# bound). Lists real endpoints/methods/schemas from the parsed structure.
# ---------------------------------------------------------------------------

_INSPECT_OPENAPI_SPEC_TOOL = {
    "name": "inspect_openapi_spec",
    "description": "Parse a real OpenAPI/Swagger spec (JSON or YAML) and summarize its endpoints (method, path, summary, operationId, parameters) and schema names — real structural parsing, never text/regex scraping. Provide url to fetch a published spec (SSRF-guarded), or spec_text with content already read (e.g. via read_file for a local spec file).",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL of a published OpenAPI/Swagger spec to fetch",
            },
            "spec_text": {
                "type": "string",
                "description": "Raw JSON or YAML spec content (alternative to url)",
            },
        },
        "required": [],
    },
}


def inspect_openapi_spec(inp: dict[str, Any]) -> str:
    import json as _json

    url = str(inp.get("url", "")).strip()
    spec_text = str(inp.get("spec_text", "")).strip()
    if not url and not spec_text:
        return (
            "[ERROR] Provide either url (to fetch a published spec) or "
            "spec_text (raw JSON/YAML content, e.g. already read via read_file)"
        )
    if url:
        ssrf_reason = _ssrf_denial_reason(url)
        if ssrf_reason:
            return f"[POLICY DENIED] {ssrf_reason}"
        try:
            r = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-L",
                    "--max-time",
                    "15",
                    "--user-agent",
                    "Gridiron-Agent/1.0",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            spec_text = r.stdout
        except Exception as e:
            return f"[ERROR] {e}"
        if not spec_text:
            return "[ERROR] Empty response fetching spec"

    spec: Any = None
    try:
        spec = _json.loads(spec_text)
    except _json.JSONDecodeError:
        try:
            import yaml as _yaml

            spec = _yaml.safe_load(spec_text)
        except Exception as e:
            return f"[ERROR] Could not parse as JSON or YAML: {e}"
    if not isinstance(spec, dict):
        return "[ERROR] Parsed content is not a valid OpenAPI/Swagger object"

    version = spec.get("openapi") or spec.get("swagger")
    if not version:
        return (
            "[ERROR] No 'openapi' or 'swagger' version field found — not a "
            "recognized OpenAPI/Swagger spec"
        )
    info = spec.get("info") or {}
    paths = spec.get("paths") or {}
    _http_methods = ("get", "post", "put", "patch", "delete", "options", "head")
    endpoints: list[dict[str, Any]] = []
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in _http_methods or not isinstance(op, dict):
                continue
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": op.get("summary", ""),
                    "operationId": op.get("operationId", ""),
                    "parameters": [
                        p.get("name")
                        for p in (op.get("parameters") or [])
                        if isinstance(p, dict)
                    ],
                }
            )
    if str(version).startswith("3"):
        schemas = list(((spec.get("components") or {}).get("schemas") or {}).keys())
    else:
        schemas = list((spec.get("definitions") or {}).keys())
    result = {
        "openapi_version": version,
        "title": info.get("title", ""),
        "api_version": info.get("version", ""),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints[:100],
        "schemas": schemas[:100],
    }
    return _json.dumps(result, indent=2)


def make_doc_generator_handlers(repo_path: str) -> dict[str, Any]:
    """Shared base for the 4 gap-closure Day 53 doc-generator agents
    (architecture_doc_agent, agent_roster_doc_agent, tool_catalog_doc_agent,
    migration_guide_doc_agent) — read-only + write_file (*.md / docs/** only,
    mirroring readme_agent's own established write scoping) + submit_docs.
    Each agent adds its own specific real-introspection tool on top of this
    shared base."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    def dg_write_file(inp: dict[str, Any]) -> str:
        from app.policy.engine import check_path_in_worktree

        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] Doc generator agents may only write .md files "
                f"or paths under docs/. Got: {rel!r}"
            )
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(inp["content"]), encoding="utf-8")
        return f"Written {rel}"

    handlers["write_file"] = dg_write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


def make_docs_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    """Docs agent: read-only + write_file (scoped to *.md and docs/**) + submit_docs."""
    from app.policy.engine import check_path_in_worktree

    handlers = make_read_only_handlers(repo_path)
    wt = Path(worktree_path)
    docs_result: dict[str, Any] = {}

    def write_file(inp: dict[str, Any]) -> str:
        rel_path = str(inp["path"])
        # Docs agent: only .md files or docs/** allowed
        is_md = rel_path.endswith(".md")
        is_docs = rel_path.startswith("docs/")
        if not (is_md or is_docs):
            return (
                f"[POLICY DENIED] Docs agent may only write .md files or paths under docs/. "
                f"Got: {rel_path!r}"
            )
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            target = wt / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(inp["content"], encoding="utf-8")
            return f"Written: {rel_path}"
        except Exception as e:
            return f"[ERROR] Cannot write {rel_path}: {e}"

    handlers["write_file"] = write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


# Docs agent tool list: read tools + write_file + submit_docs. NO bash.
DOCS_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "write_file",
        "description": "Write content to a markdown file (*.md) or a path under docs/ only. No other file types.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the worktree root (must be *.md or docs/**)",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    _SUBMIT_DOCS_TOOL,
    RECORD_LEARNING_TOOL,
]

# ---------------------------------------------------------------------------
# CHAT AGENT TOOLS — full unrestricted access (dangerous cmds need confirmation)
# ---------------------------------------------------------------------------

# moved to app/tools/filesystem/delete_file.py as DELETE_FILE_TOOL —
# tool_enhance.md productionization pass, tool #17 (2026-08-17).

# _GIT_PUSH_TOOL moved to app/tools/git/push.py as GIT_PUSH_TOOL —
# tool_enhance.md productionization pass, tool #4 (2026-08-16).

# moved to app/tools/git/create_branch.py as CREATE_BRANCH_TOOL —
# tool_enhance.md productionization pass, tool #32 (2026-08-18).

_CHAT_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run any shell command in the repository. "
        "Dangerous commands (rm -rf, git push, docker push, kubectl delete, etc.) "
        "will be paused for user confirmation before executing. "
        "Use this for running tests, installs, builds, or any investigation command."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "cwd": {
                "type": "string",
                "description": "Working directory override (default: repo root)",
            },
        },
        "required": ["command"],
    },
}

_SUBMIT_RESULT_TOOL = {
    "name": "submit_result",
    "description": "Signal that the task is fully complete. Include a summary of what was done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What was accomplished, files changed, commands run",
            },
            "status": {
                "type": "string",
                "enum": ["done", "blocked"],
                "description": "done = complete, blocked = hit a wall and need help",
            },
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths of files created or modified",
            },
        },
        "required": ["summary", "status"],
    },
}

# moved to app/tools/filesystem/append_file.py as APPEND_FILE_TOOL —
# tool_enhance.md productionization pass, tool #26 (2026-08-18).

# moved to app/tools/filesystem/rename_file.py as RENAME_FILE_TOOL — tool_enhance.md productionization pass, tool #56 (2026-08-20).

_COPY_FILE_TOOL = {
    "name": "copy_file",
    "description": "Copy a file to a new location within the repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_path": {
                "type": "string",
                "description": "Source file path relative to repo root",
            },
            "to_path": {
                "type": "string",
                "description": "Destination file path relative to repo root",
            },
        },
        "required": ["from_path", "to_path"],
    },
}

# moved to app/tools/git/commit.py as GIT_COMMIT_TOOL — tool_enhance.md productionization pass, tool #37 (2026-08-18).

_GIT_BRANCH_TOOL = {
    "name": "git_branch",
    "description": "List all branches, or create a new branch. To switch branches use git_checkout.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete"],
                "description": "Action to perform (default: list)",
            },
            "name": {
                "type": "string",
                "description": "Branch name (required for create/delete)",
            },
        },
        "required": [],
    },
}

# moved to app/tools/git/checkout.py as GIT_CHECKOUT_TOOL —
# tool_enhance.md productionization pass, tool #35 (2026-08-18).

# moved to app/tools/git/stash.py as GIT_STASH_TOOL — tool_enhance.md productionization pass, tool #42 (2026-08-19).

# moved to app/tools/git/pull.py as GIT_PULL_TOOL — tool_enhance.md productionization pass, tool #39 (2026-08-18).

_GIT_FETCH_TOOL = {
    "name": "git_fetch",
    "description": "Fetch latest refs from remote without merging. Safe read-only remote operation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "prune": {
                "type": "boolean",
                "description": "Remove stale remote-tracking refs (default: false)",
            },
        },
        "required": [],
    },
}

# moved to app/tools/git/restore.py as GIT_RESTORE_TOOL — tool_enhance.md productionization pass, tool #41 (2026-08-19).

# moved to app/tools/execution/run_tests.py as RUN_TESTS_TOOL —
# tool_enhance.md productionization pass, tool #16 (2026-08-17).

_RUN_LINTER_TOOL = {
    "name": "run_linter",
    "description": "Run linting and type-checking tools. Returns errors and warnings. Fix these before declaring a task complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool": {
                "type": "string",
                "enum": ["ruff", "mypy", "tsc", "eslint", "black", "all"],
                "description": "Linter to run (default: all — runs ruff + mypy for Python, tsc for TypeScript)",
            },
            "path": {
                "type": "string",
                "description": "Path to lint (default: backend/ or apps/web/)",
            },
            "fix": {
                "type": "boolean",
                "description": "Auto-fix issues where possible (ruff only, default: false)",
            },
        },
        "required": [],
    },
}

# _BACKGROUND_PROCESSES used to be a module-level dict (shared across all sessions).
# It is now a per-session dict created inside make_chat_handlers() so that one session
# cannot kill or read output from another session's background process.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 1: File / Editing extras
# ---------------------------------------------------------------------------

_FIND_FILE_TOOL = {
    "name": "find_file",
    "description": "Find files by name or glob pattern across the repository. Faster than list_files when you know the filename.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Filename or pattern to find (e.g. 'config.py', '*.json', 'test_*.py')",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search (default: repo root)",
            },
        },
        "required": ["name"],
    },
}

_FORMAT_FILE_TOOL = {
    "name": "format_file",
    "description": "Auto-format a source file using the appropriate formatter (black/ruff for Python, prettier for TS/JS).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "formatter": {
                "type": "string",
                "enum": ["auto", "black", "ruff", "prettier"],
                "description": "Formatter to use (default: auto — detects by extension)",
            },
        },
        "required": ["path"],
    },
}

_ORGANIZE_IMPORTS_TOOL = {
    "name": "organize_imports",
    "description": "Sort and organize import statements in a Python file using ruff (isort-compatible). Also removes unused imports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Python file path relative to repo root",
            },
        },
        "required": ["path"],
    },
}

# moved to app/tools/filesystem/insert_at_line.py as INSERT_AT_LINE_TOOL — tool_enhance.md productionization pass, tool #47 (2026-08-19).

# moved to app/tools/filesystem/replace_function.py as
# REPLACE_FUNCTION_TOOL — tool_enhance.md productionization pass, tool
# #24 (2026-08-18).

# moved to app/tools/filesystem/delete_lines.py as DELETE_LINES_TOOL —
# tool_enhance.md productionization pass, tool #34 (2026-08-18).

# moved to app/tools/filesystem/apply_patch.py as APPLY_PATCH_TOOL —
# tool_enhance.md productionization pass, tool #27 (2026-08-18).

_COMPARE_FILES_TOOL = {
    "name": "compare_files",
    "description": "Show a unified diff between two files. Useful for comparing versions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path_a": {
                "type": "string",
                "description": "First file path relative to repo root",
            },
            "path_b": {
                "type": "string",
                "description": "Second file path relative to repo root",
            },
            "context": {
                "type": "integer",
                "description": "Lines of context around changes (default: 3)",
            },
        },
        "required": ["path_a", "path_b"],
    },
}

# AUDIT_Q_BATCH01 §18 "Synchronize files" — no dedicated cross-file
# synchronization tool previously existed (rename_symbol's multi-file
# rewrite is incidental to a rename, not a general sync primitive). "paths"
# (not "targets") deliberately matches _POLICY_PATH_FIELD_NAMES in
# base_graph.py so the shared single-interceptor _policy_check
# automatically path-checks every target here, the same as read_files'
# own "paths" field — no special-casing needed there.
#
# moved to app/tools/filesystem/sync_files.py as SYNC_FILES_TOOL /
# sync_files_handler — tool_enhance.md productionization pass, tool #64
# (2026-08-22). This implementation's own check_path_in_worktree() calls
# were already correct; the real, severe finding was that
# chat_agent.py's own interactive dispatch (a separate code path from
# base_graph.py's interceptor mentioned above) had ZERO such validation
# — see that new module's docstring for the live proof (a real
# combined exfiltration + arbitrary-write via source="/etc/hostname").
_SYNC_FILES_TOOL = SYNC_FILES_TOOL

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 2: Terminal extras
# ---------------------------------------------------------------------------

# moved to app/tools/execution/run_background.py as RUN_BACKGROUND_TOOL /
# validate_run_background_cwd — tool_enhance.md productionization pass,
# tool #58 (2026-08-20). See that module's docstring for the real
# sandboxing finding (fixed in app/fleet/process_manager.py) and the
# retroactive kill_process (tool #49) fix found along the way.
_RUN_BACKGROUND_TOOL_DEF = RUN_BACKGROUND_TOOL

_LIST_BACKGROUND_PROCESSES_TOOL = {
    "name": "list_background_processes",
    "description": "List background processes started in this session via run_background, with age and whether each is possibly hung (alive well past the expected runtime). Distinct from list_processes, which lists all OS processes.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

# AUDIT_Q_BATCH01 §58 "Concurrent command execution (fan-out)" — previously
# zero asyncio.gather/TaskGroup usage anywhere in backend/app; every
# bash-shaped tool ran exactly one command at a time even when a caller had
# several genuinely independent commands to run.
# _MAX_PARALLEL_COMMANDS / _RUN_PARALLEL_COMMANDS_TOOL moved to
# app/tools/execution/parallel.py as MAX_PARALLEL_COMMANDS /
# RUN_PARALLEL_COMMANDS_TOOL — tool_enhance.md productionization pass,
# tool #9 (2026-08-16).

# moved to app/tools/execution/kill_process.py as KILL_PROCESS_TOOL — tool_enhance.md productionization pass, tool #49 (2026-08-20).

# moved to app/tools/execution/python_snippet.py as RUN_PYTHON_SNIPPET_TOOL
# — tool_enhance.md productionization pass, tool #14 (2026-08-17).

# moved to app/tools/execution/run_make.py as RUN_MAKE_TOOL /
# run_make_handler — tool_enhance.md productionization pass, tool #59
# (2026-08-22). See that module's docstring for the real findings (a
# classic shell-injection bug in chat_agent.py's own dispatch, a second
# GNU-make-own-flag code-execution primitive affecting BOTH real
# implementations even with list-args, and a directory worktree-escape).
_RUN_MAKE_TOOL = RUN_MAKE_TOOL

# tool_enhance.md productionization pass, tool #86 (2026-08-24) — moved
# to app/tools/execution/fetch_url.py as FETCH_URL_TOOL (imported
# above as _FETCH_URL_TOOL). See that module's docstring — the
# unbounded-timeout finding flagged back in tool #14 is now closed;
# ae_fetch_url (ai_engineer) previously ignored this schema's own
# timeout/summarize fields entirely, now unified onto the same
# shared, fixed handler.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 3: Git extras
# ---------------------------------------------------------------------------

# moved to app/tools/git/merge.py as GIT_MERGE_TOOL — tool_enhance.md productionization pass, tool #38 (2026-08-18).

# ---------------------------------------------------------------------------
# Gap-closure Day 51 (Stage 2, answers.md Q40 "Merge conflict resolution/
# explanation": NOT FOUND — "git_merge exists but does nothing special on
# conflict — just returns raw stdout/stderr"). Repo research
# (repos/cline/apps/vscode/src/core/controller/worktree/mergeWorktree.ts):
# cline detects a failed merge and lists conflicted files via
# `git diff --name-only --diff-filter=U` rather than scraping stdout text —
# that detection technique is reused in git_merge below. cline stops there
# (aborts the merge and reports file names); actual conflict-marker parsing
# and a resolution-assist tool are this session's own original addition —
# no repo in repos/ implements real git-merge-conflict-marker parsing
# (aider's own `<<<<<<<`/`=======`/`>>>>>>>` hits are its unrelated
# SEARCH/REPLACE edit-block format, not git conflicts).
# ---------------------------------------------------------------------------


_PARSE_MERGE_CONFLICTS_TOOL = {
    "name": "parse_merge_conflicts",
    "description": "Parse a file's real <<<<<<</=======/>>>>>>> conflict markers into structured hunks (ours/theirs text, labels, line ranges) — read this before deciding how to resolve a conflicted file, never guess resolution from raw marker text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Conflicted file, relative to repo root",
            },
        },
        "required": ["path"],
    },
}

_EXPLAIN_MERGE_CONFLICT_TOOL = {
    "name": "explain_merge_conflict",
    "description": "Parse a file's real conflict markers (like parse_merge_conflicts) and generate a plain-English explanation of what 'ours' vs 'theirs' actually changed in each hunk and why they conflict. Does not resolve anything — read before deciding, or use standalone to understand a conflict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Conflicted file, relative to repo root",
            },
        },
        "required": ["path"],
    },
}

_RESOLVE_MERGE_CONFLICT_TOOL = {
    "name": "resolve_merge_conflict",
    "description": "Resolve specific conflict hunks in a file (by index, from parse_merge_conflicts) by keeping 'ours', 'theirs', or 'custom' merged content. Hunks not named in resolutions are left untouched and reported back as still unresolved.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Conflicted file, relative to repo root",
            },
            "resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Hunk index from parse_merge_conflicts",
                        },
                        "choice": {
                            "type": "string",
                            "enum": ["ours", "theirs", "custom"],
                        },
                        "custom_content": {
                            "type": "string",
                            "description": "Required when choice='custom' — the exact merged content for this hunk",
                        },
                    },
                    "required": ["index", "choice"],
                },
            },
        },
        "required": ["path", "resolutions"],
    },
}

# _GIT_RESET_TOOL moved to app/tools/git/reset.py as GIT_RESET_TOOL —
# tool_enhance.md productionization pass, tool #5 (2026-08-16).

# moved to app/tools/git/worktree.py as GIT_WORKTREE_TOOL — tool_enhance.md productionization pass, tool #43 (2026-08-19).

# _CREATE_PR_TOOL moved to app/tools/git/pull_request.py as CREATE_PR_TOOL
# (imported near the top of this file as _CREATE_PR_TOOL) —
# tool_enhance.md productionization pass, tool #2 (2026-08-15).

_GENERATE_COMMIT_MSG_TOOL = {
    "name": "generate_commit_msg",
    "description": "Generate a conventional commit message via LLM from the real staged diff, plus the raw diff summary it was grounded in. Falls back to just the raw diff summary if generation is unavailable.",
    "input_schema": {
        "type": "object",
        "properties": {
            "staged_only": {
                "type": "boolean",
                "description": "Use only staged changes (default: true)",
            },
        },
        "required": [],
    },
}

_REVIEW_DIFF_TOOL = {
    "name": "review_diff",
    "description": "LLM-generated structured review of a real git diff — summary, risk callouts, and notable omissions grounded strictly in the diff content. Distinct from git_diff, which returns only raw stdout.",
    "input_schema": {
        "type": "object",
        "properties": {
            "staged_only": {
                "type": "boolean",
                "description": "Review only staged changes (default: true)",
            },
            "base": {
                "type": "string",
                "description": "If set, review the diff against this ref/branch instead of staged/unstaged working-tree changes",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 4: Testing extras
# ---------------------------------------------------------------------------

# moved to app/tools/execution/run_single_test.py as
# RUN_SINGLE_TEST_TOOL / run_single_test_handler — tool_enhance.md
# productionization pass, tool #62 (2026-08-22). See that module's
# docstring: chat_agent.py's own dispatch had a real shell-injection bug
# (this implementation was already correctly shlex.quote()'d); the real
# finding shared by BOTH implementations was a `file` worktree-escape —
# pytest collection executes a Python file's module-level code at
# import time, proved live with a real outside-repo file's os.system()
# side effect genuinely running.
_RUN_SINGLE_TEST_TOOL = RUN_SINGLE_TEST_TOOL

_COVERAGE_REPORT_TOOL = {
    "name": "coverage_report",
    "description": "Run pytest with coverage and return a summary showing which lines are uncovered.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to run tests on (default: backend/tests/)",
            },
            "source": {
                "type": "string",
                "description": "Source directory to measure coverage for (default: backend/app/)",
            },
            "min_coverage": {
                "type": "integer",
                "description": "Fail if coverage is below this percentage (optional)",
            },
        },
        "required": [],
    },
}

_TYPE_CHECK_TOOL = {
    "name": "type_check",
    "description": "Run static type checking (mypy for Python, tsc for TypeScript). Returns type errors.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to check (default: backend/ for Python, apps/web/ for TS)",
            },
            "strict": {
                "type": "boolean",
                "description": "Use --strict mode for mypy (default: false)",
            },
            "language": {
                "type": "string",
                "enum": ["python", "typescript", "both"],
                "description": "Which language to check (default: both)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 5: Code Intelligence
# ---------------------------------------------------------------------------

# tool_enhance.md productionization pass, tool #82 (2026-08-24) — moved
# to app/tools/filesystem/list_functions.py as LIST_FUNCTIONS_TOOL
# (imported above as _LIST_FUNCTIONS_TOOL to preserve every existing
# reference). See that module's docstring — this was the widest
# consolidation in the low-risk tier so far: all NINE real
# implementations across 32 agents now delegate to one shared,
# corrected handler.

# tool_enhance.md productionization pass, tool #87 (2026-08-24) — moved
# to app/tools/filesystem/list_classes.py as LIST_CLASSES_TOOL
# (imported above). Sibling tool to tool #82's list_functions, same
# four finding classes proved independently: worktree escape + an
# uncaught PermissionError on the 2 single-file implementations, a
# field-name mismatch (`file` vs schema's `path`) in 3 agent-specific
# ones, a relative-traversal worktree escape in 2 more, and a
# single-file-vs-subtree design mismatch across all 5.
_LIST_CLASSES_TOOL = LIST_CLASSES_TOOL

_FIND_FUNCTION_BODY_TOOL = {
    "name": "find_function_body",
    "description": "Extract the complete source code of a named function or method, including its body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "function_name": {
                "type": "string",
                "description": "Name of the function or method to extract",
            },
        },
        "required": ["path", "function_name"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 6: Debug tools
# ---------------------------------------------------------------------------

_READ_LOGS_TOOL = {
    "name": "read_logs",
    "description": "Read log files from common locations. Specify path for a log file or service name for journalctl.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Log file path, or service name (e.g. 'uvicorn', 'postgresql')",
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to return (default: 50)",
            },
            "level": {
                "type": "string",
                "enum": ["all", "ERROR", "WARNING", "INFO"],
                "description": "Filter by log level (default: all)",
            },
        },
        "required": [],
    },
}

_ANALYZE_ERROR_TOOL = {
    "name": "analyze_error",
    "description": "Parse and analyze a Python traceback or error message. Returns structured breakdown with suggestions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "error": {
                "type": "string",
                "description": "Error message or full traceback to analyze",
            },
        },
        "required": ["error"],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 7: Database tools
# ---------------------------------------------------------------------------

# moved to app/tools/database/sql.py as RUN_SQL_TOOL —
# tool_enhance.md productionization pass, tool #15 (2026-08-17).

_INSPECT_SCHEMA_TOOL = {
    "name": "inspect_schema",
    "description": "Show the PostgreSQL database schema: tables, columns, types, and constraints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Specific table name to inspect (default: list all tables)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 8: Docker tools
# ---------------------------------------------------------------------------

_DOCKER_PS_TOOL = {
    "name": "docker_ps",
    "description": "List running Docker containers. Shows ID, image, status, and ports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "all": {
                "type": "boolean",
                "description": "Show all containers including stopped ones (default: false)",
            },
        },
        "required": [],
    },
}

_DOCKER_LOGS_TOOL = {
    "name": "docker_logs",
    "description": "Get recent logs from a Docker container by name or ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
            "lines": {
                "type": "integer",
                "description": "Number of recent log lines (default: 50)",
            },
        },
        "required": ["container"],
    },
}

# moved to app/tools/execution/docker_exec.py as DOCKER_EXEC_TOOL —
# tool_enhance.md productionization pass, tool #20 (2026-08-17).

# moved to app/tools/execution/docker_compose.py as DOCKER_COMPOSE_TOOL —
# tool_enhance.md productionization pass, tool #19 (2026-08-17).

_DIAGNOSE_DEPLOYMENT_FAILURE_TOOL = {
    "name": "diagnose_deployment_failure",
    "description": "Diagnose a real deployment/container failure: gathers real docker ps -a state, docker logs, and docker inspect (exit code, OOMKilled, restart count, error) for the given container — or just the overall container state if none is given — then adds an LLM root-cause diagnosis grounded strictly in that gathered evidence. Distinct from docker_logs, which only returns raw/pattern-flagged log text with no diagnosis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {
                "type": "string",
                "description": "Container name or ID to diagnose (omit to just diagnose overall docker ps -a state)",
            },
            "lines": {
                "type": "integer",
                "description": "Number of log lines to gather when container is given (default: 100)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 9: Security
# ---------------------------------------------------------------------------

_SECRETS_SCAN_TOOL = {
    "name": "secrets_scan",
    "description": "Scan the repository for hardcoded secrets, API keys, passwords, and tokens.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: entire repo)",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# DAY 1 TOOL SPECS — Batches 10-16
# ---------------------------------------------------------------------------

# Batch 10 — AST Engine
# tool_enhance.md productionization pass, tool #83 (2026-08-24) — moved
# to app/tools/filesystem/parse_ast.py as PARSE_AST_TOOL (imported
# above as _PARSE_AST_TOOL to preserve every existing reference). See
# that module's docstring — all SEVEN real implementations shared the
# identical worktree-escape + uncaught-PermissionError bug, now
# unified onto one shared parse_ast_handler().

_IMPORT_GRAPH_TOOL = {
    "name": "import_graph",
    "description": "Show every module imported by a Python file, and which symbols are imported from each.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the .py file (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}

_CALL_GRAPH_TOOL = {
    "name": "call_graph",
    "description": (
        "Show what functions each function calls inside a Python file. "
        "Optionally limit to a single function by name."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the .py file"},
            "function_name": {
                "type": "string",
                "description": "Name of function to inspect (empty = all functions)",
            },
        },
        "required": ["path"],
    },
}

_DEAD_CODE_DETECT_TOOL = {
    "name": "dead_code_detect",
    "description": (
        "Heuristically detect public Python functions defined in a directory that are never called "
        "anywhere in that directory. Results are indicative — external callers are not visible."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (relative to repo root, default: repo root)",
            },
        },
        "required": [],
    },
}

_CIRCULAR_DEP_DETECT_TOOL = {
    "name": "circular_dep_detect",
    "description": "Detect circular local import chains in a Python package directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: repo root)",
            },
        },
        "required": [],
    },
}

# moved to app/tools/refactor/rename_symbol.py as RENAME_SYMBOL_TOOL —
# tool_enhance.md productionization pass, tool #23 (2026-08-18).

# Batch 11 — Git extras
# moved to app/tools/git/rebase.py as GIT_REBASE_TOOL — tool_enhance.md productionization pass, tool #40 (2026-08-18).

# moved to app/tools/git/cherry_pick.py as GIT_CHERRY_PICK_TOOL —
# tool_enhance.md productionization pass, tool #36 (2026-08-18).

# Batch 12 — Terminal extras
_READ_OUTPUT_TOOL = {
    "name": "read_output",
    "description": "Read the latest stdout/stderr from a background process started with run_background.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "description": "Process ID returned by run_background",
            },
            "lines": {
                "type": "integer",
                "description": "Max lines to return (default: 50)",
            },
        },
        "required": ["pid"],
    },
}

# moved to app/tools/execution/run_node.py as RUN_NODE_TOOL /
# run_node_handler — tool_enhance.md productionization pass, tool #60
# (2026-08-22). See that module's docstring: `code` was already safely
# shlex.quote()'d on both real call sites; the real finding was an
# unbounded `timeout` on both, same class as run_python_snippet (#14).
_RUN_NODE_TOOL = RUN_NODE_TOOL

# moved to app/tools/execution/run_script.py as RUN_SCRIPT_TOOL /
# run_script_handler — tool_enhance.md productionization pass, tool #61
# (2026-08-22). See that module's docstring for the real findings: a
# classic shell-injection bug in chat_agent.py's own dispatch, a severe
# arbitrary-program-execution primitive via `interpreter` affecting BOTH
# real implementations even with list-args (proved live: interpreter=
# "rm" deleted a real file), and a `path` worktree-escape.
_RUN_SCRIPT_TOOL = RUN_SCRIPT_TOOL

# moved to app/tools/execution/docker_build.py as DOCKER_BUILD_TOOL —
# tool_enhance.md productionization pass, tool #18 (2026-08-17).

# moved to app/tools/execution/docker_restart.py as DOCKER_RESTART_TOOL
# — tool_enhance.md productionization pass, tool #21 (2026-08-17).

# Batch 13 — Smart search
# tool_enhance.md productionization pass, tool #90 (2026-08-24) — moved
# to app/tools/filesystem/find_route.py as FIND_ROUTE_TOOL (imported
# above as _FIND_ROUTE_TOOL). See that module's docstring — a severe
# field-name mismatch (schema declares `path_pattern`, 2 of 4 real
# implementations read a nonexistent `path` field and ignored `method`
# entirely) caused every real, schema-conformant call to those two to
# silently return the wrong (fixed-fallback) results.

# tool_enhance.md productionization pass, tool #89 (2026-08-24) — moved
# to app/tools/filesystem/find_api.py as FIND_API_TOOL (imported above
# as _FIND_API_TOOL). See that module's docstring — `name` was
# flag-injection vulnerable on all 4 real implementations, including
# chat_agent.py's dispatch (its shlex.quote() only protects against
# shell metacharacters, not grep's own argv-level flag parsing).

_FIND_SQL_TOOL = {
    "name": "find_sql",
    "description": "Find SQL queries and database operations in the codebase (SELECT, INSERT, SQLAlchemy text(), etc).",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "SQL keyword to search for, e.g. 'SELECT', 'INSERT', 'UPDATE' (empty = all SQL)",
            },
        },
        "required": [],
    },
}

_FIND_TEST_TOOL = {
    "name": "find_test",
    "description": "Find test functions that test a specific function or feature by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "function_name": {
                "type": "string",
                "description": "Name of the function or feature to find tests for",
            },
        },
        "required": ["function_name"],
    },
}

_FIND_CONFIG_TOOL = {
    "name": "find_config",
    "description": "Search for a configuration key across all config files (.env.example, config.py, settings files, YAML).",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Config key to find (e.g. 'DATABASE_URL', 'API_KEY', 'debug')",
            },
        },
        "required": ["key"],
    },
}

# Batch 14 — Monitoring
_CPU_USAGE_TOOL = {
    "name": "cpu_usage",
    "description": "Get current CPU usage percentage from /proc/stat or the `top` command.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_MEMORY_USAGE_TOOL = {
    "name": "memory_usage",
    "description": "Get current RAM usage from /proc/meminfo or the `free` command.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_DISK_USAGE_TOOL = {
    "name": "disk_usage",
    "description": "Get disk usage (total, used, free) for a path using shutil.disk_usage (stdlib).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to check (default: repo root)",
            },
        },
        "required": [],
    },
}

_HEALTH_CHECK_TOOL = {
    "name": "health_check",
    "description": "Check if backend services are up: backend HTTP health endpoint and database connectivity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service to check: 'all', 'backend', 'db' (default: all)",
            },
        },
        "required": [],
    },
}

_TASK_PROGRESS_TOOL = {
    "name": "task_progress",
    "description": "Query recent task status from the dev_tasks database table. Optionally filter by task ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "Specific task ID (optional; default: last 10 tasks)",
            },
            "limit": {
                "type": "integer",
                "description": "Max tasks to return (default: 10)",
            },
        },
        "required": [],
    },
}

# Batch 15 — Editing extras
# moved to app/tools/filesystem/replace_class.py as REPLACE_CLASS_TOOL — tool_enhance.md productionization pass, tool #57 (2026-08-20).

_UNDO_CHANGES_TOOL = {
    "name": "undo_changes",
    "description": (
        "Restore a file to its last committed state using `git checkout -- <path>`. "
        "This DISCARDS all uncommitted changes to that file. Requires confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to restore (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}

_GENERATE_PATCH_TOOL = {
    "name": "generate_patch",
    "description": (
        "Generate a unified diff patch from two text contents using Python's difflib. "
        "Useful for previewing changes before applying them. Does NOT modify any files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content_a": {
                "type": "string",
                "description": "Original file content (the 'before' version)",
            },
            "content_b": {
                "type": "string",
                "description": "New file content (the 'after' version)",
            },
            "filename": {
                "type": "string",
                "description": "Filename shown in the patch header (default: 'file')",
            },
        },
        "required": ["content_a", "content_b"],
    },
}

# Batch 16 — DB extras
_EXPLAIN_QUERY_TOOL = {
    "name": "explain_query",
    "description": (
        "Run EXPLAIN ANALYZE on a SQL query against the configured DATABASE_URL. "
        "Shows query plan and execution times. Read-only (EXPLAIN does not modify data)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to analyse (no trailing semicolon needed)",
            },
        },
        "required": ["query"],
    },
}

# _RUN_MIGRATION_TOOL moved to app/tools/database/migration.py as
# RUN_MIGRATION_TOOL — tool_enhance.md productionization pass, tool #8
# (2026-08-16).

# _SEED_DATABASE_TOOL moved to app/tools/database/seed.py as
# SEED_DATABASE_TOOL — tool_enhance.md productionization pass, tool #10
# (2026-08-16).


# ===========================================================================
# Day 2 Agents — shared tool spec constants, tool lists, handler factories
# ===========================================================================

# moved to app/tools/filesystem/edit_file.py as EDIT_FILE_TOOL —
# tool_enhance.md productionization pass, tool #13 (2026-08-17).
_EDIT_FILE_TOOL_SPEC = _EDIT_FILE_TOOL

# moved to app/tools/filesystem/write_file.py as WRITE_FILE_TOOL —
# tool_enhance.md productionization pass, tool #12 (2026-08-17).
_WRITE_FILE_TOOL_SPEC = _WRITE_FILE_TOOL

# tool_enhance.md productionization pass, tool #84 (2026-08-24) — moved
# to app/tools/git/diff.py as GIT_DIFF_TOOL (imported above as
# git_diff_handler; this alias preserves every existing reference to
# the old name across BUG_FIX_AGENT_TOOLS/REFACTOR_AGENT_TOOLS/
# CHAT_TOOLS).
_GIT_DIFF_TOOL_SPEC = GIT_DIFF_TOOL

# --- Day 2 submit tool specs ---

_SUBMIT_BUG_FIX_TOOL = {
    "name": "submit_bug_fix",
    "description": "Submit the bug fix: root cause analysis and files modified.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {"type": "string"},
            "fix_summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "tests_passed": {"type": "boolean"},
        },
        "required": ["root_cause", "fix_summary", "files_changed"],
    },
}

_SUBMIT_SECURITY_REPORT_TOOL = {
    "name": "submit_security_report",
    "description": "Submit security review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low", "none"],
            },
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["severity", "findings", "recommendations"],
    },
}

_SUBMIT_ARCH_REVIEW_TOOL = {
    # Gap-closure Day 48 (Stage 2) — real bug fix, not a new feature: this
    # schema previously used {verdict, issues, summary}, a field set that
    # matched NEITHER roles/architecture_reviewer.md's own documented
    # "Terminal tool contract" ({structure_summary, risks, recommendations,
    # blast_radius, import_graph_ran}) NOR what
    # app/agents/architecture_reviewer.py::run_arch_review() reads back
    # (raw.get("risks", []), raw.get("structure_summary", ...)) — meaning
    # every real architecture-review finding was silently discarded
    # (raw.get("risks", []) always returned [] since "risks" never existed
    # in the schema the LLM was told to fill out). Corrected to match the
    # role prompt and the consuming code exactly.
    "name": "submit_arch_review",
    "description": "Submit architecture review result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "structure_summary": {"type": "string"},
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                        },
                        "description": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "file:line — description entries from this run's real tool output",
                        },
                    },
                    "required": ["severity", "description", "evidence"],
                },
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "blast_radius": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
            "import_graph_ran": {
                "type": "boolean",
                "description": "Overridden by the real VerificationConfig graph-execution state, never trusted from the model's own claim — see run_arch_review()'s verification handling.",
            },
        },
        "required": [
            "structure_summary",
            "risks",
            "recommendations",
            "import_graph_ran",
        ],
    },
}

_SUBMIT_SQL_REPORT_TOOL = {
    "name": "submit_sql_report",
    "description": "Submit SQL agent output: query results or migration summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "result": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "result"],
    },
}

_SUBMIT_DOCKER_REPORT_TOOL = {
    "name": "submit_docker_report",
    "description": "Submit Docker agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "outcome": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "outcome"],
    },
}

_SUBMIT_CICD_REPORT_TOOL = {
    "name": "submit_cicd_report",
    "description": "Submit CI/CD agent analysis or workflow changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["analysis"],
    },
}

_SUBMIT_REFACTOR_REPORT_TOOL = {
    "name": "submit_refactor_report",
    "description": "Submit refactoring agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "breaking_changes": {"type": "boolean"},
        },
        "required": ["summary", "files_changed"],
    },
}

_SUBMIT_DEPENDENCY_REPORT_TOOL = {
    # Gap-closure Day 49 (Stage 2) — real bug fix, same class as Day 48's
    # submit_arch_review fix: this schema previously used
    # {outdated, upgraded, issues, files_changed}, matching NEITHER
    # roles/dependency_agent.md's own documented "Terminal tool contract"
    # ({dependencies: list[{name, current_version, latest_version,
    # vulnerability_ids, upgrade_recommended, breaking_changes}], summary,
    # manifest_read}) NOR run_dependency_agent()'s own consuming code
    # (raw.get("dependencies", []), raw.get("summary", ...)) — every real
    # dependency finding was silently discarded (raw.get("dependencies", [])
    # always returned [] since "dependencies" never existed in the schema).
    # Corrected to match the role prompt and the consuming code; kept
    # files_changed (present in code's own raw.get("files_changed", []) read,
    # not in the prompt's contract but genuinely needed — this agent has real
    # edit_file access per its own AGENT_CONTRACT side_effects).
    "name": "submit_dependency_report",
    "description": "Submit dependency upgrade analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "current_version": {"type": "string"},
                        "latest_version": {"type": "string"},
                        "vulnerability_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "upgrade_recommended": {"type": "boolean"},
                        "breaking_changes": {"type": "string"},
                        # AUDIT_Q_BATCH16 §92 gap-closure (2026-08-11) —
                        # "Abandoned/unmaintained libraries": check_last_release
                        # already existed as a real tool (distinguishes
                        # "outdated but active" from "no release in a long
                        # time") but was available-not-required — nothing in
                        # this schema captured its result as a structured
                        # claim, so the distinction it exists to make never
                        # reached the report. Optional (only known when
                        # check_last_release was actually called for this
                        # dependency) rather than required — a package with
                        # no version delta (already current) has no reason to
                        # spend a registry call checking staleness.
                        "abandoned": {
                            "type": "boolean",
                            "description": "True if check_last_release showed no release in a long time (not merely 'not the newest version') — only set when check_last_release was actually called for this package this run.",
                        },
                        "last_release_days_ago": {
                            "type": "integer",
                            "description": "Days since the latest published release, from this run's real check_last_release output.",
                        },
                    },
                    "required": [
                        "name",
                        "current_version",
                        "latest_version",
                        "upgrade_recommended",
                    ],
                },
            },
            "summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "manifest_read": {
                "type": "boolean",
                "description": "Overridden by the real VerificationConfig graph-execution state, never trusted from the model's own claim.",
            },
        },
        "required": ["dependencies", "summary", "manifest_read"],
    },
}

_SUBMIT_MONITORING_REPORT_TOOL = {
    "name": "submit_monitoring_report",
    "description": "Submit system monitoring report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy", "warning", "critical"]},
            "metrics": {"type": "object"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "metrics"],
    },
}

_CICD_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run shell command. CI/CD agent limited to: git log/diff/status/show, cat, grep, echo, ls.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_REFACTOR_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run shell command. Refactor agent limited to: python -m pytest, mypy, ruff, black, isort.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_DEPENDENCY_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run dependency commands: pip index versions, pip show/list, npm audit/outdated/list.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

# Stage 4 Tier 3 (2026-08-05, answer2.md Q92) — "abandoned" is a distinct
# signal from "outdated": `pip index versions`/`npm outdated` (the bash
# tool above) only compare the installed version against the latest
# available one, never expose *when* that latest version was actually
# published — a package whose latest release is 4 years old looks
# identical to an actively-maintained one if that's the only version ever
# installed. Real registry API calls (PyPI's/npm's own public JSON APIs,
# verified live against real packages before writing this), not a
# heuristic or the LLM's own training-time guess.
_CHECK_LAST_RELEASE_TOOL = {
    "name": "check_last_release",
    "description": "Check when a package's latest version was actually published (real PyPI/npm registry lookup) — distinguishes 'outdated but active' from 'abandoned' (no release in a long time), which pip/npm version-comparison alone cannot tell apart.",
    "input_schema": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name"},
            "ecosystem": {
                "type": "string",
                "enum": ["pypi", "npm"],
                "description": "Which registry to check (default: pypi)",
            },
        },
        "required": ["package"],
    },
}

# --- Day 2 Tool Lists ---

BUG_FIX_TOOLS = READ_ONLY_TOOLS + [
    _PARSE_AST_TOOL,
    _CALL_GRAPH_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    _ANALYZE_ERROR_TOOL,
    _READ_LOGS_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _SUBMIT_BUG_FIX_TOOL,
    RECORD_LEARNING_TOOL,
]

SECURITY_REVIEWER_TOOLS = READ_ONLY_TOOLS + [
    _SECRETS_SCAN_TOOL,
    _FIND_SQL_TOOL,
    _FIND_CONFIG_TOOL,
    _FIND_API_TOOL,
    _FIND_ROUTE_TOOL,
    _SUBMIT_SECURITY_REPORT_TOOL,
]

ARCH_REVIEWER_TOOLS = READ_ONLY_TOOLS + [
    _IMPORT_GRAPH_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _CALL_GRAPH_TOOL,
    _SUBMIT_ARCH_REVIEW_TOOL,
]

SQL_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _FIND_SQL_TOOL,
    _EXPLAIN_QUERY_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_SQL_REPORT_TOOL,
]

DOCKER_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _DOCKER_PS_TOOL,
    _DOCKER_LOGS_TOOL,
    _DOCKER_EXEC_TOOL,
    _DOCKER_COMPOSE_TOOL,
    _DOCKER_BUILD_TOOL,
    _DOCKER_RESTART_TOOL,
    _DIAGNOSE_DEPLOYMENT_FAILURE_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCKER_REPORT_TOOL,
]

CICD_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _CICD_BASH_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_CICD_REPORT_TOOL,
]

REFACTOR_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    _PARSE_AST_TOOL,
    _CALL_GRAPH_TOOL,
    _IMPORT_GRAPH_TOOL,
    _RENAME_SYMBOL_TOOL,
    _REPLACE_FUNCTION_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _REFACTOR_BASH_TOOL_SPEC,
    _SUBMIT_REFACTOR_REPORT_TOOL,
]

README_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

API_DOCS_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _FIND_ROUTE_TOOL,
    _FIND_API_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

DEPENDENCY_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _DEPENDENCY_BASH_TOOL_SPEC,
    _CHECK_LAST_RELEASE_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _SUBMIT_DEPENDENCY_REPORT_TOOL,
]

MONITORING_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _CPU_USAGE_TOOL,
    _MEMORY_USAGE_TOOL,
    _DISK_USAGE_TOOL,
    _HEALTH_CHECK_TOOL,
    _TASK_PROGRESS_TOOL,
    _READ_LOGS_TOOL,
    _SUBMIT_MONITORING_REPORT_TOOL,
]


# --- Day 2 shared sub-factories (reduce duplication) ---


def _make_edit_file_handler(root: Path) -> Any:
    # moved to app/tools/filesystem/edit_file.py as edit_file_handler —
    # tool_enhance.md productionization pass, tool #13 (2026-08-17).
    def edit_file_h(inp: dict[str, Any]) -> str:
        return edit_file_handler(root, str(root), inp)

    return edit_file_h


def _make_write_file_handler(root: Path) -> Any:
    # moved to app/tools/filesystem/write_file.py as write_file_handler —
    # tool_enhance.md productionization pass, tool #12 (2026-08-17).
    def write_file_h(inp: dict[str, Any]) -> str:
        return write_file_handler(root, str(root), inp)

    return write_file_h


# tool_enhance.md productionization pass, tool #84 (2026-08-24) — the
# real fix (ZERO `--` separator before `file` — a silent
# arbitrary-file-write via git's own --output=<path> flag, same class
# as tool #80's git_show) lives in the shared git_diff_handler()
# itself; see that function's own module docstring.
def _make_git_diff_handler(repo_path: str) -> Any:
    root = Path(repo_path)

    def git_diff_h(inp: dict[str, Any]) -> str:
        return git_diff_handler(root, inp)

    return git_diff_h


# --- Day 2 Handler Factories ---


def make_bug_fix_handlers(repo_path: str) -> dict[str, Any]:
    """Bug Fix agent: read-only + AST analysis + direct file writes + submit_bug_fix."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    bug_fix_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix (ZERO worktree-boundary validation + an uncaught
    # PermissionError, same class shared by all 7 real implementations)
    # lives in the shared parse_ast_handler() itself; see that
    # function's own module docstring.
    def bf_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    def bf_call_graph(inp: dict[str, Any]) -> str:
        return _ast.build_call_graph(
            str(root / inp["path"]), inp.get("function_name", "")
        )

    def bf_find_function_body(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        r = subprocess.run(
            ["grep", "-rn", f"def {name}", str(root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:4000] if r.stdout else f"(function '{name}' not found)"

    def bf_analyze_error(inp: dict[str, Any]) -> str:
        tb = str(inp.get("traceback", ""))
        lines = [
            ln
            for ln in tb.splitlines()
            if "File" in ln or "Error" in ln or "Exception" in ln
        ]
        return "\n".join(lines[:40]) or "(no error markers found)"

    def bf_read_logs(inp: dict[str, Any]) -> str:
        log_path = str(inp.get("path", "backend/logs/app.log"))
        n = int(inp.get("lines", 100))
        try:
            p = root / log_path
            if not p.exists():
                return f"[ERROR] Log not found: {log_path}"
            return "\n".join(
                p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def bf_submit(inp: dict[str, Any]) -> str:
        bug_fix_result.update(inp)
        return "Bug fix submitted"

    handlers["parse_ast"] = bf_parse_ast
    handlers["call_graph"] = bf_call_graph
    handlers["find_function_body"] = bf_find_function_body
    handlers["analyze_error"] = bf_analyze_error
    handlers["read_logs"] = bf_read_logs
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["git_diff"] = _make_git_diff_handler(repo_path)
    handlers["submit_bug_fix"] = bf_submit
    handlers["_bug_fix_result"] = bug_fix_result
    return handlers


def make_security_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Security reviewer: read-only + specialized search + submit_security_report. No writes."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    security_result: dict[str, Any] = {}

    def sec_secrets_scan(inp: dict[str, Any]) -> str:
        # AUDIT_Q_BATCH11 §96 "Secret scanning" — delegates to the same
        # canonical scanner secrets_scan() (below, make_coder_handlers) and
        # _scan_content_for_secrets (pre-commit) now share, instead of this
        # handler's own independently-maintained regex list.
        directory = str(inp.get("directory", ""))
        return _scan_directory_for_secrets(root, directory)

    def sec_find_sql(inp: dict[str, Any]) -> str:
        keyword = str(inp.get("keyword", ""))
        fp = str(inp.get("file_pattern", "*.py"))
        if keyword:
            r = subprocess.run(
                ["grep", "-rn", "-i", "-w", keyword, "--include", fp, str(root)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-i",
                    "-E",
                    "SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|DROP TABLE",
                    "--include",
                    fp,
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        return r.stdout[:6000] if r.stdout else "(no SQL found)"

    def sec_find_config(inp: dict[str, Any]) -> str:
        fp = str(inp.get("file_pattern", "*.py"))
        r = subprocess.run(
            [
                "grep",
                "-rn",
                "-i",
                "-E",
                r"(host|port|database|db_url|dsn|connection_string)\s*=",
                "--include",
                fp,
                str(root),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.stdout[:6000] if r.stdout else "(no config patterns found)"

    # tool_enhance.md productionization pass, tool #89 (2026-08-24) — the
    # real fix (ZERO validation of `name` — a flag-injection bug, same
    # class as tool #69's search_code) lives in the shared
    # find_api_handler() itself; see that function's own module
    # docstring.
    def sec_find_api(inp: dict[str, Any]) -> str:
        return find_api_handler(root, inp)

    # tool_enhance.md productionization pass, tool #90 (2026-08-24) — the
    # real fix (this implementation read a nonexistent `path` field —
    # the schema declares `path_pattern` — and ignored `method`
    # entirely) lives in the shared find_route_handler() itself; see
    # that function's own module docstring.
    def sec_find_route(inp: dict[str, Any]) -> str:
        return find_route_handler(root, inp)

    def sec_submit(inp: dict[str, Any]) -> str:
        security_result.update(inp)
        return "Security report submitted"

    handlers["secrets_scan"] = sec_secrets_scan
    handlers["find_sql"] = sec_find_sql
    handlers["find_config"] = sec_find_config
    handlers["find_api"] = sec_find_api
    handlers["find_route"] = sec_find_route
    handlers["submit_security_report"] = sec_submit
    handlers["_security_result"] = security_result
    return handlers


def make_arch_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Architecture reviewer: read-only + AST analysis + submit_arch_review."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    arch_result: dict[str, Any] = {}

    def ar_import_graph(inp: dict[str, Any]) -> str:
        return _ast.build_import_graph(str(root / inp["path"]))

    def ar_circular_dep(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        return _ast.detect_circular_imports(
            str(root / directory) if directory else str(root)
        )

    def ar_dead_code(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        return _ast.detect_dead_code(str(root / directory) if directory else str(root))

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def ar_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path` — so every real call silently
    # ignored the requested path and grepped the entire repo instead)
    # lives in the shared list_functions_handler() itself; see that
    # function's own module docstring.
    def ar_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_classes_handler() itself; see that function's own module
    # docstring.
    def ar_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def ar_call_graph(inp: dict[str, Any]) -> str:
        return _ast.build_call_graph(
            str(root / inp["path"]), inp.get("function_name", "")
        )

    def ar_submit(inp: dict[str, Any]) -> str:
        arch_result.update(inp)
        return "Architecture review submitted"

    handlers["import_graph"] = ar_import_graph
    handlers["circular_dep_detect"] = ar_circular_dep
    handlers["dead_code_detect"] = ar_dead_code
    handlers["parse_ast"] = ar_parse_ast
    handlers["list_functions"] = ar_list_functions
    handlers["list_classes"] = ar_list_classes
    handlers["call_graph"] = ar_call_graph
    handlers["submit_arch_review"] = ar_submit
    handlers["_arch_result"] = arch_result
    return handlers


def make_sql_agent_handlers(repo_path: str) -> dict[str, Any]:
    """SQL agent: read-only + SQL execution + schema inspection + write migrations."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    sql_result: dict[str, Any] = {}

    def sq_run_sql(inp: dict[str, Any]) -> str:
        sq_query = str(inp["query"])
        sq_settings = get_settings()
        sq_db_url = getattr(sq_settings, "database_url", None)
        if not sq_db_url:
            return "[ERROR] DATABASE_URL not configured"
        try:
            r = subprocess.run(
                ["psql", str(sq_db_url), "-c", sq_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except FileNotFoundError:
            return "[ERROR] psql not found — install postgresql-client"
        except subprocess.TimeoutExpired:
            return "[ERROR] Query timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def sq_inspect_schema(inp: dict[str, Any]) -> str:
        is_table = str(inp.get("table", ""))
        is_settings = get_settings()
        is_db_url = getattr(is_settings, "database_url", None)
        if not is_db_url:
            return "[ERROR] DATABASE_URL not configured"
        if is_table:
            is_query = (
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                f"WHERE table_name = '{is_table}' ORDER BY ordinal_position"
            )
        else:
            is_query = (
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
        try:
            r = subprocess.run(
                ["psql", str(is_db_url), "-c", is_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr)[:5000] or "(empty)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def sq_find_sql(inp: dict[str, Any]) -> str:
        keyword = str(inp.get("keyword", ""))
        fp = str(inp.get("file_pattern", "*.py"))
        if keyword:
            r = subprocess.run(
                ["grep", "-rn", "-i", "-w", keyword, "--include", fp, str(root)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-i",
                    "-E",
                    "SELECT|INSERT|UPDATE|DELETE|CREATE TABLE",
                    "--include",
                    fp,
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        return r.stdout[:6000] if r.stdout else "(no SQL found)"

    def sq_explain_query(inp: dict[str, Any]) -> str:
        eq_query = str(inp.get("query", ""))
        eq_settings = get_settings()
        eq_db_url = getattr(eq_settings, "database_url", None)
        if not eq_db_url:
            return "[ERROR] DATABASE_URL not configured"
        try:
            r = subprocess.run(
                [
                    "psql",
                    str(eq_db_url),
                    "-c",
                    f"EXPLAIN ANALYZE {eq_query}",
                    "--no-password",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no plan)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def sq_submit(inp: dict[str, Any]) -> str:
        sql_result.update(inp)
        return "SQL report submitted"

    handlers["run_sql"] = sq_run_sql
    handlers["inspect_schema"] = sq_inspect_schema
    handlers["find_sql"] = sq_find_sql
    handlers["explain_query"] = sq_explain_query
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_sql_report"] = sq_submit
    handlers["_sql_result"] = sql_result
    return handlers


def make_docker_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Docker agent: read-only + docker CLI inspection + limited docker actions + write_file."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docker_result: dict[str, Any] = {}

    def dk_docker_ps(inp: dict[str, Any]) -> str:
        r = subprocess.run(
            [
                "docker",
                "ps",
                "--format",
                "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout or r.stderr or "(no containers)"

    def dk_docker_logs(inp: dict[str, Any]) -> str:
        dl_container = str(inp["container"])
        dl_n = int(inp.get("lines", 50))
        r = subprocess.run(
            ["docker", "logs", "--tail", str(dl_n), dl_container],
            capture_output=True,
            text=True,
            timeout=15,
        )
        raw = (r.stdout + r.stderr)[:6000]
        if not raw:
            return "(no logs)"
        return _summarize_docker_log_patterns(raw) + raw

    def dk_docker_exec(inp: dict[str, Any]) -> str:
        de_container = str(inp["container"])
        de_cmd = str(inp["command"])
        if any(
            d in de_cmd
            for d in ["rm ", "kill", "stop", "restart", "drop", "delete", "truncate"]
        ):
            return f"[POLICY DENIED] Docker exec not allowed: {de_cmd!r}"
        de_risk = _docker_container_risk_reason(de_container)
        if de_risk:
            return f"[POLICY DENIED] {de_risk}"
        r = subprocess.run(
            ["docker", "exec", de_container] + de_cmd.split(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:4000] or "(no output)"

    def dk_docker_compose(inp: dict[str, Any]) -> str:
        dc_action = str(inp.get("action", "ps"))
        dc_allowed = {"ps", "logs", "config", "images"}
        if dc_action not in dc_allowed:
            return f"[POLICY DENIED] Only allowed: {sorted(dc_allowed)}. Got: {dc_action!r}"
        r = subprocess.run(
            ["docker", "compose", dc_action],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:6000] or "(no output)"

    def dk_docker_build(inp: dict[str, Any]) -> str:
        db_tag = str(inp.get("tag", "app:dev"))
        db_file = str(inp.get("dockerfile", "Dockerfile"))
        db_ctx = str(inp.get("context", "."))
        db_error = validate_docker_build_inputs(db_ctx, db_file, repo_path)
        if db_error:
            return f"[POLICY DENIED] {db_error}"
        r = subprocess.run(
            ["docker", "build", "-t", db_tag, "-f", db_file, db_ctx],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        out = (r.stdout + r.stderr)[:8000]
        return f"Build {'succeeded' if r.returncode == 0 else 'FAILED'}:\n{out}"

    def dk_docker_restart(inp: dict[str, Any]) -> str:
        dr_container = str(inp["container"])
        r = subprocess.run(
            ["docker", "restart", dr_container],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr).strip() or f"Restarted {dr_container}"

    def dk_diagnose_deployment_failure(inp: dict[str, Any]) -> str:
        # AUDIT_Q_BATCH10 §19 "Diagnose deployment failures: NO — no
        # dedicated failure-analysis tool/agent beyond the log pattern
        # summarizer". Gathers real docker state (ps -a, logs, inspect
        # State) — never guessed — then adds a real LLM diagnosis layer on
        # top of it, distinct from _summarize_docker_log_patterns's
        # keyword-only detection.
        dd_container = str(inp.get("container", "")).strip()
        dd_lines = int(inp.get("lines", 100))
        parts: list[str] = []
        ps_r = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--format",
                "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        parts.append(
            "=== docker ps -a ===\n" + (ps_r.stdout or ps_r.stderr or "(no containers)")
        )
        if dd_container:
            logs_r = subprocess.run(
                ["docker", "logs", "--tail", str(dd_lines), dd_container],
                capture_output=True,
                text=True,
                timeout=15,
            )
            raw_logs = (logs_r.stdout + logs_r.stderr)[:6000]
            parts.append(
                f"=== docker logs --tail {dd_lines} {dd_container} ===\n"
                + (
                    _summarize_docker_log_patterns(raw_logs) + raw_logs
                    if raw_logs
                    else "(no logs)"
                )
            )
            inspect_r = subprocess.run(
                ["docker", "inspect", dd_container],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if inspect_r.returncode == 0:
                import json as _json

                try:
                    data = _json.loads(inspect_r.stdout)
                    state = (data[0] if data else {}).get("State", {})
                    inspect_summary = {
                        "Status": state.get("Status"),
                        "ExitCode": state.get("ExitCode"),
                        "Error": state.get("Error"),
                        "OOMKilled": state.get("OOMKilled"),
                        "RestartCount": (data[0] if data else {}).get("RestartCount"),
                        "StartedAt": state.get("StartedAt"),
                        "FinishedAt": state.get("FinishedAt"),
                    }
                    parts.append(
                        "=== docker inspect (State) ===\n"
                        + _json.dumps(inspect_summary, indent=2)
                    )
                except Exception:
                    parts.append("=== docker inspect ===\n" + inspect_r.stdout[:2000])
            else:
                parts.append(
                    f"[ERROR] docker inspect {dd_container} failed: "
                    f"{(inspect_r.stderr or '')[:500]}"
                )
        context = "\n\n".join(parts)
        diagnosis = _llm_diagnose_deployment_failure(context)
        return f"{context}\n\n=== Diagnosis ===\n{diagnosis}"

    def dk_submit(inp: dict[str, Any]) -> str:
        docker_result.update(inp)
        return "Docker report submitted"

    handlers["docker_ps"] = dk_docker_ps
    handlers["docker_logs"] = dk_docker_logs
    handlers["docker_exec"] = dk_docker_exec
    handlers["docker_compose"] = dk_docker_compose
    handlers["diagnose_deployment_failure"] = dk_diagnose_deployment_failure
    handlers["docker_build"] = dk_docker_build
    handlers["docker_restart"] = dk_docker_restart
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_docker_report"] = dk_submit
    handlers["_docker_result"] = docker_result
    return handlers


def make_cicd_agent_handlers(repo_path: str) -> dict[str, Any]:
    """CI/CD agent: read-only + limited bash (git/grep only) + file writes + submit."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    cicd_result: dict[str, Any] = {}

    _CICD_ALLOWED = (
        "git log",
        "git diff",
        "git status",
        "git show",
        "cat ",
        "grep ",
        "echo ",
        "ls ",
    )

    def ci_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _CICD_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("cicd", 30)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("cicd"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr)[:4000] or "(no output)"

    def ci_submit(inp: dict[str, Any]) -> str:
        cicd_result.update(inp)
        return "CI/CD report submitted"

    handlers["bash"] = ci_bash
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_cicd_report"] = ci_submit
    handlers["_cicd_result"] = cicd_result
    return handlers


def make_refactor_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Refactor agent: read-only + AST + write + rename + limited bash (test/lint only)."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    refactor_result: dict[str, Any] = {}

    _RF_ALLOWED = ("python -m pytest", "mypy", "ruff", "black", "isort")

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def rf_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix lives in the shared list_classes_handler(); see that
    # function's own module docstring.
    def rf_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def rf_find_function_body(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        r = subprocess.run(
            ["grep", "-rn", f"def {name}", str(root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout[:4000] if r.stdout else f"(function '{name}' not found)"

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def rf_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    def rf_call_graph(inp: dict[str, Any]) -> str:
        return _ast.build_call_graph(
            str(root / inp["path"]), inp.get("function_name", "")
        )

    def rf_import_graph(inp: dict[str, Any]) -> str:
        return _ast.build_import_graph(str(root / inp["path"]))

    def rf_rename_symbol(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        rsym_error = validate_rename_symbol_directory(directory, repo_path)
        if rsym_error:
            return f"[POLICY DENIED] {rsym_error}"
        return _ast.rename_symbol(
            inp["old_name"],
            inp["new_name"],
            str(root / directory) if directory else str(root),
            str(inp.get("file_pattern", "*.py")),
            confirm_large_batch=bool(inp.get("confirm_large_batch", False)),
        )

    # moved to app/tools/filesystem/replace_function.py as
    # replace_function_handler — tool_enhance.md productionization pass,
    # tool #24 (2026-08-18). Real bug found+fixed here: this handler
    # previously read inp["new_body"], but REPLACE_FUNCTION_TOOL's own
    # schema (what refactor_agent actually advertises to its LLM)
    # documents the field as "new_code" — every real, schema-conformant
    # call raised an uncaught KeyError. Its own regex also only matched
    # top-level functions, never class methods, unlike the shared
    # handler below (already proven correct via chat_agent.py/
    # make_chat_handlers). See replace_function.py's own docstring for
    # the full real proof.
    def rf_replace_function(inp: dict[str, Any]) -> str:
        return replace_function_handler(root, repo_path, inp)

    def rf_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _RF_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("refactor", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("refactor"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr)[:6000] or "(no output)"

    def rf_submit(inp: dict[str, Any]) -> str:
        refactor_result.update(inp)
        return "Refactor report submitted"

    handlers["list_functions"] = rf_list_functions
    handlers["list_classes"] = rf_list_classes
    handlers["find_function_body"] = rf_find_function_body
    handlers["parse_ast"] = rf_parse_ast
    handlers["call_graph"] = rf_call_graph
    handlers["import_graph"] = rf_import_graph
    handlers["rename_symbol"] = rf_rename_symbol
    handlers["replace_function"] = rf_replace_function
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["git_diff"] = _make_git_diff_handler(repo_path)
    handlers["bash"] = rf_bash
    handlers["submit_refactor_report"] = rf_submit
    handlers["_refactor_result"] = refactor_result
    return handlers


def make_readme_agent_handlers(repo_path: str) -> dict[str, Any]:
    """README agent: read-only + AST + write_file (*.md only) + submit_docs."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def rm_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def rm_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix lives in the shared list_classes_handler(); see that
    # function's own module docstring.
    def rm_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def rm_write_file(inp: dict[str, Any]) -> str:
        from app.policy.engine import check_path_in_worktree

        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] README agent may only write .md files. Got: {rel!r}"
            )
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    handlers["parse_ast"] = rm_parse_ast
    handlers["list_functions"] = rm_list_functions
    handlers["list_classes"] = rm_list_classes
    handlers["write_file"] = rm_write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


def make_api_docs_agent_handlers(repo_path: str) -> dict[str, Any]:
    """API Docs agent: read-only + route/API finders + AST + write_file (*.md) + submit_docs."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #90 (2026-08-24) — the
    # real fix lives in the shared find_route_handler(); see that
    # function's own module docstring.
    def ad_find_route(inp: dict[str, Any]) -> str:
        return find_route_handler(root, inp)

    # tool_enhance.md productionization pass, tool #89 (2026-08-24) — the
    # real fix lives in the shared find_api_handler(); see that
    # function's own module docstring.
    def ad_find_api(inp: dict[str, Any]) -> str:
        return find_api_handler(root, inp)

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def ad_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def ad_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    def ad_write_file(inp: dict[str, Any]) -> str:
        from app.policy.engine import check_path_in_worktree

        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] API docs agent may only write .md files. Got: {rel!r}"
            )
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    handlers["find_route"] = ad_find_route
    handlers["find_api"] = ad_find_api
    handlers["parse_ast"] = ad_parse_ast
    handlers["list_functions"] = ad_list_functions
    handlers["write_file"] = ad_write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


def make_dependency_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Dependency agent: read-only + bash (pip/npm audit only) + edit requirements + submit."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    dep_result: dict[str, Any] = {}

    _DEP_ALLOWED = (
        "pip index versions",
        "pip show",
        "pip list",
        "npm audit",
        "npm outdated",
        "npm list",
        "safety check",
        "pip-audit",
    )
    _DEP_EDITABLE = {
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "pyproject.toml",
    }

    def dep_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _DEP_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("dependency_agent", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("dependency_agent"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr)[:6000] or "(no output)"

    def dep_edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if Path(rel).name not in _DEP_EDITABLE:
            return f"[POLICY DENIED] Dependency agent may only edit requirements/package files. Got: {rel!r}"
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        old_s, new_s = inp["old_string"], inp["new_string"]
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited {rel}"

    def dep_submit(inp: dict[str, Any]) -> str:
        dep_result.update(inp)
        return "Dependency report submitted"

    def check_last_release(inp: dict[str, Any]) -> str:
        import json as _json

        package = str(inp.get("package", "")).strip()
        ecosystem = str(inp.get("ecosystem", "pypi")).strip().lower()
        if not package:
            return "[ERROR] package is required"
        if ecosystem == "pypi":
            registry_url = f"https://pypi.org/pypi/{package}/json"
        elif ecosystem == "npm":
            registry_url = f"https://registry.npmjs.org/{package}"
        else:
            return (
                f"[ERROR] Unknown ecosystem: {ecosystem!r} (expected 'pypi' or 'npm')"
            )

        try:
            r = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-L",
                    "--max-time",
                    "15",
                    "--user-agent",
                    "Gridiron-Agent/1.0",
                    registry_url,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            return f"[ERROR] Registry lookup for {package!r} timed out"
        except FileNotFoundError:
            return "[ERROR] curl not found"
        if r.returncode != 0 or not r.stdout:
            return f"[ERROR] Could not reach {ecosystem} registry for {package!r}"
        try:
            data = _json.loads(r.stdout)
        except _json.JSONDecodeError:
            return f"[ERROR] {package!r} not found on {ecosystem} (or invalid response)"

        try:
            if ecosystem == "pypi":
                latest_version = data["info"]["version"]
                urls = data.get("urls") or []
                upload_time = urls[0]["upload_time_iso_8601"] if urls else None
            else:
                latest_version = data["dist-tags"]["latest"]
                upload_time = data.get("time", {}).get(latest_version)
        except (KeyError, IndexError, TypeError):
            return f"[ERROR] Unexpected {ecosystem} registry response shape for {package!r}"

        if not upload_time:
            return f"{package}: latest version {latest_version}, no publish date available from {ecosystem}"

        from datetime import datetime, timezone as _timezone

        published = datetime.fromisoformat(upload_time.replace("Z", "+00:00"))
        days_since = (datetime.now(_timezone.utc) - published).days
        settings = get_settings()
        if days_since >= settings.dependency_abandoned_threshold_days:
            staleness = f"ABANDONED (no release in {days_since} days)"
        elif days_since >= settings.dependency_possibly_abandoned_threshold_days:
            staleness = f"possibly abandoned (no release in {days_since} days)"
        else:
            staleness = f"actively maintained ({days_since} days since last release)"
        return (
            f"{package} ({ecosystem}): latest release {latest_version}, "
            f"published {upload_time} — {staleness}"
        )

    handlers["bash"] = dep_bash
    handlers["check_last_release"] = check_last_release
    handlers["edit_file"] = dep_edit_file
    handlers["submit_dependency_report"] = dep_submit
    handlers["_dependency_result"] = dep_result
    return handlers


def make_monitoring_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Monitoring agent: read-only + system metrics + submit_monitoring_report. No writes."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    monitoring_result: dict[str, Any] = {}

    def mon_cpu_usage(inp: dict[str, Any]) -> str:
        r = subprocess.run(["top", "-bn1"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "%Cpu" in line or "Cpu(s)" in line:
                return line.strip()
        return r.stdout[:500] or "[ERROR] Could not read CPU"

    def mon_memory_usage(inp: dict[str, Any]) -> str:
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "[ERROR] Could not read memory"

    def mon_disk_usage(inp: dict[str, Any]) -> str:
        du_path = str(inp.get("path", "/"))
        r = subprocess.run(
            ["df", "-h", du_path], capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() or "[ERROR] Could not read disk"

    def mon_health_check(inp: dict[str, Any]) -> str:
        hc_url = str(inp.get("url", "http://localhost:8000/health"))
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code} %{time_total}s",
                hc_url,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.strip() or r.stderr.strip() or "[ERROR] curl failed"

    def mon_task_progress(inp: dict[str, Any]) -> str:
        tp_task_id = inp.get("task_id")
        tp_settings = get_settings()
        tp_db_url = getattr(tp_settings, "database_url", None)
        if not tp_db_url:
            return "[ERROR] DATABASE_URL not configured"
        if tp_task_id:
            query = f"SELECT id, title, status, updated_at FROM dev_tasks WHERE id={int(tp_task_id)}"
        else:
            query = "SELECT id, title, status, updated_at FROM dev_tasks ORDER BY updated_at DESC LIMIT 10"
        try:
            r = subprocess.run(
                ["psql", str(tp_db_url), "-c", query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr)[:4000] or "(no tasks)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def mon_read_logs(inp: dict[str, Any]) -> str:
        rl_path = str(inp.get("path", "backend/logs/app.log"))
        rl_n = int(inp.get("lines", 100))
        try:
            p = root / rl_path
            if not p.exists():
                return f"[ERROR] Log not found: {rl_path}"
            return "\n".join(
                p.read_text(encoding="utf-8", errors="replace").splitlines()[-rl_n:]
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def mon_submit(inp: dict[str, Any]) -> str:
        monitoring_result.update(inp)
        return "Monitoring report submitted"

    handlers["cpu_usage"] = mon_cpu_usage
    handlers["memory_usage"] = mon_memory_usage
    handlers["disk_usage"] = mon_disk_usage
    handlers["health_check"] = mon_health_check
    handlers["task_progress"] = mon_task_progress
    handlers["read_logs"] = mon_read_logs
    handlers["submit_monitoring_report"] = mon_submit
    handlers["_monitoring_result"] = monitoring_result
    return handlers


# ===========================================================================
# Day 3 — Browser, Memory, Planning, External Integration tool specs + Agent
# tool lists + Factories
# ===========================================================================

# moved to app/tools/browser/browser_tools.py as BROWSER_OPEN_TOOL/
# BROWSER_NAVIGATE_TOOL/BROWSER_SCREENSHOT_TOOL/BROWSER_READ_DOM_TOOL/
# BROWSER_CLICK_TOOL/BROWSER_TYPE_TOOL/BROWSER_CLOSE_TOOL —
# tool_enhance.md productionization pass, tools #28-#31 + #123-#125
# (2026-08-18).

# --- Day 3B: Memory tool specs ---

_MEMORY_READ_TOOL: dict[str, Any] = {
    "name": "memory_read",
    "description": "Read a value from the per-repo memory store by key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key to read from memory"}
        },
        "required": ["key"],
    },
}

# moved to app/tools/agents/memory_write.py as MEMORY_WRITE_TOOL — tool_enhance.md productionization pass, tool #51 (2026-08-20).

_DECISION_LOG_APPEND_TOOL: dict[str, Any] = {
    "name": "decision_log_append",
    "description": "Append a design decision with rationale to the project decision log.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "description": "The decision made"},
            "reason": {"type": "string", "description": "Why this decision was made"},
            "alternatives": {
                "type": "string",
                "description": "What alternatives were considered (optional)",
            },
        },
        "required": ["decision", "reason"],
    },
}

_TASK_HISTORY_QUERY_TOOL: dict[str, Any] = {
    "name": "task_history_query",
    "description": "Query recent task history from the task_logs table.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max records to return (default 20)",
            },
            "status": {
                "type": "string",
                "description": "Filter by status: completed, failed, blocked (optional)",
            },
        },
        "required": [],
    },
}

_KNOWN_ISSUES_READ_TOOL: dict[str, Any] = {
    "name": "known_issues_read",
    "description": "Read the project's known issues file.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_KNOWN_ISSUES_WRITE_TOOL: dict[str, Any] = {
    "name": "known_issues_write",
    "description": "Append a new known issue to the project known issues file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "Description of the issue"},
            "severity": {
                "type": "string",
                "description": "critical / high / medium / low",
            },
        },
        "required": ["issue", "severity"],
    },
}

# --- Day 3C: Planning + docs tool specs ---

_ESTIMATE_COMPLEXITY_TOOL: dict[str, Any] = {
    "name": "estimate_complexity",
    "description": "Estimate task complexity as XS/S/M/L/XL based on heuristics (description token count, file scope).",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Task or feature description to estimate",
            },
            "context_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of files/dirs likely involved",
            },
        },
        "required": ["description"],
    },
}

_SUMMARIZE_FOLDER_TOOL: dict[str, Any] = {
    "name": "summarize_folder",
    "description": "Return a concise summary of every .py/.ts file in a folder (up to 20 files).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative folder path to summarize",
            },
            "extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File extensions to include (default: .py, .ts, .tsx)",
            },
        },
        "required": ["path"],
    },
}

_GENERATE_API_DOCS_TEXT_TOOL: dict[str, Any] = {
    "name": "generate_api_docs_text",
    "description": "Parse a FastAPI route file and return a structured markdown template of all endpoints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "route_path": {
                "type": "string",
                "description": "Relative path to the FastAPI router file",
            }
        },
        "required": ["route_path"],
    },
}

_MERMAID_FROM_SCHEMA_TOOL: dict[str, Any] = {
    "name": "mermaid_from_schema",
    "description": "Convert a database schema inspection into a Mermaid ER diagram string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Table name to focus on (optional — uses all tables if omitted)",
            }
        },
        "required": [],
    },
}

# --- Day 2 Gap: Smart search tools ---

_FIND_QUEUE_TOOL: dict[str, Any] = {
    "name": "find_queue",
    "description": "Search the codebase for Queue / task-queue patterns (asyncio.Queue, BullMQ, RQ, Celery). Returns file:line matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Repo root to search (optional, defaults to current repo)",
            }
        },
        "required": [],
    },
}

_FIND_WORKER_TOOL: dict[str, Any] = {
    "name": "find_worker",
    "description": "Search the codebase for Worker / consumer patterns (Worker class, @worker, celery worker, RQ worker). Returns file:line matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Repo root to search (optional)",
            }
        },
        "required": [],
    },
}

# --- Day 2 Gap: Advanced editing tools ---

# moved to app/tools/filesystem/insert_before.py as INSERT_BEFORE_TOOL — tool_enhance.md productionization pass, tool #48 (2026-08-20).

# moved to app/tools/filesystem/insert_after.py as INSERT_AFTER_TOOL — tool_enhance.md productionization pass, tool #46 (2026-08-19).

# moved to app/tools/filesystem/delete_block.py as DELETE_BLOCK_TOOL —
# tool_enhance.md productionization pass, tool #33 (2026-08-18).

# --- Day 2 Gap: Documentation generation tools ---

_GENERATE_CHANGELOG_TOOL: dict[str, Any] = {
    "name": "generate_changelog",
    "description": "Generate a CHANGELOG.md entry from git log between two refs (Keep-a-Changelog format). Returns the changelog text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_ref": {
                "type": "string",
                "description": "Starting git ref (tag or commit). Defaults to previous tag.",
            },
            "to_ref": {
                "type": "string",
                "description": "Ending git ref (default: HEAD)",
            },
            "repo_path": {"type": "string", "description": "Repo root (optional)"},
        },
        "required": [],
    },
}

_SUMMARIZE_REPO_TOOL: dict[str, Any] = {
    "name": "summarize_repo",
    "description": "Generate a high-level summary of the repository: file tree (top 3 levels), line counts, language breakdown, and README excerpt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repo root (optional)"}
        },
        "required": [],
    },
}

_GENERATE_RELEASE_NOTES_TOOL: dict[str, Any] = {
    "name": "generate_release_notes",
    "description": "Generate a formatted release notes document from git history between two version tags.",
    "input_schema": {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "description": "New version number (e.g. v1.2.0)",
            },
            "from_ref": {
                "type": "string",
                "description": "Previous version tag or commit",
            },
            "repo_path": {"type": "string", "description": "Repo root (optional)"},
        },
        "required": ["version"],
    },
}

# --- Day 2 Gap: File type tools ---

_READ_PDF_TOOL: dict[str, Any] = {
    "name": "read_pdf",
    "description": "Extract text content from a PDF file using pdfplumber. Returns plain text, one paragraph per page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file"},
            "max_pages": {
                "type": "integer",
                "description": "Maximum pages to extract (default: 20)",
            },
        },
        "required": ["path"],
    },
}

_READ_IMAGE_TOOL: dict[str, Any] = {
    "name": "read_image",
    "description": "Read an image file and return basic metadata (format, size, mode) plus a base64-encoded thumbnail for vision inspection.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the image file (PNG, JPG, GIF, BMP, WebP)",
            },
        },
        "required": ["path"],
    },
}

# --- Day 2 Gap: GitHub PR tool ---
# _GITHUB_CREATE_PR_TOOL moved to app/tools/git/pull_request.py as
# GITHUB_CREATE_PR_TOOL — tool_enhance.md productionization pass, tool #6
# (2026-08-16).

# --- Day 3G: External integration tool specs (GitHub CLI / Linear / Slack
# webhooks — plain REST/CLI wrappers, NOT the Model Context Protocol. See
# AUDIT_Q_BATCH17 §71 gap-closure: this label previously said "MCP", which
# was a naming mismatch — real MCP-protocol-building help now lives in the
# dedicated mcp_developer_agent.py instead. ---

# moved to app/tools/git/github_create_issue.py as GITHUB_CREATE_ISSUE_TOOL — tool_enhance.md productionization pass, tool #45 (2026-08-19).

_GITHUB_LIST_PRS_TOOL: dict[str, Any] = {
    "name": "github_list_prs",
    "description": "List GitHub pull requests using the gh CLI.",
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "description": "open / closed / merged (default: open)",
            }
        },
        "required": [],
    },
}

# moved to app/tools/git/github_comment.py as GITHUB_COMMENT_TOOL — tool_enhance.md productionization pass, tool #44 (2026-08-19).

# moved to app/tools/integrations/linear_create_issue.py as LINEAR_CREATE_ISSUE_TOOL — tool_enhance.md productionization pass, tool #50 (2026-08-20).

# moved to app/tools/integrations/slack_send_message.py as
# SLACK_SEND_MESSAGE_TOOL / send_slack_message — tool_enhance.md
# productionization pass, tool #63 (2026-08-22). Same "advertised but
# never dispatched" bug class as tool #50's linear_create_issue —
# chat_agent.py had zero dispatch branch despite this being advertised
# via CHAT_TOOLS.
_SLACK_SEND_MESSAGE_TOOL: dict[str, Any] = SLACK_SEND_MESSAGE_TOOL

# --- Day 3 Agent submit tool specs ---

_SUBMIT_PERF_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_perf_review",
    "description": "Submit performance review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "object"}},
            "severity": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_STYLE_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_style_review",
    "description": "Submit style/lint review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "violations": {"type": "array", "items": {"type": "object"}},
            "auto_fixable": {"type": "boolean"},
        },
        "required": ["summary"],
    },
}

_SUBMIT_SPRINT_PLAN_TOOL: dict[str, Any] = {
    "name": "submit_sprint_plan",
    "description": "Submit a sprint plan with stories and estimates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "stories": {"type": "array", "items": {"type": "object"}},
            "total_points": {"type": "integer"},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goal", "stories"],
    },
}

_SUBMIT_BA_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_ba_result",
    "description": "Submit business analysis: user stories, acceptance criteria, edge cases.",
    "input_schema": {
        "type": "object",
        "properties": {
            "user_stories": {"type": "array", "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "edge_cases": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["user_stories", "summary"],
    },
}

_SUBMIT_MIGRATION_TOOL: dict[str, Any] = {
    "name": "submit_migration",
    "description": "Submit the generated migration file path and validation results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "migration_file": {"type": "string"},
            "is_reversible": {"type": "boolean"},
            "summary": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_SCHEMA_TOOL: dict[str, Any] = {
    "name": "submit_schema",
    "description": "Submit a schema design or review result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tables": {"type": "array", "items": {"type": "object"}},
            "normalization_issues": {"type": "array", "items": {"type": "string"}},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_AI_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_ai_result",
    "description": "Submit AI/ML engineering task results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "files_created": {"type": "array", "items": {"type": "string"}},
            "eval_results": {"type": "object"},
            "next_steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_CLEANUP_TOOL: dict[str, Any] = {
    "name": "submit_cleanup",
    "description": "Submit cleanup results: dead code removed, files deleted, imports organized.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "dead_code_removed": {"type": "array", "items": {"type": "string"}},
            "files_deleted": {"type": "array", "items": {"type": "string"}},
            "imports_cleaned": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}

_SUBMIT_TECH_DEBT_TOOL: dict[str, Any] = {
    "name": "submit_tech_debt",
    "description": "Submit technical debt analysis findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "debt_items": {"type": "array", "items": {"type": "object"}},
            "priority_fixes": {"type": "array", "items": {"type": "string"}},
            "effort_estimate": {"type": "string"},
        },
        "required": ["summary"],
    },
}

# --- Day 3 agent-specific bash specs (restricted allowlists) ---

_MIGRATION_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run migration-related commands: alembic upgrade/downgrade, alembic revision, git diff.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_AI_ENGINEER_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run AI/ML commands: python script execution, pip install packages, model evaluation scripts.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_CLEANUP_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run cleanup commands: find dead code, check imports, ruff/isort checks.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

# --- Day 3 Agent Tool Lists ---

PERFORMANCE_REVIEWER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _FIND_SQL_TOOL,
    _RUN_SQL_TOOL,
    _EXPLAIN_QUERY_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _SUBMIT_PERF_REVIEW_TOOL,
]

STYLE_REVIEWER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_LINTER_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _SUBMIT_STYLE_REVIEW_TOOL,
]

SPRINT_PLANNER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _ESTIMATE_COMPLEXITY_TOOL,
    _SUBMIT_SPRINT_PLAN_TOOL,
]

BUSINESS_ANALYST_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _SUBMIT_BA_RESULT_TOOL,
]

MIGRATION_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _MIGRATION_BASH_TOOL_SPEC,
    _SUBMIT_MIGRATION_TOOL,
]

SCHEMA_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_SCHEMA_TOOL,
]

AI_ENGINEER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_PYTHON_SNIPPET_TOOL,
    _AI_ENGINEER_BASH_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _FETCH_URL_TOOL,
    _SUBMIT_AI_RESULT_TOOL,
]

CLEANUP_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _DEAD_CODE_DETECT_TOOL,
    _ORGANIZE_IMPORTS_TOOL,
    _DELETE_FILE_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _CLEANUP_BASH_TOOL_SPEC,
    _SUBMIT_CLEANUP_TOOL,
]

TECH_DEBT_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _RUN_LINTER_TOOL,
    _COVERAGE_REPORT_TOOL,
    _SUBMIT_TECH_DEBT_TOOL,
]

# --- Day 3 Handler Factories ---


def make_performance_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Performance Reviewer agent."""
    import subprocess as _sp
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    perf_result: dict[str, Any] = {}

    def pr_find_sql(inp: dict[str, Any]) -> str:
        keyword = str(inp.get("keyword", "")).upper() or "SELECT"
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if keyword in line.upper():
                    results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
        return "\n".join(results[:50]) or f"(no matches for {keyword})"

    def pr_run_sql(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip()
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        # Block destructive ops
        low = sql.lower()
        if any(
            k in low for k in ("drop ", "delete ", "truncate ", "update ", "insert ")
        ):
            return "[POLICY DENIED] Performance reviewer is read-only — use SELECT / EXPLAIN only"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def pr_explain_query(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip().rstrip(";")
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        try:
            r = _sp.run(
                [
                    "psql",
                    db_url,
                    "-c",
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql};",
                    "--no-psqlrc",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path` — a relative `../` traversal genuinely
    # escaped the repo, since the accidental `relative_to(root)`
    # safety net only blocked ABSOLUTE outside-repo paths, not
    # traversal) lives in the shared list_functions_handler() itself;
    # see that function's own module docstring.
    def pr_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    def pr_submit(inp: dict[str, Any]) -> str:
        perf_result.update(inp)
        return "Performance review submitted"

    handlers["find_sql"] = pr_find_sql
    handlers["run_sql"] = pr_run_sql
    handlers["explain_query"] = pr_explain_query
    handlers["list_functions"] = pr_list_functions
    handlers["submit_perf_review"] = pr_submit
    handlers["_perf_result"] = perf_result
    return handlers


def make_style_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Style Reviewer agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    style_result: dict[str, Any] = {}

    def sr_run_linter(inp: dict[str, Any]) -> str:
        sr_path = str(inp.get("path", "."))
        try:
            r = _sp.run(
                ["python", "-m", "ruff", "check", sr_path, "--output-format=text"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no linting issues)"
        except Exception as e:
            return f"[ERROR] {e}"

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path`, same relative-traversal-escape finding as
    # pr_list_functions) lives in the shared list_functions_handler()
    # itself; see that function's own module docstring.
    def sr_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path` — a relative `../` traversal genuinely
    # escaped the repo) lives in the shared list_classes_handler()
    # itself; see that function's own module docstring.
    def sr_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def sr_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if "TODO" in line or "FIXME" in line or "HACK" in line:
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(no TODOs found)"

    def sr_submit(inp: dict[str, Any]) -> str:
        style_result.update(inp)
        return "Style review submitted"

    handlers["run_linter"] = sr_run_linter
    handlers["list_functions"] = sr_list_functions
    handlers["list_classes"] = sr_list_classes
    handlers["find_todos"] = sr_find_todos
    handlers["submit_style_review"] = sr_submit
    handlers["_style_result"] = style_result
    return handlers


def make_sprint_planner_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Sprint Planner agent."""
    handlers = make_read_only_handlers(repo_path)
    sprint_result: dict[str, Any] = {}

    def sp_estimate_complexity(inp: dict[str, Any]) -> str:
        description = str(inp.get("description", ""))
        context_paths = list(inp.get("context_paths", []))
        # Heuristic: word count of description + number of context files
        word_count = len(description.split())
        file_count = len(context_paths)
        score = word_count + file_count * 10
        if score < 30:
            size = "XS"
        elif score < 80:
            size = "S"
        elif score < 200:
            size = "M"
        elif score < 500:
            size = "L"
        else:
            size = "XL"
        return f"Estimated complexity: {size} (word_count={word_count}, context_files={file_count}, score={score})"

    def sp_submit(inp: dict[str, Any]) -> str:
        sprint_result.update(inp)
        return "Sprint plan submitted"

    handlers["estimate_complexity"] = sp_estimate_complexity
    handlers["submit_sprint_plan"] = sp_submit
    handlers["_sprint_result"] = sprint_result
    return handlers


def make_business_analyst_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Business Analyst agent."""
    handlers = make_read_only_handlers(repo_path)
    ba_result: dict[str, Any] = {}

    def ba_submit(inp: dict[str, Any]) -> str:
        ba_result.update(inp)
        return "Business analysis submitted"

    handlers["submit_ba_result"] = ba_submit
    handlers["_ba_result"] = ba_result
    return handlers


def make_migration_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Migration Agent."""
    import subprocess as _sp
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    migration_result: dict[str, Any] = {}

    _MIGRATION_BASH_ALLOWLIST = (
        "alembic upgrade",
        "alembic downgrade",
        "alembic revision",
        "alembic history",
        "alembic current",
        "alembic heads",
        "git diff",
        "git status",
        "git log",
    )

    def mg_run_sql(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip()
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        low = sql.lower()
        if any(k in low for k in ("drop table", "truncate", "delete from")):
            return "[POLICY DENIED] Destructive SQL blocked in migration agent"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_inspect_schema(inp: dict[str, Any]) -> str:
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        tbl = inp.get("table")
        sql = f"\\d+ {tbl}" if tbl else "\\dt+"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        # Migration agent may only write to migrations/ or backend/migrations/
        if not (
            rel.startswith("migrations/")
            or rel.startswith("backend/migrations/")
            or rel.endswith(".py")
        ):
            return (
                f"[POLICY DENIED] Migration agent may only write migration files: {rel}"
            )
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _MIGRATION_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("migration", 60)
        try:
            # alembic (migrations/env.py) reads DATABASE_URL from the
            # environment — a sandboxed container does NOT inherit the
            # host's env automatically (app.policy.sandbox.run_sandboxed's
            # own docstring), so it must be forwarded explicitly. Reaching
            # the real Postgres instance at all requires network="host"
            # (bash_tool_sandbox_network's own default for this variant) —
            # verified empirically: docker-compose.yml deliberately binds
            # Postgres to 127.0.0.1 only, unreachable from a bridge-network
            # container even via host.docker.internal routing.
            stdout, stderr, _returncode, timed_out = _run_bash_command(
                cmd,
                str(root),
                timeout=timeout,
                extra_env={"DATABASE_URL": settings.database_url},
                image=settings.bash_sandbox_toolchain_image,
                network=settings.bash_tool_sandbox_network.get("migration"),
            )
            if timed_out:
                return f"[ERROR] Command timed out after {timeout}s"
            return (stdout + stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_submit(inp: dict[str, Any]) -> str:
        migration_result.update(inp)
        return "Migration submitted"

    handlers["run_sql"] = mg_run_sql
    handlers["inspect_schema"] = mg_inspect_schema
    handlers["write_file"] = mg_write_file
    handlers["bash"] = mg_bash
    handlers["submit_migration"] = mg_submit
    handlers["_migration_result"] = migration_result
    return handlers


def make_schema_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Schema Agent."""
    import subprocess as _sp
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    schema_result: dict[str, Any] = {}

    def sa_run_sql(inp: dict[str, Any]) -> str:
        sql = str(inp["query"]).strip()
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        low = sql.lower()
        if any(k in low for k in ("drop ", "delete ", "truncate ")):
            return "[POLICY DENIED] Schema agent cannot run destructive SQL"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def sa_inspect_schema(inp: dict[str, Any]) -> str:
        settings = _gs()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        tbl = inp.get("table")
        sql = f"\\d+ {tbl}" if tbl else "\\dt+"
        try:
            r = _sp.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def sa_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def sa_submit(inp: dict[str, Any]) -> str:
        schema_result.update(inp)
        return "Schema design submitted"

    handlers["run_sql"] = sa_run_sql
    handlers["inspect_schema"] = sa_inspect_schema
    handlers["write_file"] = sa_write_file
    handlers["submit_schema"] = sa_submit
    handlers["_schema_result"] = schema_result
    return handlers


def make_ai_engineer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for AI/ML Engineer agent."""
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    ai_result: dict[str, Any] = {}

    # Blocker 6 (audit_v1.md 4.5/4.8): bare "python "/"python3 "/"pip install "
    # prefixes are inherently unrestrictable (any script path/package name
    # satisfies the prefix match; pip install is a supply-chain RCE vector
    # via install-time hooks). Dropped. "python -m "/"python3 -m " restrict
    # execution to installed modules, which is materially narrower, and are
    # kept — same as the rest of this allowlist, they now also run inside
    # the Docker sandbox (see ae_bash below), not directly on the host.
    _AI_BASH_ALLOWLIST = (
        "pip show ",
        "pip list",
        "pytest ",
        "python -m ",
        "python3 -m ",
        "echo ",
        "cat ",
        "ls ",
    )

    def ae_run_python_snippet(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        code = str(inp["code"])
        cmd = f"python -c {_shlex.quote(code)}"
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, str(root), timeout=30
        )
        if timed_out:
            return "[ERROR] Command timed out after 30s"
        return (stdout + stderr).strip() or "(no output)"

    def ae_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _AI_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        timeout = get_settings().bash_tool_timeout_seconds.get("ai_engineer", 120)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, str(root), timeout=timeout
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr).strip() or "(no output)"

    def ae_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # tool_enhance.md productionization pass, tool #86 (2026-08-24) — this
    # implementation previously ignored its own advertised
    # timeout/summarize schema fields entirely (hardcoded 10s,
    # urllib.request, no summarize support) — a real functionality-
    # parity gap. Now delegates to the shared fetch_url_handler(); see
    # that function's own module docstring.
    def ae_fetch_url(inp: dict[str, Any]) -> str:
        return fetch_url_handler(inp)

    def ae_submit(inp: dict[str, Any]) -> str:
        ai_result.update(inp)
        return "AI engineering result submitted"

    handlers["run_python_snippet"] = ae_run_python_snippet
    handlers["bash"] = ae_bash
    handlers["write_file"] = ae_write_file
    handlers["fetch_url"] = ae_fetch_url
    handlers["submit_ai_result"] = ae_submit
    handlers["_ai_result"] = ai_result
    return handlers


def make_cleanup_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Cleanup Agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    cleanup_result: dict[str, Any] = {}

    _CLEANUP_BASH_ALLOWLIST = (
        "python -m ruff",
        "python -m isort",
        "python -m black",
        "find ",
        "grep ",
        "ls ",
        "cat ",
        "echo ",
        "python -m mypy",
    )

    def cu_dead_code_detect(inp: dict[str, Any]) -> str:
        cu_dir = str(inp.get("directory", "."))
        try:
            from app.repo_tools import ast_engine as _ae

            return _ae.detect_dead_code(str(root / cu_dir))
        except Exception as e:
            return f"[ERROR] {e}"

    def cu_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if any(t in line for t in ("TODO", "FIXME", "HACK", "XXX")):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(none found)"

    def cu_organize_imports(inp: dict[str, Any]) -> str:
        cu_path = str(inp["path"])
        if _is_protected_path(cu_path, repo_path):
            return f"[POLICY DENIED] Protected path: {cu_path}"
        try:
            r = _sp.run(
                ["python", "-m", "isort", cu_path, "--diff"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no changes needed)"
        except Exception as e:
            return f"[ERROR] {e}"

    # moved to app/tools/filesystem/delete_file.py as delete_file_handler
    # — tool_enhance.md productionization pass, tool #17 (2026-08-17).
    def cu_delete_file(inp: dict[str, Any]) -> str:
        return delete_file_handler(root, repo_path, inp)

    def cu_edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        old_s = inp["old_string"]
        new_s = inp["new_string"]
        fp = root / rel
        if not fp.exists():
            return f"[ERROR] File not found: {rel}"
        text = fp.read_text(encoding="utf-8")
        count = text.count(old_s)
        if count == 0:
            return "[ERROR] old_string not found"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        fp.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited: {rel}"

    def cu_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _CLEANUP_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        # Blocker 5 (audit_v1.md 4.5): bare "find " in this allowlist,
        # combined with unsandboxed subprocess.run(shell=True), reproduced
        # the exact `find /workspace -mindepth 1 -delete` case
        # app.policy.sandbox's own docstring cites as the proof case for
        # Docker sandboxing. Route through the same Docker-sandboxed
        # primitive every other bash-shaped tool uses instead of running
        # directly on the host.
        timeout = get_settings().bash_tool_timeout_seconds.get("cleanup", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, str(root), timeout=timeout
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr).strip() or "(no output)"

    def cu_submit(inp: dict[str, Any]) -> str:
        cleanup_result.update(inp)
        return "Cleanup submitted"

    handlers["dead_code_detect"] = cu_dead_code_detect
    handlers["find_todos"] = cu_find_todos
    handlers["organize_imports"] = cu_organize_imports
    handlers["delete_file"] = cu_delete_file
    handlers["edit_file"] = cu_edit_file
    handlers["bash"] = cu_bash
    handlers["submit_cleanup"] = cu_submit
    handlers["_cleanup_result"] = cleanup_result
    return handlers


def make_tech_debt_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Technical Debt Agent."""
    import subprocess as _sp

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    tech_debt_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path`, same relative-traversal-escape finding as
    # pr_/sr_list_functions) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def td_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path`, same relative-traversal-escape finding as
    # sr_list_classes) lives in the shared list_classes_handler()
    # itself; see that function's own module docstring.
    def td_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def td_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if any(t in line for t in ("TODO", "FIXME", "HACK", "XXX")):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(none found)"

    def td_run_linter(inp: dict[str, Any]) -> str:
        td_path = str(inp.get("path", "."))
        try:
            r = _sp.run(
                ["python", "-m", "ruff", "check", td_path, "--output-format=text"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no linting issues)"
        except Exception as e:
            return f"[ERROR] {e}"

    def td_coverage_report(inp: dict[str, Any]) -> str:
        try:
            r = _sp.run(
                ["python", "-m", "pytest", "--co", "-q", "--no-header"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    def td_submit(inp: dict[str, Any]) -> str:
        tech_debt_result.update(inp)
        return "Tech debt analysis submitted"

    handlers["list_functions"] = td_list_functions
    handlers["list_classes"] = td_list_classes
    handlers["find_todos"] = td_find_todos
    handlers["run_linter"] = td_run_linter
    handlers["coverage_report"] = td_coverage_report
    handlers["submit_tech_debt"] = td_submit
    handlers["_tech_debt_result"] = tech_debt_result
    return handlers


# ===========================================================================
# Batch 15 — 34 new tools reaching the 190-tool vision
# ===========================================================================

# -- Git extras --
# moved to app/tools/git/tag.py as GIT_TAG_TOOL —
# tool_enhance.md productionization pass, tool #22 (2026-08-17).
_GIT_LOG_FILE_TOOL: dict[str, Any] = {
    "name": "git_log_file",
    "description": "Show git commit history for a specific file. Returns commits that touched that file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "limit": {
                "type": "integer",
                "description": "Max commits to return (default: 10)",
            },
        },
        "required": ["path"],
    },
}
# moved to app/tools/filesystem/semver_bump.py as SEMVER_BUMP_TOOL —
# tool_enhance.md productionization pass, tool #25 (2026-08-18).
_GIT_STASH_LIST_TOOL: dict[str, Any] = {
    "name": "git_stash_list",
    "description": "List all git stashes with their index and description.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# -- Process / System --
_LIST_PROCESSES_TOOL: dict[str, Any] = {
    "name": "list_processes",
    "description": "List running processes, optionally filtered by name. Returns PID, CPU%, MEM%, command.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Filter by process name (optional)",
            }
        },
        "required": [],
    },
}
_LIST_OPEN_PORTS_TOOL: dict[str, Any] = {
    "name": "list_open_ports",
    "description": "List TCP ports currently listening on this machine.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
_WAIT_FOR_PORT_TOOL: dict[str, Any] = {
    "name": "wait_for_port",
    "description": "Wait until a TCP port is open (useful after starting a server). Returns when port accepts connections or times out.",
    "input_schema": {
        "type": "object",
        "properties": {
            "port": {"type": "integer", "description": "TCP port number"},
            "host": {"type": "string", "description": "Hostname (default: localhost)"},
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default: 30)",
            },
        },
        "required": ["port"],
    },
}
_CHECK_URL_STATUS_TOOL: dict[str, Any] = {
    "name": "check_url_status",
    "description": "Check the HTTP status code of a URL. Returns status code, redirect chain, and response time. Does NOT return body.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to check"}},
        "required": ["url"],
    },
}
_CPU_PROFILE_TOOL: dict[str, Any] = {
    "name": "cpu_profile",
    "description": "Profile a Python script or module with cProfile and return the top N slowest functions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Python command to profile, e.g. 'python -m myapp'",
            },
            "top": {
                "type": "integer",
                "description": "Number of top functions to return (default: 20)",
            },
        },
        "required": ["command"],
    },
}

# -- File ops --
_ZIP_FILES_TOOL: dict[str, Any] = {
    "name": "zip_files",
    "description": "Zip a file or directory into an archive.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "File or directory to zip (relative to repo root)",
            },
            "output": {
                "type": "string",
                "description": "Output .zip file path (default: source + .zip)",
            },
        },
        "required": ["source"],
    },
}
_UNZIP_FILES_TOOL: dict[str, Any] = {
    "name": "unzip_files",
    "description": "Extract a .zip archive to a directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "archive": {
                "type": "string",
                "description": ".zip file path (relative to repo root)",
            },
            "dest": {
                "type": "string",
                "description": "Destination directory (default: archive directory)",
            },
        },
        "required": ["archive"],
    },
}
# moved to app/tools/filesystem/move_file.py as MOVE_FILE_TOOL — tool_enhance.md productionization pass, tool #52 (2026-08-20).
_HASH_FILE_TOOL: dict[str, Any] = {
    "name": "hash_file",
    "description": "Compute the SHA-256 hash of a file. Useful for integrity checking.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"}
        },
        "required": ["path"],
    },
}
_COUNT_LINES_TOOL: dict[str, Any] = {
    "name": "count_lines",
    "description": "Count lines in a file or all files in a directory matching a pattern.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path (relative to repo root)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern for directory mode (e.g. '**/*.py')",
            },
        },
        "required": ["path"],
    },
}

# -- Environment --
_READ_ENV_VAR_TOOL: dict[str, Any] = {
    "name": "read_env_var",
    "description": "Read the value of a specific environment variable from the running process. Returns [NOT SET] if absent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Environment variable name"}
        },
        "required": ["name"],
    },
}
_LIST_ENV_VARS_TOOL: dict[str, Any] = {
    "name": "list_env_vars",
    "description": "List all environment variable NAMES (not values) currently set. Use read_env_var to read a specific value.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
_ENV_DIFF_TOOL: dict[str, Any] = {
    "name": "env_diff",
    "description": "Compare .env.example with .env (or a named env file) to find missing or extra variables.",
    "input_schema": {
        "type": "object",
        "properties": {
            "example": {
                "type": "string",
                "description": "Path to example env file (default: .env.example)",
            },
            "actual": {
                "type": "string",
                "description": "Path to actual env file (default: .env)",
            },
        },
        "required": [],
    },
}

# -- Data format tools --
_JSON_QUERY_TOOL: dict[str, Any] = {
    "name": "json_query",
    "description": "Run a jq expression on a JSON file and return the result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON file path (relative to repo root)",
            },
            "query": {
                "type": "string",
                "description": "jq expression, e.g. '.users[].name'",
            },
        },
        "required": ["path", "query"],
    },
}
_YAML_VALIDATE_TOOL: dict[str, Any] = {
    "name": "yaml_validate",
    "description": (
        "Validate a YAML file for syntax errors. Returns 'valid' or the parse "
        "error with line number. If schema_path (a JSON Schema file, itself "
        "JSON or YAML) is given, also validates the parsed document against "
        "that JSON Schema."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "YAML file path (relative to repo root)",
            },
            "schema_path": {
                "type": "string",
                "description": "Optional: path to a JSON Schema file (.json or .yaml) to validate the document against",
            },
        },
        "required": ["path"],
    },
}
_JSON_VALIDATE_TOOL: dict[str, Any] = {
    "name": "json_validate",
    "description": (
        "Validate a JSON file for syntax errors. Returns 'valid' or the parse "
        "error with position. If schema_path (a JSON Schema file) is given, "
        "also validates the document against that JSON Schema."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON file path (relative to repo root)",
            },
            "schema_path": {
                "type": "string",
                "description": "Optional: path to a JSON Schema file (.json or .yaml) to validate the document against",
            },
        },
        "required": ["path"],
    },
}
_CSV_PREVIEW_TOOL: dict[str, Any] = {
    "name": "csv_preview",
    "description": "Preview the first N rows of a CSV file, showing column names and sample data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "CSV file path (relative to repo root)",
            },
            "rows": {
                "type": "integer",
                "description": "Number of rows to preview (default: 5)",
            },
        },
        "required": ["path"],
    },
}
# AUDIT_Q_BATCH09 §16/§79/§80 gap-closure — real, working handlers for file
# types/inspection capabilities that had zero support before, each following
# the exact pattern of the existing PDF/image/CSV/YAML tools above: stdlib or
# already-pinned dependencies only, single self-contained handler, registered
# alongside the tools it extends.
_XML_VALIDATE_TOOL: dict[str, Any] = {
    "name": "xml_validate",
    "description": "Validate an XML file for well-formedness. Returns 'valid' or the parse error with line number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "XML file path (relative to repo root)",
            }
        },
        "required": ["path"],
    },
}
_READ_NOTEBOOK_TOOL: dict[str, Any] = {
    "name": "read_notebook",
    "description": "Read a Jupyter notebook (.ipynb), returning each cell's type, source, and any text/error output — code and markdown cells in execution order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Notebook file path (relative to repo root)",
            },
            "max_cells": {
                "type": "integer",
                "description": "Maximum number of cells to include (default: 100)",
            },
        },
        "required": ["path"],
    },
}
_PARSE_DOCKERFILE_TOOL: dict[str, Any] = {
    "name": "parse_dockerfile",
    "description": "Parse a Dockerfile into its structural instructions: build stages, base images (FROM), exposed ports, and each instruction with its line number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Dockerfile path (relative to repo root, default: Dockerfile)",
            }
        },
        "required": [],
    },
}
_PARSE_DOCKER_COMPOSE_TOOL: dict[str, Any] = {
    "name": "parse_docker_compose",
    "description": "Parse a docker-compose YAML file into a structural summary: each service's image/build context, exposed ports, volumes, and dependencies.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "docker-compose file path (relative to repo root, default: docker-compose.yml)",
            }
        },
        "required": [],
    },
}
_GITHUB_INSPECT_REPO_TOOL: dict[str, Any] = {
    "name": "github_inspect_repo",
    "description": "Inspect an arbitrary external GitHub repository (not the local checkout) via the public GitHub REST API: metadata (description, default branch, stars, language) and top-level file listing. Works for any public repo; unauthenticated (rate-limited).",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner/org"},
            "repo": {"type": "string", "description": "Repository name"},
            "path": {
                "type": "string",
                "description": "Optional subdirectory to list within the repo (default: repo root)",
            },
        },
        "required": ["owner", "repo"],
    },
}
_OPENAPI_INSPECT_TOOL: dict[str, Any] = {
    "name": "openapi_inspect",
    "description": "Parse a local OpenAPI/Swagger spec (JSON or YAML) and summarize its API surface: title/version, and every path with its HTTP methods, summary, and parameter count.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "OpenAPI/Swagger spec file path (relative to repo root)",
            }
        },
        "required": ["path"],
    },
}

# -- Code / Docs tools --
_GENERATE_DIAGRAM_TOOL: dict[str, Any] = {
    "name": "generate_diagram",
    "description": (
        "Generate a Mermaid diagram. For kind='classDiagram' or 'flowchart', pass "
        "`path` (a real .py file relative to repo root) to get a diagram built from "
        "that file's actual classes/bases (classDiagram) or function call edges "
        "(flowchart) via AST analysis — not a placeholder. Without `path` (or for "
        "kind='sequence'/'erDiagram', which aren't derivable from static analysis "
        "alone), returns a labeled starter template instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What to diagram — components, flow, or relationships",
            },
            "kind": {
                "type": "string",
                "enum": ["flowchart", "sequence", "erDiagram", "classDiagram"],
                "description": "Diagram type (default: flowchart)",
            },
            "path": {
                "type": "string",
                "description": (
                    "Real .py file (relative to repo root) to derive the diagram "
                    "from via AST analysis. Only used by classDiagram/flowchart."
                ),
            },
        },
        "required": ["description"],
    },
}
_SUMMARIZE_OUTPUT_TOOL: dict[str, Any] = {
    "name": "summarize_output",
    "description": (
        "Condense a long piece of text (e.g. a command/log/tool result you just "
        "received) into a short LLM-generated summary — real summarization, "
        "distinct from just truncating the text. Use this instead of pasting a "
        "huge result verbatim into your own next message."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The long text to summarize",
            },
            "focus": {
                "type": "string",
                "description": "Optional: what to focus the summary on (e.g. 'errors only', 'files changed')",
            },
        },
        "required": ["text"],
    },
}
_EXPORT_MARKDOWN_TOOL: dict[str, Any] = {
    "name": "export_markdown",
    "description": "Render a Markdown file to HTML and save it. Returns the output HTML file path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Markdown file path (relative to repo root)",
            },
            "output": {
                "type": "string",
                "description": "Output HTML file path (default: same name + .html)",
            },
        },
        "required": ["path"],
    },
}
_FIND_UNUSED_IMPORTS_TOOL: dict[str, Any] = {
    "name": "find_unused_imports",
    "description": "Find unused imports in Python files using ruff or autoflake. Returns file:line:symbol for each unused import.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to check (default: repo root)",
            },
        },
        "required": [],
    },
}
_DEPS_OUTDATED_TOOL: dict[str, Any] = {
    "name": "deps_outdated",
    "description": "Check for outdated pip or npm dependencies. Returns package name, current version, and latest version.",
    "input_schema": {
        "type": "object",
        "properties": {
            "manager": {
                "type": "string",
                "enum": ["pip", "npm", "auto"],
                "description": "Package manager (default: auto-detect)",
            },
            "directory": {
                "type": "string",
                "description": "Directory to check (default: repo root)",
            },
        },
        "required": [],
    },
}
_CHECK_LICENSE_COMPLIANCE_TOOL: dict[str, Any] = {
    "name": "check_license_compliance",
    "description": (
        "Scan every installed Python package's license against SPDX identifiers "
        "(PEP 639 License-Expression, PyPI trove classifiers, or a short License "
        "metadata field) and classify each as allowed (permissive), review (weak "
        "copyleft — LGPL/MPL), disallowed (strong copyleft — GPL/AGPL/SSPL), or "
        "unknown (no determinable license). Real dependency metadata, not a guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
_LOC_STATS_TOOL: dict[str, Any] = {
    "name": "loc_stats",
    "description": "Lines-of-code statistics for the repo broken down by file extension/language.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory to scan (default: repo root)",
            },
        },
        "required": [],
    },
}

# -- Package management --
# moved to app/tools/execution/npm_install.py as NPM_INSTALL_TOOL — tool_enhance.md productionization pass, tool #53 (2026-08-20).
# moved to app/tools/execution/npm_run.py as NPM_RUN_TOOL — tool_enhance.md productionization pass, tool #54 (2026-08-20).
# moved to app/tools/execution/pip_install.py as PIP_INSTALL_TOOL — tool_enhance.md productionization pass, tool #55 (2026-08-20).
_PIP_LIST_TOOL: dict[str, Any] = {
    "name": "pip_list",
    "description": "List installed Python packages and their versions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Filter packages by name prefix (optional)",
            },
        },
        "required": [],
    },
}

# -- Utilities --
_CREATE_DIRECTORY_TOOL: dict[str, Any] = {
    "name": "create_directory",
    "description": "Create a directory (and any missing parents). Equivalent to mkdir -p.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to create (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}
_HTTP_REQUEST_TOOL: dict[str, Any] = {
    "name": "http_request",
    "description": "Make an HTTP request (GET/POST/PUT/DELETE) with custom headers and body. Returns status code and response body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
            "url": {"type": "string", "description": "Request URL"},
            "headers": {
                "type": "object",
                "description": "Request headers (key-value pairs)",
            },
            "body": {
                "type": "string",
                "description": "Request body (JSON string for POST/PUT)",
            },
        },
        "required": ["method", "url"],
    },
}
_BASE64_ENCODE_TOOL: dict[str, Any] = {
    "name": "base64_encode",
    "description": "Base64-encode a string or a file's contents. Useful for embedding assets or sending binary data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text string to encode (mutually exclusive with path)",
            },
            "path": {
                "type": "string",
                "description": "File path to encode (relative to repo root)",
            },
            "decode": {
                "type": "boolean",
                "description": "If true, decode base64 instead of encoding (default: false)",
            },
        },
        "required": [],
    },
}
_TEMPLATE_RENDER_TOOL: dict[str, Any] = {
    "name": "template_render",
    "description": "Render a Jinja2 template string or file with provided variables. Returns the rendered output.",
    "input_schema": {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": "Template string (mutually exclusive with path)",
            },
            "path": {
                "type": "string",
                "description": "Template file path (relative to repo root)",
            },
            "vars": {
                "type": "object",
                "description": "Variables to inject into the template",
            },
        },
        "required": [],
    },
}

# AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) — "Present options (multi-
# choice): NO — not found | Confirmation payload is binary approve/deny
# only." / "Recommend choices: PARTIAL | free-text ... no structured
# recommendation field." _confirm()'s binary approve/deny interrupt() stays
# untouched (every existing dangerous-operation gate keeps working exactly
# as before) — this is a genuinely different decision shape: not "should I
# do this Y/N" but "which of these N valid paths should I take", so it's a
# new tool (ChatAgent._confirm_with_options(), same real interrupt()/
# Command(resume=...) pause primitive as _confirm(), see chat_agent.py) not
# a change to the existing one.
_ASK_HUMAN_TO_CHOOSE_TOOL: dict[str, Any] = {
    "name": "ask_human_to_choose",
    "description": (
        "Use when there are multiple genuinely valid ways to proceed and a human should "
        "pick one — not for a plain yes/no decision (dangerous actions like delete/git push "
        "already pause for approval automatically; don't call this for those). Pauses this "
        "turn until the human selects one option; their choice is returned as this tool's "
        "result so you can act on it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific decision the human needs to make.",
            },
            "options": {
                "type": "array",
                "description": "2-5 distinct choices, each with a stable id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
                "minItems": 2,
            },
            "recommended_option": {
                "type": "string",
                "description": "id of the option you'd recommend, if any — the human sees this but still decides.",
            },
        },
        "required": ["question", "options"],
    },
}

CHAT_TOOLS = READ_ONLY_TOOLS + [
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _CHAT_BASH_TOOL,
    _APPEND_FILE_TOOL,
    _RENAME_FILE_TOOL,
    _COPY_FILE_TOOL,
    _DELETE_FILE_TOOL,
    _GIT_COMMIT_TOOL,
    _GIT_BRANCH_TOOL,
    _GIT_CHECKOUT_TOOL,
    _GIT_STASH_TOOL,
    _GIT_PULL_TOOL,
    _GIT_FETCH_TOOL,
    _GIT_RESTORE_TOOL,
    _GIT_PUSH_TOOL,
    _CREATE_BRANCH_TOOL,
    _RUN_TESTS_TOOL,
    _RUN_LINTER_TOOL,
    _SUBMIT_RESULT_TOOL,
    # Batch 1 — File/Editing extras
    _FIND_FILE_TOOL,
    _FORMAT_FILE_TOOL,
    _ORGANIZE_IMPORTS_TOOL,
    _INSERT_AT_LINE_TOOL,
    _REPLACE_FUNCTION_TOOL,
    _DELETE_LINES_TOOL,
    _APPLY_PATCH_TOOL_DEF,
    _COMPARE_FILES_TOOL,
    _SYNC_FILES_TOOL,
    # Batch 2 — Terminal extras
    _RUN_BACKGROUND_TOOL_DEF,
    _KILL_PROCESS_TOOL,
    _LIST_BACKGROUND_PROCESSES_TOOL,
    _RUN_PARALLEL_COMMANDS_TOOL,
    _RUN_PYTHON_SNIPPET_TOOL,
    _RUN_MAKE_TOOL,
    _FETCH_URL_TOOL,
    # Batch 3 — Git extras
    _GIT_MERGE_TOOL,
    _PARSE_MERGE_CONFLICTS_TOOL,
    _EXPLAIN_MERGE_CONFLICT_TOOL,
    _RESOLVE_MERGE_CONFLICT_TOOL,
    _GIT_RESET_TOOL,
    _GIT_WORKTREE_TOOL,
    _CREATE_PR_TOOL,
    _GENERATE_COMMIT_MSG_TOOL,
    _REVIEW_DIFF_TOOL,
    _INSPECT_GITHUB_REPO_TOOL,
    _INSPECT_OPENAPI_SPEC_TOOL,
    # Batch 4 — Testing extras
    _RUN_SINGLE_TEST_TOOL,
    _COVERAGE_REPORT_TOOL,
    _TYPE_CHECK_TOOL,
    # Batch 5 — Code Intelligence
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    # Batch 6 — Debug
    _READ_LOGS_TOOL,
    _ANALYZE_ERROR_TOOL,
    # Batch 7 — Database
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    # Batch 8 — Docker
    _DOCKER_PS_TOOL,
    _DOCKER_LOGS_TOOL,
    _DOCKER_EXEC_TOOL,
    _DOCKER_COMPOSE_TOOL,
    _DIAGNOSE_DEPLOYMENT_FAILURE_TOOL,
    # Batch 9 — Security
    _SECRETS_SCAN_TOOL,
    # Batch 10 — AST Engine
    _PARSE_AST_TOOL,
    _IMPORT_GRAPH_TOOL,
    _CALL_GRAPH_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _RENAME_SYMBOL_TOOL,
    # Batch 11 — Git extras
    _GIT_REBASE_TOOL,
    _GIT_CHERRY_PICK_TOOL,
    # Batch 12 — Terminal extras
    _READ_OUTPUT_TOOL,
    _RUN_NODE_TOOL,
    _RUN_SCRIPT_TOOL,
    _DOCKER_BUILD_TOOL,
    _DOCKER_RESTART_TOOL,
    # Batch 13 — Smart search
    _FIND_ROUTE_TOOL,
    _FIND_API_TOOL,
    _FIND_SQL_TOOL,
    _FIND_TEST_TOOL,
    _FIND_CONFIG_TOOL,
    # Batch 14 — Monitoring
    _CPU_USAGE_TOOL,
    _MEMORY_USAGE_TOOL,
    _DISK_USAGE_TOOL,
    _HEALTH_CHECK_TOOL,
    _TASK_PROGRESS_TOOL,
    # Batch 15 — Editing extras
    _REPLACE_CLASS_TOOL,
    _UNDO_CHANGES_TOOL,
    _GENERATE_PATCH_TOOL,
    # Batch 16 — DB extras
    _EXPLAIN_QUERY_TOOL,
    _RUN_MIGRATION_TOOL,
    _SEED_DATABASE_TOOL,
    # Day 3A — Browser tools
    _BROWSER_OPEN_TOOL,
    _BROWSER_NAVIGATE_TOOL,
    _BROWSER_SCREENSHOT_TOOL,
    _BROWSER_READ_DOM_TOOL,
    _BROWSER_CLICK_TOOL,
    _BROWSER_TYPE_TOOL,
    _BROWSER_CLOSE_TOOL,
    # Day 3B — Memory tools
    _MEMORY_READ_TOOL,
    _MEMORY_WRITE_TOOL,
    _DECISION_LOG_APPEND_TOOL,
    _TASK_HISTORY_QUERY_TOOL,
    _KNOWN_ISSUES_READ_TOOL,
    _KNOWN_ISSUES_WRITE_TOOL,
    # AUDIT_Q_BATCH15 §74/§113 gap-closure — preference memory
    RECORD_PREFERENCE_TOOL,
    # Day 3C — Planning + docs tools
    _ESTIMATE_COMPLEXITY_TOOL,
    _SUMMARIZE_FOLDER_TOOL,
    _GENERATE_API_DOCS_TEXT_TOOL,
    _MERMAID_FROM_SCHEMA_TOOL,
    # Day 3G — External integrations (GitHub/Linear/Slack — not MCP protocol)
    _GITHUB_CREATE_ISSUE_TOOL,
    _GITHUB_LIST_PRS_TOOL,
    _GITHUB_COMMENT_TOOL,
    _LINEAR_CREATE_ISSUE_TOOL,
    _SLACK_SEND_MESSAGE_TOOL,
    # Day 2 Gap — Smart search
    _FIND_QUEUE_TOOL,
    _FIND_WORKER_TOOL,
    # Day 2 Gap — Advanced editing
    _INSERT_BEFORE_TOOL,
    _INSERT_AFTER_TOOL,
    _DELETE_BLOCK_TOOL,
    # Day 2 Gap — Documentation generation
    _GENERATE_CHANGELOG_TOOL,
    _SUMMARIZE_REPO_TOOL,
    _GENERATE_RELEASE_NOTES_TOOL,
    # Day 2 Gap — File types
    _READ_PDF_TOOL,
    _READ_IMAGE_TOOL,
    # Day 2 Gap — GitHub PR
    _GITHUB_CREATE_PR_TOOL,
    # Batch 15 — 34 new tools reaching the 190-tool vision
    # Git extras
    _GIT_TAG_TOOL,
    _GIT_LOG_FILE_TOOL,
    _SEMVER_BUMP_TOOL,
    _GIT_STASH_LIST_TOOL,
    # Process / System
    _LIST_PROCESSES_TOOL,
    _LIST_OPEN_PORTS_TOOL,
    _WAIT_FOR_PORT_TOOL,
    _CHECK_URL_STATUS_TOOL,
    _CPU_PROFILE_TOOL,
    # File ops
    _ZIP_FILES_TOOL,
    _UNZIP_FILES_TOOL,
    _MOVE_FILE_TOOL,
    _HASH_FILE_TOOL,
    _COUNT_LINES_TOOL,
    # Environment
    _READ_ENV_VAR_TOOL,
    _LIST_ENV_VARS_TOOL,
    _ENV_DIFF_TOOL,
    # Data format
    _JSON_QUERY_TOOL,
    _YAML_VALIDATE_TOOL,
    _JSON_VALIDATE_TOOL,
    _CSV_PREVIEW_TOOL,
    # AUDIT_Q_BATCH09 §16/§79/§80 — file type + inspection gap-closure
    _XML_VALIDATE_TOOL,
    _READ_NOTEBOOK_TOOL,
    _PARSE_DOCKERFILE_TOOL,
    _PARSE_DOCKER_COMPOSE_TOOL,
    _GITHUB_INSPECT_REPO_TOOL,
    _OPENAPI_INSPECT_TOOL,
    # Code / Docs
    _GENERATE_DIAGRAM_TOOL,
    _SUMMARIZE_OUTPUT_TOOL,
    _EXPORT_MARKDOWN_TOOL,
    _FIND_UNUSED_IMPORTS_TOOL,
    _DEPS_OUTDATED_TOOL,
    _CHECK_LICENSE_COMPLIANCE_TOOL,
    _LOC_STATS_TOOL,
    # Package management
    _NPM_INSTALL_TOOL,
    _NPM_RUN_TOOL,
    _PIP_INSTALL_TOOL,
    _PIP_LIST_TOOL,
    # Utilities
    _CREATE_DIRECTORY_TOOL,
    _HTTP_REQUEST_TOOL,
    _BASE64_ENCODE_TOOL,
    _TEMPLATE_RENDER_TOOL,
    # AUDIT_Q_BATCH07 §13 — Human interaction
    _ASK_HUMAN_TO_CHOOSE_TOOL,
]


def task_history_query(inp: dict[str, Any]) -> str:
    """Query recent task history from task_logs. Standalone (not repo-scoped) so any
    agent can reuse it, not just chat."""
    db_url = getattr(get_settings(), "database_url", "")
    if not db_url:
        return "[ERROR] DATABASE_URL not set"
    limit = int(inp.get("limit", 20))
    status_filter = inp.get("status")
    sql = "SELECT id, status, created_at FROM task_logs"
    if status_filter:
        sql += f" WHERE status = '{status_filter}'"
    sql += f" ORDER BY created_at DESC LIMIT {limit};"
    try:
        r = subprocess.run(
            ["psql", db_url, "-c", sql, "--no-psqlrc"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (r.stdout + r.stderr).strip() or "(no output)"
    except Exception as e:
        return f"[ERROR] {e}"


def make_chat_handlers(repo_path: str, session: Any = None) -> dict[str, Any]:
    """
    Full-access handlers for the interactive chat agent.
    session: ChatSession instance — used to request user confirmation for dangerous ops.
    If session is None, dangerous commands are blocked rather than confirmed.
    """
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    # Per-session background process registry — isolated so one session cannot
    # kill or read output from a different session's background process.
    _session_bg_procs: dict[int, "subprocess.Popen[str]"] = {}

    # ---- edit_file ----
    # moved to app/tools/filesystem/edit_file.py as edit_file_handler —
    # tool_enhance.md productionization pass, tool #13 (2026-08-17).
    def edit_file(inp: dict[str, Any]) -> str:
        return edit_file_handler(root, repo_path, inp)

    # ---- write_file ----
    # moved to app/tools/filesystem/write_file.py as write_file_handler —
    # tool_enhance.md productionization pass, tool #12 (2026-08-17).
    def write_file(inp: dict[str, Any]) -> str:
        return write_file_handler(root, repo_path, inp)

    # ---- git_diff ----
    # tool_enhance.md productionization pass, tool #84 (2026-08-24) — the
    # real fix (ZERO `--` separator before `file` — a silent
    # arbitrary-file-write via git's own --output=<path> flag, same
    # class as tool #80's git_show) lives in the shared
    # git_diff_handler() itself; see that function's own module
    # docstring.
    def git_diff(inp: dict[str, Any]) -> str:
        return git_diff_handler(root, inp)

    # ---- bash (with confirmation for dangerous commands) ----
    def bash(inp: dict[str, Any]) -> str:
        command = inp["command"]
        # Gap-closure (Audit 05 fix, SEC-05-006): this used to accept an
        # LLM-controlled cwd override (`inp.get("cwd") or repo_path`) with no
        # validation it stayed inside repo_path — widening the escape
        # surface beyond even the `cd &&` chaining issue (SEC-05-005),
        # since the tool call itself could just set cwd directly. Every
        # other bash-capable handler in this file hardcodes its working
        # directory; this one now does too.
        cwd = repo_path

        # Gap-closure (Audit 05 fix, SEC-05-005): rejected before the
        # confirmation flow below — a command trying to leave the sandbox
        # entirely is a different, non-overridable class of problem from a
        # destructive-but-in-scope command a human can knowingly approve.
        boundary_policy = check_command_stays_in_boundary(command, repo_path)
        if not boundary_policy.allowed:
            return f"[POLICY DENIED] {boundary_policy.reason}"

        if _is_dangerous_command(command):
            # Gap-closure (Audit 05 fix, SEC-05-007): a human "approve" click
            # used to be able to run ANY denylisted command, including
            # irreversible/catastrophic ones (rm -rf, dd if=, mkfs, a fork
            # bomb) — no different from an unconfirmed one once approved.
            # These now stay hard-blocked regardless of confirmation.
            from app.policy.engine import is_command_override_eligible

            if not is_command_override_eligible(command):
                return (
                    f"[BLOCKED] This command is irreversible/catastrophic and "
                    f"cannot be run even with confirmation: {command!r}"
                )
            # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
            # real gap found: the session.request_confirmation() plumbing
            # below this used to exist for the case where session IS
            # provided, but `session` is never non-None for any real
            # caller of make_chat_handlers() (grepped every real call
            # site in the repo — none pass one). Unlike git_push/
            # undo_changes/etc. below, "bash" genuinely IS reachable by
            # many real one-shot agents (bug_fix, backend_dev, ...), so
            # this fail-closed behavior is real, live, and correct — a
            # one-shot agent must never autonomously run a flagged-
            # dangerous command with no human present to ask. Simplified
            # to state that plainly instead of dead async plumbing that
            # could never execute.
            return (
                f"[BLOCKED] This command is potentially destructive: {command!r}\n"
                "No interactive confirmation channel is available in this "
                "execution context. Refusing to run."
            )

        try:
            timeout = get_settings().bash_tool_timeout_seconds.get("chat", 120)
            stdout, stderr, returncode, timed_out = _run_bash_command(
                command, cwd, timeout=timeout
            )
            if timed_out:
                return f"[ERROR] Command timed out after {timeout}s"
            output = stdout + (("\n[stderr]\n" + stderr) if stderr else "")
            if returncode != 0:
                output += f"\n[exit code: {returncode}]"
            return output.strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- delete_file ----
    # moved to app/tools/filesystem/delete_file.py as delete_file_handler
    # — tool_enhance.md productionization pass, tool #17 (2026-08-17).
    def delete_file(inp: dict[str, Any]) -> str:
        return delete_file_handler(root, repo_path, inp)

    # git_push moved to app/tools/git/push.py as git_push_handler —
    # tool_enhance.md productionization pass, tool #4 (2026-08-16).

    # ---- create_branch ----
    def create_branch(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        checkout = inp.get("checkout", True)
        from_branch = str(inp.get("from_branch", ""))
        cb_error = validate_create_branch_inputs(name, from_branch)
        if cb_error:
            return cb_error

        # Create the branch
        create_cmd = ["git", "branch", name]
        if from_branch:
            create_cmd.append(from_branch)

        try:
            result = subprocess.run(
                create_cmd, cwd=repo_path, capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"[ERROR] {result.stderr.strip()}"
        except Exception as e:
            return f"[ERROR] {e}"

        if checkout:
            try:
                result = subprocess.run(
                    ["git", "checkout", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return (
                        f"Branch created but checkout failed: {result.stderr.strip()}"
                    )
            except Exception as e:
                return f"Branch created but checkout failed: {e}"
            return f"Created and switched to branch: {name}"

        return f"Created branch: {name}"

    # ---- submit_result ----
    chat_result: dict[str, Any] = {}

    def submit_result(inp: dict[str, Any]) -> str:
        chat_result.update(inp)
        return f"Result submitted: {inp.get('status', 'done')}"

    # ---- append_file ----
    # moved to app/tools/filesystem/append_file.py as append_file_handler
    # — tool_enhance.md productionization pass, tool #26 (2026-08-18).
    def append_file(inp: dict[str, Any]) -> str:
        return append_file_handler(root, repo_path, inp)

    # ---- rename_file ----
    # moved to app/tools/filesystem/rename_file.py — this now delegates to the shared rename_file_handler()
    def rename_file(inp: dict[str, Any]) -> str:
        return rename_file_handler(root, repo_path, inp)

    # ---- copy_file ----
    def copy_file(inp: dict[str, Any]) -> str:
        import shutil

        from_rel = str(inp["from_path"])
        to_rel = str(inp["to_path"])
        if _is_protected_path(from_rel, repo_path):
            return f"[POLICY DENIED] Protected source: {from_rel}"
        if _is_protected_path(to_rel, repo_path):
            return f"[POLICY DENIED] Protected destination: {to_rel}"
        src = root / from_rel
        dst = root / to_rel
        if not src.exists():
            return f"[ERROR] Source not found: {from_rel}"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            return f"Copied {from_rel} → {to_rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_commit ---- (moved to app/tools/git/commit.py — this now delegates to the shared, hardened stage_and_commit())
    def git_commit(inp: dict[str, Any]) -> str:
        message = str(inp["message"])
        files: list[str] = inp.get("files", [])
        return stage_and_commit(repo_path, message, files)

    # ---- git_branch ----
    def git_branch(inp: dict[str, Any]) -> str:
        action = str(inp.get("action", "list"))
        name = inp.get("name", "")
        try:
            if action == "list":
                r = subprocess.run(
                    ["git", "branch", "-a"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout or "(no branches)"
            elif action == "create":
                if not name:
                    return "[ERROR] name required for create"
                r = subprocess.run(
                    ["git", "branch", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout + r.stderr or f"Branch '{name}' created"
            elif action == "delete":
                if not name:
                    return "[ERROR] name required for delete"
                r = subprocess.run(
                    ["git", "branch", "-d", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout + r.stderr or f"Branch '{name}' deleted"
            return f"[ERROR] Unknown action: {action}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_checkout ----
    def git_checkout(inp: dict[str, Any]) -> str:
        target = str(inp["target"])
        file_path = str(inp.get("file", ""))
        gc_error = validate_git_checkout_inputs(target, file_path)
        if gc_error:
            return gc_error
        cmd = ["git", "checkout", target]
        if file_path:
            cmd = ["git", "checkout", target, "--", file_path]
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            out = (r.stdout + r.stderr).strip()
            return out or f"Checked out {target}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_stash ----
    # moved to app/tools/git/stash.py — this now calls the shared validate_git_stash_action() first
    def git_stash(inp: dict[str, Any]) -> str:
        action = str(inp.get("action", "push"))
        stash_error = validate_git_stash_action(action)
        if stash_error:
            return stash_error
        message = inp.get("message", "")
        cmd = ["git", "stash"]
        if action == "push":
            if message:
                cmd += ["push", "-m", message]
        elif action == "pop":
            cmd.append("pop")
        elif action == "list":
            cmd.append("list")
        elif action == "drop":
            cmd.append("drop")
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            return (r.stdout + r.stderr).strip() or f"git stash {action} complete"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_pull ---- (moved to app/tools/git/pull.py — this now calls the shared validate_git_pull_inputs() first)
    def git_pull(inp: dict[str, Any]) -> str:
        remote = str(inp.get("remote", "origin"))
        branch = str(inp.get("branch", ""))
        pull_error = validate_git_pull_inputs(remote, branch)
        if pull_error:
            return pull_error
        rebase = bool(inp.get("rebase", False))
        cmd = ["git", "pull"]
        if rebase:
            cmd.append("--rebase")
        cmd.append(remote)
        if branch:
            cmd.append(branch)
        try:
            r = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
            )
            return (r.stdout + r.stderr).strip() or "Pull complete"
        except subprocess.TimeoutExpired:
            return "[ERROR] git pull timed out after 60s"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_fetch ----
    def git_fetch(inp: dict[str, Any]) -> str:
        remote = str(inp.get("remote", "origin"))
        prune = bool(inp.get("prune", False))
        cmd = ["git", "fetch", remote]
        if prune:
            cmd.append("--prune")
        try:
            r = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
            )
            return (r.stdout + r.stderr).strip() or "Fetch complete"
        except subprocess.TimeoutExpired:
            return "[ERROR] git fetch timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_restore ----
    # moved to app/tools/git/restore.py — like undo_changes_h, this has no real,
    # safely-confirmable one-shot caller (grepped: git_restore is in zero
    # agent's allowed_tools), so it's blocked outright instead of silently
    # executing an unconfirmed irreversible discard.
    def git_restore(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        return "[BLOCKED] git_restore requires interactive session for safety confirmation"

    # ---- run_tests ----
    # moved to app/tools/execution/run_tests.py as run_tests_handler —
    # tool_enhance.md productionization pass, tool #16 (2026-08-17).
    def run_tests(inp: dict[str, Any]) -> str:
        return run_tests_handler(
            repo_path, inp, activate_snippet=_venv_activate_snippet()
        )

    # ---- run_linter ----
    def run_linter(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        tool = str(inp.get("tool", "all"))
        path = str(inp.get("path", ""))
        fix = bool(inp.get("fix", False))
        results: list[str] = []
        qpath = _shlex.quote(path) if path else ""

        if tool in ("ruff", "all"):
            target = qpath or f"{repo_path}"
            fix_flag = "--fix" if fix else ""
            cmd = f"cd {repo_path} && {_venv_activate_snippet()} && python -m ruff check {target} {fix_flag} 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            ruff_out = (r.stdout + r.stderr)[:2000] or "clean"
            ruff_summary = parse_diagnostic_summary(ruff_out, "ruff")
            results.append(
                f"=== ruff ==={f' {ruff_summary}' if ruff_summary else ''}\n{ruff_out}"
            )

        if tool in ("mypy", "all"):
            target = qpath or f"{repo_path}"
            cmd = f"cd {repo_path} && {_venv_activate_snippet()} && python -m mypy {target} --ignore-missing-imports 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=90
            )
            mypy_out = (r.stdout + r.stderr)[:2000] or "clean"
            mypy_summary = parse_diagnostic_summary(mypy_out, "mypy")
            results.append(
                f"=== mypy ==={f' {mypy_summary}' if mypy_summary else ''}\n{mypy_out}"
            )

        if tool in ("tsc", "all"):
            web = str(root.parent / "apps" / "web")
            cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=90
            )
            tsc_out = (r.stdout + r.stderr)[:2000] or "clean"
            tsc_summary = parse_diagnostic_summary(tsc_out, "tsc")
            results.append(
                f"=== tsc ==={f' {tsc_summary}' if tsc_summary else ''}\n{tsc_out}"
            )

        if tool == "black":
            target = qpath or f"{repo_path}"
            cmd = f"cd {repo_path} && {_venv_activate_snippet()} && python -m black {'--check' if not fix else ''} {target} 2>&1 | head -50"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            results.append(f"=== black ===\n{(r.stdout + r.stderr)[:2000]}")

        return "\n\n".join(results) if results else f"[ERROR] Unknown linter: {tool}"

    # =========================================================================
    # BATCH 1 — File / Editing extras
    # =========================================================================

    def find_file(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        ff_dir = str(inp.get("directory", ""))
        ff_root = root / ff_dir if ff_dir else root
        try:
            r = subprocess.run(
                [
                    "find",
                    str(ff_root),
                    "-name",
                    name,
                    "-not",
                    "-path",
                    "*/node_modules/*",
                    "-not",
                    "-path",
                    "*/__pycache__/*",
                    "-not",
                    "-path",
                    "*/.git/*",
                    "-not",
                    "-path",
                    "*/.venv/*",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            found = [ln for ln in r.stdout.splitlines() if ln.strip()]
            if not found:
                return f"(no files matching '{name}')"
            rel_paths = []
            for p in found[:100]:
                try:
                    rel_paths.append(str(Path(p).relative_to(root)))
                except ValueError:
                    rel_paths.append(p)
            return "\n".join(rel_paths)
        except subprocess.TimeoutExpired:
            return "[ERROR] find timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def format_file(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        rel = str(inp["path"])
        formatter = str(inp.get("formatter", "auto"))
        fmt_target = root / rel
        if not fmt_target.exists():
            return f"[ERROR] File not found: {rel}"
        if formatter == "auto":
            formatter = "ruff" if fmt_target.suffix == ".py" else "prettier"
        activate = (
            _venv_activate_snippet()
        )  # cwd=repo_path is passed to subprocess.run below
        quoted_target = _shlex.quote(str(fmt_target))
        if formatter in ("ruff", "black"):
            cmd = f"{activate} && python -m {formatter} format {quoted_target} 2>&1"
        elif formatter == "prettier":
            cmd = f"cd {repo_path} && npx prettier --write {quoted_target} 2>&1"
        else:
            return f"[ERROR] Unknown formatter: {formatter}"
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30
        )
        return (r.stdout + r.stderr).strip() or f"Formatted {rel}"

    def organize_imports(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        rel = str(inp["path"])
        oi_target = root / rel
        if not oi_target.exists():
            return f"[ERROR] File not found: {rel}"
        activate = (
            _venv_activate_snippet()
        )  # cwd=repo_path is passed to subprocess.run below
        cmd = (
            f"{activate} && python -m ruff check --select I --fix "
            f"{_shlex.quote(str(oi_target))} 2>&1"
        )
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=repo_path, timeout=30
        )
        return (r.stdout + r.stderr).strip() or f"Imports organized in {rel}"

    # moved to app/tools/filesystem/insert_at_line.py — this now delegates to the shared insert_at_line_handler()
    def insert_at_line(inp: dict[str, Any]) -> str:
        return insert_at_line_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/replace_function.py as
    # replace_function_handler — tool_enhance.md productionization pass,
    # tool #24 (2026-08-18).
    def replace_function(inp: dict[str, Any]) -> str:
        return replace_function_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/delete_lines.py as
    # delete_lines_handler — tool_enhance.md productionization pass,
    # tool #34 (2026-08-18).
    def delete_lines(inp: dict[str, Any]) -> str:
        return delete_lines_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/apply_patch.py as apply_patch_handler
    # — tool_enhance.md productionization pass, tool #27 (2026-08-18).
    def apply_patch(inp: dict[str, Any]) -> str:
        return apply_patch_handler(repo_path, inp)

    def compare_files(inp: dict[str, Any]) -> str:
        rel_a = str(inp["path_a"])
        rel_b = str(inp["path_b"])
        context = int(inp.get("context", 3))
        cf_a = root / rel_a
        cf_b = root / rel_b
        if not cf_a.exists():
            return f"[ERROR] File not found: {rel_a}"
        if not cf_b.exists():
            return f"[ERROR] File not found: {rel_b}"
        r = subprocess.run(
            ["diff", f"-U{context}", str(cf_a), str(cf_b)],
            capture_output=True,
            text=True,
        )
        return r.stdout[:8000] or "Files are identical"

    # tool_enhance.md productionization pass, tool #64 (2026-08-22) — the
    # real fix (chat_agent.py's own dispatch had zero worktree-boundary
    # validation, this implementation already had it) lives in the
    # shared sync_files_handler() itself; see that function's own module
    # docstring.
    def sync_files(inp: dict[str, Any]) -> str:
        return sync_files_handler(root, repo_path, inp)

    # =========================================================================
    # BATCH 2 — Terminal extras
    # =========================================================================

    # tool_enhance.md productionization pass, tool #58 (2026-08-20) — the
    # real fix (Docker sandboxing) lives in process_manager.spawn() itself,
    # already the shared implementation this call delegates to; see that
    # function's own docstring, including a retroactive kill_process
    # (tool #49) fix found along the way. `cwd` is now validated here
    # since it gets bind-mounted read-write into the sandbox.
    def run_background(inp: dict[str, Any]) -> str:
        from app.fleet import process_manager as _pm

        rb_command = str(inp["command"])
        rb_cwd = str(inp.get("cwd") or repo_path)
        rb_policy = check_command(rb_command)
        if not rb_policy.allowed:
            return f"[POLICY DENIED] {rb_policy.reason}"
        rb_cwd_error = validate_run_background_cwd(rb_cwd, repo_path)
        if rb_cwd_error:
            return rb_cwd_error
        rb_wait_for = inp.get("wait_for_pids")
        rb_wait_pids = [int(p) for p in rb_wait_for] if rb_wait_for else None
        return _pm.spawn(
            rb_command, rb_cwd, _session_bg_procs, wait_for_pids=rb_wait_pids
        )

    # tool_enhance.md productionization pass, tool #49 (2026-08-20) — the
    # real fix (an ownership gate) lives in process_manager.kill() itself,
    # already the shared implementation this call delegates to; see that
    # function's own docstring.
    def kill_process(inp: dict[str, Any]) -> str:
        from app.fleet import process_manager as _pm

        kp_pid = int(inp["pid"])
        kp_sig_name = str(inp.get("signal", "TERM"))
        return _pm.kill(kp_pid, kp_sig_name, _session_bg_procs)

    def list_background_processes_h(inp: dict[str, Any]) -> str:
        from app.fleet import process_manager as _pm

        return _pm.format_tracked(_session_bg_procs)

    # run_parallel_commands_h removed — tool_enhance.md productionization
    # pass, tool #9 (2026-08-16). Now registered directly against
    # run_parallel_commands_handler (app/tools/execution/parallel.py),
    # which also closes a real cwd-boundary-escape finding (see that
    # module's docstring) shared with the generic bash tool.

    # moved to app/tools/execution/python_snippet.py as
    # run_python_snippet_handler — tool_enhance.md productionization pass,
    # tool #14 (2026-08-17).
    def run_python_snippet(inp: dict[str, Any]) -> str:
        return run_python_snippet_handler(
            repo_path, inp, activate_snippet=_venv_activate_snippet()
        )

    # tool_enhance.md productionization pass, tool #59 (2026-08-22) — the
    # real fix lives in the shared run_make_handler() itself; see that
    # function's own module docstring.
    def run_make(inp: dict[str, Any]) -> str:
        return run_make_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #86 (2026-08-24) — the
    # real fix (an unbounded LLM-controlled timeout, flagged back in
    # tool #14, plus an uncaught ValueError on a non-numeric timeout)
    # lives in the shared fetch_url_handler() itself; see that
    # function's own module docstring.
    def fetch_url(inp: dict[str, Any]) -> str:
        return fetch_url_handler(inp)

    # =========================================================================
    # BATCH 3 — Git extras
    # =========================================================================

    # moved to app/tools/git/merge.py — this now calls the shared validate_git_merge_inputs() first
    def git_merge(inp: dict[str, Any]) -> str:
        gm_branch = str(inp["branch"])
        gm_error = validate_git_merge_inputs(gm_branch)
        if gm_error:
            return gm_error
        gm_no_ff = bool(inp.get("no_ff", False))
        gm_squash = bool(inp.get("squash", False))
        gm_msg = str(inp.get("message", ""))
        gm_cmd = ["git", "merge"]
        if gm_no_ff:
            gm_cmd.append("--no-ff")
        if gm_squash:
            gm_cmd.append("--squash")
        if gm_msg:
            gm_cmd += ["-m", gm_msg]
        gm_cmd.append(gm_branch)
        try:
            r = subprocess.run(
                gm_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            output = (r.stdout + r.stderr).strip() or f"Merged {gm_branch}"
            if r.returncode == 0:
                return output
            # Gap-closure Day 51 — repo research
            # (repos/cline/apps/vscode/.../mergeWorktree.ts): detect real
            # conflicted files via `git diff --name-only --diff-filter=U`
            # rather than trusting stdout text alone, so a caller has an
            # exact file list to run parse_merge_conflicts against.
            diff_r = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            conflicted = [f for f in diff_r.stdout.strip().split("\n") if f]
            if conflicted:
                files_list = ", ".join(conflicted)
                return (
                    f"[CONFLICT] Merge of {gm_branch} has real conflicts in "
                    f"{len(conflicted)} file(s): {files_list}. Use "
                    f"parse_merge_conflicts on each, then resolve_merge_conflict "
                    f"to resolve, then git_commit to finish the merge.\n{output}"
                )
            return f"[ERROR] {output}"
        except Exception as e:
            return f"[ERROR] {e}"

    def parse_merge_conflicts(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        target = Path(repo_path) / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        hunks = _parse_conflict_markers(text)
        if not hunks:
            return f"No conflict markers found in {rel}."
        import json as _json

        return _json.dumps({"path": rel, "hunks": hunks}, indent=2)

    def explain_merge_conflict(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        target = Path(repo_path) / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        hunks = _parse_conflict_markers(text)
        if not hunks:
            return f"No conflict markers found in {rel}."
        return _llm_explain_conflict_hunks(rel, hunks)

    def resolve_merge_conflict(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        target = Path(repo_path) / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        raw_resolutions = inp.get("resolutions") or []
        if not raw_resolutions:
            return "[ERROR] resolutions is required — at least one {index, choice}"
        resolutions: dict[int, dict[str, Any]] = {}
        for entry in raw_resolutions:
            idx = int(entry["index"])
            choice = str(entry.get("choice", ""))
            if choice == "custom" and "custom_content" not in entry:
                return f"[ERROR] hunk {idx}: choice='custom' requires custom_content"
            resolutions[idx] = entry
        text = target.read_text(encoding="utf-8")
        new_text, applied, unresolved = _apply_conflict_resolutions(text, resolutions)
        target.write_text(new_text, encoding="utf-8")
        if unresolved:
            return (
                f"Resolved {len(applied)} hunk(s) in {rel}. "
                f"Still unresolved (markers left intact): {unresolved}"
            )
        return f"Resolved all {len(applied)} conflict hunk(s) in {rel}."

    # git_reset moved to app/tools/git/reset.py as git_reset_handler —
    # tool_enhance.md productionization pass, tool #5 (2026-08-16).

    # moved to app/tools/git/worktree.py — validates inputs and blocks the
    # unconfirmable "add" action (like undo_changes_h/git_restore, this has no
    # real, safely-confirmable one-shot caller for a destructive/impactful action)
    def git_worktree(inp: dict[str, Any]) -> str:
        gw_action = str(inp.get("action", "list"))
        gw_path = str(inp.get("path", ""))
        gw_branch = str(inp.get("branch", ""))
        gw_error = validate_git_worktree_inputs(gw_action, gw_path, gw_branch)
        if gw_error:
            return gw_error
        try:
            if gw_action == "list":
                r = subprocess.run(
                    ["git", "worktree", "list"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout or "(no worktrees)"
            elif gw_action == "add":
                return (
                    "[BLOCKED] git_worktree add requires interactive session "
                    "for safety confirmation — it writes a new checkout to "
                    "an arbitrary filesystem path."
                )
            elif gw_action == "remove":
                r = subprocess.run(
                    ["git", "worktree", "remove", "--", gw_path],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return (r.stdout + r.stderr).strip() or f"Removed worktree at {gw_path}"
            return f"[ERROR] Unknown action: {gw_action}"
        except Exception as e:
            return f"[ERROR] {e}"

    def create_pr(inp: dict[str, Any]) -> str:
        # Moved to app/tools/git/pull_request.py::create_pr_handler —
        # tool_enhance.md productionization pass, tool #2 (2026-08-15).
        # This thin wrapper is what keeps every existing
        # `handlers["create_pr"](...)` call site (all real tests, every
        # agent) working unchanged. See that module's TOOL PATH MIGRATION
        # REPORT for the full consumer audit.
        return create_pr_handler(repo_path, inp)

    def generate_commit_msg(inp: dict[str, Any]) -> str:
        gcm_staged = bool(inp.get("staged_only", True))
        diff_args = ["diff", "--cached"] if gcm_staged else ["diff"]
        stat_args = diff_args + ["--stat"]
        r_stat = subprocess.run(
            ["git"] + stat_args, cwd=repo_path, capture_output=True, text=True
        )
        r_diff = subprocess.run(
            ["git"] + diff_args, cwd=repo_path, capture_output=True, text=True
        )
        stat = r_stat.stdout.strip()
        diff = r_diff.stdout[:3000]
        if not stat:
            return "[ERROR] No staged changes. Stage files with git_commit or git add first."
        generated = _llm_generate_commit_message(stat, diff)
        if generated:
            return (
                f"=== Generated commit message ===\n{generated}\n\n"
                f"=== Changed files ===\n{stat}\n\n"
                f"=== Diff (truncated to 3000 chars) ===\n{diff}"
            )
        return (
            f"=== Changed files ===\n{stat}\n\n"
            f"=== Diff (truncated to 3000 chars) ===\n{diff}\n\n"
            "Analyze the diff above and write a conventional commit message:\n"
            "Format: <type>(<scope>): <description>\n"
            "Types: feat, fix, docs, refactor, test, chore, style, perf"
        )

    def review_diff(inp: dict[str, Any]) -> str:
        rd_staged = bool(inp.get("staged_only", True))
        rd_base = str(inp.get("base", "")).strip()
        if rd_base:
            diff_args = ["diff", f"{rd_base}...HEAD"]
        elif rd_staged:
            diff_args = ["diff", "--cached"]
        else:
            diff_args = ["diff"]
        r_stat = subprocess.run(
            ["git"] + diff_args + ["--stat"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        r_diff = subprocess.run(
            ["git"] + diff_args, cwd=repo_path, capture_output=True, text=True
        )
        stat = r_stat.stdout.strip()
        diff = r_diff.stdout[:6000]
        if not stat:
            return "[ERROR] No changes to review for the given scope."
        review = _llm_review_diff(stat, diff)
        if review:
            return f"=== Changed files ===\n{stat}\n\n=== Review ===\n{review}"
        return (
            f"[ERROR] Review generation unavailable — raw diff below.\n\n"
            f"=== Changed files ===\n{stat}\n\n=== Diff ===\n{diff}"
        )

    # =========================================================================
    # BATCH 4 — Testing extras
    # =========================================================================

    # tool_enhance.md productionization pass, tool #62 (2026-08-22) — the
    # real fix (a `file` worktree-escape validator, shared with
    # chat_agent.py's dispatch which also had a real shell-injection bug)
    # lives in the shared run_single_test_handler() itself; see that
    # function's own module docstring.
    def run_single_test(inp: dict[str, Any]) -> str:
        return run_single_test_handler(
            repo_path, inp, activate_snippet=_venv_activate_snippet()
        )

    def coverage_report(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        cov_path = str(inp.get("path", "backend/tests/"))
        cov_source = str(inp.get("source", "backend/app/"))
        cov_min = inp.get("min_coverage")
        activate = (
            _venv_activate_snippet()
        )  # cwd=repo_path is passed to subprocess.run below
        min_flag = ""
        if cov_min:
            try:
                min_flag = f"--cov-fail-under={int(cov_min)}"
            except (TypeError, ValueError):
                return f"[ERROR] min_coverage must be a number, got: {cov_min!r}"
        cmd = (
            f"{activate} && python -m pytest {_shlex.quote(cov_path)} "
            f"--cov={_shlex.quote(cov_source)} --cov-report=term-missing {min_flag} "
            f"--tb=no -q 2>&1 | tail -50"
        )
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=180,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] Coverage run timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def type_check(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        tc_path = str(inp.get("path", ""))
        tc_strict = bool(inp.get("strict", False))
        tc_lang = str(inp.get("language", "both"))
        activate = (
            _venv_activate_snippet()
        )  # cwd=repo_path is passed to subprocess.run below
        tc_results: list[str] = []
        if tc_lang in ("python", "both"):
            py_path = _shlex.quote(tc_path) if tc_path else "backend/"
            strict_flag = "--strict" if tc_strict else "--ignore-missing-imports"
            cmd = (
                f"{activate} && python -m mypy {py_path} {strict_flag} 2>&1 | head -60"
            )
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=90,
            )
            tc_mypy_out = (r.stdout + r.stderr)[:3000] or "clean"
            tc_mypy_summary = parse_diagnostic_summary(tc_mypy_out, "mypy")
            tc_results.append(
                f"=== mypy ==={f' {tc_mypy_summary}' if tc_mypy_summary else ''}\n{tc_mypy_out}"
            )
        if tc_lang in ("typescript", "both"):
            web = str(root.parent / "apps" / "web")
            cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -60"
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=90
            )
            tc_tsc_out = (r.stdout + r.stderr)[:3000] or "clean"
            tc_tsc_summary = parse_diagnostic_summary(tc_tsc_out, "tsc")
            tc_results.append(
                f"=== tsc ==={f' {tc_tsc_summary}' if tc_tsc_summary else ''}\n{tc_tsc_out}"
            )
        return "\n\n".join(tc_results) if tc_results else "[ERROR] No language selected"

    # =========================================================================
    # BATCH 5 — Code Intelligence
    # =========================================================================

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation and an uncaught PermissionError, same class as tool
    # #76's analyze_file) lives in the shared list_functions_handler()
    # itself; see that function's own module docstring.
    def list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation and an uncaught PermissionError, same class as tool
    # #76's analyze_file/tool #82's list_functions) lives in the
    # shared list_classes_handler() itself; see that function's own
    # module docstring.
    def list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def find_function_body(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        ffb_name = str(inp["function_name"])
        ffb_fp = root / rel
        if not ffb_fp.exists():
            return f"[ERROR] File not found: {rel}"
        ffb_lines = ffb_fp.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        ffb_start: int | None = None
        ffb_base = 0
        for ffb_i, ffb_line in enumerate(ffb_lines):
            s = ffb_line.strip()
            if s.startswith(f"def {ffb_name}(") or s.startswith(
                f"async def {ffb_name}("
            ):
                ffb_start = ffb_i
                ffb_base = len(ffb_line) - len(ffb_line.lstrip())
                break
        if ffb_start is None:
            return f"[ERROR] Function '{ffb_name}' not found in {rel}"
        ffb_end = len(ffb_lines)
        for ffb_j in range(ffb_start + 1, len(ffb_lines)):
            ffb_jline = ffb_lines[ffb_j]
            if ffb_jline.strip() == "":
                continue
            ffb_jind = len(ffb_jline) - len(ffb_jline.lstrip())
            if (
                ffb_jind <= ffb_base
                and ffb_jline.strip()
                and not ffb_jline.strip().startswith(("@", "#"))
            ):
                ffb_end = ffb_j
                break
        body = "".join(ffb_lines[ffb_start:ffb_end])
        return f"=== {ffb_name} (lines {ffb_start + 1}-{ffb_end}) ===\n{body}"

    # =========================================================================
    # BATCH 6 — Debug tools
    # =========================================================================

    def read_logs(inp: dict[str, Any]) -> str:
        rl_path = str(inp.get("path", ""))
        rl_lines = int(inp.get("lines", 50))
        rl_level = str(inp.get("level", "all"))
        out = ""
        if rl_path and ("/" in rl_path or rl_path.endswith(".log")):
            log_file = (
                root / rl_path if not Path(rl_path).is_absolute() else Path(rl_path)
            )
            if log_file.exists():
                r = subprocess.run(
                    ["tail", f"-{rl_lines}", str(log_file)],
                    capture_output=True,
                    text=True,
                )
                out = r.stdout
            else:
                return f"[ERROR] Log file not found: {rl_path}"
        elif rl_path:
            r = subprocess.run(
                ["journalctl", "-u", rl_path, f"-n{rl_lines}", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            out = r.stdout or r.stderr
        else:
            log_dirs = [root / "logs", root / "backend" / "logs", Path("/tmp")]
            found: list[Path] = []
            for ld in log_dirs:
                if ld.exists():
                    found.extend(ld.glob("*.log"))
            if not found:
                return "(no log files found — specify a path or service name)"
            newest = max(found, key=lambda p: p.stat().st_mtime)
            r = subprocess.run(
                ["tail", f"-{rl_lines}", str(newest)], capture_output=True, text=True
            )
            out = f"From {newest}:\n" + r.stdout
        if rl_level != "all":
            filtered = [
                line for line in out.splitlines() if rl_level.upper() in line.upper()
            ]
            out = "\n".join(filtered)
        return out[:5000] or "(no log entries)"

    def analyze_error(inp: dict[str, Any]) -> str:
        ae_error = str(inp["error"])
        ae_lines = ae_error.strip().splitlines()
        exception_line = ""
        for ae_line in reversed(ae_lines):
            if any(
                x in ae_line for x in ("Error:", "Exception:", "Warning:", "Traceback")
            ):
                exception_line = ae_line
                break
        frames: list[str] = []
        ae_i = 0
        while ae_i < len(ae_lines):
            ae_line = ae_lines[ae_i]
            if ae_line.strip().startswith("File ") and "line " in ae_line:
                if not any(
                    x in ae_line for x in ("site-packages", ".venv", "lib/python")
                ):
                    code_line = (
                        ae_lines[ae_i + 1].strip() if ae_i + 1 < len(ae_lines) else ""
                    )
                    frames.append(f"  {ae_line.strip()}\n    → {code_line}")
                ae_i += 2
            else:
                ae_i += 1
        ae_result = ["=== Error Analysis ==="]
        if exception_line:
            ae_result.append(f"Exception: {exception_line.strip()}")
        if frames:
            ae_result.append(f"\nRelevant frames ({len(frames)}):")
            ae_result.extend(frames[-5:])
        ae_low = ae_error.lower()
        suggestions: list[str] = []
        if "modulenotfounderror" in ae_low or "importerror" in ae_low:
            suggestions.append(
                "→ Missing dependency — run: pip install -r requirements.txt"
            )
        elif "attributeerror" in ae_low:
            suggestions.append(
                "→ Object doesn't have this attribute — check spelling and type"
            )
        elif "typeerror" in ae_low:
            suggestions.append("→ Wrong argument type/count — check function signature")
        elif "keyerror" in ae_low:
            suggestions.append(
                "→ Dictionary key not found — use .get() or check key exists"
            )
        elif "filenotfounderror" in ae_low:
            suggestions.append(
                "→ Path doesn't exist — verify path and working directory"
            )
        elif "connectionrefusederror" in ae_low or "connection refused" in ae_low:
            suggestions.append(
                "→ Service not running — check if DB/Redis/backend is started"
            )
        elif "syntaxerror" in ae_low:
            suggestions.append(
                "→ Python syntax error — check brackets, colons, indentation"
            )
        elif "valueerror" in ae_low:
            suggestions.append("→ Invalid value — validate input before passing it")
        if suggestions:
            ae_result.append("\nSuggestions:")
            ae_result.extend(suggestions)
        return "\n".join(ae_result)

    # =========================================================================
    # BATCH 7 — Database tools
    # =========================================================================

    # moved to app/tools/database/sql.py as run_sql_handler —
    # tool_enhance.md productionization pass, tool #15 (2026-08-17).
    def run_sql(inp: dict[str, Any]) -> str:
        rs_settings = get_settings()
        rs_db_url = str(getattr(rs_settings, "database_url", "") or "")
        return run_sql_handler(rs_db_url, inp)

    def inspect_schema(inp: dict[str, Any]) -> str:
        is_table = str(inp.get("table", ""))
        is_settings = get_settings()
        is_db_url = getattr(is_settings, "database_url", None)
        if not is_db_url:
            return "[ERROR] DATABASE_URL not configured"
        if is_table:
            is_query = (
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                f"WHERE table_name = '{is_table}' ORDER BY ordinal_position"
            )
        else:
            is_query = (
                "SELECT table_name, pg_size_pretty(pg_total_relation_size(table_name::regclass)) AS size "
                "FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        try:
            r = subprocess.run(
                ["psql", str(is_db_url), "-c", is_query, "--no-password"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr)[:5000] or "(empty schema)"
        except FileNotFoundError:
            return "[ERROR] psql not found"
        except Exception as e:
            return f"[ERROR] {e}"

    # =========================================================================
    # BATCH 8 — Docker tools
    # =========================================================================

    def docker_ps(inp: dict[str, Any]) -> str:
        show_all = bool(inp.get("all", False))
        docker_cmd = [
            "docker",
            "ps",
            "--format",
            "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}",
        ]
        if show_all:
            docker_cmd.append("-a")
        try:
            r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=10)
            return (r.stdout + r.stderr)[:3000] or "(no containers)"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_logs(inp: dict[str, Any]) -> str:
        dl_container = str(inp["container"])
        dl_lines = int(inp.get("lines", 50))
        try:
            r = subprocess.run(
                ["docker", "logs", "--tail", str(dl_lines), dl_container],
                capture_output=True,
                text=True,
                timeout=15,
            )
            raw = (r.stdout + r.stderr)[:5000]
            if not raw:
                return "(no logs)"
            return _summarize_docker_log_patterns(raw) + raw
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_exec(inp: dict[str, Any]) -> str:
        de_container = str(inp["container"])
        de_command = str(inp["command"])
        de_policy = check_command(de_command)
        if not de_policy.allowed:
            return f"[POLICY DENIED] {de_policy.reason}"
        de_risk = _docker_container_risk_reason(de_container)
        if de_risk:
            return f"[POLICY DENIED] {de_risk}"
        try:
            r = subprocess.run(
                ["docker", "exec", de_container, "sh", "-c", de_command],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_compose(inp: dict[str, Any]) -> str:
        dc_action = str(inp["action"])
        dc_services: list[str] = list(inp.get("services") or [])
        dc_detach = bool(inp.get("detach", True))
        dc_cmd = ["docker", "compose"]
        if dc_action == "up":
            # "up" creates/starts containers from whatever docker-compose.yml
            # currently sits in the repo — including one this same agent
            # could have just written via write_file, with no restriction on
            # privileged:/pid: host/cap_add/host mounts. docker_exec's own
            # risk-inspection guard only ever sees a container *after* it
            # exists; this is the actual creation step.
            #
            # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
            # real gap found: the confirmation attempt here used
            # session.request_confirmation(), but `session` is never
            # non-None for any real caller of make_chat_handlers() (grepped
            # every real call site in the repo — none pass one; only tests
            # construct a fake session). docker_agent, a real, registered
            # one-shot agent, genuinely has docker_compose in its
            # allowed_tools — so 'up' was a live, permanently-broken dead
            # end for it (every other action still worked). Fixed with the
            # same fail-closed, config-driven gate as create_pr_require_approval
            # (tool #2's second pass) — the honest fix for this handler
            # tier, which has no per-call human-approval channel at all,
            # rather than an unreachable pseudo-confirmation.
            if get_settings().docker_compose_up_require_approval:
                return (
                    "[POLICY DENIED] docker_compose('up') requires human "
                    "approval, and this execution context has no per-call "
                    "approval channel available (see Settings."
                    "docker_compose_up_require_approval). Use the "
                    "interactive chat agent instead, which gates this "
                    "behind a real confirmation prompt."
                )

            dc_cmd.append("up")
            if dc_detach:
                dc_cmd.append("-d")
        elif dc_action in ("down", "restart", "build", "ps", "pull"):
            dc_cmd.append(dc_action)
        elif dc_action == "logs":
            dc_cmd += ["logs", "--tail=50"]
        else:
            return f"[ERROR] Unknown action: {dc_action}"
        dc_cmd.extend(dc_services)
        try:
            r = subprocess.run(
                dc_cmd, cwd=repo_path, capture_output=True, text=True, timeout=120
            )
            return (r.stdout + r.stderr)[
                :5000
            ] or f"docker compose {dc_action} complete"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except subprocess.TimeoutExpired:
            return f"[ERROR] docker compose {dc_action} timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def diagnose_deployment_failure(inp: dict[str, Any]) -> str:
        dd_container = str(inp.get("container", "")).strip()
        dd_lines = int(inp.get("lines", 100))
        parts: list[str] = []
        ps_r = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--format",
                "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        parts.append(
            "=== docker ps -a ===\n" + (ps_r.stdout or ps_r.stderr or "(no containers)")
        )
        if dd_container:
            logs_r = subprocess.run(
                ["docker", "logs", "--tail", str(dd_lines), dd_container],
                capture_output=True,
                text=True,
                timeout=15,
            )
            raw_logs = (logs_r.stdout + logs_r.stderr)[:6000]
            parts.append(
                f"=== docker logs --tail {dd_lines} {dd_container} ===\n"
                + (
                    _summarize_docker_log_patterns(raw_logs) + raw_logs
                    if raw_logs
                    else "(no logs)"
                )
            )
            inspect_r = subprocess.run(
                ["docker", "inspect", dd_container],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if inspect_r.returncode == 0:
                import json as _json

                try:
                    data = _json.loads(inspect_r.stdout)
                    state = (data[0] if data else {}).get("State", {})
                    inspect_summary = {
                        "Status": state.get("Status"),
                        "ExitCode": state.get("ExitCode"),
                        "Error": state.get("Error"),
                        "OOMKilled": state.get("OOMKilled"),
                        "RestartCount": (data[0] if data else {}).get("RestartCount"),
                        "StartedAt": state.get("StartedAt"),
                        "FinishedAt": state.get("FinishedAt"),
                    }
                    parts.append(
                        "=== docker inspect (State) ===\n"
                        + _json.dumps(inspect_summary, indent=2)
                    )
                except Exception:
                    parts.append("=== docker inspect ===\n" + inspect_r.stdout[:2000])
            else:
                parts.append(
                    f"[ERROR] docker inspect {dd_container} failed: "
                    f"{(inspect_r.stderr or '')[:500]}"
                )
        context = "\n\n".join(parts)
        diagnosis = _llm_diagnose_deployment_failure(context)
        return f"{context}\n\n=== Diagnosis ===\n{diagnosis}"

    # =========================================================================
    # BATCH 9 — Security tools
    # =========================================================================

    def secrets_scan(inp: dict[str, Any]) -> str:
        # AUDIT_Q_BATCH11 §96 "Secret scanning" — delegates to the same
        # canonical scanner sec_secrets_scan() (make_security_reviewer_
        # handlers) and _scan_content_for_secrets (pre-commit) now share,
        # instead of this handler's own independently-maintained regex list
        # and grep-subprocess implementation (also more portable: no
        # dependency on a `grep` binary being on PATH).
        ss_dir = str(inp.get("directory", ""))
        return _scan_directory_for_secrets(root, ss_dir)

    handlers["edit_file"] = edit_file
    handlers["write_file"] = write_file
    handlers["git_diff"] = git_diff
    handlers["bash"] = bash
    handlers["append_file"] = append_file
    handlers["rename_file"] = rename_file
    handlers["copy_file"] = copy_file
    handlers["delete_file"] = delete_file
    handlers["git_commit"] = git_commit
    handlers["git_branch"] = git_branch
    handlers["git_checkout"] = git_checkout
    handlers["git_stash"] = git_stash
    handlers["git_pull"] = git_pull
    handlers["git_fetch"] = git_fetch
    handlers["git_restore"] = git_restore
    handlers["git_push"] = git_push_handler
    handlers["create_branch"] = create_branch
    handlers["run_tests"] = run_tests
    handlers["run_linter"] = run_linter
    handlers["submit_result"] = submit_result
    # Batch 1
    handlers["find_file"] = find_file
    handlers["format_file"] = format_file
    handlers["organize_imports"] = organize_imports
    handlers["insert_at_line"] = insert_at_line
    handlers["replace_function"] = replace_function
    handlers["delete_lines"] = delete_lines
    handlers["apply_patch"] = apply_patch
    handlers["compare_files"] = compare_files
    handlers["sync_files"] = sync_files
    # Batch 2
    handlers["run_background"] = run_background
    handlers["kill_process"] = kill_process
    handlers["list_background_processes"] = list_background_processes_h
    handlers["run_parallel_commands"] = lambda inp: run_parallel_commands_handler(
        repo_path, inp
    )
    handlers["run_python_snippet"] = run_python_snippet
    handlers["run_make"] = run_make
    handlers["fetch_url"] = fetch_url
    # AUDIT_Q_BATCH09 §79/80 gap-closure — web_search is standalone (see its
    # own docstring: "so any agent can reuse it, not just the research
    # agent"), but was only ever wired into make_research_handlers. Any
    # agent built on make_chat_handlers (e.g. spike_agent) can now declare
    # it in allowed_tools and get a real handler, matching fetch_url above.
    handlers["web_search"] = web_search_handler
    # Batch 3
    handlers["git_merge"] = git_merge
    handlers["parse_merge_conflicts"] = parse_merge_conflicts
    handlers["explain_merge_conflict"] = explain_merge_conflict
    handlers["resolve_merge_conflict"] = resolve_merge_conflict
    handlers["git_reset"] = lambda inp: git_reset_handler(repo_path, inp)
    handlers["git_worktree"] = git_worktree
    handlers["create_pr"] = create_pr
    handlers["generate_commit_msg"] = generate_commit_msg
    handlers["review_diff"] = review_diff
    handlers["inspect_github_repo"] = inspect_github_repo
    handlers["inspect_openapi_spec"] = inspect_openapi_spec
    # Batch 4
    handlers["run_single_test"] = run_single_test
    handlers["coverage_report"] = coverage_report
    handlers["type_check"] = type_check
    # Batch 5
    handlers["list_functions"] = list_functions
    handlers["list_classes"] = list_classes
    handlers["find_function_body"] = find_function_body
    # Batch 6
    handlers["read_logs"] = read_logs
    handlers["analyze_error"] = analyze_error
    # Batch 7
    handlers["run_sql"] = run_sql
    handlers["inspect_schema"] = inspect_schema
    # Batch 8
    handlers["docker_ps"] = docker_ps
    handlers["docker_logs"] = docker_logs
    handlers["docker_exec"] = docker_exec
    handlers["docker_compose"] = docker_compose
    handlers["diagnose_deployment_failure"] = diagnose_deployment_failure
    # Batch 9
    handlers["secrets_scan"] = secrets_scan
    handlers["_chat_result"] = chat_result

    # =========================================================================
    # BATCH 10 — AST Engine (parse_ast, import_graph, call_graph, dead_code_detect,
    #             circular_dep_detect, rename_symbol)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def parse_ast_h(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    def import_graph_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import build_import_graph

        return build_import_graph(str(root / str(inp["path"])))

    def call_graph_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import build_call_graph

        return build_call_graph(
            str(root / str(inp["path"])), str(inp.get("function_name", ""))
        )

    def dead_code_detect_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import detect_dead_code

        dcd_d = str(inp.get("directory", ""))
        return detect_dead_code(str(root / dcd_d) if dcd_d else repo_path)

    def circular_dep_detect_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import detect_circular_imports

        cdd_d = str(inp.get("directory", ""))
        return detect_circular_imports(str(root / cdd_d) if cdd_d else repo_path)

    def rename_symbol_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import rename_symbol as _rsym

        rs_d = str(inp.get("directory", ""))
        rsym_error = validate_rename_symbol_directory(rs_d, repo_path)
        if rsym_error:
            return f"[POLICY DENIED] {rsym_error}"
        return _rsym(
            str(inp["old_name"]),
            str(inp["new_name"]),
            str(root / rs_d) if rs_d else repo_path,
            str(inp.get("file_pattern", "*.py")),
            confirm_large_batch=bool(inp.get("confirm_large_batch", False)),
        )

    handlers["parse_ast"] = parse_ast_h
    handlers["import_graph"] = import_graph_h
    handlers["call_graph"] = call_graph_h
    handlers["dead_code_detect"] = dead_code_detect_h
    handlers["circular_dep_detect"] = circular_dep_detect_h
    handlers["rename_symbol"] = rename_symbol_h

    # =========================================================================
    # BATCH 11 — Git extras (git_rebase, git_cherry_pick)
    # =========================================================================

    # moved to app/tools/git/rebase.py — this now calls the shared validate_git_rebase_inputs() first
    def git_rebase_h(inp: dict[str, Any]) -> str:
        grb_onto = str(inp["onto"])
        grb_error = validate_git_rebase_inputs(grb_onto)
        if grb_error:
            return grb_error
        if bool(inp.get("interactive", False)):
            return "[BLOCKED] Interactive rebase requires a TTY. Run 'git rebase -i' manually in a terminal."
        try:
            r = subprocess.run(
                ["git", "rebase", grb_onto],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] git rebase timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_cherry_pick_h(inp: dict[str, Any]) -> str:
        gcp_hash = str(inp["commit_hash"])
        gcp_error = validate_git_cherry_pick_inputs(gcp_hash)
        if gcp_error:
            return gcp_error
        gcp_cmd = ["git", "cherry-pick"]
        if bool(inp.get("no_commit", False)):
            gcp_cmd.append("--no-commit")
        gcp_cmd.append(gcp_hash)
        try:
            r = subprocess.run(
                gcp_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["git_rebase"] = git_rebase_h
    handlers["git_cherry_pick"] = git_cherry_pick_h

    # =========================================================================
    # BATCH 12 — Terminal extras (read_output, run_node, run_script, docker_build, docker_restart)
    # =========================================================================

    def _read_stream_nonblocking(stream: Any, max_bytes: int = 8192) -> str | None:
        """Best-effort non-blocking read of up to max_bytes from a pipe.

        fcntl-based O_NONBLOCK (the POSIX approach) doesn't exist on Windows
        pipe file descriptors — found via real execution (ModuleNotFoundError:
        'fcntl'), which broke every test that reaches this handler. On
        Windows, run the blocking read() in a daemon thread and give it a
        short timeout instead: if data arrives in time we return it, if not
        we abandon the thread (harmless — it's a daemon thread that will
        simply finish, its result unused, whenever the target process next
        writes or exits) and report no output yet, matching this function's
        existing "(no output yet ...)" behavior for an idle process.
        """
        if sys.platform != "win32":
            import fcntl as _fcntl

            fd = stream.fileno()
            fl = _fcntl.fcntl(fd, _fcntl.F_GETFL)
            _fcntl.fcntl(fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
            try:
                chunk: str | None = stream.read(max_bytes)
                return chunk
            except (IOError, BlockingIOError, TypeError):
                return None

        import threading

        result: dict[str, str | None] = {"data": None}

        def _reader() -> None:
            try:
                result["data"] = stream.read(max_bytes)
            except Exception:
                pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout=0.1)
        return result["data"]

    def read_output_h(inp: dict[str, Any]) -> str:
        from app.fleet import process_manager as _pm

        ro_pid = int(inp["pid"])
        ro_max = int(inp.get("lines", 50))
        return _pm.read_output(
            ro_pid, ro_max, _session_bg_procs, _read_stream_nonblocking
        )

    # tool_enhance.md productionization pass, tool #60 (2026-08-22) — the
    # real fix (an unbounded timeout clamp) lives in the shared
    # run_node_handler() itself; see that function's own module docstring.
    def run_node_h(inp: dict[str, Any]) -> str:
        return run_node_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #61 (2026-08-22) — the
    # real fix lives in the shared run_script_handler() itself; see that
    # function's own module docstring.
    def run_script_h(inp: dict[str, Any]) -> str:
        return run_script_handler(root, repo_path, inp)

    def docker_build_h(inp: dict[str, Any]) -> str:
        dbld_tag = str(inp["tag"])
        dbld_context = str(inp.get("context", "."))
        dbld_df = inp.get("dockerfile")
        dbld_error = validate_docker_build_inputs(
            dbld_context, str(dbld_df) if dbld_df else None, repo_path
        )
        if dbld_error:
            return f"[POLICY DENIED] {dbld_error}"
        dbld_ctx_path = str(root / dbld_context) if dbld_context != "." else repo_path
        dbld_cmd = ["docker", "build", "-t", dbld_tag]
        if dbld_df:
            dbld_cmd += ["-f", str(root / str(dbld_df))]
        dbld_cmd.append(dbld_ctx_path)
        try:
            r = subprocess.run(
                dbld_cmd, cwd=repo_path, capture_output=True, text=True, timeout=600
            )
            result = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                result += f"\n[exit {r.returncode}]"
            return result or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] docker build timed out after 600s"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_restart_h(inp: dict[str, Any]) -> str:
        drst_name = str(inp["container"])
        try:
            r = subprocess.run(
                ["docker", "restart", drst_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or f"Restarted {drst_name}"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["read_output"] = read_output_h
    handlers["run_node"] = run_node_h
    handlers["run_script"] = run_script_h
    handlers["docker_build"] = docker_build_h
    handlers["docker_restart"] = docker_restart_h

    # =========================================================================
    # BATCH 13 — Smart search (find_route, find_api, find_sql, find_test, find_config)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #90 (2026-08-24) — this
    # implementation was already correct; unified onto the shared
    # find_route_handler() for maintainability (2 sibling
    # implementations elsewhere had a severe field-name mismatch); see
    # that function's own module docstring.
    def find_route_h(inp: dict[str, Any]) -> str:
        return find_route_handler(root, inp)

    # tool_enhance.md productionization pass, tool #89 (2026-08-24) — the
    # real fix (ZERO validation of `name` — a flag-injection bug, same
    # class as tool #69's search_code) lives in the shared
    # find_api_handler() itself; see that function's own module
    # docstring.
    def find_api_h(inp: dict[str, Any]) -> str:
        return find_api_handler(root, inp)

    def find_sql_h(inp: dict[str, Any]) -> str:
        fsql_kw = str(inp.get("keyword", "")).upper()
        # Use -i for case-insensitive, -w for whole-word; avoid (?i) inline flag (not ERE)
        if fsql_kw:
            fsql_pat = fsql_kw
            fsql_flags = ["-rn", "-i", "-w"]
        else:
            fsql_pat = r"SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE"
            fsql_flags = ["-rn", "-i", "-E"]
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        try:
            r = subprocess.run(
                ["grep"]
                + fsql_flags
                + [
                    fsql_pat,
                    repo_path,
                    "--include=*.py",
                    "--include=*.sql",
                    "--include=*.ts",
                ]
                + exclude,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (
                r.stdout[:5000]
                if r.stdout.strip()
                else "No SQL statements found in codebase"
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def find_test_h(inp: dict[str, Any]) -> str:
        ftest_fn = str(inp["function_name"])
        patterns = [
            f"def test_{ftest_fn}",
            f"def test.*{ftest_fn}",
            f"test.*[\"'].*{ftest_fn}",
        ]
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        ftest_out: list[str] = []
        for pt in patterns:
            try:
                r = subprocess.run(
                    [
                        "grep",
                        "-rn",
                        "-E",
                        pt,
                        repo_path,
                        "--include=*.py",
                        "--include=*.ts",
                    ]
                    + exclude,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if r.stdout.strip():
                    ftest_out.append(r.stdout[:2000])
            except Exception:
                pass
        return (
            "\n".join(ftest_out)[:5000]
            if ftest_out
            else f"No tests found for '{ftest_fn}'"
        )

    def find_config_h(inp: dict[str, Any]) -> str:
        fcfg_key = str(inp["key"])
        patterns_to_try = [fcfg_key, fcfg_key.upper(), fcfg_key.lower()]
        include_globs = [
            "--include=*.env*",
            "--include=.env*",
            "--include=*.yaml",
            "--include=*.yml",
            "--include=*.toml",
            "--include=*.cfg",
            "--include=*.ini",
            "--include=config.py",
            "--include=settings.py",
        ]
        exclude = [
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=__pycache__",
        ]
        fcfg_out: list[str] = []
        seen: set[str] = set()
        for pt in patterns_to_try:
            try:
                r = subprocess.run(
                    ["grep", "-rn", pt, repo_path] + include_globs + exclude,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                for ln in r.stdout.splitlines():
                    if ln not in seen:
                        seen.add(ln)
                        fcfg_out.append(ln)
            except Exception:
                pass
        return (
            "\n".join(fcfg_out)[:5000]
            if fcfg_out
            else f"'{fcfg_key}' not found in config files"
        )

    handlers["find_route"] = find_route_h
    handlers["find_api"] = find_api_h
    handlers["find_sql"] = find_sql_h
    handlers["find_test"] = find_test_h
    handlers["find_config"] = find_config_h

    # =========================================================================
    # BATCH 14 — Monitoring (cpu_usage, memory_usage, disk_usage, health_check, task_progress)
    # =========================================================================

    def cpu_usage_h(inp: dict[str, Any]) -> str:
        try:
            proc_stat = Path("/proc/stat")
            if proc_stat.exists():
                lines = proc_stat.read_text().splitlines()
                cpu_line = lines[0] if lines else ""
                fields = cpu_line.split()
                if len(fields) >= 5:
                    total = sum(int(f) for f in fields[1:])
                    idle = int(fields[4])
                    used_pct = round((total - idle) / total * 100, 1) if total else 0
                    return f"CPU: {used_pct}% used  (raw: {cpu_line})"
            r = subprocess.run(
                ["top", "-bn1"], capture_output=True, text=True, timeout=5
            )
            for ln in r.stdout.splitlines():
                if "Cpu" in ln or "cpu" in ln:
                    return f"CPU: {ln.strip()}"
            return "(could not read CPU usage)"
        except Exception as e:
            return f"[ERROR] {e}"

    def memory_usage_h(inp: dict[str, Any]) -> str:
        try:
            mem_info = Path("/proc/meminfo")
            if mem_info.exists():
                rows = mem_info.read_text().splitlines()[:8]
                return "\n".join(rows)
            r = subprocess.run(
                ["free", "-h"], capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() or "(no memory info)"
        except Exception as e:
            return f"[ERROR] {e}"

    def disk_usage_h(inp: dict[str, Any]) -> str:
        import shutil as _shu

        dsk_path = str(inp.get("path", "")) or repo_path
        try:
            u = _shu.disk_usage(dsk_path)
            gb = 1024**3
            pct = round(u.used / u.total * 100, 1) if u.total else 0
            return (
                f"Disk usage for {dsk_path}:\n"
                f"  Total: {u.total / gb:.1f} GB\n"
                f"  Used:  {u.used / gb:.1f} GB  ({pct}%)\n"
                f"  Free:  {u.free / gb:.1f} GB"
            )
        except Exception as e:
            return f"[ERROR] {e}"

    def health_check_h(inp: dict[str, Any]) -> str:
        hc_svc = str(inp.get("service", "all"))
        settings = get_settings()
        hc_results: list[str] = []
        if hc_svc in ("all", "backend"):
            hc_port = getattr(settings, "port", 8000)
            try:
                r = subprocess.run(
                    [
                        "curl",
                        "-s",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        f"http://localhost:{hc_port}/health",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                code = r.stdout.strip()
                hc_results.append(
                    f"Backend (:{hc_port}/health): {'✅ UP' if code == '200' else f'⚠️ HTTP {code}'}"
                )
            except Exception:
                hc_port2 = getattr(settings, "port", 8000)
                hc_results.append(f"Backend (:{hc_port2}/health): ❌ unreachable")
        if hc_svc in ("all", "db"):
            db_url = getattr(settings, "database_url", "")
            if db_url:
                try:
                    r = subprocess.run(
                        ["pg_isready", "-d", db_url],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    hc_results.append(
                        f"Database: {'✅ UP' if r.returncode == 0 else '❌ DOWN'}"
                    )
                except Exception:
                    hc_results.append("Database: ❓ pg_isready not available")
            else:
                hc_results.append("Database: (DATABASE_URL not configured)")
        return "\n".join(hc_results) if hc_results else "No services checked"

    def task_progress_h(inp: dict[str, Any]) -> str:
        tprog_task_id = inp.get("task_id")
        tprog_limit = int(inp.get("limit", 10))
        settings = get_settings()
        tp_db = getattr(settings, "database_url", "")
        if not tp_db:
            return "[ERROR] DATABASE_URL not set"
        if tprog_task_id is not None:
            sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks WHERE id = {int(tprog_task_id)} LIMIT 1;"
        else:
            sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks ORDER BY created_at DESC LIMIT {tprog_limit};"
        try:
            r = subprocess.run(
                ["psql", tp_db, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (r.stdout + r.stderr).strip() or "(no results)"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["cpu_usage"] = cpu_usage_h
    handlers["memory_usage"] = memory_usage_h
    handlers["disk_usage"] = disk_usage_h
    handlers["health_check"] = health_check_h
    handlers["task_progress"] = task_progress_h

    # =========================================================================
    # BATCH 15 — Editing extras (replace_class, undo_changes, generate_patch)
    # =========================================================================

    # moved to app/tools/filesystem/replace_class.py — this now delegates to the shared replace_class_handler()
    def replace_class_h(inp: dict[str, Any]) -> str:
        return replace_class_handler(root, repo_path, inp)

    def undo_changes_h(inp: dict[str, Any]) -> str:
        undo_rel = str(inp["path"])
        if _is_protected_path(undo_rel, repo_path):
            return f"[POLICY DENIED] Protected path: {undo_rel}"

        settings = get_settings()
        if settings.sentry_environment == "production":
            return (
                "[BLOCKED] undo_changes is disabled in the production environment. "
                "Run migrations in a non-production environment only."
            )

        # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
        # real gap found: `session` is never non-None for any real caller
        # of make_chat_handlers() (grepped every real call site in the
        # repo — none pass one; undo_changes isn't in any one-shot agent's
        # allowed_tools either). The interactive chat agent has its own
        # separate, real, working undo_changes dispatch with a genuine
        # self._confirm() gate. Simplified to state that plainly instead
        # of dead async plumbing that could never execute.
        return "[BLOCKED] undo_changes requires interactive session for safety confirmation"

    def generate_patch_h(inp: dict[str, Any]) -> str:
        import difflib

        gp_a = str(inp.get("content_a", ""))
        gp_b = str(inp.get("content_b", ""))
        gp_fn = str(inp.get("filename", "file"))
        diff = list(
            difflib.unified_diff(
                gp_a.splitlines(keepends=True),
                gp_b.splitlines(keepends=True),
                fromfile=f"a/{gp_fn}",
                tofile=f"b/{gp_fn}",
            )
        )
        return "".join(diff) if diff else "(no differences)"

    handlers["replace_class"] = replace_class_h
    handlers["undo_changes"] = undo_changes_h
    handlers["generate_patch"] = generate_patch_h

    # =========================================================================
    # BATCH 16 — DB extras (explain_query, run_migration, seed_database)
    # =========================================================================

    def explain_query_h(inp: dict[str, Any]) -> str:
        expq_sql = str(inp["query"]).strip().rstrip(";")
        settings = get_settings()
        expq_db = getattr(settings, "database_url", "")
        if not expq_db:
            return "[ERROR] DATABASE_URL not set"
        full_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {expq_sql};"
        try:
            r = subprocess.run(
                ["psql", expq_db, "-c", full_sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    # run_migration_h removed — tool_enhance.md productionization pass,
    # tool #8 (2026-08-16). Now registered directly against
    # run_migration_handler (app/tools/database/migration.py), which
    # also closes a real shell-injection finding (see that module's
    # docstring) that this handler was never actually reachable enough
    # to be exploitable through, but shares the same validation as the
    # real, reachable chat_agent.py dispatch for defense-in-depth.

    # seed_database_h removed — tool_enhance.md productionization pass,
    # tool #10 (2026-08-16). Now registered directly against
    # seed_database_handler (app/tools/database/seed.py), which also
    # closes a real shell-injection + path-boundary-escape finding (see
    # that module's docstring).

    handlers["explain_query"] = explain_query_h
    handlers["run_migration"] = lambda inp: run_migration_handler(repo_path, inp)
    handlers["seed_database"] = lambda inp: seed_database_handler(repo_path, inp)

    # =========================================================================
    # DAY 3A — Browser tools (Playwright)
    # =========================================================================

    # moved to app/tools/browser/browser_tools.py — tool_enhance.md
    # productionization pass, tools #28-#31 + #123-#125 (2026-08-18).
    def _browser_sid() -> str:
        return getattr(session, "session_id", None) or "__default__"

    def browser_open_h(inp: dict[str, Any]) -> str:
        return browser_open_handler(inp, session_id=_browser_sid())

    def browser_navigate_h(inp: dict[str, Any]) -> str:
        return browser_navigate_handler(inp, session_id=_browser_sid())

    def browser_screenshot_h(inp: dict[str, Any]) -> str:
        return browser_screenshot_handler(inp, session_id=_browser_sid())

    def browser_read_dom_h(inp: dict[str, Any]) -> str:
        return browser_read_dom_handler(inp, session_id=_browser_sid())

    def browser_click_h(inp: dict[str, Any]) -> str:
        return browser_click_handler(inp, session_id=_browser_sid())

    def browser_type_h(inp: dict[str, Any]) -> str:
        return browser_type_handler(inp, session_id=_browser_sid())

    def browser_close_h(inp: dict[str, Any]) -> str:
        return browser_close_handler(inp, session_id=_browser_sid())

    handlers["browser_open"] = browser_open_h
    handlers["browser_navigate"] = browser_navigate_h
    handlers["browser_screenshot"] = browser_screenshot_h
    handlers["browser_read_dom"] = browser_read_dom_h
    handlers["browser_click"] = browser_click_h
    handlers["browser_type"] = browser_type_h
    handlers["browser_close"] = browser_close_h

    # =========================================================================
    # DAY 3B — Memory tools (flat JSON files per repo slug)
    # =========================================================================

    import json as _json_mem
    import hashlib as _hlib

    # fcntl.flock is POSIX-only (found via real execution: ModuleNotFoundError
    # on Windows, breaking every test that builds this handler set, since the
    # import ran unconditionally at handler-setup time, not lazily inside a
    # single tool call). msvcrt.locking is stdlib and available on Windows;
    # both are used purely as an advisory mutual-exclusion lock around the
    # read-modify-write of these flat JSON/JSONL memory files, so locking a
    # single agreed-upon byte (offset 0) via msvcrt is equivalent in effect
    # to flock's whole-file lock for this use case.
    if sys.platform == "win32":
        import msvcrt as _msvcrt

        def _mem_lock(fh: Any) -> None:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_LOCK, 1)

        def _mem_unlock(fh: Any) -> None:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)

    else:
        import fcntl as _fcntl

        def _mem_lock(fh: Any) -> None:
            _fcntl.flock(fh, _fcntl.LOCK_EX)

        def _mem_unlock(fh: Any) -> None:
            _fcntl.flock(fh, _fcntl.LOCK_UN)

    _mem_slug = _hlib.md5(repo_path.encode()).hexdigest()[:8]
    _mem_dir = Path(__file__).parent.parent / "memory"
    _mem_dir.mkdir(exist_ok=True)
    _mem_store_path = _mem_dir / f"{_mem_slug}_store.json"
    _mem_decisions_path = _mem_dir / f"{_mem_slug}_decisions.jsonl"
    _mem_issues_path = _mem_dir / f"{_mem_slug}_known_issues.md"

    def _read_mem_store() -> dict[str, str]:
        if not _mem_store_path.exists():
            return {}
        try:
            return dict(_json_mem.loads(_mem_store_path.read_text(encoding="utf-8")))
        except Exception:
            return {}

    def _write_mem_store(store: dict[str, str]) -> None:
        with open(_mem_store_path, "w", encoding="utf-8") as _fh:
            _mem_lock(_fh)
            _json_mem.dump(store, _fh, indent=2)
            _mem_unlock(_fh)

    def memory_read_h(inp: dict[str, Any]) -> str:
        key = str(inp["key"])
        store = _read_mem_store()
        val = store.get(key)
        return val if val is not None else f"(key '{key}' not found in memory)"

    # moved to app/tools/agents/memory_write.py — this now calls the shared, atomic write_memory_key()
    # (real, empirically-proven lost-update race condition fixed there; see that module's own docstring)
    def memory_write_h(inp: dict[str, Any]) -> str:
        key = str(inp["key"])
        value = str(inp["value"])
        return write_memory_key(repo_path, key, value)

    def decision_log_append_h(inp: dict[str, Any]) -> str:
        import datetime as _dt

        entry = {
            "timestamp": _dt.datetime.utcnow().isoformat(),
            "decision": str(inp["decision"]),
            "reason": str(inp["reason"]),
            "alternatives": str(inp.get("alternatives", "")),
        }
        try:
            with open(_mem_decisions_path, "a", encoding="utf-8") as _fh:
                _mem_lock(_fh)
                _fh.write(_json_mem.dumps(entry) + "\n")
                _mem_unlock(_fh)
            return f"Decision logged: {entry['decision'][:80]}"
        except Exception as e:
            return f"[ERROR] {e}"

    task_history_query_h = task_history_query

    def known_issues_read_h(inp: dict[str, Any]) -> str:
        if not _mem_issues_path.exists():
            return "(no known issues file yet)"
        return _mem_issues_path.read_text(encoding="utf-8")

    def known_issues_write_h(inp: dict[str, Any]) -> str:
        import datetime as _dt

        issue = str(inp["issue"])
        severity = str(inp.get("severity", "medium")).upper()
        now = _dt.datetime.utcnow()
        line = f"\n## [{severity}] {now.strftime('%Y-%m-%d')}\n{issue}\n"
        try:
            with open(_mem_issues_path, "a", encoding="utf-8") as _fh:
                _mem_lock(_fh)
                _fh.write(line)
                _mem_unlock(_fh)
        except Exception as e:
            return f"[ERROR] {e}"

        # AUDIT_Q_BATCH15 §75/§105/§112 gap-closure (2026-08-11) — the flat
        # KNOWN_ISSUES.md-style append above is kept unchanged (nothing that
        # reads that file today breaks); this additionally makes the same
        # known issue searchable/retrievable via memory_hook_node, which the
        # flat file alone never was. Best-effort — a memory-backend failure
        # must not turn a successful known-issue write into an error.
        try:
            from app.memory.store import embed_bug_sync

            embed_bug_sync(
                task_id=f"known-issue-{now.strftime('%Y%m%dT%H%M%S%f')}",
                issue=issue,
                severity=severity.lower(),
            )
        except Exception:
            pass

        return f"Known issue appended (severity: {severity})"

    handlers["memory_read"] = memory_read_h
    handlers["memory_write"] = memory_write_h
    handlers["decision_log_append"] = decision_log_append_h
    handlers["task_history_query"] = task_history_query_h
    handlers["known_issues_read"] = known_issues_read_h
    handlers["known_issues_write"] = known_issues_write_h
    # AUDIT_Q_BATCH15 §74/§113 gap-closure (2026-08-11).
    handlers["record_preference"] = make_record_preference_handler(
        task_id=f"chat-{session.session_id}" if session is not None else "chat"
    )

    # =========================================================================
    # DAY 3C — Planning + docs tools
    # =========================================================================

    def estimate_complexity_h(inp: dict[str, Any]) -> str:
        description = str(inp.get("description", ""))
        context_paths = list(inp.get("context_paths", []))
        word_count = len(description.split())
        file_count = len(context_paths)
        score = word_count + file_count * 10
        if score < 30:
            size = "XS"
        elif score < 80:
            size = "S"
        elif score < 200:
            size = "M"
        elif score < 500:
            size = "L"
        else:
            size = "XL"
        return f"Estimated complexity: {size} (word_count={word_count}, context_files={file_count}, score={score})"

    def summarize_folder_h(inp: dict[str, Any]) -> str:
        sf_path = str(inp.get("path", "."))
        exts = set(inp.get("extensions", [".py", ".ts", ".tsx"]))
        results: list[str] = []
        folder = root / sf_path
        if not folder.exists():
            return f"[ERROR] Path not found: {sf_path}"
        count = 0
        for fp in sorted(folder.rglob("*")):
            if not fp.is_file():
                continue
            if fp.suffix not in exts:
                continue
            if count >= 20:
                results.append("(truncated — 20 file limit)")
                break
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                n_lines = len(lines)
                n_funcs = sum(
                    1
                    for ln in lines
                    if ln.strip().startswith("def ")
                    or ln.strip().startswith("async def ")
                )
                n_classes = sum(1 for ln in lines if ln.strip().startswith("class "))
                rel = fp.relative_to(root)
                results.append(
                    f"**{rel}** — {n_lines} lines, {n_funcs} functions, {n_classes} classes"
                )
            except Exception as e:
                results.append(f"[ERROR reading {fp.name}] {e}")
            count += 1
        return "\n".join(results) if results else "(no matching files)"

    def generate_api_docs_text_h(inp: dict[str, Any]) -> str:
        import re as _re_docs

        route_path = str(inp["route_path"])
        fp = root / route_path
        if not fp.exists():
            return f"[ERROR] File not found: {route_path}"
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] {e}"
        lines = text.splitlines()
        endpoints: list[str] = []
        for i, line in enumerate(lines):
            m = _re_docs.match(
                r'\s*@\w+\.(get|post|put|patch|delete|options|head)\s*\("([^"]+)"', line
            )
            if m:
                method = m.group(1).upper()
                path_val = m.group(2)
                # Find the next def line
                func_name = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    fm = _re_docs.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[j])
                    if fm:
                        func_name = fm.group(1)
                        break
                endpoints.append(
                    f"### {method} {path_val}\n**Function:** `{func_name}`\n\n**Description:** _TODO_\n\n**Request:** _TODO_\n\n**Response:** _TODO_\n"
                )
        if not endpoints:
            return "(no FastAPI route decorators found)"
        return "\n".join(endpoints)

    def mermaid_from_schema_h(inp: dict[str, Any]) -> str:
        import subprocess as _sp_merm
        from app.config import get_settings as _gs_merm

        settings = _gs_merm()
        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return "[ERROR] DATABASE_URL not set"
        tbl = inp.get("table")
        sql = f"\\d {tbl}" if tbl else "\\dt+"
        try:
            r = _sp_merm.run(
                ["psql", db_url, "-c", sql, "--no-psqlrc"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            raw = (r.stdout + r.stderr).strip()
        except Exception as e:
            return f"[ERROR] {e}"
        # Build a basic Mermaid erDiagram from psql table listing
        lines = ["```mermaid", "erDiagram"]
        for row in raw.splitlines():
            parts = row.split("|")
            if len(parts) >= 2:
                tname = parts[1].strip()
                if (
                    tname
                    and not tname.startswith("-")
                    and tname not in ("Name", "Schema")
                ):
                    lines.append(f"    {tname} {{")
                    lines.append("        string id")
                    lines.append("    }")
        lines.append("```")
        return "\n".join(lines) if len(lines) > 3 else f"(raw schema)\n{raw}"

    handlers["estimate_complexity"] = estimate_complexity_h
    handlers["summarize_folder"] = summarize_folder_h
    handlers["generate_api_docs_text"] = generate_api_docs_text_h
    handlers["mermaid_from_schema"] = mermaid_from_schema_h

    # =========================================================================
    # DAY 3G — External integrations (GitHub/Linear/Slack — not MCP protocol)
    # =========================================================================

    import subprocess as _sp_mcp
    import os as _os_mcp

    # moved to app/tools/git/github_create_issue.py — command-building now shared via github_create_issue_command()
    def github_create_issue_h(inp: dict[str, Any]) -> str:
        title = str(inp["title"])
        body = str(inp["body"])
        labels = [str(lbl) for lbl in inp.get("labels", [])]
        cmd = github_create_issue_command(title, body, labels)
        try:
            r = _sp_mcp.run(
                cmd, capture_output=True, text=True, cwd=str(root), timeout=30
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found — install GitHub CLI"
        except Exception as e:
            return f"[ERROR] {e}"

    def github_list_prs_h(inp: dict[str, Any]) -> str:
        state = str(inp.get("state", "open"))
        try:
            r = _sp_mcp.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    state,
                    "--json",
                    "number,title,state,author",
                ],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found"
        except Exception as e:
            return f"[ERROR] {e}"

    # moved to app/tools/git/github_comment.py — command-building now shared via github_comment_command()
    def github_comment_h(inp: dict[str, Any]) -> str:
        number = int(inp["number"])
        body = str(inp["body"])
        kind = str(inp.get("kind", "issue"))
        try:
            r = _sp_mcp.run(
                github_comment_command(number, body, kind),
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "Comment posted"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found"
        except Exception as e:
            return f"[ERROR] {e}"

    # moved to app/tools/integrations/linear_create_issue.py — this now calls the shared create_linear_issue()
    def linear_create_issue_h(inp: dict[str, Any]) -> str:
        api_key = _os_mcp.environ.get("LINEAR_API_KEY", "")
        if not api_key:
            return "[ERROR] LINEAR_API_KEY not set"
        title = str(inp["title"])
        description = str(inp["description"])
        team_key = str(inp["team_key"])
        return create_linear_issue(api_key, title, description, team_key)

    # tool_enhance.md productionization pass, tool #63 (2026-08-22) —
    # the real fix (a new chat_agent.py dispatch, since this was
    # advertised but never dispatched there) lives in
    # send_slack_message() itself; see that function's own module
    # docstring.
    def slack_send_message_h(inp: dict[str, Any]) -> str:
        webhook_url = _os_mcp.environ.get("SLACK_WEBHOOK_URL", "")
        if not webhook_url:
            return "[ERROR] SLACK_WEBHOOK_URL not set"
        return send_slack_message(webhook_url, str(inp["text"]))

    handlers["github_create_issue"] = github_create_issue_h
    handlers["github_list_prs"] = github_list_prs_h
    handlers["github_comment"] = github_comment_h
    handlers["linear_create_issue"] = linear_create_issue_h
    handlers["slack_send_message"] = slack_send_message_h

    # ── Day 2 Gap handlers ─────────────────────────────────────────────────────

    def find_queue_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        patterns = [  # noqa: F841
            r"asyncio\.Queue",
            r"class.*Queue",
            r"BullMQ\|rq\.Queue\|celery\|dramatiq\|huey",
            r"Queue\(",
        ]
        results: list[str] = []
        try:
            pat = (
                r"asyncio\.Queue|class.*Queue|rq\.Queue|Queue\(|BullMQ|celery|dramatiq"
            )
            out = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.js",
                    "-E",
                    pat,
                    _rp,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = out.stdout.strip().splitlines()
            results = [
                ln for ln in lines if ".venv/" not in ln and "node_modules/" not in ln
            ][:30]
        except Exception as e:
            return f"[ERROR] find_queue: {e}"
        if not results:
            return "No queue patterns found."
        return "\n".join(results)

    def find_worker_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        try:
            pat = r"class.*Worker|@worker|celery\.task|\.delay\(|rq.*worker|dramatiq\.actor|Consumer"
            out = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.js",
                    "-E",
                    pat,
                    _rp,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = out.stdout.strip().splitlines()
            results = [
                ln for ln in lines if ".venv/" not in ln and "node_modules/" not in ln
            ][:30]
        except Exception as e:
            return f"[ERROR] find_worker: {e}"
        if not results:
            return "No worker patterns found."
        return "\n".join(results)

    # moved to app/tools/filesystem/insert_before.py — this now delegates to the shared insert_before_handler()
    def insert_before_h(inp: dict[str, Any]) -> str:
        return insert_before_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/insert_after.py — this now delegates to the shared insert_after_handler()
    def insert_after_h(inp: dict[str, Any]) -> str:
        return insert_after_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/delete_block.py as
    # delete_block_handler — tool_enhance.md productionization pass,
    # tool #33 (2026-08-18).
    def delete_block_h(inp: dict[str, Any]) -> str:
        return delete_block_handler(root, repo_path, inp)

    def generate_changelog_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        from_ref = str(inp.get("from_ref", ""))
        to_ref = str(inp.get("to_ref", "HEAD"))
        try:
            if not from_ref:
                tags = subprocess.run(
                    ["git", "-C", _rp, "tag", "--sort=-version:refname"],
                    capture_output=True,
                    text=True,
                )
                tag_list = [t for t in tags.stdout.strip().splitlines() if t]
                from_ref = (
                    tag_list[1]
                    if len(tag_list) >= 2
                    else tag_list[0]
                    if tag_list
                    else ""
                )
            ref_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
            log = subprocess.run(
                [
                    "git",
                    "-C",
                    _rp,
                    "log",
                    ref_range,
                    "--pretty=format:%s (%an)",
                    "--no-merges",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            commits = log.stdout.strip().splitlines()
            if not commits:
                return f"No commits found between {from_ref or 'start'} and {to_ref}"
            sections: dict[str, list[str]] = {
                "Added": [],
                "Changed": [],
                "Fixed": [],
                "Other": [],
            }
            for c in commits:
                cl = c.lower()
                if cl.startswith(("feat:", "add ", "new ")):
                    sections["Added"].append(f"- {c}")
                elif cl.startswith(("fix:", "bug ", "patch ")):
                    sections["Fixed"].append(f"- {c}")
                elif cl.startswith(("refactor:", "chore:", "update ", "change ")):
                    sections["Changed"].append(f"- {c}")
                else:
                    sections["Other"].append(f"- {c}")
            import datetime as _dt

            lines_out = [
                f"## [Unreleased] — {_dt.date.today().isoformat()}",
                f"Changes from {from_ref or 'start'} to {to_ref}",
                "",
            ]
            for sec, items in sections.items():
                if items:
                    lines_out.append(f"### {sec}")
                    lines_out.extend(items)
                    lines_out.append("")
            return "\n".join(lines_out)
        except Exception as e:
            return f"[ERROR] generate_changelog: {e}"

    def summarize_repo_h(inp: dict[str, Any]) -> str:
        _rp = str(inp.get("repo_path", repo_path))
        try:
            import os as _os_sr

            # File tree (3 levels)
            tree_lines: list[str] = []
            for dirpath, dirnames, filenames in _os_sr.walk(_rp):
                dirnames[:] = [
                    d
                    for d in sorted(dirnames)
                    if d not in (".git", ".venv", "node_modules", "__pycache__")
                ]
                depth = dirpath.replace(_rp, "").count(_os_sr.sep)
                if depth > 2:
                    continue
                indent = "  " * depth
                tree_lines.append(f"{indent}{_os_sr.path.basename(dirpath)}/")
                if depth < 2:
                    for f in sorted(filenames)[:10]:
                        tree_lines.append(f"{indent}  {f}")

            # Line counts by extension
            ext_counts: dict[str, int] = {}
            total_files = 0
            for dirpath, dirnames, filenames in _os_sr.walk(_rp):
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in (".git", ".venv", "node_modules", "__pycache__")
                ]
                for fname in filenames:
                    ext = _os_sr.path.splitext(fname)[1] or "other"
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    total_files += 1

            top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:8]

            # README excerpt
            readme_excerpt = ""
            for rname in ("README.md", "readme.md", "README.rst"):
                rpath = _os_sr.path.join(_rp, rname)
                if _os_sr.path.exists(rpath):
                    with open(rpath, encoding="utf-8", errors="ignore") as rf:
                        readme_excerpt = rf.read(800)
                    break

            summary = [
                f"## Repository Summary: {_os_sr.path.basename(_rp)}",
                f"Total files: {total_files}",
                "",
                "### Top file types",
            ]
            for ext, count in top_exts:
                summary.append(f"  {ext:10} {count}")
            summary += ["", "### Directory tree (3 levels)"] + tree_lines[:50]
            if readme_excerpt:
                summary += ["", "### README (first 800 chars)", readme_excerpt]
            return "\n".join(summary)
        except Exception as e:
            return f"[ERROR] summarize_repo: {e}"

    def generate_release_notes_h(inp: dict[str, Any]) -> str:
        version = str(inp["version"])
        _rp = str(inp.get("repo_path", repo_path))
        from_ref = str(inp.get("from_ref", ""))
        try:
            if not from_ref:
                tags = subprocess.run(
                    ["git", "-C", _rp, "tag", "--sort=-version:refname"],
                    capture_output=True,
                    text=True,
                )
                tag_list = [t for t in tags.stdout.strip().splitlines() if t]
                from_ref = tag_list[0] if tag_list else ""
            ref_range = f"{from_ref}..HEAD" if from_ref else "HEAD"
            log = subprocess.run(
                [
                    "git",
                    "-C",
                    _rp,
                    "log",
                    ref_range,
                    "--pretty=format:* %s",
                    "--no-merges",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            commits = log.stdout.strip()
            import datetime as _dt_rn

            notes = [
                f"# Release Notes — {version}",
                f"Released: {_dt_rn.date.today().isoformat()}",
                "",
                "## What's Changed",
                "",
                commits or "No commits found.",
                "",
                f"**Full Changelog:** {from_ref}...{version}" if from_ref else "",
            ]
            return "\n".join(notes)
        except Exception as e:
            return f"[ERROR] generate_release_notes: {e}"

    def read_pdf_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        max_pages = int(inp.get("max_pages", 20))
        fpath = Path(path) if Path(path).is_absolute() else root / path
        try:
            import pdfplumber as _pp

            pages_text: list[str] = []
            with _pp.open(str(fpath)) as pdf:
                for i, page in enumerate(pdf.pages[:max_pages]):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages_text.append(f"--- Page {i + 1} ---\n{text.strip()}")
            if not pages_text:
                return f"[WARN] No text extracted from {fpath} (may be image-only PDF)"
            return "\n\n".join(pages_text)
        except ImportError:
            return (
                "[ERROR] pdfplumber not installed. Run: pip install pdfplumber==0.11.10"
            )
        except Exception as e:
            return f"[ERROR] read_pdf: {e}"

    def read_image_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        fpath = Path(path) if Path(path).is_absolute() else root / path
        try:
            from PIL import Image as _PilImg
            import base64 as _b64
            import io as _io_img

            img = _PilImg.open(str(fpath))
            meta = {
                "format": img.format,
                "mode": img.mode,
                "size": f"{img.width}x{img.height}",
                "path": str(fpath),
            }
            # Generate a small thumbnail as base64 for inspection
            thumb = img.copy()
            thumb.thumbnail((256, 256))
            buf = _io_img.BytesIO()
            thumb.save(buf, format="PNG")
            b64_thumb = _b64.b64encode(buf.getvalue()).decode()
            return (
                f"Image: {meta['path']}\n"
                f"Format: {meta['format']} | Mode: {meta['mode']} | Size: {meta['size']}\n"
                f"Thumbnail (base64 PNG, 256x256): {b64_thumb[:200]}…"
            )
        except Exception as e:
            return f"[ERROR] read_image: {e}"

    # github_create_pr_h removed — tool_enhance.md productionization
    # pass, tool #6 (2026-08-16). It was a second, separately-maintained,
    # far less hardened implementation of the exact same action as
    # create_pr (both just run `gh pr create`) — no repo/branch/base
    # identity verification, no no-diff guard, no duplicate-PR check, no
    # approval gate at all. Now registered directly against the already-
    # hardened create_pr_handler below.

    handlers["find_queue"] = find_queue_h
    handlers["find_worker"] = find_worker_h
    handlers["insert_before"] = insert_before_h
    handlers["insert_after"] = insert_after_h
    handlers["delete_block"] = delete_block_h
    handlers["generate_changelog"] = generate_changelog_h
    handlers["summarize_repo"] = summarize_repo_h
    handlers["generate_release_notes"] = generate_release_notes_h
    handlers["read_pdf"] = read_pdf_h
    handlers["read_image"] = read_image_h
    handlers["github_create_pr"] = lambda inp: create_pr_handler(repo_path, inp)

    # ---- Batch 15 handlers ----

    # moved to app/tools/git/tag.py as git_tag_handler —
    # tool_enhance.md productionization pass, tool #22 (2026-08-17).
    def git_tag_h(inp: dict[str, Any]) -> str:
        return git_tag_handler(repo_path, inp)

    def git_log_file_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        limit = int(inp.get("limit", 10))
        try:
            r = subprocess.run(
                ["git", "log", f"--max-count={limit}", "--oneline", "--", path],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=15,
            )
            return r.stdout.strip() or f"(no commits found for {path})"
        except Exception as e:
            return f"[ERROR] git_log_file: {e}"

    # moved to app/tools/filesystem/semver_bump.py as semver_bump_handler
    # — tool_enhance.md productionization pass, tool #25 (2026-08-18).
    def semver_bump_h(inp: dict[str, Any]) -> str:
        return semver_bump_handler(root, repo_path, inp)

    def git_stash_list_h(inp: dict[str, Any]) -> str:
        try:
            r = subprocess.run(
                ["git", "stash", "list"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=15,
            )
            return r.stdout.strip() or "(no stashes)"
        except Exception as e:
            return f"[ERROR] git_stash_list: {e}"

    def list_processes_h(inp: dict[str, Any]) -> str:
        name_filter = str(inp.get("filter", ""))
        try:
            r = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=10
            )
            lines = r.stdout.strip().splitlines()
            if name_filter:
                lines = [
                    ln
                    for ln in lines
                    if name_filter.lower() in ln.lower() or ln.startswith("USER")
                ]
            return "\n".join(lines[:50])
        except Exception as e:
            return f"[ERROR] list_processes: {e}"

    def list_open_ports_h(inp: dict[str, Any]) -> str:
        try:
            r = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                r = subprocess.run(
                    ["netstat", "-tlnp"], capture_output=True, text=True, timeout=10
                )
            return r.stdout.strip() or "(no open ports found)"
        except Exception as e:
            return f"[ERROR] list_open_ports: {e}"

    def wait_for_port_h(inp: dict[str, Any]) -> str:
        import socket as _socket
        import time as _time

        port = int(inp["port"])
        host = str(inp.get("host", "localhost"))
        timeout = int(inp.get("timeout", 30))
        start = _time.time()
        while _time.time() - start < timeout:
            try:
                with _socket.create_connection((host, port), timeout=1):
                    elapsed = round(_time.time() - start, 2)
                    return f"Port {host}:{port} is open (waited {elapsed}s)"
            except (ConnectionRefusedError, OSError):
                _time.sleep(0.5)
        return f"[TIMEOUT] Port {host}:{port} not open after {timeout}s"

    def check_url_status_h(inp: dict[str, Any]) -> str:
        import urllib.request as _req
        import time as _time

        url = str(inp["url"])
        try:
            start = _time.time()
            r = _req.urlopen(url, timeout=10)
            elapsed = round((_time.time() - start) * 1000)
            return f"HTTP {r.status} {r.reason} ({elapsed}ms) — {url}"
        except Exception as e:
            return f"[ERROR] check_url_status {url}: {e}"

    def cpu_profile_h(inp: dict[str, Any]) -> str:
        command = str(inp["command"])
        top = int(inp.get("top", 20))
        try:
            profiled = f"python -m cProfile -s cumulative -c 'import subprocess; subprocess.run({command!r}.split(), check=True)'"  # noqa: F841
            r = subprocess.run(
                ["python", "-m", "cProfile", "-s", "cumulative"] + command.split()[1:],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=60,
            )
            lines = (r.stdout + r.stderr).strip().splitlines()
            return "\n".join(lines[: top + 10])
        except Exception as e:
            return f"[ERROR] cpu_profile: {e}"

    def zip_files_h(inp: dict[str, Any]) -> str:
        import zipfile as _zf

        source = str(inp["source"])
        src_path = root / source
        output = str(inp.get("output", source.rstrip("/") + ".zip"))
        out_path = root / output
        try:
            with _zf.ZipFile(str(out_path), "w", _zf.ZIP_DEFLATED) as zf:
                if src_path.is_dir():
                    for f in src_path.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(root))
                else:
                    zf.write(src_path, src_path.relative_to(root))
            return f"Zipped to {output}"
        except Exception as e:
            return f"[ERROR] zip_files: {e}"

    def unzip_files_h(inp: dict[str, Any]) -> str:
        import zipfile as _zf

        archive = str(inp["archive"])
        dest = str(inp.get("dest", str((root / archive).parent)))
        arc_path = root / archive
        dest_path = root / dest if not (root / dest).is_absolute() else Path(dest)
        try:
            with _zf.ZipFile(str(arc_path), "r") as zf:
                zf.extractall(str(dest_path))
            return f"Extracted {archive} to {dest}"
        except Exception as e:
            return f"[ERROR] unzip_files: {e}"

    # moved to app/tools/filesystem/move_file.py — this now calls the shared, hardened move_file_handler()
    def move_file_h(inp: dict[str, Any]) -> str:
        return move_file_handler(root, repo_path, inp)

    def hash_file_h(inp: dict[str, Any]) -> str:
        import hashlib as _hl

        fpath = root / str(inp["path"])
        try:
            h = _hl.sha256()
            with open(fpath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return f"SHA-256 {inp['path']}: {h.hexdigest()}"
        except Exception as e:
            return f"[ERROR] hash_file: {e}"

    def count_lines_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        pattern = str(inp.get("pattern", "**/*"))
        target = root / path
        try:
            if target.is_file():
                count = sum(1 for _ in target.open(encoding="utf-8", errors="ignore"))
                return f"{path}: {count} lines"
            totals: dict[str, int] = {}
            for fp in target.glob(pattern):
                if fp.is_file():
                    ext = fp.suffix or "(no ext)"
                    n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                    totals[ext] = totals.get(ext, 0) + n
            rows = sorted(totals.items(), key=lambda x: -x[1])
            lines_out = "\n".join(f"{ext}: {n:,}" for ext, n in rows)
            return f"Lines by extension in {path}:\n{lines_out}\nTotal: {sum(totals.values()):,}"
        except Exception as e:
            return f"[ERROR] count_lines: {e}"

    def read_env_var_h(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        val = os.environ.get(name)
        if val is None:
            return f"{name}=[NOT SET]"
        return f"{name}={_mask_secret_value(name, val)}"

    def list_env_vars_h(inp: dict[str, Any]) -> str:
        names = sorted(os.environ.keys())
        return "\n".join(names)

    def env_diff_h(inp: dict[str, Any]) -> str:
        example_path = root / str(inp.get("example", ".env.example"))
        actual_path = root / str(inp.get("actual", ".env"))

        def _keys(fp: Path) -> set[str]:
            if not fp.exists():
                return set()
            keys: set[str] = set()
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    keys.add(line.split("=", 1)[0].strip())
            return keys

        example_keys = _keys(example_path)
        actual_keys = _keys(actual_path)
        missing = sorted(example_keys - actual_keys)
        extra = sorted(actual_keys - example_keys)
        lines = []
        if missing:
            lines.append(f"Missing in {inp.get('actual', '.env')} ({len(missing)}):")
            lines.extend(f"  - {k}" for k in missing)
        if extra:
            lines.append(
                f"Extra in {inp.get('actual', '.env')} (not in example, {len(extra)}):"
            )
            lines.extend(f"  + {k}" for k in extra)
        if not missing and not extra:
            lines.append("✅ No differences — .env matches .env.example")
        return "\n".join(lines)

    def json_query_h(inp: dict[str, Any]) -> str:
        fpath = root / str(inp["path"])
        query = str(inp["query"])
        try:
            r = subprocess.run(
                ["jq", query, str(fpath)], capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                return f"[ERROR] jq: {r.stderr.strip()}"
            return r.stdout.strip()
        except FileNotFoundError:
            import json as _json

            data = _json.loads(fpath.read_text(encoding="utf-8"))
            return f"(jq not installed) Raw JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        except Exception as e:
            return f"[ERROR] json_query: {e}"

    def _load_schema_doc(schema_rel: str) -> Any:
        """Load a JSON Schema from a .json or .yaml/.yml file at schema_rel."""
        import json as _json

        import yaml as _yaml

        schema_path = root / schema_rel
        text = schema_path.read_text(encoding="utf-8")
        if schema_path.suffix in (".yaml", ".yml"):
            return _yaml.safe_load(text)
        return _json.loads(text)

    def _validate_against_schema(rel: str, doc: Any, schema_rel: str) -> str | None:
        """Returns an error string if the schema check fails/errors, else None."""
        import jsonschema

        try:
            schema = _load_schema_doc(schema_rel)
        except Exception as e:
            return f"[ERROR] Cannot load schema {schema_rel}: {e}"
        try:
            jsonschema.validate(instance=doc, schema=schema)
        except jsonschema.ValidationError as e:
            return f"[SCHEMA VIOLATION] {rel} does not match {schema_rel}: {e.message} (at {'/'.join(str(p) for p in e.absolute_path) or '<root>'})"
        except jsonschema.SchemaError as e:
            return f"[ERROR] {schema_rel} is not a valid JSON Schema: {e.message}"
        return None

    def yaml_validate_h(inp: dict[str, Any]) -> str:
        # AUDIT_Q_BATCH09 §16 gap-closure — this used to be syntax-only despite
        # jsonschema already being a pinned, production-used dependency
        # (app/agents/base_graph.py's tool-submission validation). schema_path
        # is optional and backward compatible: omitting it preserves the
        # original syntax-only behavior exactly.
        fpath = root / str(inp["path"])
        try:
            import yaml as _yaml

            with open(fpath, encoding="utf-8") as f:
                doc = _yaml.safe_load(f)
        except ImportError:
            return "(pyyaml not available in this environment)"
        except Exception as e:
            return f"[INVALID YAML] {inp['path']}: {e}"
        schema_rel = inp.get("schema_path")
        if schema_rel:
            err = _validate_against_schema(str(inp["path"]), doc, str(schema_rel))
            if err:
                return err
            return f"✅ {inp['path']} is valid YAML and matches schema {schema_rel}"
        return f"✅ {inp['path']} is valid YAML"

    def json_validate_h(inp: dict[str, Any]) -> str:
        import json as _json

        fpath = root / str(inp["path"])
        try:
            doc = _json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            return f"[INVALID JSON] {inp['path']}: {e}"
        schema_rel = inp.get("schema_path")
        if schema_rel:
            err = _validate_against_schema(str(inp["path"]), doc, str(schema_rel))
            if err:
                return err
            return f"✅ {inp['path']} is valid JSON and matches schema {schema_rel}"
        return f"✅ {inp['path']} is valid JSON"

    def csv_preview_h(inp: dict[str, Any]) -> str:
        import csv as _csv

        fpath = root / str(inp["path"])
        rows_n = int(inp.get("rows", 5))
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                reader = _csv.reader(f)
                rows: list[list[str]] = []
                for i, row in enumerate(reader):
                    if i > rows_n:
                        break
                    rows.append(row)
            if not rows:
                return "(empty CSV)"
            header = rows[0]
            out = ["Columns: " + ", ".join(header)]
            for row in rows[1:]:
                out.append(" | ".join(row))
            return "\n".join(out)
        except Exception as e:
            return f"[ERROR] csv_preview: {e}"

    def xml_validate_h(inp: dict[str, Any]) -> str:
        import xml.etree.ElementTree as _ET

        fpath = root / str(inp["path"])
        try:
            _ET.parse(str(fpath))
            return f"✅ {inp['path']} is well-formed XML"
        except _ET.ParseError as e:
            return f"[INVALID XML] {inp['path']}: {e}"
        except Exception as e:
            return f"[ERROR] xml_validate: {e}"

    def read_notebook_h(inp: dict[str, Any]) -> str:
        import json as _json

        fpath = root / str(inp["path"])
        max_cells = int(inp.get("max_cells", 100))
        try:
            nb = _json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            return f"[ERROR] read_notebook: {e}"
        cells = nb.get("cells", []) if isinstance(nb, dict) else []
        if not isinstance(cells, list) or not cells:
            return f"[ERROR] {inp['path']} has no readable 'cells' array (not a valid .ipynb?)"
        parts: list[str] = []
        for i, cell in enumerate(cells[:max_cells]):
            ctype = cell.get("cell_type", "unknown")
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            block = [f"--- Cell {i} ({ctype}) ---", str(source).rstrip()]
            for out_item in cell.get("outputs", []) or []:
                otype = out_item.get("output_type")
                if otype == "stream":
                    text = out_item.get("text", "")
                    if isinstance(text, list):
                        text = "".join(text)
                    block.append(f"[output] {str(text).rstrip()}")
                elif otype == "error":
                    block.append(
                        f"[error] {out_item.get('ename', '')}: {out_item.get('evalue', '')}"
                    )
                elif otype in ("execute_result", "display_data"):
                    text_out = out_item.get("data", {}).get("text/plain", "")
                    if isinstance(text_out, list):
                        text_out = "".join(text_out)
                    if text_out:
                        block.append(f"[result] {str(text_out).rstrip()}")
            parts.append("\n".join(block))
        remaining = len(cells) - min(len(cells), max_cells)
        result = f"Notebook: {inp['path']} ({len(cells)} cells)\n\n" + "\n\n".join(
            parts
        )
        if remaining > 0:
            result += f"\n\n[NOTICE] {remaining} additional cell(s) not shown (max_cells={max_cells})"
        return result

    def parse_dockerfile_h(inp: dict[str, Any]) -> str:
        path = str(inp.get("path", "Dockerfile"))
        fpath = root / path
        if not fpath.exists():
            return f"[ERROR] File not found: {path}"
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            return f"[ERROR] parse_dockerfile: {e}"
        stages: list[str] = []
        exposed_ports: list[str] = []
        instructions: list[str] = []
        pending = ""
        for lineno, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if pending:
                line = f"{pending} {line}"
                pending = ""
            if not line or line.startswith("#"):
                continue
            if line.endswith("\\"):
                pending = line[:-1].strip()
                continue
            head, _, rest = line.partition(" ")
            instr = head.upper()
            rest = rest.strip()
            instructions.append(f"{lineno}: {instr} {rest}".rstrip())
            if instr == "FROM":
                stages.append(rest)
            elif instr == "EXPOSE":
                exposed_ports.append(rest)
        if not instructions:
            return f"(empty or unparseable Dockerfile: {path})"
        out = [
            f"Dockerfile: {path}",
            f"Stages/base images: {', '.join(stages) or '(none)'}",
            f"Exposed ports: {', '.join(exposed_ports) or '(none)'}",
            "",
            "Instructions:",
            *instructions,
        ]
        return "\n".join(out)

    def parse_docker_compose_h(inp: dict[str, Any]) -> str:
        path = str(inp.get("path", "docker-compose.yml"))
        fpath = root / path
        if not fpath.exists():
            return f"[ERROR] File not found: {path}"
        try:
            import yaml as _yaml

            doc = _yaml.safe_load(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            return f"[ERROR] parse_docker_compose: {e}"
        if not isinstance(doc, dict):
            return f"(empty or invalid compose file: {path})"
        services = doc.get("services", {})
        if not isinstance(services, dict) or not services:
            return f"(no services found in {path})"
        out = [f"docker-compose: {path} ({len(services)} service(s))"]
        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            out.append(f"\n- {name}:")
            for key in ("image", "build", "ports", "volumes", "depends_on"):
                val = svc.get(key)
                if val:
                    out.append(f"    {key}: {val}")
        return "\n".join(out)

    def github_inspect_repo_h(inp: dict[str, Any]) -> str:
        import json as _json
        import re as _re
        import urllib.error as _urlerr
        import urllib.request as _req

        owner = str(inp["owner"])
        repo_name = str(inp["repo"])
        sub_path = str(inp.get("path", "")).strip("/")
        valid = _re.compile(r"^[A-Za-z0-9._-]+$")
        if not valid.match(owner) or not valid.match(repo_name):
            return "[ERROR] owner/repo must contain only letters, digits, '.', '_', '-'"
        sub_segments = [seg for seg in sub_path.split("/") if seg]
        if sub_path and (
            not all(valid.match(seg) for seg in sub_segments)
            or any(seg in (".", "..") for seg in sub_segments)
        ):
            return (
                "[ERROR] path segments must contain only letters, digits, "
                "'.', '_', '-' and must not be '.' or '..'"
            )

        def _get(url: str) -> Any:
            req = _req.Request(
                url,
                headers={
                    "User-Agent": "Gridiron-Agent/1.0",
                    "Accept": "application/vnd.github+json",
                },
            )
            with _req.urlopen(req, timeout=15) as resp:
                return _json.loads(resp.read().decode("utf-8"))

        try:
            meta = _get(f"https://api.github.com/repos/{owner}/{repo_name}")
        except _urlerr.HTTPError as e:
            return f"[ERROR] GitHub API {e.code}: {owner}/{repo_name} — {e.reason}"
        except Exception as e:
            return f"[ERROR] github_inspect_repo: {e}"

        lines = [
            str(meta.get("full_name", f"{owner}/{repo_name}")),
            f"Description: {meta.get('description') or '(none)'}",
            f"Default branch: {meta.get('default_branch', '?')}",
            f"Language: {meta.get('language') or '?'} | Stars: {meta.get('stargazers_count', 0)} | Forks: {meta.get('forks_count', 0)}",
            f"URL: {meta.get('html_url', '')}",
        ]
        try:
            contents = _get(
                f"https://api.github.com/repos/{owner}/{repo_name}/contents/{sub_path}"
            )
            if isinstance(contents, list):
                lines.append(
                    f"\nFiles at /{sub_path}:" if sub_path else "\nFiles at repo root:"
                )
                for item in contents[:100]:
                    lines.append(f"  [{item.get('type', '?')}] {item.get('name', '?')}")
        except Exception as e:
            lines.append(f"\n[WARN] Could not list contents: {e}")
        return "\n".join(lines)

    def openapi_inspect_h(inp: dict[str, Any]) -> str:
        import json as _json

        import yaml as _yaml

        fpath = root / str(inp["path"])
        if not fpath.exists():
            return f"[ERROR] File not found: {inp['path']}"
        try:
            text = fpath.read_text(encoding="utf-8")
            spec = (
                _yaml.safe_load(text)
                if fpath.suffix in (".yaml", ".yml")
                else _json.loads(text)
            )
        except Exception as e:
            return f"[ERROR] openapi_inspect: {e}"
        if not isinstance(spec, dict) or (
            "openapi" not in spec and "swagger" not in spec
        ):
            return (
                f"[ERROR] {inp['path']} does not look like an OpenAPI/Swagger spec "
                "(missing 'openapi'/'swagger' key)"
            )
        info = spec.get("info", {}) if isinstance(spec.get("info"), dict) else {}
        version = spec.get("openapi") or spec.get("swagger")
        paths = spec.get("paths", {}) if isinstance(spec.get("paths"), dict) else {}
        out = [
            f"{info.get('title', '(untitled)')} — API version {info.get('version', '?')} (OpenAPI {version})",
            f"{len(paths)} path(s):",
        ]
        http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}
        for p, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.lower() not in http_methods:
                    continue
                summary = op.get("summary", "") if isinstance(op, dict) else ""
                params = op.get("parameters", []) if isinstance(op, dict) else []
                out.append(
                    f"  {method.upper():6} {p}  {summary}  ({len(params)} param(s))"
                )
        return "\n".join(out)

    def summarize_output_h(inp: dict[str, Any]) -> str:
        """AUDIT_Q_BATCH14 §99 gap-closure — real LLM-generated output
        summarization, distinct from the hard char/line truncation used
        elsewhere in this file (e.g. result.stdout[:8000]). Reuses
        _llm_generate_text (the same one-shot, circuit-breaker-protected,
        never-raises LLM call already used by generate_commit_msg and
        every other "generate X" tool in this module — see that function's
        own docstring) rather than building a second Anthropic call path."""
        text = str(inp["text"])
        focus = str(inp.get("focus", "")).strip()
        if not text.strip():
            return "(nothing to summarize — empty text)"

        focus_line = f" Focus specifically on: {focus}." if focus else ""
        prompt = (
            "Summarize the following text concisely, in 3-8 concrete bullet "
            "points. Preserve specifics (file paths, error messages, numbers, "
            f"conclusions) — do not write vague generalities.{focus_line}\n\n"
            f"Text to summarize:\n{text[:20000]}"
        )
        summary = _llm_generate_text(prompt, max_tokens=500)
        if not summary:
            return (
                "[summarization unavailable — LLM call failed] "
                f"Original text was {len(text)} chars; here is a truncated excerpt:\n"
                f"{text[:2000]}"
            )
        return summary

    def _real_class_diagram(file_path: str) -> str | None:
        """AUDIT_Q_BATCH14 §99 gap-closure — real classes/bases from
        parse_file_ast (app/repo_tools/ast_engine.py), not a fake
        MyClass/method() skeleton. Returns None (never a guess) when the
        file can't be parsed or declares no classes, so the caller falls
        back to the labeled template instead of fabricating content."""
        import json

        from app.repo_tools.ast_engine import parse_file_ast

        raw = parse_file_ast(str(root / file_path))
        if raw.startswith("[ERROR]"):
            return None
        classes = json.loads(raw).get("classes", [])
        if not classes:
            return None

        lines = ["classDiagram"]
        for cls in classes:
            name = cls["name"]
            for method in cls["methods"][:15]:
                lines.append(f"    {name} : +{method}()")
            for base in cls["bases"]:
                # Mermaid inheritance arrow: subclass --|> superclass.
                # ast.unparse() can return a dotted expr (e.g. "abc.ABC") —
                # Mermaid class names can't contain '.', so the last
                # component is used, matching build_class_graph's own
                # identifier-name-matching convention (cross_file_graph.py).
                base_name = base.rsplit(".", 1)[-1]
                lines.append(f"    {base_name} <|-- {name}")
        return "\n".join(lines)

    def _real_call_flowchart(file_path: str, description: str) -> str | None:
        """AUDIT_Q_BATCH14 §99 gap-closure — real function call edges from
        get_call_edges (app/repo_tools/ast_engine.py), not a fake
        Start/Process/Decision/End skeleton. Returns None when the file has
        no functions or can't be parsed."""
        from app.repo_tools.ast_engine import get_call_edges

        edges = get_call_edges(str(root / file_path))
        if isinstance(edges, str) or not edges:
            return None

        known_functions = {e["caller"] for e in edges}
        lines = [f"flowchart TD\n    %% {description}"]
        seen_edges: set[tuple[str, str]] = set()
        for edge in edges:
            caller = edge["caller"]
            # Only draw edges to functions actually defined in this same
            # file — an edge to an unknown external call would be a real
            # name but a misleading, unverifiable diagram node.
            for callee in edge["calls"]:
                target = callee.rsplit(".", 1)[-1]
                if target in known_functions and (caller, target) not in seen_edges:
                    lines.append(f"    {caller} --> {target}")
                    seen_edges.add((caller, target))
        if len(lines) == 1:
            return None
        return "\n".join(lines)

    def generate_diagram_h(inp: dict[str, Any]) -> str:
        description = str(inp["description"])
        kind = str(inp.get("kind", "flowchart"))
        path_in = inp.get("path")

        if path_in:
            real: str | None = None
            if kind == "classDiagram":
                real = _real_class_diagram(str(path_in))
            elif kind == "flowchart":
                real = _real_call_flowchart(str(path_in), description)
            if real is not None:
                return f"```mermaid\n{real}\n```"

        templates = {
            "flowchart": f"flowchart TD\n    %% {description}\n    A[Start] --> B[Process]\n    B --> C{{Decision}}\n    C -->|Yes| D[End]\n    C -->|No| B",
            "sequence": f"sequenceDiagram\n    %% {description}\n    participant A\n    participant B\n    A->>B: Request\n    B-->>A: Response",
            "erDiagram": f"erDiagram\n    %% {description}\n    ENTITY1 {{string id}}\n    ENTITY2 {{string id}}\n    ENTITY1 ||--o{{ ENTITY2 : has",
            "classDiagram": f"classDiagram\n    %% {description}\n    class MyClass {{\n        +String name\n        +method()\n    }}",
        }
        mermaid = templates.get(kind, templates["flowchart"])
        note = (
            f"Note: pass `path` (a real .py file) with kind='{kind}' to derive this "
            f"from actual code instead."
            if kind in ("classDiagram", "flowchart")
            else f"Note: customize the template above to match your actual {kind} structure "
            "— sequence/ER diagrams aren't derivable from static analysis alone."
        )
        return f"```mermaid\n{mermaid}\n```\n\n{note}"

    def export_markdown_h(inp: dict[str, Any]) -> str:
        fpath = root / str(inp["path"])
        output_name = str(inp.get("output", str(inp["path"]).replace(".md", ".html")))
        out_path = root / output_name
        try:
            text = fpath.read_text(encoding="utf-8")
            try:
                import markdown as _md

                html = _md.markdown(text, extensions=["fenced_code", "tables"])
            except ImportError:
                html = f"<pre>{text}</pre>"
            out_path.write_text(
                f"<!DOCTYPE html><html><body>{html}</body></html>", encoding="utf-8"
            )
            return f"Exported to {output_name}"
        except Exception as e:
            return f"[ERROR] export_markdown: {e}"

    def find_unused_imports_h(inp: dict[str, Any]) -> str:
        path = str(inp.get("path", "."))
        target = str(root / path)
        try:
            r = subprocess.run(
                ["python", "-m", "ruff", "check", "--select=F401", target],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=30,
            )
            return r.stdout.strip() or "✅ No unused imports found"
        except Exception as e:
            return f"[ERROR] find_unused_imports: {e}"

    def deps_outdated_h(inp: dict[str, Any]) -> str:
        manager = str(inp.get("manager", "auto"))
        directory = str(inp.get("directory", "."))
        target_dir = str(root / directory)
        if manager == "auto":
            has_pip = (root / "requirements.txt").exists() or (
                root / "pyproject.toml"
            ).exists()
            has_npm = (root / "package.json").exists()  # noqa: F841
            manager = "pip" if has_pip else "npm"
        try:
            if manager == "pip":
                r = subprocess.run(
                    ["pip", "list", "--outdated", "--format=columns"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            else:
                r = subprocess.run(
                    ["npm", "outdated"],
                    capture_output=True,
                    text=True,
                    cwd=target_dir,
                    timeout=60,
                )
            return r.stdout.strip() or "✅ All dependencies are up to date"
        except Exception as e:
            return f"[ERROR] deps_outdated: {e}"

    def check_license_compliance_h(inp: dict[str, Any]) -> str:
        # AUDIT_Q_BATCH11 §85 "Licensing policy enforcement" — real SPDX-
        # based classification of every installed package's license
        # (app/policy/license_check.py), not a placeholder.
        from app.policy.license_check import (
            format_report,
            scan_installed_package_licenses,
        )

        try:
            report = scan_installed_package_licenses()
            return format_report(report)
        except Exception as e:
            return f"[ERROR] check_license_compliance: {e}"

    def loc_stats_h(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", "."))
        target = root / directory
        totals: dict[str, int] = {}
        try:
            for fp in target.rglob("*"):
                if fp.is_file() and not any(
                    p in str(fp)
                    for p in [".git", "__pycache__", "node_modules", ".venv"]
                ):
                    ext = fp.suffix or "(no ext)"
                    try:
                        n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                        totals[ext] = totals.get(ext, 0) + n
                    except Exception:
                        pass
            rows = sorted(totals.items(), key=lambda x: -x[1])[:20]
            out = "\n".join(f"{ext:15} {n:>8,}" for ext, n in rows)
            return f"{'Extension':15} {'Lines':>8}\n{'-' * 25}\n{out}\n{'':15} {sum(totals.values()):>8,} total"
        except Exception as e:
            return f"[ERROR] loc_stats: {e}"

    def npm_install_h(inp: dict[str, Any]) -> str:
        # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
        # real gap found: `session` is never non-None for any real caller
        # of make_chat_handlers() (grepped every real call site in the
        # repo — none pass one; npm_install isn't in any one-shot agent's
        # allowed_tools either). npm_install/npm_run/pip_install are
        # advertised to the interactive chat agent via CHAT_TOOLS but had
        # NO dispatch in chat_agent.py at all — a real, separate bug,
        # fixed there in this same pass (see that file). Simplified here
        # to state the real constraint plainly instead of dead async
        # plumbing that could never execute.
        return "[BLOCKED] npm_install requires interactive session for safety confirmation"

    # tool_enhance.md productionization pass, tool #54 (2026-08-20) — real
    # gap found: same shape as npm_install_h/pip_install_h right below
    # (no real one-shot caller, grepped; a real side effect — arbitrary
    # script execution). Unlike those two, this handler had NOT been
    # blocked, and its own directory field was never validated either —
    # proved live, a real malicious package.json script placed outside
    # the repo was genuinely executed via this exact handler, with zero
    # confirmation gate anywhere. Brought in line with its own siblings.
    def npm_run_h(inp: dict[str, Any]) -> str:
        return "[BLOCKED] npm_run requires interactive session for safety confirmation"

    def pip_install_h(inp: dict[str, Any]) -> str:
        # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
        # same real gap as npm_install_h above. Re-audited during tool #55
        # (2026-08-20): still correct, no changes needed — see
        # app/tools/execution/pip_install.py's own docstring.
        return "[BLOCKED] pip_install requires interactive session for safety confirmation"

    def pip_list_h(inp: dict[str, Any]) -> str:
        name_filter = str(inp.get("filter", ""))
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=columns"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = r.stdout.strip().splitlines()
            if name_filter:
                lines = [
                    ln
                    for ln in lines
                    if name_filter.lower() in ln.lower() or ln.startswith("Package")
                ]
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] pip_list: {e}"

    def create_directory_h(inp: dict[str, Any]) -> str:
        path = str(inp["path"])
        if _is_protected_path(path, repo_path):
            return f"[POLICY DENIED] Cannot create directory in protected path: {path}"
        target = root / path
        try:
            target.mkdir(parents=True, exist_ok=True)
            return f"Created directory: {path}"
        except Exception as e:
            return f"[ERROR] create_directory: {e}"

    def http_request_h(inp: dict[str, Any]) -> str:
        import urllib.request as _req
        import urllib.error as _uerr

        method = str(inp["method"]).upper()
        url = str(inp["url"])
        headers = dict(inp.get("headers") or {})
        body = inp.get("body")
        try:
            data = body.encode("utf-8") if body else None
            req = _req.Request(url, data=data, method=method, headers=headers)
            with _req.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                text = raw.decode("utf-8", errors="replace")[:3000]
                return f"HTTP {resp.status} {resp.reason}\n{text}"
        except _uerr.HTTPError as e:
            return f"HTTP {e.code} {e.reason}"
        except Exception as e:
            return f"[ERROR] http_request: {e}"

    def base64_encode_h(inp: dict[str, Any]) -> str:
        import base64 as _b64

        decode = bool(inp.get("decode", False))
        text = inp.get("text")
        path = inp.get("path")
        try:
            if path:
                raw = (root / str(path)).read_bytes()
                if decode:
                    return _b64.b64decode(raw).decode("utf-8", errors="replace")
                return _b64.b64encode(raw).decode("ascii")
            if text:
                if decode:
                    return _b64.b64decode(str(text).encode("utf-8")).decode(
                        "utf-8", errors="replace"
                    )
                return _b64.b64encode(str(text).encode("utf-8")).decode("ascii")
            return "[ERROR] Provide either text or path"
        except Exception as e:
            return f"[ERROR] base64_encode: {e}"

    def template_render_h(inp: dict[str, Any]) -> str:
        template_str = inp.get("template")
        path = inp.get("path")
        variables = dict(inp.get("vars") or {})
        try:
            from jinja2 import Template as _Tpl

            if path:
                template_str = (root / str(path)).read_text(encoding="utf-8")
            if not template_str:
                return "[ERROR] Provide either template or path"
            return str(_Tpl(str(template_str)).render(**variables))
        except ImportError:
            src = (
                str(template_str)
                if template_str
                else ((root / str(path)).read_text(encoding="utf-8") if path else "")
            )
            if not src:
                return "[ERROR] jinja2 not installed and no template provided"
            for k, v in variables.items():
                src = src.replace("{{" + k + "}}", str(v)).replace(
                    "{{ " + k + " }}", str(v)
                )
            return src
        except Exception as e:
            return f"[ERROR] template_render: {e}"

    handlers["git_tag"] = git_tag_h
    handlers["git_log_file"] = git_log_file_h
    handlers["semver_bump"] = semver_bump_h
    handlers["git_stash_list"] = git_stash_list_h
    handlers["list_processes"] = list_processes_h
    handlers["list_open_ports"] = list_open_ports_h
    handlers["wait_for_port"] = wait_for_port_h
    handlers["check_url_status"] = check_url_status_h
    handlers["cpu_profile"] = cpu_profile_h
    handlers["zip_files"] = zip_files_h
    handlers["unzip_files"] = unzip_files_h
    handlers["move_file"] = move_file_h
    handlers["hash_file"] = hash_file_h
    handlers["count_lines"] = count_lines_h
    handlers["read_env_var"] = read_env_var_h
    handlers["list_env_vars"] = list_env_vars_h
    handlers["env_diff"] = env_diff_h
    handlers["json_query"] = json_query_h
    handlers["yaml_validate"] = yaml_validate_h
    handlers["json_validate"] = json_validate_h
    handlers["csv_preview"] = csv_preview_h
    handlers["xml_validate"] = xml_validate_h
    handlers["read_notebook"] = read_notebook_h
    handlers["parse_dockerfile"] = parse_dockerfile_h
    handlers["parse_docker_compose"] = parse_docker_compose_h
    handlers["github_inspect_repo"] = github_inspect_repo_h
    handlers["openapi_inspect"] = openapi_inspect_h
    handlers["generate_diagram"] = generate_diagram_h
    handlers["summarize_output"] = summarize_output_h
    handlers["export_markdown"] = export_markdown_h
    handlers["find_unused_imports"] = find_unused_imports_h
    handlers["deps_outdated"] = deps_outdated_h
    handlers["check_license_compliance"] = check_license_compliance_h
    handlers["loc_stats"] = loc_stats_h
    handlers["npm_install"] = npm_install_h
    handlers["npm_run"] = npm_run_h
    handlers["pip_install"] = pip_install_h
    handlers["pip_list"] = pip_list_h
    handlers["create_directory"] = create_directory_h
    handlers["http_request"] = http_request_h
    handlers["base64_encode"] = base64_encode_h
    handlers["template_render"] = template_render_h

    return handlers


# ---------------------------------------------------------------------------
# Day 9 — Fleet Enhancement Dashboard tools
#
# Shared by the 5 self-improvement agents (agent_performance_reviewer,
# agent_debugger, agent_advisor, knowledge_curator, quality_auditor). These
# agents target the Gridiron project's own codebase (settings.fleet_self_repo_path),
# not a user-connected repo.
#
# SCAN phase (autonomous, read-only): fleet_metrics_read, audit_log_read,
# task_history_query (already exists above), memory_search, memory_curate_read,
# submit_enhancement_request — writes a pending row, nothing else happens.
#
# APPLY phase (only after human approval on a specific request):
# memory_curate_write, git_commit_change — stages only the named files, never `-A`.
# ---------------------------------------------------------------------------


def _new_isolated_db_engine() -> Any:
    """A throwaway async engine, NOT the shared app.db.session singleton.

    Tool handlers are sync functions called from arbitrary contexts (a fleet
    agent's scan loop may call several DB tools in the same process run).
    asyncio.run() opens and tears down its own event loop per call; the shared
    engine/pool in app.db.session gets bound to whichever loop first touched
    it, so reusing it across multiple asyncio.run() calls raises
    "Future attached to a different loop". A fresh, disposed-after-use engine
    per call avoids that entirely — slightly less efficient, always correct.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings as _gs

    return create_async_engine(_gs().database_url, pool_pre_ping=True)


_FLEET_METRICS_READ_TOOL: dict[str, Any] = {
    "name": "fleet_metrics_read",
    "description": "Read real runtime performance data for an agent (or the whole fleet): recent runs, p50/p95 latency, average tool accuracy. Use this before claiming an agent is slow or unreliable — never guess.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Agent to inspect. Omit to see the most recent runs across all agents.",
            },
            "n": {
                "type": "integer",
                "description": "Max runs to consider (default 20).",
            },
        },
        "required": [],
    },
}


def fleet_metrics_read(inp: dict[str, Any]) -> str:
    from app.fleet.metrics import get_metrics_collector

    agent_name = str(inp.get("agent_name", "")).strip()
    n = int(inp.get("n", 20))
    collector = get_metrics_collector()

    if not agent_name:
        runs = collector.recent(n)
        if not runs:
            return "(no runs recorded yet)"
        lines = [
            f"{m.agent_name}: status={m.status} time={m.execution_time_ms:.0f}ms tokens_in={m.tokens_in} tokens_out={m.tokens_out}"
            for m in runs
        ]
        return "\n".join(lines)

    runs = collector.by_agent(agent_name, n)
    if not runs:
        return f"(no recorded runs for agent {agent_name!r})"
    p50 = collector.p50_latency_ms(agent_name)
    p95 = collector.p95_latency_ms(agent_name)
    accuracy = collector.avg_tool_accuracy(agent_name)
    failed = sum(1 for m in runs if m.status == "failed")
    lines = [
        f"agent: {agent_name}",
        f"runs considered: {len(runs)} (failed: {failed})",
        f"p50 latency: {p50:.0f}ms" if p50 is not None else "p50 latency: n/a",
        f"p95 latency: {p95:.0f}ms" if p95 is not None else "p95 latency: n/a",
        (
            f"avg tool accuracy: {accuracy:.2f}"
            if accuracy is not None
            else "avg tool accuracy: n/a"
        ),
    ]
    return "\n".join(lines)


_AUDIT_LOG_READ_TOOL: dict[str, Any] = {
    "name": "audit_log_read",
    "description": "Read the fleet audit trail: what actions ran, for which agent, with what outcome. Use this to diagnose failing agents from real evidence, not speculation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Filter to one agent. Omit for the most recent entries across all agents.",
            },
            "n": {
                "type": "integer",
                "description": "Max entries to return (default 50).",
            },
        },
        "required": [],
    },
}


def audit_log_read(inp: dict[str, Any]) -> str:
    from app.fleet.audit_log import get_audit_log

    agent_name = str(inp.get("agent_name", "")).strip()
    n = int(inp.get("n", 50))
    log = get_audit_log()
    entries = log.recent(max(n, 200))
    if agent_name:
        entries = [e for e in entries if e.agent_name == agent_name]
    entries = entries[-n:]
    if not entries:
        return f"(no audit entries{f' for agent {agent_name!r}' if agent_name else ''})"
    lines = [
        f"[{e.timestamp}] {e.agent_name} — {e.action_type} — outcome={e.outcome}"
        + (f" — {e.description}" if e.description else "")
        for e in entries
    ]
    return "\n".join(lines)


_CAPABILITY_GAP_SCAN_TOOL: dict[str, Any] = {
    "name": "capability_gap_scan",
    "description": (
        "AUDIT_Q_BATCH15 §76 gap-closure — deterministically cluster real AgentRun "
        "history by agent_type and surface any agent whose real failure count/rate "
        "over the scan window crosses a real threshold, with real sample error text "
        "from those failed runs. Use this instead of trying to eyeball a capability "
        "gap from raw task_history_query output — the clustering itself is already "
        "computed for you here, not something to infer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "window_days": {
                "type": "integer",
                "description": "Lookback window in days (default 14).",
            },
            "min_failures": {
                "type": "integer",
                "description": "Minimum failed-run count for an agent to be reported (default 3).",
            },
            "min_failure_rate": {
                "type": "number",
                "description": "Minimum failure rate (0.0-1.0) for an agent to be reported (default 0.3).",
            },
        },
        "required": [],
    },
}


def capability_gap_scan(inp: dict[str, Any]) -> str:
    """Sync tool handler — bridges to the async DB query the same way every
    other DB-backed sync tool handler in this module does (new isolated
    engine + asyncio.run(), never the shared app.db.session engine — see
    feedback_asyncio_isolated_engine)."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine
    from app.fleet.capability_gap import (
        format_capability_gap_report,
        scan_capability_gaps,
    )

    window_days = int(inp.get("window_days", 14))
    min_failures = int(inp.get("min_failures", 3))
    min_failure_rate = float(inp.get("min_failure_rate", 0.3))

    async def _run() -> str:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                clusters = await scan_capability_gaps(
                    db,
                    window_days=window_days,
                    min_failures=min_failures,
                    min_failure_rate=min_failure_rate,
                )
                return format_capability_gap_report(clusters)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        return f"[ERROR] capability_gap_scan failed: {exc}"


_SUBMIT_ENHANCEMENT_REQUEST_TOOL: dict[str, Any] = {
    "name": "submit_enhancement_request",
    "description": (
        "File a proposed enhancement for human review on the Fleet Dashboard. "
        "Call this only when you have real evidence for a genuine issue or improvement — "
        "an empty scan with nothing to report is a normal, expected outcome, not a failure. "
        "This only creates a pending request; nothing changes on disk until a human approves it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title, plain language."},
            "description": {
                "type": "string",
                "description": "Full explanation in plain, non-technical-jargon language — this is what the human reads to decide approve/reject.",
            },
            "category": {
                "type": "string",
                "enum": [
                    "performance",
                    "bug",
                    "orchestration",
                    "knowledge",
                    "quality",
                    "security",
                ],
            },
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {
                "type": "object",
                "description": "file:line citations, metrics, or other evidence backing this claim.",
            },
        },
        "required": ["title", "description", "category", "priority"],
    },
}


def make_submit_enhancement_request_handler(
    agent_name: str, trace_id: str = "", repo_path: str = ""
) -> Any:
    def submit_enhancement_request(inp: dict[str, Any]) -> str:
        import asyncio

        # AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — pre-change impact
        # simulation, computed here (SCAN/submission time, before ANY human
        # decision) so it's visible on the row the human actually reviews,
        # not bolted on after approval. Best-effort: a simulation failure
        # must never block filing the request itself — see this function's
        # own docstring for why an empty report is the honest fallback, not
        # a fabricated one.
        try:
            from app.fleet.enhancement_impact import simulate_enhancement_impact

            impact = simulate_enhancement_impact(
                repo_path, str(inp["description"]), dict(inp.get("evidence") or {})
            )
        except Exception:
            impact = None

        async def _write() -> int:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import EnhancementRequest

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(
                    engine, expire_on_commit=False
                )() as session:
                    row = EnhancementRequest(
                        agent_name=agent_name,
                        title=str(inp["title"]),
                        description=str(inp["description"]),
                        category=str(inp["category"]),
                        priority=str(inp["priority"]),
                        evidence=dict(inp.get("evidence") or {}),
                        status="pending",
                        trace_id=trace_id or None,
                        impact_simulation=impact,
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    return int(row.id)
            finally:
                await engine.dispose()

        try:
            req_id = asyncio.run(_write())
        except Exception as exc:
            return f"[ERROR] Could not file enhancement request: {exc}"

        try:
            from app.services.activity_stream import get_activity_registry

            stream = get_activity_registry().get_or_create("fleet-dashboard")
            stream.push(
                {
                    "type": "new_request",
                    "id": req_id,
                    "agentName": agent_name,
                    "title": str(inp["title"]),
                    "priority": str(inp["priority"]),
                    "category": str(inp["category"]),
                }
            )
        except Exception:
            pass  # dashboard notification is non-fatal — the row is already written

        return f"Enhancement request #{req_id} filed for human review."

    return submit_enhancement_request


_MEMORY_SEARCH_TOOL: dict[str, Any] = {
    "name": "memory_search",
    "description": "Semantic search over the fleet's persistent engineering memory (past task outcomes, architecture decisions, failures, lessons) — NOT the same as memory_read/memory_write (those are a different, per-repo scratch store). Searches fleet-wide (across every repo) by default — pass repo_id only to narrow to one specific repo's own memories plus fleet-wide/legacy ones.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "top_k": {"type": "integer", "description": "Max results (default 5)."},
            "repo_id": {
                "type": "integer",
                "description": "Stage 4 Cluster O Phase 1d (2026-08-05): optional — restrict "
                "results to this repo's own memories plus fleet-wide/legacy ones. Omit to "
                "search fleet-wide (the default, and the right choice for this tool's real "
                "caller, knowledge_curator, whose job is curating memory across the whole "
                "fleet, not one repo).",
            },
        },
        "required": ["query"],
    },
}


def memory_search(inp: dict[str, Any]) -> str:
    import asyncio

    query = str(inp.get("query", "")).strip()
    if not query:
        return "[ERROR] query is required"
    top_k = int(inp.get("top_k", 5))
    repo_id_raw = inp.get("repo_id")
    repo_id: int | None = int(repo_id_raw) if repo_id_raw is not None else None

    async def _search() -> list[dict[str, Any]]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.memory.store import query_similar_tasks

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await query_similar_tasks(
                    description=query, db=session, top_k=top_k, repo_id=repo_id
                )
        finally:
            await engine.dispose()

    try:
        results = asyncio.run(_search())
    except Exception as exc:
        return f"[ERROR] memory_search failed: {exc}"
    if not results:
        return "(no similar memories found)"
    lines = [
        f"[{r.get('similarity', 0):.2f}] task={r.get('task_id')} outcome={r.get('outcome')} — {str(r.get('summary', ''))[:200]}"
        for r in results
    ]
    return "\n".join(lines)


_MEMORY_CURATE_READ_TOOL: dict[str, Any] = {
    "name": "memory_curate_read",
    "description": "List engineering-memory entries for curation review (duplicates, stale entries, mis-categorized entries) — distinct from memory_search (similarity search) and from memory_read (unrelated per-repo scratch store).",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter: task | architecture | failure | learning. Omit for all.",
            },
            "limit": {"type": "integer", "description": "Max rows (default 20)."},
        },
        "required": [],
    },
}


def memory_curate_read(inp: dict[str, Any]) -> str:
    import asyncio

    category = str(inp.get("category", "")).strip()
    limit = int(inp.get("limit", 20))

    async def _list() -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import MemoryEmbedding

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                q = (
                    select(MemoryEmbedding)
                    .order_by(MemoryEmbedding.created_at.desc())
                    .limit(limit)
                )
                if category:
                    q = q.where(MemoryEmbedding.category == category)
                result = await session.execute(q)
                rows = result.scalars().all()
                return [
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "category": r.category,
                        "outcome": r.outcome,
                        "summary": r.summary[:200],
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
        finally:
            await engine.dispose()

    try:
        rows = asyncio.run(_list())
    except Exception as exc:
        return f"[ERROR] memory_curate_read failed: {exc}"
    if not rows:
        return "(no memory entries found)"
    return "\n".join(
        f"#{r['id']} [{r['category']}] {r['outcome']} ({r['created_at']}) — {r['summary']}"
        for r in rows
    )


_MEMORY_LIST_DRAFT_LESSONS_TOOL: dict[str, Any] = {
    "name": "memory_list_draft_lessons",
    "description": (
        "List versioned lessons currently in draft state, awaiting review. "
        "Gap-closure Day 6: every record_learning call now files a draft, "
        "not a published lesson — this is how a curation pass finds what's "
        "actually pending, distinct from memory_curate_read (which only "
        "ever sees the older, unversioned memory_embeddings table)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max rows (default 20)."},
        },
        "required": [],
    },
}


def memory_list_draft_lessons(inp: dict[str, Any]) -> str:
    import asyncio

    limit = int(inp.get("limit", 20))

    async def _list() -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import VersionedLesson

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(VersionedLesson)
                    .where(VersionedLesson.state == "draft")
                    .order_by(VersionedLesson.created_at.desc())
                    .limit(limit)
                )
                rows = result.scalars().all()
                return [
                    {
                        "lesson_id": r.lesson_id,
                        "topic": r.topic,
                        "version": r.version,
                        "content": r.content[:300],
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                    }
                    for r in rows
                ]
        finally:
            await engine.dispose()

    try:
        rows = asyncio.run(_list())
    except Exception as exc:
        return f"[ERROR] memory_list_draft_lessons failed: {exc}"
    if not rows:
        return "(no draft lessons pending review)"
    return "\n".join(
        f"lesson_id={r['lesson_id']} v{r['version']} [{r['topic']}] "
        f"({r['created_at']}) — {r['content']}"
        for r in rows
    )


_MEMORY_CURATE_WRITE_TOOL: dict[str, Any] = {
    "name": "memory_curate_write",
    "description": "Update a memory entry during curation (recategorize, or mark as a superseded duplicate by rewriting its summary to note the supersession). Precursor to the full versioned-lesson lifecycle — light-touch, not a rewrite of history.",
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "MemoryEmbedding row id."},
            "category": {
                "type": "string",
                "description": "New category, if recategorizing.",
            },
            "note": {
                "type": "string",
                "description": "Note to append to the summary, e.g. superseded-by info.",
            },
        },
        "required": ["id"],
    },
}


def memory_curate_write(inp: dict[str, Any]) -> str:
    import asyncio

    row_id = int(inp["id"])
    new_category = inp.get("category")
    note = inp.get("note")
    if not new_category and not note:
        return "[ERROR] provide category and/or note — nothing to update"

    async def _update() -> bool:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import MemoryEmbedding

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await session.get(MemoryEmbedding, row_id)
                if row is None:
                    return False
                if new_category:
                    row.category = str(new_category)
                if note:
                    row.summary = f"{row.summary}\n[curated] {note}"
                await session.commit()
                return True
        finally:
            await engine.dispose()

    try:
        found = asyncio.run(_update())
    except Exception as exc:
        return f"[ERROR] memory_curate_write failed: {exc}"
    if not found:
        return f"[ERROR] No memory entry with id={row_id}"
    return f"Memory entry #{row_id} updated."


_MEMORY_PROMOTE_LESSON_TOOL: dict[str, Any] = {
    "name": "memory_promote_lesson",
    "description": (
        "Promote a DRAFT versioned lesson to PUBLISHED, making it real, "
        "queryable fleet memory. Gap-closure Day 6: every lesson any agent "
        "records now lands in draft state, invisible to the fleet, until "
        "this is called — only ever call it after actually reading the "
        "draft's real content (via memory_curate_read or the lesson's own "
        "id) and judging it genuinely worth promoting, never reflexively."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lesson_id": {
                "type": "string",
                "description": "The stable lesson_id (not the row id) of the draft to promote.",
            },
        },
        "required": ["lesson_id"],
    },
}


def memory_promote_lesson(inp: dict[str, Any]) -> str:
    from app.fleet.versioned_memory import get_versioned_memory_store

    lesson_id = str(inp["lesson_id"])
    try:
        record = get_versioned_memory_store().promote(
            lesson_id, agent_name="knowledge_curator"
        )
    except ValueError as exc:
        return f"[ERROR] {exc}"
    except Exception as exc:
        return f"[ERROR] memory_promote_lesson failed: {exc}"
    return f"Lesson {lesson_id!r} (row #{record.id}) promoted to published."


# delegate_to_agent — plan14 Day 4 (#1 Agent-to-Agent Delegation). Real
# invocation, real safety guards (depth/cycle/policy/budget/timeout) — see
# app/agents/delegation.py's own module docstring for the full design.
# Tool spec + handler factory moved to app/tools/agents/delegate.py —
# tool_enhance.md productionization pass, tool #3 (2026-08-15). See that
# module's TOOL PATH MIGRATION REPORT.

# Appended (not inserted into the list literal above) because BUG_FIX_TOOLS
# is defined earlier in this file, before _DELEGATE_TO_AGENT_TOOL exists —
# module-level code runs top-to-bottom once, so mutating the already-built
# list here takes effect for every importer exactly the same as if it had
# been in the original literal.
BUG_FIX_TOOLS.append(_DELEGATE_TO_AGENT_TOOL)


# PROPOSE_SUBTASK_TOOL / make_propose_subtask_handler moved to
# app/tools/agents/propose_subtask.py — tool_enhance.md productionization
# pass, tool #7 (2026-08-16). See that module's TOOL PATH MIGRATION
# REPORT.


_GIT_COMMIT_CHANGE_TOOL: dict[str, Any] = {
    "name": "git_commit_change",
    "description": "Stage exactly the named files (never all changes) and commit them. Only usable in the APPLY phase, after a human has approved this specific fix.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths (relative to repo root) to stage. Never pass a wildcard — list every file explicitly.",
            },
            "message": {"type": "string", "description": "Commit message."},
        },
        "required": ["files", "message"],
    },
}


def make_git_commit_change_handler(repo_path: str) -> Any:
    def git_commit_change(inp: dict[str, Any]) -> str:
        files = [str(f) for f in (inp.get("files") or [])]
        message = str(inp.get("message", "")).strip()
        if not files:
            return "[ERROR] files is required — list every file explicitly, never a wildcard"
        if not message:
            return "[ERROR] message is required"

        for f in files:
            result = check_path_in_worktree(f, repo_path)
            if not result.allowed:
                return f"[POLICY DENIED] {f}: {result.reason}"
            fpath = Path(repo_path) / f
            if fpath.is_file():
                try:
                    fcontent = fpath.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    fcontent = ""
                secret_reason = _scan_content_for_secrets(fcontent)
                if secret_reason:
                    return (
                        f"[POLICY DENIED] Refusing to commit {f}: {secret_reason}. "
                        "Remove the secret and use an environment variable/config "
                        "reference instead."
                    )

        try:
            add_result = subprocess.run(
                ["git", "add", "--"] + files,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if add_result.returncode != 0:
                return f"[ERROR] git add failed: {add_result.stderr.strip()}"
            commit_result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if commit_result.returncode != 0:
                return f"[ERROR] git commit failed: {(commit_result.stdout + commit_result.stderr).strip()}"
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            sha = sha_result.stdout.strip()
            return f"Committed {len(files)} file(s) as {sha[:12]}: {message}"
        except subprocess.TimeoutExpired:
            return "[ERROR] git operation timed out"
        except Exception as exc:
            return f"[ERROR] {exc}"

    return git_commit_change


def _role_prompt_name(rel: str) -> str | None:
    """Returns the role_name if rel is exactly roles/<role_name>.md, else None."""
    p = Path(rel)
    if len(p.parts) == 2 and p.parts[0] == "roles" and p.suffix == ".md":
        return p.stem
    return None


def _propose_and_deploy_role_prompt(
    role_name: str, content: str, agent_name: str
) -> str:
    """Route a role-prompt change through prompt_registry's real
    propose -> submit_for_review -> approve -> deploy lifecycle instead of a
    raw disk write — gap-closure Day 50 (answers.md Q35/Q36/Phase-6 finding
    #8): this shared handler was the one real production path that touched
    roles/*.md files, and it bypassed the built regression-gated approval
    machinery entirely, leaving prompt_registry.deploy() with no real
    caller. The enclosing enhancement_request is already human-approved
    before this APPLY-phase handler ever runs, so auto-advancing through
    review/approval here reuses oversight that already happened rather than
    skipping it — while still real-checking the regression gate before any
    write reaches disk."""
    from app.fleet.prompt_registry import get_prompt_registry
    from app.fleet.regression_detector import DeploymentBlocked

    registry = get_prompt_registry()
    version = registry.propose(role_name, content, proposed_by=agent_name)
    if version.status == "deployed":
        return (
            f"No change: {role_name}.md content already matches the deployed "
            f"version (v{version.version_number})."
        )
    try:
        registry.submit_for_review(version.id)
        registry.approve(version.id, approved_by=f"{agent_name}-post-human-approval")
        deployed = registry.deploy(version.id)
    except DeploymentBlocked as exc:
        return (
            f"[BLOCKED] Regression gate blocked deploying {role_name}.md "
            f"v{version.version_number}: {exc}"
        )
    return (
        f"Deployed {role_name}.md as v{deployed.version_number} via "
        f"prompt_registry (id={deployed.id})."
    )


def make_fleet_apply_handlers(
    repo_path: str, agent_name: str = "fleet_apply"
) -> dict[str, Any]:
    """Shared APPLY-phase handler set for the 4 write-capable fleet-enhancement
    agents (agent_performance_reviewer, agent_debugger, knowledge_curator,
    quality_auditor) — only ever invoked after a human approves a specific
    enhancement request. read_file + write_file + edit_file + run_tests +
    git_commit_change, all scoped to repo_path (settings.fleet_self_repo_path).

    write_file/edit_file targeting roles/<name>.md are routed through
    prompt_registry (see _propose_and_deploy_role_prompt) instead of a raw
    disk write — gap-closure Day 50."""
    base = Path(repo_path)

    # Non-role-prompt branch moved to app/tools/filesystem/write_file.py as
    # write_file_handler — tool_enhance.md productionization pass, tool #12
    # (2026-08-17).
    def write_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        role_name = _role_prompt_name(rel)
        if role_name is not None:
            return _propose_and_deploy_role_prompt(
                role_name, str(inp["content"]), agent_name
            )
        return write_file_handler(base, repo_path, inp)

    def edit_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        role_name = _role_prompt_name(rel)
        if role_name is not None:
            # Role-prompt content is authoritatively tracked by
            # prompt_registry (its deployed row), which may live outside
            # repo_path — read the current text from there, not `base / rel`.
            from app.fleet.prompt_registry import get_prompt_registry

            deployed = get_prompt_registry().get_deployed(role_name)
            if deployed is None:
                return f"[ERROR] File not found: {rel}"
            text = deployed.content
        else:
            target = base / rel
            if not target.exists():
                return f"[ERROR] File not found: {rel}"
            text = target.read_text(encoding="utf-8")
        old_s, new_s = str(inp["old_string"]), str(inp["new_string"])
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel} — must be unique"
        new_text = text.replace(old_s, new_s, 1)
        if role_name is not None:
            return _propose_and_deploy_role_prompt(role_name, new_text, agent_name)
        target.write_text(new_text, encoding="utf-8")
        return f"Edited {rel}"

    def run_tests_h(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        path = str(inp.get("path", "backend/tests/"))
        flags = str(inp.get("flags", ""))
        flags_reason = _shell_metachar_reason(flags, "flags")
        if flags_reason:
            return f"[POLICY DENIED] {flags_reason}"
        # Gap-closure Day 15: no trailing `| tail -50` — a shell pipeline's
        # exit code is the LAST command's (tail always exits 0), which was
        # silently destroying pytest's real exit code before the check
        # below could ever see it. Output truncation is Python-side only.
        # Gap-closure Day 15: `;` after the activation attempt is a POSIX-only
        # separator — under cmd.exe (Windows' subprocess.run(shell=True)
        # default), it isn't a statement separator at all, so a failed
        # `source` (no such builtin on Windows) aborts the whole line before
        # pytest ever runs. `&& ... || true &&` matches
        # make_chat_handlers.run_tests's already-working pattern, which
        # degrades safely on both shells.
        cmd = f"cd {repo_path} && {_venv_activate_snippet()} && python -m pytest {_shlex.quote(path)} {flags} -q --tb=short 2>&1"
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=180
            )
            out = (r.stdout or r.stderr or "(no output)")[-3000:]
            # Gap-closure Day 15 (Stage 1.2, answers.md) — same fix as
            # make_chat_handlers.run_tests above: agent_debugger/
            # agent_performance_reviewer/quality_auditor all map
            # "run_tests" -> "tests_run"/"tests_passed" in their APPLY-mode
            # VerificationConfig; without this, a real failing test run was
            # indistinguishable from a passing one to that flag.
            if r.returncode != 0:
                return f"[ERROR] Tests failed (exit code {r.returncode}):\n{out}"
            return out
        except subprocess.TimeoutExpired:
            return "[ERROR] tests timed out"

    return {
        "read_file": make_read_only_handlers(repo_path)["read_file"],
        "write_file": write_file_h,
        "edit_file": edit_file_h,
        "run_tests": run_tests_h,
        "git_commit_change": make_git_commit_change_handler(repo_path),
    }


FLEET_APPLY_TOOLS = [
    READ_ONLY_TOOLS[0],
    _WRITE_FILE_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _RUN_TESTS_TOOL,
    _GIT_COMMIT_CHANGE_TOOL,
]

# _FLEET_BASH_TOOL + make_scoped_bash_handler moved to
# app/tools/execution/bash.py (tool_enhance.md productionization pass,
# tool #1, 2026-08-15) — imported at the top of this file for backward
# compatibility.
