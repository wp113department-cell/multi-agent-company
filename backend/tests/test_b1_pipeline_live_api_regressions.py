"""Verification batch B1, item #11 (execution pipeline trace) — defects found by
running the REAL pipeline (task -> PM -> Architect -> Decomposer) against the
REAL Anthropic API, none of which any mocked-LLM test could see:

1. `thinking: {"type": "enabled", "budget_tokens": N}` — sent to the opus-tier
   agents (architect/decomposer/planner map to claude-opus-4-8) — is REMOVED on
   Opus 4.7+/Sonnet 5 and answers 400, so the Architect failed on its very first
   call and every task blocked at planning.
2. reflection_node runs between call_llm and execute_tools, so the history ends
   with the assistant's tool_use and no tool_result yet; the reviewer call
   appended a plain user message after it -> 400 ("tool_use ids were found
   without tool_result blocks immediately after") EVERY time, swallowed as
   "non-fatal". Reflection never worked with a real API.
3. Even when told "Respond in JSON only", Claude Haiku returns the JSON inside a
   ```json fence. planner_node (confidence), critique_node and the lesson
   extractor did a bare json.loads() -> "Expecting value: line 1 column 1",
   swallowed: confidence was always the 0.8 default, no critique ever ran, no
   lesson was ever stored.

The fake API below ENFORCES the real tool-pairing rule (confirmed against the
live API) and answers in fenced JSON exactly as the live model does.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agents import base_graph as bg
from app.agents.base_graph import _messages_valid_for_review, _parse_llm_json
from app.fleet.model_router import thinking_param_for

# ------------------------------- thinking ----------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5-1",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "some-future-model",
    ],
)
def test_modern_models_get_adaptive_thinking_never_a_budget(model) -> None:
    assert thinking_param_for(model, 2048) == {"type": "adaptive"}


@pytest.mark.parametrize(
    "model",
    [
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-5",
        "claude-opus-4-1-20250805",
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    ],
)
def test_legacy_models_keep_the_budget_form(model) -> None:
    assert thinking_param_for(model, 2048) == {"type": "enabled", "budget_tokens": 2048}


def test_real_router_routes_opus_agents_to_a_valid_thinking_param() -> None:
    from app.fleet.model_router import get_model_router

    route = get_model_router().route("architect")
    assert route.tier == "opus"
    kw = route.token_kwargs()
    assert "budget_tokens" not in str(kw.get("thinking", {})) or route.model.startswith(
        ("claude-haiku-4-5", "claude-opus-4-5")
    )


def test_no_other_code_path_hardcodes_the_removed_thinking_form() -> None:
    import re
    from pathlib import Path

    hits = []
    for p in (Path(__file__).resolve().parent.parent / "app").rglob("*.py"):
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if (
                re.search(r"""["']type["']\s*:\s*["']enabled["']""", line)
                and "budget" in line
            ):
                hits.append(f"{p.name}:{n}")
            if re.search(r"""["']budget_tokens["']\s*:""", line):
                hits.append(f"{p.name}:{n}")
    # the ONLY legitimate producer is thinking_param_for's legacy branch
    assert all(h.startswith("model_router.py") for h in hits), hits


# ----------------------------- fake "real" API -----------------------------


def _pairing_violation(messages: list[dict[str, Any]]) -> str | None:
    """Anthropic's rule: every assistant tool_use must be answered by a
    tool_result in the IMMEDIATELY following user message."""
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            ids = [b["id"] for b in m["content"] if b.get("type") == "tool_use"]
            if not ids:
                continue
            nxt = messages[i + 1] if i + 1 < len(messages) else None
            got: set[str] = set()
            if (
                nxt
                and nxt.get("role") == "user"
                and isinstance(nxt.get("content"), list)
            ):
                got = {
                    b.get("tool_use_id")
                    for b in nxt["content"]
                    if b.get("type") == "tool_result"
                }
            if not set(ids) <= got:
                return f"messages.{i}: `tool_use` ids were found without `tool_result` blocks immediately after"
    return None


class FakeAnthropic:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(self, client, **kw):  # stands in for _call_anthropic
        self.calls.append(kw)
        bad = _pairing_violation(kw["messages"])
        if bad:
            raise RuntimeError(f"Error code: 400 - invalid_request_error: {bad}")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


