"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #126/#146 "Step-by-Step Guidance
(dedicated renderer)").

Real role files (roles/*.md) already write a genuine numbered process list —
this parses it into a structured list instead of it only ever existing as
prose buried in the system prompt. No new content invented: a deterministic
markdown parse of what the role file's own author already wrote.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.agents.base import load_role
from app.agents.guidance import extract_guidance_steps


def test_extracts_the_real_numbered_process_from_bug_fix_role_file() -> None:
    steps = extract_guidance_steps(load_role("bug_fix"))
    assert len(steps) == 6
    assert steps[0].startswith("Understand the error")
    assert "**" not in steps[0]  # markdown bold stripped


def test_extracts_the_real_bold_step_convention_from_qa_role_file() -> None:
    """roles/qa.md uses '**Step N — label**: rest' instead of a plain 'N.'
    list — the other real numbering convention in this codebase's role
    files (13 of them), which needs its own parse path."""
    steps = extract_guidance_steps(load_role("qa"))
    assert len(steps) == 8
    assert steps[0].startswith("Read the subtask and changed files")
    assert "**" not in steps[0]


def test_returns_empty_for_a_role_file_with_no_process_section() -> None:
    """security_reviewer.md has a review CHECKLIST (unordered categories to
    check), not a sequential numbered process — an honest [] is correct
    here, not a forced/fabricated match."""
    steps = extract_guidance_steps(load_role("security_reviewer"))
    assert steps == []


def test_caps_step_count_and_length() -> None:
    lines = "\n".join(f"{i}. " + ("x" * 300) for i in range(1, 40))
    markdown = f"## Process\n{lines}\n## Next Section\nignored"
    steps = extract_guidance_steps(markdown)
    assert len(steps) == 20
    assert all(len(s) <= 200 for s in steps)


def test_stops_at_the_next_heading_not_a_later_unrelated_numbered_list() -> None:
    markdown = (
        "## Process\n1. real step one\n2. real step two\n"
        "## Unrelated Section\n1. not a real step\n2. also not real\n"
    )
    steps = extract_guidance_steps(markdown)
    assert steps == ["real step one", "real step two"]


def test_run_bug_fix_surfaces_real_guidance_steps_on_agent_result() -> None:
    from app.agents.bug_fix import run_bug_fix

    with (
        patch("app.agents.bug_fix.make_bug_fix_handlers", return_value={}),
        patch("app.agents.bug_fix.run_agent_graph") as mock_run,
    ):
        mock_run.return_value = {
            "submitted": True,
            "tokens_in": 10,
            "tokens_out": 5,
            "verification": {"tests_passed": True},
            "result": {
                "root_cause": "x",
                "fix_summary": "y",
                "files_changed": [],
                "_guidance_steps": ["step one", "step two"],
            },
        }
        result = run_bug_fix(task_id=1, error_description="boom")

    assert result.guidance_steps == ["step one", "step two"]


def test_run_agent_graph_computes_guidance_steps_from_the_real_role_file() -> None:
    """End-to-end at the graph level (not mocked at the wrapper boundary):
    run_agent_graph() itself attaches _guidance_steps to final_state
    ["result"], sourced from the SAME load_role() every real caller uses."""
    from types import SimpleNamespace

    from app.agents.base_graph import VerificationConfig, run_agent_graph

    with (
        patch(
            "app.agents.base_graph.load_role",
            return_value=(
                "## Process\n1. do the first thing\n2. do the second thing\n"
            ),
        ),
        patch("anthropic.Anthropic") as mock_anthropic_cls,
    ):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="tu1",
                    name="submit_result",
                    input={"summary": "done"},
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="t2b3_guidance_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[
                {
                    "name": "submit_result",
                    "description": "Submit",
                    "input_schema": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                }
            ],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_critique=False,
            enable_replanning=False,
            max_turns=5,
            enable_run_tracking=False,
        )

    assert final_state["result"]["_guidance_steps"] == [
        "do the first thing",
        "do the second thing",
    ]
