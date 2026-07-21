"""Shared agent runner — every LangGraph agent node calls run_agent()."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import anthropic

from app.config import get_settings
from app.policy.engine import check_command, check_path

logger = logging.getLogger(__name__)

_ROLES_DIR = Path(__file__).parent.parent.parent / "roles"

# Runtime API key override — set by load_api_key_override() at startup.
# DB-stored key takes precedence over the env var.
_api_key_override: str = ""


def set_api_key_override(key: str) -> None:
    """Called at startup (and after UI key save) to override the env-var API key."""
    global _api_key_override
    _api_key_override = key.strip()
    logger.info("Anthropic API key override loaded from DB")


def get_effective_api_key() -> str:
    """Return DB-stored key if set, else fall back to env var."""
    return _api_key_override or get_settings().anthropic_api_key


_GLOBAL_STANDARDS_PATH = _ROLES_DIR / "_GLOBAL_STANDARDS.md"


def load_role(name: str) -> str:
    path = _ROLES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Role file not found: {path}")
    role_text = path.read_text(encoding="utf-8").strip()
    if _GLOBAL_STANDARDS_PATH.exists():
        global_text = _GLOBAL_STANDARDS_PATH.read_text(encoding="utf-8").strip()
        return f"{global_text}\n\n---\n\n{role_text}"
    return role_text


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_effective_api_key())


def _enforce_policy(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Return denial reason if tool call is policy-denied, else None."""
    if tool_name in ("write_file", "edit_file"):
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


def run_agent(
    *,
    role_name: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_handlers: dict[str, Any],
    max_turns: int = 20,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> tuple[str, int, int, int, int]:
    """
    Run an agent loop until end_turn or tool_use exhausted.

    Returns (final_text, tokens_in, tokens_out, cache_read_tokens, cache_creation_tokens).
    on_heartbeat() called every 5 tool calls.
    on_tool_call(name, input, result) called after each tool execution.

    Backend is selected by USE_GROQ setting:
      False (default) → Anthropic SDK (prompt caching enabled)
      True            → Groq (OpenAI-compatible, no prompt caching)
    """
    settings = get_settings()
    if settings.use_groq:
        return _run_via_groq(
            role_name=role_name,
            model=model,
            messages=messages,
            tools=tools,
            tool_handlers=tool_handlers,
            max_turns=max_turns,
            on_heartbeat=on_heartbeat,
            on_tool_call=on_tool_call,
        )
    return _run_via_anthropic(
        role_name=role_name,
        model=model,
        messages=messages,
        tools=tools,
        tool_handlers=tool_handlers,
        max_turns=max_turns,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )


def _run_via_anthropic(
    *,
    role_name: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_handlers: dict[str, Any],
    max_turns: int,
    on_heartbeat: Any,
    on_tool_call: Any,
) -> tuple[str, int, int, int, int]:
    client = _make_client()
    system_prompt = load_role(role_name)

    total_in = 0
    total_out = 0
    total_cache_read = 0
    total_cache_creation = 0
    tool_call_count = 0
    final_text = ""

    anthropic_tools: list[anthropic.types.ToolParam] = [
        anthropic.types.ToolParam(
            name=t["name"],
            description=t.get("description", ""),
            input_schema=t["input_schema"],
        )
        for t in tools
    ]

    current_messages = list(messages)

    for _ in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=current_messages,  # type: ignore[arg-type]
            tools=anthropic_tools,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        total_cache_read += response.usage.cache_read_input_tokens or 0
        total_cache_creation += response.usage.cache_creation_input_tokens or 0

        tool_uses = []
        for block in response.content:
            if block.type == "text":
                final_text = block.text
            elif block.type == "tool_use":
                tool_uses.append(block)

        current_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn" or not tool_uses:
            break

        tool_results = []
        _submitted = False
        for tu in tool_uses:
            tool_call_count += 1
            if tool_call_count % 5 == 0 and on_heartbeat:
                on_heartbeat()

            denial = _enforce_policy(tu.name, dict(tu.input))
            if denial:
                result_content = f"[POLICY DENIED] {denial}"
                logger.warning("Policy denied tool %s: %s", tu.name, denial)
            else:
                handler = tool_handlers.get(tu.name)
                if handler is None:
                    result_content = f"[ERROR] Unknown tool: {tu.name}"
                else:
                    try:
                        result_content = handler(dict(tu.input))
                    except Exception as e:
                        result_content = f"[ERROR] {tu.name} failed: {e}"
                        logger.exception("Tool %s raised", tu.name)
                if tu.name.startswith("submit_"):
                    _submitted = True

            if on_tool_call:
                on_tool_call(tu.name, dict(tu.input), result_content)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": str(result_content),
                }
            )

        current_messages.append({"role": "user", "content": tool_results})
        if _submitted:
            break

    return final_text, total_in, total_out, total_cache_read, total_cache_creation


def _run_via_groq(
    *,
    role_name: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_handlers: dict[str, Any],
    max_turns: int,
    on_heartbeat: Any,
    on_tool_call: Any,
) -> tuple[str, int, int, int, int]:
    from app.agents.groq_adapter import run_groq

    system_prompt = load_role(role_name)

    total_in = 0
    total_out = 0
    tool_call_count = 0
    final_text = ""

    current_messages = list(messages)
    _nudge_count = 0

    for _ in range(max_turns):
        response = run_groq(
            system_prompt=system_prompt,
            model=model,
            messages=current_messages,
            tools=tools,
            max_tokens=4096,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        tool_uses = []
        for block in response.content:
            if block.type == "text":
                final_text = block.text
            elif block.type == "tool_use":
                tool_uses.append(block)

        current_messages.append({"role": "assistant", "content": response.content})

        if not tool_uses:
            # Model returned no tool calls — nudge it up to 2 times before giving up.
            if _nudge_count >= 2:
                logger.warning("Model skipped tools %d times — giving up", _nudge_count)
                break
            _nudge_count += 1
            logger.warning(
                "Groq returned no tool calls (stop=%s, nudge %d/2) — retrying",
                response.stop_reason,
                _nudge_count,
            )
            current_messages.append(
                {
                    "role": "user",
                    "content": "You must call one of the provided tools to complete this task. Do not respond with text — call the appropriate tool now.",
                }
            )
            continue

        _nudge_count = 0  # reset on successful tool call

        tool_results = []
        _submitted = False
        for tu in tool_uses:
            tool_call_count += 1
            if tool_call_count % 5 == 0 and on_heartbeat:
                on_heartbeat()

            denial = _enforce_policy(tu.name, dict(tu.input))
            if denial:
                result_content = f"[POLICY DENIED] {denial}"
                logger.warning("Policy denied tool %s: %s", tu.name, denial)
            else:
                handler = tool_handlers.get(tu.name)
                if handler is None:
                    result_content = f"[ERROR] Unknown tool: {tu.name}"
                else:
                    try:
                        result_content = handler(dict(tu.input))
                    except Exception as e:
                        result_content = f"[ERROR] {tu.name} failed: {e}"
                        logger.exception("Tool %s raised", tu.name)
                if tu.name.startswith("submit_"):
                    _submitted = True

            if on_tool_call:
                on_tool_call(tu.name, dict(tu.input), result_content)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": str(result_content),
                }
            )

        current_messages.append({"role": "user", "content": tool_results})
        if _submitted:
            break

    return final_text, total_in, total_out, 0, 0
