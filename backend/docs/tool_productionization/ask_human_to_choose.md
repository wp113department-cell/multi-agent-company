# Tool #217 — `ask_human_to_choose` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Chat-only tool (in `CHAT_TOOLS`, `agent_count: 1` matching
`tool_inventory.json` — the chat agent itself). Schema lives at
`app/agents/tools.py::_ASK_HUMAN_TO_CHOOSE_TOOL`; dispatch is entirely
in `ChatAgent._execute_tool()` (`app/agents/chat_agent.py`), which
validates the input then pauses the graph via `_confirm_with_options()`
— a genuinely different decision shape from the existing binary
approve/deny `_confirm()` gate, reusing the same real
`interrupt()`/`Command(resume=...)` pause primitive (added for
AUDIT_Q_BATCH07 §13).

Already has thorough end-to-end test coverage in
`tests/test_audit_q_batch07_guardian_human_interaction.py`
(`TestAskHumanToChoose`): full pause/resume cycle with a real
selection, decline-is-cancelled-not-a-random-pick, and a stale/invalid
`selected` id from a resume payload being ignored rather than trusted
— read and re-verified as still passing before making any change.

## Problems found

One real finding: `ahtc_question = str(inp["question"]).strip()` used
direct dict indexing instead of `.get(...)`. The schema marks
`question` as `required`, but nothing enforces that at runtime — an
LLM (especially a local/weaker model, or any client that doesn't
strictly validate tool-call arguments against the schema) can omit a
required field. Proved live via a direct `_execute_tool()` call with
no `question` key:

```
$ python -c "... await agent._execute_tool('ask_human_to_choose', {'options': [...]})"
UNCAUGHT: KeyError 'question'
```

The graph's outer generic exception handler in
`_execute_tool_node` (`except Exception as e: result = f"[ERROR] Tool
{tu['name']} failed: {e}"`) does prevent this from crashing the whole
turn, but the LLM would see the confusing
`"[ERROR] Tool ask_human_to_choose failed: 'question'"` instead of the
clean, already-implemented `"[ERROR] question is required."` message
on the very next line of the same function — a real, avoidable
robustness gap, the same class already found and fixed on numerous
other tools in this initiative (bare `inp[...]` instead of
`inp.get(...)`).

All other input handling in this branch was already correct:
`ahtc_options = inp.get("options")` uses `.get()`, each option's
`opt.get("description", "")` is safe, and `id`/`label` presence is
explicitly checked with `"id" not in opt or "label" not in opt` before
being trusted. The resume-side validation (`raw_selected` checked
against `valid_ids` before being accepted) was also re-verified — no
issue found there.

Noted but NOT changed: the schema's description says "2-5 distinct
choices," but the code only enforces a minimum of 2, no maximum of 5.
This has no crash or security impact (no injection surface — the
option list only flows to `session.push()` for UI rendering and into
the `interrupt()` payload) and matches this initiative's "don't add
validation for scenarios that don't cause a real problem" standard —
recorded here for completeness, not fixed.

## Changes made

`app/agents/chat_agent.py`: changed `inp["question"]` to
`inp.get("question", "")`, matching the pattern already used
everywhere else in this same dispatch branch. No other line changed.

## Tests

Existing `TestAskHumanToChoose`'s 3 tests (full pause/resume,
decline-cancelled, stale-selection-ignored) re-run and confirmed
passing unchanged, plus the full `test_audit_q_batch07_guardian_human_interaction.py`
suite (27 tests).

New file `tests/test_ask_human_to_choose_hardening.py`, 6 tests:
`CHAT_TOOLS` membership, the missing-`question`-key proof (now
returns the clean error instead of raising), empty-string `question`,
missing `options`, single-option (below the 2-minimum), and an option
missing `id`/`label`.

## Regression

This tool's own new hardening tests (6/6 pass) plus
`test_audit_q_batch07_guardian_human_interaction.py` (27 passed),
`test_new_tools.py` + `test_final_session.py` (94 passed combined),
and the broader `chat_agent.py`-adjacent suite —
`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_chat_agent_memory_wiring.py`,
`test_gap16_chat_agent_verification_gate.py` (26 passed) — run because
`chat_agent.py` is a large, widely-shared file.

Verified via `mypy app/agents/chat_agent.py` (clean) and `ruff check`
on both touched files (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Real robustness gap found and fixed via evidence (live
reproduction before the fix, live proof of the clean error message
after). No functionality lost or changed for well-formed calls — all
pre-existing end-to-end tests (pause/resume, decline, stale-selection)
still pass unchanged. Agent alignment verified: PASS (sole consumer is
the chat agent itself).
