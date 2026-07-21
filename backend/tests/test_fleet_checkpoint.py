"""Tests for Fleet OS fleet_checkpoint.py — Day 0 exit criterion §20.

Key tests:
- save → restore returns an identical deep-copy
- rollback returns the snapshot and raises KeyError for unknown IDs
- ring buffer eviction (capacity exceeded)
- multiple checkpoints per agent/task, latest_for filter
- mutations to restored state do not affect the stored snapshot (deep-copy isolation)
- process singleton is stable across imports
"""

from __future__ import annotations

import pytest

from app.fleet.fleet_checkpoint import (
    CheckpointStore,
    get_checkpoint_store,
    restore_checkpoint,
    rollback_to,
    save_checkpoint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(turns: int = 0, messages: list | None = None) -> dict:
    return {
        "messages": messages or [{"role": "user", "content": "test task"}],
        "verification": {"tests_passed": False},
        "result": {},
        "turns": turns,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 100 * turns,
        "tokens_out": 50 * turns,
    }


def _fresh(capacity: int = 100) -> CheckpointStore:
    return CheckpointStore(capacity=capacity)


# ---------------------------------------------------------------------------
# AgentCheckpoint
# ---------------------------------------------------------------------------


class TestAgentCheckpoint:
    def test_to_dict_has_all_fields(self) -> None:
        store = _fresh()
        ckpt_id = store.save(
            _state(turns=3), agent_name="coder", task_id="task-1", label="before_edit"
        )
        cp = store.get(ckpt_id)
        assert cp is not None
        d = cp.to_dict()
        assert d["checkpoint_id"] == ckpt_id
        assert d["agent_name"] == "coder"
        assert d["task_id"] == "task-1"
        assert d["label"] == "before_edit"
        assert d["turns_saved"] == 3
        assert "created_at" in d

    def test_checkpoint_id_starts_with_ckpt(self) -> None:
        store = _fresh()
        ckpt_id = store.save(_state(), agent_name="bug_fix")
        assert ckpt_id.startswith("ckpt-")

    def test_each_save_produces_unique_id(self) -> None:
        store = _fresh()
        ids = {store.save(_state(), agent_name="qa") for _ in range(50)}
        assert len(ids) == 50


# ---------------------------------------------------------------------------
# Save → Restore
# ---------------------------------------------------------------------------


class TestSaveRestore:
    def test_restore_returns_identical_state(self) -> None:
        store = _fresh()
        s = _state(turns=5)
        ckpt_id = store.save(s, agent_name="coder", task_id="task-42")
        restored = store.restore(ckpt_id)
        assert restored is not None
        assert restored == s

    def test_restore_returns_none_for_unknown_id(self) -> None:
        store = _fresh()
        assert store.restore("ckpt-doesnotexist") is None

    def test_restore_is_deep_copy_not_reference(self) -> None:
        store = _fresh()
        s = _state()
        ckpt_id = store.save(s, agent_name="coder")
        restored = store.restore(ckpt_id)
        assert restored is not None
        # Mutate the restored copy
        restored["turns"] = 999
        restored["messages"].append({"role": "assistant", "content": "added"})
        # Original in store must be unchanged
        restored2 = store.restore(ckpt_id)
        assert restored2 is not None
        assert restored2["turns"] == 0
        assert len(restored2["messages"]) == 1

    def test_mutating_original_after_save_does_not_affect_checkpoint(self) -> None:
        store = _fresh()
        s = _state()
        ckpt_id = store.save(s, agent_name="coder")
        s["turns"] = 999  # mutate original AFTER save
        restored = store.restore(ckpt_id)
        assert restored is not None
        assert restored["turns"] == 0  # deep-copied at save time


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_returns_snapshot(self) -> None:
        store = _fresh()
        s = _state(turns=2)
        ckpt_id = store.save(s, agent_name="bug_fix", label="before_risky_op")
        rolled = store.rollback(ckpt_id)
        assert rolled["turns"] == 2

    def test_rollback_raises_keyerror_for_missing_id(self) -> None:
        store = _fresh()
        with pytest.raises(KeyError, match="not found"):
            store.rollback("ckpt-ghost")

    def test_module_rollback_to_function(self) -> None:
        store = get_checkpoint_store()
        s = _state(turns=7)
        ckpt_id = store.save(s, agent_name="qa", task_id="task-module-test")
        rolled = rollback_to(ckpt_id)
        assert rolled["turns"] == 7


# ---------------------------------------------------------------------------
# List + Filter
# ---------------------------------------------------------------------------


class TestListFilter:
    def test_list_all(self) -> None:
        store = _fresh()
        store.save(_state(), agent_name="agent_a", task_id="t1")
        store.save(_state(), agent_name="agent_b", task_id="t2")
        store.save(_state(), agent_name="agent_a", task_id="t3")
        assert len(store.list_checkpoints()) == 3

    def test_filter_by_agent(self) -> None:
        store = _fresh()
        store.save(_state(), agent_name="agent_a")
        store.save(_state(), agent_name="agent_b")
        store.save(_state(), agent_name="agent_a")
        result = store.list_checkpoints(agent_name="agent_a")
        assert len(result) == 2
        assert all(c.agent_name == "agent_a" for c in result)

    def test_filter_by_task(self) -> None:
        store = _fresh()
        store.save(_state(), agent_name="coder", task_id="task-99")
        store.save(_state(), agent_name="coder", task_id="task-00")
        result = store.list_checkpoints(task_id="task-99")
        assert len(result) == 1
        assert result[0].task_id == "task-99"

    def test_latest_for_returns_most_recent(self) -> None:
        store = _fresh()
        id1 = store.save(  # noqa: F841
            _state(turns=1), agent_name="coder", task_id="t1"
        )
        id2 = store.save(_state(turns=2), agent_name="coder", task_id="t1")
        latest = store.latest_for("coder", "t1")
        assert latest is not None
        assert latest.checkpoint_id == id2


# ---------------------------------------------------------------------------
# Ring Buffer Eviction
# ---------------------------------------------------------------------------


class TestRingBuffer:
    def test_evicts_oldest_when_at_capacity(self) -> None:
        store = CheckpointStore(capacity=3)
        id1 = store.save(_state(), agent_name="a")
        id2 = store.save(_state(), agent_name="a")
        id3 = store.save(_state(), agent_name="a")  # noqa: F841
        id4 = store.save(_state(), agent_name="a")  # evicts id1
        assert store.restore(id1) is None
        assert store.restore(id2) is not None
        assert store.restore(id4) is not None

    def test_total_saved_counts_evicted(self) -> None:
        store = CheckpointStore(capacity=3)
        for _ in range(10):
            store.save(_state(), agent_name="a")
        assert store.total_saved == 10
        assert store.current_size == 3

    def test_current_size_stays_at_capacity(self) -> None:
        store = CheckpointStore(capacity=5)
        for _ in range(20):
            store.save(_state(), agent_name="a")
        assert store.current_size == 5


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_total_saved_increments(self) -> None:
        store = _fresh()
        assert store.total_saved == 0
        store.save(_state(), agent_name="a")
        store.save(_state(), agent_name="b")
        assert store.total_saved == 2

    def test_current_size_increments(self) -> None:
        store = _fresh()
        assert store.current_size == 0
        store.save(_state(), agent_name="a")
        assert store.current_size == 1


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    def test_save_and_restore_via_module_functions(self) -> None:
        s = _state(turns=4)
        ckpt_id = save_checkpoint(s, agent_name="reviewer", task_id="task-module")
        restored = restore_checkpoint(ckpt_id)
        assert restored is not None
        assert restored["turns"] == 4

    def test_restore_returns_none_for_unknown(self) -> None:
        assert restore_checkpoint("ckpt-missing-99") is None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_checkpoint_store_returns_same_instance(self) -> None:
        s1 = get_checkpoint_store()
        s2 = get_checkpoint_store()
        assert s1 is s2

    def test_singleton_state_persists_across_calls(self) -> None:
        store = get_checkpoint_store()
        before = store.total_saved
        save_checkpoint(_state(), agent_name="singleton_test")
        assert get_checkpoint_store().total_saved == before + 1


# ---------------------------------------------------------------------------
# Day 0 exit criterion: one complete save → restore → rollback cycle
# ---------------------------------------------------------------------------


def test_day0_complete_checkpoint_rollback_cycle() -> None:
    """§20 Day 0 exit criterion: demonstrate a real save → restore → rollback cycle.

    Scenario: agent is about to run a risky migration.
    1. Checkpoint saved before the risky op.
    2. 'Risky op' mutates the state (simulated).
    3. Rollback restores the pre-op state exactly.
    """
    store = _fresh()

    # Step 1: state before risky operation
    state_before = {
        "messages": [{"role": "user", "content": "Run database migration"}],
        "verification": {"tests_passed": True, "schema_inspected": True},
        "result": {},
        "turns": 3,
        "submitted": False,
        "requires_human_approval": True,
        "tokens_in": 3000,
        "tokens_out": 500,
    }
    ckpt_id = store.save(
        state_before,
        agent_name="migration_agent",
        task_id="task-day0-ckpt",
        label="before_alembic_upgrade",
        metadata={"risk": "high", "operation": "alembic upgrade head"},
    )

    # Verify checkpoint metadata
    cp = store.get(ckpt_id)
    assert cp is not None
    assert cp.agent_name == "migration_agent"
    assert cp.label == "before_alembic_upgrade"
    assert cp.metadata["operation"] == "alembic upgrade head"

    # Step 2: simulate risky op mutating state
    state_after = dict(state_before)
    state_after["turns"] = 8
    state_after["verification"] = {"tests_passed": False, "schema_inspected": False}
    state_after["result"] = {"error": "migration failed: constraint violation"}

    # Step 3: rollback to pre-op state
    rolled_back = store.rollback(ckpt_id)
    assert rolled_back["turns"] == 3
    assert rolled_back["verification"]["tests_passed"] is True
    assert rolled_back["result"] == {}
    assert rolled_back["requires_human_approval"] is True

    # The rolled-back state must match the original exactly
    assert rolled_back == state_before
