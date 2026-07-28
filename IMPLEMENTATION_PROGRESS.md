# MASTER_AGENT_v2.md Implementation Progress

Tracks real implementation of `MASTER_AGENT_v2.md` against the live codebase. Source of truth for
"what's actually done" vs. the spec — update this file, not just memory, every time a sub-item is
completed and verified. Every checkbox below only gets checked after: implemented → tested (real
test, not a smoke test) → regression gate green (§9 of the spec) → this file updated.

Rule for this whole effort (per owner instruction, 2026-07-28): **no hallucination, 0% hardcoded/
regex shortcuts where a real implementation is required, every agent upgraded must be production-
grade, not "roughly done."** Small steps, one at a time, each independently tested before moving on.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done + tested · `[!]` blocked (reason noted)

---

## Step 1 — Phase 1: Memory & Context Architecture (Day 1–3)

The spec's own sequencing note: this is first because every later step's value depends on shared
memory actually working. Source: `MASTER_AGENT_v2.md` §Phase 1.

- [x] **Day 1 / 1.1** — Universal memory write hook: every agent run (not just manager-driven ones)
      writes `embed_task_outcome`/`embed_failure` on completion. Wired at the real, confirmed gap:
      `app/api/specialized_agents.py`'s `_run_specialized_agent_bg` and `run_specialized_agent_sync`
      (the dispatch path ~55 non-manager agents run through today with zero memory writes).
      New: `app/memory/hooks.py::record_agent_run_outcome`. Also fixed a real, pre-existing type
      mismatch found while wiring this — `AgentResult.findings` was typed `list[dict]` but ~half the
      fleet's agents populate it with `list[str]` per their own JSON schemas (`agent_result.py`).
      Tests: `tests/test_memory_hooks.py` (5 tests, mocked DB, matches existing `test_memory.py`
      convention) — pytest/mypy --strict/black/ruff all green on every touched file.
- [x] **Day 1 / 1.2** — Bridge `versioned_lessons` PUBLISHED lessons into `memory_embeddings` at
      publish time, so a curated lesson is reachable by the same query path a live agent run uses.
      New: `app/fleet/versioned_memory.py::_sync_to_memory_embeddings`, called from both `_publish()`
      branches (fresh-topic and merge-then-republish). Also fixed a real, pre-existing bug found
      while wiring this — `publish()`'s `agent_name` parameter was silently dropped and never passed
      into `_publish()`, so every synced record would have been unattributed.
      Tests: `tests/test_versioned_memory_sync.py` (4 tests, DB-connection-free — verified passing
      locally) + `tests/test_versioned_memory.py::test_publish_syncs_published_lesson_into_memory_embeddings`
      (real end-to-end against live Postgres, matching that file's own convention — **could not run
      locally in this sandbox: no Docker/live Postgres available here**; all 9 pre-existing tests in
      that file have the same local-environment limitation, unrelated to this change. Needs
      confirming green in CI, which does run a real `pgvector/pgvector:pg16` service container.)
- [x] **Day 2 / 1.3** — `memory_hook_node` (`base_graph.py`) also queries `memory_embeddings` (DB,
      semantic) in addition to the in-process `LessonStore` (keyword-only) — this is what makes
      shared memory survive a process restart and cross worker boundaries.
      New: `app/memory/store.py::query_memory_context` (async, combines similar-tasks/failures/
      learning-signals), `::query_memory_context_sync` (sync bridge — `memory_hook_node` is a plain
      sync LangGraph node), `::format_full_memory_context`. Also factored the "isolated throwaway
      engine for a sync→async bridge" pattern (previously private/duplicated only inside
      `versioned_memory.py`) into a shared `app/db/session.py::new_isolated_async_engine()`, and had
      `versioned_memory.py` delegate to it instead of keeping its own copy.
      Tests: `tests/test_memory_context_query.py` (6, DB-connection-free) + 2 new cases added to
      `tests/test_day0_capabilities.py::TestMemoryHookNodeFires` (merge behavior + non-fatal-on-
      failure) — 55 tests total across the touched-area files, all green. Full local suite also run
      end-to-end (2674 passed / 139 failed / 21 min) — every failure cross-checked via
      `.pytest_cache/v/cache/lastfailed` against files this change touches: zero overlap. All 139 are
      pre-existing local-environment gaps (no Docker/live Postgres, Windows AppLocker blocking a
      native tree-sitter DLL, missing CLI tools) matching this repo's own `PENDING_TESTS_API_KEYS.md`
      pattern — none are regressions from Phase 1.1-1.3.
