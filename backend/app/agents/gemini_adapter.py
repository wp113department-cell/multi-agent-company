"""Gemini API adapter — translates Anthropic SDK tool-use format to the
google-genai SDK's format.

TEMPORARY, easily removable — 2026-09-28, added purely as a second free-
tier testing backend alongside app/agents/groq_adapter.py (same reason:
no Anthropic balance to test against). Production always runs on
Anthropic; this exists only until a real key is available. Mirrors
groq_adapter.py's own shape exactly so it can be removed the same way:
delete this file, app/agents/base.py's _run_via_gemini() + its branch in
run_agent(), the `use_gemini`/`gemini_*` settings in app/config.py, the
`or _gs().use_gemini` clause in app/agents/base_graph.py's Groq-bypass
block, tests/gemini_compat.py, and tests/test_day0_gemini_integration.py.

Used when USE_GEMINI=true in settings:
  - System prompt goes as `system_instruction` in GenerateContentConfig
    (Gemini has no separate system message in `contents`).
  - Anthropic's `input_schema` (standard lowercase-type JSON Schema) is
    passed straight through as a FunctionDeclaration's `parameters` — the
    google-genai SDK accepts it as-is, no OpenAPI-Type-enum conversion
    needed (verified live before writing this).
  - Assistant turns become role="model"; tool_use blocks become
    `function_call` Parts.
  - tool_result blocks become role="user" `function_response` Parts.
  - No prompt caching (cache tokens always return 0/None), same posture
    as groq_adapter.py.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _register() -> None:
    """Lightweight agent_registry entry only — same posture as
    groq_adapter.py's own _register(): a translation utility, not a
    task-running agent."""
    try:
        from app.fleet.agent_registry import get_agent_registry

        get_agent_registry().register("gemini_adapter", kind="infra_utility")
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()


def _anthropic_model_to_gemini(model: str, settings: Any) -> str:
    """Map an Anthropic model name to the equivalent Gemini model —
    mirrors groq_adapter._anthropic_model_to_groq() exactly."""
    coder: str = settings.gemini_model_coder
    planner: str = settings.gemini_model_planner
    router: str = settings.gemini_model_router
    if model == settings.model_coder:
        return coder
    if model == settings.model_planner:
        return planner
    if model == settings.model_router:
        return router
    if "sonnet" in model.lower() or "opus" in model.lower():
        return coder
    if "haiku" in model.lower():
        return router
    return planner


def _to_gemini_tools(tools: list[dict[str, Any]]) -> Any:
    """Convert Anthropic tool defs to a single google.genai Tool with one
    FunctionDeclaration per tool. `input_schema` is passed through as
    `parameters` unchanged (verified live: the SDK accepts standard
    lowercase-type JSON Schema directly, no enum conversion needed)."""
    from google.genai import types

    declarations = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("input_schema", {"type": "object", "properties": {}}),
        )
        for t in tools
    ]
    return types.Tool(function_declarations=declarations)


def _build_gemini_contents(messages: list[dict[str, Any]]) -> list[Any]:
    """Build the google.genai `contents` list from Anthropic-shaped
    messages. The system prompt is NOT included here — Gemini takes it
    separately as `system_instruction`."""
    from google.genai import types

    contents: list[Any] = []

    # Anthropic's tool_result blocks only carry `tool_use_id` (the id of
    # the tool_use block they answer), never the function's own name —
    # but Gemini's FunctionResponse correlates by `name`, not by id. Build
    # a tool_use_id -> name lookup across the whole history up front so
    # each function_response part below gets the REAL function name, not
    # a placeholder — required for the model to know which result answers
    # which call, especially when a turn makes more than one tool call.
    id_to_name: dict[str, str] = {}
    for msg in messages:
        if msg["role"] != "assistant":
            continue
        blocks = msg["content"]
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if hasattr(block, "type") and block.type == "tool_use":
                id_to_name[block.id] = block.name
            elif isinstance(block, dict) and block.get("type") == "tool_use":
                id_to_name[block["id"]] = block["name"]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "assistant":
            parts: list[Any] = []
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type"):
                        if block.type == "text" and block.text:
                            parts.append(types.Part(text=block.text))
                        elif block.type == "tool_use":
                            parts.append(
                                types.Part(
                                    function_call=types.FunctionCall(
                                        name=block.name, args=dict(block.input)
                                    )
                                )
                            )
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(types.Part(text=block.get("text", "")))
                        elif block.get("type") == "tool_use":
                            parts.append(
                                types.Part(
                                    function_call=types.FunctionCall(
                                        name=block["name"],
                                        args=dict(block.get("input", {})),
                                    )
                                )
                            )
            else:
                parts.append(types.Part(text=str(content)))
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif role == "user":
            parts = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        tool_use_id = block.get("tool_use_id", "")
                        fn_name = id_to_name.get(tool_use_id, "unknown_tool")
                        parts.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=fn_name,
                                    response={"result": str(result_content)},
                                )
                            )
                        )
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(types.Part(text=block.get("text", "")))
            else:
                parts.append(types.Part(text=str(content)))
            if parts:
                contents.append(types.Content(role="user", parts=parts))

    return contents


class _GeminiToolUse:
    """Minimal stub mirroring Anthropic's tool_use content block — same
    shape as groq_adapter._GroqToolUse."""

    type = "tool_use"

    def __init__(self, call: Any, call_id: str) -> None:
        self.id = call_id
        self.name = call.name
        self.input: dict[str, Any] = dict(call.args) if call.args else {}


class _GeminiTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _GeminiUsage:
    def __init__(self, tokens_in: int, tokens_out: int) -> None:
        self.input_tokens = tokens_in
        self.output_tokens = tokens_out
        self.cache_read_input_tokens: int | None = None
        self.cache_creation_input_tokens: int | None = None


class _GeminiResponse:
    """Minimal stub mirroring Anthropic's Message response — same shape
    as groq_adapter._GroqResponse."""

    def __init__(self, candidate: Any, tokens_in: int, tokens_out: int) -> None:
        import uuid

        content: list[Any] = []
        has_tool_call = False
        parts = candidate.content.parts if candidate.content else []
        for part in parts or []:
            if getattr(part, "text", None):
                content.append(_GeminiTextBlock(part.text))
            elif getattr(part, "function_call", None) is not None:
                # A random id, not a per-response counter: run_gemini() is
                # called fresh each turn with no shared state, and
                # _build_gemini_contents() above builds its tool_use_id ->
                # name lookup across the WHOLE message history — a
                # counter that resets to 1 each call would collide across
                # turns and could map a tool_result to the wrong
                # function's name.
                call_id = f"gemini_call_{uuid.uuid4().hex[:8]}"
                content.append(_GeminiToolUse(part.function_call, call_id))
                has_tool_call = True

        self.content = content
        # Gemini's finish_reason doesn't reliably distinguish "stopped to
        # call a tool" the way Anthropic's stop_reason does (a real
        # response was observed with finish_reason=STOP alongside a
        # function_call part) — so this is derived from the parts
        # themselves, not the raw finish_reason.
        self.stop_reason = "tool_use" if has_tool_call else "end_turn"
        self.usage = _GeminiUsage(tokens_in, tokens_out)


def run_gemini(
    *,
    system_prompt: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int = 4096,
) -> "_GeminiResponse":
    """Call the Gemini API and return a response object that looks like
    Anthropic's — mirrors groq_adapter.run_groq()'s exact signature and
    retry/circuit-breaker shape.

    Retries up to `settings.gemini_max_retries` times with linear backoff
    on real 429 rate-limit errors, same posture as run_groq().
    """
    import time

    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    from app.config import get_settings
    from app.fleet.circuit_breaker import CircuitBreakerOpenError, get_gemini_breaker

    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    gemini_model = _anthropic_model_to_gemini(model, settings)
    gemini_tools = [_to_gemini_tools(tools)] if tools else []

    contents = _build_gemini_contents(messages)
    config = types.GenerateContentConfig(
        tools=gemini_tools or None,
        system_instruction=system_prompt,
        max_output_tokens=max_tokens,
    )

    max_retries = settings.gemini_max_retries
    breaker = get_gemini_breaker()
    response = None
    for attempt in range(max_retries):
        if not breaker.allow():
            raise CircuitBreakerOpenError(breaker.open_error_message())
        try:
            response = client.models.generate_content(
                model=gemini_model, contents=contents, config=config
            )
            breaker.record_success()
            break
        except genai_errors.ClientError as exc:
            if exc.code == 429:
                breaker.record_failure()
                if attempt < max_retries - 1:
                    wait = 30 * (attempt + 1)
                    logger.warning(
                        "Gemini rate limit (attempt %d/%d) — sleeping %ds: %s",
                        attempt + 1,
                        max_retries,
                        wait,
                        exc,
                    )
                    time.sleep(wait)
                    continue
                raise
            breaker.record_failure()
            raise
        except Exception:
            breaker.record_failure()
            raise

    assert response is not None  # loop always either breaks with a response or raises
    candidate = response.candidates[0]
    usage = response.usage_metadata
    tokens_in = usage.prompt_token_count if usage else 0
    tokens_out = usage.candidates_token_count if usage else 0

    logger.debug(
        "Gemini call: model=%s tokens_in=%d tokens_out=%d finish=%s",
        gemini_model,
        tokens_in,
        tokens_out,
        candidate.finish_reason,
    )
    return _GeminiResponse(candidate, tokens_in, tokens_out)
