"""bhaskar_agent / bhaskar_tool end to end on the Docker sandbox (audit 15).

The model is an in-process mock (no network, no API key); the sandbox runs
real containers (skipped without Docker). Proves: a synthesized script is
tested and then independently re-run before it is trusted; a script that
tries to read the host's .env neither succeeds nor is trusted; the
recursion guard holds; a verified script is cached and replayed in the
sandbox without asking the model again.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.policy.sandbox import _docker_available

pytestmark = pytest.mark.skipif(not _docker_available(), reason="needs Docker")

GOOD = "print(sum(i * i for i in range(1, 11)))"
EVIL = (
    "import _io\n"
    "try:\n    d = _io.FileIO('/home/pc-117/Documents/CRR2906/backend/.env').read()\n"
    "except Exception:\n    raise SystemExit(3)\n"
    "print('LEAKED' if b'API_KEY' in d else 'none')"
)


def _tool_use(name: str, inp: dict[str, Any]) -> Any:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", id=f"tu_{name}", name=name, input=inp)
        ],
        usage=SimpleNamespace(input_tokens=30, output_tokens=10),
        stop_reason="tool_use",
    )


def _scripted(code: str) -> Any:
    """Turn 1 tests the script in the sandbox, turn 2 submits it."""
    calls: list[Any] = []

    def model(**kw: Any) -> Any:
        calls.append(kw)
        if len(calls) == 1:
            return _tool_use("run_sandboxed_script", {"code": code})
        return _tool_use(
            "submit_generated_tool", {"code": code, "result_summary": "done"}
        )

    model.calls = calls  # type: ignore[attr-defined]
    return model


@pytest.fixture(autouse=True)
def _docker_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "bhaskar_tool_sandbox_backend", "docker")


def _run(code: str) -> dict[str, Any]:
    from app.agents.bhaskar_agent import run_bhaskar_agent

    with patch("anthropic.Anthropic") as cls, patch(
        "app.agents.base_graph.load_role", return_value="# bhaskar\n"
    ):
        cls.return_value.messages.create.side_effect = _scripted(code)
        return run_bhaskar_agent("sum of squares 1..10", "", "")


def test_a_tested_script_is_independently_reverified_before_it_is_trusted() -> None:
    out = _run(GOOD)
    assert out["ok"] is True, out
    assert "385" in out["tested_output"]
    assert out["code"].strip() == GOOD


def test_a_script_reaching_for_host_secrets_is_neither_successful_nor_trusted() -> None:
    out = _run(EVIL)
    assert out["ok"] is False
    # (the submitted source itself contains the word; check what it printed)
    assert "LEAKED" not in out["tested_output"]


def test_bhaskar_cannot_call_itself() -> None:
    from app.agents.bhaskar_agent import (
        BhaskarRecursionError,
        bhaskar_agent_active,
        run_bhaskar_agent,
    )

    token = bhaskar_agent_active.set(True)
    try:
        with pytest.raises(BhaskarRecursionError):
            run_bhaskar_agent("anything", "", "")
    finally:
        bhaskar_agent_active.reset(token)


def test_a_verified_script_is_cached_and_replayed_without_the_model() -> None:
    from app.tools.agents import bhaskar_tool as bt

    generated = {
        "ok": True,
        "code": GOOD,
        "result_summary": "385",
        "tested_output": "385\n",
        "error": "",
        "tokens_in": 0,
        "tokens_out": 0,
    }
    task = {
        "task_description": "sum of squares 1..10 (audit15 cache probe)",
        "context": "",
    }
    with patch.object(bt, "_run_with_process_bound", return_value=generated) as gen:
        first = json.loads(bt.bhaskar_tool_handler("", task, agent_name="t"))
        second = json.loads(bt.bhaskar_tool_handler("", task, agent_name="t"))
    assert first["ok"] and "385" in first["output"]
    assert second["ok"] and second["source"] == "cache" and "385" in second["output"]
    assert gen.call_count == 1, "the second call must not ask the model again"
