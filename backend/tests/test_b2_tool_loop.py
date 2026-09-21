"""Verification batch B2, items #59/#60/#62/#63 — the agent tool loop, driven through
the REAL execute_tools node: several tool calls in one turn, unknown tools, raising
handlers, verification state set from real results, blocking gates, and
graph-enforced result fields (an agent cannot claim what did not happen)."""

from __future__ import annotations

from typing import Any

from app.agents.base_graph import VerificationConfig, _make_execute_tools_node

SCHEMA = {"type": "object", "properties": {}}


def _tools(*names: str) -> list[dict[str, Any]]:
    return [{"name": n, "description": n, "input_schema": SCHEMA} for n in names]


def _state(
    tool_uses: list[tuple[str, str, dict]], verification=None, result=None
) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": tid, "name": name, "input": inp}
                    for tid, name, inp in tool_uses
                ],
            },
        ],
        "verification": dict(verification or {}),
        "result": dict(result or {}),
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _drain(node, state: dict[str, Any]) -> dict[str, Any]:
    """The graph self-loops execute_tools while a batch is still draining; do
    the same, merging each partial update into the state."""
    for _ in range(20):
        upd = node(state)
        state = {**state, **upd}
        if not state.get("pending_tool_uses"):
            return state
    raise AssertionError("execute_tools never finished the batch")


def _results(state: dict[str, Any]) -> list[dict[str, Any]]:
    last = state["messages"][-1]
    assert last["role"] == "user"
    return [b for b in last["content"] if b["type"] == "tool_result"]


def test_several_tools_in_one_turn_all_run_in_order_and_return_one_message() -> None:
    ran: list[str] = []
    handlers = {
        "a": lambda inp: ran.append("a") or "A-out",
        "b": lambda inp: ran.append("b") or "B-out",
        "c": lambda inp: ran.append("c") or "C-out",
    }
    node = _make_execute_tools_node(
        handlers, VerificationConfig(), False, tools=_tools("a", "b", "c")
    )
    st = _drain(node, _state([("t1", "a", {}), ("t2", "b", {}), ("t3", "c", {})]))
    assert ran == ["a", "b", "c"]
    res = _results(st)
    assert [(r["tool_use_id"], r["content"]) for r in res] == [
        ("t1", "A-out"),
        ("t2", "B-out"),
        ("t3", "C-out"),
    ]
    assert (
        len(st["messages"]) == 3
    )  # user, assistant, ONE user message with all results
    assert st["turns"] == 1


def test_a_failing_tool_does_not_stop_the_rest_of_the_batch() -> None:
    def boom(inp):
        raise RuntimeError("disk on fire")

    node = _make_execute_tools_node(
        {"bad": boom, "good": lambda inp: "fine"},
        VerificationConfig(),
        False,
        tools=_tools("bad", "good"),
    )
    st = _drain(node, _state([("t1", "bad", {}), ("t2", "good", {})]))
    res = {r["tool_use_id"]: r["content"] for r in _results(st)}
    assert res["t1"].startswith("[ERROR]") and "disk on fire" in res["t1"]
    assert res["t2"] == "fine"


def test_a_tool_outside_the_advertised_list_is_refused_even_if_a_handler_exists() -> (
    None
):
    ran: list[str] = []
    node = _make_execute_tools_node(
        {"a": lambda i: "x", "secret_tool": lambda i: ran.append("ran") or "boom"},
        VerificationConfig(),
        False,
        tools=_tools("a"),
    )
    st = _drain(node, _state([("t1", "secret_tool", {}), ("t2", "does_not_exist", {})]))
    res = _results(st)
    assert all("[POLICY DENIED]" in r["content"] for r in res)
    assert "not among the tools advertised" in res[0]["content"]
    assert ran == [], "an unadvertised tool's handler was dispatched"


def test_verification_flag_is_set_only_by_a_successful_run() -> None:
    cfg = VerificationConfig(
        set_by={"run_tests": "tests_run"}, initial={"tests_run": False}
    )
    ok = _make_execute_tools_node(
        {"run_tests": lambda i: "3 passed"}, cfg, False, tools=_tools("run_tests")
    )
    assert (
        _drain(ok, _state([("t1", "run_tests", {})], {"tests_run": False}))[
            "verification"
        ]["tests_run"]
        is True
    )
    bad = _make_execute_tools_node(
        {"run_tests": lambda i: "[ERROR] boom"}, cfg, False, tools=_tools("run_tests")
    )
    assert (
        _drain(bad, _state([("t1", "run_tests", {})], {"tests_run": False}))[
            "verification"
        ]["tests_run"]
        is False
    )


def test_mutating_tool_resets_the_flag_it_invalidates() -> None:
    cfg = VerificationConfig(
        set_by={"run_tests": "tests_run"},
        reset_by=("write_file",),
        reset_keys=("tests_run",),
    )
    node = _make_execute_tools_node(
        {"write_file": lambda i: "Written", "run_tests": lambda i: "ok"},
        cfg,
        False,
        tools=_tools("write_file", "run_tests"),
    )
    st = _drain(node, _state([("t1", "run_tests", {})], {"tests_run": False}))
    assert st["verification"]["tests_run"] is True
    st2 = _drain(node, _state([("t2", "write_file", {})], st["verification"]))
    assert (
        st2["verification"]["tests_run"] is False
    ), "tests_run must not survive a code change"


def test_blocking_gate_refuses_the_handler_until_the_prerequisite_ran() -> None:
    calls: list[str] = []
    cfg = VerificationConfig(
        set_by={"read_file": "read"},
        blocking_until={"write_file": "read"},
        initial={"read": False},
    )
    node = _make_execute_tools_node(
        {
            "read_file": lambda i: calls.append("read") or "content",
            "write_file": lambda i: calls.append("write") or "Written",
        },
        cfg,
        False,
        tools=_tools("read_file", "write_file"),
    )
    st = _drain(node, _state([("t1", "write_file", {})], {"read": False}))
    assert (
        "[POLICY DENIED]" in _results(st)[0]["content"] and calls == []
    ), "handler ran despite the gate"
    st = _drain(node, _state([("t2", "read_file", {})], st["verification"]))
    st = _drain(node, _state([("t3", "write_file", {})], st["verification"]))
    assert calls == ["read", "write"] and _results(st)[0]["content"] == "Written"


def test_enforced_result_fields_override_a_false_claim() -> None:
    """An agent cannot SAY it ran the tests: the graph overwrites the field with
    what actually happened."""
    cfg = VerificationConfig(
        enforce_in_result={"tests_passed": "tests_run"},
        initial={"tests_run": False},
    )
    submit_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tests_passed": {"type": "boolean"},
        },
    }
    tools = [
        {"name": "submit_result", "description": "s", "input_schema": submit_schema}
    ]
    node = _make_execute_tools_node(
        {"submit_result": lambda inp: "ok"},
        cfg,
        False,
        tools=tools,
    )
    st = _drain(
        node,
        _state(
            [("t1", "submit_result", {"summary": "done", "tests_passed": True})],
            {"tests_run": False},
        ),
    )
    assert st["submitted"] is True
    assert st["result"]["tests_passed"] is False, "the model's own claim leaked through"
