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

- [x] **3.2** — Fixed `manager.py`'s fake epic `cost_actual` placeholder. Real root cause was deeper
      than the spec assumed: `agent_runs` (the table the spec's own text says to aggregate) is **not
      populated at all** for manager-dispatched subtask agents (`create_agent_run` has exactly 2 real
      call sites, both in `app/api/agents.py`'s standalone `launch_planner`/`launch_coder` endpoints —
      confirmed by grep, not assumed) — querying it would have returned nothing or the wrong epic's
      data. The real numbers were one layer up: `backend_dev.py`/`frontend_dev.py` already computed
      real `tokens_in`/`tokens_out` per attempt (for a log line) and then **discarded them** at every
      `return` statement (2-tuple, not 4 like `coder.py`'s own already-correct convention);
      `qa.py`/`reviewer.py`'s result dataclasses didn't carry token fields at all. Fixed at the real
      source: `run_backend_dev`/`run_frontend_dev` now return `(files_changed, error, tokens_in,
      tokens_out)` (accumulated across every retry attempt, matching `coder.py`'s pattern exactly);
      `QAResult`/`ReviewResult` gained `tokens_in`/`tokens_out` fields; `run_manager`'s dispatch loop
      accumulates all of dev+qa+reviewer's real tokens into an epic-wide total and returns it;
      `_run_epic_manager_body` computes `cost_actual` via a new pure `compute_actual_cost_usd()`
      function using the exact same `$/token` formula `cost_controller.py`'s own `estimate_epic_cost()`
      already uses (so the pre-run estimate and post-run actual are consistent). Also updated
      `app/pipeline/dispatcher.py` (a second, independent caller of the same 4 functions) and fixed
      `backend_dev`/`frontend_dev`'s `AGENT_CONTRACT["output_types"]` to honestly list `tokens_in`/
      `tokens_out`, matching `coder.py`'s existing convention.
      **Real regressions found and fixed, not just new tests added:** this return-signature change
      broke 11 pre-existing test files that mocked `run_backend_dev`/`run_frontend_dev` with the old
      2-tuple shape (`test_agent_registry.py`, `test_audit04_orchestration_fixes.py` [4 sites],
      `test_day12_smoke_test.py`, `test_failure_ladder.py`, `test_gap_closure_days0_18.py`,
      `test_hierarchy_chain.py`, `test_day18_streaming_wiring.py`, `test_session2_migration.py`,
      `test_task_images.py`, `test_dispatcher.py`) — every site found via exhaustive grep (not
      sampling) and fixed to the new 4-tuple shape, several with new assertions confirming real token
      values flow through end to end.
      Tests: `tests/test_epic_cost_actual.py` (4 — the pure cost formula, and a regression guard that
      the literal `sqlfunc.sum(DevTask.id)` bug pattern can't reappear) + 2 new assertions in
      `tests/test_manager_git_commit.py` confirming `run_manager()`'s real accumulated total
      (100+20+15 in, 50+10+5 out = 135/65) + 3 new assertions in `tests/test_dispatcher.py`. 367 tests
      green across every touched-area file; `mypy --strict`/`black`/`ruff` clean on the full `app/`
      tree.
- [x] **3.1** — Confirmation audit for the 5 Step-2 Executor-tier agents (not new work — each flag
      was already graph-enforced when Step 2 added the tool). New: `tests/test_phase3_verification_audit.py`
      (8 tests) — confirms all 5 agents' `"bash"` tool maps to a real `VerificationConfig.set_by` key
      starting `False`, and for the 2 agents where the flag is load-bearing (`test_writer_agent`,
      `test_coverage_agent`), confirms via source inspection that `AgentResult.verified` actually
      reads it. A permanent regression guard, not just a one-time check.
- [x] **3.5** — Formal self-critique loop: new `critique_node` in `base_graph.py`, extending the
      existing reflection pattern rather than duplicating it. Fires once per submission (not once per
      tool turn like `reflection_node`), scores the just-submitted work against the agent's OWN role
      file's real `## Quality Gates`/`## Success Criteria` bullets (`_extract_role_criteria` — real
      text extraction from the role's actual prompt, confirmed against the live `roles/backend_dev.md`
      file, never a fabricated per-agent checklist), and requires the scoring LLM call to cite real
      evidence — the actual `state["verification"]` dict and the actual submitted `state["result"]`,
      both embedded verbatim in the prompt — for every `{criterion, met, evidence}` entry, not a bare
      claim. **Improve step reuses existing machinery, no new control flow**: when unsatisfied, the
      node resets `submitted=False` and appends a `[Critique]` message; the existing
      `call_llm`→`execute_tools` loop (already bounded by `max_turns`) does the retry. A second, purpose-
      built bound (`max_critique_retries`, default 1) additionally caps critique-driven retries
      specifically, so an unsatisfiable or flaky critique call can never loop forever even before
      `max_turns` would catch it — verified directly by
      `test_graph_critique_never_satisfied_is_bounded_by_max_critique_retries` (an always-unsatisfied
      mock critique response still terminates after exactly 1 retry).
      Graph wiring: `execute_tools`'s edge to `call_llm` became conditional
      (`_post_execute_tools_router`) — a fresh submission now routes to `critique_node` first; a new
      `_post_critique_router` sends it to `END` (satisfied, or budget exhausted) or back to `call_llm`
      (unsatisfied, budget remains). This closes a real pre-existing inefficiency as a side effect for
      agents that opt in: previously `execute_tools→call_llm` was unconditional, so the graph always
      spent one extra, fully-discarded LLM call after every submission before the router (which only
      runs after `call_llm`) ever saw `submitted=True` — confirmed by
      `test_graph_critique_satisfied_first_try_ends_immediately` (1 main-turn LLM call with critique
      enabled) vs. `test_graph_critique_disabled_by_default_preserves_prior_behavior` (2 main-turn LLM
      calls with it off — the pre-existing wasted-call behavior, intentionally left unchanged for the
      default path since fixing it fleet-wide is out of this task's scope).
      **Rollout decision**: `enable_critique` defaults `False` — same Session-0-style rollout this file
      already used once before for `enable_reflection`/`enable_planning`/`enable_memory` (launched
      opt-in, flipped to fleet-wide `True` only after dedicated testing). Flipping the fleet-wide
      default is an explicit follow-up decision, not hidden scope creep: it would add a real LLM call
      (cost + latency) to every submission across all ~72 agents and deserves its own dedicated full-
      suite regression pass rather than riding in silently on this change.
      Tests: `tests/test_phase35_self_critique.py` (14 new — 4 for `_extract_role_criteria`, 6 direct
      unit tests of `_make_critique_node` in isolation incl. non-fatal LLM-failure/malformed-JSON
      paths, 4 full-graph integration tests proving the actual Plan→Execute→Critique→Improve→Verify
      wiring). Full regression sweep after this change: 1158 tests green across every
      `base_graph`-adjacent test file (`test_hierarchy_chain.py`, `test_day12_smoke_test.py`,
      `test_failure_ladder.py`, all `test_day*_agent*.py`/`test_session*_migration.py` files, etc.) +
      the 14 new ones = 1172 total; `black`/`ruff` clean; `mypy --strict` clean on `base_graph.py`
      itself (the only `--strict` error surfaced, in `app/fleet/budget_manager.py`'s POSIX-only
      `resource` import, is pre-existing and confirmed unrelated — reproduces identically when checking
      that file alone, untouched by this change).
- [x] **3.6** — Bounded continuous replanning: new `replan_node` in `base_graph.py`, sharing the same
      real gather-facts→create-plan two-call sequence `planner_node` already uses (extracted into
      `_gather_facts_and_plan`, now a single source of truth for both instead of duplicated logic).
      Fires mid-execution on every "loop back to `call_llm`" edge, but is a genuine no-op (zero LLM
      calls, confirmed by `test_replan_node_no_op_when_trigger_not_met` asserting `_make_client` is
      never even constructed) unless a real, already-tracked, evidence-grounded trigger fires —
      per the spec's own two named triggers, not a fabricated heuristic:
      (a) `reflection_unsatisfied_count >= 2` — `reflection_node` (Phase 0/3.5) has judged the tool
      output unsatisfactory at least twice in a row, a real signal the current approach isn't working;
      (b) `critique_retries >= 2` with the same criterion still unmet in the latest `critique_result`
      — `critique_node` (3.5) has sent work back for improvement more than once for the same reason.
      `_should_replan` returns `(bool, reason)`, where `reason` cites the actual repeated criterion
      text or the actual dissatisfaction count (never a generic message) — that reason is folded
      into both the facts and plan prompts as "new evidence since the last plan," so the revised plan
      is genuinely grounded in what went wrong, and a `[Replan]` message citing it is appended to
      `state["messages"]` so the model actually sees why its plan changed.
      **Bounded two ways, deliberately**: `max_replans` (default 1) caps replan_node's own trigger
      independent of anything else — `test_should_replan_false_once_budget_exhausted` confirms the
      trigger goes permanently inert once the cap is hit even if the underlying signal is still true.
      It also sits inside the existing `max_turns` loop rather than a separate mechanism, so a
      replan is just one more bounded node visit, never a second unbounded loop layered on the first.
      Trigger (b)'s 2-retry threshold has a real, documented dependency on `max_critique_retries`:
      with 3.5's own default of 1, critique_node's budget is exhausted (submission auto-accepted) right
      when the first retry would have looped back, so `critique_retries` can never actually reach 2
      under default settings — trigger (b) is real, tested, and dormant until a caller raises
      `max_critique_retries >= 2`, not dead code (documented here so it isn't mistaken for one).
      **Rollout decision**: `enable_replanning` defaults `False`, same Session-0-style opt-in as
      `enable_critique` (3.5) — flipping the fleet-wide default is an explicit follow-up, not silent
      scope creep, since it adds real LLM calls to a live run.
      Tests: `tests/test_phase36_continuous_replanning.py` (10 new — 6 for `_should_replan`'s trigger
      logic incl. both the "single failure isn't enough" and "budget exhausted" negative cases, 2 direct
      `_make_replan_node` unit tests, 2 full-graph integration tests: one drives 3 consecutive
      unsatisfied `reflection_node` turns end-to-end and confirms exactly 1 replan with the actual
      `[Replan]` message landing in `final_state["messages"]`, the other confirms the disabled-by-
      default path never touches replan logic at all). Full regression sweep: 1216 tests green across
      every `base_graph`-adjacent file (same set as 3.5's sweep + the 24 new 3.5/3.6 tests);
      `black`/`ruff` clean; `mypy --strict` clean on `base_graph.py` (same pre-existing, unrelated
      `budget_manager.py` `resource`-import error as 3.5, confirmed unchanged).
- [x] **3.7** — Formal quality gate: new `_run_quality_gate` + `QualityGateResult` in `base_graph.py`,
      called once from `execute_tools` at the exact `submit_*` boundary — the single real chokepoint
      every agent's submission already passes through (same chokepoint Audit 02's schema-validation
      gap-closure already used). Consolidates the spec's named factors into one function, each backed
      by a real, already-produced signal rather than a new invented one: verification (3.1, read from
      `state["verification"]`), consistency (re-confirms `enforce_in_result`'s own override actually
      took, rather than re-deriving it), evidence/critique (3.5 — surfaces it when `critique_node`'s
      retry budget was exhausted while criteria were still unmet, instead of letting that fact
      silently vanish into an accepted submission), policy (the existing `_validation_warning` schema
      signal), and a confidence threshold (`state["confidence"]` vs. a caller-set floor). Every
      submission gets a structured, auditable `result["_quality_gate"] = {passed, checks, warnings}` —
      real per-check booleans and evidence-citing warning strings, never a bare pass/fail claim.
      **Deliberate scope boundary**: only the confidence and critique checks are allowed to flip
      `passed` False and escalate `requires_human_approval` — verification/consistency stay
      informational-only, because which verification flags are actually load-bearing vs. merely
      tracked is a legitimate **per-agent** decision (3.1's own `EXECUTOR_TIER_VERIFICATION_FLAGS`
      already shows 3 of 5 agents intentionally treat their flag as non-blocking) that this one
      shared, fleet-wide function has no business overriding unilaterally — documented directly in
      the function's own docstring so it isn't mistaken for an oversight.
      **Runs unconditionally** (unlike 3.5/3.6 — cheap, zero LLM calls, pure state inspection) but is
      inert by construction under every existing default: `quality_gate_min_confidence` defaults to
      `0.0` (every real confidence passes) and `critique_result` is only ever non-empty when 3.5's
      `enable_critique` is on (default `False`) — confirmed directly by
      `test_execute_tools_default_min_confidence_is_inert` (confidence 0.01 still never escalates
      under defaults). Verified this doesn't silently break any existing fleet-wide assertion on the
      `result` dict's shape by running the full 1216-test `base_graph`-adjacent sweep with the gate
      wired in *before* writing a single new test for it.
      Tests: `tests/test_phase37_quality_gate.py` (11 new — 7 direct `_run_quality_gate` unit tests
      incl. the informational-only verification/consistency/policy cases, 3 `execute_tools`-level
      integration tests proving escalation actually reaches `requires_human_approval` end to end, 1
      full-graph test proving a real low `planner_node` confidence flows through
      `quality_gate_min_confidence` into a real escalation). `black`/`ruff` clean; `mypy --strict`
      clean on `base_graph.py` (same pre-existing, unrelated `budget_manager.py` error as 3.5/3.6).
- [x] **Step 3 regression gate** — Full backend suite (not just the `base_graph`-adjacent subset each
      sub-item verified individually): `python -m pytest tests/` → **3095 passed, 26 failed, 55
      skipped, 17 deselected** (357.64s). All 26 failures independently confirmed pre-existing and
      unrelated to every change in this Step (`test_git_service.py`, `test_chat_tools.py`,
      `test_concurrency.py`, `test_credential_vault.py`, `test_day1_tools.py`, `test_day2_agents.py`,
      `test_fleet_metrics.py`, `test_versioned_memory.py`, `test_architecture_mapper.py` — none touch
      `base_graph.py`, `manager.py`, `backend_dev.py`/`frontend_dev.py`, `qa.py`/`reviewer.py`, or any
      Phase 3 file). Sampled 4 directly to confirm root cause rather than assuming: `test_git_status`
      fails with `FileNotFoundError: [WinError 2]` — the `git` binary isn't invokable via `subprocess`
      in this sandbox; `test_path_without_epic` fails on a hardcoded POSIX path assertion
      (`/tmp/wt/task-42`) against this Windows sandbox's real `\tmp\wt\task-42` separator;
      `test_memory_usage_returns_string` is the same subprocess-unavailable class; `test_run_span_times_execution`
      passed cleanly in isolation (flaky under full-suite parallel timing, not a real failure). All are
      Windows-sandbox/local-environment limitations of the same kind already documented repeatedly
      elsewhere in this file (e.g. Day 1/1.2's "no Docker/live Postgres available here"), not
      regressions from Step 3's work.
      `mypy --strict` on `app/agents/base_graph.py`: 0 errors (the only `--strict` error in the whole
      run traces to `app/fleet/budget_manager.py`'s POSIX-only `resource` import — reproduces
      identically checking that file alone, confirmed untouched by any Step 3 change).
      **Step 3 total new tests this session: 3.1 (8) + 3.2 (4, +5 assertions in existing files) + 3.5
      (14) + 3.6 (10) + 3.7 (11) = 47 new tests**, all passing, none skipped, none xfail.

## Steps 1–3 gap-closure audit (2026-07-28)

Per owner instruction: before starting Step 4, went back through Steps 1–3 line-by-line against
`MASTER_AGENT_v2.md`'s own Definition-of-Done checklists — re-verified with grep/reads, not by
trusting this file's own prior claims. Found 6 real gaps (5 in Step 3, 1 in Step 1); all 6 closed and
tested below, plus one **previously-undiscovered fleet-wide bug** the Gap 4 test work surfaced as a
side effect.

- [x] **Gap 1 (Step 1 / 1.1)** — `embed_architecture_note` had zero real call sites (confirmed by the
      spec's own prescribed grep: only its own definition + an importability test). Closed at the two
      real dispatch paths architecture-tagged agents actually run through: `security_architect`/
      `database_architect`/`api_designer_agent` (dispatched via `app/api/specialized_agents.py`) now
      get it from the existing universal post-run hook (`app/memory/hooks.py::record_agent_run_outcome`,
      via a new `_is_architecture_agent` check — named-agent match first, since none of the real
      registered capabilities literally say `"architecture"` as the spec's text assumed, `architect.py`
      really tags `"architecture_design"` — with a substring-based capability-tag fallback for
      future-proofing); `architect` (a `app/pipeline/graph.py` pipeline node, not dispatched through
      `specialized_agents.py`, so it has no shared hook to piggyback on) gets a direct call at its own
      submission point via a new `embed_architecture_note_sync` bridge (same `new_isolated_async_engine`
      pattern as `embed_learning_signal_sync`). Also added `agent_name` attribution to
      `embed_architecture_note` itself (prepended into content, `MemoryEmbedding` has no dedicated
      column — same convention `embed_procedure` already uses).
      Tests: `tests/test_architecture_note_wiring.py` (17 new) — `_is_architecture_agent` incl. the
      real capability-tag substring case, the sync bridge's 3-outcome pattern, `record_agent_run_outcome`
      wiring (completed writes, blocked skips, non-architecture skips, failure non-fatal), and
      `architect_node`'s own direct call (writes on real submission, skips when not submitted, non-fatal
      on failure).
- [x] **Gap 2 (Step 3 / 3.1)** — the original verification audit (`test_phase3_verification_audit.py`)
      only covered the 5 Executor-tier agents; the spec's own DoD says "every Executor/**Editor**-tier
      agent." Extended to both real Editor-tier agents: `runbook_generator_agent` (`yaml_validate` →
      `structure_validated`, confirmed tracked-not-required, same pattern as 3 of the 5 Executor-tier
      flags) and `onboarding_agent` — confirmed, against its real role file, that it genuinely has no
      edit-time verification tool at all (it produces free-form Markdown with no meaningful syntax to
      lint, unlike `runbook_generator_agent`'s YAML) rather than manufacturing a placeholder validator
      just to have one.
      Tests: 5 new assertions added to `tests/test_phase3_verification_audit.py` (13 total in that file
      now).
- [x] **Gap 3 (Step 3 / 3.3)** — `chat_agent.py` had zero memory read/write wiring (confirmed by grep:
      no `embed_task_outcome`/`embed_failure`/`query_memory_context` call anywhere in the file);
      `manager.py` was already partially real (writes via `embed_task_outcome`). `chat_agent.py`'s own
      LangGraph structural conversion stays deferred to Phase 5 per 3.3's own text — this applies just
      the memory read/write behavior at `ChatAgent.run()`'s real natural unit of work (one call = one
      turn): new `_memory_read_context` (queries `memory_embeddings` using the user's message, injects
      the result into a per-call `system_prompt` — never mutates the static `self._system`) and
      `_memory_write_outcome` (writes a task-outcome record after every turn, plus a failure record when
      the turn errored), both non-fatal.
      Tests: `tests/test_chat_agent_memory_wiring.py` (7 new) — the two hooks in isolation, plus a full
      `run()` integration test (mocked streaming client) proving the wiring is real, not just that the
      standalone methods work, and a source-inspection guard confirming `system=system_prompt` (not the
      static `self._system`) reaches the actual API call.
- [x] **Gap 4 (Step 3 / 3.4)** — no fleet-wide "mock a failing verification tool, assert `submit_*`
      correctly reports the failure sourced from `state["verification"]`, not the model's claim" test
      existed anywhere, beyond the narrow wiring-level audit in 3.1/2.1. Closed with a real end-to-end
      test per distinct `VerificationConfig` wiring shape (not a per-agent-name checkbox): the 4
      Executor-tier agents whose `enforce_in_result` overrides a field beyond `"read"`
      (`test_writer_agent`, `test_coverage_agent`, `load_test_agent`, `infra_agent`) — each run through
      its REAL `run_<agent>()` wrapper (not a hand-rolled `run_agent_graph` call) with a mocked model
      that submits immediately, falsely claiming its tracked flag is `True` with no real tool call
      behind it.
      **This test work surfaced a real, previously-undiscovered, fleet-wide bug, not a test-design
      issue**: `AgentResult.raw` was built via `raw = result if result else final_state["result"]` —
      `result` is a dict captured directly from the model's raw `submit_*` input at the moment the
      handler runs, `final_state["result"]` is the graph's actually-overridden, verification-enforced
      dict. Since `result` is always truthy once any submission happens, `raw` **always** preferred the
      unverified claim over the graph-enforced truth — meaning a false claim like `tests_run=True` could
      leak into `AgentResult.raw` even though `AgentResult.verified` itself (computed separately, direct
      from `final_state["verification"]`) was already correct. This directly contradicts
      `base_graph.py`'s own stated contract ("the model cannot lie about 'tests passed' or 'scan
      clean'") — for the `.raw` field specifically, it could. Confirmed identical, byte-for-byte across
      **25 agent files** (verified via grep before touching any of them, same discipline as every prior
      codemod this session) and fixed as one verified batch: flipped the priority to
      `raw = final_state["result"] if final_state["result"] else result`, with a rationale comment added
      to all 25 explaining why. Re-ran all 613 tests across every file referencing any of the 25 agents
      — zero regressions.
      Tests: `tests/test_phase34_real_output_verification.py` (6 new) — 4 parametrized "false claim
      overridden" tests (one per wiring shape) + 2 "`AgentResult.verified` is `False`" tests for the 2
      where the flag is load-bearing.
- [x] **Gap 5 (Step 3 / 3.5)** — the spec's own DoD: "one full end-to-end test per agent tier
      (Executor/Analyzer/Editor)." The original `test_phase35_self_critique.py` only ever used a
      synthetic test-only role (`ROLE_WITH_CRITERIA`), never a real agent. Closed with 3 new end-to-end
      tests, one real agent per tier, each invoked via `run_agent_graph` directly (with
      `enable_critique=True` — no `run_<agent>()` wrapper exposes this flag yet, critique stays
      fleet-wide opt-in per 3.5's own rollout decision) using that agent's REAL role file, `_TOOLS`,
      handler factory, and `VerificationConfig`: Executor = `debugger_agent`, Analyzer =
      `code_quality_agent`, Editor = `runbook_generator_agent`. Each test asserts the critique prompt
      sent to the mocked LLM actually contains real text pulled from that agent's own
      `roles/<agent>.md` (proving `_extract_role_criteria` parsed the real file, not a stand-in), not
      just that the mechanism completes.
      Tests: `tests/test_phase35_per_tier_critique.py` (4 new).
- [x] **Gap 6 (Step 3 / 3.6)** — the spec's own DoD: "a test that forces repeated plan-vs-reality
      mismatches confirms the agent halts ... at the turn budget rather than looping forever." The
      original tests only proved boundedness via `max_replans` (a real, separate, smaller bound) —
      never proved `max_turns` itself is the actual backstop if `max_replans` were set irresponsibly
      high. New test sets `max_replans=100` and a model that never submits (always leaves reflection
      unsatisfied) — confirms the graph still halts at exactly `max_turns` turns, with `replan_count`
      genuinely nonzero (the mechanism fired for real) but far short of the generous 100 budget,
      proving `max_turns` — not `max_replans` — is what actually stops it.
      Tests: 1 new test added to `tests/test_phase36_continuous_replanning.py` (11 total in that file
      now).
- [x] **Gap-closure regression gate**: `python -m pytest tests/` → **3136 passed, 25 failed, 55
      skipped, 17 deselected** (364.96s) — pass count rose by 41 (the new tests), failure count fell by
      1 (the one flaky timing test, `test_run_span_times_execution`, simply didn't flake this run —
      already confirmed passing in isolation during Step 3's own gate). Every one of the 25 remaining
      failures is the exact same file as the pre-gap-closure baseline — zero new failures, zero new
      files affected by any of the 6 fixes. `black`/`ruff` clean across the full `app/`+`tests/` tree;
      `mypy --strict` clean (same single pre-existing `budget_manager.py` `resource`-import error,
      confirmed unrelated).
      **Total new tests this audit: 17 + 5 + 7 + 6 + 4 + 1 = 40 new/added tests**, all passing.

## Step 4 — Phase 4: Near-Claude-Code Capability Baseline (Day 10)

**Status: PLANNED, not yet implemented.** Session paused here at owner's request ("if this is big
work, plan and save it, we'll do it tomorrow") after a real, verified research/audit pass — zero code
changes made yet this Step, only read-only investigation (grep/read). Everything below is real,
gathered data, not assumption — safe to resume directly from "Next session: start here."

Source: `MASTER_AGENT_v2.md` §Phase 4 (a 7-item checklist applied to every agent, not new subsystems).
DoD: every agent's checklist filled in and true, with a citation (test name or file:line) proving it,
recorded in a shared tracking table — plus full regression green.

### Real agent count (verified, not assumed)
`grep -rl "^AGENT_CONTRACT" app/agents/*.py` → **72 real agent modules**. Two are structurally special
and need bespoke handling rather than the standard per-item check: `chat_agent.py` (no `run_agent_graph`
— its own loop, memory-wired in Step 3's Gap 3) and `manager.py` (orchestrator, no LLM tool-calling loop
of its own, no `AGENT_CONTRACT`-style tools list — its Phase-4 checklist doesn't map 1:1 the way a
worker agent's does). The per-item audits below cover the other 70 unless noted.

### Item 1 — "Can it read broadly?" (incl. repo intelligence layer)

- **1b (repo intelligence layer — call graph/PageRank) is ALREADY satisfied fleet-wide, confirmed, no
  fix needed.** `app/repo_tools/context_builder.py::build_context` (real PageRank-style ranking +
  `cross_file_graph.py`'s call graph) is already called from `base_graph.py`'s `memory_hook_node`
  (`enable_memory=True` is the fleet-wide default), so every agent that hasn't opted out already reaches
  it. Just needs a citation in the tracking table, not new code.
- **1a (broad-read tools) — real, narrow gap found, not yet fixed.** Checked actual tool presence (not
  just "does it import the `READ_ONLY_TOOLS` constant," which produced false negatives for Tier-A
  agents using differently-named curated tool lists like `CODER_TOOLS`/`QA_TOOLS`). The real signal:
  `search_code` + `get_file_tree` present almost everywhere; `find_references` (a real, separately
  wired tool per `app/agents/tools.py:173`, present on 59/72 agents already) is missing on exactly 12:
  `agent_advisor`, `agent_debugger`, `agent_performance_reviewer`, `changelog_agent`,
  `database_architect`, `evaluation_agent`, `knowledge_curator`, `quality_auditor`,
  `rag_engineer_agent`, `release_notes_agent`, `research`, `user_story_generator`.
  `executive` was also flagged by the raw grep but is a **confirmed, deliberate exception** — its real
  role file (`roles/executive.md`) is a pure business-goal→epics translator with no codebase
  interaction at all; it correctly has zero code tools, not a gap.
  **Important nuance found mid-audit, not yet resolved**: 3 of the 12
  (`agent_advisor`/`agent_debugger`/`agent_performance_reviewer`) are the "fleet self-improvement
  agents" cohort and deliberately use an **index-sliced subset** of `READ_ONLY_TOOLS`
  (`SCAN_TOOLS = [READ_ONLY_TOOLS[0], READ_ONLY_TOOLS[2], READ_ONLY_TOOLS[4]]` in
  `agent_debugger.py`) rather than the full bundle — this looked like an intentional, narrower safety
  scope for agents that audit/modify *other agents*, not an oversight. **Next-session first task**: read
  why that index-slice was chosen (git history / any comment near it) before blindly adding
  `find_references` to those 3 — the other 9 (which use the full `READ_ONLY_TOOLS` bundle or
  individually curated lists, not an index-slice) are safe to fix the same way Step 2's dead-contract
  codemod worked: verify the exact tool-list construction pattern per file first, then batch-add
  `find_references` only where it's a real, byte-verified, low-risk addition.

### Item 4 — "Does it benefit from and contribute to fleet memory?" (`record_learning`)

**Real, well-precedented gap — mechanical fix, same codemod pattern as Step 1 / 1.4's original
38-agent rollout.** Checked the real functional signal (`make_record_learning_handler` actually wired
+ `"record_learning"` in the real tool list — not just a schema-constant-name grep, which
undercounted). Exactly **32 agents still lack it** (70 total minus the 38 that 1.4 already covered
matches exactly, confirming this count is accurate): `agent_advisor`, `agent_debugger`,
`agent_performance_reviewer`, `ai_engineer`, `api_docs_agent`, `architecture_reviewer`, `business_analyst`,
`changelog_agent`, `cicd_agent`, `cleanup_agent`, `database_architect`, `dependency_agent`,
`docker_agent`, `evaluation_agent`, `executive`, `knowledge_curator`, `migration_agent`,
`monitoring_agent`, `performance_reviewer`, `quality_auditor`, `rag_engineer_agent`, `readme_agent`,
`refactor_agent`, `release_notes_agent`, `schema_agent`, `security_architect`, `security_reviewer`,
`sprint_planner`, `sql_agent`, `style_reviewer`, `tech_debt_agent`, `user_story_generator`.
**Next-session plan**: same verified-byte-identical-before-writing codemod discipline as every prior
rollout this session (1.4, 2.3, Step 3 Gap 4's 25-file fix) — check each file's real tool-list
construction pattern (shared template vs. individually curated), wire
`handlers["record_learning"] = make_record_learning_handler("<agent_name>")` + add `"record_learning"`
to both `AGENT_CONTRACT["allowed_tools"]` and the real `_TOOLS`/tool-list, verify with
`test_record_learning_rollout.py`-style tests (3 real checks per agent: declared in contract, present
in real schema, wired to a real callable handler attributing the calling agent correctly) mirroring
Step 1/1.4's own test file.

### Item 5 — "Does it have real workspace awareness (git) where relevant?"

**Not yet audited this session — starting point for next time.** Not universal by the spec's own
text ("not every agent needs this... apply it where the role genuinely calls for it"). Plan: for
every agent lacking `git_status`/`git_diff`/`git_log`/`git_blame`, read its real role file to judge
whether its job genuinely depends on repo history/state (same evidence-based judgment call already
used for `localization_agent`'s Editor-tier exception and `onboarding_agent`'s missing-validator
decision in Steps 2/3) — do not blanket-add git tools to every agent.

### Item 3 — "Can it iterate on failure?" (bounded retry, now via Phase 3's critique/quality-gate)

**Not yet audited/decided this session.** The spec ties this explicitly to Phase 3's self-critique and
quality-gate machinery, which is currently **opt-in, off by default fleet-wide**
(`enable_critique=False`/`enable_replanning=False` — a deliberate Session-0-style rollout decision
from Step 3, not an oversight). Open question to resolve next session: does Phase 4's "iterate on
failure" checklist item require flipping `enable_critique=True` (at least) for Executor-tier agents
now, or is "the mechanism exists and is real, tested, and available to opt into" sufficient to check
this box, with the fleet-wide default-flip remaining its own explicitly-tracked future decision (as
Step 3's own tracker entries already flagged it)? Leaning toward the latter (least blast radius,
consistent with the rollout discipline already established) but not yet decided — **decide this
first** before writing any tracking-table entries for this item.

### Item 2 — "Can it verify its own output?"

**Not yet audited this session.** Largely believed already true (Phase 2/3's core deliverable per the
spec's own text) for the 38 agents Steps 2–3 already touched. Real open work: confirm the ~32 agents
Item 4 above lists (mostly Analyzer/Advisor-style agents never touched by Phase 2's tiering pass) each
have *some* real verification gate appropriate to their role (at minimum: submission gated on a real
`"read"` flag from `state["verification"]`, matching the pattern already confirmed for every other
Analyzer-tier agent in Step 2's Day 7 pass) — not a blanket trust-the-LLM submission. Needs the same
per-agent `_CFG` inspection already done repeatedly this session, not new mechanism design.

### Item 7 — "Is its role prompt specific and honest?"

**Not yet audited this session.** Likely mostly fine for the 38 already-touched agents (Phase 2.4 +
Day 7's role-file regeneration). Real open work: grep the ~32 untouched agents' role files for the
generic 14-file boilerplate block (same check already used in Step 2's own DoD verification —
`grep -l "All role-relevant checks pass with 0 errors" roles/*.md`) and confirm each remaining match's
agent genuinely has the tools to back the claim, same reasoning already applied in Step 2.

### Item 6 — "Can it ask for clarification instead of guessing?" — real forward-dependency, not a gap to silently skip

The spec's own text cites **"(Phase 5.3)"** — a mechanism that doesn't exist yet; Phase 5 comes after
Phase 4 in the roadmap. This is a genuine spec-ordering dependency, not an oversight: Phase 4's DoD
can't be 100% true until *something* like Phase 5.3 exists. **Decision needed next session** (pick one,
don't silently skip):
(a) Pull forward a small, real, scoped `request_clarification` tool now (not all of Phase 5 — just this
    one tool, wired into agents whose tasks can genuinely be underspecified), and note the rest of
    Phase 5.3/Phase 5 remains for later, or
(b) Document this checklist item as explicitly blocked-on-Phase-5 in the tracking table (real, honest,
    not hidden) and revisit when Phase 5 starts.
Leaning toward (a) for a small, well-scoped subset of agents (the ones most likely to face genuinely
ambiguous tasks — e.g. `executive`, `pm`, `architect`) since a fully-blocked checklist item across all
of Phase 4 feels like it undersells what's realistically buildable now, but this needs a real decision,
not a default.

### Next session: start here

1. Resolve the 3 open decisions above (Item 1's index-slice-agent question, Item 3's critique-enablement
   question, Item 6's build-now-vs-defer question) — quick judgment calls informed by reading real code,
   not new research.
2. Execute Item 1a's `find_references` rollout (12 agents, minus whichever of the 3 index-slice agents
   turn out to be intentionally scoped) and Item 4's `record_learning` rollout (32 agents) as verified
   batch codemods — the two most mechanical, lowest-risk, highest-confidence fixes, do these first.
3. Then Items 5, 2, 7 (all require per-agent role-file reading — no shortcuts, same discipline as every
   prior audit this session).
4. Then Item 6 (clarification tool, scoped per the decision above).
5. Build the Phase 4 tracking table (new file or a section here) — one row per agent, 7 columns, each
   cell a real citation (test name or file:line), per the spec's own DoD wording.
6. Write real tests for every fix (same standard as every prior step — real test, not smoke test).
7. Full regression gate (`pytest tests/`, `mypy --strict`, `black`, `ruff`) — compare against this
   session's own 3136/25 baseline, confirm zero new failures, same triage discipline as every prior gate.
8. Update this section with `[x]` results, matching the exact format of Steps 1–3 above.

- [ ] Step 4 implementation (see plan above).
- [ ] Step 4 regression gate.

## Already done, ahead of schedule (2026-07-29) — reference only, not pending

Owner asked to check whether any Phase 5/6 items were small + independent enough to do before Step 4.
Spec's own §8: only 5.2 (`chat_agent` conversion) must wait until Phase 1-4 finish; Phase 6 explicitly
"can run in parallel with Phase 2-4." These 3 are DONE — implemented, tested, mypy --strict/black/ruff
clean. Full-suite regression gate for them is folded into Step 5's own regression gate below (not run
separately) to avoid a redundant full-suite pass.

- **5.4 — `thinking_budget_opus` wired for real.** Was dead (zero real callers, confirmed by grep).
  Scoped to real opus-tier agents via `ModelRouter.agents_by_tier("opus")` (live `agent_models.json`,
  not a hardcoded list). Wired into `base_graph.py::_make_call_llm_node`. Tests:
  `tests/test_phase54_thinking_budget.py` (4, inspects the real request payload).
- **5.6a — orphan `agent_run` recovery.** New `app/fleet/failure_ladder.py::reconcile_orphaned_runs`/
  `start_orphan_recovery_loop` (mirrors `retention.py`'s existing loop pattern), wired into `main.py`
  lifespan. New config `agent_run_orphan_threshold_seconds` (900s default). Tests:
  `tests/test_orphan_recovery.py` (6, real Postgres).
- **5.6b — deadlock timeout on slot acquisition.** New `SlotAcquisitionTimeout` +
  `asyncio.wait_for(...)` in `app/pipeline/concurrency.py`'s `agent_run_slot()`/`subtask_slot()`. New
  config `slot_acquisition_timeout_seconds` (300s default). Tests: `tests/test_concurrency.py` (4 new).
  **Known, documented follow-up (real, not hidden) — folded into Step 5's 5.6 entry below**:
  `manager.py`'s subtask retry loop has a documented "nothing raises past this function" invariant that
  a raised `SlotAcquisitionTimeout` would break; graceful handling there was not done in this pass
  (high-blast-radius file, needs its own dedicated care) — tracked as pending work below, not skipped.

## Step 5 — Phase 5 + Phase 6 (all remaining/pending work, merged into one step)

Per owner instruction (2026-07-29): only 2 steps left to implement — Step 4 (Phase 4, entirely, plan
above) and this Step 5 (everything still pending from Phase 5 + Phase 6, merged, completed items
removed from the to-do list — see "Already done" section above for those). Nothing from Phase 5/6 may
be silently dropped — every item below traces to a real `MASTER_AGENT_v2.md` §Phase 5/§Phase 6 bullet.

### Phase 5 — remaining

- [ ] **5.1** — Convert `manager.py` to a LangGraph supervisor graph. Preserve every existing behavior
      exactly (retry counts, epic halting, git-commit-before-review, checkpointing) — structural
      conversion only, not a rewrite of what the manager decides.
- [ ] **5.2** — Convert `chat_agent.py` to an interrupt-based LangGraph graph. **Spec-mandated: do this
      last**, only after Phase 1-4 and the rest of Phase 5 are stable — highest blast-radius item in the
      whole document. Do not start this early even if time allows.
- [ ] **5.3** — Add a real `request_clarification` tool (via the existing `PendingApproval`/
      `interrupt()` pattern, A.11) for agents whose tasks can be genuinely underspecified (`pm`,
      `architect`, `planner`, `decomposer`, loosely-specified Tier-B/C tasks). Gate to genuine blockers
      via the `confidence` field (reuse, don't invent a second ambiguity metric) + Phase 3.7's
      confidence-threshold gate. This also resolves Phase 4 Item 6's forward-dependency.
- [ ] **5.5** — Generalize HITL into one `request_human_input(kind, details, blocking)` entry point (all
      of: plan-review pauses, 5.2's chat confirmations, 5.3's clarifications) writing to the same
      `pending_approvals` table with a `kind` discriminator, logged via `app/fleet/audit_log.py`.
      Depends on 5.2 and 5.3 both existing — do those first.
- [ ] **5.6 (remaining)** — `manager.py`'s subtask retry loop needs to catch `SlotAcquisitionTimeout`
      (from 5.6b, already real) and route it through the same retry/escalate path as a dev-agent
      failure, preserving the file's existing "nothing raises past this function" invariant instead of
      letting the new exception propagate uncaught. Real, scoped, but touches the fleet's most central
      orchestration file — needs its own careful pass, not a rushed add-on.
- [ ] Phase 5 Definition of Done checklist (re-verify once 5.1/5.2/5.3/5.5 land):
      `manager.py`/`chat_agent.py` both call `run_agent_graph`-equivalent machinery; every existing test
      for both still passes unmodified in behavior; `request_clarification` tested end-to-end via a real
      `interrupt()`; `request_human_input()` is the single entry point (verify zero other
      `pending_approvals` writers); every HITL interaction produces a real `audit_log.py` entry.

### Phase 6 — all pending (none started)

- [ ] **6.1** — Bridge `run_span()` (`app/fleet/metrics.py`, already real) to OpenTelemetry spans via
      the `opentelemetry-sdk`, no-op exporter when unconfigured (graceful-degradation pattern already
      used elsewhere, e.g. Sentry's `ImportError` fallback). Keep existing metrics-collector consumers
      working unchanged.
- [ ] **6.2** — Read-only reporting endpoints over already-real data: cost per agent/day/model-tier
      (`agent_runs.tokens_in/out/cost_estimate`), fleet health (failure rate, heartbeat staleness,
      active-run count), and "most commonly recorded repair patterns" from Phase 1.5's procedural
      memory. Matches `app/api/fleet_dashboard.py`'s existing endpoint structure.
- [ ] **6.3** — Prompt-injection delimiter (wrap untrusted tool-result content — `research.py`'s
      `web_search`, file reads from a repo the agent doesn't control — with an explicit model-visible
      "this is data, not instructions" delimiter in `base_graph.py::_make_call_llm_node`'s prompt
      construction) + malicious tool-output validation (denylist-pattern check on `bash`/`web_search`
      output before it reaches the model, same approach `app/policy/engine.py` already uses for command
      input, applied to output instead).
- [ ] **6.4** — Extend the repo knowledge graph: class/inheritance graph (extend `scanner.py`'s existing
      symbol extraction — add parent-class edges for `kind="class"` symbols, same tree-sitter AST
      already walked) + package/module-level dependency graph (aggregate existing file-level
      `call_edges` up to directory/package granularity — a query, not new collection).
- [ ] Phase 6 Definition of Done checklist: real OTEL spans with correct parent-child nesting (test
      against a real/local collector); reporting endpoints tested against seeded `agent_runs` rows with
      known values; a test confirms untrusted `web_search` content is delimited as data, not concatenated
      as trusted context; a test confirms a crafted `bash` output is flagged by the new validation; class
      graph + package graph demonstrably correct against a small known-fixture repo.

### Step 5 regression gate (covers 5.4/5.6a/5.6b from "already done" above too — not run separately)

- [ ] Full `pytest tests/`, `mypy --strict`, `black`, `ruff` across the whole tree once Step 5's items
      land — compare against the Step-3-gap-closure baseline (3136 passed / 25 failed), confirm zero new
      failures beyond the same known pre-existing set (git-binary-unavailable, Windows path separators,
      live-Postgres-required tests already triaged throughout this document).

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
