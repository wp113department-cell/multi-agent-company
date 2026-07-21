"""
TEMPORARY Groq compatibility shim for testing (Day 0, 2026-07-16).
===================================================================
Purpose: lets real-LLM tests run against Groq while ANTHROPIC_API_KEY is unavailable.
         The main production code (base_graph.py) is UNCHANGED — still pure Anthropic.

HOW IT WORKS:
  - Patches `anthropic.Anthropic` at the class level so every `.messages.create()` call
    inside base_graph.py nodes is intercepted and forwarded to Groq instead.
  - The Groq response is wrapped in a duck-type shim so _serialize_content() works identically.

HOW TO REMOVE (when you get Anthropic API key):
  1. Delete this file (tests/groq_compat.py)
  2. Delete tests/test_day0_groq_integration.py
  3. Done — all other tests already mock the LLM anyway.

USAGE IN TESTS:
  from tests.groq_compat import groq_llm_patch

  def test_something(groq_llm_patch):   # fixture auto-patches anthropic
      result = run_agent_graph(...)      # calls Groq transparently
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Groq → Anthropic response shim
# Wraps Groq's response so _serialize_content() sees the same shape as Anthropic
# ---------------------------------------------------------------------------

class _ShimTextBlock:
    type = "text"
    def __init__(self, text: str) -> None:
        self.text = text


class _ShimToolUse:
    type = "tool_use"
    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input


class _ShimUsage:
    def __init__(self, inp: int, out: int) -> None:
        self.input_tokens = inp
        self.output_tokens = out


def _clean_text(raw: str) -> str:
    """Strip <think>...</think> blocks and markdown code fences from model output.

    qwen3 / llama models sometimes wrap JSON in ```json...``` or emit <think> prefixes.
    This normalises the text so json.loads() works the same as with Anthropic responses.
    """
    import re
    # Remove <think>...</think> blocks (including empty ones)
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return text.strip()


class _ShimResponse:
    """Duck-type Anthropic Message → wraps a Groq _GroqResponse."""
    def __init__(self, groq_resp: Any) -> None:
        self.content: list[Any] = []
        self.usage = _ShimUsage(
            groq_resp.usage.input_tokens,
            groq_resp.usage.output_tokens,
        )
        for block in groq_resp.content:
            if getattr(block, "type", None) == "text":
                self.content.append(_ShimTextBlock(_clean_text(block.text)))
            elif getattr(block, "type", None) == "tool_use":
                self.content.append(_ShimToolUse(block.id, block.name, block.input))


# ---------------------------------------------------------------------------
# Fake Anthropic client backed by Groq
# ---------------------------------------------------------------------------

def _make_groq_backed_anthropic(groq_api_key: str) -> Any:
    """Return a fake anthropic.Anthropic() instance whose .messages.create() calls Groq."""
    from app.agents.groq_adapter import run_groq
    from app.config import get_settings

    settings = get_settings()  # noqa: F841

    def _messages_create(
        *,
        model: str,
        max_tokens: int = 1024,
        messages: Any = None,
        system: Any = None,
        tools: Any = None,
        **kwargs: Any,
    ) -> _ShimResponse:
        # Extract system prompt string from Anthropic-format system block
        sys_prompt = ""
        if isinstance(system, list) and system:
            sys_prompt = system[0].get("text", "") if isinstance(system[0], dict) else ""
        elif isinstance(system, str):
            sys_prompt = system

        # Convert anthropic.types.ToolParam (TypedDict) to plain dicts for run_groq
        plain_tools: list[dict[str, Any]] = []
        if tools:
            for t in tools:
                if isinstance(t, dict):
                    plain_tools.append(t)
                else:
                    plain_tools.append({
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "input_schema": t["input_schema"],
                    })

        # Convert Anthropic messages format to plain dicts
        plain_msgs: list[dict[str, Any]] = []
        if messages:
            for m in messages:
                if isinstance(m, dict):
                    plain_msgs.append(m)
                else:
                    plain_msgs.append({"role": m.role, "content": str(m.content)})

        groq_resp = run_groq(
            system_prompt=sys_prompt,
            model=model,
            messages=plain_msgs,
            tools=plain_tools,
            max_tokens=max_tokens,
        )
        return _ShimResponse(groq_resp)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = _messages_create
    return fake_client


# ---------------------------------------------------------------------------
# pytest fixture — use in any test that needs a real LLM call via Groq
# ---------------------------------------------------------------------------

@pytest.fixture
def groq_llm_patch():
    """Patch anthropic.Anthropic so base_graph nodes call Groq instead.

    Skip automatically when GROQ_API_KEY is not set.
    Remove this fixture (and this file) once ANTHROPIC_API_KEY is available.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        pytest.skip("GROQ_API_KEY not set — skipping real-LLM test")

    # Temporarily set USE_GROQ env var so get_settings() picks it up
    os.environ["USE_GROQ"] = "true"
    os.environ["GROQ_API_KEY"] = groq_key

    fake_client = _make_groq_backed_anthropic(groq_key)

    with patch("app.agents.base_graph.anthropic.Anthropic", return_value=fake_client):
        yield fake_client

    # Cleanup
    os.environ.pop("USE_GROQ", None)
