"""
TEMPORARY Gemini compatibility shim for testing (2026-09-28).
===============================================================
Purpose: lets real-LLM tests run against Gemini (a second free-tier
         backend, alongside tests/groq_compat.py) while ANTHROPIC_API_KEY
         is unavailable / Groq's own rate limit is too tight. The main
         production code (base_graph.py) is UNCHANGED by this file — still
         pure Anthropic; only test-time behavior is patched.

HOW IT WORKS: identical shape to tests/groq_compat.py — patches
  `anthropic.Anthropic` at the class level so every `.messages.create()`
  call inside base_graph.py nodes is intercepted and forwarded to Gemini
  instead. The Gemini response is wrapped in a duck-type shim so
  _serialize_content() works identically.

HOW TO REMOVE (once a real Anthropic key is available, alongside removing
Groq's own equivalent — see app/agents/gemini_adapter.py's own docstring
for the full removal list):
  1. Delete this file (tests/gemini_compat.py)
  2. Delete tests/test_day0_gemini_integration.py
  3. Done — all other tests already mock the LLM anyway.

USAGE IN TESTS:
  from tests.gemini_compat import gemini_llm_patch

  def test_something(gemini_llm_patch):   # fixture auto-patches anthropic
      result = run_agent_graph(...)        # calls Gemini transparently
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Gemini → Anthropic response shim
# Wraps Gemini's response so _serialize_content() sees the same shape as
# Anthropic — mirrors tests/groq_compat.py's own _ShimResponse exactly.
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


class _ShimResponse:
    """Duck-type Anthropic Message → wraps a Gemini _GeminiResponse."""

    def __init__(self, gemini_resp: Any) -> None:
        self.content: list[Any] = []
        self.usage = _ShimUsage(
            gemini_resp.usage.input_tokens,
            gemini_resp.usage.output_tokens,
        )
        for block in gemini_resp.content:
            if getattr(block, "type", None) == "text":
                self.content.append(_ShimTextBlock(block.text))
            elif getattr(block, "type", None) == "tool_use":
                self.content.append(_ShimToolUse(block.id, block.name, block.input))


# ---------------------------------------------------------------------------
# Fake Anthropic client backed by Gemini
# ---------------------------------------------------------------------------


def _make_gemini_backed_anthropic(gemini_api_key: str) -> Any:
    """Return a fake anthropic.Anthropic() instance whose .messages.create()
    calls Gemini instead — mirrors groq_compat._make_groq_backed_anthropic()
    exactly."""
    from app.agents.gemini_adapter import run_gemini

    def _messages_create(
        *,
        model: str,
        max_tokens: int = 1024,
        messages: Any = None,
        system: Any = None,
        tools: Any = None,
        **kwargs: Any,
    ) -> _ShimResponse:
        sys_prompt = ""
        if isinstance(system, list) and system:
            sys_prompt = (
                system[0].get("text", "") if isinstance(system[0], dict) else ""
            )
        elif isinstance(system, str):
            sys_prompt = system

        plain_tools: list[dict[str, Any]] = []
        if tools:
            for t in tools:
                if isinstance(t, dict):
                    plain_tools.append(t)
                else:
                    plain_tools.append(
                        {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "input_schema": t["input_schema"],
                        }
                    )

        plain_msgs: list[dict[str, Any]] = []
        if messages:
            for m in messages:
                if isinstance(m, dict):
                    plain_msgs.append(m)
                else:
                    plain_msgs.append({"role": m.role, "content": str(m.content)})

        gemini_resp = run_gemini(
            system_prompt=sys_prompt,
            model=model,
            messages=plain_msgs,
            tools=plain_tools,
            max_tokens=max_tokens,
        )
        return _ShimResponse(gemini_resp)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = _messages_create
    return fake_client


# ---------------------------------------------------------------------------
# pytest fixture — use in any test that needs a real LLM call via Gemini
# ---------------------------------------------------------------------------


@pytest.fixture
def gemini_llm_patch():
    """Patch anthropic.Anthropic so base_graph nodes call Gemini instead.

    Skip automatically when GEMINI_API_KEY is not set.
    Remove this fixture (and this file) once ANTHROPIC_API_KEY is available.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        pytest.skip("GEMINI_API_KEY not set — skipping real-LLM test")

    os.environ["USE_GEMINI"] = "true"
    os.environ["GEMINI_API_KEY"] = gemini_key

    fake_client = _make_gemini_backed_anthropic(gemini_key)

    with patch("app.agents.base_graph.anthropic.Anthropic", return_value=fake_client):
        yield fake_client

    os.environ.pop("USE_GEMINI", None)
