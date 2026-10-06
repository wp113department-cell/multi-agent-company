"""barot_agent fills a REAL capability gap end to end (audit 15, 2026-10-06).

Before: nothing in the app could ever ask for a capability no agent has —
the delegation allow-list only named covered capabilities — so barot only
ever ran when an existing agent was busy. With "*new*", backend_dev asks
for `csv_schema_inference` (no agent declares it): select() → barot plans a
tool profile → a temporary_agent is spawned, registered, actually runs and
returns → the pool scraps it. The model is an in-process mock (no network,
no API key); everything else is the real code path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.delegation import (
    DelegationNotAllowedError,
    DelegationRequest,
    delegate,
)
from app.config import get_settings
from app.fleet.capability_registry import (
    ensure_all_agents_registered,
    get_capability_registry,
)

GAP = "csv_schema_inference"


def _tool_use(name: str, inp: dict[str, Any]) -> Any:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", id=f"tu_{name}", name=name, input=inp)
        ],
        usage=SimpleNamespace(input_tokens=30, output_tokens=10),
        stop_reason="tool_use",
    )


class _Model:
    """barot's planning call → a tool profile (asks for write_file too, which
    must be refused); the temporary agent's own run → its submit tool."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> Any:
        self.calls.append(kw)
        if (kw.get("tool_choice") or {}).get("name") == "plan_tool_profile":
            return _tool_use(
                "plan_tool_profile",
                {
                    "tool_names": ["read_file", "search_code", "write_file"],
                    "briefing": "Infer column names and types of data.csv.",
                },
            )
        submit = next(
            t["name"] for t in kw.get("tools") or [] if t["name"].startswith("submit")
        )
        return _tool_use(
            submit,
            {
                "summary": "data.csv has columns id:int, name:str",
                "findings": [],
                "verified": True,
            },
        )


def _request(**kw: Any) -> DelegationRequest:
    base: dict[str, Any] = dict(
        source_agent="backend_dev",
        target_capability=GAP,
        objective="Infer the schema of data.csv",
        context="",
        ancestry=("backend_dev",),
        delegation_depth=0,
        budget_remaining_usd=1.0,
        task_id="9150",
        repo_path="",
    )
    base.update(kw)
    return DelegationRequest(**base)


def test_a_new_capability_is_filled_by_a_read_only_temporary_agent(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data.csv").write_text("id,name\n1,a\n")
    monkeypatch.setattr(get_settings(), "barot_agent_enabled", True)
    monkeypatch.setattr(get_settings(), "delegation_enabled", True)
    ensure_all_agents_registered()
    assert not get_capability_registry().find_by_capability(GAP), "must be a real gap"

    model = _Model()
    granted: list[list[str]] = []
    import app.agents.temporary_agent as ta

    real_resolve = ta.make_temporary_agent_tools_and_handlers

    def spy(**kw: Any) -> Any:
        specs, handlers = real_resolve(**kw)
        granted.append([t["name"] for t in specs])
        return specs, handlers

    with patch("anthropic.Anthropic") as cls, patch.object(
        ta, "make_temporary_agent_tools_and_handlers", spy
    ):
        cls.return_value.messages.create.side_effect = model
        result = delegate(_request(repo_path=str(tmp_path)))

    assert result.success, result
    assert result.target_agent and result.target_agent.startswith("temporary_agent")
    assert granted and "write_file" not in granted[0] and "read_file" in granted[0]
    assert any(
        (c.get("tool_choice") or {}).get("name") == "plan_tool_profile"
        for c in model.calls
    )
    # torn down after its one task
    assert not get_capability_registry().find_by_capability(GAP)


def test_a_covered_capability_still_needs_an_explicit_allow_entry() -> None:
    with pytest.raises(DelegationNotAllowedError):
        delegate(_request(target_capability="code_review"))