def _fence(obj: str) -> str:
    return f"```json\n{obj}\n```"  # exactly how the live model answers


PENDING = [
    {"role": "user", "content": "fix the bug"},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "reading"},
            {
                "type": "tool_use",
                "id": "toolu_A",
                "name": "read_file",
                "input": {"path": "a.py"},
            },
            {
                "type": "tool_use",
                "id": "toolu_B",
                "name": "read_file",
                "input": {"path": "b.py"},
            },
        ],
    },
]


# --------------------------- _parse_llm_json --------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Sure! Here is the result:\n{"a": 1}\nHope that helps.',
        '  \n```JSON\n{"a": 1}\n```\n',
    ],
)
def test_parse_llm_json_accepts_what_real_models_emit(text) -> None:
    assert _parse_llm_json(text) == {"a": 1}


def test_parse_llm_json_arrays_nested_and_failures() -> None:
    assert _parse_llm_json('```json\n[1, {"b": [2]}]\n```', expect=list) == [
        1,
        {"b": [2]},
    ]
    assert _parse_llm_json('x {"o": {"i": [1, 2]}} y') == {"o": {"i": [1, 2]}}
    for bad in ("", "no json here", "{broken", "```json\n{nope}\n```"):
        with pytest.raises(ValueError):
            _parse_llm_json(bad)


# --------------------------- reflection history ----------------------------


def test_review_history_pairs_every_pending_tool_use() -> None:
    assert _pairing_violation(PENDING) is not None  # the shape the node used to send
    fixed = _messages_valid_for_review(PENDING)
    assert _pairing_violation(fixed) is None
    results = fixed[-1]["content"]
    assert [b["tool_use_id"] for b in results] == ["toolu_A", "toolu_B"]
    assert "pending" in results[0]["content"]
    assert len(fixed) == len(PENDING) + 1 and PENDING[-1] is fixed[len(PENDING) - 1]


def test_review_history_leaves_valid_histories_untouched() -> None:
    complete = PENDING + [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_A", "content": "x"},
                {"type": "tool_result", "tool_use_id": "toolu_B", "content": "y"},
            ],
        },
    ]
    assert _messages_valid_for_review(complete) == complete
    plain = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "yo"}]},
    ]
    assert _messages_valid_for_review(plain) == plain
    assert _messages_valid_for_review([]) == []


# ------------------------------ node behaviour -----------------------------


def test_reflection_node_works_against_the_real_api_shape(monkeypatch) -> None:
    fake = FakeAnthropic(_fence('{"satisfied": false, "issues": ["missed edge case"]}'))
    monkeypatch.setattr(bg, "_call_anthropic", fake)
    monkeypatch.setattr(bg, "_make_client", lambda: object())
    node = bg._make_reflection_node("claude-sonnet-5")
    out = node({"messages": list(PENDING), "reflection_unsatisfied_count": 0})
    assert fake.calls and _pairing_violation(fake.calls[0]["messages"]) is None
    assert out["reflection_unsatisfied_count"] == 1, "reflection was silently skipped"
    assert "messages" not in out  # never inserted between tool_use and its result
    assert "[Self-review]" in out["self_review"]
    assert "missed edge case" in out["self_review"]


def test_reflection_satisfied_and_garbage_replies_do_not_break_the_run(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bg, "_make_client", lambda: object())
    for reply in (_fence('{"satisfied": true, "issues": []}'), "no json at all", ""):
        monkeypatch.setattr(bg, "_call_anthropic", FakeAnthropic(reply))
        node = bg._make_reflection_node("claude-sonnet-5")
        assert node({"messages": list(PENDING)}) == {}


def test_critique_node_parses_a_fenced_verdict_and_sends_work_back(monkeypatch) -> None:
    reply = _fence(
        '{"criteria": [{"criterion": "tests run", "met": false, "evidence": "no tests_run flag"}],'
        ' "all_met": false}'
    )
    monkeypatch.setattr(bg, "_call_anthropic", FakeAnthropic(reply))
    monkeypatch.setattr(bg, "_make_client", lambda: object())
    node = bg._make_critique_node("coder", "claude-sonnet-5", max_critique_retries=2)
    state = {
        "messages": [{"role": "user", "content": "task"}],
        "verification": {},
        "result": {"summary": "done"},
        "critique_retries": 0,
    }
    out = node(state)
    assert (
        out["submitted"] is False and out["critique_retries"] == 1
    ), "critique_node silently did nothing (bare json.loads on a fenced reply)"
    assert "tests run" in out["messages"][-1]["content"]


