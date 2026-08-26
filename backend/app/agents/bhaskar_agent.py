"""bhaskar_agent — the internal LangGraph sub-agent that bhaskar_tool
(app/tools/agents/bhaskar_tool.py) runs when no existing tool covers a
requesting agent's task.

Not a user-facing/fleet-registered agent like coder/research/etc. — it has
no AGENT_CONTRACT and no capability_registry entry, and is never selectable
by name. It exists purely as bhaskar_tool's own internal engine: one more
run_agent_graph() caller (the same LangGraph runner every real agent uses —
see app/agents/base_graph.py) with a small, fixed, three-tool set:

  - web_search            (app/tools/integrations/web_search.py, unchanged)
  - run_sandboxed_script  (app/agents/bhaskar_sandbox.py — hardened,
                           isolated; NOT the plain run_python_snippet tool
                           other agents use, which runs with cwd=repo_path
                           and the full process environment)
  - submit_generated_tool (local to this module — this agent's only way to
                           return a final answer, same "submit_*" idiom as
                           research.py/submit_docs.py/submit_patch.py)

Since run_agent_graph()'s Dynamic Tool Selection (base_graph.py, plan14 Day
1 Task 1) only narrows a tool to agents that declare it a HIGH-RISK tool in
their own capability_registry contract, and bhaskar_agent has no such
contract at all, these three internal-only tools pass through unfiltered as
long as they have a live handler — which they always do here.

Recursion guardrail: this tool list deliberately excludes bhaskar_tool
itself. The Anthropic API can only invoke a tool present in the `tools=`
list passed to it, so this is a structural guarantee, not a prompt
instruction — bhaskar_agent physically cannot call bhaskar_tool. A
ContextVar guard (`bhaskar_agent_active`) is layered on top purely as
defense-in-depth in case a future change ever merges tool lists by
accident; app/tools/agents/bhaskar_tool.py checks it too before starting a
run.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, Callable

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.bhaskar_sandbox import (
    SANDBOXED_RUN_SCRIPT_TOOL,
    make_sandboxed_run_script_handler,
    run_sandboxed_python,
)
from app.config import get_settings
from app.tools.integrations.web_search import WEB_SEARCH_TOOL, web_search_handler

logger = logging.getLogger(__name__)

bhaskar_agent_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "bhaskar_agent_active", default=False
)


class BhaskarRecursionError(RuntimeError):
    """Raised if bhaskar_agent is entered while already active on this call
    stack (should be structurally impossible — see module docstring)."""


SUBMIT_GENERATED_TOOL: dict[str, Any] = {
    "name": "submit_generated_tool",
    "description": (
        "Submit your final, tested Python script as the answer to the "
        "requested task. Call this only after you have run the script via "
        "run_sandboxed_script at least once and confirmed it actually "
        "works. The script must be fully self-contained and print() its "
        "result — that printed output is what gets returned."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The final, tested Python script",
            },
            "result_summary": {
                "type": "string",
                "description": "A short summary of what the script produced/found",
            },
        },
        "required": ["code", "result_summary"],
    },
}


def _make_submit_handler(
    sink: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    def _handler(inp: dict[str, Any]) -> str:
        code = str(inp.get("code", "")).strip()
        if not code:
            return "[ERROR] code is required"
        sink["code"] = code
        sink["result_summary"] = str(inp.get("result_summary", ""))
        return "Submitted."

    return _handler


def run_bhaskar_agent(
    task_description: str,
    context: str,
    repo_path: str,
    trace_id: str = "",
) -> dict[str, Any]:
    """Run the bhaskar_agent LangGraph loop once — no internal retry (the
    caller, bhaskar_tool_handler, owns bounded retry per
    settings.bhaskar_tool_max_retries). Never raises. Returns:

        {"ok": bool, "code": str, "result_summary": str,
         "tested_output": str, "error": str,
         "tokens_in": int, "tokens_out": int}

    `ok` reflects a real, independently re-executed verification run of the
    submitted code (below) — never just the agent's own self-report that it
    "works", matching this codebase's existing "verify deterministically,
    don't trust the LLM's claim" convention.
    """
    if bhaskar_agent_active.get():
        raise BhaskarRecursionError(
            "run_bhaskar_agent() called while already active on this call stack"
        )

    settings = get_settings()
    result_sink: dict[str, Any] = {}

    sandbox_kwargs: dict[str, Any] = {
        "repo_path": repo_path,
        "timeout": settings.bhaskar_tool_sandbox_script_timeout_seconds,
        "allow_network": settings.bhaskar_tool_sandbox_allow_network,
        "max_memory_mb": settings.bhaskar_tool_sandbox_max_memory_mb,
        "max_output_file_mb": settings.bhaskar_tool_sandbox_max_output_file_mb,
        "max_output_chars": settings.bhaskar_tool_sandbox_max_output_chars,
        "max_total_disk_mb": settings.bhaskar_tool_sandbox_max_total_disk_mb,
        "max_processes": settings.bhaskar_tool_sandbox_max_processes,
    }

    tools = [WEB_SEARCH_TOOL, SANDBOXED_RUN_SCRIPT_TOOL, SUBMIT_GENERATED_TOOL]
    handlers: dict[str, Any] = {
        "web_search": web_search_handler,
        "run_sandboxed_script": make_sandboxed_run_script_handler(**sandbox_kwargs),
        "submit_generated_tool": _make_submit_handler(result_sink),
    }

    verification_cfg = VerificationConfig(
        set_by={"submit_generated_tool": "submitted"},
        reset_by=(),
        reset_keys=(),
        enforce_in_result={"submitted": "submitted"},
        initial={"submitted": False},
    )

    initial_message = (
        "You are a narrow, single-purpose helper: write and test ONE "
        "self-contained Python script that accomplishes the task below, "
        "then call submit_generated_tool with the final script.\n\n"
        f"TASK:\n{task_description}\n\n"
        + (f"CONTEXT/INPUTS:\n{context}\n\n" if context.strip() else "")
        + "Use web_search only if you genuinely need to look up an API or "
        "library detail. Use run_sandboxed_script to test your script — it "
        "runs in an isolated sandbox with no access to this project's "
        "files or credentials, so don't assume any local files exist. "
        "Iterate until the script actually works, then call "
        "submit_generated_tool exactly once with the final version."
    )

    token = bhaskar_agent_active.set(True)
    try:
        final_state = run_agent_graph(
            role_name="bhaskar_agent",
            model=settings.model_coder,
            tools=tools,
            tool_handlers=handlers,
            verification_cfg=verification_cfg,
            initial_message=initial_message,
            task_description=task_description,
            repo_path=repo_path,
            model_haiku=settings.model_router,
            max_turns=settings.bhaskar_tool_max_turns,
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_run_tracking=False,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning("bhaskar_agent run failed: %s", exc)
        return {
            "ok": False,
            "code": "",
            "result_summary": "",
            "tested_output": "",
            "error": f"bhaskar_agent run failed: {exc}",
            "tokens_in": 0,
            "tokens_out": 0,
        }
    finally:
        bhaskar_agent_active.reset(token)

    tokens_in = final_state.get("tokens_in", 0)
    tokens_out = final_state.get("tokens_out", 0)

    if not result_sink.get("code"):
        return {
            "ok": False,
            "code": "",
            "result_summary": "",
            "tested_output": "",
            "error": (
                "bhaskar_agent did not submit a script "
                "(no submit_generated_tool call)"
            ),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    final_check = run_sandboxed_python(result_sink["code"], **sandbox_kwargs)

    return {
        "ok": bool(final_check["success"]),
        "code": result_sink["code"],
        "result_summary": result_sink.get("result_summary", ""),
        "tested_output": final_check["output"],
        "error": "" if final_check["success"] else "final verification run failed",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
