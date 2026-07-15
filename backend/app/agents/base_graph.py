"""
Base LangGraph agent builder — all production worker agents use build_agent_graph().

LangGraph Production Contract (enforced here, not in prompts):
1.  state["verification"] tracks what the graph has PROVEN via actual tool runs.
    The model's claims in submit_* arguments are OVERRIDDEN by this dict.
2.  Mutating tools (edit_file, write_file, apply_patch) invalidate tests_passed.
3.  Verification tools (run_tests, run_linter, run_sast_scan, etc.) set their
    flag to True ONLY when they complete without an [ERROR] prefix.
4.  submit_* handler reads state["verification"] to enforce boolean fields in the
    final result — the model cannot lie about "tests passed" or "scan clean."
5.  max_turns is enforced by the graph's conditional edge, not by hoping the model
    stops itself.
6.  High-blast-radius agents set requires_human_approval=True in their result;
    the orchestrator checks this before applying changes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

import anthropic

from app.agents.base import get_effective_api_key, load_role
from app.agents.guardrails import check_command, check_path
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class AgentRunState(TypedDict):
    """State passed between nodes in every agent graph."""
    messages: list[dict[str, Any]]
    verification: dict[str, Any]   # proven facts — never accept from model claims
    result: dict[str, Any]          # final result from submit_* tool
    turns: int
    submitted: bool
    requires_human_approval: bool
    tokens_in: int
    tokens_out: int


# ---------------------------------------------------------------------------
# Verification configuration (per agent)
# ---------------------------------------------------------------------------

@dataclass
class VerificationConfig:
    """Declares the verification rules for a specific agent.

    set_by: {tool_name: verification_key}
        When tool_name runs without [ERROR], set state["verification"][key] = True.
    reset_by: tuple[str, ...]
        Tools that mutate code — running any of them resets the listed reset_keys to False.
    reset_keys: tuple[str, ...]
        Verification keys that get reset when a mutating tool runs.
    enforce_in_result: {result_field: verification_key}
        When submit_* runs, override result[field] with state["verification"][key].
    initial: dict[str, Any]
        Initial values for the verification dict.
    """
    set_by: dict[str, str] = field(default_factory=dict)
    reset_by: tuple[str, ...] = field(default_factory=tuple)
    reset_keys: tuple[str, ...] = field(default_factory=tuple)
    enforce_in_result: dict[str, str] = field(default_factory=dict)
    initial: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_content(content: Any) -> list[dict[str, Any]]:
    """Convert Anthropic response content to plain JSON-serialisable dicts."""
    if isinstance(content, list):
        out: list[dict[str, Any]] = []
        for block in content:
            if hasattr(block, "type"):
                if block.type == "text":
                    out.append({"type": "text", "text": getattr(block, "text", "")})
                elif block.type == "tool_use":
                    out.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(block.input or {}),
                    })
            elif isinstance(block, dict):
                out.append(block)
        return out
    return []


# ---------------------------------------------------------------------------
# Policy enforcement (delegates to guardrails)
# ---------------------------------------------------------------------------

def _policy_check(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Return denial string if the tool call is policy-denied, else None."""
    if tool_name in ("write_file", "edit_file", "apply_patch", "delete_file"):
        path = str(tool_input.get("path", ""))
        result = check_path(path)
        if not result.allowed:
            return result.reason
    if tool_name == "bash":
        cmd = str(tool_input.get("command", ""))
        result = check_command(cmd)
        if not result.allowed:
            return result.reason
    return None


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------

def _make_call_llm_node(
    role_name: str,
    model: str,
    tools: list[dict[str, Any]],
) -> Callable[[AgentRunState], dict[str, Any]]:
    """Build the 'call_llm' node — calls Anthropic, returns updated state slice."""
    system_prompt = load_role(role_name)
    anthropic_tools: list[anthropic.types.ToolParam] = [
        anthropic.types.ToolParam(
            name=t["name"],
            description=t.get("description", ""),
            input_schema=t["input_schema"],
        )
        for t in tools
    ]

    def call_llm(state: AgentRunState) -> dict[str, Any]:
        client = anthropic.Anthropic(api_key=get_effective_api_key())
        response = client.messages.create(
            model=model,
            max_tokens=8096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=state["messages"],  # type: ignore[arg-type]
            tools=anthropic_tools,
        )
        serialized_content = _serialize_content(response.content)
        return {
            "messages": state["messages"] + [
                {"role": "assistant", "content": serialized_content}
            ],
            "tokens_in": state["tokens_in"] + response.usage.input_tokens,
            "tokens_out": state["tokens_out"] + response.usage.output_tokens,
        }

    return call_llm


