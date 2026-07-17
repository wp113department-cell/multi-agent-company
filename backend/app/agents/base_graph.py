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

Session 0 additions (2026-07-16) — all flags default False, zero breaking changes:
  planner_node     — gather-facts + create-plan (Haiku). AutoGen MagenticOne pattern.
  memory_hook_node — pre-inference lesson injection. AutoGen MemoryController pattern.
  reflection_node  — post-tool reflect_on_tool_use. AutoGen reflect pattern.
  lesson_node      — post-submit lesson extraction. AutoGen MemoryController pattern.
  Stall detection  — n_stalls counter in router. AutoGen MagenticOne stall detection.
  run_span         — Fleet OS metrics wrapper. fleet/metrics.py.
  Context trim     — token budget enforcement. LangGraph RemainingSteps + roo-code condense.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, TypedDict

import anthropic

from app.agents.base import get_effective_api_key, load_role
from app.agents.guardrails import check_command, check_path
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph State — 8 original required fields + 9 new optional Fleet OS fields
# ---------------------------------------------------------------------------

class _AgentRunStateBase(TypedDict):
    """Original 8 required fields — unchanged from Day 3."""
    messages: list[dict[str, Any]]
    verification: dict[str, Any]
    result: dict[str, Any]
    turns: int
    submitted: bool
    requires_human_approval: bool
    tokens_in: int
    tokens_out: int


class AgentRunState(_AgentRunStateBase, total=False):
    """Full agent state including 9 new Fleet OS fields (Session 0, 2026-07-16).

    All new fields are optional (total=False) so existing callers need zero changes.
    run_agent_graph() populates them with safe defaults in initial_state.
    """
    plan: str           # structured plan JSON from planner_node
    facts: str          # gathered-facts JSON from planner_node
    n_stalls: int       # consecutive turns without tool calls (stall detection)
    retry_count: int    # total replan cycles
    confidence: float   # planner-assigned confidence 0.0–1.0
    status: str         # running | completed | blocked | failed
    trace_id: str       # Fleet OS correlation ID
    memory_context: str # retrieved past lessons, injected into system prompt
    repo_context: str   # repo structure snapshot from context_builder


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
# LessonStore — in-process cross-agent lesson sharing
# Pattern from: AutoGen MemoryController + LangGraph cross-thread store
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    agent_name: str
    lesson: str
    pattern: str
    category: str
    reusable: bool = True

    def as_context_line(self) -> str:
        return f"- [{self.category}] {self.lesson}"


