"""AUDIT_Q_BATCH18 §54/55/56 gap-closure (2026-08-12) — "Refuse to invent
APIs/files/functions/classes" was scored NO: every real no-hallucination
mechanism in this codebase (VerificationConfig.blocking_until,
_run_quality_gate, ...) constrains what an agent may DO, none of them
checked what an agent's own final CLAIM says, despite several role prompts
(security_reviewer.py, architecture_reviewer.py) already demanding a
file:line citation discipline. verify_file_line_citations() (app.agents.
tool_security) + its wiring into _make_execute_tools_node's submit_*
chokepoint is that missing check.
"""

from __future__ import annotations

from typing import Any

from app.agents.base_graph import VerificationConfig, _make_execute_tools_node
from app.agents.tool_security import verify_file_line_citations


def _cfg(**overrides: Any) -> VerificationConfig:
    base: dict[str, Any] = dict(
        set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
    )
    base.update(overrides)
    return VerificationConfig(**base)


SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


def _submit_state(summary: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "submit_result",
                        "input": {"summary": summary},
                    }
                ],
            }
        ],
        "verification": {},
        "result": {},
        "submitted": False,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }


class TestVerifyFileLineCitationsUnit:
    def test_real_citation_verifies_clean(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        f = tmp_path / "foo.py"
        f.write_text("line1\nline2\nline3\n")
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see foo.py:2 for the fix"}
        )
        assert report["checked"] == 1
        assert report["unverified"] == []

    def test_nonexistent_file_is_flagged(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see ghost_module.py:42 for details"}
        )
        assert report["checked"] == 1
        assert len(report["unverified"]) == 1
        assert "not found" in report["unverified"][0]

    def test_line_beyond_file_length_is_flagged(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        f = tmp_path / "short.py"
        f.write_text("only one line\n")
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "bug is at short.py:500"}
        )
        assert report["checked"] == 1
        assert "only" in report["unverified"][0]

    def test_nested_dict_and_list_structures_are_scanned(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        f = tmp_path / "real.py"
        f.write_text("\n".join(f"line{i}" for i in range(10)) + "\n")
        raw_result = {
            "risks": [
                {"severity": "high", "evidence": ["real.py:3", "fake.py:9"]},
            ]
        }
        report = verify_file_line_citations(str(tmp_path), raw_result)
        assert report["checked"] == 2
        assert len(report["unverified"]) == 1
        assert "fake.py" in report["unverified"][0]

    def test_no_repo_root_is_a_safe_noop(self) -> None:
        report = verify_file_line_citations("", {"summary": "foo.py:1"})
        assert report == {"checked": 0, "unverified": [], "unverified_names": []}

    def test_nonexistent_repo_root_is_a_safe_noop(self) -> None:
        report = verify_file_line_citations(
            "/definitely/not/a/real/path/xyz", {"summary": "foo.py:1"}
        )
        assert report == {"checked": 0, "unverified": [], "unverified_names": []}

    def test_duplicate_citations_counted_once(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        f = tmp_path / "dup.py"
        f.write_text("line1\nline2\n")
        report = verify_file_line_citations(
            str(tmp_path), {"a": "dup.py:1", "b": "also dup.py:1 again"}
        )
        assert report["checked"] == 1

    def test_non_citation_looking_text_is_ignored(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "the ratio was 3:4 and time was 10:30"}
        )
        assert report["checked"] == 0
        assert report["unverified"] == []


class TestExecuteToolsCitationWiring:
    def test_bad_citation_is_flagged_on_submit_but_does_not_block(
        self, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            repo_path=str(tmp_path),
        )
        result = node(_submit_state("the bug is in nonexistent_file.py:99"))

        assert result["submitted"] is True
        assert "_citation_check" in result["result"]
        assert result["result"]["_citation_check"]["unverified"]
        # Non-blocking: a bad citation alone must not fail the quality gate.
        assert result["result"]["_quality_gate"]["passed"] is True

    def test_good_citation_produces_no_flag(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        real_file = tmp_path / "real_module.py"
        real_file.write_text("def f():\n    pass\n")
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            repo_path=str(tmp_path),
        )
        result = node(_submit_state("see real_module.py:1"))

        assert "_citation_check" not in result["result"]

    def test_no_repo_path_is_backward_compatible_noop(self) -> None:
        """Every pre-existing caller that doesn't pass repo_path (the
        default "") must see zero behavior change."""
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
        )
        result = node(_submit_state("see totally_made_up_file.py:1"))

        assert "_citation_check" not in result["result"]


class TestCitationHallucinationCount:
    """#443 (2026-09-28, GRIDIRON_PARTIAL "Detect hallucinating agents /
    memory leaks / sync failures") — #502's citation check was already
    computed at every submit_* call but only ever logged, never persisted
    or aggregated. citation_hallucination_count is the real, cross-turn
    counter this closes."""

    def test_bad_citation_increments_the_counter(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            repo_path=str(tmp_path),
        )
        result = node(_submit_state("the bug is in nonexistent_file.py:99"))
        assert result["citation_hallucination_count"] == 1

    def test_good_citation_does_not_increment_the_counter(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        real_file = tmp_path / "real_module.py"
        real_file.write_text("def f():\n    pass\n")
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            repo_path=str(tmp_path),
        )
        result = node(_submit_state("see real_module.py:1"))
        assert result["citation_hallucination_count"] == 0

    def test_counter_accumulates_across_turns(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The real cross-turn property: a prior turn's own count must be
        read from state and carried forward, not reset each call — same
        pattern reflection_unsatisfied_count already relies on."""
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            repo_path=str(tmp_path),
        )
        state = _submit_state("bad ref one: nonexistent_a.py:1")
        state["citation_hallucination_count"] = 2  # as if two prior turns flagged
        result = node(state)
        assert result["citation_hallucination_count"] == 3

    def test_no_repo_path_leaves_counter_at_zero(self) -> None:
        """Same backward-compatible no-op as _citation_check itself — no
        repo_path means verify_file_line_citations never runs at all."""
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
        )
        result = node(_submit_state("see totally_made_up_file.py:1"))
        assert result["citation_hallucination_count"] == 0
