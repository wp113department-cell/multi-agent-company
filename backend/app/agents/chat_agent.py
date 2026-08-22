"""Interactive streaming chat agent — the core of the conversational interface.

MASTER_AGENT_v2.md Phase 5.2 — chat_agent.py is now a real, interrupt()-based
LangGraph graph (`ChatAgent._build_chat_graph()`), replacing the old bespoke
`asyncio.Event`-based pause mechanism.

The first attempt at this (superseded) wrapped the whole `run()` loop as a
single graph node and called `interrupt()` from inside
`session.request_confirmation()`. That was rejected as unsafe: LangGraph
re-runs a node's ENTIRE body from the top on `Command(resume=...)`, and a
single node covering the whole loop would replay every tool call — including
real side effects like `git push` and `bash` — that already ran earlier in
that same node before the confirmation point. Confirmed directly (not by
inference): a two-line reproduction script showed a side effect placed
before `interrupt()` within one node executing twice across a pause/resume
cycle, while a side effect in an *already-completed, separate* node never
re-executes at all.

That is the actual fix applied here: **every tool call is its own graph
node**, not a Python `for` loop inside one node. `call_llm` (one LLM
streaming turn) and `execute_tool` (one tool call, looping back to itself
via a conditional edge until a turn's tool_use batch is drained, then
handing back to `call_llm`) are separate, independently checkpointed steps.
A confirmation-gated tool's handler calls `interrupt()` as the very first
side-effecting-adjacent step of its branch (verified true for all 8 real
call sites — `git_push`, dangerous `bash`, `git_reset --hard`,
`undo_changes`, `run_migration`, `seed_database`, and, as of gap-closure
Day 5, `delete_file` and `write_file`-on-an-existing-file — nothing before
the confirmation point in any of them does real work, only cheap string/path
prep). So when `execute_tool` replays after a resume: prior tool-call nodes
never re-execute (proven, not assumed); nothing inside *this* node
re-executes a side effect either, because there wasn't one before
`interrupt()` to begin with — only after, on the resumed pass, does the
node reach the actual git/bash/subprocess call, exactly once.

The `tool_use_id` Anthropic assigns each tool call (stable across replay —
it's an input read from checkpointed state, never regenerated) is reused as
the confirmation's `action_id`, instead of a fresh `uuid.uuid4()` per
attempt — a freshly generated id would itself have differed between the
paused and resumed pass, silently orphaning the pending_approvals row and
mismatching the id the client already has.

Checkpointer: PostgreSQL-backed (`init_chat_checkpointer()`/
`close_chat_checkpointer()` below, wired into FastAPI's lifespan in
app/main.py) so chat sessions survive a server restart — AUDIT_Q_BATCH08
§14 migrated this off the in-process `MemorySaver` this docstring used to
describe. `MemorySaver` is kept only as the module-level default and as an
automatic fallback if the Postgres checkpointer fails to initialize (see
`init_chat_checkpointer()`'s except-branch). Keeps `Popen` handles for
background processes (`self._background_processes`) trivially
checkpoint-compatible without a serialization story regardless of which
checkpointer backs a given session. One `ChatAgent` instance is kept alive
per session (`get_or_create_chat_agent()`) and reused across the initial
`run()` call and any later `resume()` calls for the same session, so
`thread_id=session_id` always resolves to the same checkpointer state.

Chat confirmations also still register into the generalized
`request_human_input()`/`arecord_decision()` entry point (Phase 5.5) —
`plan_review`/`git_push`/`clarification` already use, giving every human-
in-the-loop pause in the fleet, chat included, the same audit trail.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TypedDict, cast

import anthropic
from anthropic.types import (
    MessageParam,
    RawContentBlockDeltaEvent,
    TextDelta,
    ToolParam,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.base import get_effective_api_key, load_role
from app.agents.base_graph import (
    VerificationConfig,
    _flag_suspicious_tool_output,
    _policy_check,
    _select_messages_to_condense,
    _stringify_messages_for_summary,
    _wrap_untrusted_tool_content,
)
from app.agents.output_parsers import parse_diagnostic_summary
from app.agents.tools import (
    CHAT_TOOLS,
    _apply_conflict_resolutions,
    _docker_container_risk_reason,
    _is_dangerous_command,
    _is_protected_path,
    _llm_diagnose_deployment_failure,
    _llm_explain_conflict_hunks,
    _llm_generate_commit_message,
    _llm_review_diff,
    _llm_summarize_url_content,
    _parse_conflict_markers,
    _redact_secrets_in_text,
    _run_bash_command,
    _ssrf_denial_reason,
    _venv_activate_snippet,
    inspect_github_repo as _inspect_github_repo,
    inspect_openapi_spec as _inspect_openapi_spec,
)
from app.config import get_settings
from app.models.chat import ChatSession
from app.policy.engine import check_command, check_path_in_worktree
from app.repo_tools import ast_engine as _ast_engine
from app.tools.agents.memory_write import write_memory_key
from app.tools.browser.browser_tools import (
    browser_click_handler,
    browser_close_handler,
    browser_navigate_handler,
    browser_open_handler,
    browser_read_dom_handler,
    browser_screenshot_handler,
    browser_type_handler,
)
from app.tools.database.migration import validate_run_migration_inputs
from app.tools.database.seed import validate_seed_database_script
from app.tools.execution.parallel import MAX_PARALLEL_COMMANDS
from app.tools.database.sql import run_sql_handler
from app.tools.execution.docker_build import validate_docker_build_inputs
from app.tools.execution.docker_compose import build_docker_compose_command
from app.tools.execution.docker_exec import build_docker_exec_command
from app.tools.execution.docker_restart import build_docker_restart_command
from app.tools.execution.npm_install import validate_npm_install_directory
from app.tools.execution.npm_run import validate_npm_run_directory
from app.tools.execution.python_snippet import run_python_snippet_handler
from app.tools.execution.run_background import validate_run_background_cwd
from app.tools.execution.run_make import run_make_handler
from app.tools.execution.run_node import run_node_handler
from app.tools.execution.run_tests import run_tests_handler
from app.tools.filesystem.append_file import append_file_handler
from app.tools.filesystem.apply_patch import apply_patch_handler
from app.tools.filesystem.delete_block import delete_block_handler
from app.tools.filesystem.delete_lines import delete_lines_handler
from app.tools.filesystem.delete_file import delete_file_handler
from app.tools.filesystem.edit_file import edit_file_handler
from app.tools.filesystem.insert_after import insert_after_handler
from app.tools.filesystem.insert_at_line import insert_at_line_handler
from app.tools.filesystem.insert_before import insert_before_handler
from app.tools.filesystem.move_file import move_file_handler
from app.tools.filesystem.rename_file import rename_file_handler
from app.tools.filesystem.replace_class import replace_class_handler
from app.tools.filesystem.replace_function import replace_function_handler
from app.tools.filesystem.semver_bump import semver_bump_handler
from app.tools.filesystem.write_file import write_file_handler
from app.tools.git.checkout import validate_git_checkout_inputs
from app.tools.git.cherry_pick import validate_git_cherry_pick_inputs
from app.tools.git.commit import stage_and_commit
from app.tools.git.create_branch import validate_create_branch_inputs
from app.tools.git.github_comment import github_comment_command
from app.tools.git.github_create_issue import github_create_issue_command
from app.tools.git.merge import validate_git_merge_inputs
from app.tools.git.pull import validate_git_pull_inputs
from app.tools.git.pull_request import (
    build_gh_pr_create_command,
    generate_pr_description as _llm_generate_pr_description,
)
from app.tools.git.rebase import validate_git_rebase_inputs
from app.tools.git.reset import validate_git_reset_inputs
from app.tools.git.stash import validate_git_stash_action
from app.tools.git.tag import git_tag_handler
from app.tools.git.worktree import validate_git_worktree_inputs
from app.tools.integrations.linear_create_issue import create_linear_issue
from app.tools.refactor.rename_symbol import validate_rename_symbol_directory

logger = logging.getLogger(__name__)


class ChatGraphState(TypedDict, total=False):
    """MASTER_AGENT_v2.md Phase 5.2 — per-turn state for ChatAgent's graph.
    Message history itself is deliberately NOT threaded through this state
    — it lives on self.session.history (the durable, cross-turn store) and
    is mutated directly by nodes, which is safe under LangGraph's replay
    model precisely because every mutation happens either in a node that
    never contains an interrupt() (so it only ever runs once, full stop)
    or strictly after the interrupt() point within a node that does (see
    this module's own docstring for why that ordering matters)."""

    user_message: str
    system_prompt: str
    iteration: int
    pending_tool_uses: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    final_text: str
    last_error: str | None
    stop: bool
    # Gap-closure Day 16 (Stage 1.2, answers.md): _VERIFICATION_CFG below has
    # existed since this class was written but was never consulted anywhere
    # — no key on this TypedDict could even hold it, and _execute_tool_node
    # never read or wrote one. Deliberately NOT included in run()'s per-turn
    # initial_state dict — LangGraph's checkpointer merges partial state
    # updates onto what's already checkpointed for this thread_id, so
    # omitting it here means it accumulates across the whole session (a file
    # read in turn 1 still counts in turn 5), not reset every user message.
    verification: dict[str, Any]


# ---------------------------------------------------------------------------
# Per-session ChatAgent registry — MASTER_AGENT_v2.md Phase 5.2. A single
# ChatAgent instance (and its checkpointer/compiled graph) is kept alive for
# the life of a session and reused across the initial run() call and any
# later resume() calls, so thread_id=session_id always resolves to the same
# in-process checkpointer state, and instance state (self._background_processes)
# survives a pause/resume cycle exactly as it did under the old mechanism.
# ---------------------------------------------------------------------------

# AUDIT_Q_BATCH08 §14 "Checkpoints" — chat sessions were the one execution
# path left on MemorySaver (in-process, lost on crash/restart) while the
# pipeline graph (app/pipeline/graph.py) and every run_agent_graph()-based
# worker agent (app/agents/base_graph.py) were already Postgres-backed.
# Mirrors app.agents.base_graph.init_agent_checkpointer()/
# close_agent_checkpointer() exactly — same driver, same
# fallback-to-MemorySaver-on-init-failure behavior, same "called once from
# FastAPI lifespan startup" contract — kept as its own independent
# module-level checkpointer/connection rather than importing base_graph.py's
# or pipeline/graph.py's, matching the architectural boundary base_graph.py
# itself already established (its own docstring: kept independent "so
# base_graph.py ... doesn't depend on the higher-level pipeline orchestrator
# module"); the same reasoning applies one layer up here.
_chat_checkpointer: Any = MemorySaver()
_chat_pg_cm: Any = None  # holds the AsyncPostgresSaver context manager open


async def init_chat_checkpointer(database_url: str) -> None:
    """Initialize the LangGraph PostgreSQL checkpointer so chat sessions
    survive server restarts. Called once from FastAPI lifespan startup."""
    global _chat_checkpointer, _chat_pg_cm
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        psycopg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        cm = AsyncPostgresSaver.from_conn_string(psycopg_url)
        saver = await cm.__aenter__()
        await saver.setup()  # creates langgraph checkpoint tables if missing
        _chat_pg_cm = cm
        _chat_checkpointer = saver
        logger.info(
            "Chat agent PostgreSQL checkpointer initialized — chat sessions "
            "are now durably checkpointed"
        )
    except Exception as exc:
        logger.warning(
            "Chat agent PostgreSQL checkpointer init failed, falling back "
            "to MemorySaver: %s",
            exc,
        )


async def close_chat_checkpointer() -> None:
    """Close the PostgreSQL checkpointer connection. Called at FastAPI
    shutdown. Also resets _chat_checkpointer back to a fresh MemorySaver —
    mirrors base_graph.py::close_agent_checkpointer()'s own reasoning:
    without this reset, a process that inits+closes+keeps running (this
    test suite's own pattern) would keep referencing the just-closed,
    now-dead-event-loop-bound AsyncPostgresSaver."""
    global _chat_pg_cm, _chat_checkpointer
    if _chat_pg_cm is not None:
        try:
            await _chat_pg_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("Error closing chat agent checkpointer: %s", exc)
        _chat_pg_cm = None
    _chat_checkpointer = MemorySaver()


_chat_agents: dict[str, "ChatAgent"] = {}


def get_or_create_chat_agent(session: ChatSession) -> "ChatAgent":
    agent = _chat_agents.get(session.session_id)
    if agent is None:
        agent = ChatAgent(session=session)
        _chat_agents[session.session_id] = agent
    return agent


def delete_chat_agent(session_id: str) -> None:
    """Mirrors app.models.chat.delete_session() — called when a session is
    closed, so its ChatAgent (and the checkpointer/graph it holds) doesn't
    leak for the life of the process.

    Gap-closure Day 23 (Stage 1.3, answers.md) — before this, popping the
    agent out of _chat_agents just made its self._background_processes
    dict (and the subprocess.Popen objects in it) unreachable; garbage
    collecting a Popen object does NOT terminate the real OS process it
    wraps, so any run_background call a session made outlived the session
    itself with nothing left able to stop it. This is the session-close
    hook that actually terminates them, the immediate-and-graceful
    counterpart to bg_process_registry.sweep_orphaned_processes()'s
    startup-time safety net for crashes that never reach here at all."""
    agent = _chat_agents.pop(session_id, None)
    if agent is None:
        return
    from app.fleet.bg_process_registry import unregister as _bg_unregister

    for pid, proc in agent._background_processes.items():
        if proc.poll() is None:  # still running
            try:
                proc.terminate()
                logger.info(
                    "Session %s closed — terminated its background PID %d",
                    session_id,
                    pid,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to terminate background PID %d on session close: %s",
                    pid,
                    exc,
                )
        _bg_unregister(pid)


def _read_stream_nonblocking(stream: Any, max_bytes: int = 8192) -> str | None:
    """Best-effort non-blocking read of up to max_bytes from a pipe.

    fcntl-based O_NONBLOCK (the POSIX approach) doesn't exist on Windows pipe
    file descriptors — found via real execution (ModuleNotFoundError:
    'fcntl'). On Windows, run the blocking read() in a daemon thread with a
    short timeout: if data arrives in time we return it, otherwise we abandon
    the thread (harmless — it finishes whenever the target process next
    writes or exits, its result simply unused) and report no output yet,
    matching this tool's existing "(no output yet ...)" behavior for an idle
    process. Mirrors app.agents.tools._read_stream_nonblocking.
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

    ro_result: dict[str, str | None] = {"data": None}

    def _reader() -> None:
        try:
            ro_result["data"] = stream.read(max_bytes)
        except Exception:
            pass

    ro_thread = threading.Thread(target=_reader, daemon=True)
    ro_thread.start()
    ro_thread.join(timeout=0.1)
    return ro_result["data"]


# ---------------------------------------------------------------------------
# Fleet OS capability declaration.
#
# ChatAgent is an interactive, open-ended, multi-turn session (not a single-shot
# run_agent_graph task) — dangerous tool calls already gate on
# session.request_confirmation() instead of a post-hoc VerificationConfig state
# machine. AGENT_CONTRACT/_register() exist so the fleet capability_registry can
# discover it like every other agent; VerificationConfig documents the same
# read/write verification semantics the other 67 agents declare, for parity.
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "chat_agent",
    "description": "Interactive streaming chat agent — full agentic loop over the repo (read/search/edit/git/test/db/docker) with human confirmation gating dangerous actions.",
    "allowed_tools": [t["name"] for t in CHAT_TOOLS],
    "input_types": ["chat_session", "user_message"],
    "output_types": ["streamed_events", "AgentResult"],
    "side_effects": [
        "reads/writes repo files",
        "runs bash",
        "runs git (incl. push, with confirmation)",
    ],
    "permissions": ["read_repo", "write_repo", "execute_bash", "git_write"],
    "risk_level": "high",
    "expected_verification": {
        "read": "read_file or search_code must run before write/bash tools"
    },
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_tests": "tests_passed",
        "run_linter": "lint_ran",
        "git_diff": "diff_checked",
        "read_file": "read",
        "search_code": "read",
    },
    reset_by=("write_file", "edit_file", "apply_patch"),
    reset_keys=("tests_passed",),
    enforce_in_result={"read": "read"},
    initial={
        "read": False,
        "tests_passed": False,
        "lint_ran": False,
        "diff_checked": False,
    },
    # Gap-closure Day 16 (Stage 1.2, answers.md): this config object existed
    # since this class was written but nothing ever consulted it — no
    # `state["verification"]` slot existed, and _execute_tool_node never
    # read or wrote one. Now genuinely enforced by _execute_tool_node below.
    # blocking_until makes AGENT_CONTRACT["expected_verification"]'s own
    # stated rule ("read_file or search_code must run before write/bash
    # tools") a real refusal — scoped to the literal "write"-shaped tools
    # (write_file/edit_file/apply_patch) plus bash; delete_file is
    # deliberately excluded here since gap-closure Day 5 already gates it
    # behind a mandatory human confirmation for every call, a stronger
    # protection than a prior-read requirement would add.
    blocking_until={
        "write_file": "read",
        "edit_file": "read",
        "apply_patch": "read",
        "bash": "read",
    },
)


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
                capabilities=["interactive_chat_session"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()


def _run_subprocess(
    command: str, cwd: str, timeout: int = 120, *, fail_on_nonzero_exit: bool = False
) -> str:
    """Run a shell command synchronously (safe to call from a thread pool).

    fail_on_nonzero_exit (gap-closure Day 15, Stage 1.2, answers.md):
    default False preserves the existing behavior for the generic `bash`
    tool, where a nonzero exit is often expected/benign (e.g. grep finding
    no matches) — not something the verification system should treat as a
    failure. True is for run_tests specifically, where a nonzero exit
    genuinely means the tests failed: prefixes [ERROR] so it flows through
    the same "don't set the verification flag on an [ERROR]-prefixed
    result" check every other tool already goes through, instead of the
    real exit code being silently discarded as a `[exit N]` suffix on
    output that still reads as a clean, flag-setting success.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = result.stdout
        if result.stderr:
            out += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            if fail_on_nonzero_exit:
                return f"[ERROR] Tests failed (exit code {result.returncode}):\n{out.strip() or '(no output)'}"
            out += f"\n[exit {result.returncode}]"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"


def _run_bash_tool(command: str, cwd: str, timeout: int = 120) -> str:
    """Formats app.agents.tools._run_bash_command's (stdout, stderr,
    returncode, timed_out) tuple into the exact same string shape
    _run_subprocess above already produces, so this tool's output is
    unchanged — only the execution engine underneath moves from a raw host
    `subprocess.run` to the real Docker sandbox (Settings.bash_sandbox_enabled)
    that _run_subprocess never routed through.

    AUDIT_Q_BATCH11 §21 "Sandboxing" — chat_agent.py's own generic `bash`
    tool handler called _run_subprocess directly, bypassing
    app.policy.sandbox.run_sandboxed entirely (a finding cross-validated
    three times across audit batches). Scoped to just the generic `bash`
    tool, matching sandbox.py's own documented rollout scope: the other
    _run_subprocess call sites in this file (run_tests, run_linter, git
    plumbing, npm/pip installs, ...) are allowlist-scoped commands that
    need the target repo's own installed toolchain (venv/node_modules),
    which the minimal default sandbox image does not have — routing those
    through the sandbox too would break them, not secure them further.
    """
    stdout, stderr, returncode, timed_out = _run_bash_command(
        command, cwd, timeout=timeout
    )
    if timed_out:
        return f"[ERROR] Command timed out after {timeout}s"
    out = stdout
    if stderr:
        out += "\n[stderr]\n" + stderr
    if returncode != 0:
        out += f"\n[exit {returncode}]"
    return out.strip() or "(no output)"


# ---------------------------------------------------------------------------
# Context condense — Gap-closure Stage 1.5 (answers.md). Async counterpart
# to base_graph.py::_condense_messages/_summarize_dropped_messages: this
# file's own client is anthropic.AsyncAnthropic (base_graph.py's is sync
# anthropic.Anthropic), so the sync, circuit-breaker-wrapped _call_anthropic
# helper can't be reused directly for the summarization call itself — but
# _select_messages_to_condense/_stringify_messages_for_summary are pure
# (no I/O), so those ARE reused as-is, keeping the actual condense
# decision and message formatting identical between both graphs.
# ---------------------------------------------------------------------------


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Cheap, no-API-call token estimate (~4 chars/token, a standard rough
    heuristic — not exact, but only used to gate the condense decision when
    self._tokens_in hasn't observed a real API response yet, e.g. the first
    turn of a restored session; a real response's usage.input_tokens
    replaces this estimate for every subsequent turn). See the condense
    gate in _call_llm_node for why this exists (audit_v1.md 4.4 #3)."""
    total_chars = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(
                        str(block.get("text") or block.get("content") or "")
                    )
    return total_chars // 4


_CHAT_CONDENSE_SUMMARY_PROMPT = (
    "Summarize the key facts, decisions, file names/paths, and progress "
    "from this earlier part of a chat conversation, in 3-8 concrete bullet "
    "points. Preserve specifics (values, file paths, conclusions) — do not "
    "write vague generalities.\n\nConversation excerpt:\n{excerpt}"
)


async def _summarize_dropped_messages_async(
    dropped: list[dict[str, Any]], client: anthropic.AsyncAnthropic, model_haiku: str
) -> str:
    """Uses the shared Anthropic circuit breaker's allow()/record_success()/
    record_failure() primitives directly (the same pattern _call_llm_node
    already uses for its own main streaming call), since call() only wraps
    a sync callable."""
    excerpt = _stringify_messages_for_summary(dropped)[:12000]
    if not excerpt:
        return "(no summarizable content in the dropped messages)"

    from app.fleet.circuit_breaker import get_anthropic_breaker

    breaker = get_anthropic_breaker()
    if not breaker.allow():
        return (
            f"({len(dropped)} earlier messages were dropped; "
            "circuit breaker open — Anthropic API calls temporarily suspended)"
        )
    try:
        r = await client.messages.create(
            model=model_haiku,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": _CHAT_CONDENSE_SUMMARY_PROMPT.format(excerpt=excerpt),
                }
            ],
        )
        breaker.record_success()
        text = "".join(
            str(getattr(block, "text", ""))
            for block in r.content
            if getattr(block, "type", None) == "text"
        )
        return text or "(summarization returned no content)"
    except Exception as exc:
        breaker.record_failure()
        logger.warning("Chat context condense summarization failed: %s", exc)
        return (
            f"({len(dropped)} earlier messages were dropped; "
            f"summarization failed: {exc})"
        )


