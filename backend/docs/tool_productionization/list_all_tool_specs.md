# Tool #219 — `list_all_tool_specs` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `list_all_tool_specs()` in `app/agents/tools.py`,
one of 3 Day-53 "real introspection, never a guess" tools alongside
`list_registered_agents` and `list_migrations`. Shared by exactly 1
real agent, confirmed via direct grep — `tool_catalog_doc_agent`,
matching `tool_inventory.json`'s `agent_count: 1` exactly. Deliberately
NOT in `CHAT_TOOLS` (confirmed via membership check). Takes no
meaningful input (`inp` is unused; schema declares no properties).

Its stated purpose, per its own schema description: "Real introspection
of every distinct tool schema defined in this codebase (name +
description), deduplicated by name — not a guess from grepping." Its
sole real caller uses this output as the mandatory, "real, complete,
deduplicated" source of truth for writing the tool catalog
documentation (`catalog_read` verification gate requires it to run
before `write_file`).

## Problems found

The implementation only ever scanned `dir(sys.modules[__name__])` —
i.e. only `app.agents.tools` itself, not "this codebase." Proved live
via a direct set-difference check against every module-level
tool-shaped dict (`{"name": ..., "input_schema": ...}`) found across
`app/agents/*.py` via AST parsing:

```
missing from list_all_tool_specs (before fix): 2
 - score_tech_options (in app.agents.tech_advisor_agent)
 - submit_fix (in app.agents.agent_performance_reviewer)
```

- `submit_fix` is tool #214's own shared schema/handler from this same
  initiative — unified across 4 real agent files
  (`agent_performance_reviewer`, `knowledge_curator`, `agent_debugger`,
  `quality_auditor`) but, unlike every other similarly-unified
  `submit_*` tool (`submit_docs`, `submit_bug_fix`, etc.), never given
  a re-export line inside `app.agents.tools` — an oversight in that
  earlier turn's migration, surfaced here.
- `score_tech_options` is a real, pre-existing tool
  (`tech_advisor_agent.py`-local) unrelated to any change made in this
  initiative — it was silently invisible to this introspection tool
  from before this initiative began.

Both are exactly the class of thing this tool exists to catch — a
real, agent-local tool schema that a doc-generation agent would never
know exists. This is a genuine functional defect in the tool's own
documented contract (not a hypothetical edge case), matching this
initiative's evidence-based, "found via real introspection, not
assumption" standard applied to the tool's own behavior.

Also confirmed via a separate AST-driven audit: all 83 module-level
tool-schema dicts that live under `app/tools/**/*.py` (the
category-organized modules this initiative has been extracting tools
into) ARE already correctly discovered, because every one of them is
re-exported into `app.agents.tools` — so this gap was specific to
agent-file-local schemas, not the ongoing modularization work.

## Changes made

Extracted the scanning logic into a small helper,
`_collect_tool_specs_from_module()`, then extended `list_all_tool_specs()`
to also import and scan every other `.py` file directly under
`app/agents/` (excluding `tools.py`, already scanned, and
`__init__.py`) — closing the root cause so any future agent-local-only
tool schema is discovered automatically, rather than special-casing
just the 2 known instances. Per-module import failures are caught and
skipped (mirrors `list_migrations`' existing "per-file failure is
skipped, not fatal" pattern) so one broken/unusual agent module can't
take down the whole introspection call. Result count grew from 230 to
278 real tool schemas (all newly-discovered entries verified to be
genuine agent-local tools, not duplicates or artifacts — confirmed via
a real-time dedup check).

## Tests

Existing `tests/test_gap53_doc_generators.py::TestListAllToolSpecs::test_returns_real_deduplicated_tool_specs`
re-run and confirmed passing unchanged (no fixed-count assertion, so
growing the result set doesn't break it) — full file (32 tests) also
re-run clean.

New file `tests/test_list_all_tool_specs_hardening.py`, 6 tests:
`CHAT_TOOLS` non-membership, still-deduplicated + pre-existing-tools
regression, direct proofs that `submit_fix` and `score_tech_options`
are now discovered, a sanity check that coverage genuinely broadened
(not just the 2 named cases), and an identity proof that
`tool_catalog_doc_agent`'s real handler dict still wires the exact
same function.

## Regression

This tool's own new hardening tests (6/6 pass) plus
`test_audit_q_batch10_deployment_external_git_docs.py` +
`test_day8_role_prompts.py` + `test_gap52_doc_agent_auto_trigger.py` +
`test_gap53_doc_generators.py` + `test_new_tools.py` +
`test_final_session.py` (343 passed total).

Verified via `mypy app/agents/tools.py` (clean) and `ruff check`
(clean) BEFORE claiming GREEN_FLAG. Also verified `CHAT_TOOLS` still
has zero duplicate names (186 entries) and that `app.agents.tools`
reloads cleanly. Execution time for the full call (importing every
`app/agents/*.py` module, most already cached from normal app startup)
measured at ~2.8s in isolation — negligible for a non-hot-path
documentation tool called once per catalog-doc-generation run.

## Final verdict

**GREEN FLAG.** Real functional defect found and fixed via evidence
(a direct AST-based audit proving exactly which real tools were
invisible, live before/after proof that both are now discovered). No
functionality lost — deduplication and all pre-existing entries
verified unchanged; only new, real, previously-hidden entries were
added. Agent alignment verified: PASS (sole consumer's handler wiring
confirmed unchanged by identity).
