# Fleet Day 8 Test Report — Role Prompt Upgrades
Date: 2026-07-20

## Repo-first research (per CLAUDE.md's REPO-FIRST rule, done before touching any file)

Read `repos/roo-code/src/core/prompts/system.ts` + `repos/roo-code/src/core/prompts/sections/`
— roo-code assembles its production system prompt from modular section functions
(role definition, rules, objective, capabilities, tool-use-guidelines, custom-instructions).
This validates the shape of our own design: a shared constitution (`_GLOBAL_STANDARDS.md`)
composed with role-specific content at runtime (`load_role()` in `app/agents/base.py`),
rather than duplicating boilerplate into every file. One difference, arguably a stronger
choice for a multi-agent graph system: roo-code bakes its "Objective" (plan → act →
verify loop) as static prose repeated in the prompt; we instead implement the equivalent
loop as real LangGraph nodes (`planner_node`, `reflection_node`, `lesson_node` in
`base_graph.py`) — behavior enforced in code, not just requested in prose.

## What Day 8 actually needed

Plan's Day 8 goal: append a 9-section master template (Understanding First → Production
Quality) to all 68 role files. This was already superseded outside the day-by-day plan by
the 2026-07-20 v2.0 role-prompt overhaul (commit `b5778bb`), which replaced the
byte-identical 9-section boilerplate (previously copy-pasted into all 67 files) with:
- `backend/roles/_GLOBAL_STANDARDS.md` — an 11-section constitution, loaded once and
  prepended to every agent's system prompt at runtime by `load_role()`
- 7 role-specific sections per file: Non-Responsibilities, Success Criteria, Failure
  Conditions, Output Contract, Quality Gates, Edge Cases, Escalation

## Verification performed (not assumed)

Before this session, "Day 8 is done" was an inference from reading the v2.0 commit message —
never actually checked against the plan's literal 9 required sections, and there was **zero
existing automated test coverage** for role-prompt structure at all (confirmed via
`grep -rln "_GLOBAL_STANDARDS\|role_prompt\|9-section" tests/*.py` → no matches).

Did a manual line-by-line diff of each of the plan's 9 sections against
`_GLOBAL_STANDARDS.md`'s content (not just headers, since v2.0 folded some into numbered
steps under "Operating Loop" rather than keeping them as separate `##` headers):

| Plan's original section | Found in `_GLOBAL_STANDARDS.md` | Match |
|---|---|---|
| Understanding First | §1 Operating Loop, step 1 (UNDERSTAND) — near-verbatim | ✅ |
| Instruction Analysis | §1 Operating Loop, step 1 (same paragraph) — near-verbatim | ✅ |
| Smart Planning | §1 Operating Loop, step 2 (PLAN) — verbatim | ✅ |
| Context Use | §3 Context Management, final bullet — verbatim | ✅ |
| Credential Safety | §5 Security Guidelines, first bullet — near-verbatim | ✅ |
| Verification | §1 Operating Loop, step 5 (VERIFY) — verbatim | ✅ |
| Honest Errors | §7 Error Handling & Honest Errors — verbatim | ✅ |
| Self Review | §1 Operating Loop, step 6 (SELF-REVIEW) — verbatim + 1 extra question | ✅ |
| Production Quality | §11 Production Quality Bar — verbatim + extra | ✅ |

All 9 present. v2.0 adds 6 more sections beyond the original 9 (Anti-Hallucination,
Engineering Principles, Reasoning Guidelines, Escalation, Communication, Output Contract
Discipline) — a genuine superset, not a lossy rename.

Then closed the actual gap this session found: **wrote a durable, automated test** so this
isn't a one-time manual check that silently rots — `tests/test_day8_role_prompts.py`:
- `test_role_file_count_is_67` — catches drift in the agent roster
- `test_global_standards_covers_original_9_sections` (9 parametrized cases) — asserts the
  plan's 9 required phrases are present in `_GLOBAL_STANDARDS.md`
- `test_role_file_has_all_role_specific_sections` (67 parametrized cases) — every role file
  has all 7 role-specific sections
- `test_load_role_prepends_global_standards_at_runtime` (67 parametrized cases) — **functional**
  check that `load_role()` actually composes the full prompt at runtime, not just that the
  files exist on disk

**145/145 new tests pass.**

## Ground truth after this session

```
pytest tests/ -q -p no:cacheprovider
→ 2399 passed, 0 failed, 55 skipped, 17 deselected, 3 warnings in 42.69s
```
(2254 from the Day 7 baseline + 145 new Day 8 tests.)

## Verdict

✅ **GREEN FLAG — DAY 8 COMPLETE**: All 68 role files (67 real agents, verified count) carry
the plan's required content — confirmed as a genuine superset, not just claimed. Test
coverage for role-prompt structure went from 0 to 145 durable, automated checks. 2399/2399
tests pass, 0 failed. Ready for Day 9.
