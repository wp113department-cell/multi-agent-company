"""Shared agent runner — every LangGraph agent node calls run_agent()."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import anthropic

from app.config import get_settings
from app.policy.engine import check_command, check_path

logger = logging.getLogger(__name__)

_ROLES_DIR = Path(__file__).parent.parent.parent / "roles"


def load_role(name: str) -> str:
    path = _ROLES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Role file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


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
) -> tuple[str, int, int]:
    """
    Run an agent loop until end_turn or tool_use exhausted.

    Returns (final_text, tokens_in, tokens_out).
    on_heartbeat() called every 5 tool calls.
    on_tool_call(name, input, result) called after each tool execution.
    """
    settings = get_settings()
    client = _make_client()
    system_prompt = load_role(role_name)

    total_in = 0
    total_out = 0
    tool_call_count = 0
    final_text = ""

    # Build anthropic tool specs from our dict format
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

        # Collect text and tool_use blocks
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                final_text = block.text
            elif block.type == "tool_use":
                tool_uses.append(block)

        # Append assistant message
        current_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn" or not tool_uses:
            break

        # Process tool calls
        tool_results = []
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

            if on_tool_call:
                on_tool_call(tu.name, dict(tu.input), result_content)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": str(result_content),
            })

        current_messages.append({"role": "user", "content": tool_results})

    return final_text, total_in, total_out
