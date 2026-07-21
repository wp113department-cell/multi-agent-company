"""Groq API adapter — translates Anthropic SDK tool-use format to Groq/OpenAI format.

Used when USE_GROQ=true in settings. Groq uses an OpenAI-compatible API so:
  - System prompt goes as first message {role: "system", content: "..."}
  - Tools use {"type": "function", "function": {"name", "description", "parameters"}}
  - Tool calls come back in choice.message.tool_calls[i]
  - Tool results go back as {"role": "tool", "tool_call_id": ..., "content": ...}
  - No prompt caching (cache tokens always return 0)

tool_use_failed recovery:
  Some llama models emit function calls in a legacy XML-like format:
    <function=NAME [{"arg": "val"}]</function>
  Groq rejects these with 400 tool_use_failed + a failed_generation field.
  We parse that field and synthesize a proper tool-use response so the agent
  loop can continue without the caller seeing an error.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)


def _register() -> None:
    """Lightweight agent_registry entry only — groq_adapter is a translation
    utility (Anthropic <-> Groq/OpenAI format), not a task-running agent, so it
    carries no AGENT_CONTRACT / capability_registry entry (see
    docs/FLEET_ENHANCEMENT_PLAN.md Day 6 note)."""
    try:
        from app.fleet.agent_registry import get_agent_registry

        get_agent_registry().register("groq_adapter", kind="infra_utility")
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()


def _anthropic_model_to_groq(model: str, settings: Any) -> str:
    """Map an Anthropic model name to the equivalent Groq model."""
    coder: str = settings.groq_model_coder
    planner: str = settings.groq_model_planner
    router: str = settings.groq_model_router
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


def _to_groq_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Anthropic tool defs to OpenAI/Groq function tool format."""
    groq_tools = []
    for t in tools:
        groq_tools.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    # Anthropic calls it input_schema; OpenAI/Groq calls it parameters
                    "parameters": t.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return groq_tools


def _build_groq_messages(
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the Groq messages list (system first, then conversation)."""
    groq_msgs: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "assistant":
            # content may be a list of Anthropic blocks or a plain string
            if isinstance(content, list):
                # Collect text and tool_use blocks
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []

                for block in content:
                    if hasattr(block, "type"):
                        if block.type == "text" and block.text:
                            text_parts.append(block.text)
                        elif block.type == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block.id,
                                    "type": "function",
                                    "function": {
                                        "name": block.name,
                                        "arguments": json.dumps(dict(block.input)),
                                    },
                                }
                            )
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block["id"],
                                    "type": "function",
                                    "function": {
                                        "name": block["name"],
                                        "arguments": json.dumps(block.get("input", {})),
                                    },
                                }
                            )

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": " ".join(text_parts) if text_parts else None,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                groq_msgs.append(assistant_msg)

            else:
                groq_msgs.append({"role": "assistant", "content": str(content)})

        elif role == "user":
            if isinstance(content, list):
                # May contain tool_result blocks
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        groq_msgs.append(
                            {
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": str(block.get("content", "")),
                            }
                        )
                    elif isinstance(block, dict) and block.get("type") == "text":
                        groq_msgs.append(
                            {"role": "user", "content": block.get("text", "")}
                        )
            else:
                groq_msgs.append({"role": "user", "content": str(content)})

    return groq_msgs


class _GroqToolUse:
    """Minimal stub mirroring Anthropic's tool_use content block."""

    def __init__(self, call: Any) -> None:
        self.type = "tool_use"
        self.id = call.id
        self.name = call.function.name
        try:
            self.input: dict[str, Any] = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            self.input = {}


class _GroqTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _GroqResponse:
    """Minimal stub mirroring Anthropic's Message response."""

    def __init__(self, choice: Any, tokens_in: int, tokens_out: int) -> None:
        self._choice = choice
        msg = choice.message

        content: list[Any] = []
        if msg.content:
            content.append(_GroqTextBlock(msg.content))
        for tc in msg.tool_calls or []:
            content.append(_GroqToolUse(tc))

        self.content = content

        # Map Groq finish_reason → Anthropic stop_reason
        fr = choice.finish_reason
        if fr == "tool_calls":
            self.stop_reason = "tool_use"
        else:
            self.stop_reason = "end_turn"

        self.usage = _GroqUsage(tokens_in, tokens_out)


class _GroqUsage:
    def __init__(self, tokens_in: int, tokens_out: int) -> None:
        self.input_tokens = tokens_in
        self.output_tokens = tokens_out
        self.cache_read_input_tokens: int | None = None
        self.cache_creation_input_tokens: int | None = None


# ---------------------------------------------------------------------------
# tool_use_failed recovery helpers
# ---------------------------------------------------------------------------


def _parse_failed_generation(failed_gen: str) -> tuple[str, dict[str, Any]] | None:
    """Parse Groq's failed_generation string to recover function name + args.

    Handles llama legacy format:
      <function=NAME [{"key": "value", ...}]</function>
      <function=NAME {"key": "value"}</function>

    Returns (function_name, args_dict) or None if unparseable.
    """
    name_match = re.match(r"<function=(\w+)", failed_gen)
    if not name_match:
        return None
    fn_name = name_match.group(1)

    # Extract the JSON object — find first { and last }
    start = failed_gen.find("{")
    end = failed_gen.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        args = json.loads(failed_gen[start : end + 1])
        return fn_name, args
    except json.JSONDecodeError:
        return None


def _synthesize_tool_call_response(
    fn_name: str,
    args: dict[str, Any],
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> "_GroqResponse":
    """Build a _GroqResponse that looks like the model made a successful tool call."""
    call_id = f"call_{uuid.uuid4().hex[:8]}"
    fake_tool_call = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=fn_name, arguments=json.dumps(args)),
    )
    fake_choice = SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=[fake_tool_call]),
        finish_reason="tool_calls",
    )
    logger.info(
        "tool_use_failed recovery: synthesised tool call %s with %d args",
        fn_name,
        len(args),
    )
    return _GroqResponse(fake_choice, tokens_in, tokens_out)


