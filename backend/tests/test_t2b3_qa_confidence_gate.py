"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #130 "Confidence Evaluation feeds
control flow") — qa.py is the second real agent (after spike_agent) opted
into Settings.quality_gate_min_confidence_by_agent.

The underlying mechanism (a real pending_approvals row fired by
_run_quality_gate/request_human_input once a caller opts into a nonzero
floor) is already proven generically by
tests/test_confidence_gated_control_flow.py — these tests are specifically
about run_qa()'s OWN wiring: does it actually pass the configured floor to
run_agent_graph(), and does it correctly read
final_state["result"]["_requires_human_approval"] back onto QAResult
(not handlers["_qa_result"], the model's own pre-enforcement submission,
which never carries that key).
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.qa import QAResult, run_qa
from app.config import get_settings


def _fake_final_state(
    *, requires_human_approval: bool, tests_run: bool = True
) -> dict[str, object]:
    return {
        "submitted": True,
        "tokens_in": 100,
        "tokens_out": 40,
        "confidence": 0.2 if requires_human_approval else 0.95,
        "verification": {"tests_run": tests_run},
        "result": {
            "status": "passed",
            "tests_run": 5,
            "tests_passed": 5,
            "tests_failed": 0,
            "typecheck_clean": True,
            "lint_clean": True,
            "summary": "all green",
            "_requires_human_approval": requires_human_approval,
        },
    }


def test_config_seeds_qa_pilot_threshold() -> None:
    settings = get_settings()
    assert settings.quality_gate_min_confidence_by_agent.get("qa") == 0.5


def test_run_qa_passes_the_configured_confidence_floor_to_run_agent_graph() -> None:
    with patch("app.agents.qa.run_agent_graph") as mock_run:
        mock_run.return_value = _fake_final_state(requires_human_approval=False)
        run_qa(
            task_id=1,
            subtask_id=1,
            files_changed=["a.py"],
            worktree_path="/tmp/does-not-need-to-exist-for-this-mock",
        )

    assert mock_run.call_count == 1
    kwargs = mock_run.call_args.kwargs
    assert kwargs["quality_gate_min_confidence"] == 0.5


def test_run_qa_propagates_requires_human_approval_true() -> None:
    # make_qa_handlers is also mocked here: handlers["_qa_result"] is
    # normally populated by the real submit_qa_result handler when the
    # (mocked-away) graph actually calls it — status/tests_run/etc. come
    # from THIS dict, deliberately separate from final_state["result"]
    # (where _requires_human_approval lives) per qa.py's own comment.
    with (
        patch("app.agents.qa.run_agent_graph") as mock_run,
        patch("app.agents.qa.make_qa_handlers") as mock_make_handlers,
    ):
        mock_run.return_value = _fake_final_state(requires_human_approval=True)
        mock_make_handlers.return_value = {
            "_qa_result": {"status": "passed", "tests_run": 5, "tests_passed": 5}
        }
        result = run_qa(
            task_id=2,
            subtask_id=1,
            files_changed=["a.py"],
            worktree_path="/tmp/does-not-need-to-exist-for-this-mock",
        )

    assert isinstance(result, QAResult)
    assert result.requires_human_approval is True
    assert result.status == "passed"  # the flag doesn't fabricate a failure


def test_run_qa_leaves_requires_human_approval_false_for_a_confident_pass() -> None:
    with patch("app.agents.qa.run_agent_graph") as mock_run:
        mock_run.return_value = _fake_final_state(requires_human_approval=False)
        result = run_qa(
            task_id=3,
            subtask_id=1,
            files_changed=["a.py"],
            worktree_path="/tmp/does-not-need-to-exist-for-this-mock",
        )

    assert result.requires_human_approval is False