def test_planner_reads_the_real_confidence_not_the_default(monkeypatch) -> None:
    replies = iter(
        [
            _fence('{"given": [], "to_look_up": []}'),
            _fence(
                '{"steps": ["a"], "validation": [], "confidence": 0.42, "risks": []}'
            ),
        ]
    )

    def fake(client, **kw):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=next(replies))]
        )

    monkeypatch.setattr(bg, "_call_anthropic", fake)
    _facts, _plan, confidence = bg._gather_facts_and_plan(
        object(), "claude-haiku-4-5", "do x"
    )
    assert confidence == pytest.approx(
        0.42
    ), "confidence was permanently the 0.8 default"


def test_lesson_extractor_stores_a_lesson_from_a_fenced_reply(monkeypatch) -> None:
    stored: list[Any] = []
    monkeypatch.setattr(
        bg,
        "_call_anthropic",
        FakeAnthropic(
            _fence(
                '{"lesson": "run tests first", "pattern": "tdd", "category": "testing", "reusable": true}'
            )
        ),
    )
    monkeypatch.setattr(bg, "_make_client", lambda: object())
    monkeypatch.setattr(
        bg, "get_lesson_store", lambda: SimpleNamespace(add=stored.append)
    )
    bg._extract_and_store_lesson(
        {
            "messages": [{"role": "user", "content": "task"}],
            "result": {"summary": "ok"},
        },
        "coder",
        "claude-haiku-4-5",
    )
    assert stored and stored[0].lesson == "run tests first", "no lesson was ever stored"


def test_self_review_is_delivered_after_the_tool_results_and_history_stays_valid() -> (
    None
):
    """The second-order bug the reflection fix exposed: a self-review placed
    before execute_tools sat between tool_use and tool_result (400 on the next
    call). Drive the real execute_tools node and check the history it produces
    satisfies the API's pairing rule, with the note AFTER the results."""
    from app.agents.base_graph import VerificationConfig

    node = bg._make_execute_tools_node(
        tool_handlers={"read_file": lambda inp: "file body"},
        verification_cfg=VerificationConfig(),
        human_approval_required=False,
        tools=[
            {"name": "read_file", "input_schema": {"type": "object", "properties": {}}}
        ],
    )
    history = [
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "toolu_X", "name": "read_file", "input": {}}
            ],
        },
    ]
    state = {
        "messages": history,
        "verification": {},
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "self_review": "[Self-review]\nyou missed an edge case",
    }
    out = node(state)
    msgs = out["messages"]
    assert _pairing_violation(msgs) is None
    content = msgs[-1]["content"]
    assert (
        content[0]["type"] == "tool_result" and content[0]["tool_use_id"] == "toolu_X"
    )
    assert content[-1] == {
        "type": "text",
        "text": "[Self-review]\nyou missed an edge case",
    }
    assert out["self_review"] == "", "the note must be delivered exactly once"
    # without a pending review the message is exactly the tool results, as before
    state2 = {**state, "self_review": ""}
    assert [b["type"] for b in node(state2)["messages"][-1]["content"]] == [
        "tool_result"
    ]


def test_parse_llm_json_never_returns_a_nested_list_as_the_object() -> None:
    """Live: a malformed plan object made the fallback return its inner
    "steps" list, then `.get` blew up ('list' object has no attribute 'get')."""
    broken = '{"steps": ["a", "b"], "validation": [1, 2,'  # truncated object
    with pytest.raises(ValueError):
        _parse_llm_json(broken)
    assert _parse_llm_json("[1, 2]", expect=list) == [1, 2]
    assert _parse_llm_json("[1, 2]", expect=None) == [1, 2]
    with pytest.raises(ValueError):
        _parse_llm_json("[1, 2]")  # default expects an object
