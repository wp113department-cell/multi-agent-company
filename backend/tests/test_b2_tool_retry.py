"""Verification batch B2, items #61/#63 — automatic retry of failed tool calls.
The retry policy comes from the tool manifest; hazardous permissions are never
retried; a POLICY denial is deterministic and must not be retried (it used to burn
the whole backoff)."""

from __future__ import annotations

import time

import pytest

from app.agents import base_graph as bg
from app.fleet.tool_manifest import TOOL_MANIFEST


def _by_policy(policy: str, hazardous: bool) -> str:
    for name, e in TOOL_MANIFEST.items():
        is_haz = bool({"write_remote", "execute", "write_repo"} & set(e.permissions))
        if e.retry_policy == policy and is_haz == hazardous:
            return name
    pytest.skip(f"no manifest tool with retry_policy={policy!r} hazardous={hazardous}")


class Flaky:
    def __init__(self, fail_times: int, fail_text: str = "[ERROR] transient") -> None:
        self.calls = 0
        self.fail_times, self.fail_text = fail_times, fail_text

    def __call__(self, inp):
        self.calls += 1
        return self.fail_text if self.calls <= self.fail_times else "ok"


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(bg.time, "sleep", lambda s: None)


def test_backoff_tool_recovers_after_transient_failures() -> None:
    name = _by_policy("backoff", hazardous=False)
    h = Flaky(fail_times=2)
    assert bg._run_tool_with_retry(h, name, {}) == "ok" and h.calls == 3


def test_backoff_tool_gives_up_with_the_error_after_max_attempts() -> None:
    name = _by_policy("backoff", hazardous=False)
    h = Flaky(fail_times=99)
    assert bg._run_tool_with_retry(h, name, {}).startswith("[ERROR]") and h.calls == 3


def test_once_tool_retries_exactly_once() -> None:
    name = _by_policy("once", hazardous=False)
    h = Flaky(fail_times=99)
    bg._run_tool_with_retry(h, name, {})
    assert h.calls == 2


def test_hazardous_tools_are_never_retried_whatever_their_policy() -> None:
    hazardous = [
        n
        for n, e in TOOL_MANIFEST.items()
        if e.retry_policy != "none"
        and {"write_remote", "execute", "write_repo"} & set(e.permissions)
    ]
    for name in hazardous:
        h = Flaky(fail_times=99)
        bg._run_tool_with_retry(h, name, {})
        assert h.calls == 1, f"{name} was retried"


def test_unknown_and_none_policy_tools_run_once() -> None:
    for name in ("no_such_tool", _by_policy("none", hazardous=False)):
        h = Flaky(fail_times=99)
        bg._run_tool_with_retry(h, name, {})
        assert h.calls == 1


def test_a_policy_denial_is_not_retried() -> None:
    name = _by_policy("backoff", hazardous=False)
    h = Flaky(fail_times=99, fail_text="[POLICY DENIED] blocked host")
    assert bg._run_tool_with_retry(h, name, {}).startswith("[POLICY DENIED]")
    assert h.calls == 1


def test_a_raising_handler_is_converted_to_an_error_result_not_propagated() -> None:
    name = _by_policy("backoff", hazardous=False)

    def boom(inp):
        raise RuntimeError("kaput")

    out = bg._run_tool_with_retry(boom, name, {})
    assert out.startswith("[ERROR]") and "kaput" in out


def test_backoff_delays_are_bounded(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(bg.time, "sleep", sleeps.append)
    name = _by_policy("backoff", hazardous=False)
    bg._run_tool_with_retry(Flaky(fail_times=99), name, {})
    assert sleeps == [0.5, 1.0] and max(sleeps) <= 4.0
