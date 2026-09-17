# Tool #234 — `submit_architect_plan` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_architect_plan` lives entirely in `app/agents/architect.py`.
Unlike most agents in this initiative's recent turns, `architect`
doesn't run through `make_chat_handlers()`/interactive chat at all —
it's a dedicated `app/pipeline/graph.py` node (`architect_node`)
called directly by the main task pipeline. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check). Confirmed single
implementation — no duplicate anywhere in `chat_agent.py` or
`app.agents.tools` (the one other reference, in
`app/pipeline/conflict_guard.py`, is a comment only).

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion. The handler itself is a trivial no-op:

```python
handlers["submit_architect_plan"] = lambda inp: "Architect plan submitted"
```

This is **intentional, correct design, not dead code** — confirmed by
direct inspection of `architect_node`'s own body:
`plan_result = final_state.get("result", {})` reads directly from
`final_state["result"]`, which `base_graph.py`'s generic `submit_*`
capture mechanism (`state["result"] = dict(tu_input)`) populates
automatically for any tool whose name starts with `submit_`. The
lambda's return value is only the tool-call confirmation text the LLM
sees in its own conversation — never a data path. This matches the
same "genuinely relies on the generic capture, not a dead
accumulator" pattern already confirmed correct on several other
tools in this initiative.

Because the lambda ignores `inp` entirely, there is no possible input
shape that can make it raise — proved by exercising it with 7
different malformed/adversarial input shapes (empty dict, `None`
values, wrong types, non-dict, non-object) and confirming an identical
safe return every time.

The surrounding `architect_node` logic (repo-id resolution for
`embed_architecture_note_sync`, `clean_plan` key-stripping) was also
reviewed — already defensively guarded (`except (ValueError,
TypeError)` around the numeric task-id coercion, broad `except
Exception` around the best-effort memory-write call) with no
additional crash paths found.

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 12 files reference `architect`/`architect_node`/
`submit_architect_plan` — the 5 most directly relevant
(`test_architecture_note_wiring.py`, `test_session1_migration.py`,
`test_day1_agent_flags.py`, `test_day2_agent_contracts.py`,
`test_day2_agents.py`) re-run and confirmed passing unchanged (46
architect-related tests).

New file `tests/test_submit_architect_plan_hardening.py`, 4 tests:
schema check, `CHAT_TOOLS` non-membership, a direct proof that the
handler's own no-op lambda never crashes across 7 malformed input
shapes, and an `AGENT_CONTRACT` wiring regression.

## Regression

This tool's own new hardening tests (4/4 pass) plus the 5 existing
architect-adjacent test files (46 tests) + `test_new_tools.py` +
`test_final_session.py` (317 passed total).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. The tool's apparent triviality was specifically
verified to be intentional correct design (relying on `base_graph.py`'s
real, generic capture mechanism) rather than assumed safe. No
functionality lost or changed. Agent alignment verified: PASS.