async def _condense_history_async(
    messages: list[dict[str, Any]],
    token_budget: int,
    tokens_in: int,
    client: anthropic.AsyncAnthropic,
    model_haiku: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Real LLM-summarization condense step for the interactive chat
    session's history, mirroring base_graph.py::_condense_messages exactly
    (same head[0] + tail[-4] boundary, same "summarize, don't silently
    drop" behavior) — the async counterpart chat_agent.py's own client
    type requires."""
    selection = _select_messages_to_condense(messages, token_budget, tokens_in)
    if selection is None:
        return messages, False
    head, dropped, tail = selection
    summary_text = await _summarize_dropped_messages_async(dropped, client, model_haiku)
    condensed = (
        head
        + [
            {
                "role": "user",
                "content": (
                    f"[Earlier conversation summary — {len(dropped)} messages "
                    f"condensed]\n{summary_text}"
                ),
            }
        ]
        + tail
    )
    logger.info(
        "Chat context condense: %d → %d messages (tokens_in=%d > budget=%d), "
        "%d messages summarized",
        len(messages),
        len(condensed),
        tokens_in,
        token_budget,
        len(dropped),
    )
    return condensed, True


def _git(args: list[str], cwd: str, timeout: int = 30) -> str:
    """Run a git command and return combined output."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[ERROR] git timed out"
    except Exception as e:
        return f"[ERROR] {e}"


class ChatAgent:
    """
    Async streaming chat agent that runs a full agentic loop:
    LLM call → tool execution → LLM call → … until stop_reason == end_turn.

    MASTER_AGENT_v2.md Phase 5.2 — this loop is a real LangGraph StateGraph
    (self._graph, built by _build_chat_graph()), not a plain Python method.
    Dangerous operations pause via a real interrupt() call (self._confirm())
    instead of a bespoke asyncio.Event. See this module's own docstring for
    the full design and why per-tool-call node granularity is what makes
    that safe.
    """

    MAX_ITERATIONS = 30

    def __init__(self, session: ChatSession) -> None:
        self.session = session
        self.root = Path(session.repo_path)
        # AUDIT_Q_BATCH04 §6 gap-closure (2026-08-10) — was chat_agent's own
        # local _load_role() (a pure roles_dir/name.md read, no global-
        # standards prepend), a real divergence from every other agent: the
        # shared app.agents.base.load_role() also prepends
        # roles/_GLOBAL_STANDARDS.md (the honest-errors/verification/
        # self-review constitution every one of the other ~76 agents'
        # system prompts already carries — tests/test_day8_role_prompts.py
        # ::test_load_role_prepends_global_standards_at_runtime already
        # covers "chat" in its role-file parametrization and passes against
        # load_role() directly, proving roles/chat.md was always compliant;
        # this call site just wasn't using it). Same roles/ directory, same
        # file — reusing the shared loader instead of a second copy.
        self._system = load_role("chat")
        # Per-session background process table (one ChatAgent per ChatSession) —
        # mirrors make_chat_handlers()'s per-session isolation in tools.py so one
        # session cannot kill or read another session's background process.
        # Kept on the instance (not in graph state) since a Popen handle isn't
        # meaningfully "checkpointed" data — get_or_create_chat_agent() keeps
        # this same instance alive across a pause/resume, so it survives one
        # exactly as it did under the old mechanism.
        self._background_processes: dict[int, subprocess.Popen[str]] = {}
        # The Anthropic tool_use_id of whichever tool call _execute_tool_node
        # is currently dispatching — read by _confirm() as a REPLAY-STABLE
        # confirmation action_id (see module docstring: a freshly generated
        # uuid4() would differ between the paused and resumed pass of the
        # same node, since node bodies re-run from the top on resume).
        self._current_tool_use_id: str = ""
        # AUDIT_Q_BATCH07 §39 gap-closure (2026-08-11) — the stable key
        # _confirm() checks against session.remembered_confirmations for
        # "don't ask again this session". Set alongside
        # _current_tool_use_id below for the same replay-safety reason.
        self._current_tool_name: str = ""
        self._graph = self._build_chat_graph()
        # Gap-closure Stage 1.5 (answers.md) — chat_agent.py had ZERO
        # token-budget tracking before this (confirmed by grep: no
        # tokens_in/tokens_out/response.usage reference anywhere in this
        # file), unlike base_graph.py's call_llm. Kept on the instance for
        # the same reason self._background_processes is: this ChatAgent
        # instance survives the whole session (get_or_create_chat_agent()),
        # so cumulative usage naturally persists across turns without
        # needing to round-trip through checkpointed graph state.
        self._tokens_in: int = 0
        self._tokens_out: int = 0
        # AUDIT_Q_BATCH04 §6 gap-closure (2026-08-10) — chat_agent tracked
        # tokens/tools entirely on its own instance state and never fed the
        # shared app.fleet.metrics.RunMetrics span the other ~76
        # run_agent_graph()-based agents all use (confirmed by grep: no
        # "fleet.metrics" reference anywhere in this file before this fix).
        # Set for the duration of one graph ainvoke() (run() or resume(),
        # each its own span — a paused-for-confirmation turn genuinely
        # completes its pre-interrupt span; resume() opens a new one for the
        # post-interrupt continuation, since RunMetrics has no notion of a
        # single span suspended across two separate ASGI requests) so
        # _execute_tool_node can attach real per-tool-call timing via the
        # same get_metrics_collector().get(trace_id) lookup base_graph.py's
        # execute_tools node already uses (app/agents/base_graph.py:1844).
        self._current_trace_id: str = ""

    def _client(self) -> anthropic.AsyncAnthropic:
        # AUDIT_Q_BATCH08 §38/§66 — explicit, config-driven max_retries,
        # matching app/agents/base_graph.py::_make_client() — the SDK
        # already retries connection/408/409/429/5xx errors with real
        # exponential backoff internally (proven against the real SDK by
        # tests/test_gap58_59_llm_outage_retry_and_breaker.py) whenever this
        # is >0; previously unset here, relying on the SDK's own
        # undocumented default instead of a real settings value.
        return anthropic.AsyncAnthropic(
            api_key=get_effective_api_key(),
            max_retries=get_settings().llm_call_max_retries,
        )

    def _haiku_model(self) -> str:
        """Gap-closure Stage 1.5 (answers.md) — cheap model for the context
        condense summarization call, same ModelRouter-first-then-settings
        fallback pattern run_agent_graph() already uses for its own
        model_haiku default (base_graph.py)."""
        try:
            from app.fleet.model_router import get_model_router

            haiku_agents = get_model_router().agents_by_tier("haiku")
            if haiku_agents:
                return get_model_router().model_for(haiku_agents[0])
        except Exception:
            pass
        return get_settings().model_coder

    # ------------------------------------------------------------------
    # Human confirmation — MASTER_AGENT_v2.md Phase 5.2, real interrupt().
    # ------------------------------------------------------------------

    async def _confirm(self, description: str, details: str) -> bool:
        """Pause the current tool-call node and ask the user to approve or
        deny an action, via a real LangGraph interrupt(). Only ever called
        from inside _execute_tool()'s dispatch, itself only ever called
        from _execute_tool_node() — i.e. always from within exactly one
        tool call's own graph node, and always as the first side-effecting-
        adjacent thing that node does (verified true for every real call
        site — see this module's docstring).

        AUDIT_Q_BATCH07 §39 gap-closure (2026-08-11) — "'Don't ask again
        this session': NO — not found." If the human previously approved
        this exact tool with remember=True earlier in this session, skip
        the pause entirely and auto-approve — but only for this pause
        itself; it can never bypass a hard, confirmation-independent block
        (e.g. production migrations), since those checks run in the
        caller, before _confirm() is ever invoked. Still recorded in the
        audit trail and pushed to the client, just without blocking."""
        action_id = self._current_tool_use_id or str(uuid.uuid4())
        thread_id = f"chat-{self.session.session_id}-{action_id}"

        if (
            self._current_tool_name
            and self._current_tool_name in self.session.remembered_confirmations
        ):
            try:
                from app.fleet.approval_gate import arecord_decision

                await arecord_decision(
                    thread_id=thread_id,
                    approved=True,
                    decided_by="user (remembered this session)",
                )
            except Exception:
                logger.warning(
                    "Failed to record remembered chat confirmation for session %s",
                    self.session.session_id,
                    exc_info=True,
                )
            await self.session.push(
                {
                    "type": "confirmation_auto_approved",
                    "actionId": action_id,
                    "description": description,
                    "details": details,
                }
            )
            return True

        try:
            from app.fleet.approval_gate import arequest_human_input

            await arequest_human_input(
                kind="chat_confirmation",
                details={"description": description, "details": details},
                agent_name="chat_agent",
                thread_id=thread_id,
                blocking=True,
                description=description,
            )
        except Exception:
            logger.warning(
                "Failed to record chat confirmation request for session %s",
                self.session.session_id,
                exc_info=True,
            )

        await self.session.push(
            {
                "type": "confirmation_required",
                "actionId": action_id,
                "description": description,
                "details": details,
            }
        )

        decision = interrupt(
            {"action_id": action_id, "description": description, "details": details}
        )
        approved = (
            bool(decision.get("approved", False))
            if isinstance(decision, dict)
            else bool(decision)
        )
        remember = (
            bool(decision.get("remember", False))
            if isinstance(decision, dict)
            else False
        )
        if approved and remember and self._current_tool_name:
            self.session.remembered_confirmations.add(self._current_tool_name)

        try:
            from app.fleet.approval_gate import arecord_decision

            await arecord_decision(
                thread_id=thread_id, approved=approved, decided_by="user"
            )
        except Exception:
            logger.warning(
                "Failed to record chat confirmation decision for session %s",
                self.session.session_id,
                exc_info=True,
            )

        return approved

    async def _confirm_with_options(
        self,
        description: str,
        options: list[dict[str, str]],
        recommended: str | None = None,
    ) -> str | None:
        """AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) — "Present options
        (multi-choice): NO — Confirmation payload is binary approve/deny
        only" / "Recommend choices: PARTIAL — no structured recommendation
        field." A genuinely different decision shape from _confirm()'s
        Y/N pause (which stays completely untouched — every existing
        dangerous-operation gate keeps behaving exactly as before): here
        the human picks one of several named options rather than approving
        or denying a single proposed action. Reuses the exact same real
        interrupt()/Command(resume=...) pause primitive as _confirm() —
        same thread, same checkpointer, same resume() method (now extended
        with an optional `selected` param) — not a second pause mechanism.

        Returns the selected option's id, or None if the human declined to
        choose (resumed with approved=False and no selection)."""
        action_id = self._current_tool_use_id or str(uuid.uuid4())
        thread_id = f"chat-{self.session.session_id}-{action_id}"
        valid_ids = {str(o["id"]) for o in options}

        try:
            from app.fleet.approval_gate import arequest_human_input

            await arequest_human_input(
                kind="chat_confirmation",
                details={
                    "description": description,
                    "options": options,
                    "recommended": recommended,
                },
                agent_name="chat_agent",
                thread_id=thread_id,
                blocking=True,
                description=description,
            )
        except Exception:
            logger.warning(
                "Failed to record chat multi-choice request for session %s",
                self.session.session_id,
                exc_info=True,
            )

        await self.session.push(
            {
                "type": "confirmation_required",
                "actionId": action_id,
                "description": description,
                "options": options,
                "recommended": recommended,
            }
        )

        decision = interrupt(
            {
                "action_id": action_id,
                "description": description,
                "options": options,
                "recommended": recommended,
            }
        )
        selected: str | None = None
        approved = False
        if isinstance(decision, dict):
            approved = bool(decision.get("approved", False))
            raw_selected = decision.get("selected")
            if raw_selected is not None and str(raw_selected) in valid_ids:
                selected = str(raw_selected)

        try:
            from app.fleet.approval_gate import arecord_decision

            await arecord_decision(
                thread_id=thread_id,
                approved=approved and selected is not None,
                decided_by="user",
            )
        except Exception:
            logger.warning(
                "Failed to record chat multi-choice decision for session %s",
                self.session.session_id,
                exc_info=True,
            )

        return selected

    # ------------------------------------------------------------------
    # Unified memory read/write — MASTER_AGENT_v2.md Phase 1.1/3.3.
    # chat_agent.py's own LangGraph conversion is deliberately deferred to
    # Phase 5 (it never calls run_agent_graph, so it gets none of
    # memory_hook_node's/the universal post-run hook's wiring "for free").
    # Applying just the memory read/write behavior now — not the structural
    # conversion — is what Phase 3.3 explicitly asks for. `run()` is called
    # once per user message, so that's this agent's real unit of "a run":
    # one memory read before the turn, one outcome write after it.
    # ------------------------------------------------------------------

    async def _memory_read_context(self, query: str) -> str:
        """Fetch relevant past memory for this specific message — same
        sources memory_hook_node already queries for every run_agent_graph
        agent. Non-fatal: any failure returns "" so a broken memory backend
        can never break a chat turn."""
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.session import new_isolated_async_engine
            from app.memory.store import (
                format_full_memory_context,
                query_memory_context,
            )

            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    # Stage 4 Cluster O Phase 1b (2026-08-05) — repo-scoped
                    # read, using the repo_id resolved once at session
                    # creation (app/api/chat.py::create_chat_session).
                    mem = await query_memory_context(
                        query, db, repo_id=self.session.repo_id
                    )
            finally:
                await engine.dispose()
            return format_full_memory_context(
                mem["tasks"],
                mem["failures"],
                mem["learnings"],
                mem.get("procedures", []),
                mem.get("preferences", []),
                mem.get("bugs", []),
            )
        except Exception:
            logger.debug("ChatAgent memory read skipped (non-fatal)", exc_info=True)
            return ""

    async def _memory_write_outcome(
        self, description: str, summary: str, error: str | None
    ) -> None:
        """Write this turn's outcome to shared memory — the write-side
        counterpart to _memory_read_context. Non-fatal by design, matching
        every other post-run memory hook in this codebase."""
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.session import new_isolated_async_engine
            from app.memory.store import embed_failure, embed_task_outcome

            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    # Stage 4 Cluster O Phase 1b (2026-08-05) — repo-scoped
                    # write; see the matching read-side comment above.
                    await embed_task_outcome(
                        task_id=self.session.session_id,
                        description=description,
                        summary=summary or (error or ""),
                        outcome="blocked" if error else "completed",
                        files_changed=[],
                        db=db,
                        repo_id=self.session.repo_id,
                    )
                    if error:
                        await embed_failure(
                            task_id=self.session.session_id,
                            error_description=error,
                            root_cause=error,
                            db=db,
                            repo_id=self.session.repo_id,
                        )
            finally:
                await engine.dispose()
        except Exception:
            logger.debug("ChatAgent memory write skipped (non-fatal)", exc_info=True)

    # ------------------------------------------------------------------
    # Tool execution — dispatches all 36 CHAT_TOOLS
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_name: str, inp: dict[str, Any]
    ) -> str:  # noqa: C901
        root = self.root
        repo = str(root)

        # ========== FILE SYSTEM — READ ==========

        if tool_name == "read_file":
            p = root / str(inp["path"])
            if not p.exists():
                return f"[ERROR] File not found: {inp['path']}"
            try:
                return p.read_text(encoding="utf-8")
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "read_files":
            rf_all_paths = inp.get("paths") or []
            rf_offset = max(0, int(inp.get("offset", 0)))
            rf_page = rf_all_paths[rf_offset : rf_offset + 20]
            file_parts: list[str] = []
            for rel in rf_page:
                fp = root / str(rel)
                try:
                    file_parts.append(
                        f"=== {rel} ===\n{fp.read_text(encoding='utf-8')}"
                        if fp.exists()
                        else f"=== {rel} ===\n[NOT FOUND]"
                    )
                except Exception as e:
                    file_parts.append(f"=== {rel} ===\n[ERROR] {e}")
            if not file_parts:
                return (
                    "[ERROR] No paths given"
                    if not rf_all_paths
                    else "(no paths at this offset)"
                )
            rf_remaining = len(rf_all_paths) - (rf_offset + len(rf_page))
            if rf_remaining > 0:
                file_parts.append(
                    f"[NOTICE] {rf_remaining} of {len(rf_all_paths)} requested "
                    f"path(s) were not read (20-per-call limit). Call again "
                    f"with offset={rf_offset + len(rf_page)} to continue."
                )
            return "\n\n".join(file_parts)

        if tool_name == "file_exists":
            p = root / str(inp["path"])
            return "file" if p.is_file() else "directory" if p.is_dir() else "not_found"

        if tool_name == "file_info":
            import datetime

            p = root / str(inp["path"])
            if not p.exists():
                return f"[ERROR] Not found: {inp['path']}"
            stat = p.stat()
            line_count = ""
            if p.is_file():
                try:
                    line_count = f"\nlines: {len(p.read_text(encoding='utf-8', errors='replace').splitlines())}"
                except Exception:
                    pass
            return (
                f"path: {inp['path']}\ntype: {'file' if p.is_file() else 'dir'}\n"
                f"size: {stat.st_size} bytes{line_count}\n"
                f"modified: {datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}"
            )

        if tool_name == "list_files":
            directory = str(inp.get("directory", ""))
            pattern = str(inp.get("pattern", "**/*"))
            search_root = root / directory if directory else root
            if not search_root.exists():
                return f"[ERROR] Directory not found: {directory}"
            paths = sorted(
                str(fp.relative_to(root))
                for fp in search_root.glob(pattern)
                if fp.is_file()
            )
            return "\n".join(paths[:300])

        if tool_name == "get_file_tree":
            directory = str(inp.get("directory", ""))
            max_depth = min(int(inp.get("max_depth", 3)), 4)
            start = root / directory if directory else root
            if not start.exists():
                return f"[ERROR] Not found: {directory}"
            _SKIP = {
                "__pycache__",
                "node_modules",
                ".next",
                ".venv",
                "venv",
                ".git",
                "dist",
                "build",
                ".mypy_cache",
            }
            tree_lines: list[str] = [directory or "."]

            def _tree(path: Path, depth: int, prefix: str) -> None:
                if depth > max_depth:
                    return
                try:
                    items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
                except PermissionError:
                    return
                items = [
                    i
                    for i in items
                    if i.name not in _SKIP and not i.name.startswith(".")
                ]
                for idx, item in enumerate(items):
                    conn = "└── " if idx == len(items) - 1 else "├── "
                    tree_lines.append(f"{prefix}{conn}{item.name}")
                    if item.is_dir() and depth < max_depth:
                        ext = "    " if idx == len(items) - 1 else "│   "
                        _tree(item, depth + 1, prefix + ext)

            _tree(start, 1, "")
            return "\n".join(tree_lines[:300])

        # ========== SEARCH ==========

        if tool_name == "search_code":
            pattern = str(inp["pattern"])
            fp = inp.get("file_pattern", "")
            cmd_args = [
                "grep",
                "-rn",
                "--include",
                str(fp) if fp else "*",
                pattern,
                repo,
            ]
            try:
                r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=15)
                return r.stdout[:8000] or "(no matches)"
            except subprocess.TimeoutExpired:
                return "[ERROR] Search timed out"

        if tool_name == "search_symbols":
            sym_name = str(inp["name"])
            kind = str(inp.get("kind", "all"))
            patterns: list[str] = []
            if kind in ("function", "all"):
                patterns += [
                    f"def {sym_name}",
                    f"async def {sym_name}",
                    f"function {sym_name}",
                    f"const {sym_name} =",
                ]
            if kind in ("class", "all"):
                patterns += [
                    f"class {sym_name}",
                    f"interface {sym_name}",
                    f"type {sym_name} =",
                ]
            sym_results: list[str] = []
            for pat in patterns:
                try:
                    r = subprocess.run(
                        [
                            "grep",
                            "-rn",
                            "--include=*.py",
                            "--include=*.ts",
                            "--include=*.tsx",
                            pat,
                            repo,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.stdout:
                        sym_results.append(r.stdout[:2000])
                except subprocess.TimeoutExpired:
                    pass
            combined = "\n".join(sym_results)[:6000]
            return combined or f"(no symbol '{sym_name}' found)"

        if tool_name == "find_references":
            sym = str(inp["symbol"])
            fp = inp.get("file_pattern", "")
            ref_cmd = ["grep", "-rn"]
            if fp:
                ref_cmd += ["--include", str(fp)]
            ref_cmd += [r"\b" + sym + r"\b", repo]
            try:
                r = subprocess.run(ref_cmd, capture_output=True, text=True, timeout=15)
                return r.stdout[:6000] or f"(no references to '{sym}')"
            except subprocess.TimeoutExpired:
                return "[ERROR] Search timed out"

        if tool_name == "find_todos":
            directory = str(inp.get("directory", ""))
            kind = str(inp.get("kind", "all"))
            search_root = root / directory if directory else root
            markers = ["TODO", "FIXME", "HACK", "XXX"] if kind == "all" else [kind]
            try:
                r = subprocess.run(
                    [
                        "grep",
                        "-rn",
                        "-E",
                        f"({'|'.join(markers)}):",
                        str(search_root),
                        "--include=*.py",
                        "--include=*.ts",
                        "--include=*.tsx",
                        "--include=*.md",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                return r.stdout[:5000] or "(no TODOs found)"
            except subprocess.TimeoutExpired:
                return "[ERROR] Search timed out"

        if tool_name == "search_imports":
            module = str(inp["module"])
            fp = inp.get("file_pattern", "")
            imp_patterns = [
                f"import {module}",
                f"from {module}",
                f'require("{module}")',
                f"require('{module}')",
            ]
            import_results: list[str] = []
            for pat in imp_patterns:
                imp_cmd = ["grep", "-rn"]
                if fp:
                    imp_cmd += ["--include", str(fp)]
                imp_cmd += [pat, repo]
                try:
                    r = subprocess.run(
                        imp_cmd, capture_output=True, text=True, timeout=10
                    )
                    if r.stdout.strip():
                        import_results.append(r.stdout[:2000])
                except subprocess.TimeoutExpired:
                    pass
            return "\n".join(import_results)[:6000] or f"(no imports of '{module}')"

        if tool_name == "analyze_file":
            rel = str(inp["path"])
            fp = root / rel
            if not fp.exists():
                return f"[ERROR] Not found: {rel}"
            content = fp.read_text(encoding="utf-8", errors="replace")
            af_lines = content.splitlines()
            af_imports: list[str] = []
            af_defs: list[str] = []
            for i, line in enumerate(af_lines, 1):
                s = line.strip()
                if s.startswith(("import ", "from ")):
                    af_imports.append(f"  L{i}: {s}")
                elif s.startswith(
                    (
                        "def ",
                        "async def ",
                        "class ",
                        "export function ",
                        "export async function ",
                        "export class ",
                        "export const ",
                        "export interface ",
                        "export type ",
                        "export default function ",
                    )
                ):
                    af_defs.append(f"  L{i}: {s[:120]}")
            af_result = [f"File: {rel}  ({len(af_lines)} lines)"]
            if af_imports:
                af_result += [f"\nImports ({len(af_imports)}):"] + af_imports[:30]
            if af_defs:
                af_result += [f"\nDefinitions ({len(af_defs)}):"] + af_defs[:50]
            return "\n".join(af_result)

        # ========== GIT — READ ==========

        if tool_name == "git_log":
            count = min(int(inp.get("count", 10)), 30)
            file_filter = str(inp.get("file", ""))
            log_args = ["log", "--oneline", f"-{count}", "--no-merges"]
            if file_filter:
                log_args += ["--", file_filter]
            return _git(log_args, repo)

        if tool_name == "git_status":
            return _git(["status", "--short", "--branch"], repo) or "(clean)"

        if tool_name == "git_show":
            ref = str(inp.get("ref", "HEAD"))
            out = _git(["show", "--stat", "--no-color", ref], repo)
            return out[:5000]

        if tool_name == "git_blame":
            rel = str(inp["path"])
            blame_start = inp.get("start_line")
            blame_end = inp.get("end_line")
            blame_args = ["blame", "--date=short", "-w"]
            if blame_start and blame_end:
                blame_args.append(f"-L{blame_start},{blame_end}")
            blame_args.append(rel)
            return _git(blame_args, repo)[:5000]

        if tool_name == "git_diff":
            file_ = str(inp.get("file", ""))
            staged = _git(["diff", "--cached", "--no-color"], repo)
            unstaged_args = ["diff", "--no-color"] + ([file_] if file_ else [])
            unstaged = _git(unstaged_args, repo)
            out = ""
            if staged.strip():
                out += "=== STAGED ===\n" + staged
            if unstaged.strip():
                out += "=== UNSTAGED ===\n" + unstaged
            return out or "No changes."

        # ========== FILE SYSTEM — WRITE ==========

        if tool_name == "write_file":
            rel = str(inp["path"])
            if _is_protected_path(rel, repo):
                return f"[POLICY DENIED] Cannot write to protected path: {rel}"
            target = root / rel
            # Gap-closure Day 5 (root cause 2, answers.md Q39): write_file
            # replaces a file's ENTIRE content with no diff-awareness, unlike
            # edit_file's precise, unique old_string->new_string replacement
            # (inherently safer, git-diffable, and left ungated — matching
            # how coding agents normally operate without per-edit
            # confirmation). Gating creation of a brand-new file would
            # disrupt the agent's core, extremely frequent workflow for no
            # real safety benefit (nothing existing is at risk); gating a
            # silent full-content overwrite of a file that already has real
            # content is the actual destructive case this closes.
            if target.exists():
                approved = await self._confirm(
                    description="Overwrite an existing file's entire content",
                    details=rel,
                )
                if not approved:
                    return f"[DENIED] User declined to overwrite: {rel}"
            return write_file_handler(root, repo, inp)

        if tool_name == "edit_file":
            return edit_file_handler(root, repo, inp)

        if tool_name == "append_file":
            return append_file_handler(root, repo, inp)

        if tool_name == "rename_file":
            return rename_file_handler(root, repo, inp)

        if tool_name == "copy_file":
            import shutil as _shutil

            from_rel = str(inp["from_path"])
            to_rel = str(inp["to_path"])
            if _is_protected_path(from_rel, repo):
                return f"[POLICY DENIED] Protected source: {from_rel}"
            if _is_protected_path(to_rel, repo):
                return f"[POLICY DENIED] Protected destination: {to_rel}"
            src = root / from_rel
            dst = root / to_rel
            if not src.exists():
                return f"[ERROR] Source not found: {from_rel}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(str(src), str(dst))
            return f"Copied {from_rel} → {to_rel}"

        if tool_name == "move_file":
            # tool_enhance.md productionization pass, tool #52 (2026-08-20)
            # — same "advertised but never dispatched" class as tools
            # #44/#45/#46/#48/#50/#51: already in CHAT_TOOLS, zero
            # dispatch here. Also found a real, severe finding matching
            # tool #11's copy_file bug class (never validated from_path)
            # but worse — `source` was never validated at all, and a
            # move also DELETES the original, proved live: an absolute
            # outside-repo source was successfully relocated into the
            # repo, destroying the original file at its source location.
            # Fixed via the shared move_file_handler(), which validates
            # both source and dest.
            return move_file_handler(root, repo, inp)

        if tool_name == "delete_file":
            rel = str(inp["path"])
            del_reason = str(inp.get("reason", "")).strip()
            if _is_protected_path(rel, repo):
                return f"[POLICY DENIED] Cannot delete protected path: {rel}"
            target = root / rel
            if not target.exists():
                return f"[ERROR] File not found: {rel}"
            if not target.is_file():
                return (
                    f"[ERROR] {rel} is a directory — use bash 'rm -rf' for directories"
                )
            # Gap-closure Day 5 (root cause 2, answers.md Q39): deletion is
            # irreversible and, unlike write_file/edit_file, not something a
            # coding agent does dozens of times per turn — same confirmation
            # pattern as git_push/dangerous-bash/git_reset --hard below.
            confirm_details = f"{rel}\nReason: {del_reason}" if del_reason else rel
            approved = await self._confirm(
                description="Delete a file", details=confirm_details
            )
            if not approved:
                return f"[DENIED] User declined to delete: {rel}"
            return delete_file_handler(root, repo, inp)

        # ========== GIT — WRITE ==========

        if tool_name == "git_commit":
            gc_message = str(inp["message"])
            gc_raw_files = inp.get("files", [])
            gc_files: list[str] = (
                list(gc_raw_files) if isinstance(gc_raw_files, list) else ["--all"]
            )
            return await asyncio.to_thread(
                stage_and_commit, repo, gc_message, gc_files
            )

        if tool_name == "git_branch":
            action = str(inp.get("action", "list"))
            bname = str(inp.get("name", ""))
            if action == "list":
                return _git(["branch", "-a"], repo)
            if action == "create":
                return (
                    "[ERROR] name required"
                    if not bname
                    else _git(["branch", bname], repo) or f"Branch '{bname}' created"
                )
            if action == "delete":
                return (
                    "[ERROR] name required"
                    if not bname
                    else _git(["branch", "-d", bname], repo)
                )
            return f"[ERROR] Unknown action: {action}"

        if tool_name == "create_branch":
            bname = str(inp["name"])
            do_checkout = bool(inp.get("checkout", True))
            from_b = str(inp.get("from_branch", ""))
            cb_error = validate_create_branch_inputs(bname, from_b)
            if cb_error:
                return cb_error
            create_args = ["branch", bname] + ([from_b] if from_b else [])
            out = _git(create_args, repo)
            if "[ERROR]" in out:
                return out
            if do_checkout:
                return (
                    _git(["checkout", bname], repo)
                    or f"Created and switched to branch: {bname}"
                )
            return f"Created branch: {bname}"

        if tool_name == "git_checkout":
            ck_target = str(inp["target"])
            file_arg = str(inp.get("file", ""))
            ck_error = validate_git_checkout_inputs(ck_target, file_arg)
            if ck_error:
                return ck_error
            if file_arg:
                return _git(["checkout", ck_target, "--", file_arg], repo)
            return _git(["checkout", ck_target], repo)

        if tool_name == "git_stash":
            gst_action = str(inp.get("action", "push"))
            gst_error = validate_git_stash_action(gst_action)
            if gst_error:
                return gst_error
            gst_msg = str(inp.get("message", ""))
            if gst_action == "push" and gst_msg:
                return _git(["stash", "push", "-m", gst_msg], repo)
            return _git(["stash", gst_action], repo)

        if tool_name == "git_pull":
            gp_remote = str(inp.get("remote", "origin"))
            gp_branch = str(inp.get("branch", ""))
            gp_error = validate_git_pull_inputs(gp_remote, gp_branch)
            if gp_error:
                return gp_error
            gp_rebase = bool(inp.get("rebase", False))
            pull_args = (
                ["pull"]
                + (["--rebase"] if gp_rebase else [])
                + [gp_remote]
                + ([gp_branch] if gp_branch else [])
            )
            return await asyncio.to_thread(_git, pull_args, repo, 60)

        if tool_name == "git_fetch":
            remote = str(inp.get("remote", "origin"))
            prune = bool(inp.get("prune", False))
            return await asyncio.to_thread(
                _git, ["fetch", remote] + (["--prune"] if prune else []), repo, 60
            )

        if tool_name == "git_restore":
            gres_rel = str(inp["path"])
            if _is_protected_path(gres_rel, repo):
                return f"[POLICY DENIED] Protected path: {gres_rel}"
            gres_staged = bool(inp.get("staged", False))
            if not gres_staged:
                gres_fp = root / gres_rel
                if not gres_fp.exists():
                    return f"[ERROR] File not found: {gres_rel}"
                gres_confirmed = await self._confirm(
                    description=f"git restore {gres_rel}",
                    details="DISCARDS all uncommitted working-tree changes to this file — irreversible",
                )
                if not gres_confirmed:
                    return f"[CANCELLED] git_restore for {gres_rel} cancelled by user"
            restore_args = (
                ["restore"]
                + (["--staged"] if gres_staged else [])
                + ["--", gres_rel]
            )
            return _git(restore_args, repo)

        if tool_name == "git_push":
            branch = str(inp.get("branch", ""))
            remote = str(inp.get("remote", "origin"))
            force = bool(inp.get("force", False))
            cmd_preview = (
                f"git push {remote} {branch}{'  --force' if force else ''}".strip()
            )
            # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
            # real gap found by reading this code against its own tool
            # description: _GIT_PUSH_TOOL's schema promises force push
            # "requires extra confirmation," but force and normal pushes
            # previously got the identical single confirmation dialog. A
            # force push to a real, configured protected branch (main/
            # master by default) now gets a distinct, more explicit warning
            # naming the actual risk (rewriting shared history), rather
            # than the same generic "Push commits" description every push
            # already shows.
            settings = get_settings()
            if force:
                gp_target_branch = branch or await asyncio.to_thread(
                    _git, ["rev-parse", "--abbrev-ref", "HEAD"], repo
                )
                if gp_target_branch in settings.git_push_protected_branches:
                    approved = await self._confirm(
                        description=(
                            f"FORCE PUSH to protected branch {gp_target_branch!r} — "
                            "this can permanently overwrite remote history other "
                            "people or CI depend on"
                        ),
                        details=cmd_preview,
                    )
                else:
                    approved = await self._confirm(
                        description="FORCE PUSH — this overwrites remote history for this branch",
                        details=cmd_preview,
                    )
            else:
                approved = await self._confirm(
                    description="Push commits to remote repository",
                    details=cmd_preview,
                )
            if not approved:
                return "[DENIED] User declined git push."
            push_args = (
                ["push", remote]
                + ([branch] if branch else [])
                + (["--force"] if force else [])
            )
            return await asyncio.to_thread(_git, push_args, repo, 60)

        # ========== TERMINAL ==========

        if tool_name == "bash":
            command = str(inp["command"])
            cwd = str(inp.get("cwd") or repo)
            # tool_enhance.md productionization pass, tool #9 (2026-08-16)
            # — real, empirically-verified boundary-escape found: `cwd` is
            # fully LLM-controlled and was passed straight through to the
            # real sandboxed execution primitive with NO validation that
            # it stays inside this session's own repo. run_sandboxed()
            # mounts whatever `cwd` it receives read-write as the
            # container's /workspace — proved directly (not assumed): a
            # cwd pointed at an unrelated directory let a real file
            # outside the intended worktree be read back through the
            # sandbox. check_path_in_worktree (already used elsewhere in
            # this codebase for exactly this class of check, e.g.
            # write_file/edit_file's own path arguments) closes it here.
            cwd_check = check_path_in_worktree(cwd, repo)
            if not cwd_check.allowed:
                return f"[POLICY DENIED] {cwd_check.reason}"
            if _is_dangerous_command(command):
                approved = await self._confirm(
                    description="Run potentially destructive command",
                    details=command,
                )
                if not approved:
                    return f"[DENIED] User declined: {command!r}"
            return await asyncio.to_thread(_run_bash_tool, command, cwd, 120)

        if tool_name == "run_parallel_commands":
            rpc_raw = inp.get("commands")
            if not isinstance(rpc_raw, list) or not rpc_raw:
                return "[ERROR] commands must be a non-empty list of {command, cwd?} objects"
            if len(rpc_raw) > MAX_PARALLEL_COMMANDS:
                return f"[ERROR] run_parallel_commands supports at most {MAX_PARALLEL_COMMANDS} commands per call"
            rpc_timeout = int(inp.get("timeout", 60))
            rpc_parsed: list[tuple[str, str]] = []
            for rpc_entry in rpc_raw:
                if isinstance(rpc_entry, dict):
                    rpc_cmd = str(rpc_entry.get("command", ""))
                    rpc_cwd = str(rpc_entry.get("cwd") or repo)
                else:
                    rpc_cmd = str(rpc_entry)
                    rpc_cwd = repo
                rpc_parsed.append((rpc_cmd, rpc_cwd))
            # tool_enhance.md productionization pass, tool #9 (2026-08-16)
            # — same real boundary-escape found and fixed for the `bash`
            # tool just above: each sub-command's own `cwd` gets the same
            # check_path_in_worktree validation before any of them run.
            for rpc_cmd, rpc_cwd in rpc_parsed:
                rpc_cwd_check = check_path_in_worktree(rpc_cwd, repo)
                if not rpc_cwd_check.allowed:
                    return f"[POLICY DENIED] {rpc_cwd_check.reason}"
                if rpc_cmd and _is_dangerous_command(rpc_cmd):
                    return (
                        f"[POLICY DENIED] {rpc_cmd!r} looks destructive/dangerous — "
                        "run_parallel_commands does not support the bash tool's "
                        "human-confirmation flow. Run it individually via bash instead."
                    )

            async def _rpc_run_one(cmd: str, cwd: str) -> str:
                if not cmd:
                    return "[ERROR] empty command"
                return await asyncio.to_thread(_run_bash_tool, cmd, cwd, rpc_timeout)

            rpc_results = await asyncio.gather(
                *(_rpc_run_one(c, w) for c, w in rpc_parsed)
            )
            return "\n\n".join(
                f"=== [{i}] {cmd[:80]!r} ===\n{res}"
                for i, ((cmd, _w), res) in enumerate(zip(rpc_parsed, rpc_results))
            )

        # ========== TESTING / LINTING ==========

        if tool_name == "run_tests":
            return await asyncio.to_thread(
                run_tests_handler,
                repo,
                inp,
                activate_snippet=_venv_activate_snippet(),
            )

        if tool_name == "run_linter":
            lint_tool = str(inp.get("tool", "all"))
            lint_path = str(inp.get("path", ""))
            fix = bool(inp.get("fix", False))
            lint_parts: list[str] = []

            async def _lint(cmd_str: str, label: str, diag_tool: str = "") -> None:
                out = await asyncio.to_thread(_run_subprocess, cmd_str, repo, 90)
                out = out or "clean"
                summary = (
                    parse_diagnostic_summary(out, diag_tool) if diag_tool else None
                )
                header = f"=== {label} ===" + (f" {summary}" if summary else "")
                lint_parts.append(f"{header}\n{out}")

            if lint_tool in ("ruff", "all"):
                t = lint_path or repo
                await _lint(
                    f"cd {repo} && {_venv_activate_snippet()} && python -m ruff check {t} {'--fix' if fix else ''} 2>&1 | head -50",
                    "ruff",
                    "ruff",
                )
            if lint_tool in ("mypy", "all"):
                t = lint_path or repo
                await _lint(
                    f"cd {repo} && {_venv_activate_snippet()} && python -m mypy {t} --ignore-missing-imports 2>&1 | head -50",
                    "mypy",
                    "mypy",
                )
            if lint_tool in ("tsc", "all"):
                web = str(root.parent / "apps" / "web")
                await _lint(
                    f"cd {web} && npx tsc --noEmit 2>&1 | head -50", "tsc", "tsc"
                )
            if lint_tool == "black":
                t = lint_path or repo
                await _lint(
                    f"cd {repo} && {_venv_activate_snippet()} && python -m black {'--check' if not fix else ''} {t} 2>&1 | head -50",
                    "black",
                )

            return "\n\n".join(lint_parts) or f"[ERROR] Unknown linter: {lint_tool}"

        if tool_name == "submit_result":
            return (
                f"Task complete: {inp.get('status', 'done')}\n{inp.get('summary', '')}"
            )

        # ========== BATCH 1 — File / Editing extras ==========

        if tool_name == "find_file":
            name = str(inp["name"])
            ff_dir = str(inp.get("directory", ""))
            ff_root = root / ff_dir if ff_dir else root
            try:
                r = await asyncio.to_thread(
                    subprocess.run,
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
                ff_rel_paths: list[str] = []
                for ff_path in found[:100]:
                    try:
                        ff_rel_paths.append(str(Path(ff_path).relative_to(root)))
                    except ValueError:
                        ff_rel_paths.append(ff_path)
                return "\n".join(ff_rel_paths)
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "format_file":
            rel = str(inp["path"])
            formatter = str(inp.get("formatter", "auto"))
            fmt_target = root / rel
            if not fmt_target.exists():
                return f"[ERROR] File not found: {rel}"
            if formatter == "auto":
                formatter = "ruff" if fmt_target.suffix == ".py" else "prettier"
            # AUDIT_Q_BATCH01 §1 "Windows terminal support" — was hardcoded
            # POSIX `source`, silently never activating the venv on Windows
            # (relative path is safe here: _run_subprocess always passes
            # cwd=repo, so the shell's starting directory is already repo,
            # matching this line's previous absolute-path behavior exactly
            # on POSIX while adding a real Windows branch).
            activate = _venv_activate_snippet()
            if formatter in ("ruff", "black"):
                cmd_s = (
                    f"{activate} && python -m {formatter} format {str(fmt_target)} 2>&1"
                )
            else:
                cmd_s = f"cd {repo} && npx prettier --write {str(fmt_target)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 30)

        if tool_name == "organize_imports":
            rel = str(inp["path"])
            oi_target = root / rel
            if not oi_target.exists():
                return f"[ERROR] File not found: {rel}"
            # AUDIT_Q_BATCH01 §1 "Windows terminal support" — was hardcoded
            # POSIX `source`, silently never activating the venv on Windows
            # (relative path is safe here: _run_subprocess always passes
            # cwd=repo, so the shell's starting directory is already repo,
            # matching this line's previous absolute-path behavior exactly
            # on POSIX while adding a real Windows branch).
            activate = _venv_activate_snippet()
            cmd_s = f"{activate} && python -m ruff check --select I --fix {str(oi_target)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 30)

        if tool_name == "insert_at_line":
            return insert_at_line_handler(root, repo, inp)

        if tool_name == "insert_after":
            # tool_enhance.md productionization pass, tool #46 (2026-08-19)
            # — same "advertised but never dispatched" bug class as tools
            # #4/#6/#22/#25/#33/#44/#45: already in CHAT_TOOLS, zero
            # dispatch here, every real call fell through to "Unknown
            # tool". Its worktree-boundary handling was already correct
            # (tool #11's fix, re-verified not re-fixed). Deferred, not
            # fixed here (same class + reasoning as tool #33's
            # delete_block): `pattern` is an LLM-controlled regex run via
            # re.search() per line with no timeout — real ReDoS exposure,
            # but Python's stdlib re has no timeout primitive.
            return insert_after_handler(root, repo, inp)

        if tool_name == "insert_before":
            # tool_enhance.md productionization pass, tool #48 (2026-08-20)
            # — identical shape to tool #46's insert_after (its exact
            # mirror-image sibling): same "advertised but never
            # dispatched" bug class, same already-correct worktree check,
            # same deferred ReDoS finding on `pattern` (documented, not
            # fixed, matching tools #33/#46's reasoning).
            return insert_before_handler(root, repo, inp)

        if tool_name == "replace_function":
            return replace_function_handler(root, repo, inp)

        if tool_name == "delete_lines":
            return delete_lines_handler(root, repo, inp)

        if tool_name == "apply_patch":
            return await asyncio.to_thread(apply_patch_handler, repo, inp)

        if tool_name == "compare_files":
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

        if tool_name == "sync_files":
            sf_source = str(inp["source"])
            sf_targets = inp.get("paths") or []
            if not sf_targets:
                return "[ERROR] paths must be a non-empty list of target file paths"
            sf_source_path = root / sf_source
            if not sf_source_path.exists():
                return f"[ERROR] Source file not found: {sf_source}"
            try:
                sf_content = sf_source_path.read_text(encoding="utf-8")
            except Exception as e:
                return f"[ERROR] Could not read source {sf_source}: {e}"
            sf_results: list[str] = []
            for sf_target in sf_targets:
                sf_target = str(sf_target)
                sf_tgt_path = root / sf_target
                try:
                    sf_existing = (
                        sf_tgt_path.read_text(encoding="utf-8")
                        if sf_tgt_path.exists()
                        else None
                    )
                except Exception as e:
                    sf_results.append(f"  {sf_target}: [ERROR] {e}")
                    continue
                if sf_existing == sf_content:
                    sf_results.append(f"  {sf_target}: unchanged (already in sync)")
                    continue
                try:
                    sf_tgt_path.parent.mkdir(parents=True, exist_ok=True)
                    sf_tgt_path.write_text(sf_content, encoding="utf-8")
                    sf_results.append(
                        f"  {sf_target}: "
                        f"{'created' if sf_existing is None else 'updated'} from {sf_source}"
                    )
                except Exception as e:
                    sf_results.append(f"  {sf_target}: [ERROR] {e}")
            return (
                f"Synchronized '{sf_source}' to {len(sf_targets)} target(s):\n"
                + "\n".join(sf_results)
            )

        # ========== BATCH 2 — Terminal extras ==========

        if tool_name == "run_background":
            # tool_enhance.md productionization pass, tool #58 (2026-08-20)
            # — real, severe finding, raised to the user before fixing
            # (AskUserQuestion) given the scope: `command` had zero
            # sandboxing at all, full unrestricted host shell execution —
            # the same unsandboxed state bash (tool #1) was in before its
            # own real Docker-sandboxing remediation. Fixed at the shared
            # process_manager.spawn() (now routes through a real
            # Docker sandbox when enabled — see that function's own
            # docstring, including a retroactive kill_process fix found
            # along the way). `cwd` now gets bind-mounted into the
            # sandbox, so it must stay inside the repo — validated here
            # before spawn() is ever called.
            from app.fleet import process_manager as _pm

            rb_command = str(inp["command"])
            rb_cwd = str(inp.get("cwd") or repo)
            rb_policy = check_command(rb_command)
            if not rb_policy.allowed:
                return f"[POLICY DENIED] {rb_policy.reason}"
            rb_cwd_error = validate_run_background_cwd(rb_cwd, repo)
            if rb_cwd_error:
                return rb_cwd_error
            rb_wait_for = inp.get("wait_for_pids")
            rb_wait_pids = [int(p) for p in rb_wait_for] if rb_wait_for else None
            return _pm.spawn(
                rb_command,
                rb_cwd,
                self._background_processes,
                wait_for_pids=rb_wait_pids,
            )

        if tool_name == "kill_process":
            # tool_enhance.md productionization pass, tool #49 (2026-08-20)
            # — real, severe finding, proved live: process_manager.kill()
            # previously sent os.kill() to ANY pid, not just ones this
            # session tracked, letting a real unrelated process (even the
            # server's own) be killed. Fixed at the shared implementation
            # itself (process_manager.kill()'s own docstring has the full
            # account) via an ownership gate — this call site is
            # unchanged, it already delegated there.
            from app.fleet import process_manager as _pm

            kp_pid = int(inp["pid"])
            kp_sig_name = str(inp.get("signal", "TERM"))
            return _pm.kill(kp_pid, kp_sig_name, self._background_processes)

        if tool_name == "list_background_processes":
            from app.fleet import process_manager as _pm

            return _pm.format_tracked(self._background_processes)

        if tool_name == "run_python_snippet":
            return await asyncio.to_thread(
                run_python_snippet_handler,
                repo,
                inp,
                activate_snippet=_venv_activate_snippet(),
            )

        if tool_name == "run_make":
            # tool_enhance.md productionization pass, tool #59 (2026-08-22)
            # — real, proven findings: (1) this dispatch used to interpolate
            # `target` raw into a shell=True command (classic shell
            # injection, proved live); (2) GNU make's own flags (e.g.
            # --eval) let a single flag-shaped `target` run arbitrary code
            # even with no shell involved — closed for both real call
            # sites at the shared validator; (3) `directory` could escape
            # the repo entirely (proved live: a real Makefile target ran
            # from outside the repo). Full account in run_make_handler()'s
            # own docstring. Now delegates to the same shared, fixed
            # handler `tools.py`'s implementation already used.
            return await asyncio.to_thread(run_make_handler, root, repo, inp)

        if tool_name == "fetch_url":
            fu_url = str(inp["url"])
            fu_timeout = int(inp.get("timeout", 15))
            fu_summarize = bool(inp.get("summarize", False))
            fu_ssrf_reason = _ssrf_denial_reason(fu_url)
            if fu_ssrf_reason:
                return f"[POLICY DENIED] {fu_ssrf_reason}"
            import shlex as _shlex_fu

            cmd_s = f"curl -s -L --max-time {fu_timeout} --user-agent 'Gridiron-Agent/1.0' {_shlex_fu.quote(fu_url)} 2>&1"
            fu_raw = await asyncio.to_thread(
                _run_subprocess, cmd_s, repo, fu_timeout + 5
            )
            if fu_summarize and fu_raw and not fu_raw.startswith("[ERROR]"):
                fu_summary = await asyncio.to_thread(
                    _llm_summarize_url_content, fu_url, fu_raw
                )
                if fu_summary:
                    return f"=== Summary ===\n{fu_summary}\n\n=== Raw content (first 10000 chars) ===\n{fu_raw[:10000]}"
            return fu_raw

        # ========== BATCH 3 — Git extras ==========

        if tool_name == "git_merge":
            gm_branch = str(inp["branch"])
            gm_error = validate_git_merge_inputs(gm_branch)
            if gm_error:
                return gm_error
            gm_no_ff = bool(inp.get("no_ff", False))
            gm_squash = bool(inp.get("squash", False))
            gm_msg = str(inp.get("message", ""))
            gm_args = (
                ["merge"]
                + (["--no-ff"] if gm_no_ff else [])
                + (["--squash"] if gm_squash else [])
            )
            if gm_msg:
                gm_args += ["-m", gm_msg]
            gm_args.append(gm_branch)
            gm_output = _git(gm_args, repo)
            if gm_output.startswith("[ERROR]") or "CONFLICT" in gm_output:
                gm_conflicted = _git(["diff", "--name-only", "--diff-filter=U"], repo)
                gm_files = [f for f in gm_conflicted.strip().split("\n") if f]
                if gm_files:
                    return (
                        f"[CONFLICT] Merge of {gm_branch} has real conflicts in "
                        f"{len(gm_files)} file(s): {', '.join(gm_files)}. Use "
                        f"parse_merge_conflicts on each, then resolve_merge_conflict "
                        f"to resolve, then git_commit to finish the merge.\n{gm_output}"
                    )
            return gm_output

        if tool_name == "parse_merge_conflicts":
            pmc_rel = str(inp["path"])
            if _is_protected_path(pmc_rel, repo):
                return f"[POLICY DENIED] Protected path: {pmc_rel}"
            pmc_target = root / pmc_rel
            if not pmc_target.exists():
                return f"[ERROR] File not found: {pmc_rel}"
            pmc_text = pmc_target.read_text(encoding="utf-8")
            pmc_hunks = _parse_conflict_markers(pmc_text)
            if not pmc_hunks:
                return f"No conflict markers found in {pmc_rel}."
            import json as _json

            return _json.dumps({"path": pmc_rel, "hunks": pmc_hunks}, indent=2)

        if tool_name == "resolve_merge_conflict":
            rmc_rel = str(inp["path"])
            if _is_protected_path(rmc_rel, repo):
                return f"[POLICY DENIED] Protected path: {rmc_rel}"
            rmc_target = root / rmc_rel
            if not rmc_target.exists():
                return f"[ERROR] File not found: {rmc_rel}"
            rmc_raw_resolutions = inp.get("resolutions") or []
            if not rmc_raw_resolutions:
                return "[ERROR] resolutions is required — at least one {index, choice}"
            rmc_resolutions: dict[int, dict[str, Any]] = {}
            for entry in rmc_raw_resolutions:
                rmc_idx = int(entry["index"])
                rmc_choice = str(entry.get("choice", ""))
                if rmc_choice == "custom" and "custom_content" not in entry:
                    return (
                        f"[ERROR] hunk {rmc_idx}: choice='custom' requires "
                        "custom_content"
                    )
                rmc_resolutions[rmc_idx] = entry
            rmc_text = rmc_target.read_text(encoding="utf-8")
            rmc_new_text, rmc_applied, rmc_unresolved = _apply_conflict_resolutions(
                rmc_text, rmc_resolutions
            )
            rmc_target.write_text(rmc_new_text, encoding="utf-8")
            if rmc_unresolved:
                return (
                    f"Resolved {len(rmc_applied)} hunk(s) in {rmc_rel}. "
                    f"Still unresolved (markers left intact): {rmc_unresolved}"
                )
            return f"Resolved all {len(rmc_applied)} conflict hunk(s) in {rmc_rel}."

        if tool_name == "explain_merge_conflict":
            emc_rel = str(inp["path"])
            if _is_protected_path(emc_rel, repo):
                return f"[POLICY DENIED] Protected path: {emc_rel}"
            emc_target = root / emc_rel
            if not emc_target.exists():
                return f"[ERROR] File not found: {emc_rel}"
            emc_text = emc_target.read_text(encoding="utf-8")
            emc_hunks = _parse_conflict_markers(emc_text)
            if not emc_hunks:
                return f"No conflict markers found in {emc_rel}."
            return await asyncio.to_thread(
                _llm_explain_conflict_hunks, emc_rel, emc_hunks
            )

        if tool_name == "git_reset":
            gr_ref = str(inp.get("ref", "HEAD"))
            gr_mode = str(inp.get("mode", "mixed"))
            # tool_enhance.md productionization pass, tool #5 (2026-08-16)
            # — real, empirically-verified confirmation bypass found while
            # auditing this tool: `git reset --soft --hard HEAD` actually
            # performs a HARD reset (git takes the LAST reset-mode flag as
            # authoritative — verified directly, not assumed: a real repo
            # with an uncommitted change had it silently discarded).
            # Building the command as ["git", "reset", f"--{gr_mode}",
            # gr_ref] meant a caller could set mode="soft" (bypassing the
            # confirmation check below entirely) while setting
            # ref="--hard", which git then reads as a second mode flag —
            # a real, exploitable way to perform an unconfirmed hard reset.
            # validate_git_reset_inputs (shared with the second, currently
            # unreachable make_chat_handlers() implementation of this same
            # tool) closes this before ever reaching the confirmation check.
            gr_validation_error = validate_git_reset_inputs(gr_mode, gr_ref)
            if gr_validation_error:
                return gr_validation_error
            if gr_mode == "hard":
                approved = await self._confirm(
                    description="git reset --hard — discards ALL uncommitted changes",
                    details=f"git reset --hard {gr_ref}",
                )
                if not approved:
                    return "[DENIED] User declined git reset --hard."
            return _git(["reset", f"--{gr_mode}", gr_ref], repo)

        if tool_name == "git_worktree":
            gw_action = str(inp.get("action", "list"))
            gw_wt_path = str(inp.get("path", ""))
            gw_branch = str(inp.get("branch", ""))
            gw_error = validate_git_worktree_inputs(gw_action, gw_wt_path, gw_branch)
            if gw_error:
                return gw_error
            if gw_action == "list":
                return _git(["worktree", "list"], repo)
            elif gw_action == "add":
                gw_confirmed = await self._confirm(
                    description=f"git worktree add {gw_wt_path} {gw_branch}",
                    details=(
                        "Creates a full checkout of the branch's tree at "
                        f"{gw_wt_path!r} — this path may be anywhere on "
                        "disk, including outside the current repository."
                    ),
                )
                if not gw_confirmed:
                    return f"[CANCELLED] git_worktree add {gw_wt_path} cancelled by user"
                return await asyncio.to_thread(
                    _git, ["worktree", "add", "--", gw_wt_path, gw_branch], repo, 30
                )
            elif gw_action == "remove":
                return _git(["worktree", "remove", "--", gw_wt_path], repo)
            return f"[ERROR] Unknown action: {gw_action}"

        if tool_name in ("create_pr", "github_create_pr"):
            # tool_enhance.md productionization pass, tool #6 (2026-08-16)
            # — real finding: github_create_pr is functionally the same
            # action as create_pr (both run `gh pr create`), just with a
            # schema that requires title/body explicitly instead of
            # offering LLM auto-generation. It had NO dispatch here at
            # all despite being advertised via CHAT_TOOLS/
            # AGENT_CONTRACT["allowed_tools"] — every real call fell
            # through to "[ERROR] Unknown tool", the same live bug class
            # found for npm_install/npm_run/pip_install in tool #4.
            # Routed through this same, already-hardened block (confirmed
            # safe: with title/body always supplied per its schema, the
            # auto-generation branch below simply never triggers) rather
            # than building a second, separately-maintained, unhardened
            # implementation — real duplication tool #2's own pass
            # already flagged as a risk pattern to avoid repeating.
            pr_title = str(inp.get("title", "")).strip()
            pr_body = str(inp.get("body", "")).strip()
            pr_base = str(inp.get("base", "main"))
            pr_draft = bool(inp.get("draft", False))
            if not pr_title or not pr_body:
                pr_stat = _git(["diff", f"{pr_base}...HEAD", "--stat"], repo)
                pr_diff = _git(["diff", f"{pr_base}...HEAD"], repo)[:6000]
                pr_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
                if pr_stat and not pr_stat.startswith("[ERROR]"):
                    gen_title, gen_body = await asyncio.to_thread(
                        _llm_generate_pr_description,
                        pr_stat,
                        pr_diff,
                        pr_branch,
                        pr_base,
                    )
                    pr_title = pr_title or gen_title
                    pr_body = pr_body or gen_body
            if not pr_title:
                return "[ERROR] title is required (auto-generation failed — supply one explicitly)"
            # tool_enhance.md productionization pass, tool #2 (2026-08-15) —
            # real gap found by reading this code: creating a PR is a real,
            # publicly-visible external write (permissions: write_remote in
            # its manifest), yet — unlike git_push and git_reset --hard
            # right above this in the same dispatch — it had no
            # confirmation gate at all. Confirmed AFTER title/body are
            # resolved (including LLM auto-generation) so the human sees
            # the real content that will actually be posted, not a preview
            # of empty/unresolved fields.
            approved = await self._confirm(
                description="Create a GitHub pull request",
                details=(
                    f"gh pr create --title {pr_title!r} --base {pr_base!r}"
                    f"{' --draft' if pr_draft else ''}\n\n{pr_body}"
                ),
            )
            if not approved:
                return "[DENIED] User declined create_pr."
            # Shared with app/tools/git/pull_request.py::create_pr_handler
            # (the other real create_pr implementation) — previously each
            # built this command independently and had already drifted
            # apart; tool_enhance.md productionization pass, tool #2.
            pr_cmd_parts = build_gh_pr_create_command(
                pr_title, pr_base, pr_body, pr_draft
            )
            cmd_s = " ".join(__import__("shlex").quote(c) for c in pr_cmd_parts)
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 30)

        if tool_name == "generate_commit_msg":
            gcm_staged = bool(inp.get("staged_only", True))
            gcm_diff_args = ["diff", "--cached"] if gcm_staged else ["diff"]
            gcm_stat = _git(gcm_diff_args + ["--stat"], repo)
            gcm_diff = _git(gcm_diff_args, repo)[:3000]
            if not gcm_stat.strip():
                return "[ERROR] No staged changes. Stage files first."
            gcm_generated = await asyncio.to_thread(
                _llm_generate_commit_message, gcm_stat, gcm_diff
            )
            if gcm_generated:
                return (
                    f"=== Generated commit message ===\n{gcm_generated}\n\n"
                    f"=== Changed files ===\n{gcm_stat}\n\n"
                    f"=== Diff (truncated) ===\n{gcm_diff}"
                )
            return (
                f"=== Changed files ===\n{gcm_stat}\n\n"
                f"=== Diff (truncated) ===\n{gcm_diff}\n\n"
                "Write a conventional commit message:\n"
                "Format: <type>(<scope>): <description>\n"
                "Types: feat, fix, docs, refactor, test, chore, style, perf"
            )

        if tool_name == "review_diff":
            rd_staged = bool(inp.get("staged_only", True))
            rd_base = str(inp.get("base", "")).strip()
            if rd_base:
                rd_diff_args = ["diff", f"{rd_base}...HEAD"]
            elif rd_staged:
                rd_diff_args = ["diff", "--cached"]
            else:
                rd_diff_args = ["diff"]
            rd_stat = _git(rd_diff_args + ["--stat"], repo)
            rd_diff = _git(rd_diff_args, repo)[:6000]
            if not rd_stat.strip() or rd_stat.startswith("[ERROR]"):
                return "[ERROR] No changes to review for the given scope."
            rd_review = await asyncio.to_thread(_llm_review_diff, rd_stat, rd_diff)
            if rd_review:
                return (
                    f"=== Changed files ===\n{rd_stat}\n\n=== Review ===\n{rd_review}"
                )
            return (
                f"[ERROR] Review generation unavailable — raw diff below.\n\n"
                f"=== Changed files ===\n{rd_stat}\n\n=== Diff ===\n{rd_diff}"
            )

        if tool_name == "github_comment":
            # tool_enhance.md productionization pass, tool #44 (2026-08-19)
            # — same "advertised but never dispatched" bug class as tools
            # #4/#6/#22/#25/#33: github_comment was already in CHAT_TOOLS
            # (see the correction note in
            # docs/tool_productionization/github_comment.md for how an
            # earlier pass of this same audit briefly got that wrong) but
            # had zero dispatch here, so no live agent could ever reach it.
            # Posting a comment is a real, publicly-visible external write
            # (permissions: write_remote) — same risk category as create_pr
            # (tool #2) — so this mirrors that tool's exact confirmation
            # pattern: confirm AFTER all fields are resolved, so the human
            # sees the real content that will actually be posted.
            gc_number = int(inp["number"])
            gc_body = str(inp["body"])
            gc_kind = str(inp.get("kind", "issue"))
            gc_cmd = github_comment_command(gc_number, gc_body, gc_kind)
            gc_approved = await self._confirm(
                description=f"Post a comment on GitHub {gc_kind} #{gc_number}",
                details=f"{' '.join(gc_cmd[:-1])!r} <<< {gc_body!r}",
            )
            if not gc_approved:
                return "[DENIED] User declined github_comment."
            try:
                gc_r = await asyncio.to_thread(
                    subprocess.run,
                    gc_cmd,
                    capture_output=True,
                    text=True,
                    cwd=repo,
                    timeout=30,
                )
                return (gc_r.stdout + gc_r.stderr).strip() or "Comment posted"
            except FileNotFoundError:
                return "[ERROR] gh CLI not found"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "github_create_issue":
            # tool_enhance.md productionization pass, tool #45 (2026-08-19)
            # — same "advertised but never dispatched" bug class as tool
            # #44's github_comment: already in CHAT_TOOLS ("Day 3G —
            # External integrations"), zero dispatch here, every real call
            # fell through to "Unknown tool". Creating a GitHub issue is a
            # real, publicly-visible external write — same risk category
            # as create_pr/github_comment — so this mirrors their exact
            # confirmation pattern.
            gci_title = str(inp["title"])
            gci_body = str(inp["body"])
            gci_labels = [str(lbl) for lbl in inp.get("labels", [])]
            gci_cmd = github_create_issue_command(gci_title, gci_body, gci_labels)
            gci_approved = await self._confirm(
                description=f"Create a GitHub issue: {gci_title!r}",
                details=f"{' '.join(gci_cmd[:-1])!r} <<< {gci_body!r}",
            )
            if not gci_approved:
                return "[DENIED] User declined github_create_issue."
            try:
                gci_r = await asyncio.to_thread(
                    subprocess.run,
                    gci_cmd,
                    capture_output=True,
                    text=True,
                    cwd=repo,
                    timeout=30,
                )
                return (gci_r.stdout + gci_r.stderr).strip() or "(no output)"
            except FileNotFoundError:
                return "[ERROR] gh CLI not found — install GitHub CLI"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "linear_create_issue":
            # tool_enhance.md productionization pass, tool #50 (2026-08-20)
            # — same "advertised but never dispatched" bug class as tools
            # #44/#45: already in CHAT_TOOLS, zero dispatch here, every
            # real call fell through to "Unknown tool". Its own request-
            # building logic was already safe (GraphQL variables, never
            # string-interpolated into the query). Creating a Linear
            # issue is a real external write with a real cost/consequence
            # — same risk category as create_pr/github_comment/
            # github_create_issue — so this mirrors their confirmation
            # pattern.
            lci_api_key = os.environ.get("LINEAR_API_KEY", "")
            if not lci_api_key:
                return "[ERROR] LINEAR_API_KEY not set"
            lci_title = str(inp["title"])
            lci_description = str(inp["description"])
            lci_team_key = str(inp["team_key"])
            lci_approved = await self._confirm(
                description=f"Create a Linear issue in team {lci_team_key!r}: {lci_title!r}",
                details=lci_description,
            )
            if not lci_approved:
                return "[DENIED] User declined linear_create_issue."
            return await asyncio.to_thread(
                create_linear_issue, lci_api_key, lci_title, lci_description, lci_team_key
            )

        if tool_name == "memory_write":
            # tool_enhance.md productionization pass, tool #51 (2026-08-20)
            # — same "advertised but never dispatched" bug class as tools
            # #44/#45/#50: already in CHAT_TOOLS, zero dispatch here,
            # every real call fell through to "Unknown tool". Also found
            # a real, severe, empirically-proven data-loss race
            # condition in the underlying store logic (17 of 20
            # concurrent writes silently lost) — fixed at the shared
            # write_memory_key() implementation itself; see that
            # function's own docstring. Purely a local, non-externally-
            # visible write (unlike create_pr/github_comment/
            # linear_create_issue), so no confirmation gate needed here.
            mw_key = str(inp["key"])
            mw_value = str(inp["value"])
            return await asyncio.to_thread(write_memory_key, repo, mw_key, mw_value)

        if tool_name == "inspect_github_repo":
            return await asyncio.to_thread(_inspect_github_repo, inp)

        if tool_name == "inspect_openapi_spec":
            return await asyncio.to_thread(_inspect_openapi_spec, inp)

        # ========== BATCH 4 — Testing extras ==========

        if tool_name == "run_single_test":
            rst_kw = str(inp["keyword"])
            rst_file = str(inp.get("file", ""))
            rst_verbose = bool(inp.get("verbose", True))
            rst_vflag = "-v" if rst_verbose else "-q"
            # AUDIT_Q_BATCH01 §1 "Windows terminal support" — was hardcoded
            # POSIX `source`, silently never activating the venv on Windows
            # (relative path is safe here: _run_subprocess always passes
            # cwd=repo, so the shell's starting directory is already repo,
            # matching this line's previous absolute-path behavior exactly
            # on POSIX while adding a real Windows branch).
            activate = _venv_activate_snippet()
            rst_path = rst_file if rst_file else "backend/tests/"
            cmd_s = f"{activate} && python -m pytest {rst_path} -k '{rst_kw}' {rst_vflag} --tb=short 2>&1 | head -100"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 120)

        if tool_name == "coverage_report":
            cov_path = str(inp.get("path", "backend/tests/"))
            cov_source = str(inp.get("source", "backend/app/"))
            cov_min = inp.get("min_coverage")
            # AUDIT_Q_BATCH01 §1 "Windows terminal support" — was hardcoded
            # POSIX `source`, silently never activating the venv on Windows
            # (relative path is safe here: _run_subprocess always passes
            # cwd=repo, so the shell's starting directory is already repo,
            # matching this line's previous absolute-path behavior exactly
            # on POSIX while adding a real Windows branch).
            activate = _venv_activate_snippet()
            cov_min_flag = f"--cov-fail-under={cov_min}" if cov_min else ""
            cmd_s = (
                f"{activate} && python -m pytest {cov_path} "
                f"--cov={cov_source} --cov-report=term-missing {cov_min_flag} "
                f"--tb=no -q 2>&1 | tail -50"
            )
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 180)

        if tool_name == "type_check":
            tc_path = str(inp.get("path", ""))
            tc_strict = bool(inp.get("strict", False))
            tc_lang = str(inp.get("language", "both"))
            # AUDIT_Q_BATCH01 §1 "Windows terminal support" — was hardcoded
            # POSIX `source`, silently never activating the venv on Windows
            # (relative path is safe here: _run_subprocess always passes
            # cwd=repo, so the shell's starting directory is already repo,
            # matching this line's previous absolute-path behavior exactly
            # on POSIX while adding a real Windows branch).
            activate = _venv_activate_snippet()
            tc_results: list[str] = []
            if tc_lang in ("python", "both"):
                py_path = tc_path or "backend/"
                sf = "--strict" if tc_strict else "--ignore-missing-imports"
                tc_results.append(
                    await asyncio.to_thread(
                        _run_subprocess,
                        f"{activate} && python -m mypy {py_path} {sf} 2>&1 | head -60",
                        repo,
                        90,
                    )
                )
            if tc_lang in ("typescript", "both"):
                web = str(root.parent / "apps" / "web")
                tc_results.append(
                    await asyncio.to_thread(
                        _run_subprocess,
                        f"cd {web} && npx tsc --noEmit 2>&1 | head -60",
                        repo,
                        90,
                    )
                )
            return "\n\n".join(tc_results) or "[ERROR] No language selected"

        # ========== BATCH 5 — Code Intelligence ==========

        if tool_name == "list_functions":
            rel = str(inp["path"])
            lf_fp = root / rel
            if not lf_fp.exists():
                return f"[ERROR] File not found: {rel}"
            lf_lines = lf_fp.read_text(encoding="utf-8", errors="replace").splitlines()
            lf_results: list[str] = []
            for lf_i, lf_line in enumerate(lf_lines, 1):
                s = lf_line.strip()
                if s.startswith(("def ", "async def ")):
                    lf_results.append(
                        f"  L{lf_i}: {s.split(':')[0] if ':' in s else s}"
                    )
                elif (
                    s.startswith(
                        ("export function ", "export async function ", "function ")
                    )
                    and "(" in s
                ):
                    lf_results.append(f"  L{lf_i}: {s[:120]}")
                elif s.startswith(("export const ", "const ")) and (
                    "=>" in s or "= (" in s or "= async" in s
                ):
                    lf_results.append(f"  L{lf_i}: {s[:120]}")
            return (
                f"Functions in {rel} ({len(lf_results)}):\n" + "\n".join(lf_results)
                if lf_results
                else f"(no functions in {rel})"
            )

        if tool_name == "list_classes":
            rel = str(inp["path"])
            lc_fp = root / rel
            if not lc_fp.exists():
                return f"[ERROR] File not found: {rel}"
            lc_lines = lc_fp.read_text(encoding="utf-8", errors="replace").splitlines()
            lc_results: list[str] = []
            lc_current: str | None = None
            lc_base_indent = 0
            for lc_i, lc_line in enumerate(lc_lines, 1):
                s = lc_line.strip()
                curr_indent = len(lc_line) - len(lc_line.lstrip())
                if s.startswith(("class ", "export class ", "export default class ")):
                    lc_current = s.split("(")[0].split("{")[0].rstrip()
                    lc_base_indent = curr_indent
                    lc_results.append(f"\nL{lc_i}: {lc_current}")
                elif lc_current and curr_indent > lc_base_indent:
                    if s.startswith(("def ", "async def ")):
                        lc_results.append(f"    L{lc_i}: {s.split(':')[0]}")
                    elif (
                        s.startswith(
                            ("public ", "private ", "protected ", "async ", "static ")
                        )
                        and "(" in s
                    ):
                        lc_results.append(f"    L{lc_i}: {s[:120]}")
                elif (
                    lc_current
                    and lc_line.strip()
                    and curr_indent <= lc_base_indent
                    and not s.startswith(("@", "#", "/"))
                ):
                    lc_current = None
            return (
                f"Classes in {rel}:\n" + "\n".join(lc_results)
                if lc_results
                else f"(no classes in {rel})"
            )

        if tool_name == "find_function_body":
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
                ffb_jl = ffb_lines[ffb_j]
                if ffb_jl.strip() == "":
                    continue
                ffb_jind = len(ffb_jl) - len(ffb_jl.lstrip())
                if (
                    ffb_jind <= ffb_base
                    and ffb_jl.strip()
                    and not ffb_jl.strip().startswith(("@", "#"))
                ):
                    ffb_end = ffb_j
                    break
            body = "".join(ffb_lines[ffb_start:ffb_end])
            return f"=== {ffb_name} (lines {ffb_start + 1}-{ffb_end}) ===\n{body}"

        # ========== BATCH 6 — Debug tools ==========

        if tool_name == "read_logs":
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
                found_logs: list[Path] = []
                for ld in log_dirs:
                    if ld.exists():
                        found_logs.extend(ld.glob("*.log"))
                if not found_logs:
                    return "(no log files found — specify path or service name)"
                newest = max(found_logs, key=lambda p: p.stat().st_mtime)
                r = subprocess.run(
                    ["tail", f"-{rl_lines}", str(newest)],
                    capture_output=True,
                    text=True,
                )
                out = f"From {newest}:\n" + r.stdout
            if rl_level != "all":
                out = "\n".join(
                    line
                    for line in out.splitlines()
                    if rl_level.upper() in line.upper()
                )
            return out[:5000] or "(no log entries)"

        if tool_name == "analyze_error":
            ae_error = str(inp["error"])
            ae_lines = ae_error.strip().splitlines()
            exception_line = ""
            for ae_line in reversed(ae_lines):
                if any(
                    x in ae_line
                    for x in ("Error:", "Exception:", "Warning:", "Traceback")
                ):
                    exception_line = ae_line
                    break
            ae_frames: list[str] = []
            ae_i = 0
            while ae_i < len(ae_lines):
                ae_line = ae_lines[ae_i]
                if ae_line.strip().startswith("File ") and "line " in ae_line:
                    if not any(
                        x in ae_line for x in ("site-packages", ".venv", "lib/python")
                    ):
                        code_line = (
                            ae_lines[ae_i + 1].strip()
                            if ae_i + 1 < len(ae_lines)
                            else ""
                        )
                        ae_frames.append(f"  {ae_line.strip()}\n    → {code_line}")
                    ae_i += 2
                else:
                    ae_i += 1
            ae_result = ["=== Error Analysis ==="]
            if exception_line:
                ae_result.append(f"Exception: {exception_line.strip()}")
            if ae_frames:
                ae_result.append(f"\nRelevant frames ({len(ae_frames)}):")
                ae_result.extend(ae_frames[-5:])
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
                suggestions.append(
                    "→ Wrong argument type/count — check function signature"
                )
            elif "keyerror" in ae_low:
                suggestions.append("→ Key not found — use .get() or check key exists")
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
            if suggestions:
                ae_result.append("\nSuggestions:")
                ae_result.extend(suggestions)
            return "\n".join(ae_result)

        # ========== BATCH 7 — Database tools ==========

        if tool_name == "run_sql":
            from app.config import get_settings as _get_settings

            rs_db_url = str(getattr(_get_settings(), "database_url", ""))
            return await asyncio.to_thread(run_sql_handler, rs_db_url, inp)

        if tool_name == "inspect_schema":
            from app.config import get_settings as _get_settings

            is_table = str(inp.get("table", ""))
            is_db_url = str(getattr(_get_settings(), "database_url", ""))
            if not is_db_url:
                return "[ERROR] DATABASE_URL not configured"
            if is_table:
                is_q = (
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    f"WHERE table_name = '{is_table}' ORDER BY ordinal_position"
                )
            else:
                is_q = (
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
            return await asyncio.to_thread(
                _run_subprocess,
                f"psql '{is_db_url}' -c {__import__('shlex').quote(is_q)} --no-password 2>&1",
                repo,
                10,
            )

        # ========== BATCH 8 — Docker tools ==========

        if tool_name == "docker_ps":
            show_all = bool(inp.get("all", False))
            cmd_s = (
                "docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}'"
                + (" -a" if show_all else "")
            )
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 10)

        if tool_name == "docker_logs":
            dl_container = str(inp["container"])
            dock_lines = int(inp.get("lines", 50))
            return await asyncio.to_thread(
                _run_subprocess,
                f"docker logs --tail {dock_lines} {dl_container} 2>&1",
                repo,
                15,
            )

        if tool_name == "docker_exec":
            de_container = str(inp["container"])
            de_command = str(inp["command"])
            de_cmd_policy = check_command(de_command)
            if not de_cmd_policy.allowed:
                return f"[POLICY DENIED] {de_cmd_policy.reason}"
            de_risk = _docker_container_risk_reason(de_container)
            if de_risk:
                return f"[POLICY DENIED] {de_risk}"
            return await asyncio.to_thread(
                _run_subprocess,
                build_docker_exec_command(de_container, de_command),
                repo,
                30,
            )

        if tool_name == "docker_compose":
            dc_action = str(inp["action"])
            dc_services = [str(s) for s in (inp.get("services") or [])]
            dc_detach = bool(inp.get("detach", True))
            if dc_action == "up":
                # tool_enhance.md productionization pass, tool #4 (2026-08-16)
                # — real gap found while auditing git_push's dead sibling in
                # tools.py: that unreachable code already identified 'up' as
                # needing confirmation ("creates/starts containers... with
                # no restriction on privileged/host-mount config"), but this
                # real, actually-executing dispatch had no gate at all.
                dc_cmd_preview = (
                    f"docker compose up {'-d' if dc_detach else ''} {' '.join(dc_services)}".strip()
                )
                dc_approved = await self._confirm(
                    description="Start containers via docker compose up",
                    details=dc_cmd_preview,
                )
                if not dc_approved:
                    return "[DENIED] User declined docker compose up."
            dc_cmd, dc_error = build_docker_compose_command(
                dc_action, dc_services, dc_detach
            )
            if dc_error:
                return f"[ERROR] {dc_error}"
            assert dc_cmd is not None
            return await asyncio.to_thread(_run_subprocess, dc_cmd, repo, 120)

        if tool_name == "npm_install":
            # tool_enhance.md productionization pass, tool #4 (2026-08-16)
            # — real bug found: npm_install is advertised to the model via
            # CHAT_TOOLS/AGENT_CONTRACT["allowed_tools"] (chat_agent's own
            # contract is built FROM CHAT_TOOLS), but _execute_tool had no
            # dispatch branch for it at all — every real call from the
            # interactive chat agent fell through to the generic "[ERROR]
            # Unknown tool" response. Confirmation-gated to match the real,
            # working pattern already used for pip_install below and for
            # git_push/docker_compose above — installing arbitrary
            # dependencies is a real side effect, not a read.
            #
            # tool_enhance.md productionization pass, tool #53 (2026-08-20)
            # — real, severe finding on this same turn's own full audit:
            # `directory` was never validated, letting npm run in an
            # arbitrary directory outside the repo. Proved live: a real
            # package.json with a malicious preinstall script, placed
            # outside the repo, had that script actually executed —
            # arbitrary command execution via npm's own lifecycle-script
            # mechanism. Fixed via validate_npm_install_directory().
            ni_directory = str(inp.get("directory", "."))
            ni_package = str(inp.get("package", "")).strip()
            ni_dir_error = validate_npm_install_directory(ni_directory, repo)
            if ni_dir_error:
                return ni_dir_error
            ni_target_dir = str(root / ni_directory)
            ni_cmd = ["npm", "install"] + ([ni_package] if ni_package else [])
            ni_approved = await self._confirm(
                description=(
                    f"Run npm install in {ni_directory}"
                    + (f" (package: {ni_package})" if ni_package else "")
                ),
                details=" ".join(ni_cmd),
            )
            if not ni_approved:
                return f"[DENIED] User declined npm_install ({' '.join(ni_cmd)})."

            def _run_npm_install() -> str:
                try:
                    r = subprocess.run(
                        ni_cmd,
                        capture_output=True,
                        text=True,
                        cwd=ni_target_dir,
                        timeout=120,
                    )
                    return (r.stdout + r.stderr).strip()[-2000:] or "npm install complete"
                except Exception as e:
                    return f"[ERROR] npm_install: {e}"

            return await asyncio.to_thread(_run_npm_install)

        if tool_name == "npm_run":
            # Real bug, same class as npm_install above — advertised via
            # CHAT_TOOLS, no dispatch existed. No confirmation gate,
            # matching tools.py's own npm_run_h precedent: running a
            # package.json script (build/test/lint) is lower-risk than
            # installing arbitrary new dependencies.
            #
            # tool_enhance.md productionization pass, tool #54 (2026-08-20)
            # — real, severe finding, same shape as tool #53's
            # npm_install: `directory` was never validated, letting npm
            # run in an arbitrary directory outside the repo. Proved
            # live (via make_chat_handlers, no confirmation gate at all
            # there): a real malicious package.json script, placed
            # outside the repo, was genuinely executed. Fixed via
            # validate_npm_run_directory(); the no-confirmation-gate
            # design above is kept, since it's only safe once directory
            # is actually constrained to this repo (this fix) — the
            # same trust level run_tests/run_make already operate at.
            nr_script = str(inp["script"])
            nr_directory = str(inp.get("directory", "."))
            nr_dir_error = validate_npm_run_directory(nr_directory, repo)
            if nr_dir_error:
                return nr_dir_error
            nr_target_dir = str(root / nr_directory)

            def _run_npm_script() -> str:
                try:
                    r = subprocess.run(
                        ["npm", "run", nr_script],
                        capture_output=True,
                        text=True,
                        cwd=nr_target_dir,
                        timeout=180,
                    )
                    return (
                        (r.stdout + r.stderr).strip()[-3000:]
                        or f"npm run {nr_script} complete"
                    )
                except Exception as e:
                    return f"[ERROR] npm_run: {e}"

            return await asyncio.to_thread(_run_npm_script)

        if tool_name == "pip_install":
            # Real bug, same class as npm_install above — advertised via
            # CHAT_TOOLS, no dispatch existed.
            #
            # tool_enhance.md productionization pass, tool #55 (2026-08-20)
            # — full audit found no new vulnerability: no directory/cwd
            # field exists (unlike npm_install/npm_run, no worktree-
            # escape surface), list-args (no shell injection), and this
            # confirmation gate already shows the human the exact raw
            # command before anything runs — the correct, intended
            # safeguard for pip's own rich package-spec syntax (editable/
            # VCS installs), which has no safe reject-boundary without
            # breaking real use. See app/tools/execution/pip_install.py's
            # docstring for the full audit, including a real (but
            # non-actionable) finding about pip's internal flag
            # recognition within a single package string.
            pi_package = str(inp["package"])
            pi_approved = await self._confirm(
                description=f"Install Python package: {pi_package}",
                details=f"pip install {pi_package}",
            )
            if not pi_approved:
                return f"[DENIED] User declined pip_install ({pi_package})."

            def _run_pip_install() -> str:
                try:
                    r = subprocess.run(
                        [sys.executable, "-m", "pip", "install", pi_package],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    return (r.stdout + r.stderr).strip()[-2000:]
                except Exception as e:
                    return f"[ERROR] pip_install: {e}"

            return await asyncio.to_thread(_run_pip_install)

        if tool_name == "diagnose_deployment_failure":
            dd_container = str(inp.get("container", "")).strip()
            dd_lines = int(inp.get("lines", 100))
            dd_ps = await asyncio.to_thread(
                _run_subprocess,
                "docker ps -a --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}'",
                repo,
                10,
            )
            dd_parts = [f"=== docker ps -a ===\n{dd_ps}"]
            if dd_container:
                dd_logs = await asyncio.to_thread(
                    _run_subprocess,
                    f"docker logs --tail {dd_lines} {dd_container} 2>&1",
                    repo,
                    15,
                )
                dd_parts.append(
                    f"=== docker logs --tail {dd_lines} {dd_container} ===\n{dd_logs or '(no logs)'}"
                )
                dd_inspect = await asyncio.to_thread(
                    _run_subprocess,
                    f"docker inspect {dd_container} 2>&1",
                    repo,
                    15,
                )
                import json as _json_dd

                try:
                    dd_data = _json_dd.loads(dd_inspect)
                    dd_state = (dd_data[0] if dd_data else {}).get("State", {})
                    dd_summary = {
                        "Status": dd_state.get("Status"),
                        "ExitCode": dd_state.get("ExitCode"),
                        "Error": dd_state.get("Error"),
                        "OOMKilled": dd_state.get("OOMKilled"),
                        "RestartCount": (dd_data[0] if dd_data else {}).get(
                            "RestartCount"
                        ),
                        "StartedAt": dd_state.get("StartedAt"),
                        "FinishedAt": dd_state.get("FinishedAt"),
                    }
                    dd_parts.append(
                        "=== docker inspect (State) ===\n"
                        + _json_dd.dumps(dd_summary, indent=2)
                    )
                except Exception:
                    dd_parts.append("=== docker inspect ===\n" + dd_inspect[:2000])
            dd_context = "\n\n".join(dd_parts)
            dd_diagnosis = await asyncio.to_thread(
                _llm_diagnose_deployment_failure, dd_context
            )
            return f"{dd_context}\n\n=== Diagnosis ===\n{dd_diagnosis}"

        # ========== BATCH 9 — Security ==========

        if tool_name == "secrets_scan":
            ss_dir = str(inp.get("directory", ""))
            ss_root = str(root / ss_dir) if ss_dir else repo
            ss_patterns = [
                r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{4,}['\"]",
                r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
                r"(?i)(secret[_-]?key|secretkey)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
                r"(sk-[a-zA-Z0-9]{20,})",
                r"(AKIA[0-9A-Z]{16})",
                r"(ghp_[a-zA-Z0-9]{36})",
            ]
            ss_exclude = [
                "--exclude-dir=node_modules",
                "--exclude-dir=.git",
                "--exclude-dir=.venv",
                "--exclude-dir=__pycache__",
                "--exclude=*.env",
                "--exclude=.env*",
                "--exclude=*.example",
            ]
            ss_findings: list[str] = []
            for ss_pat in ss_patterns:
                cmd_s = f"grep -rn -E {__import__('shlex').quote(ss_pat)} {ss_root} {' '.join(ss_exclude)} 2>/dev/null || true"
                result = await asyncio.to_thread(_run_subprocess, cmd_s, repo, 15)
                if result and result != "(no output)":
                    ss_findings.append(result)
            return (
                "⚠️  Potential secrets found:\n\n" + "\n\n".join(ss_findings)[:5000]
                if ss_findings
                else "✅ No hardcoded secrets detected."
            )

        # ========== BATCH 10 — AST Engine ==========

        if tool_name == "parse_ast":
            pa_rel = str(inp["path"])
            pa_fp = root / pa_rel
            if not pa_fp.exists():
                return f"[ERROR] File not found: {pa_rel}"
            return await asyncio.to_thread(_ast_engine.parse_file_ast, str(pa_fp))

        if tool_name == "import_graph":
            ig_rel = str(inp["path"])
            ig_fp = root / ig_rel
            if not ig_fp.exists():
                return f"[ERROR] File not found: {ig_rel}"
            return await asyncio.to_thread(_ast_engine.build_import_graph, str(ig_fp))

        if tool_name == "call_graph":
            cg_rel = str(inp["path"])
            cg_fn = str(inp.get("function_name", ""))
            cg_fp = root / cg_rel
            if not cg_fp.exists():
                return f"[ERROR] File not found: {cg_rel}"
            return await asyncio.to_thread(
                _ast_engine.build_call_graph, str(cg_fp), cg_fn
            )

        if tool_name == "dead_code_detect":
            dcd_d = str(inp.get("directory", ""))
            dcd_target = str(root / dcd_d) if dcd_d else repo
            return await asyncio.to_thread(_ast_engine.detect_dead_code, dcd_target)

        if tool_name == "circular_dep_detect":
            cdd_d = str(inp.get("directory", ""))
            cdd_target = str(root / cdd_d) if cdd_d else repo
            return await asyncio.to_thread(
                _ast_engine.detect_circular_imports, cdd_target
            )

        if tool_name == "rename_symbol":
            rsym_old = str(inp["old_name"])
            rsym_new = str(inp["new_name"])
            rsym_d = str(inp.get("directory", ""))
            rsym_pat = str(inp.get("file_pattern", "*.py"))
            rsym_error = validate_rename_symbol_directory(rsym_d, repo)
            if rsym_error:
                return f"[POLICY DENIED] {rsym_error}"
            rsym_target = str(root / rsym_d) if rsym_d else repo
            rsym_confirm = bool(inp.get("confirm_large_batch", False))
            if rsym_old == rsym_new:
                return "[ERROR] old_name and new_name are the same"
            return await asyncio.to_thread(
                _ast_engine.rename_symbol,
                rsym_old,
                rsym_new,
                rsym_target,
                rsym_pat,
                rsym_confirm,
            )

        # ========== BATCH 11 — Git extras ==========

        if tool_name == "git_rebase":
            grb_onto = str(inp["onto"])
            grb_error = validate_git_rebase_inputs(grb_onto)
            if grb_error:
                return grb_error
            if bool(inp.get("interactive", False)):
                return "[BLOCKED] Interactive rebase requires a TTY. Run 'git rebase -i' manually in a terminal."
            return await asyncio.to_thread(_git, ["rebase", grb_onto], repo, 60)

        if tool_name == "git_cherry_pick":
            gcp_hash = str(inp["commit_hash"])
            gcp_error = validate_git_cherry_pick_inputs(gcp_hash)
            if gcp_error:
                return gcp_error
            gcp_args = ["cherry-pick"]
            if bool(inp.get("no_commit", False)):
                gcp_args.append("--no-commit")
            gcp_args.append(gcp_hash)
            return await asyncio.to_thread(_git, gcp_args, repo, 30)

        # ========== BATCH 12 — Terminal extras ==========

        if tool_name == "read_output":
            from app.fleet import process_manager as _pm

            ro_pid = int(inp["pid"])
            ro_max_lines = int(inp.get("lines", 50))
            return _pm.read_output(
                ro_pid,
                ro_max_lines,
                self._background_processes,
                _read_stream_nonblocking,
            )

        if tool_name == "run_node":
            # tool_enhance.md productionization pass, tool #60 (2026-08-22)
            # — `code` was already safely shlex.quote()'d here (proved live:
            # a real shell-metacharacter-and-quote-breakout payload was NOT
            # shell-interpreted). Real finding: `timeout` had no upper
            # bound on either real call site — proved live, a real
            # timeout=999999999 reached subprocess.run's own timeout
            # unmodified. Fixed at the shared run_node_handler(); see that
            # function's own module docstring.
            return await asyncio.to_thread(run_node_handler, repo, inp)

        if tool_name == "run_script":
            rscr_rel = str(inp["path"])
            rscr_fp = root / rscr_rel
            if not rscr_fp.exists():
                return f"[ERROR] Script not found: {rscr_rel}"
            rscr_interp = str(inp.get("interpreter", "auto"))
            if rscr_interp == "auto":
                rscr_interp = (
                    "python3"
                    if rscr_fp.suffix == ".py"
                    else "node" if rscr_fp.suffix in (".js", ".mjs", ".cjs") else "bash"
                )
            rscr_cmd = f"{rscr_interp} {str(rscr_fp)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, rscr_cmd, repo, 120)

        if tool_name == "docker_build":
            dbld_tag = str(inp["tag"])
            dbld_context = str(inp.get("context", "."))
            dbld_df = inp.get("dockerfile")
            dbld_error = validate_docker_build_inputs(
                dbld_context, str(dbld_df) if dbld_df else None, repo
            )
            if dbld_error:
                return f"[POLICY DENIED] {dbld_error}"
            dbld_ctx_path = str(root / dbld_context) if dbld_context != "." else repo
            dbld_cmd_parts = ["docker", "build", "-t", dbld_tag]
            if dbld_df:
                dbld_cmd_parts += ["-f", str(root / str(dbld_df))]
            dbld_cmd_parts.append(dbld_ctx_path)
            import shlex as _shlex3

            dbld_cmd_str = " ".join(_shlex3.quote(c) for c in dbld_cmd_parts) + " 2>&1"
            return await asyncio.to_thread(_run_subprocess, dbld_cmd_str, repo, 600)

        if tool_name == "docker_restart":
            drst_name = str(inp["container"])
            drst_cmd = build_docker_restart_command(drst_name)
            return await asyncio.to_thread(_run_subprocess, drst_cmd, repo, 60)

        if tool_name == "git_tag":
            # tool_enhance.md productionization pass, tool #22 (2026-08-17)
            # — real gap found: advertised via CHAT_TOOLS but never
            # dispatched here at all, same class as npm_install/pip_install
            # (tool #4) — every real call fell through to "Unknown tool".
            return await asyncio.to_thread(git_tag_handler, repo, inp)

        if tool_name == "semver_bump":
            # tool_enhance.md productionization pass, tool #25 (2026-08-18)
            # — same "advertised but never dispatched" gap as git_tag
            # (tool #22), plus a real worktree-boundary-escape write bug
            # in the only existing implementation — both closed in the
            # shared handler.
            return await asyncio.to_thread(semver_bump_handler, root, repo, inp)

        if tool_name == "delete_block":
            # tool_enhance.md productionization pass, tool #33 (2026-08-18)
            # — same "advertised but never dispatched" gap as git_tag/
            # semver_bump/create_branch (tools #22/#25/#32).
            return await asyncio.to_thread(delete_block_handler, root, repo, inp)

        if tool_name in (
            "browser_open",
            "browser_navigate",
            "browser_screenshot",
            "browser_read_dom",
            "browser_click",
            "browser_type",
            "browser_close",
        ):
            # tool_enhance.md productionization pass, tools #28-#31 +
            # #123-#125 (2026-08-18) — same "advertised but never
            # dispatched" gap as git_tag/semver_bump (tools #22/#25): all
            # 7 browser_* tools are in CHAT_TOOLS but chat_agent.py never
            # had a dispatch branch for any of them.
            bsid = self.session.session_id or "__default__"
            _browser_handler = {
                "browser_open": browser_open_handler,
                "browser_navigate": browser_navigate_handler,
                "browser_screenshot": browser_screenshot_handler,
                "browser_read_dom": browser_read_dom_handler,
                "browser_click": browser_click_handler,
                "browser_type": browser_type_handler,
                "browser_close": browser_close_handler,
            }[tool_name]
            return await asyncio.to_thread(_browser_handler, inp, session_id=bsid)

        # ========== BATCH 13 — Smart search ==========

        if tool_name == "find_route":
            frt_method = str(inp.get("method", "")).upper()
            frt_path_pat = str(inp.get("path_pattern", ""))
            frt_pat = (
                rf"@(router|app)\.{frt_method.lower()}\("
                if frt_method
                else r"@(router|app)\.(get|post|put|delete|patch|head|options)\("
            )
            frt_cmd = (
                f"grep -rn -E {__import__('shlex').quote(frt_pat)} {repo} "
                "--include=*.py --include=*.ts "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            frt_result = await asyncio.to_thread(_run_subprocess, frt_cmd, repo, 15)
            if frt_path_pat:
                frt_result = "\n".join(
                    ln for ln in frt_result.splitlines() if frt_path_pat in ln
                )
            return (
                frt_result[:5000]
                if frt_result.strip()
                else ("No routes found" + (f" for {frt_method}" if frt_method else ""))
            )

        if tool_name == "find_api":
            fapi_name = str(inp.get("name", ""))
            fapi_pat = (
                fapi_name
                if fapi_name
                else r"@(router|app)\.(get|post|put|delete|patch)\("
            )
            fapi_cmd = (
                f"grep -rn -E {__import__('shlex').quote(fapi_pat)} {repo} "
                "--include=*.py --include=*.ts "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            fapi_result = await asyncio.to_thread(_run_subprocess, fapi_cmd, repo, 15)
            return (
                fapi_result[:5000]
                if fapi_result.strip()
                else (
                    "No API definitions found"
                    + (f" matching '{fapi_name}'" if fapi_name else "")
                )
            )

        if tool_name == "find_sql":
            import shlex as _shlex4

            fsql_kw = str(inp.get("keyword", "")).upper()
            if fsql_kw:
                # -i case-insensitive, -w whole-word; avoid (?i) inline flag
                fsql_cmd = (
                    f"grep -rn -i -w {_shlex4.quote(fsql_kw)} {repo} "
                    "--include=*.py --include=*.sql --include=*.ts "
                    "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
                )
            else:
                fsql_cmd = (
                    f"grep -rn -i -E 'SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE' {repo} "
                    "--include=*.py --include=*.sql --include=*.ts "
                    "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
                )
            fsql_result = await asyncio.to_thread(_run_subprocess, fsql_cmd, repo, 15)
            return (
                fsql_result[:5000] if fsql_result.strip() else "No SQL statements found"
            )

        if tool_name == "find_test":
            ftest_fn = str(inp["function_name"])
            ftest_pat = rf"def test_{ftest_fn}|def test.*{ftest_fn}"
            ftest_cmd = (
                f"grep -rn -E {__import__('shlex').quote(ftest_pat)} {repo} "
                "--include=*.py --include=*.test.ts --include=*.spec.ts "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            ftest_result = await asyncio.to_thread(_run_subprocess, ftest_cmd, repo, 15)
            return (
                ftest_result[:5000]
                if ftest_result.strip()
                else f"No tests found for '{ftest_fn}'"
            )

        if tool_name == "find_config":
            fcfg_key = str(inp["key"])
            fcfg_pat = fcfg_key.upper()
            fcfg_cmd = (
                f"grep -rn {__import__('shlex').quote(fcfg_pat)} {repo} "
                "--include=*.env* --include=.env* --include=*.yaml --include=*.yml "
                "--include=*.toml --include=config.py --include=settings.py "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            fcfg_result = await asyncio.to_thread(_run_subprocess, fcfg_cmd, repo, 15)
            if not fcfg_result.strip():
                # Try lowercase too
                fcfg_cmd2 = (
                    f"grep -rn {__import__('shlex').quote(fcfg_key.lower())} {repo} "
                    "--include=*.yaml --include=*.yml --include=*.toml "
                    "--exclude-dir=node_modules --exclude-dir=.venv 2>/dev/null || true"
                )
                fcfg_result = await asyncio.to_thread(
                    _run_subprocess, fcfg_cmd2, repo, 15
                )
            return (
                fcfg_result[:5000]
                if fcfg_result.strip()
                else f"'{fcfg_key}' not found in config files"
            )

        # ========== BATCH 14 — Monitoring ==========

        if tool_name == "cpu_usage":
            cpu_cmd = "cat /proc/stat 2>/dev/null | head -1 || top -bn1 2>/dev/null | grep -i cpu | head -3"
            cpu_raw = await asyncio.to_thread(_run_subprocess, cpu_cmd, repo, 5)
            # Parse /proc/stat if available
            if cpu_raw.startswith("cpu "):
                cpu_fields = cpu_raw.split()
                if len(cpu_fields) >= 5:
                    cpu_total = sum(int(f) for f in cpu_fields[1:] if f.isdigit())
                    cpu_idle = int(cpu_fields[4])
                    cpu_pct = (
                        round((cpu_total - cpu_idle) / cpu_total * 100, 1)
                        if cpu_total
                        else 0
                    )
                    return f"CPU: {cpu_pct}% used"
            return f"CPU: {cpu_raw[:300]}"

        if tool_name == "memory_usage":
            memus_cmd = "cat /proc/meminfo 2>/dev/null | head -8 || free -h 2>/dev/null"
            return await asyncio.to_thread(_run_subprocess, memus_cmd, repo, 5)

        if tool_name == "disk_usage":
            import shutil as _shu2

            disk_path = str(inp.get("path", "")) or repo
            try:
                dsk_u = _shu2.disk_usage(disk_path)
                dsk_gb = 1024**3
                dsk_pct = round(dsk_u.used / dsk_u.total * 100, 1) if dsk_u.total else 0
                return (
                    f"Disk usage for {disk_path}:\n"
                    f"  Total: {dsk_u.total / dsk_gb:.1f} GB\n"
                    f"  Used:  {dsk_u.used / dsk_gb:.1f} GB  ({dsk_pct}%)\n"
                    f"  Free:  {dsk_u.free / dsk_gb:.1f} GB"
                )
            except Exception as dsk_e:
                return f"[ERROR] {dsk_e}"

        if tool_name == "health_check":
            from app.config import get_settings as _gs2

            hc_svc = str(inp.get("service", "all"))
            hc_settings = _gs2()
            hc_port = getattr(hc_settings, "port", 8000)
            hc_res: list[str] = []
            if hc_svc in ("all", "backend"):
                hc_curl = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{hc_port}/health 2>/dev/null || echo 000"
                hc_code = (
                    await asyncio.to_thread(_run_subprocess, hc_curl, repo, 5)
                ).strip()
                hc_res.append(
                    f"Backend (:{hc_port}/health): {'✅ UP' if hc_code == '200' else f'⚠️ HTTP {hc_code}'}"
                )
            if hc_svc in ("all", "db"):
                hc_db_url = getattr(hc_settings, "database_url", "")
                if hc_db_url:
                    hc_pg = await asyncio.to_thread(
                        _run_subprocess, f"pg_isready -d '{hc_db_url}' 2>&1", repo, 5
                    )
                    hc_res.append(
                        f"Database: {'✅ UP' if 'accepting' in hc_pg else f'❌ {hc_pg[:80]}'}"
                    )
                else:
                    hc_res.append("Database: (DATABASE_URL not configured)")
            return "\n".join(hc_res) if hc_res else "No services checked"

        if tool_name == "task_progress":
            from app.config import get_settings as _gs3

            tprog_tid = inp.get("task_id")
            tprog_lim = int(inp.get("limit", 10))
            tp_db_url = getattr(_gs3(), "database_url", "")
            if not tp_db_url:
                return "[ERROR] DATABASE_URL not set"
            if tprog_tid is not None:
                tprog_sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks WHERE id = {int(tprog_tid)} LIMIT 1;"
            else:
                tprog_sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks ORDER BY created_at DESC LIMIT {tprog_lim};"
            tprog_cmd = f"psql '{tp_db_url}' -c {__import__('shlex').quote(tprog_sql)} --no-psqlrc 2>&1"
            return await asyncio.to_thread(_run_subprocess, tprog_cmd, repo, 10)

        # ========== BATCH 15 — Editing extras ==========

        if tool_name == "replace_class":
            return replace_class_handler(root, repo, inp)

        if tool_name == "undo_changes":
            undo_rel = str(inp["path"])
            if _is_protected_path(undo_rel, repo):
                return f"[POLICY DENIED] Protected path: {undo_rel}"
            undo_fp = root / undo_rel
            if not undo_fp.exists():
                return f"[ERROR] File not found: {undo_rel}"
            confirmed_undo = await self._confirm(
                description=f"git checkout -- {undo_rel}",
                details="DISCARDS all uncommitted changes to this file — irreversible",
            )
            if not confirmed_undo:
                return f"[CANCELLED] undo_changes for {undo_rel} cancelled by user"
            return await asyncio.to_thread(_git, ["checkout", "--", undo_rel], repo, 15)

        if tool_name == "generate_patch":
            import difflib as _dl

            gpatch_a = str(inp.get("content_a", ""))
            gpatch_b = str(inp.get("content_b", ""))
            gpatch_fn = str(inp.get("filename", "file"))
            gpatch_diff = list(
                _dl.unified_diff(
                    gpatch_a.splitlines(keepends=True),
                    gpatch_b.splitlines(keepends=True),
                    fromfile=f"a/{gpatch_fn}",
                    tofile=f"b/{gpatch_fn}",
                )
            )
            return "".join(gpatch_diff) if gpatch_diff else "(no differences)"

        # ========== BATCH 16 — DB extras ==========

        if tool_name == "explain_query":
            expq_sql = str(inp["query"]).strip().rstrip(";")
            from app.config import get_settings as _gs4

            expq_db = getattr(_gs4(), "database_url", "")
            if not expq_db:
                return "[ERROR] DATABASE_URL not set"
            expq_full = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {expq_sql};"
            expq_cmd = f"psql '{expq_db}' -c {__import__('shlex').quote(expq_full)} --no-psqlrc 2>&1"
            return await asyncio.to_thread(_run_subprocess, expq_cmd, repo, 30)

        if tool_name == "run_migration":
            rmig_dir = str(inp.get("direction", "upgrade"))
            rmig_rev = str(
                inp.get("revision", "head" if rmig_dir == "upgrade" else "-1")
            )
            # tool_enhance.md productionization pass, tool #8 (2026-08-16)
            # — real, empirically-verified shell-injection vulnerability
            # found while auditing this tool: direction/revision are
            # LLM-controlled strings interpolated directly into a raw
            # shell=True command below, with no validation at all. Proved
            # directly (not assumed) before writing this fix: passing
            # revision="head; touch /tmp/PWNED..." actually executed the
            # injected command — a real arbitrary-command-execution bug
            # that bypassed the confirmation dialog's entire purpose,
            # since a human reviewing "alembic upgrade <revision>" has no
            # reasonable way to notice an injection payload hidden inside
            # what looks like a revision identifier.
            # validate_run_migration_inputs (shared with the second,
            # currently unreachable make_chat_handlers() implementation of
            # this same tool) closes this before ever reaching the shell.
            rmig_validation_error = validate_run_migration_inputs(rmig_dir, rmig_rev)
            if rmig_validation_error:
                return rmig_validation_error
            rmig_confirmed = await self._confirm(
                description=f"alembic {rmig_dir} {rmig_rev}",
                details="Modifies the database schema — review migration file before confirming",
            )
            if not rmig_confirmed:
                return "[CANCELLED] run_migration cancelled by user"
            rmig_backend = (
                str(root / "backend") if (root / "backend").exists() else repo
            )
            activate = f"source {rmig_backend}/.venv/bin/activate 2>/dev/null || true"
            rmig_cmd = (
                f"{activate} && cd {rmig_backend} && alembic {rmig_dir} {rmig_rev} 2>&1"
            )
            return await asyncio.to_thread(_run_subprocess, rmig_cmd, rmig_backend, 120)

        # ========== AUDIT_Q_BATCH07 §13 — Human interaction ==========

        if tool_name == "ask_human_to_choose":
            ahtc_question = str(inp["question"]).strip()
            ahtc_options = inp.get("options")
            if not ahtc_question:
                return "[ERROR] question is required."
            if not isinstance(ahtc_options, list) or len(ahtc_options) < 2:
                return "[ERROR] options must be a list of at least 2 choices."
            ahtc_clean: list[dict[str, str]] = []
            for opt in ahtc_options:
                if not isinstance(opt, dict) or "id" not in opt or "label" not in opt:
                    return "[ERROR] each option needs at least 'id' and 'label'."
                ahtc_clean.append(
                    {
                        "id": str(opt["id"]),
                        "label": str(opt["label"]),
                        "description": str(opt.get("description", "")),
                    }
                )
            ahtc_recommended = inp.get("recommended_option")
            selected = await self._confirm_with_options(
                description=ahtc_question,
                options=ahtc_clean,
                recommended=str(ahtc_recommended) if ahtc_recommended else None,
            )
            if selected is None:
                return "[CANCELLED] Human did not select an option."
            chosen = next(o for o in ahtc_clean if o["id"] == selected)
            return f"Human selected: {chosen['id']} ({chosen['label']})"

        if tool_name == "seed_database":
            seeddb_script = str(inp.get("script", ""))
            if not seeddb_script:
                seeddb_script = "backend/scripts/seed.py"
            # tool_enhance.md productionization pass, tool #10 (2026-08-16)
            # — real, empirically-verified vulnerabilities found (first
            # diagnosed while auditing run_migration, tool #8, closed
            # here): (1) shell injection — `script` was interpolated
            # directly into a raw shell=True command below with zero
            # validation, proved directly with a crafted filename that
            # actually executed an injected command; (2) a path-boundary
            # escape — `root / script` silently ignores `root` entirely
            # when `script` is an absolute path (Python's own
            # Path.__truediv__ behavior), proved directly with
            # script="/etc/hostname" resolving outside the repo, despite
            # this tool's own schema documenting `script` as "relative to
            # repo root." validate_seed_database_script (shared with the
            # second, currently unreachable make_chat_handlers()
            # implementation of this same tool) closes both before the
            # path is ever touched.
            seeddb_validation_error = validate_seed_database_script(
                seeddb_script, repo
            )
            if seeddb_validation_error:
                return seeddb_validation_error
            seeddb_fp = root / seeddb_script
            if not seeddb_fp.exists():
                return f"[ERROR] Seed script not found: {seeddb_script}"
            seeddb_confirmed = await self._confirm(
                description=f"Run seed script: {seeddb_script}",
                details="Modifies database data — will insert/update rows",
            )
            if not seeddb_confirmed:
                return "[CANCELLED] seed_database cancelled by user"
            # AUDIT_Q_BATCH01 §1 "Windows terminal support" — was hardcoded
            # POSIX `source`, silently never activating the venv on Windows
            # (relative path is safe here: _run_subprocess always passes
            # cwd=repo, so the shell's starting directory is already repo,
            # matching this line's previous absolute-path behavior exactly
            # on POSIX while adding a real Windows branch).
            activate = _venv_activate_snippet()
            seeddb_cmd = f"{activate} && python3 {str(seeddb_fp)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, seeddb_cmd, repo, 120)

        return f"[ERROR] Unknown tool: {tool_name}"

    # ------------------------------------------------------------------
    # Main agentic loop — MASTER_AGENT_v2.md Phase 5.2, a real LangGraph
    # StateGraph. Every tool call is its own node (see module docstring for
    # why that granularity is what makes interrupt()-based confirmation
    # safe here); call_llm/execute_tool loop via conditional edges instead
    # of Python for-loops.
    # ------------------------------------------------------------------

    async def _call_llm_node(self, state: ChatGraphState) -> dict[str, Any]:
        iteration = state.get("iteration", 0)
        if iteration >= self.MAX_ITERATIONS:
            return {"stop": True}

        await self.session.push({"type": "thinking", "iteration": iteration})

        client = self._client()
        settings = get_settings()
        system_prompt = state.get("system_prompt", self._system)

        full_text = ""
        tool_uses: list[dict[str, Any]] = []
        stop_reason = "end_turn"

        # Gap-closure Stage 1.5 (answers.md) — this file had ZERO
        # token-budget tracking before this (confirmed by grep). Mirrors
        # base_graph.py::call_llm's own condense/approaching_limit check
        # exactly: always attempt condense and check was_condensed FIRST
        # (never a separate pct>=1.0 pre-check — that duplicated boundary
        # doesn't exactly match _select_messages_to_condense's own `tokens_in
        # <= token_budget` cutoff at the exact tokens_in==token_budget edge,
        # caught by this day's own test suite before shipping), falling
        # through to the approaching_limit check only when nothing was
        # condensed. Condensing mutates self.session.history in place so it
        # persists for every later turn, not just this one call.
        context_token_budget = settings.context_token_budget
        # Blocker (audit_v1.md 4.4 #3): this gate used to be
        # `self._tokens_in > 0` — always false on the very first call of a
        # freshly-constructed ChatAgent (self._tokens_in inits to 0 and
        # only becomes real after a real LLM response's usage.input_tokens
        # comes back), which is exactly the state a restored session is in
        # on its first resumed turn. That meant the entire unbounded-until-
        # bounded-by-load_history_from_db's-own-fix history skipped condense
        # entirely on precisely the turn budget protection matters most.
        # When self._tokens_in is still 0, fall back to a cheap character-
        # based estimate of the actual restored history so the condense
        # decision is based on real content size, not a counter that hasn't
        # observed a real API response yet.
        effective_tokens_in = (
            self._tokens_in
            if self._tokens_in > 0
            else _estimate_tokens(self.session.history)
        )
        if effective_tokens_in > 0 and context_token_budget > 0:
            messages_before = len(self.session.history)
            condensed, was_condensed = await _condense_history_async(
                list(self.session.history),
                token_budget=context_token_budget,
                tokens_in=effective_tokens_in,
                client=client,
                model_haiku=self._haiku_model(),
            )
            if was_condensed:
                self.session.history[:] = condensed
                await self.session.push(
                    {
                        "type": "context_trimmed",
                        "messages_before": messages_before,
                        "messages_after": len(self.session.history),
                    }
                )
            else:
                pct = effective_tokens_in / context_token_budget
                if 0.8 <= pct < 1.0:
                    await self.session.push(
                        {
                            "type": "approaching_limit",
                            "tokens_in": effective_tokens_in,
                            "token_budget": context_token_budget,
                            "pct": round(pct, 3),
                        }
                    )

        # AUDIT_Q_BATCH13 §65 gap-closure (2026-08-11) — same real-context-
        # window safety net as base_graph.py::call_llm, applied here too
        # (§52 already confirmed condensation itself is genuinely shared
        # between both paths; this check was missing from both). Chat calls
        # settings.model_coder directly rather than routing by agent name,
        # but that is exactly the model registered under "coder" in
        # agent_models.json, so context_window_for("coder") is the real
        # ceiling for this call, not a guess.
        _real_context_window = 200_000
        try:
            from app.fleet.model_router import get_model_router as _get_router

            _real_context_window = _get_router().context_window_for("coder")
        except Exception:
            pass
        if effective_tokens_in >= _real_context_window:
            msg = (
                f"Conversation too long: {effective_tokens_in} tokens >= real "
                f"model context window {_real_context_window} "
                f"(context_token_budget={context_token_budget})"
            )
            logger.warning(msg)
            await self.session.push({"type": "error", "message": msg})
            return {"stop": True, "last_error": msg}

        # Cast our dict-based messages/tools to what the SDK expects
        sdk_messages = cast(list[MessageParam], self.session.history)
        sdk_tools = cast(list[ToolParam], CHAT_TOOLS)

        # Gap-closure Day 22 (Stage 1.3, answers.md) — circuit breaker around
        # the Anthropic streaming call. Uses allow()/record_success()/
        # record_failure() directly (not the simpler call() wrapper) since
        # this whole block is `async with ... stream: async for ...` — not
        # a single callable a sync breaker.call() could wrap.
        from app.fleet.circuit_breaker import get_anthropic_breaker

        breaker = get_anthropic_breaker()
        if not breaker.allow():
            msg = breaker.open_error_message()
            await self.session.push({"type": "error", "message": msg})
            return {"stop": True, "last_error": msg}

        try:
            async with client.messages.stream(
                model=settings.model_coder,
                max_tokens=8192,
                system=system_prompt,
                messages=sdk_messages,
                tools=sdk_tools,
            ) as stream:
                async for event in stream:
                    if isinstance(event, RawContentBlockDeltaEvent):
                        delta = event.delta
                        if isinstance(delta, TextDelta):
                            full_text += delta.text
                            await self.session.push(
                                {"type": "text_delta", "text": delta.text}
                            )

                final = await stream.get_final_message()
                stop_reason = final.stop_reason or "end_turn"
                # Gap-closure Stage 1.5 — real cumulative usage tracking,
                # feeding the condense check above on the NEXT turn.
                self._tokens_in += final.usage.input_tokens
                self._tokens_out += final.usage.output_tokens
                for block in final.content:
                    if block.type == "tool_use":
                        tool_uses.append(
                            {
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )

        except anthropic.APIStatusError as e:
            breaker.record_failure()
            await self.session.push(
                {"type": "error", "message": f"API error: {e.message}"}
            )
            return {"stop": True, "last_error": f"API error: {e.message}"}
        except Exception as e:
            breaker.record_failure()
            await self.session.push({"type": "error", "message": str(e)})
            logger.exception("Chat agent error on iteration %d", iteration)
            return {"stop": True, "last_error": str(e)}
        else:
            breaker.record_success()

        # AUDIT_Q_BATCH11 §21 "Data leakage prevention" — a secret the agent
        # encountered via read_file/bash/etc and then quoted back in its own
        # reply used to sail straight through unredacted: _mask_secret_value
        # and _scan_content_for_secrets each covered exactly one narrow call
        # site, neither the model's own generated text. This chat graph
        # streams full_text live to the user token-by-token via text_delta
        # events *before* this point runs, so the raw bytes the user
        # already saw can't be un-sent — redacting here still closes the
        # more consequential half of the gap: it stops the secret from
        # being replayed into session.history (future LLM turns, DB
        # persistence, memory embeddings), and a security_warning event
        # gives the frontend/user an explicit, visible signal that the
        # reply they just read likely contained a live credential.
        if full_text:
            full_text, _secret_found = _redact_secrets_in_text(full_text)
            if _secret_found:
                await self.session.push(
                    {
                        "type": "security_warning",
                        "message": (
                            "This response appeared to contain a secret/credential "
                            "and has been redacted before being saved to this "
                            "session's history."
                        ),
                    }
                )
                logger.warning(
                    "Redacted apparent secret(s) from chat agent's own "
                    "generated reply (session_id=%s)",
                    self.session.session_id,
                )

        # Append assistant turn to history
        turn_content: list[dict[str, Any]] = []
        update: dict[str, Any] = {}
        if full_text:
            update["final_text"] = full_text
            turn_content.append({"type": "text", "text": full_text})
        for tu in tool_uses:
            turn_content.append(
                {
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                }
            )
        if turn_content:
            self.session.history.append({"role": "assistant", "content": turn_content})

        if stop_reason != "tool_use" or not tool_uses:
            update["stop"] = True
            return update

        update["stop"] = False
        update["pending_tool_uses"] = tool_uses
        update["tool_results"] = []
        update["iteration"] = iteration + 1
        return update

    async def _execute_tool_node(self, state: ChatGraphState) -> dict[str, Any]:
        pending = list(state.get("pending_tool_uses", []))
        tu = pending.pop(0)
        # Read by _confirm() as a replay-stable action_id — see this
        # module's docstring for why it must be the Anthropic tool_use_id,
        # not a freshly generated uuid4().
        self._current_tool_use_id = tu["id"]
        self._current_tool_name = str(tu["name"])

        await self.session.push(
            {
                "type": "tool_call",
                "tool_name": tu["name"],
                "tool_input": tu["input"],
                "tool_use_id": tu["id"],
            }
        )

        # Gap-closure Day 16 (Stage 1.2, answers.md) — real enforcement of
        # _VERIFICATION_CFG, previously dead config (see module-level
        # comments on ChatGraphState.verification / _VERIFICATION_CFG for
        # the full "why"). Accumulates across the whole session, not reset
        # per turn.
        verification: dict[str, Any] = dict(
            state.get("verification") or _VERIFICATION_CFG.initial
        )
        blocking_key = _VERIFICATION_CFG.blocking_until.get(tu["name"])

        # AUDIT_Q_BATCH11 §85 "All agents automatically follow policy
        # (structural guarantee)" — this graph's own tool dispatch never
        # had a central pre-execution policy gate at all (unlike
        # base_graph.py's execute_tools(), which already calls
        # _policy_check before every one of the ~72-agent fleet's tool
        # calls): every one of this file's ~150 `if tool_name ==` branches
        # relied entirely on its own inline _is_protected_path/
        # _is_dangerous_command call — real everywhere sampled, but with no
        # structural guarantee a future branch couldn't skip it. Reusing
        # base_graph.py's manifest-driven _policy_check here (not a second,
        # independently-maintained copy) gives this graph the same
        # structural chokepoint, checked first so a policy denial always
        # wins over a verification-gate denial.
        policy_denial = _policy_check(tu["name"], tu["input"])
        if policy_denial:
            result = f"[POLICY DENIED] {policy_denial}"
            logger.warning("Policy denied %s: %s", tu["name"], policy_denial)
            try:
                from app.fleet.audit_log import audit as _audit

                _audit(
                    action_type="policy_denial",
                    agent_name="chat_agent",
                    description=f"{tu['name']} denied: {policy_denial}",
                    task_id=self.session.session_id or None,
                    outcome="denied",
                    details={"tool_name": tu["name"], "tool_input": tu["input"]},
                )
            except Exception:
                pass
        elif blocking_key is not None and not verification.get(blocking_key, False):
            result = (
                f"[POLICY DENIED] {tu['name']} is refused until "
                f"'{blocking_key}' is satisfied first — "
                f"{AGENT_CONTRACT['expected_verification'].get(blocking_key, '')}"
            )
        else:
            _tool_t0 = time.monotonic()
            try:
                result = await self._execute_tool(tu["name"], tu["input"])
            except GraphBubbleUp:
                # Real bug caught by testing: interrupt() (called deep inside
                # _execute_tool, from _confirm()) signals a pause by raising
                # GraphInterrupt, a genuine subclass of Exception — a blanket
                # `except Exception` here would silently swallow it, turning
                # every confirmation pause into a fake "[ERROR] Tool ... failed"
                # result and permanently breaking the graph's ability to pause
                # at all. Must propagate uncaught for LangGraph's own execution
                # engine to catch and handle.
                raise
            except Exception as e:
                result = f"[ERROR] Tool {tu['name']} failed: {e}"
                logger.exception("Tool %s failed", tu["name"])

            _tool_duration_ms = (time.monotonic() - _tool_t0) * 1000
            _tool_ok = not result.startswith("[ERROR]") and not result.startswith(
                "[POLICY"
            )
            if self._current_trace_id:
                try:
                    from app.fleet.metrics import get_metrics_collector

                    _m = get_metrics_collector().get(self._current_trace_id)
                    if _m is not None:
                        _tool_err = None if _tool_ok else result[:200]
                        _m.record_tool(
                            tu["name"], _tool_ok, _tool_duration_ms, _tool_err
                        )
                except Exception:
                    pass

            if not result.startswith("[ERROR]") and not result.startswith("[POLICY"):
                # AUDIT_Q_BATCH18 §54/55/56 gap-closure — this file's own
                # existing _redact_secrets_in_text call (further down, on
                # full_text) only scans the MODEL's synthesized reply, never
                # the raw tool result feeding into it. A secret surfaced via
                # this chat's read_file/bash/git_show/etc tools and never
                # re-quoted verbatim by the model (only paraphrased, or left
                # sitting in `result[:3000]`'s pushed SSE event/history
                # below) sailed through unredacted. Same chokepoint base_
                # graph.py's execute_tools node was just given the identical
                # fix at, applied before flag/wrap so the redaction marker
                # lands inside the untrusted-data delimiter, not outside it.
                result, _secret_found = _redact_secrets_in_text(result)
                if _secret_found:
                    logger.warning(
                        "Redacted apparent secret(s) from %s's raw tool "
                        "result (session=%s)",
                        tu["name"],
                        self.session.session_id,
                    )
                # AUDIT_Q_BATCH11 §21 — base_graph.py's execute_tools node
                # already flags+wraps tool output at its own chokepoint, but
                # this chat graph runs its own separate _execute_tool_node
                # (Phase 5.2) that never routed through either mitigation,
                # so every one of the 36 chat tools returned raw, unwrapped
                # content regardless of the base-graph fix's coverage. Same
                # order as base_graph.py: flag first (inspects the real
                # handler output), then wrap, so the delimiter encloses the
                # warning too.
                result = _flag_suspicious_tool_output(tu["name"], result)
                result = _wrap_untrusted_tool_content(tu["name"], result)

                set_key = _VERIFICATION_CFG.set_by.get(tu["name"])
                if set_key is not None:
                    verification[set_key] = True
                if tu["name"] in _VERIFICATION_CFG.reset_by:
                    for reset_key in _VERIFICATION_CFG.reset_keys:
                        verification[reset_key] = False

        await self.session.push(
            {
                "type": "tool_result",
                "tool_name": tu["name"],
                "tool_use_id": tu["id"],
                "output": result[:3000],
            }
        )

        tool_results = list(state.get("tool_results", [])) + [
            {"type": "tool_result", "tool_use_id": tu["id"], "content": result}
        ]

        if pending:
            return {
                "pending_tool_uses": pending,
                "tool_results": tool_results,
                "verification": verification,
            }

        # Last tool in this LLM turn's batch — flush to history, matching
        # the original loop's post-for-loop history.append() exactly.
        self.session.history.append({"role": "user", "content": tool_results})
        return {
            "pending_tool_uses": [],
            "tool_results": [],
            "verification": verification,
        }

    async def _finalize_node(self, state: ChatGraphState) -> dict[str, Any]:
        await self._memory_write_outcome(
            state.get("user_message", ""),
            state.get("final_text", ""),
            state.get("last_error"),
        )
        await self.session.push({"type": "done"})
        return {}

    def _route_after_llm(self, state: ChatGraphState) -> str:
        return "finalize" if state.get("stop") else "execute_tool"

    def _route_after_tool(self, state: ChatGraphState) -> str:
        return "execute_tool" if state.get("pending_tool_uses") else "call_llm"

    def _build_chat_graph(self) -> Any:
        graph: StateGraph[ChatGraphState] = StateGraph(ChatGraphState)

        graph.add_node("call_llm", self._call_llm_node)
        graph.add_node("execute_tool", self._execute_tool_node)
        graph.add_node("finalize", self._finalize_node)

        graph.add_edge(START, "call_llm")
        graph.add_conditional_edges(
            "call_llm",
            self._route_after_llm,
            {"execute_tool": "execute_tool", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "execute_tool",
            self._route_after_tool,
            {"execute_tool": "execute_tool", "call_llm": "call_llm"},
        )
        graph.add_edge("finalize", END)

        # Reads the current module-level singleton at compile time (not a
        # value captured once at import time) — same property
        # base_graph.py::build_agent_graph() relies on for
        # _agent_checkpointer, and what makes init_chat_checkpointer()
        # (called from FastAPI lifespan startup, strictly before any
        # ChatAgent can be constructed from a real request) actually take
        # effect for every session created afterward.
        return graph.compile(checkpointer=_chat_checkpointer)

    async def run(self, user_message: str) -> None:
        """
        Process user_message through the full agentic loop.
        Events are pushed to session.push() for SSE delivery.

        If a confirmation is required, this returns early (the graph
        paused via a real interrupt()) WITHOUT pushing a 'done' event —
        _finalize_node is only reached when the graph actually completes.
        resume() continues a paused turn later.
        """
        # Stage 4 Tier 3 (2026-08-05, answer2.md Q7: "Detect User
        # Satisfaction: NO — no sentiment/satisfaction-detection code found
        # anywhere in the agent graph") — real, bounded, code-level signal,
        # separate from roles/chat.md's own prompt-level frustration
        # guidance. Computed before the new message is appended to history,
        # so "recent prior messages" genuinely excludes the current one.
        # AUDIT_Q_BATCH12 §26/§63 gap-closure (2026-08-11) — this signal used
        # to be telemetry-only: computed, pushed as an SSE user_sentiment
        # event for the frontend, and never read again. It never reached the
        # system prompt, so the LLM call that immediately follows had no way
        # to know frustration/repetition had been detected unless it happened
        # to notice from the raw conversation itself (roles/chat.md's own
        # prompt-level guidance). frustration_directive closes that loop —
        # a short, honest instruction folded into THIS turn's system prompt,
        # not a new detector.
        frustration_directive = ""
        try:
            from app.agents.user_sentiment import detect_user_frustration

            prior_user_messages = [
                str(m.get("content", ""))
                for m in self.session.history
                if m.get("role") == "user"
            ]
            signal = detect_user_frustration(user_message, prior_user_messages)
            if signal.frustrated:
                await self.session.push(
                    {
                        "type": "user_sentiment",
                        "frustrated": True,
                        "signals": signal.signals,
                    }
                )
                repeated = any(
                    s.startswith("repeated_message:") for s in signal.signals
                )
                frustration_directive = (
                    "\n\n[Signal: the user's latest message shows signs of "
                    "frustration"
                    + (
                        ", including repeating a point they already made"
                        if repeated
                        else ""
                    )
                    + ". Prioritize a concrete, direct next step over lengthy "
                    "re-explanation, acknowledge the frustration briefly "
                    "rather than ignoring it, and avoid repeating an approach "
                    "that hasn't worked so far.]"
                )
        except Exception:
            logger.debug(
                "user frustration detection skipped (non-fatal)", exc_info=True
            )

        # AUDIT_Q_BATCH17 §73 gap-closure (2026-08-11) — "Adaptive Expertise:
        # NO — nothing detects which [domain] a conversational user
        # implicitly needs, or adapts tone/terminology to a detected role."
        # Same additive-directive shape as frustration_directive above: a
        # real, code-computed signal folded into THIS turn's system prompt,
        # never a new graph routing edge — _route_after_llm/_route_after_tool
        # (the actual tool_use/stop decision) are untouched. Classified once
        # per session and cached on self.session (a professional role rarely
        # changes mid-conversation), not on every turn.
        if not self.session.role_detected:
            try:
                from app.agents.role_detection import detect_professional_role

                role_signal = detect_professional_role(
                    user_message, self._haiku_model()
                )
                self.session.role_directive = role_signal.directive
            except Exception:
                logger.debug("role detection skipped (non-fatal)", exc_info=True)
            finally:
                self.session.role_detected = True
        role_directive = self.session.role_directive

        self.session.history.append({"role": "user", "content": user_message})
        memory_block = await self._memory_read_context(user_message)
        system_prompt = (
            (f"{self._system}\n\n{memory_block}" if memory_block else self._system)
            + frustration_directive
            + role_directive
        )

        config = {"configurable": {"thread_id": self.session.session_id}}
        initial_state: ChatGraphState = {
            "user_message": user_message,
            "system_prompt": system_prompt,
            "iteration": 0,
            "pending_tool_uses": [],
            "tool_results": [],
            "final_text": "",
            "last_error": None,
            "stop": False,
        }

        from app.fleet.metrics import run_span

        tokens_in_before, tokens_out_before = self._tokens_in, self._tokens_out
        with run_span("chat_agent", task_id=self.session.session_id) as _metrics:
            self._current_trace_id = _metrics.trace_id
            try:
                await self._graph.ainvoke(initial_state, config=config)
            finally:
                _metrics.record_tokens(
                    self._tokens_in - tokens_in_before,
                    self._tokens_out - tokens_out_before,
                )
                self._current_trace_id = ""

    async def resume(
        self,
        action_id: str,
        approved: bool,
        selected: str | None = None,
        remember: bool = False,
    ) -> bool:
        """Resume a turn paused at a real interrupt() after a human
        answered a confirmation. Returns False (a safe no-op — nothing is
        re-run) if action_id doesn't match the currently pending
        confirmation, e.g. a stale or duplicate confirm call; True if a
        real resume happened.

        `selected` is AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) —
        carries the chosen option's id back to a paused
        _confirm_with_options() call; ignored (and harmless) for every
        plain _confirm() call site, which only ever reads `approved`.

        `remember` is AUDIT_Q_BATCH07 §39 gap-closure (2026-08-11) — when
        True on an approved confirmation, _confirm() adds the paused tool
        name to session.remembered_confirmations so the same tool
        auto-approves without pausing for the rest of this session."""
        config = {"configurable": {"thread_id": self.session.session_id}}
        snapshot = await self._graph.aget_state(config)

        pending_action_id: str | None = None
        for task in snapshot.tasks:
            for i in task.interrupts:
                pending_action_id = i.value.get("action_id")

        if pending_action_id != action_id:
            logger.warning(
                "Chat confirmation action_id mismatch for session %s: got %r, pending %r",
                self.session.session_id,
                action_id,
                pending_action_id,
            )
            return False

        from app.fleet.metrics import run_span

        tokens_in_before, tokens_out_before = self._tokens_in, self._tokens_out
        with run_span("chat_agent", task_id=self.session.session_id) as _metrics:
            self._current_trace_id = _metrics.trace_id
            try:
                resume_payload: dict[str, Any] = {
                    "approved": approved,
                    "remember": remember,
                }
                if selected is not None:
                    resume_payload["selected"] = selected
                await self._graph.ainvoke(Command(resume=resume_payload), config=config)
            finally:
                _metrics.record_tokens(
                    self._tokens_in - tokens_in_before,
                    self._tokens_out - tokens_out_before,
                )
                self._current_trace_id = ""
        return True