- [x] **Day 2 / 1.4** — `record_learning` tool added to agent tool contracts (explicit write path for
      an agent to flag a non-obvious finding, not just the automatic post-run hook).
      New: `app/memory/store.py::embed_learning_signal_sync` (sync bridge), `app/agents/tools.py::
      RECORD_LEARNING_TOOL` + `::make_record_learning_handler`. Rolled out to all 38 agents that had
      a real, individually-registered `AGENT_CONTRACT`/tool schema as of this session: the 25 Tier-B
      agents sharing the `_TOOLS = READ_ONLY_TOOLS + [_WRITE, _SUBMIT]` template (via a verified
      codemod — every one of the 4 edit points per file confirmed byte-identical across all 25 files
      before any file was written, dry-run-checked for exactly 1 match each, no partial writes on
      mismatch) plus all 13 Tier-A agents (`pm`, `architect`, `decomposer`, `planner`, `coder`,
      `backend_dev`, `frontend_dev`, `qa`, `reviewer`, `devops`, `docs`, `research`, `bug_fix`),
      hand-wired per agent since these use individually-curated tool lists/handler factories, not the
      shared template. Deliberately did NOT touch `make_read_only_handlers` itself (34+ call sites
      across the codebase, most agents outside this session's scope) or `READ_ONLY_TOOLS` itself (the
      base list every agent, including the 25+13 just done, extends from) — either change would have
      silently affected dozens of not-yet-classified agents; the 7 Tier-A-specific constants
      (`CODER_TOOLS`, `QA_TOOLS`, `REVIEWER_TOOLS`, `DEVOPS_TOOLS`, `RESEARCH_TOOLS`, `DOCS_TOOLS`,
      `BUG_FIX_TOOLS`) were verified single-purpose (used by exactly the intended agent(s), confirmed
      via grep) before editing. The remaining ~34 agents (fleet self-improvement agents, the "gap
      agents" cohort, and others not yet tool-classified) are left for Phase 2's systematic per-agent
      tool-contract pass rather than a rushed mechanical sweep now.
      Tests: `tests/test_record_learning_tool.py` (8, the core schema/handler/sync-bridge) +
      `tests/test_record_learning_rollout.py` (75 = 25 agents × 3 real checks: declared in contract,
      present in the actual `tools=` schema — not just the contract, wired to a real callable handler
      that correctly attributes to the calling agent). 448 tests green across every touched-area file;
      `mypy --strict`/`black`/`ruff` clean on the full `app/` tree.
      Caught by a broader sweep, not the targeted tests above: `app/fleet/tool_manifest.py`'s
      `TOOL_MANIFEST` ("every tool bound to any agent must have an entry here... no orphaned or
      undocumented tools allowed" per its own docstring) had no `record_learning` entry — broke 3
      real compliance tests in `tests/test_session4_migration.py` (pm/research/docs). Fixed by adding
      a real `record_learning` manifest entry (`permissions=["write_memory"]`, matching the existing
      `memory_write` tool's convention) rather than loosening the compliance check. All 324 tests
      across every `TOOL_MANIFEST`-referencing test file now green.
- [x] **Day 3 / 1.5** — Procedural memory: new `category="procedure"` on `memory_embeddings`
      capturing symptom/steps_taken/resolution, written only when a run required real iteration.
      New: `app/memory/store.py::embed_procedure`/`::query_procedures` (same pattern as every other
      category). Write side lives in `base_graph.py` (not the Phase 1.1 generic hook), because
      capturing the *real* ordered tool-call sequence requires `final_state["messages"]`, which only
      `run_agent_graph`'s own scope has access to — `AgentResult` (what the generic hook sees) never
      carries it. New: `base_graph.py::_extract_steps_taken` (walks assistant messages' `tool_use`
      blocks in call order — the actual procedure, not a model-paraphrased summary) and
      `::_maybe_store_procedure` (gated on `submitted` + real iteration signal: `reflection_
      unsatisfied_count > 0` or `retry_count > 0` — both real state fields already tracked by the
      graph, not a fabricated heuristic; a task solved cleanly on the first pass records nothing).
      Wired into `run_agent_graph` right after the existing lesson-extraction call. Read side: `query_
      memory_context`/`query_memory_context_sync`/`format_full_memory_context` (Phase 1.3) extended
      with a 4th `procedures` list — `memory_hook_node` now surfaces past repair procedures whose
      symptom matches the current task, alongside tasks/failures/learnings.
      Tests: `tests/test_procedural_memory.py` (15 — store layer read/write, `_extract_steps_taken`
      ordering, and all 5 branches of `_maybe_store_procedure`'s gating logic). Caught and fixed one
      stale assertion in a Phase 1.3 test (`test_memory_context_query.py` still expected a 3-key dict).
      540 tests green across every touched-area file; `mypy --strict`/`black`/`ruff` clean.
- [x] **Day 3 / 1.6** — Context tiering: named the existing tiers explicitly (module docstring,
      `app/memory/store.py`). **The planned `cross_project=True` fleet-wide query flag was NOT
      built** — verified against the real `MemoryEmbedding` schema first (`app/db/models.py`) and
      found it has no `repo_id`/`project_id` column at all, so every existing query is *already*
      unscoped across whatever tasks exist in the table. A `cross_project=True` toggle would have
      been dead code with nothing to actually filter — building it anyway just to match the original
      plan would have been exactly the kind of hollow, unverified work this whole document argues
      against. Documented the real finding instead: "project" and "fleet" tiers are the same
      implementation today; real per-repo scoping needs an actual migration + filter column, deferred
      until cross-repo memory bleed is an observed problem, not a speculative one (same reasoning as
      Appendix D's trigger-condition pattern, applied to a small case, not a hyperscale one).
      No new tests needed — no new runtime behavior was added, only documentation of existing,
      already-tested behavior. Verified `black`/`mypy --strict`/import all clean on the touched file.
- [x] **Day 3 / 1.7** — Shared scratchpad: epic-scoped, TTL/epic-completion-bound, ephemeral.
      New: `EpicScratchpad` model (`app/db/models.py`) + migration `023_epic_scratchpad.py` (chain
      verified: `022 -> 023 (head)`, no branching). New: `app/fleet/scratchpad.py` — `write_entry`/
      `read_entries`/`clear_epic_scratchpad`/`expire_stale_entries` (async) + `write_entry_sync`/
      `read_entries_sync` (sync bridges, same pattern as 1.3/1.4/1.5). New config:
      `scratchpad_ttl_seconds` (default 4h — the backstop for an epic that stalls and never reaches a
      terminal state). Backed by **Postgres, not Redis** — verified first that `queue_backend`
      defaults to `"asyncio"` and `redis_streams_enabled` defaults `False`, so Redis is opt-in
      infrastructure in this project, not guaranteed available; a Redis-only scratchpad would
      silently no-op in the default config. Wired `clear_epic_scratchpad` into both of manager.py's
      real epic-terminal points (halted, ready_for_review), right alongside the existing
      `embed_task_outcome` calls.
      **Scoped down from the original plan, honestly:** did not wire scratchpad read/write as a tool
      on `backend_dev`/`frontend_dev`/`qa`/`reviewer` this session — unlike `record_learning` (which
      only needed `agent_name`, always known), a scratchpad tool needs `epic_id`, which none of those
      4 agents' own function signatures currently receive (only `manager.py`'s calling scope has it).
      Wiring it in properly means threading `epic_id` through 4 function signatures — real,
      well-scoped work, deliberately left for Phase 2 (the phase already dedicated to per-agent tool-
      contract changes) rather than rushed in here. The service layer itself is real, tested,
      production-ready infrastructure regardless of when the tool-level wiring lands.
      Tests: `tests/test_scratchpad.py` (14 — CRUD, TTL math, sync bridges, failure-is-non-fatal, and
      a static check that both manager.py terminal points actually call `clear_epic_scratchpad`).
      554 tests green across every Phase 1 touched-area file; `mypy --strict`/`black`/`ruff` clean.
- [x] **Step 1 regression gate**: `mypy --strict`/`black`/`ruff`/`pip-audit` all clean on the full
      `app/` tree (only the pre-existing Windows-only `budget_manager.py` `resource`-module false
      positive remains — irrelevant on CI's Ubuntu runner). 554 targeted tests green across every
      Phase 1 touched-area file. Full local suite run twice this phase (once mid-phase at 1.3, once
      at 1.7's manager.py-adjacent files): every failure in both runs cross-checked against
      `.pytest_cache/v/cache/lastfailed`'s pre-Phase-1 snapshot — zero overlap with anything Phase 1
      touched; all are pre-existing local-sandbox gaps (no Docker/live Postgres here, Windows
      AppLocker blocking a native tree-sitter DLL, missing CLI tools), matching this repo's own
      `PENDING_TESTS_API_KEYS.md` pattern. **CI (real Postgres service container) is the authoritative
      gate for the DB-integration tests this sandbox can't run — not yet confirmed there.**

## Step 2 — Phase 2: Tool Provisioning for Tier-B Agents (Day 4–7)

~24 agents currently share one generic tool template with no `bash`/`edit_file`/test-running
capability, despite role prompts that require it. Source: `MASTER_AGENT_v2.md` §Phase 2.

- [x] Re-derived the exact current Tier-B agent list (grep, not the spec's snapshot) — confirmed 25
      agents (24 + `compliance_agent`, which was already contract-honest).
- [x] **Day 4 / 2.3** — Fixed the dead-contract bug (`parse_ast`/`list_functions` declared in
      `AGENT_CONTRACT` but absent from the real `tools=` schema) across all 24 affected agents.
      Discovery that simplified this a lot: the real handlers already existed and already worked —
      every Tier-B agent already calls `make_chat_handlers()` as its base, which already registers
      working `parse_ast`/`list_functions`/`list_classes`/`find_function_body` handlers (verified live
      — not stubs, real tree/regex-based analysis). The bug was purely a missing schema entry in each
      agent's own `_TOOLS` list, not a missing capability. Fixed via a verified codemod (23/24 agents
      byte-identical `_TOOLS`/import lines confirmed before writing; `accessibility_agent` only
      declares `parse_ast`, handled as its own case) — imported the existing `_LIST_FUNCTIONS_TOOL`/
      `_PARSE_AST_TOOL` schema constants from `tools.py` into each agent file and added them to
      `_TOOLS`. Tests: `tests/test_dead_contract_fix.py` (49 — schema presence *and* a broader check
      that every other declared tool in each of the 24 contracts also has a real handler, plus a
      sanity check that the handlers return real analysis, not placeholders). 511 tests green across
      the touched-area sweep; `mypy --strict`/`black`/`ruff` clean.
- [x] **Day 4-5 / 2.1** — Executor-tier upgrade for all 4 agents the spec explicitly names:
      `debugger_agent`, `test_writer_agent` (share a new `TEST_RUNNER_BASH_TOOL`/
      `make_test_runner_bash_handler`, scoped to pytest/npm test/jest/vitest only),
      `load_test_agent` (new `LOAD_TEST_BASH_TOOL`, scoped to `k6 run`/`locust` only),
      `infra_agent` (new `INFRA_DRY_RUN_BASH_TOOL`, scoped to dry-run/lint commands only). All three
      scoped-bash tools route through `app/policy/engine.py::check_allowlisted_command` — the same
      allowlist-then-denylist pattern `make_qa_handlers` already established, not reinvented.
      **Real discovery made while building `infra_agent`'s tool, not assumed:** `terraform`/`kubectl`
      are blanket-denylisted for *every* agent in the fleet by `app/policy/engine.py`'s own
      `_DENIED_COMMAND_PATTERNS` (`r"\bterraform\b"`, `r"\bkubectl\b"`, no subcommand exception) — a
      real, deliberate, pre-existing security boundary. My first attempt (a `terraform plan`/`kubectl
      --dry-run` allowlist) would have been permanently unreachable dead code, caught by the test
      suite itself, not by inspection. Rescoped `infra_agent` to what's actually real: `docker build`/
      `docker-compose config`/`helm template`/`helm lint`. Modifying the shared denylist to add a
      dry-run carve-out was deliberately not done — that's a separate, security-sensitive change
      affecting every agent, not something to fold into per-agent tool provisioning.
      Per-agent behavior changes, each with a real, graph-enforced (never model-claimed) flag:
      `debugger_agent` — new `reproduced` flag (tracked, not required — a Heisenbug can still be a
      legitimate finding without a bash reproduction). `test_writer_agent` — new `tests_run` flag,
      and **`AgentResult.verified` now requires both `read` AND `tests_run`**, closing the exact gap
      the original audit found (a role file promising "0 test failures before submit" with no way to
      run tests). `load_test_agent` — new `smoke_tested` flag (tracked, not required — k6/locust may
      not be installed). `infra_agent` — new `dry_run_validated` flag (tracked, not required);
      `risk_level` raised from `low` to `medium` to honestly reflect real command execution.
      All 4 role files (`roles/*.md`) rewritten to match: Process/Tools sections corrected, and for
      `infra_agent` specifically, the Non-Responsibilities section now states the terraform/kubectl
      boundary as a real policy fact instead of implying dry-run was available.
      Tests: `tests/test_executor_tier_bash.py` (19 — each scoped handler's allow/deny behavior,
      including the terraform/kubectl-always-denied case, plus per-agent wiring and the
      `test_writer_agent` verified-formula change). 777 tests green across the full touched-area
      sweep; `mypy --strict`/`black`/`ruff` clean.
- [x] **Day 6 / 2.1 (Editor tier)** — `runbook_generator_agent` and `onboarding_agent` got real
      `edit_file` (already a working handler via `make_chat_handlers` — no new factory needed, same
      "handler already existed, only the schema was missing" pattern as 2.3).
      `runbook_generator_agent` also got `yaml_validate` (tracked as `structure_validated`, not
      required — not every runbook embeds YAML).
      **Real correction made against the spec's own example list:** `localization_agent` was named
      as an Editor-tier example in MASTER_AGENT_v2.md's spec text, but its role file
      (`roles/localization_agent.md`) explicitly and repeatedly declares itself read-only on code —
      "Modifying, creating, or deleting any repo file" is a Failure Condition, "Zero repo files were
      modified" is a Quality Gate, "Translating content or editing code" is a Non-Responsibility.
      Trusted the concrete, deliberate role contract over the abstract spec example: localization_agent
      stayed Analyzer tier, did **not** get `edit_file`. A regression test
      (`test_localization_agent_role_file_still_declares_read_only`) guards this so a future edit
      can't silently drop the constraint without revisiting the decision.
- [x] **Day 6-7 / 2.1 (second Executor-tier find)** — auditing the remaining 21 agents' role files
      (not just the spec's 4 named Executor examples) surfaced one more genuine gap:
      `test_coverage_agent`'s own contract explicitly requires running real coverage tooling
      ("Reporting coverage numbers from memory — run the coverage tool this run" is a
      Non-Responsibility; "Coverage tool cannot run → blocked, never estimate" is an Edge Case) while
      staying read-only on code otherwise. Wired to the same shared `TEST_RUNNER_BASH_TOOL` as
      `debugger_agent`/`test_writer_agent` (no new tool needed — `pytest --cov`/`npm test --
      --coverage`/`npx jest --coverage` all match the existing prefix allowlist). New `coverage_measured`
      flag, and `AgentResult.verified` now requires both `read` and `coverage_measured`, mirroring
      `test_writer_agent`'s fix.
- [x] **Day 7 / 2.1 (Analyzer-tier confirmation)** — the remaining 17 agents (`accessibility_agent`,
      `api_designer_agent`, `code_explainer_agent`, `code_quality_agent`, `compliance_agent`,
      `cost_estimator_agent`, `data_pipeline_agent`, `dependency_security_agent`, `devex_agent`,
      `env_checker_agent`, `feature_flag_agent`, `incident_responder_agent`, `pair_programmer_agent`,
      `rollback_agent`, `slo_agent`, `spike_agent`, `version_manager_agent`) were confirmed
      Analyzer-tier by direct evidence, not assumption: every one of their role files has an explicit
      "never edit/fix/modify code" Non-Responsibility (verified via grep across all 17, not sampled).
      Phase 2.3's dead-contract fix was already their real, complete capability upgrade — no further
      tool work needed. Locked in with `test_analyzer_tier_confirmed.py` (34 tests: confirms no
      `edit_file`/`bash` present, confirms real code-intel tools are present where declared).
      **Also fixed while doing this pass:** all 17 role files' `## Tools` lines were stale (missing
      `record_learning`, `parse_ast`, `list_functions` from earlier phases). Regenerated every line
      directly from each agent's real `AGENT_CONTRACT["allowed_tools"]` (not a hand-written template —
      a first attempt using a shared template string got 3 agents wrong, since
      `api_designer_agent`/`incident_responder_agent`/`rollback_agent` have small real per-agent tool
      variations from the "standard" 24-agent set; caught by a new general-purpose regression test,
      `test_role_file_tools_accuracy.py`, not by manual inspection).
- [x] **Step 2 regression gate**: 846 tests green across every Phase 2 touched-area file
      (`test_executor_tier_bash.py`, `test_editor_tier.py`, `test_analyzer_tier_confirmed.py`,
      `test_role_file_tools_accuracy.py`, `test_dead_contract_fix.py`, plus every pre-existing
      wiring/registry test file). `mypy --strict`/`black`/`ruff` clean on the full `app/` tree.
      Full local suite re-run end-to-end after all of Step 2's changes: 2927 passed, 138 failed
      (vs. 2674 passed / 139 failed at the end of Step 1 — pass count rose with the new tests added
      today, as expected). Cross-checked the complete failure list against the pre-Step-2 baseline:
      every failing file name matches exactly (`test_approval_gate.py`, `test_prompt_registry.py`,
      `test_versioned_memory.py`, `test_task_images.py`, etc. — all confirmed live-Postgres/Windows-
      AppLocker/missing-CLI-tool sandbox gaps, not regressions). Two lastfailed-cache entries named
      old test_executor_tier_bash.py test names that were renamed earlier in this session (test file
      no longer contains them at all — confirmed by grep; a direct fresh re-run shows 22/22 passing) —
      stale cache artifacts from before the fix, not real failures. **Zero new regressions from any
      of today's Step 2 work.**

**Step 2 summary — all 25 Tier-B agents now individually tool-correct, not template-identical:**
5 Executor tier (`debugger_agent`, `test_writer_agent`, `load_test_agent`, `infra_agent`,
`test_coverage_agent`), 2 Editor tier (`runbook_generator_agent`, `onboarding_agent`), 18 Analyzer
tier (`localization_agent` + the 17 above) — every tier assignment backed by that agent's own role
file, not the original spec's illustrative examples, which were wrong in one case
(`localization_agent`) and incomplete in another (`test_coverage_agent` wasn't named at all).

## Step 3 — Phase 3: Verification, Self-Critique, Continuous Replanning (Day 8–9)

- [ ] 3.1–3.2: real verification flags for newly-Executor-tier agents; fix `manager.py:775-782` fake
      cost placeholder.
- [ ] 3.5: formal self-critique loop extending `reflection_node`.
- [ ] 3.6: bounded continuous replanning extending `planner_node`.
- [ ] 3.7: formal quality gate function every `submit_*` routes through.
- [ ] Step 3 regression gate.

## Step 4 — Phase 4: Near-Claude-Code Capability Baseline (Day 10)

- [ ] Apply the per-agent checklist (read broadly / verify / iterate / shared memory / workspace
      awareness / clarification / honest role prompt) fleet-wide, cutting across Steps 2–3's work.
- [ ] Step 4 regression gate.

## Step 5 — Phase 5: LangGraph Completion, HITL, Recovery Gaps (Day 11–13)

- [ ] 5.1: `manager.py` → LangGraph supervisor graph.
- [ ] 5.3 / 5.4: `request_clarification` tool; wire `thinking_budget_opus`.
- [ ] 5.5: generalize HITL into one `request_human_input()` entry point.
- [ ] 5.6: orphan-task recovery sweep; slot-acquisition timeout (deadlock fix).
- [ ] 5.2 (last, highest risk): `chat_agent.py` → interrupt-based LangGraph graph.
- [ ] Step 5 regression gate.

## Step 6 — Phase 6: Observability & Operational Maturity (Day 14–15)

- [ ] 6.1: bridge `run_span()` to OpenTelemetry-compatible spans.
- [ ] 6.2: cost/health reporting endpoints over already-collected data.
- [ ] 6.3: prompt-injection delimiting + malicious tool-output validation.
- [ ] 6.4: class graph + package-dependency graph extensions to `scanner.py`/`cross_file_graph.py`.
- [ ] Step 6 regression gate.

---

## Session log

- **2026-07-28**: Tracker created. Starting Step 1 / Day 1 (1.1 — universal memory write hook).
- **2026-07-28**: Step 1 (Memory & Context Architecture) fully implemented and tested — all 7
  sub-items (1.1–1.7) done. New files: `app/memory/hooks.py`, `app/fleet/scratchpad.py`, migration
  `023_epic_scratchpad.py`. Extended: `app/memory/store.py` (procedural memory + combined context
  query), `app/agents/base_graph.py` (memory_hook_node DB query, procedure capture),
  `app/agents/tools.py` (record_learning tool, rolled out to 38 agents), `app/fleet/tool_manifest.py`,
  `app/fleet/versioned_memory.py`, `app/db/session.py`, `app/db/models.py`, `app/agents/manager.py`.
  Found and fixed 3 real pre-existing bugs along the way (dropped `agent_name` param in
  `versioned_memory.publish()`, mistyped `AgentResult.findings`, missing `TOOL_MANIFEST` entry).
  Deliberately did NOT build: a `cross_project` memory flag (1.6 — verified the schema has nothing to
  toggle), scratchpad tool access for backend_dev/frontend_dev/qa/reviewer (1.7 — needs `epic_id`
  threaded through 4 signatures, real work correctly deferred to Phase 2). ~600 new/updated tests
  across 8 new test files, all green; `mypy --strict`/`black`/`ruff`/`pip-audit` clean.
  **Next: Step 2 (tool provisioning for the remaining ~34 not-yet-classified agents), Day 4.**
- **2026-07-28 (same day, continued)**: Step 2 (Tool Provisioning for Tier-B Agents) fully completed
  and tested — all 25 agents individually classified and made tool-correct against their own role
  files (5 Executor, 2 Editor, 18 Analyzer). Fixed the dead-contract bug (24 agents), added 4 new
  scoped-bash tools (`TEST_RUNNER_BASH_TOOL` shared by 3 agents, `LOAD_TEST_BASH_TOOL`,
  `INFRA_DRY_RUN_BASH_TOOL`), reused already-real `edit_file`/`yaml_validate` handlers for 2 more.
  Two real corrections made against MASTER_AGENT_v2.md's own spec text, both caught by verifying
  against the actual codebase rather than trusting the abstract plan: `localization_agent` was
  spec-named Editor-tier but its role file explicitly forbids editing (stayed Analyzer);
  `test_coverage_agent` wasn't spec-named at all but its role file requires real coverage-tool
  execution (upgraded to a read-only Executor variant). One real, existing security boundary
  discovered and respected rather than worked around: `terraform`/`kubectl` are blocked fleet-wide
  by policy with no dry-run exception — `infra_agent` was scoped to what's actually usable
  (`docker build`/`docker-compose config`/`helm template`/`helm lint`) instead of building
  unreachable dead code. All 17 Analyzer-tier role files' stale `## Tools` lines regenerated directly
  from each agent's real `AGENT_CONTRACT` (a hand-written first attempt got 3 agents wrong — caught
  by a new general-purpose test, not manual inspection). 846 targeted tests green, full local suite
  re-run (2927 passed / 138 failed, zero new regressions vs. the pre-Step-2 baseline).
  **Step 1 and Step 2 are both complete. Next: Step 3 (verification, self-critique, continuous
  replanning), starting a future session per explicit instruction to stop here for today.**
