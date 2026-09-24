"""T2-B2 (2026-09-22, GRIDIRON_PARTIAL #212/#213/#235/#236/#246) — tests for
app.fleet.resume_registry, the per-agent-type graph-rebuild factory. See that
module's own docstring for the design (reuses specialized_agents.py's
existing _load_agent_fn/_agent_call_kwargs; coverage is driven by which
run_* functions declare a resume_trace_id parameter).
"""

from __future__ import annotations

from app.fleet.resume_registry import is_resumable_agent_type, resolve_resume_call


def test_covered_agent_resolves_with_resume_trace_id_and_right_param_name() -> None:
    fn, kwargs = resolve_resume_call(
        "bug_fix",
        task_id=42,
        trace_id="trace-abc123",
        resume_message="please also fix the edge case",
        repo_path="/tmp/some-repo",
    )  # type: ignore[misc]
    assert fn.__name__ == "run_bug_fix"
    assert kwargs["task_id"] == 42
    assert kwargs["error_description"] == "please also fix the edge case"
    assert kwargs["repo_path"] == "/tmp/some-repo"
    assert kwargs["resume_trace_id"] == "trace-abc123"


def test_covered_agent_with_a_different_second_param_name_still_resolves() -> None:
    """readme_agent's real second parameter is `doc_request`, not
    `description` (the Day 53 bug _agent_call_kwargs itself exists to
    handle) — proves this registry inherits that correctness rather than
    hardcoding a param name of its own."""
    fn, kwargs = resolve_resume_call(
        "readme_agent",
        task_id=7,
        trace_id="trace-xyz",
        resume_message="also document the new endpoint",
        repo_path="/tmp/repo",
    )  # type: ignore[misc]
    assert fn.__name__ == "run_readme_agent"
    assert kwargs["doc_request"] == "also document the new endpoint"
    assert kwargs["resume_trace_id"] == "trace-xyz"


def test_uncovered_agent_returns_none_not_a_guess() -> None:
    """An agent whose wrapper hasn't been given a resume_trace_id parameter
    yet must return None — never a fabricated/best-effort call that would
    silently drop the resume intent (e.g. task_description would be
    overwritten with a follow-up note the agent has no way to actually
    resume with)."""
    # security_reviewer is a real, registered specialized agent that has NOT
    # been given resume_trace_id support in this batch.
    assert (
        resolve_resume_call(
            "security_reviewer",
            task_id=1,
            trace_id="t",
            resume_message="m",
            repo_path="/tmp",
        )
        is None
    )
    assert is_resumable_agent_type("security_reviewer") is False


def test_unknown_agent_name_returns_none() -> None:
    assert (
        resolve_resume_call(
            "not_a_real_agent_xyz",
            task_id=1,
            trace_id="t",
            resume_message="m",
            repo_path="/tmp",
        )
        is None
    )
    assert is_resumable_agent_type("not_a_real_agent_xyz") is False


def test_is_resumable_agent_type_true_for_every_agent_given_resume_support() -> None:
    for name in (
        "bug_fix",
        "readme_agent",
        "api_docs_agent",
        "sql_agent",
        "cleanup_agent",
        "cicd_agent",
    ):
        assert is_resumable_agent_type(name) is True, name