class LessonStore:
    """Thread-safe in-process lesson registry shared across all agent runs.

    Agents write via lesson extraction after submit. Agents read top-k relevant
    lessons before each LLM call. Uses keyword overlap scoring — no embeddings.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self._lessons: list[Lesson] = []
        self._capacity = capacity
        self._lock = Lock()

    def add(self, lesson: Lesson) -> None:
        with self._lock:
            if len(self._lessons) >= self._capacity:
                self._lessons.pop(0)
            self._lessons.append(lesson)

    def retrieve(self, query: str, top_k: int = 3) -> list[Lesson]:
        query_tokens = set(query.lower().split())
        with self._lock:
            lessons = list(self._lessons)
        scored: list[tuple[float, Lesson]] = []
        for lesson in lessons:
            if not lesson.reusable:
                continue
            text = f"{lesson.lesson} {lesson.pattern} {lesson.category}".lower()
            score = len(query_tokens & set(text.split()))
            if score > 0:
                scored.append((score, lesson))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ls for _, ls in scored[:top_k]]

    def format_for_injection(self, query: str, top_k: int = 3) -> str:
        retrieved = self.retrieve(query, top_k=top_k)
        if not retrieved:
            return ""
        lines = ["## Relevant past insights:"] + [ls.as_context_line() for ls in retrieved]
        return "\n".join(lines)

    @property
    def total(self) -> int:
        with self._lock:
            return len(self._lessons)


_lesson_store: LessonStore | None = None
_lesson_store_lock = Lock()


def get_lesson_store() -> LessonStore:
    global _lesson_store
    if _lesson_store is None:
        with _lesson_store_lock:
            if _lesson_store is None:
                _lesson_store = LessonStore()
    return _lesson_store


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


def _text_from_content(content: list[dict[str, Any]]) -> str:
    return " ".join(
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()


# ---------------------------------------------------------------------------
# Context trim — token budget enforcement before call_llm
# Pattern from: LangGraph RemainingSteps + roo-code src/core/condense/
# ---------------------------------------------------------------------------

def _trim_messages(
    messages: list[dict[str, Any]],
    token_budget: int,
    tokens_in: int,
) -> list[dict[str, Any]]:
    """Drop oldest messages when over budget. Keeps head[0] + tail[-4]."""
    if tokens_in <= token_budget or len(messages) <= 4:
        return messages
    trimmed = messages[:1] + messages[-4:]
    logger.info(
        "Context trim: %d → %d messages (tokens_in=%d > budget=%d)",
        len(messages), len(trimmed), tokens_in, token_budget,
    )
    return trimmed



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

def _make_planner_node(
    model_haiku: str,
    task_description: str,
) -> Callable[[AgentRunState], dict[str, Any]]:
    """gather-facts → create-plan (Haiku). AutoGen MagenticOne task ledger pattern.
    Runs once at graph start. Sets plan, facts, confidence in state.
    """

    def planner_node(state: AgentRunState) -> dict[str, Any]:
        client = anthropic.Anthropic(api_key=get_effective_api_key())
        task = task_description or str(
            (state["messages"][0].get("content", "") if state["messages"] else "")
        )

        # Call 1: gather-facts survey
        facts_prompt = (
            f"Analyze this task. Respond ONLY in JSON:\n"
            f'{{ "given": [...], "to_look_up": [...], "to_derive": [...], "guesses": [...] }}\n\n'
            f"Task: {task[:600]}"
        )
        facts_text = "{}"
        try:
            r = client.messages.create(
                model=model_haiku, max_tokens=512,
                messages=[{"role": "user", "content": facts_prompt}],
            )
            facts_text = _text_from_content(_serialize_content(r.content))
        except Exception as exc:
            logger.warning("planner_node facts call failed: %s", exc)

        # Call 2: create structured plan
        plan_prompt = (
            f"Create a step-by-step plan. Respond ONLY in JSON:\n"
            f'{{ "steps": [...], "validation": [...], "confidence": 0.85, "risks": [...] }}\n\n'
            f"Task: {task[:600]}\nFacts: {facts_text[:400]}"
        )
        plan_text = "{}"
        confidence = 0.8
        try:
            r2 = client.messages.create(
                model=model_haiku, max_tokens=512,
                messages=[{"role": "user", "content": plan_prompt}],
            )
            plan_text = _text_from_content(_serialize_content(r2.content))
            confidence = float(json.loads(plan_text).get("confidence", 0.8))
        except Exception as exc:
            logger.warning("planner_node plan call failed: %s", exc)

        logger.info("planner_node done (confidence=%.2f)", confidence)
        return {"facts": facts_text, "plan": plan_text, "confidence": confidence, "status": "running"}

    return planner_node


def _make_memory_hook_node(
    task_description: str,
    repo_path: str,
) -> Callable[[AgentRunState], dict[str, Any]]:
    """Pre-inference lesson + repo context injection (runs once at graph entry).
    AutoGen MemoryController.update_context() + OpenHands repo.md pattern.
    Sync only — no async DB calls.
    """

    def memory_hook_node(state: AgentRunState) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        query = task_description or str(
            (state["messages"][0].get("content", "") if state["messages"] else "")
        )

        # 1. Retrieve relevant past lessons from in-process LessonStore
        lesson_block = get_lesson_store().format_for_injection(query, top_k=3)
        if lesson_block:
            updates["memory_context"] = lesson_block

        # 2. Repo context injection (sync, non-fatal)
        if repo_path and not state.get("repo_context"):
            try:
                from app.repo_tools.context_builder import build_context
                from app.repo_tools.scanner import build_repo_index
                idx = build_repo_index(repo_path)
                ctx = build_context(task_description=query or "general", index=idx, top_k=10)
                summary = f"## Repo context\nRelevant files: {', '.join(ctx.relevant_files[:8])}"
                if ctx.related_symbols:
                    summary += f"\nKey symbols: {', '.join(ctx.related_symbols[:6])}"
                updates["repo_context"] = summary
            except Exception as exc:
                logger.debug("memory_hook repo context skipped: %s", exc)

        return updates

    return memory_hook_node


def _make_call_llm_node(
    role_name: str,
    model: str,
    tools: list[dict[str, Any]],
    context_token_budget: int,
    task_id: str = "",
) -> Callable[[AgentRunState], dict[str, Any]]:
    """Calls Anthropic. Injects plan + memory_context into system prompt.
    Applies context trim when tokens_in exceeds budget.
    Pushes thinking/token_usage events to ActivityStream when task_id is set.
    """
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
        # Check abort flag before calling LLM
        if task_id:
            try:
                from app.services.activity_stream import get_activity_registry
                if get_activity_registry().should_abort(task_id):
                    logger.info("Abort flag set for task %s — stopping agent", task_id)
                    return {"submitted": True, "status": "stopped"}
            except Exception:
                pass

        client = anthropic.Anthropic(api_key=get_effective_api_key())

        # Context trim
        messages = _trim_messages(
            list(state["messages"]),
            token_budget=context_token_budget,
            tokens_in=state.get("tokens_in", 0),
        )

        # Enrich system prompt with plan + memory context
        full_system = system_prompt
        plan = state.get("plan", "")
        mem = state.get("memory_context", "")
        repo = state.get("repo_context", "")
        suffix_parts = []
        if plan:
            suffix_parts.append(f"## Execution plan:\n{plan}")
        if mem:
            suffix_parts.append(mem)
        if repo:
            suffix_parts.append(repo)
        if suffix_parts:
            full_system = full_system + "\n\n" + "\n\n".join(suffix_parts)

        response = client.messages.create(
            model=model,
            max_tokens=8096,
            system=[{"type": "text", "text": full_system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,  # type: ignore[arg-type]
            tools=anthropic_tools,
        )
        serialized = _serialize_content(response.content)

        # Push activity stream events (non-fatal)
        if task_id:
            try:
                from app.services.activity_stream import push_thinking, push_token_usage
                text = _text_from_content(serialized)
                if text:
                    push_thinking(task_id, text, role_name)
                tokens_in_new = state.get("tokens_in", 0) + response.usage.input_tokens
                tokens_out_new = state.get("tokens_out", 0) + response.usage.output_tokens
                push_token_usage(task_id, tokens_in_new, tokens_out_new)
            except Exception:
                pass

        return {
            "messages": list(state["messages"]) + [{"role": "assistant", "content": serialized}],
            "tokens_in": state.get("tokens_in", 0) + response.usage.input_tokens,
            "tokens_out": state.get("tokens_out", 0) + response.usage.output_tokens,
        }

    return call_llm


def _make_reflection_node(model: str) -> Callable[[AgentRunState], dict[str, Any]]:
    """Post-tool second LLM call with no tools (tool_choice=none equivalent).
    AutoGen reflect_on_tool_use pattern. Forces synthesis before next LLM turn.
    Returns a reflection message appended to state["messages"].
    """

    REFLECTION_PROMPT = (
        "Review what the tools just produced. Ask yourself:\n"
        "1. Did I solve the REAL problem or just the surface symptom?\n"
        "2. Are there edge cases or side effects I missed?\n"
        "3. Is this production-ready, or does it need more work?\n"
        "Respond in JSON only: "
        '{"satisfied": true/false, "issues": ["issue1", ...]}'
    )

    def reflection_node(state: AgentRunState) -> dict[str, Any]:
        client = anthropic.Anthropic(api_key=get_effective_api_key())
        try:
            r = client.messages.create(
                model=model, max_tokens=384,
                messages=list(state["messages"]) + [
                    {"role": "user", "content": REFLECTION_PROMPT}
                ],
                # No tools param → tool_choice=none equivalent
            )
            text = _text_from_content(_serialize_content(r.content))
            satisfied = True
            try:
                satisfied = bool(json.loads(text).get("satisfied", True))
            except (json.JSONDecodeError, ValueError):
                pass

            if not satisfied:
                logger.info("reflection_node: not satisfied — adding self-review message")
                return {
                    "messages": list(state["messages"]) + [
                        {"role": "user", "content": f"[Self-review]\n{text}"}
                    ]
                }
        except Exception as exc:
            logger.warning("reflection_node failed (non-fatal): %s", exc)
        return {}

    return reflection_node


def _make_execute_tools_node(
    tool_handlers: dict[str, Any],
    verification_cfg: VerificationConfig,
    human_approval_required: bool,
    task_id: str = "",
) -> Callable[[AgentRunState], dict[str, Any]]:
    """Runs tool calls, enforces verification contract, resets stall counter.
    Pushes tool_call / tool_result / file_edit / terminal events to ActivityStream.
    """

    def execute_tools(state: AgentRunState) -> dict[str, Any]:
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

            # Push tool_call event
            if task_id:
                try:
                    from app.services.activity_stream import push_tool_call
                    push_tool_call(task_id, tu_name, tu_input, tu_id)
                except Exception:
                    pass

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

                    if not result_content.startswith("[ERROR]") and not result_content.startswith("[POLICY"):
                        if tu_name in verification_cfg.set_by:
                            key = verification_cfg.set_by[tu_name]
                            new_verification[key] = True
                            logger.debug("Verification: %s=True (from %s)", key, tu_name)

                    if tu_name in verification_cfg.reset_by:
                        for key in verification_cfg.reset_keys:
                            new_verification[key] = False

                    if tu_name.startswith("submit_"):
                        submitted = True
                        raw_result = dict(tu_input)
                        for result_field, verif_key in verification_cfg.enforce_in_result.items():
                            actual = new_verification.get(verif_key, False)
                            if raw_result.get(result_field) != actual:
                                logger.info(
                                    "Verification override: result[%s]=%s → %s",
                                    result_field, raw_result.get(result_field), actual,
                                )
                            raw_result[result_field] = actual
                        raw_result["_requires_human_approval"] = human_approval_required
                        new_result.update(raw_result)

            # Push tool_result + specialized events
            if task_id:
                try:
                    from app.services.activity_stream import (
                        push_tool_result, push_file_edit, push_terminal,
                    )
                    ok = not result_content.startswith("[ERROR]") and not result_content.startswith("[POLICY")
                    push_tool_result(task_id, tu_name, result_content, ok, tu_id)
                    if tu_name in ("write_file", "edit_file", "apply_patch", "delete_file"):
                        path = str(tu_input.get("path", ""))
                        push_file_edit(task_id, path, tu_name)
                    if tu_name == "bash":
                        push_terminal(task_id, str(tu_input.get("command", "")), result_content)
                except Exception:
                    pass

            tool_results.append({"type": "tool_result", "tool_use_id": tu_id, "content": result_content})

        return {
            "messages": list(state["messages"]) + [{"role": "user", "content": tool_results}],
            "verification": new_verification,
            "result": new_result,
            "submitted": submitted,
            "turns": state["turns"] + 1,
            "requires_human_approval": human_approval_required and submitted,
            "n_stalls": 0,  # reset stall counter — tools were used this turn
        }

    return execute_tools


# ---------------------------------------------------------------------------
# Post-graph lesson extraction (not a graph node — runs after graph.invoke)
# AutoGen MemoryController.train_on_task() pattern
# ---------------------------------------------------------------------------

def _extract_and_store_lesson(
    final_state: AgentRunState,
    role_name: str,
    model_haiku: str,
    trace_id: str = "",
) -> None:
    """Extract a reusable lesson from the completed run and store in LessonStore.
    Non-fatal — any failure is logged and swallowed.
    """
    task = str(final_state["messages"][0].get("content", "")) if final_state["messages"] else ""
    result = final_state.get("result", {})
    result_summary = json.dumps(
        {k: v for k, v in result.items() if not k.startswith("_")}, default=str
    )[:400]

    prompt = (
        f"An agent just completed a task. Extract a reusable lesson.\n"
        f"Task: {task[:400]}\nResult: {result_summary}\n\n"
        "Respond in JSON only:\n"
        '{"lesson": "...", "pattern": "...", '
        '"category": "testing|security|refactor|debugging|planning|docs|general", '
        '"reusable": true}'
    )
    try:
        client = anthropic.Anthropic(api_key=get_effective_api_key())
        r = client.messages.create(
            model=model_haiku, max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _text_from_content(_serialize_content(r.content))
        data = json.loads(text)
        lesson = Lesson(
            agent_name=role_name,
            lesson=str(data.get("lesson", "")),
            pattern=str(data.get("pattern", "")),
            category=str(data.get("category", "general")),
            reusable=bool(data.get("reusable", True)),
        )
        if lesson.lesson:
            get_lesson_store().add(lesson)
            logger.info("lesson stored for %s (category=%s)", role_name, lesson.category)
            try:
                from app.fleet.fleet_events import lesson_published, publish
                publish(lesson_published(role_name, lesson.lesson, lesson.category, trace_id=trace_id))
            except Exception:
                pass
    except Exception as exc:
        logger.debug("lesson extraction failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Graph routing — stall detection (AutoGen MagenticOne progress_ledger pattern)
# ---------------------------------------------------------------------------

def _make_router(
    max_turns: int,
    max_stalls: int,
    enable_reflection: bool,
) -> Callable[[AgentRunState], str]:
    """Route after call_llm. Detects stalls (turns with no tool calls)."""

    def router(state: AgentRunState) -> str:
        if state.get("submitted"):
            return END  # type: ignore[return-value]
        if state["turns"] >= max_turns:
            logger.warning("Agent hit max_turns (%d) — stopping", max_turns)
            return END  # type: ignore[return-value]

        last_msg = state["messages"][-1] if state["messages"] else {}
        content = last_msg.get("content", []) if isinstance(last_msg, dict) else []
        has_tools = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)

        if has_tools:
            return "reflection_node" if enable_reflection else "execute_tools"

        # No tool calls this turn — stall detection
        n_stalls = state.get("n_stalls", 0) + 1
        if n_stalls >= max_stalls:
            logger.warning("Agent stalled %d turns without tool calls — stopping", n_stalls)
        return END  # type: ignore[return-value]

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
    # Fleet OS flags — enabled by default (Day 0, 2026-07-16)
    # Pass False explicitly to opt an agent out of a specific node.
    enable_planning: bool = True,
    enable_memory: bool = True,
    enable_reflection: bool = True,
    task_description: str = "",
    repo_path: str = "",
    model_haiku: str = "",
    context_token_budget: int = 60_000,
    max_stalls: int = 3,
    task_id: str = "",
) -> Any:
    """Build a production LangGraph StateGraph for a worker agent.

    The graph enforces the verification contract. All Fleet OS flags default to
    True — every agent gets planning + memory + reflection unless it opts out.
    """
    haiku = model_haiku or model
    call_llm = _make_call_llm_node(role_name, model, tools, context_token_budget, task_id)
    execute_tools_node = _make_execute_tools_node(tool_handlers, verification_cfg, human_approval_required, task_id)
    router = _make_router(max_turns, max_stalls, enable_reflection)

    g: StateGraph = StateGraph(AgentRunState)
    g.add_node("call_llm", call_llm)
    g.add_node("execute_tools", execute_tools_node)

    if enable_planning:
        g.add_node("planner_node", _make_planner_node(haiku, task_description))
    if enable_memory:
        g.add_node("memory_hook_node", _make_memory_hook_node(task_description, repo_path))
    if enable_reflection:
        g.add_node("reflection_node", _make_reflection_node(model))

    # --- Entry point ---
    if enable_planning and enable_memory:
        g.set_entry_point("planner_node")
        g.add_edge("planner_node", "memory_hook_node")
        g.add_edge("memory_hook_node", "call_llm")
    elif enable_planning:
        g.set_entry_point("planner_node")
        g.add_edge("planner_node", "call_llm")
    elif enable_memory:
        g.set_entry_point("memory_hook_node")
        g.add_edge("memory_hook_node", "call_llm")
    else:
        g.set_entry_point("call_llm")

    # --- Router edges from call_llm ---
    if enable_reflection:
        g.add_conditional_edges(
            "call_llm", router,
            {"reflection_node": "reflection_node", "execute_tools": "execute_tools", END: END},
        )
        # reflection runs after call_llm (when tools present), then execute_tools
        g.add_edge("reflection_node", "execute_tools")
    else:
        g.add_conditional_edges(
            "call_llm", router,
            {"execute_tools": "execute_tools", END: END},
        )

    # --- After execute_tools: loop back to call_llm ---
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
    # Fleet OS flags — enabled by default (Day 0, 2026-07-16)
    enable_planning: bool = True,
    enable_memory: bool = True,
    enable_reflection: bool = True,
    enable_lesson: bool = True,
    task_description: str = "",
    repo_path: str = "",
    model_haiku: str = "",
    context_token_budget: int = 60_000,
    max_stalls: int = 3,
    trace_id: str = "",
    task_id: str = "",
) -> AgentRunState:
    """Build + run the agent graph, return the final state.

    All Fleet OS flags default to True. Callers can pass False to opt out.
    Settings-based defaults for model_haiku and repo_path when not provided.
    """
    import uuid as _uuid

    tid = trace_id or _uuid.uuid4().hex[:12]

    # Day 5A: ModelRouter wins over passed-in model — router is source of truth.
    # Agents pass model=settings.model_coder as a fallback; router overrides per role_name.
    try:
        from app.fleet.model_router import get_model_router as _get_router
        _rc = _get_router().route(role_name)
        model = _rc.model
        logger.debug("ModelRouter: %s → %s (tier=%s)", role_name, model, _rc.tier)
    except Exception:
        pass  # Keep caller-provided model as fallback

    # Wire settings-based defaults when not explicitly provided (Day 0)
    if not model_haiku:
        try:
            from app.fleet.model_router import get_model_router as _get_router
            _haiku_agents = _get_router().agents_by_tier("haiku")
            model_haiku = _get_router().model_for(_haiku_agents[0]) if _haiku_agents else model
        except Exception:
            try:
                from app.config import get_settings as _gs
                model_haiku = _gs().model_router
            except Exception:
                model_haiku = model
    if not repo_path:
        try:
            from app.config import get_settings as _gs
            repo_path = _gs().target_repo_path
        except Exception:
            repo_path = ""

    # Fleet OS metrics span (non-fatal if fleet not wired)
    _span: Any = None
    try:
        from app.fleet.metrics import run_span
        _span = run_span(role_name, task_id="", trace_id=tid)
        _span.__enter__()
    except Exception:
        _span = None

    # Lifecycle: agent transitions to RUNNING + emits TaskStarted (Gap 7 / Gap 10)
    try:
        from app.fleet.agent_registry import get_agent_registry
        from app.fleet.fleet_events import publish, task_started
        _reg = get_agent_registry()
        if _reg.get(role_name) is not None:
            _reg.start_task(role_name, task_id=tid)
        publish(task_started(task_id=tid, agent_name=role_name, trace_id=tid))
    except Exception:
        pass

    try:
        graph = build_agent_graph(
            role_name=role_name,
            model=model,
            tools=tools,
            tool_handlers=tool_handlers,
            verification_cfg=verification_cfg,
            human_approval_required=human_approval_required,
            max_turns=max_turns,
            enable_planning=enable_planning,
            enable_memory=enable_memory,
            enable_reflection=enable_reflection,
            task_description=task_description or initial_message,
            repo_path=repo_path,
            model_haiku=model_haiku,
            context_token_budget=context_token_budget,
            max_stalls=max_stalls,
            task_id=task_id,
        )

        initial_state: AgentRunState = {
            # Original 8 required fields
            "messages": [{"role": "user", "content": initial_message}],
            "verification": dict(verification_cfg.initial),
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
            # New Fleet OS fields with safe defaults
            "plan": "",
            "facts": "",
            "n_stalls": 0,
            "retry_count": 0,
            "confidence": 1.0,
            "status": "running",
            "trace_id": tid,
            "memory_context": "",
            "repo_context": "",
        }

        final_state: AgentRunState = graph.invoke(initial_state)  # type: ignore[assignment]

        # Post-graph lesson extraction (non-fatal, runs after graph completes)
        if enable_lesson and final_state.get("submitted"):
            _extract_and_store_lesson(final_state, role_name, model_haiku or model, trace_id=tid)

        if _span is not None:
            _span.__exit__(None, None, None)

        # Push done or stopped event to activity stream (non-fatal)
        if task_id:
            try:
                from app.services.activity_stream import push_done, push_stopped
                tok_in = final_state.get("tokens_in", 0)
                tok_out = final_state.get("tokens_out", 0)
                if final_state.get("status") == "stopped":
                    push_stopped(task_id, checkpoint_id=tid, tokens_in=tok_in, tokens_out=tok_out)
                else:
                    push_done(task_id, final_state.get("result", {}), tok_in, tok_out)
            except Exception:
                pass

        # Lifecycle: SLEEP + events (Gap 7 / Gap 10) — runs after span closes, always
        try:
            from app.fleet.agent_registry import get_agent_registry
            from app.fleet.fleet_events import publish, task_completed, health_updated
            _reg = get_agent_registry()
            if _reg.get(role_name) is not None:
                _reg.complete_task(role_name)  # → AgentState.SLEEP
            publish(task_completed(task_id=tid, agent_name=role_name, trace_id=tid))
            publish(health_updated(role_name, health="healthy", state="sleep", trace_id=tid))
        except Exception:
            pass

        return final_state

    except Exception as exc:
        # Push error event to activity stream (non-fatal)
        if task_id:
            try:
                from app.services.activity_stream import push_error
                push_error(task_id, str(exc)[:500])
            except Exception:
                pass

        # Lifecycle: agent transitions to ERROR on unhandled exception (Gap 7)
        try:
            from app.fleet.agent_registry import get_agent_registry
            from app.fleet.fleet_events import publish, task_failed
            _reg = get_agent_registry()
            if _reg.get(role_name) is not None:
                _reg.fail_task(role_name, reason=str(exc))
            publish(task_failed(task_id=tid, agent_name=role_name, reason=str(exc)[:200], trace_id=tid))
        except Exception:
            pass

        if _span is not None:
            try:
                _span.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
        raise
