"""submit_bug_fix tool #211 — tool_enhance.md productionization pass
(2026-09-16).

Two real findings on the one real implementation (`bf_submit` inside
`make_bug_fix_handlers`).

1. Dead-code accumulator, never actually read — same class as sibling
   tools #180-#186/#188-#192/#194/#196-#201. Real result-capture lives
   entirely in base_graph.py's generic submit_* handling
   (bug_fix.py reads final_state["result"], not _bug_fix_result).
2. `app.agents.bug_fix.AGENT_CONTRACT["allowed_tools"]` declared a
   tool `bug_fix` cannot actually call ("submit_patch" — no such
   handler exists in `make_bug_fix_handlers()`) and a tool it doesn't
   have ("bash" — also absent from both the real handler factory and
   the real `BUG_FIX_TOOLS` runtime tool list) while OMITTING the tool
   it actually uses (`submit_bug_fix`). The real runtime tool list
   (`BUG_FIX_TOOLS`, what `run_bug_fix()` actually passes to
   `run_agent_graph()`) was always correct — only the separate,
   secondary `AGENT_CONTRACT["allowed_tools"]` metadata (used for
   fleet capability-registry registration) was stale.

Not in CHAT_TOOLS — confirmed intentional (bug_fix is a batch agent,
never exposed to interactive chat).

Separately noted, NOT fixed here (out of scope for this tool's own
turn): `bug_fix`'s role prompt instructs "Run run_tests to verify the
fix — this is MANDATORY before submit," and
`_VERIFICATION_CFG.enforce_in_result` overrides `tests_passed` based
on whether a real `run_tests` call fired — but `run_tests` is not
actually in `BUG_FIX_TOOLS`, so this verification can never fire in
practice. A real, significant gap, but about `run_tests`'s own
agent-wiring completeness, not this tool — flagged in
`bhaskar_next/tool_enhance_tracking.md` for a dedicated future turn.
"""

from __future__ import annotations

from app.agents.bug_fix import AGENT_CONTRACT
from app.agents.tools import (
    BUG_FIX_TOOLS,
    CHAT_TOOLS,
    make_bug_fix_handlers,
)
from app.fleet.tool_manifest import TOOL_MANIFEST
from app.tools.agents.submit_bug_fix import (
    SUBMIT_BUG_FIX_TOOL,
    submit_bug_fix_handler,
)


def test_submit_bug_fix_tool_schema() -> None:
    assert SUBMIT_BUG_FIX_TOOL["name"] == "submit_bug_fix"
    assert SUBMIT_BUG_FIX_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "root_cause",
        "fix_summary",
        "files_changed",
    ]


def test_submit_bug_fix_appears_exactly_once_in_bug_fix_tools() -> None:
    names = [t["name"] for t in BUG_FIX_TOOLS]
    assert names.count("submit_bug_fix") == 1


def test_submit_bug_fix_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_bug_fix" not in names


# ---------------------------------------------------------------------------
# Finding #1 — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_bug_fix_result_key_exported(self) -> None:
        handlers = make_bug_fix_handlers("/tmp")
        assert "_bug_fix_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_bug_fix_handler(
            {"root_cause": "off-by-one", "fix_summary": "fix", "files_changed": []}
        )
        assert out == "Bug fix submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_bug_fix_handler({})
        out_full = submit_bug_fix_handler(
            {
                "root_cause": "x",
                "fix_summary": "y",
                "files_changed": ["a.py", "b.py"],
                "tests_passed": True,
            }
        )
        assert out_minimal == out_full == "Bug fix submitted"


# ---------------------------------------------------------------------------
# Finding #2 — AGENT_CONTRACT["allowed_tools"] corrected
# ---------------------------------------------------------------------------


class TestAgentContractCorrected:
    def test_allowed_tools_declares_submit_bug_fix_not_submit_patch(self) -> None:
        allowed = AGENT_CONTRACT["allowed_tools"]
        assert "submit_bug_fix" in allowed
        assert "submit_patch" not in allowed

    def test_allowed_tools_no_longer_falsely_claims_bash(self) -> None:
        """bash is in neither make_bug_fix_handlers()'s real handler
        dict nor the real BUG_FIX_TOOLS runtime tool list — the
        contract must not claim it either."""
        assert "bash" not in AGENT_CONTRACT["allowed_tools"]
        handlers = make_bug_fix_handlers("/tmp")
        assert "bash" not in handlers
        names = [t["name"] for t in BUG_FIX_TOOLS]
        assert "bash" not in names

    def test_allowed_tools_matches_real_bug_fix_handlers_capability(self) -> None:
        """Every non-inherited tool the contract claims must actually
        have a real handler (directly or via the shared read-only
        bundle)."""
        handlers = make_bug_fix_handlers("/tmp")
        for tool in AGENT_CONTRACT["allowed_tools"]:
            if tool == "delegate_to_agent":
                continue  # wired separately, per-call, in run_bug_fix()
            if tool == "record_learning":
                continue  # wired separately, per-call, in run_bug_fix()
            assert tool in handlers, f"AGENT_CONTRACT claims {tool!r} but no real handler exists"

    def test_contract_still_declares_all_tools_in_manifest(self) -> None:
        for tool in AGENT_CONTRACT["allowed_tools"]:
            assert tool in TOOL_MANIFEST, f"{tool!r} has no TOOL_MANIFEST entry"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_bug_fix_handlers_wires_submit_bug_fix(self) -> None:
        handlers = make_bug_fix_handlers("/tmp")
        assert "submit_bug_fix" in handlers
        out = handlers["submit_bug_fix"]({"root_cause": "x", "fix_summary": "y"})
        assert out == "Bug fix submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_bug_fix_handlers("/tmp")
        out1 = handlers["submit_bug_fix"]({"root_cause": "first"})
        out2 = handlers["submit_bug_fix"]({"root_cause": "second"})
        assert out1 == out2 == "Bug fix submitted"

    def test_other_bug_fix_handlers_unaffected(self) -> None:
        handlers = make_bug_fix_handlers("/tmp")
        for key in (
            "parse_ast",
            "call_graph",
            "find_function_body",
            "analyze_error",
            "read_logs",
            "edit_file",
            "write_file",
            "git_diff",
            "submit_bug_fix",
        ):
            assert key in handlers