def _make_execute_tools_node(
    tool_handlers: dict[str, Any],
    verification_cfg: VerificationConfig,
    human_approval_required: bool,
) -> Callable[[AgentRunState], dict[str, Any]]:
    """Build the 'execute_tools' node — runs tool calls, enforces verification."""

    def execute_tools(state: AgentRunState) -> dict[str, Any]:
        # Last message is the assistant message with tool_use blocks
        last_msg = state["messages"][-1]
        content = last_msg.get("content", []) if isinstance(last_msg, dict) else []
        tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]

        new_verification = dict(state["verification"])
        new_result = dict(state["result"])
        submitted = state["submitted"]
        tool_results: list[dict[str, Any]] = []

        for tu in tool_uses:
            tu_id = str(tu.get("id", ""))
            tu_name = str(tu.get("name", ""))
            tu_input = dict(tu.get("input", {}))

            # 1. Policy gate
            denial = _policy_check(tu_name, tu_input)
            if denial:
                result_content = f"[POLICY DENIED] {denial}"
                logger.warning("Policy denied %s: %s", tu_name, denial)
            else:
                handler = tool_handlers.get(tu_name)
                if handler is None:
                    result_content = f"[ERROR] Unknown tool: {tu_name}"
                else:
                    try:
                        result_content = str(handler(tu_input))
                    except Exception as exc:
                        result_content = f"[ERROR] {tu_name} raised: {exc}"
                        logger.exception("Tool %s raised", tu_name)

                    # 2. Verification side-effects
                    if not result_content.startswith("[ERROR]") and not result_content.startswith("[POLICY"):
                        # A verification tool ran successfully → prove its claim
                        if tu_name in verification_cfg.set_by:
                            key = verification_cfg.set_by[tu_name]
                            new_verification[key] = True
                            logger.debug("Verification: %s = True (from %s)", key, tu_name)

                    # 3. Mutating tools invalidate prior test verification
                    if tu_name in verification_cfg.reset_by:
                        for key in verification_cfg.reset_keys:
                            new_verification[key] = False
                            logger.debug("Verification reset: %s = False (after %s)", key, tu_name)

                    # 4. Submit tool: enforce verification facts over model claims
                    if tu_name.startswith("submit_"):
                        submitted = True
                        raw_result = dict(tu_input)
                        # Override any boolean the model tried to claim
                        for result_field, verif_key in verification_cfg.enforce_in_result.items():
                            actual_value = new_verification.get(verif_key, False)
                            if raw_result.get(result_field) != actual_value:
                                logger.info(
                                    "Verification override: result[%s]=%s → %s (from state.verification.%s)",
                                    result_field, raw_result.get(result_field), actual_value, verif_key,
                                )
                            raw_result[result_field] = actual_value
                        raw_result["_requires_human_approval"] = human_approval_required
                        new_result.update(raw_result)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": result_content,
            })

        return {
            "messages": state["messages"] + [{"role": "user", "content": tool_results}],
            "verification": new_verification,
            "result": new_result,
            "submitted": submitted,
            "turns": state["turns"] + 1,
            "requires_human_approval": human_approval_required and submitted,
        }

    return execute_tools


# ---------------------------------------------------------------------------
# Graph routing
# ---------------------------------------------------------------------------

def _make_router(max_turns: int) -> Callable[[AgentRunState], str]:
    """Route after the call_llm node."""
    def router(state: AgentRunState) -> str:
        # Terminal conditions
        if state["submitted"]:
            return END  # type: ignore[return-value]
        if state["turns"] >= max_turns:
            logger.warning("Agent hit max_turns (%d) — stopping", max_turns)
            return END  # type: ignore[return-value]
        # Check if the last message has tool_use blocks
        last_msg = state["messages"][-1] if state["messages"] else {}
        content = last_msg.get("content", []) if isinstance(last_msg, dict) else []
        has_tools = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        return "execute_tools" if has_tools else END  # type: ignore[return-value]

    return router


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_agent_graph(
    *,
    role_name: str,
    model: str,
    tools: list[dict[str, Any]],
    tool_handlers: dict[str, Any],
    verification_cfg: VerificationConfig,
    human_approval_required: bool = False,
    max_turns: int = 20,
) -> Any:  # returns a CompiledStateGraph
    """
    Build a production LangGraph StateGraph for a worker agent.

    The graph enforces the verification contract — no agent can claim its work
    is verified unless the corresponding tool actually ran and succeeded.
    """
    call_llm = _make_call_llm_node(role_name, model, tools)
    execute_tools = _make_execute_tools_node(
        tool_handlers, verification_cfg, human_approval_required
    )
    router = _make_router(max_turns)

    g: StateGraph = StateGraph(AgentRunState)
    g.add_node("call_llm", call_llm)
    g.add_node("execute_tools", execute_tools)
    g.set_entry_point("call_llm")
    g.add_conditional_edges("call_llm", router, {"execute_tools": "execute_tools", END: END})
    g.add_edge("execute_tools", "call_llm")

    return g.compile()


def run_agent_graph(
    *,
    role_name: str,
    model: str,
    tools: list[dict[str, Any]],
    tool_handlers: dict[str, Any],
    verification_cfg: VerificationConfig,
    initial_message: str,
    human_approval_required: bool = False,
    max_turns: int = 20,
) -> AgentRunState:
    """
    Build + run the agent graph, return the final state.

    The caller reads state["result"] for results and
    state["verification"] for what was actually proven.
    """
    graph = build_agent_graph(
        role_name=role_name,
        model=model,
        tools=tools,
        tool_handlers=tool_handlers,
        verification_cfg=verification_cfg,
        human_approval_required=human_approval_required,
        max_turns=max_turns,
    )

    initial_state: AgentRunState = {
        "messages": [{"role": "user", "content": initial_message}],
        "verification": dict(verification_cfg.initial),
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }

    final_state: AgentRunState = graph.invoke(initial_state)  # type: ignore[assignment]
    return final_state
