# Tool #236 — `submit_changelog` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_changelog` lives entirely in `app/agents/changelog_agent.py`.
Shared by exactly 1 real agent, confirmed via direct grep —
`changelog_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check).

**Investigated and RULED OUT** the same `write_file`-scoping finding
class just fixed on sibling tools #231/#232: unlike those agents,
`changelog_agent`'s own `AGENT_CONTRACT` explicitly claims
`permissions=["read_repo", "write_repo"]` (not `"write_docs"`), and
`roles/changelog_agent.md`'s Non-Responsibilities section only
excludes "editing code or release artifacts" as a design guideline —
never an absolute file-system lockout like #231/#232's explicit "any
repo file modification = automatic Failure." This agent's whole job is
writing `CHANGELOG.md`, and its contract accurately reflects the
broader write access it legitimately needs. No contradiction to fix.

## Problems found

Two real, separate uncaught-crash paths, in both `submit_changelog_h`
**and** `run_changelog_agent`'s own near-identical post-processing
(neither validated `sections` before aggregating it):

```python
sections = inp.get("sections", {})
total = sum(sections.values()) if sections else 0
```

Proved live, before any fix:

```
sections={"added": "not-a-number"}  → uncaught TypeError: unsupported operand type(s) for +: 'int' and 'str'
sections=["not", "a", "dict"]       → uncaught AttributeError: 'list' object has no attribute 'values'
```

Neither the tool's declared JSON schema (never runtime-enforced — an
LLM or malformed client can send anything) nor any `try`/`except` at
either call site prevented this.

## Changes made

Added one shared, defensive helper, `_sum_section_counts(sections)`,
used by both `submit_changelog_h` and `run_changelog_agent`: a
non-dict `sections` value becomes a safe empty dict (so any downstream
`.items()`/`.values()` call stays safe), and each per-section value is
coerced via its own `try: total += int(v) except (TypeError,
ValueError): continue` — a non-numeric value is skipped rather than
crashing the whole aggregation, giving partial credit for the valid
entries instead of an all-or-nothing failure. All legitimate,
well-formed calls produce byte-identical output to before.

## Tests

Existing tests across 6 files re-run and confirmed passing unchanged
(40 changelog-related tests).

New file `tests/test_submit_changelog_hardening.py`, 8 tests: schema
check, `CHAT_TOOLS` non-membership, both crash-path proofs via the
real `submit_changelog` handler, two direct proofs of
`_sum_section_counts()`'s behavior (`None` input, mixed valid/invalid
values), a legitimate well-formed-sections regression, and a proof
that `write_file`'s intentionally broader scope for this specific
agent is correct (not the same finding class as #231/#232).

## Regression

This tool's own new hardening tests (8/8 pass) plus the 6 existing
test files (40 tests) + `test_new_tools.py` + `test_final_session.py`
(460 passed total).

Verified via `mypy app/agents/changelog_agent.py` (clean) and `ruff
check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified crash paths found and
fixed via evidence (live reproduction before the fix, live proof of
graceful, partial-credit aggregation after) — fixed once, shared by
both real call sites, rather than duplicating the guard. Also
correctly ruled out a superficially-similar finding class from
sibling tools after actually reading this agent's own contract and
role file, rather than blindly pattern-matching. No functionality
lost — legitimate changelog submission and `CHANGELOG.md` writing both
re-verified correct. Agent alignment verified: PASS.