def run_groq(
    *,
    system_prompt: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int = 4096,
) -> "_GroqResponse":
    """Call Groq API and return a response object that looks like Anthropic's.

    Retries up to 5 times with exponential backoff on rate-limit errors (413/429).
    """
    import time
    import groq as groq_module  # local import to avoid hard dependency at startup
    from app.config import get_settings

    settings = get_settings()
    client = groq_module.Groq(api_key=settings.groq_api_key)
    groq_model = _anthropic_model_to_groq(model, settings)
    groq_tools = _to_groq_tools(tools) if tools else []

    # qwen3 models default to thinking mode — prepend /no_think to disable it.
    # Without this the model reasons internally then returns stop without calling tools.
    effective_system = system_prompt
    if "qwen3" in groq_model.lower():
        effective_system = "/no_think\n" + system_prompt

    groq_messages = _build_groq_messages(effective_system, messages)

    kwargs: dict[str, Any] = {
        "model": groq_model,
        "messages": groq_messages,
        "max_tokens": max_tokens,
    }
    if groq_tools:
        kwargs["tools"] = groq_tools
        kwargs["tool_choice"] = "auto"

    from app.config import get_settings

    max_retries = get_settings().groq_max_retries
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except groq_module.RateLimitError as exc:
            if attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                logger.warning(
                    "Groq rate limit (attempt %d/%d) — sleeping %ds: %s",
                    attempt + 1,
                    max_retries,
                    wait,
                    exc,
                )
                time.sleep(wait)
            else:
                raise
        except groq_module.BadRequestError as exc:
            body = getattr(exc, "body", {}) or {}
            err = body.get("error", {}) if isinstance(body, dict) else {}
            if err.get("code") == "tool_use_failed":
                failed_gen = err.get("failed_generation", "")
                parsed = _parse_failed_generation(failed_gen) if failed_gen else None
                if parsed:
                    fn_name, args = parsed
                    return _synthesize_tool_call_response(fn_name, args)
                # Could not parse — surface a clear error
                raise RuntimeError(
                    f"Groq tool_use_failed (model={groq_model}): "
                    f"{err.get('message', str(exc))}"
                ) from exc
            raise

    choice = response.choices[0]

    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0

    logger.debug(
        "Groq call: model=%s tokens_in=%d tokens_out=%d stop=%s",
        groq_model,
        tokens_in,
        tokens_out,
        choice.finish_reason,
    )
    return _GroqResponse(choice, tokens_in, tokens_out)
