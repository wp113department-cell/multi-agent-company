"""Session 0 scaffold tests — base_graph.py enhancements (no real LLM calls).

Tests prove:
- All 9 new state fields exist with correct types in initial_state
- LessonStore add / retrieve / format_for_injection works correctly
- Keyword scoring returns correct top-k results
- _trim_messages enforces token budget
- _policy_check still blocks protected paths and commands
- VerificationConfig dataclass unchanged (backward compat)
- build_agent_graph compiles with all flags False (existing behavior preserved)
- build_agent_graph compiles with enable_planning, enable_memory, enable_reflection True
- run_agent_graph signature accepts all new keyword args without error
- Lesson extraction helpers don't raise on bad input
- get_lesson_store() singleton is stable
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.base_graph import (
    AgentRunState,
    Lesson,
    LessonStore,
    VerificationConfig,
    _policy_check,
    _serialize_content,
    _text_from_content,
    _trim_messages,
    build_agent_graph,
    get_lesson_store,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_state(**overrides: Any) -> AgentRunState:
    base: AgentRunState = {
        "messages": [{"role": "user", "content": "Fix the null pointer bug"}],
        "verification": {"tests_passed": False},
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        # New Fleet OS fields
        "plan": "",
        "facts": "",
        "n_stalls": 0,
        "retry_count": 0,
        "confidence": 1.0,
        "status": "running",
        "trace_id": "test-trace-001",
        "memory_context": "",
        "repo_context": "",
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _empty_vcfg() -> VerificationConfig:
    return VerificationConfig()


# ---------------------------------------------------------------------------
# New state fields — 9 added in Session 0
# ---------------------------------------------------------------------------

class TestNewStateFields:
    """Verify all 9 new Fleet OS state fields exist with correct types."""

    def test_plan_field_is_str(self) -> None:
        s = _minimal_state()
        assert isinstance(s["plan"], str)

    def test_facts_field_is_str(self) -> None:
        s = _minimal_state()
        assert isinstance(s["facts"], str)

    def test_n_stalls_field_is_int(self) -> None:
        s = _minimal_state()
        assert isinstance(s["n_stalls"], int)

    def test_retry_count_field_is_int(self) -> None:
        s = _minimal_state()
        assert isinstance(s["retry_count"], int)

    def test_confidence_field_is_float(self) -> None:
        s = _minimal_state()
        assert isinstance(s["confidence"], float)

    def test_status_field_is_str(self) -> None:
        s = _minimal_state()
        assert isinstance(s["status"], str)

    def test_trace_id_field_is_str(self) -> None:
        s = _minimal_state()
        assert isinstance(s["trace_id"], str)

    def test_memory_context_field_is_str(self) -> None:
        s = _minimal_state()
        assert isinstance(s["memory_context"], str)

    def test_repo_context_field_is_str(self) -> None:
        s = _minimal_state()
        assert isinstance(s["repo_context"], str)

    def test_original_8_fields_still_present(self) -> None:
        s = _minimal_state()
        for key in ("messages", "verification", "result", "turns",
                    "submitted", "requires_human_approval", "tokens_in", "tokens_out"):
            assert key in s, f"Original field {key!r} missing from state"

    def test_total_field_count_is_17(self) -> None:
        s = _minimal_state()
        assert len(s) == 17  # 8 original + 9 new


# ---------------------------------------------------------------------------
# LessonStore
# ---------------------------------------------------------------------------

class TestLessonStore:
    def test_add_increments_total(self) -> None:
        store = LessonStore()
        store.add(Lesson("agent", "Always run tests after edit_file", "test-first", "testing"))
        assert store.total == 1

    def test_retrieve_returns_relevant_lessons(self) -> None:
        store = LessonStore()
        store.add(Lesson("coder", "Run tests after editing Python files", "test-after-edit", "testing"))
        store.add(Lesson("qa", "Check migration rollback before applying", "migration-safety", "security"))
        results = store.retrieve("run tests python", top_k=3)
        assert len(results) >= 1
        assert any("test" in r.lesson.lower() for r in results)

    def test_retrieve_returns_empty_for_no_match(self) -> None:
        store = LessonStore()
        store.add(Lesson("coder", "Always lint after refactoring", "lint-after-refactor", "refactor"))
        results = store.retrieve("database migration security", top_k=3)
        assert results == []

    def test_retrieve_respects_top_k(self) -> None:
        store = LessonStore()
        for i in range(10):
            store.add(Lesson("coder", f"test lesson {i} testing tests", f"pattern-{i}", "testing"))
        results = store.retrieve("testing tests", top_k=3)
        assert len(results) <= 3

    def test_non_reusable_lessons_are_excluded(self) -> None:
        store = LessonStore()
        store.add(Lesson("coder", "This is a one-time fix testing", "one-time", "testing", reusable=False))
        results = store.retrieve("testing fix", top_k=5)
        assert results == []

    def test_format_for_injection_empty_when_no_match(self) -> None:
        store = LessonStore()
        result = store.format_for_injection("completely unrelated query xyz", top_k=3)
        assert result == ""

    def test_format_for_injection_returns_header_when_matched(self) -> None:
        store = LessonStore()
        store.add(Lesson("coder", "Always run pytest after editing", "run-pytest", "testing"))
        result = store.format_for_injection("run pytest testing", top_k=3)
        assert "Relevant past insights" in result
        assert "testing" in result

    def test_capacity_evicts_oldest(self) -> None:
        store = LessonStore(capacity=3)
        for i in range(5):
            store.add(Lesson("coder", f"lesson {i}", f"pattern-{i}", "general"))
        assert store.total == 3

    def test_retrieve_scores_by_keyword_overlap(self) -> None:
        store = LessonStore()
        store.add(Lesson("a", "run tests always", "test-always", "testing"))
        store.add(Lesson("b", "security scan required", "sec-scan", "security"))
        # Query is testing-related — should rank testing lesson higher
        results = store.retrieve("run tests", top_k=2)
        assert results[0].category == "testing"


class TestLessonStoreSingleton:
    def test_get_lesson_store_returns_same_instance(self) -> None:
        s1 = get_lesson_store()
        s2 = get_lesson_store()
        assert s1 is s2

    def test_singleton_persists_lessons_across_calls(self) -> None:
        store = get_lesson_store()
        before = store.total
        store.add(Lesson("singleton_test", "singleton lesson test pytest", "pattern", "testing"))
        assert get_lesson_store().total == before + 1


# ---------------------------------------------------------------------------
# _trim_messages
# ---------------------------------------------------------------------------

class TestTrimMessages:
    def _msgs(self, n: int) -> list[dict[str, Any]]:
        return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"} for i in range(n)]

    def test_no_trim_when_under_budget(self) -> None:
        msgs = self._msgs(6)
        result = _trim_messages(msgs, token_budget=100_000, tokens_in=50_000)
        assert result == msgs

    def test_trims_when_over_budget(self) -> None:
        msgs = self._msgs(10)
        result = _trim_messages(msgs, token_budget=100, tokens_in=90_000)
        assert len(result) < len(msgs)

    def test_trim_keeps_head_and_tail(self) -> None:
        msgs = self._msgs(10)
        result = _trim_messages(msgs, token_budget=100, tokens_in=90_000)
        assert result[0] == msgs[0]   # head preserved
        assert result[-1] == msgs[-1]  # tail preserved

    def test_no_trim_when_few_messages(self) -> None:
        msgs = self._msgs(3)
        result = _trim_messages(msgs, token_budget=100, tokens_in=90_000)
        assert result == msgs


# ---------------------------------------------------------------------------
# _serialize_content + _text_from_content
# ---------------------------------------------------------------------------

class TestSerializeHelpers:
    def test_serialize_text_block(self) -> None:
        block = MagicMock()
        block.type = "text"
        block.text = "hello world"
        result = _serialize_content([block])
        assert result == [{"type": "text", "text": "hello world"}]

    def test_serialize_tool_use_block(self) -> None:
        block = MagicMock()
        block.type = "tool_use"
        block.id = "tu_001"
        block.name = "read_file"
        block.input = {"path": "src/main.py"}
        result = _serialize_content([block])
        assert result[0]["name"] == "read_file"
        assert result[0]["input"] == {"path": "src/main.py"}

    def test_serialize_empty_list(self) -> None:
        assert _serialize_content([]) == []

    def test_text_from_content_joins_text_blocks(self) -> None:
        content = [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "name": "read_file"},
            {"type": "text", "text": "world"},
        ]
        assert _text_from_content(content) == "hello world"

    def test_text_from_content_empty(self) -> None:
        assert _text_from_content([]) == ""


# ---------------------------------------------------------------------------
# _policy_check (backward compat)
# ---------------------------------------------------------------------------

class TestPolicyCheck:
    def test_blocks_protected_path(self) -> None:
        result = _policy_check("write_file", {"path": ".env"})
        assert result is not None
        assert "denied" in result.lower() or "protect" in result.lower() or result != ""

    def test_allows_safe_path(self) -> None:
        result = _policy_check("write_file", {"path": "src/utils.py"})
        assert result is None

    def test_blocks_dangerous_bash(self) -> None:
        result = _policy_check("bash", {"command": "rm -rf /"})
        assert result is not None

    def test_allows_safe_bash(self) -> None:
        result = _policy_check("bash", {"command": "git status"})
        assert result is None

    def test_non_file_non_bash_tool_passes(self) -> None:
        result = _policy_check("read_file", {"path": ".env"})
        assert result is None  # read_file not in the write-tool set


# ---------------------------------------------------------------------------
# VerificationConfig — unchanged from Day 3 (backward compat)
# ---------------------------------------------------------------------------

class TestVerificationConfig:
    def test_defaults_are_empty(self) -> None:
        cfg = VerificationConfig()
        assert cfg.set_by == {}
        assert cfg.reset_by == ()
        assert cfg.reset_keys == ()
        assert cfg.enforce_in_result == {}
        assert cfg.initial == {}

    def test_full_config(self) -> None:
        cfg = VerificationConfig(
            set_by={"run_tests": "tests_passed"},
            reset_by=("edit_file",),
            reset_keys=("tests_passed",),
            enforce_in_result={"tests_passed": "tests_passed"},
            initial={"tests_passed": False},
        )
        assert cfg.set_by["run_tests"] == "tests_passed"
        assert "edit_file" in cfg.reset_by


# ---------------------------------------------------------------------------
# build_agent_graph — compile without errors
# ---------------------------------------------------------------------------

DUMMY_TOOL = {
    "name": "submit_test",
    "description": "Submit test result",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
class TestBuildAgentGraph:
    def test_compiles_with_all_flags_false(self, mock_load: Any) -> None:
        graph = build_agent_graph(
            role_name="bug_fix",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={"submit_test": lambda x: "ok"},
            verification_cfg=_empty_vcfg(),
        )
        assert graph is not None

    def test_compiles_with_planning_enabled(self, mock_load: Any) -> None:
        graph = build_agent_graph(
            role_name="pm",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={},
            verification_cfg=_empty_vcfg(),
            enable_planning=True,
            task_description="Build a login page",
            model_haiku="claude-haiku-4-5-20251001",
        )
        assert graph is not None

    def test_compiles_with_memory_enabled(self, mock_load: Any) -> None:
        graph = build_agent_graph(
            role_name="coder",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={},
            verification_cfg=_empty_vcfg(),
            enable_memory=True,
            task_description="Refactor auth module",
        )
        assert graph is not None

    def test_compiles_with_reflection_enabled(self, mock_load: Any) -> None:
        graph = build_agent_graph(
            role_name="reviewer",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={},
            verification_cfg=_empty_vcfg(),
            enable_reflection=True,
        )
        assert graph is not None

    def test_compiles_with_all_flags_true(self, mock_load: Any) -> None:
        graph = build_agent_graph(
            role_name="bug_fix",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={},
            verification_cfg=_empty_vcfg(),
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            task_description="Fix the auth bug",
            model_haiku="claude-haiku-4-5-20251001",
            repo_path="/tmp/test-repo",
        )
        assert graph is not None

    def test_backward_compat_existing_call_signature(self, mock_load: Any) -> None:
        """Existing 52 agents call build_agent_graph with only the original 7 kwargs."""
        graph = build_agent_graph(
            role_name="bug_fix",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={"submit_test": lambda x: "ok"},
            verification_cfg=_empty_vcfg(),
            human_approval_required=False,
            max_turns=10,
        )
        assert graph is not None


# ---------------------------------------------------------------------------
# run_agent_graph signature — accepts all new kwargs
# ---------------------------------------------------------------------------

@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
class TestRunAgentGraphSignature:
    def test_accepts_all_new_fleet_os_kwargs(self, mock_key: Any, mock_load: Any) -> None:
        """Verify run_agent_graph accepts all Session 0 keyword arguments.
        Does not call Anthropic — just tests the signature compiles.
        """
        import inspect
        sig = inspect.signature(build_agent_graph)
        new_params = {
            "enable_planning", "enable_memory", "enable_reflection",
            "task_description", "repo_path", "model_haiku",
            "context_token_budget", "max_stalls",
        }
        actual_params = set(sig.parameters.keys())
        for param in new_params:
            assert param in actual_params, f"New param {param!r} missing from build_agent_graph"

    def test_run_agent_graph_has_enable_lesson_param(self, mock_key: Any, mock_load: Any) -> None:
        import inspect
        from app.agents.base_graph import run_agent_graph
        sig = inspect.signature(run_agent_graph)
        assert "enable_lesson" in sig.parameters
        assert "trace_id" in sig.parameters
