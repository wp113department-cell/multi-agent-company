"""Tests for app.fleet.dynamic_agent_runtime — the generic name->callable
registry that lets a runtime-spawned agent (e.g. barot_agent's
temporary_agent instances) be found by the real dispatch call sites, none
of which can resolve an agent that isn't a static module on disk or a
hand-curated adapter-dict entry."""

from __future__ import annotations

from app.fleet.dynamic_agent_runtime import (
    register_runtime_agent_fn,
    resolve_runtime_agent_fn,
    unregister_runtime_agent_fn,
)


def _fn(task_id: int, description: str, repo_path: str) -> str:
    return f"{task_id}:{description}:{repo_path}"


def test_register_and_resolve() -> None:
    register_runtime_agent_fn("temp_agent_1", _fn)
    resolved = resolve_runtime_agent_fn("temp_agent_1")
    assert resolved is _fn
    unregister_runtime_agent_fn("temp_agent_1")


def test_resolve_missing_returns_none() -> None:
    assert resolve_runtime_agent_fn("never_registered_xyz") is None


def test_unregister_removes_entry() -> None:
    register_runtime_agent_fn("temp_agent_2", _fn)
    unregister_runtime_agent_fn("temp_agent_2")
    assert resolve_runtime_agent_fn("temp_agent_2") is None


def test_unregister_missing_is_noop() -> None:
    unregister_runtime_agent_fn("never_registered_abc")  # must not raise


def test_register_overwrites_existing_name() -> None:
    def _other_fn(task_id: int, description: str, repo_path: str) -> str:
        return "other"

    register_runtime_agent_fn("temp_agent_3", _fn)
    register_runtime_agent_fn("temp_agent_3", _other_fn)
    assert resolve_runtime_agent_fn("temp_agent_3") is _other_fn
    unregister_runtime_agent_fn("temp_agent_3")


def test_resolved_fn_is_callable_with_expected_shape() -> None:
    register_runtime_agent_fn("temp_agent_4", _fn)
    resolved = resolve_runtime_agent_fn("temp_agent_4")
    assert resolved is not None
    assert resolved(42, "do the thing", "/repo") == "42:do the thing:/repo"
    unregister_runtime_agent_fn("temp_agent_4")
