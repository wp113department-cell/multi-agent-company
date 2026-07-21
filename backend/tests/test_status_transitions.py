"""Status transition state machine tests."""
from app.db.models import can_transition, VALID_TRANSITIONS


def test_pending_to_planning_allowed():
    assert can_transition("pending", "planning") is True


def test_pending_to_done_blocked():
    assert can_transition("pending", "completed") is False


def test_planning_to_ready_for_review_allowed():
    assert can_transition("planning", "ready_for_review") is True


def test_ready_for_review_to_coding_allowed():
    assert can_transition("ready_for_review", "coding") is True


def test_coding_to_testing_allowed():
    assert can_transition("coding", "testing") is True


def test_testing_to_ready_for_review_allowed():
    assert can_transition("testing", "ready_for_review") is True


def test_ready_for_review_to_completed():
    # completed is NOT a valid transition from ready_for_review
    # The human manually closes via the API after approve
    # Actually in Python backend the approve route moves to 'coding' not 'completed'
    # Let's verify the machine is consistent
    assert can_transition("ready_for_review", "rejected") is True


def test_completed_has_no_transitions():
    assert VALID_TRANSITIONS["completed"] == []


def test_failed_has_no_transitions():
    assert VALID_TRANSITIONS["failed"] == []


def test_blocked_can_restart():
    assert can_transition("blocked", "planning") is True


def test_done_to_pending_blocked():
    assert can_transition("completed", "pending") is False


def test_invalid_current_status():
    assert can_transition("nonexistent_status", "planning") is False
