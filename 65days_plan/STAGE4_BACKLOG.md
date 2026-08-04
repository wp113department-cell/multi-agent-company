# Gridiron — Stage 4 Backlog: Closing the 120-Question Strict-YES Gap

## Why this document exists

`answer2.md` (2026-08-03, independent fresh audit) scores the 120 questions from
`Bhaskar's_questions.md` at **question level**, strict-AND: a question is YES only if every one of
its sub-parts is YES. Result: **20 YES / 82 PARTIAL / 12 NO / 1 NOT VERIFIED / 5 deferred**.

Stage 0-2 (Days 1-57, `PLAN.md`) were scoped against `answers.md`'s **811 sub-answer** breakdown,
not the 120-question strict view, and explicitly left a **97-item SKIP list** untouched by design
(`PLAN.md:187`). That's the entire reason the question-level board still reads mostly PARTIAL
despite Stage 0-2 being genuinely, verifiably complete (Day 57 close-out: 3691 tests, 0
regressions, zero drift on re-check). Two different scoreboards, not a broken plan.

This document is the flat backlog needed to move the **question-level** board — i.e., what's
actually still open in `answer2.md`, organized the way `PLAN.md` organized Stage 0 (root-cause
clusters first, cheap items called out separately, big items sized honestly).

**This is a backlog, not yet a day-wise schedule.** `PLAN.md`'s own Day-1 baseline pass corrected
several assumed sizes against real grep counts before committing to day numbers (e.g. "8 call
sites, not ~75"). The same discipline needs to run against every cluster below before day counts
are locked — sizing here is preliminary (S/M/L/XL) based on what `answer2.md` described, not a
fresh repo measurement. **Recommended next step after this document: a Day-1-style baseline pass,
one cluster at a time, before scheduling.**

---

## Tier 1 — The 12 real NOs (net-new subsystems, not fixes)

Each of these is confirmed by grep in `answer2.md` to have **zero code** — not a gap in an
existing feature, a feature that doesn't exist yet.

| # | Question | What must be built | Size |
|---|---|---|---|
| 1 | Q33 AI Suggestion Review | Entry point that takes externally-pasted LLM code as a distinct input type, routes it through duplicate/conflict checks explicitly, and reports a verdict | S |
| 2 | Q51 Repeat Task & Historical Context | Detect "user is asking me to repeat/continue task X" distinct from generic semantic-similarity memory retrieval; detect task-already-complete and explain why | M |
| 3 | Q60 Agent Creation Capability | Tool/agent that scaffolds a new agent module (`AGENT_CONTRACT`, role prompt, tests, `_register()`) from a description — the capability-registry self-registration (Q47) already makes plugging one in free; this generates the module itself | L |
| 4 | Q73 Adaptive Expertise | Detect the user's professional role (SWE/PM/founder/beginner) and adapt explanation depth/terminology | M |
| 5 | Q83 Technology Recommendation Engine | Given requirements, recommend backend/DB/model/cloud/frontend choices considering scale/budget — currently the platform assumes a fixed stack | L |
| 6 | Q89 Automatic Agent Retirement | Disable/replace/flag an underperforming agent automatically (no such lifecycle exists — `VersionedLesson.promote()` is a memory concept, unrelated) | M |
| 7 | Q105 Company Brain (unified) | Single interface over the 4 real-but-separate systems: `memory_embeddings`, `VersionedLesson`/`LessonStore`, `tool_manifest.py`, `prompt_registry.py` | M |
| 8 | Q107 Pattern Recognition | Trend-mining over `RunMetrics`/`EnhancementRequest` to surface recurring failures ("Docker setup fails repeatedly," "one agent always overloaded") | M |
| 9 | Q111 Tool Evolution | Detect a repeatedly-failing tool and recommend a replacement/new MCP/API/library | S |
| 10 | Q113 User Preference Learning | Stable per-user profile distinct from task-similarity memory; distinguish "temporary choice" from "permanent preference" | M |
| 11 | Q115 Release Retrospectives | "What went well / what failed / what should become standard practice" report generator — distinct from `changelog_agent`'s "what shipped" | S |
| 12 | Q116 Capability Gap Detection | Aggregate repeated unmet requests into "we need a new agent/tool/workflow for X" | S |

**Dependency note**: #8, #9, #12 all read from the same `RunMetrics`/`EnhancementRequest` trend
data — build the aggregation layer once, feed three features. #6/#7 both touch fleet/agent
lifecycle — natural to sequence together.

---

## Cluster N — Orphan recovery is dead in production (PRODUCTION VERIFIED 2026-08-04, same day it was found)

**Fixed and production-verified**, per the owner's explicit request for real end-to-end validation
beyond unit/integration tests before trusting this ("This was the right architectural approach
instead of a quick patch... I want one final production-level validation"). See
`65days_plan/answers.md`'s Q38 "Docker crashes"/"Python crashes" entries for the full fix writeup,
and the "Production Verification" subsection there for the live-validation evidence: a real subprocess
was launched, its real periodic heartbeats observed (twice, each exactly 30.000s apart), SIGKILLed
abruptly, and the real `reconcile_orphaned_runs()` sweep correctly reconciled it — with zero
duplicate execution and zero regressions. A 30-agent concurrent-heartbeat stress test found zero
exceptions, zero connection leaks, and peak Postgres connections well under the configured limit.

**This validation pass itself found and fixed a second, separate, pre-existing bug** — real
production validation doing exactly what it's for: `reconcile_orphaned_runs()`'s cutoff computation
used a timezone-naive datetime that a non-UTC system timezone (this environment: Asia/Kolkata,
UTC+5:30) causes the DB driver to silently misinterpret, making the sweep's cutoff land ~5.5 hours
earlier than intended — invisible in every pre-existing test because the test fixture's own stale-
timestamp write had the identical bug, so the error canceled out on both sides by coincidence. Only
a REAL heartbeat write (this session's own fix, previously nothing ever wrote one) exposed it. Fixed
by keeping timestamps timezone-aware end to end. See `answers.md` for full detail and
`tests/test_orphan_recovery.py::test_a_real_heartbeat_write_is_correctly_recognized_as_stale` for
the regression guard (confirmed to fail without the fix, pass with it).

**A related, lower-severity instance of the same bug class was found in a different subsystem**
(`app/services/retention.py`'s day-scale log/memory retention cutoffs) but was NOT fixed — out of
today's scope (Cluster N is about orphan recovery, not retention) and much lower real-world impact
(a multi-day retention window landing ~5.5 hours "late" is a minor scheduling imprecision, not a
correctness failure the way a 900-second orphan-detection threshold effectively never firing was).
Flagged here for a future day, not silently dropped.

This section is kept below as the original finding record, not an open item.

Not in the original backlog — found while starting Tier 3's "verification-only" items (checking
whether `on_heartbeat()` is wired into the main execution path, per the old Q102 note that this was
"likely a 1-line fix if actually missing"). It was not a 1-line fix; it's a real, previously
undetected production gap in a mechanism that has been repeatedly cited as "YES, real" throughout
this project's entire audit history (`answers.md` Stage 1.3 Day 22, re-confirmed at the Day 57
checkpoint, re-confirmed in this session's own Days 64-65 spot-checks — all wrong to the same
degree, none of them checked whether the heartbeat was actually firing, only that the sweep function
existed and its own SQL logic was correct in isolation).

**What's actually true, verified via direct code reading + this suite's own existing test**
(`test_orphan_recovery.py::test_never_heartbeated_run_is_left_alone_real_db`, whose docstring
already documented the NULL-exclusion behavior without anyone connecting it to this):
- `AgentRun.last_heartbeat_at` is only ever set by `heartbeat_agent_run()`
  (`app/db/repository.py:274`), only ever called from a closure in `app/api/agents.py`, only ever
  passed as the `on_heartbeat` argument to `run_planner()`/`run_coder()` — and **both functions
  treat it as a documented no-op** ("kept for backward compat — no-op, run_span handles telemetry").
  `run_span()` is a separate, in-process-only `MetricsCollector`, not the durable DB row
  `reconcile_orphaned_runs()` actually queries.
- `last_heartbeat_at` therefore stays NULL for the entire lifetime of every real run created via
  those 2 dispatch paths. `WHERE last_heartbeat_at < :cutoff` never matches a NULL row (standard SQL
  semantics) — the sweep can never reconcile anything.
- **Worse**: `app/agents/manager.py::run_manager()` — the epic-manager dev→QA→review loop, the
  *primary* way real coding tasks execute — never calls `create_agent_run()` at all (zero hits,
  grepped). It has no `AgentRun` row and no orphan-recovery coverage whatsoever, not even the broken
  kind. `AgentRun`/orphan-recovery only ever applied to 2 narrow "simple mode" dispatch paths
  (direct planner-only, direct single-coder-only), and even there, it's dead.
- **Likely why the no-op exists, not just an oversight**: the real `heartbeat()` closure calls
  `_spawn_tracked()` → `asyncio.create_task(coro)`, which requires a running event loop in the
  *calling thread*. `run_agent_graph()` runs synchronously, frequently inside an `asyncio.to_thread()`
  worker thread — invoking that closure for real from inside its tool-call loop would likely raise
  `RuntimeError: no running event loop`. Leaving it a no-op was probably a deliberate dodge of a real
  cross-thread scheduling hazard someone ran into, not carelessness — which is exactly why this needs
  a properly-designed fix, not a rushed patch to a foundational, heavily-used function.

**What a real fix requires** (do not rush this into a "cheap items" batch):
1. A thread-safe way to trigger an async DB heartbeat write from `run_agent_graph()`'s synchronous
   tool-call loop, regardless of which thread is running it (e.g. `asyncio.run_coroutine_threadsafe`
   against a captured loop reference, or a thread-safe queue the main event loop drains) — solving
   the actual hazard that likely caused the no-op in the first place, not just calling the closure
   and hoping.
2. Wire a real periodic call (mirroring `base.py`'s existing "every 5 tool calls" pattern) into
   `run_agent_graph()`'s own loop, since that's the shared, universal path ~76+ agents already go
   through — not a per-agent patch.
3. Extend real `AgentRun` row creation (`create_agent_run()`) to `run_manager()`'s own dispatch path,
   so the primary work pipeline gets orphan-recovery coverage at all, not just the 2 narrow
   "simple mode" paths that currently have (broken) coverage.
4. A real reproduction test proving a run that stops heartbeating mid-execution (not just one
   manually set stale in a test fixture, the way the existing test does) actually gets reconciled —
   closing the exact gap between "the SQL sweep logic is correct" (already tested) and "a real run's
   heartbeat actually reaches that SQL" (never tested, because never true).

Size: **L** (touches a foundational, heavily-used function; needs real design for the cross-thread
problem, not just effort). Severity: **Critical** — this is a currently-nonfunctional safety net for
crash recovery across the entire fleet, not a nice-to-have.

---

## Cluster O — `repo_id` scoping is built but never wired (found 2026-08-04, verifying Q95) — ALL 4 PHASES PRODUCTION VERIFIED

**Phases 1a, 1b, 1c, and 1d all PRODUCTION VERIFIED 2026-08-05**, same day as design approval —
every phase in the original rollout plan is now shipped. **CLOSED except for defect fixes** —
future repository-related memory work belongs under Cluster R (below) or `versioned_memory.py`'s
own Phase 2, not as an extension of this cluster. **Canonical reference for future contributors**:
`docs/adr/006-repository-scoped-memory.md`. Full design history: `65days_plan/CLUSTER_O_DESIGN.md`
— answers all 8 questions the user posed, plus a "Repository Isolation Invariants" section (INV-1
through INV-8) added on approval, with sequence diagrams, a data-flow diagram, API changes, risk
analysis, phased rollout/rollback strategy, and implementation sizing.

**Phase 1a shipped** (the 2 fleet-wide chokepoints, per "prioritize chokepoints over manual
propagation"): `run_agent_graph()` (change point C) resolves `repo_id` once from `task_id`, stored
on `AgentRunState`, read by `memory_hook_node`/`_maybe_store_procedure` with zero new params on
either — covers the ~76-agent shared entry point. `record_agent_run_outcome()` (change points A/B)
threads `repo_id` into all 3 embed_* calls; its 3 real callers updated. New
`get_task_repo_id`/`get_task_repo_id_sync` resolvers (`app/db/repository.py`, cached — immutable
post-creation). Found and fixed a second, previously-undocumented instance of the Day-4
racy-repo-resolution bug at `specialized_agents.py`'s `/run-sync` endpoint.
**Verified**: `tests/test_cluster_o_repo_scoped_memory_isolation.py` (9 tests, real Postgres, no
mocks). Full regression 3766 → 3775 passed, 0 failed (also fixed 1 pre-existing `AsyncMock`
test-fixture gap, `tests/test_memory_hooks.py`).

**Phase 1b shipped** (remaining change points D/E/F/G): `run_planning_pipeline()` (G) and
`architect_node()` (F) both reused Phase 1a's existing resolvers with **zero new parameters** on
either function. `EpicManagerState` (D, `manager.py`) gained a `repo_id` field, same
one-field-on-existing-state-object shape as Phase 1a. `ChatSession` (E) gained a `repo_id` field,
resolved once at session creation via new `app/db/repository.py::resolve_repo_id_from_path()` — the
one documented exception to "never reverse-resolve from a path" (INV-1), since chat sessions have no
`DevTask` to resolve from; mitigated via a `status == 'ready'`, most-recent-first filter.
**A real, honestly-named finding, promoted to its own cluster (2026-08-05)**: `CreateEpicRequest`/
`Epic` have no `repo_id` field anywhere in the real `/api/epics` creation path — confirmed by
reading the endpoint, not assumed — so every real epic's memory writes resolve to `repo_id=None`
today. Not fixed here (scope discipline: that's a separate "epics need repo assignment" gap, not
"wire repo_id into memory calls") — the wiring is correct and forward-compatible. Per explicit
instruction, this is a missing domain capability, not an implementation bug, so it's promoted to
**Cluster R** below rather than left as a footnote.
**Verified**: `tests/test_cluster_o_phase1b_repo_scoped_memory_isolation.py` (7 tests, real
Postgres, no mocks; each change point's graph/LLM layer short-circuited using patterns already
established elsewhere in this test suite, e.g. `test_task_images.py`'s `get_graph()`-patching trick
and `test_day18_streaming_wiring.py`'s `run_agent_graph`-patching trick). Full regression
3775 → 3782 passed, 0 failed. `git stash` confirmed genuine failures without the fix on both phases.
`mypy app/ --strict` clean across all 192 source files throughout.

**Phase 1c shipped** (change point H, the smallest phase — "implement only the planned scope"):
`GET /api/memory/search` gained one new optional, explicit `repo_id` query param (deliberately not
auto-injected — a human debugging memory should choose what they search) — an 11-line diff, nothing
else touched. **Verified two ways, not one**: direct-call tests (2 real repos + global memory) plus
a genuine `TestClient` HTTP test (reusing `test_phase62_reporting_endpoints.py`'s own
`dependency_overrides[get_db]` pattern) — the second layer was necessary because a direct call
bypasses FastAPI's own `Query()` resolution entirely (confirmed live: an omitted arg is the literal
unresolved `Query(None)` object, not `None`). `git stash` showed the HTTP-level test's failure mode
without the fix is worse than an error: **HTTP 200 with silently leaked cross-repo results**, since
FastAPI ignores unrecognized query params by default rather than rejecting the request. Full
regression 3782 → 3785 passed, 0 failed. **Cluster O Phase 1c is PRODUCTION VERIFIED and the API
layer is verified end-to-end** — clearing the explicit gate for Phase 1d.

**Phase 1d shipped** (change point I, the last phase): `memory_search` chat/agent tool
(`app/agents/tools.py`) gained an optional, LLM-provided `repo_id` input.
**A real finding corrected the design's own speculative default before writing code**: `grep`
confirmed `memory_search`'s only real caller anywhere is `knowledge_curator`, whose entire job is
curating the fleet's shared memory *across every repo* — the design doc's §10 open question had
speculated "current run's repo" would be the safer default, but that would have actively broken
this agent's real job. Corrected: omitted `repo_id` stays fleet-wide (`None`), matching the same
"intentionally global" category already established for `record_learning`/`fleet_dashboard.py`'s
own learning signals — a future caller can still narrow explicitly.
**Verified**: `tests/test_cluster_o_phase1d_memory_search_tool.py` (4 tests) — schema correctness,
leak-proof test (2 real repos, explicit `repo_id`, absence-based), the corrected-default proof
(omitted `repo_id` still surfaces a real fleet-wide row), and a regression guard. `git stash`
confirmed exactly the right 2 of 4 tests fail without the fix (schema + leak-proof — the leak test's
pre-fix failure shows real cross-repo leakage), while the other 2 correctly still pass (they test
pre-existing behavior, not new behavior) — a clean signal the suite distinguishes "new" from
"preserved," not a blanket check.
**Cluster O Phase 1d is PRODUCTION VERIFIED — all 4 phases of the original rollout plan are
complete.**

**Not yet done, deliberately out of scope for this design**: `versioned_memory.py`'s own Phase 2
(its functions don't accept `repo_id` at all yet — a separate, smaller design question about
pre/post-publish lesson scoping). The epic repo-assignment gap is tracked as its own item — see
Cluster R below.

Same pattern as Cluster N: real, working infrastructure that nothing actually connects to. The
Day 2-4 gap-closure effort built full `repo_id` support into all 14 `query_*`/`embed_*` functions in
`app/memory/store.py` — every one accepts `repo_id: int | None`, every SQL query correctly filters
`(repo_id IS NULL OR repo_id = :repo_id)` when given one. What was never verified until now: whether
any real caller actually passes a resolved `repo_id`, or whether every call silently falls back to
the unscoped (`None`) default.

**Verified by reading every real call site, not sampled**: grepped all ~20 real callers of these 14
functions across the codebase (`app/memory/hooks.py`, `app/agents/chat_agent.py`, `app/agents/
base_graph.py`'s `memory_hook_node`, `app/pipeline/graph.py`, `app/api/memory.py`, `app/api/
fleet_dashboard.py`, `app/fleet/versioned_memory.py`, `app/agents/tools.py` (2 sites), `app/agents/
architect.py`, `app/agents/manager.py` (2 sites)). **0 of 20 thread a `repo_id`.** Every real memory
read and write in this system today is fleet-wide/unscoped, not per-repo.

**Root cause, precisely identified**: no `repo_path -> repo_id` resolver function exists anywhere in
this codebase (confirmed by grep, zero hits) — most call sites only have `repo_path` (a string, e.g.
`ChatSession.repo_path`, `memory_hook_node`'s own `repo_path` closure param) in scope, not a `repo_id`
int, and nothing bridges the two. Where a real `repo_id` *is* already sitting on a row the caller has
in hand (`DevTask.repo_id`, confirmed populated correctly at task-creation time by the real
`POST /api/tasks` endpoint, `app/api/tasks.py:107`), it's simply never fetched and threaded through —
`app/memory/hooks.py::record_agent_run_outcome` (3 real callers) and `app/agents/manager.py`'s 2
`embed_task_outcome` call sites are the clearest examples: the task's own `repo_id` is one query away
and still isn't used.

**Highest-impact single site**: `app/agents/base_graph.py::_make_memory_hook_node`'s `memory_hook_node`
— this runs on **every single agent run across all ~76 agents** (it's a standard node in the shared
graph every `run_agent_graph()` call builds), and its memory read is completely unscoped. Fixing this
one site (once a resolver exists) would cover the single most consequential gap.

**What a real fix requires**:
1. A `repo_path -> repo_id` resolver (a simple `SELECT id FROM repos WHERE local_path = :path`
   helper, doesn't exist yet) for the call sites that only have a path in scope.
2. Threading `task.repo_id` (already correctly populated) through `record_agent_run_outcome` and
   `manager.py`'s 2 sites — no resolver needed, just a fetch-and-pass.
3. Deciding how `base_graph.py::memory_hook_node` obtains a `repo_id` — it already receives
   `repo_path` as a closure param, so wiring it through the resolver from (1) is the natural fix,
   highest priority given its universal reach.
4. The remaining ~13 call sites (`chat_agent.py`, `api/memory.py`, `fleet_dashboard.py`,
   `versioned_memory.py`, `tools.py` x2, `architect.py`, `pipeline/graph.py`) each need the same
   treatment — mostly mechanical once (1)-(3) establish the pattern.
5. A real test proving cross-repo isolation end-to-end: two repos, two tasks, memory written under
   one must never surface when querying under the other — the actual property this whole feature
   exists for, never directly tested (existing tests check that the SQL filter works given a
   `repo_id`, not that any real call site supplies one).

Size: **L** (comparable to Cluster N — a resolver to build plus ~20 call sites across ~10 files to
thread through, though each individual site's change is small/mechanical once the pattern is set).
Severity: **High**, not Critical — this is a data-isolation/multi-tenancy correctness gap (memory
bleeds across repos/projects), not a safety-shutdown-preventing issue the way Cluster N was. Per the
owner's own standing instruction ("avoid bundling unrelated fixes unless they are critical"), **not
fixed in this pass** — documented precisely and sized for its own dedicated work, same treatment
Cluster N got before being picked up deliberately.

---

## Cluster P — Cost tracking uses one flat rate regardless of actual model tier (found 2026-08-05, scoping Q42) — FIXED + VERIFIED 2026-08-05

Found while scoping Q42 ("no recommend a cheaper approach step") — that item turned out to be
blocked on something more fundamental, not just missing.

**The real finding**: every cost computation in this codebase — pre-run estimates
(`app/pipeline/cost_controller.py::estimate_epic_cost`) *and* real post-run actual-cost tracking
(`app/agents/manager.py:130`, `app/fleet/metrics.py:179`) — uses a single flat
`cost_per_input_token`/`cost_per_output_token` pair (`app/config.py`), whose own field description
literally says `"Haiku pricing"`. But `app/fleet/model_router.py::route()` already computes a real
per-agent model **tier** (`sonnet` by default, `haiku` for specific agents) — most real coding/QA/
review work runs on Sonnet per this project's own permanent model-tiering rule
(`CLAUDE.md`: "CODING/QA/REVIEW agents → Claude Sonnet"), not Haiku. So every real cost figure this
system has ever computed — the pre-run estimate that gates `requires_approval` (epics over
`cost_approval_threshold` need human sign-off), and the actual post-run cost shown anywhere —
has likely been computed at the wrong (cheaper) rate for the majority of real runs, not just
imprecisely rounded.

**Why this blocks Q42 specifically**: "recommend a cheaper approach" (e.g. "use a smaller model,
save $X") is not a meaningful recommendation to build on top of a cost model that doesn't
distinguish model tiers in the first place — there's no "cheaper" to compute relative to, since
every tier is already priced identically today.

**Severity**: real, but not urgent-critical — this doesn't cause data loss or a safety failure, but
it is a real correctness gap in a cost-governance mechanism (`requires_approval` gating could
silently under-trigger for expensive Sonnet-tier epics, and any cost dashboard/report is
systematically understated for non-Haiku work). Not verified precisely how large the real-world
gap is (would need real per-tier Anthropic pricing figures, not asserted here from memory per this
project's own zero-hallucination rule) — but the *mechanism* is confirmed wrong regardless of the
exact magnitude.

**What a real fix requires**: per-tier pricing config (at minimum haiku/sonnet, ideally matching
whatever tiers `model_router.py`'s own `_tiers` table defines), threaded through
`estimate_epic_cost()` (which would need to know which tier the epic's agents will actually run at
— `model_router.route(agent_name).tier` already provides this, just not consulted here) and the 2
real post-run cost call sites. Only after that exists does "recommend a cheaper approach" (Q42)
become a meaningful, buildable feature — computing what the same estimate would cost at a cheaper
tier and surfacing the delta.

Size: **M**. Severity: **Medium-High** (cost-governance correctness, not safety).

### Fix — verified 2026-08-05

Real scope check before implementing (per this session's standing discipline) found the actual
picture was narrower than the finding above speculated: `estimate_epic_cost()`'s two real call
sites (`app/agents/manager.py`'s `_cost_estimate_node`/`_refine_and_dispatch_node`) both estimate
*before* any subtask is dispatched to a specific agent, and the real dev-dispatch decision
(`run_manager()`'s `selected_agent_name`) only ever chooses between `backend_dev`/`frontend_dev` —
both confirmed sonnet-tier in `agent_models.json`, same as the fixed `qa`/`reviewer` agents. So
there was no real per-tier signal available at either estimate call site to "consult" — the design
doc's own `model_router.route(agent_name).tier` framing didn't apply there. `app/agents/manager.py`'s
`compute_actual_cost_usd()` (epic-wide actual cost) was verified the same way: the only 4 agents
whose tokens ever feed its `epic_tokens_in`/`epic_tokens_out` are `backend_dev`, `frontend_dev`,
`qa`, `reviewer` — all sonnet-tier today. `app/fleet/metrics.py`'s `RunMetrics._recompute_cost()`,
by contrast, genuinely does run per-agent with a real `agent_name` available.

**What was implemented**:
- `app/config.py`: `cost_per_input_token`/`cost_per_output_token` corrected from the mislabeled,
  stale "Haiku pricing" (`0.0000008`/`0.000004`) to the real Sonnet-tier rate (`0.000003`/`0.000015`,
  sourced from Anthropic's current published pricing, standard non-introductory rate so the default
  doesn't go stale when the introductory Sonnet 5 discount period ends). Also now the documented
  fallback rate for any tier without its own dedicated field. Added `cost_per_input_token_haiku`/
  `cost_per_output_token_haiku` (`0.000001`/`0.000005`) and `cost_per_input_token_opus`/
  `cost_per_output_token_opus` (`0.000005`/`0.000025`).
- `app/pipeline/cost_controller.py`: new `cost_rates_for_tier(tier, settings)` — the single tier-aware
  lookup (haiku/opus dedicated, everything else incl. `"gpt"` — zero registered agents today, Groq
  deprecated 2026-06-17 — falls back to the sonnet/default rate, mirroring `ModelRouter.route()`'s
  own fallback-to-sonnet for unregistered names).
- `app/fleet/metrics.py`: `RunMetrics._recompute_cost()` now resolves `model_router.route(self.agent_name).tier`
  and prices via `cost_rates_for_tier()` instead of the single flat rate — the real per-run fix.
- `app/agents/manager.py`: `compute_actual_cost_usd()` left formula-unchanged (correct as-is given
  the verified all-sonnet contributor set) but given an explicit documented invariant + forward
  pointer to switch to per-tier accumulation if a non-sonnet agent is ever added to that dispatch
  path — the exact bug this fix closed, guarded by a new regression test.
- **Found and fixed the same stale value duplicated in the live `.env`** (not just `.env.example`) —
  the config.py default alone would have been silently overridden by the real running environment's
  own `COST_PER_INPUT_TOKEN=0.0000008`/`COST_PER_OUTPUT_TOKEN=0.000004`, exactly the "built but never
  wired" pattern this whole session has repeatedly found (Cluster N/O/Q). Updated both files.
- `tests/test_stage4_cluster_p_per_tier_cost.py` (11 new tests): `cost_rates_for_tier()` per tier +
  unknown-tier fallback; sourced-pricing sanity ordering (haiku < sonnet < opus); `RunMetrics`
  end-to-end proof for opus (architect), haiku (env_checker_agent), sonnet (backend_dev), and an
  unregistered agent name (falls back to sonnet via `ModelRouter`'s own `DEFAULT`); the
  `compute_actual_cost_usd` all-sonnet-contributor regression guard; and a direct proof the live
  settings no longer carry the stale Haiku value.
- Fixed `tests/test_cost_controller.py::test_estimate_with_historical_averages`, which had hardcoded
  the stale `0.0000008`/`0.000004` literals directly (would have kept silently passing after the
  real fix landed if left as-is) — now reads `get_settings()` dynamically, same standard this
  session has applied throughout.

Zero regressions: full backend suite green after the fix (see `IMPLEMENTATION_PROGRESS.md`).

---

## Cluster Q — Unified quality score has no real cross-category inputs to aggregate (found 2026-08-05, scoping Q117)

Found while scoping Q117 ("no unified cross-category quality score"). The backlog's own original
note assumed this was "an aggregation layer over data that mostly already exists
(`benchmark_manager.py`, `dependency_security_agent`, test counts)" — checked that assumption
directly rather than trusting it (same discipline that caught Q95/Cluster O), and it's wrong on
inspection: most of the category data doesn't exist in scoreable form yet.

**The real finding**: `grep` for `security_score`/`vulnerability_count`/`security_findings`,
`docs_coverage`/`documentation_score`, `architecture_score`/`arch_drift`/`complexity_score`, and
`test_coverage`/`coverage_pct` across `app/` turned up **zero** matches for security, docs, and
architecture scoring — those categories have no structured numeric output anywhere. What exists:
- `benchmark_manager.py::BenchmarkResult.objectives["benchmark_score"]` — real, computed, persisted
  (migration 012) — but this measures **agent execution quality** (latency/tool-accuracy/
  verification/retry/compile/hallucination), not "tools" or "architecture" as the question's
  category list implies.
- `dependency_security_agent.py` and `test_coverage_agent.py` are both real LangGraph agents
  (`run_dependency_security_agent()`, `run_test_coverage_agent()`) that return a narrative
  `AgentResult` (LLM tool-driven analysis) — not a structured numeric score. There is nothing to
  average into a composite today; the agents produce prose/findings, not a `float` in `[0, 1]`.
- "prompts" and "docs" categories have no producing agent or metric at all.

**Why this isn't a Tier 3 item**: a real fix needs, at minimum, (1) deciding what a numeric
security/docs/architecture score even means and where its inputs come from (parsing
`dependency_security_agent`'s findings into a severity-weighted count would be the honest path for
security; docs/architecture would need new instrumentation, not just a query), (2) building those
missing scoring functions without fabricating them (the project's own Zero Hallucination Rules
forbid inventing a number with no real basis), and only then (3) a genuine aggregation/weighting
layer with new config weights, likely a new DB table for historical tracking (mirroring
`agent_benchmarks`), and an API surface. That is the same shape as Cluster N/O — a real subsystem,
not a query over existing data.

**Severity**: real but low-urgency — no other subsystem depends on this being unified (unlike
Cluster N's orphan recovery or Cluster O's cross-repo leakage risk); it's a reporting/visibility gap,
not a correctness or safety one.

Size: **M-L** (mostly gated on deciding real per-category metrics, not raw effort). Not fixed in
this pass — documented and Q117 marked blocked-on-this rather than fabricating a placeholder score.

### Architecture review (2026-08-05) — per-category producer audit before any aggregation work

Q117's real category list (`Bhaskar's_questions.md` #117, verbatim): **Architecture, Prompts,
Agents, Tools, Memory, Documentation, Tests, Performance, Security** — 9 categories. The original
finding above checked 4 of these with a name-pattern grep; this pass verified all 9 directly against
real code (submit-tool schemas, DB migrations, agent implementations), not the category's name
alone — because a category name matching a real signal's name does not mean the signal is the right
*kind* of data for that category (the same trap the original finding already caught once, with
`benchmark_score` measuring agent execution quality, not "Tools"). Two more instances of that exact
trap turned up in this pass:

| Category | Real producer today | Verified shape | Honest path to a real score |
|---|---|---|---|
| **Agents** | `benchmark_manager.py` → `agent_benchmarks` table (migration 012) | **Real, working, historical.** `objectives` JSONB per run: `latency_p50`, `tool_accuracy`, `verification_coverage`, `retry_success`, `compile_success`, `hallucination_rate`, weighted into `benchmark_score` (`config.py`'s `benchmark_weight_*`); `is_baseline` flag drives `compare_to_baseline()`. | Already done — this is the one category with a full, working "track improvements over time" precedent. Any new per-category table should mirror this shape. |
| **Architecture** | `architecture_reviewer.py` → `submit_arch_review` | No numeric score, but `risks[]` is already structured: `{severity: enum[critical\|high\|medium\|low], description, evidence[]}` (`app/agents/tools.py:3885-3925`). | **Cheap, honest, non-fabricated path exists**: severity-weighted count over `risks[]`. Needs an aggregator + a new historical table (mirroring `agent_benchmarks`) — no new agent instrumentation required. |
| **Security** | `dependency_security_agent.py` → `submit_dependency_security_agent` | **Wrong shape, not missing**: `findings` is `array[string]` — free text, no severity field (unlike architecture_reviewer's `risks[]`). The underlying `pip-audit`/`npm audit` run via `DEPENDENCY_AUDIT_BASH_TOOL` *does* emit structured JSON with real CVE severities as its raw stdout, but that structured output is discarded — only the LLM's narrative summary of it survives into the result. | The original finding's suggested path ("parse dependency_security_agent's findings into a severity-weighted count") is **not actually available as-is** — `findings` has nothing to parse. The real honest path is different: capture and parse the audit tool's own raw JSON output directly (deterministic, zero LLM-interpretation risk), not the agent's narrative findings. Needs a schema/capture change in the agent, not just an aggregator. |
| **Tests** | `test_coverage_agent.py` → `submit_test_coverage_agent` | Agent's role prompt explicitly requires running real `pytest --cov`/`jest --coverage` via bash and forbids reporting a percentage "you didn't actually measure this run" — but the submit schema (`summary`, `findings: array[string]`, `recommendations: array[string]`) has **no numeric field to put that percentage in**. The real number is measured every run and then discarded into prose. | **Cheapest real fix of all 9**: no new instrumentation needed, no new tool call — just add a structured field (e.g. `coverage_pct: number`) to the existing submit schema so the number the agent already computes gets captured instead of thrown away. |
| **Memory** | `app/memory/store.py`'s `_COMPOSITE_SCORE_EXPR` (`memory_score_weight_*` in `config.py`) | **Real, but the wrong kind of signal** — this is a per-row *retrieval-ranking* formula (similarity + recency + reuse + importance + verified, SQL-computed per query to rank candidate memories), not a subsystem-wide health/quality score tracked over time. Reusing it as "Memory category score" would misrepresent a ranking heuristic as a quality metric. | Needs a genuinely new signal — e.g. dedupe rate, verified-vs-unverified ratio, staleness distribution across `memory_embeddings` — none of which exist today. |
| **Tools** | `RunMetrics.tool_accuracy` (`app/fleet/metrics.py`) / `benchmark_weight_tool_accuracy` | **Real, but scoped to one agent run**, not a fleet-wide "Tools" subsystem signal (tool schema health, per-tool reliability across all agents, deprecated/unused tool detection). Already folded into `benchmark_score` as one of six weighted signals for the **Agents** category. | No dedicated producer exists. Would need new instrumentation aggregating tool-call outcomes *across* agents/runs, not reuse of the existing per-run number. |
| **Performance** | `benchmark_score`'s `latency_p50` component | Same shape mismatch as Tools: measures *this orchestrator's own agent-run wall-clock time*, not the shipped application's real runtime performance. `load_test_agent.py`'s submit schema (`summary`, `findings: array[string]`, `recommendations: array[string]`) is purely narrative — no numeric throughput/latency field despite the agent's whole job being load testing. | Needs new structured capture in `load_test_agent`'s submit schema (same shape of fix as Tests) plus a decision on what "Performance" means for a codebase with no deployed running instance to measure. |
| **Prompts** | none | **Zero real signal anywhere** — `app/fleet/prompt_registry.py` has no quality/score fields at all; no agent evaluates prompt quality. | Needs net-new instrumentation from scratch — no existing data to build on, honestly or otherwise. |
| **Documentation** | none | **Zero real signal anywhere.** Multiple real agents *write* documentation (`api_docs_agent`, `docker_agent`, `migration_guide_doc_agent`, `tool_catalog_doc_agent`, `architecture_doc_agent`, `agent_roster_doc_agent`) — none *measure* coverage, staleness, or quality of what exists. | Needs net-new instrumentation from scratch (e.g. docstring/README coverage via AST, staleness via git blame vs. code-change recency) — no existing data to build on. |

**Net picture**: 1 of 9 categories (Agents) is fully real and historical today. 3 of 9 (Architecture,
Security, Tests) have a genuinely honest, non-fabricated path available from data that's already
either structured or already computed-and-discarded — none of these three require new agent
capability, only capture/aggregation work, though Security's real path differs from what this
section originally assumed. 2 of 9 (Memory, Tools — plus Performance, arguably a 3rd) have a
real *existing* signal that is the **wrong kind** for this purpose and must not be reused as-is,
on pain of exactly the "aggregation on inferred data" the user asked this review to guard against.
2 of 9 (Prompts, Documentation) have nothing at all and need net-new instrumentation from scratch.

This means Cluster Q is not one M-L-sized piece of work — it's at minimum 3 substantially
independent efforts (a cheap schema-capture fix for Tests; an aggregator over already-structured
`risks[]` for Architecture; a capture-and-parse fix for Security) plus a decision on whether/how to
tackle the harder net-new categories (Prompts, Documentation, and a correctly-scoped Memory/Tools/
Performance) before any single "unified cross-category score" can exist without a placeholder or
fabricated component. Recommended staging, cheapest-and-most-honest first: **Tests → Architecture →
Security**, each independently shippable and each adding one real category to the eventual
aggregate; the composite/weighting/aggregation layer and its historical table should not be built
until at least these 3 are real, so the aggregation code is never written against placeholder data
for categories it already claims to cover.

### Tests slice — implemented + verified 2026-08-05

User-approved first slice (of the 3-effort staging above): add `coverage_pct` to
`test_coverage_agent`'s existing submit schema — no new agent capability, no aggregator/historical
table yet.

**Implemented**:
- `app/agents/test_coverage_agent.py`: `_SUBMIT` schema gained `coverage_pct: [number, null]`
  (optional — `required` stays `["summary"]` only, so a genuinely blocked run, e.g. coverage tool
  unavailable, is never pressured into fabricating a number to pass schema validation). Role-prompt
  message (`run_test_coverage_agent`'s `msg`) and `roles/test_coverage_agent.md`'s Process step 6
  both updated to tell the model to include it.
- **Second real gap found and fixed in the same change**: even with the schema field added,
  `app/api/specialized_agents.py`'s two real persistence call sites (`_run_specialized_agent_bg`,
  `run_specialized_agent_sync`) build a hand-rolled `artifact_payload` dict that never included
  `AgentResult.raw` at all — so `coverage_pct` would have been captured by the schema and then
  silently discarded a second time at the artifact-write boundary, the exact "measured then
  discarded" pattern this whole item is about, one layer deeper. Fixed narrowly: both call sites now
  add `artifact_payload["coverage_pct"] = result.raw.get("coverage_pct")`, **gated on
  `agent_name == "test_coverage_agent"`** — deliberately not exposing `raw` fleet-wide for all 78
  agents, which is outside this slice's approved scope.
- **Pre-existing, unrelated gap found and documented, not fixed**: `roles/test_coverage_agent.md`'s
  own "Output Contract" section (lines 51-58) describes a *different* contract than the real code
  implements — `coverage`/`critical_gaps`/`status` fields that don't exist in `_SUBMIT` at all,
  same bug class as the Day 48/49 `submit_arch_review`/`submit_dependency_report` schema-vs-role-file
  mismatches referenced in `app/agents/tools.py`'s own comments. Left unfixed here — reconciling it
  is a larger, separate change than adding one field, and doing it silently inside this slice would
  be exactly the unrelated-change scope creep this project's standards warn against. Flagged for a
  future pass.

**Verified**: `tests/test_stage4_cluster_q_test_coverage_pct.py` (7 new tests) — schema shape
(optional/nullable, `summary` still the only required field); end-to-end proof via a mocked
`run_agent_graph` that a real `coverage_pct` survives into `AgentResult.raw`, and that a blocked run
carries none (never fabricated); both persistence call sites (`_run_specialized_agent_bg`,
`run_specialized_agent_sync`) persist `coverage_pct` for `test_coverage_agent` and — regression guard
— do *not* add the key for any other agent (`debugger_agent`), proving the fix stayed scoped.
`mypy --strict` clean on both touched modules. `tests/test_day6b_agents.py`,
`tests/test_phase3_verification_audit.py`, `tests/test_memory_hooks.py`,
`tests/test_phase34_real_output_verification.py` (229 tests covering this agent's contract shape and
the same 2 persistence call sites from other angles) all still green. **Full backend suite confirmed:
3807 passed, 0 failed, 56 skipped** — exact match to the 3800 prior baseline + 7 new tests, zero
regressions.

### Architecture slice — implemented + verified 2026-08-05

Re-verified before writing any code (per user instruction) that `architecture_reviewer` genuinely
produces sufficient structured data: `run_arch_review()`'s `submit_arch_review` schema
(`app/agents/tools.py`) declares `risks[]` as `{severity: enum[critical|high|medium|low],
description, evidence[]}` — `severity` is a real JSON-schema enum, not free text. Also confirmed a
**second, separate real producer exists but is out of scope**: `run_architecture_reviewer_scan()`
(the periodic autonomous SCAN phase, called from `app.main::_fleet_agents_scan_loop()`) files
`EnhancementRequest` rows via `submit_enhancement_request` (`priority` enum, human-approval workflow)
— a different real subsystem (an escalation backlog, not a point-in-time review snapshot). Scoring
against `risks[]` only, not conflating the two, is what "narrowly scoped to Architecture category
only" required here. Also confirmed `run_arch_review()` is dispatched only on-demand via
`specialized_agents.py`'s `"arch_reviewer"` registry key (not `"architecture_reviewer"`, the
`AGENT_CONTRACT` name — a real naming mismatch, noted for anyone wiring a future caller) — there is
no existing scheduled/automatic trigger, so "track improvements over time" is honestly a capability
that exists and works, not a claim that data is already accumulating today without a human or future
scheduler calling it.

**Implemented**:
- `app/config.py`: `architecture_score_weight_{critical,high,medium,low}` (policy defaults 1.0/0.5/
  0.2/0.05 — same category of config as `benchmark_weight_*`, not measured constants) and
  `architecture_score_risk_cap` (default 3.0 — the weighted-point sum at which the score bottoms at
  0.0).
- `app/fleet/architecture_score.py` (new module, mirrors `benchmark_manager.py`'s shape exactly — the
  one other real per-category historical-tracking precedent in this codebase): `compute_architecture_score()`
  is a pure function reading **only** the `severity` field (never `description`/`evidence`, proven by
  a dedicated test); a clean review (`risks=[]`) scores `1.0` vacuously, mirroring
  `benchmark_manager.py`'s own "no negative signal → full marks" convention; an unrecognized/missing
  severity value is excluded from both counts and the weighted sum, never guessed. `store_architecture_score()`/
  `get_latest_architecture_score()`/`get_architecture_score_trend()` are sync entry points (no
  AsyncSession param — matches `BenchmarkManager`'s real shape; no async caller exists yet, so one
  wasn't built) using `new_isolated_async_engine()` per call.
- New `architecture_scores` table (migration 028, applied and verified against real Postgres):
  `task_id`, `repo_id` (resolved via `DevTask.repo_id` — Cluster O's established single source of
  truth, ADR 006 — nullable per INV-8), `risk_counts` JSONB, `weighted_risk_score`,
  `architecture_score`, `created_at`.
- `app/agents/architecture_reviewer.py::run_arch_review()`: computes and persists a score only when
  `import_graph_ran` is real graph-verified True (the same flag `AgentResult.verified` already uses)
  — an unverified run's `risks[]` claim isn't independently grounded, so no row is written for it,
  never a score built on an unverified claim. Non-fatal: a persistence failure logs and returns,
  never breaks the real review.

**Verified**: `tests/test_stage4_cluster_q_architecture_score.py` (9 new tests) — pure-function
formula correctness (weighting, clamping at 0, vacuous 1.0, unrecognized-severity exclusion, and a
dedicated test proving identical scores regardless of narrative text content); real-Postgres
persist/read-back (`store_architecture_score` → `get_latest_architecture_score`/
`get_architecture_score_trend`, newest-first); and a full end-to-end test (`run_arch_review()` with
`run_agent_graph` mocked at the LLM seam only — not the scoring logic — proving a real Postgres row
is written and reads back with the exact value `compute_architecture_score()` itself would produce,
so the test can't drift from the real formula) plus the unverified-run-persists-nothing gate.
**`git stash` confirmed the real discriminating test fails without the wiring**: with
`architecture_reviewer.py`'s implementation reverted (module/config/migration left in place), the
end-to-end persistence test failed with a clear message (`latest is not None` → `assert None is not
None`) while the 8 other tests (pure function + persistence-layer-in-isolation) correctly still
passed — proving the E2E test specifically exercises the real wiring, not just the standalone module.
`mypy app/ --strict` clean across all 193 source files. 492 tests across every file referencing
`architecture_reviewer`/`run_arch_review` (day2/day6b contract tests, gap48 scan tests, phase3/phase4
verification-audit tests) still green. **Full backend suite confirmed: 3816 passed, 0 failed, 56
skipped** — exact match to the 3807 prior baseline + 9 new tests, zero regressions.

**Architecture slice is production verified.** Per user instruction, the Security slice does not
begin until this is fully documented — this entry is that record.

**Next**: Security (capture-and-parse the `pip-audit`/`npm audit` tool's own raw JSON output, per the
architecture review's corrected finding — not the originally-assumed `dependency_security_agent`
`findings` parse) is the last of the 3 staged efforts — not yet started, awaiting user direction.

---

## Cluster R — Epics have no repository assignment mechanism (found 2026-08-05, discovered implementing Cluster O Phase 1b)

Found while implementing Cluster O Phase 1b's change point D (threading `repo_id` through
`manager.py`'s epic-manager graph). Not assumed — confirmed by reading the real `/api/epics` POST
endpoint (`app/api/epics.py::create_epic`) directly.

**The real finding**: `CreateEpicRequest` (`app/api/epics.py`) has exactly two fields — `title` and
`description` — and the `Epic` model (`app/db/models.py`) has no `repo_id` (or `repo_path`) column
at all. `run_epic_manager()`'s own `repo_path: str | None = None` parameter exists but is never
populated by the real `/api/epics` creation flow (`_launch_epic_manager(epic_id, body.description)`
passes only `epic_id`/`goal`). Downstream, `_planning_node`'s internally-created `DevTask` (the one
real per-epic task row, `manager.py`) is created without `repo_id=` set, so it always resolves to
`None`. **This is not a Cluster O gap** — Cluster O's own repo_id-threading wiring for epics
(`EpicManagerState["repo_id"]`, shipped in Phase 1b) is correct and already forward-compatible; there
is simply no repo assignment anywhere upstream for it to thread. This is a **missing domain
capability**: epics, as a top-level unit of work in this system, have no concept of "which repository
this epic's work happens in" at all, unlike `DevTask` (which has had `repo_id` since Day 0) and `Repo`
(which has been a first-class entity since the original repo-management work).

**Why this matters**: every real epic created through the actual UI today operates against
whichever repo is either explicitly passed (never, in practice) or falls back through
`state.get("repo", settings.target_repo_path)` deep in the pipeline — the same class of
"resolve at the wrong time, from the wrong source" risk Day 4 fixed for individual task dispatch,
except epics were never brought under that fix because they had no `repo_id` to resolve from in the
first place. In a genuinely multi-repo deployment, this means every epic silently operates on
whatever repo happens to be globally active, with no way for a human to specify or verify which repo
an epic's work is scoped to at creation time.

**What a real fix requires**: (1) add `repo_id: int | None` to `CreateEpicRequest` and the `Epic`
model (a real Alembic migration, mirroring `dev_tasks.repo_id`'s own FK/index shape from migration
024), (2) thread it through `create_epic()` → `_launch_epic_manager()` → `run_epic_manager()` →
`EpicManagerState` → `_planning_node`'s `DevTask(...)` creation (at which point Cluster O's own
Phase 1b wiring picks it up automatically — no further memory-scoping work needed), (3) decide the
UI/API contract: is `repo_id` required at epic creation, or does it default to the currently-active
repo the same way `DevTask` creation already does elsewhere in this codebase, (4) decide what happens
to epics created before this migration (mirrors Cluster O's own Q8 "NULL means legacy/unscoped"
precedent — likely the same answer here).

**Severity**: real, not urgent-critical — no data leakage or correctness failure results from this
today (an epic's memory just stays globally-visible, the same safe default every other unscoped
category already gets); the real cost is an epic-management/multi-repo usability gap, not a security
one. Distinct from Cluster O's own cross-repo leakage risk, which is why this is its own cluster
rather than folded back into O.

Size: **S-M** (one migration, one API field, threading through an already-understood, already-mapped
call path — Cluster O's Phase 1b work already identified exactly where `repo_id` needs to enter the
epic-manager graph). Not fixed in this pass — documented and promoted to its own cluster per explicit
instruction, rather than treated as a footnote inside Cluster O.

---

## Tier 2 — Clustered PARTIAL sub-gaps (existing feature, real named gap inside it)

Grouped by root cause / shared code path, same style as `PLAN.md`'s Stage 0 clustering.

### Cluster A — Cross-process scale (CRITICAL, per answer2.md's own priority list)
- Q46/Q48/Q94: `asyncio.Semaphore` concurrency slots (`app/pipeline/concurrency.py`) are
  in-process only — don't hold across multiple backend processes. Fix: Postgres row-locks or
  Redis token bucket for `max_concurrent_agent_runs`.
- Q48/Q94: No multi-tenant `Project`/workspace entity above the single `Repo` model.
Size: **XL** (architectural — likely the single largest item in this backlog).

### Cluster B — Agent-to-agent collaboration (CRITICAL)
- Q2/Q62: no agent-to-agent request/negotiation mechanism (escalation only goes up to
  manager/human, never sideways to a peer).
- Q2: no "agent declines a task" mechanism — `FleetManager.select()` filters before dispatch, the
  agent is never offered a chance to refuse.
Size: **L**

### Cluster C — Agent lifecycle & selection scoring
- Q3: memory, current-workload (graded, not just available/unavailable), and confidence are not
  factors in `FleetManager.select()`'s scoring formula.
- Q88: no alerting for slow/looping/hallucinating/idle/overloaded agents beyond the raw
  `max_turns`/`max_stalls` bound.
- Q77: no load-balancing optimizer beyond health/availability gating.
Size: **M**

### Cluster D — Self-improvement completeness
- Q36: nothing decides a prompt is weak / initiates a change (Day 50 built the delivery pipeline;
  the decision-making trigger is still missing).
- Q118: no "simulate impact" step before an APPLY; no automatic rollback on a detected post-apply
  regression (`failure_ladder.py` rollback stays manual/operator-invoked by design).
- Q34: no milestone-level rollback distinct from per-subtask retry/escalate.
Size: **M**

### Cluster E — Intent & requirement understanding
- Q25: no vagueness detector, no hidden-intent detection, no single-prompt→multiple-top-level-tasks
  splitter, no explicit intent classifier (explanation-only vs. implementation vs. debugging vs.
  comparison vs. documentation-only).
- Q28: no "raw giant prompt → milestones" step distinct from `decomposer.py`'s plan-splitting; no
  "propose an alternative architecture" capability; impossible-requirement detection only catches
  *contradicted* constraints, not abstractly-impossible ones.
- Q26: abusive-language/mixed-language/extreme-length prompt handling — not dedicated, not
  code-verified (relies on base model).
Size: **M**

### Cluster F — File format coverage
- Q16: zero parsers for Jupyter Notebook, Excel, Word, PowerPoint, Audio, Video (6 formats,
  confirmed by grep for `ipynb`/`nbformat`/`openpyxl`/`python-docx`/`python-pptx`/`whisper`/`ffmpeg`
  — all zero hits).
- Q16: PHP has no tree-sitter grammar (plain-text read only).
Size: **M** (mostly library integration — `nbformat`, `openpyxl`, `python-docx`, `python-pptx` are
real, well-documented libraries; audio/video transcription is the outlier, needs a model decision).

### Cluster G — Realtime & frontend
- Q9: no WebSocket endpoints anywhere (SSE is the only real-time mechanism).
- Q9: `error.tsx` boundaries not exhaustively verified at every nested route.
Size: **S-M**

### Cluster H — Codebase health detectors
- Q35: no unused-file detector, no duplicate-function detector, no memory-leak detector.
- Q35: dependency-conflict detection is CVE-scan only, not a version-constraint-graph solver.
- Q98: `version_manager_agent` is actually a dependency-version auditor, not a
  semver-compatibility-reasoning tool (misleading name, real gap underneath).
Size: **M**

### Cluster I — Deployment intelligence
- Q19: no deployment-health-check/diagnose tool.
- Q19: no dedicated deployment-guide generator (only a migration-guide generator exists).
- Q19: no per-platform tooling beyond Docker (Vercel/Railway/Kubernetes/Azure/AWS/GCP are
  incidental prompt mentions only).
Size: **M**

### Cluster J — Explainability & documentation completeness
- Q44/Q104: `architect.md`'s plan output has no "alternatives considered" field; agent-selection
  score and tool-usage reasoning aren't surfaced as a user-facing explanation artifact.
- Q41: 5 of 8 real doc agents remain on-demand only (only `changelog_agent`/`release_notes_agent`
  auto-trigger on `main` HEAD movement).
- Q67: no dedicated "inspect coding standards / inspect existing tests before writing new ones /
  inspect docs first" steps.
Size: **S-M**

### Cluster K — Governance beyond safety
- Q85: coding standards/naming conventions/approved frameworks/licensing policy are prompt-level
  only — `app/policy/engine.py` is safety-scoped (paths/commands), not a standards-enforcement layer.
- Q86: no dedicated `Scheduler`/priority-queue class; `DevTask.priority` is unenforced free text,
  not fed into execution order.
Size: **M**

### Cluster L — Memory system residual gaps
- Q5: working memory has no explicit auto-discard step; session memory isn't a distinct object
  from raw message history; project-memory `repo_id` scoping not independently re-verified at
  every single `query_*`/`embed_*` call site (flagged, not confirmed complete, in both audits).
- Q120: no conflict-resolution mechanism for concurrent memory writes beyond DB transaction
  semantics; no full usefulness/accuracy scoring pass on stored memories; archived rows are never
  purged (no real storage reduction over time, only archival).
Size: **S-M**

### Cluster M — Execution control edge cases
- Q14: no clean mid-graph "cancel this agent run" API; the epic-manager graph has **no
  checkpointer at all**, unlike `chat_agent.py`'s graph (a real, named asymmetry).
- Q45: no branch-change detection to invalidate a stale checkpoint referencing since-changed files.
- Q103: no generic "stop this agent regardless of what it's doing" API; no human take-over /
  edit-in-flight-plan capability.
Size: **M**

---

## Tier 3 — Small / verification-only items (cheap, high leverage — do these first)

These mirror Stage 0's original "cheap fixes" bucket — small, mostly single-file, no architectural
decision needed:

- **NEW (found 2026-08-04 during Cluster N production validation, not yet fixed)**:
  `app/services/retention.py`'s day-scale log/memory-embeddings retention cutoffs
  (`_run_cleanup()`, lines ~88/95) use the same `.replace(tzinfo=None)` naive-datetime pattern
  `reconcile_orphaned_runs()` had — confirmed the same real bug class (a non-UTC system timezone
  causes the DB driver to misinterpret the naive cutoff, landing it ~5.5 hours off) — but the
  file's own code comment (lines 44-52) explicitly claims this doesn't matter for raw `text()` SQL,
  which is the same incorrect assumption that hid the orphan-recovery bug. Low real-world severity
  (a multi-day retention window firing ~5.5 hours "late" daily is a minor scheduling imprecision,
  not a correctness failure), so deliberately not fixed today (out of Cluster N's scope) — but the
  comment is now known to be wrong and should be corrected alongside a real fix (keep `now`/`cutoff`
  timezone-aware, matching `reconcile_orphaned_runs()`'s fix) when this item is picked up.
- Q1: ~~remaining POSIX-only shell patterns (`source .venv/bin/activate`) not yet ported to the
  Windows branches.~~ **DONE 2026-08-05** — genuinely bounded, as originally estimated. All 11 real
  call sites in `app/agents/tools.py` consolidated onto one shared `_venv_activate_snippet()`
  helper (`sys.platform`-branched: POSIX unchanged byte-for-byte, Windows gets real
  `.venv\Scripts\activate.bat`/`2>nul`/`ver` cmd.exe syntax instead of meaningless bash-isms).
  3 new tests (`tests/test_stage4_tier3_venv_activate_cross_platform.py`) plus the 8 pre-existing
  `test_gap15_test_runner_exit_code.py` tests (real subprocess pytest execution against 2 of the 11
  fixed sites) all pass unchanged. Windows branch verified by construction only (no Windows host in
  this environment), stated honestly. **Related, still-open, deliberately out of scope**: 5 of the
  11 sites also pipe through `| head -N`/`| tail -N` (also POSIX-only, `head`/`tail` aren't cmd.exe
  builtins) — the same bug *class*, a different named finding (Q1 was specifically about venv
  activation), not fixed here per "avoid bundling unrelated fixes."
- Q2: ~~`DevTask.priority` not DB-enforced (ties into Cluster K, but the flag-only part is cheap).~~
  **DONE 2026-08-05** — genuinely bounded, as originally estimated. Migration `027` adds a real
  `CHECK (priority IN ('low','medium','high'))`, actually run against this environment's live
  Postgres (upgrade + downgrade + re-upgrade all exercised, not just authored); `CreateTaskRequest.
  priority` tightened to `Literal["low","medium","high"]` for a real 422 at the API boundary. 5 new
  tests, all real (2 hit the live DB directly: a raw-SQL insert proving the CHECK constraint itself,
  and a real `create_task()` call for all 3 valid values). **Priority still isn't fed into
  scheduling order anywhere** — that's Cluster K's job (a real scheduler doesn't exist), correctly
  left out of this fix per "avoid bundling unrelated fixes."
- Q4: ~~no automatic tool-level retry wrapper (retry currently only at the agent-run level).~~
  **DONE 2026-08-05** — `tool_manifest.py`'s `retry_policy` field (declared on all 193 tools, zero
  real readers before this) is now consumed by a new `_run_tool_with_retry()` in
  `app/agents/base_graph.py`'s shared `execute_tools` node. Deliberately excludes 2 real hazard
  classes discovered while scoping this (by permission, not a hand-maintained name list):
  `write_remote` tools (a false-negative network error could mean a PR/Slack-message already sent —
  retry risks a real duplicate) and `execute`/`write_repo` tools (`run_tests` etc. fail
  deterministically far more often than transiently — retrying doubles real wall-clock cost for an
  outcome a retry can't change). Only 7 of 19 manifest-tagged tools end up eligible — all pure
  network reads. 7 new tests, including 2 that specifically prove the exclusions hold (`run_tests`
  and `slack_send_message` never auto-retry despite their own manifest saying `"once"`).
- Q6: ~~`enable_critique`/`enable_replanning` not universal — currently opt-in for 5 highest-risk
  agents only; decide whether to widen.~~ **SCOPED 2026-08-05, deliberately NOT flipped** — verified
  the real current state first (still exactly 5/76 for `enable_critique` — `coder`/`backend_dev`/
  `frontend_dev`/`qa`/`reviewer`; confirmed 0/76 for `enable_replanning`, not just "not universal").
  This is not an oversight: `build_agent_graph()`'s own code comments describe it as a deliberate,
  staged "Session-0-style rollout" — the *same* pattern this project used for
  `enable_planning`/`enable_memory`/`enable_reflection` (all launched `False` fleet-wide, "flipped
  True fleet-wide after dedicated testing," per the code's own history). `enable_critique` adds a
  real extra LLM call per turn (a `critique_node` reviewing the agent's own output) — flipping it
  for all 76 agents is a real cost/latency decision affecting the whole fleet simultaneously, the
  same category of change this project's own established precedent handles with dedicated
  validation days, not a one-line Tier-3 flip. Left as-is; a real "widen the rollout" decision
  belongs in its own dedicated pass with real before/after cost measurement, not decided
  unilaterally here.
- Q7: ~~no sentiment/satisfaction-detection code anywhere.~~ **DONE 2026-08-05** — new
  `app/agents/user_sentiment.py::detect_user_frustration()`, 3 real bounded signals (known-phrase
  regex, Jaccard message-repetition, excessive-caps ratio, all config-thresholded), wired into
  `ChatAgent.run()` with a real `user_sentiment` SSE consumer (not "built but never wired"). 10 new
  tests. See `IMPLEMENTATION_PROGRESS.md` 2026-08-05 entry for full evidence.
- Q17: ~~`docker_logs` returns raw output only — no structured parsing/pattern-detection layer.~~
  **DONE 2026-08-05** — new `_summarize_docker_log_patterns()` mirrors `tools.py`'s own established
  `analyze_error()` convention (real pattern list, "=== X Analysis ===" summary prepended to the
  real raw content, not replacing it). Detects error/exception/warning lines and crash/OOM
  signatures. Found and fixed a SECOND, near-duplicate `docker_logs` implementation
  (`make_chat_handlers`'s own, distinct from `make_docker_agent_handlers`'s) that would otherwise
  have been silently missed. 7 new tests, 2 against real running containers
  (`gridiron-postgres`, already running in this environment).
- Q20: ~~`web_search`/`fetch_url` are scoped to `research_agent` only, not fleet-wide.~~
  **DONE 2026-08-05 — the real bug was narrower and different from this one-liner's framing.**
  First read this as a Q6-style "should we widen fleet-wide web access" scope decision and nearly
  left it alone — but `answers.md`'s own existing Q20 section already documented a much more
  specific, already-diagnosed bug: `RESEARCH_TOOLS` (`tools.py:1729`, the actual tool **schema**
  array sent to the model) never included `_WEB_SEARCH_TOOL`, even though
  `make_research_handlers()` (`tools.py:1772`) DOES wire a real `web_search` **handler**. Confirmed
  live before touching anything: `research.py`'s `AGENT_CONTRACT["allowed_tools"]` also omitted
  `"web_search"` while its own `capabilities` list claims `"web_search"` — a real contract/reality
  mismatch. Net effect: the one agent whose entire job is web research could never actually call
  `web_search` (Anthropic's tool-use API only allows tools present in the request's `tools` array).
  Fixed both: added `_WEB_SEARCH_TOOL` to `RESEARCH_TOOLS` and `"web_search"` to
  `research.py::AGENT_CONTRACT["allowed_tools"]`. Genuinely bounded — 2 files, matching this
  session's Q92-style "add real tool to an existing agent's real allowlist" shape, not a fleet-wide
  policy change. (`fetch_url` was correctly left `research_agent`-only and un-widened — no
  equivalent handler-vs-schema mismatch was found for it, and there's no evidence it was ever meant
  to be reachable there.)
- Q42: ~~no "recommend a cheaper approach" step (estimate exists, recommendation doesn't).~~
  **SCOPED 2026-08-05, blocked on new Cluster P, not independently fixable** — the cost model
  itself uses one flat rate for every model tier (mislabeled "Haiku pricing" but applied to Sonnet
  too), so there's no per-tier cost difference to recommend switching to yet. See Cluster P above.
- Q43: ~~`RunMetrics.confidence` is self-reported by the LLM, never independently verified.~~
  **DONE 2026-08-05, scoped honestly** — no ground-truth outcome labels exist anywhere to check
  confidence *accuracy* against (verifying "is 0.9 really 90% right" would need real labeled data
  this project doesn't have) — building that would be fabricating a capability, not implementing
  one. What's real and bounded: new `check_confidence_calibration()`
  (`app/fleet/metrics.py`) flags a real mismatch between self-reported confidence and this same
  run's *other* independently-computed signals (`verification_pct`, `reflection_unsatisfied`) —
  high confidence + poor real verification is flagged, low confidence never is (that's honest, not
  miscalibrated). New `RunMetrics.confidence_miscalibrated` field, wired into `run_agent_graph()`'s
  existing metrics-recording block. 3 new config thresholds (not hardcoded). 6 new tests.
- Q66: ~~exponential backoff not re-confirmed this pass~~ **RESOLVED Stage 3 Days 58-59** —
  `tests/test_gap58_59_llm_outage_retry_and_breaker.py`, real `httpx.MockTransport`-simulated
  outage, real SDK backoff measured.
- Q66: transaction-boundary/rollback-on-exception correctness not reviewed across all DB writes —
  still open, verification not build.
- Q92: ~~"detect abandoned libraries" not confirmed as distinct from "outdated" — verification
  task.~~ **DONE 2026-08-05** — was correctly assumed blocked on no network access when this
  backlog was written; re-checked live and network access IS available in this environment
  (`curl https://pypi.org` reachable), which changed the scope from "can't verify" to "can build."
  Confirmed the real, distinct gap first: `pip index versions`/`npm outdated` only compare
  installed-vs-latest, never expose *when* latest was published. New `check_last_release` tool
  (`app/agents/tools.py`, wired into `dependency_agent`'s real `AGENT_CONTRACT["allowed_tools"]`)
  queries the real PyPI/npm JSON registry APIs (both shapes verified live before writing any code
  against them) and classifies staleness via 2 new config thresholds (not hardcoded). 7 new tests,
  3 hitting real live registries (including `left-pad`, npm's own famous 2016-incident package,
  confirmed correctly classified ABANDONED — 3039 real days since last release).
- Q95: ~~`repo_id` threading at every `query_*`/`embed_*` call site — verification task, may resolve
  to "already fine" on inspection.~~ **VERIFIED 2026-08-04, moved to Cluster O below** — it was not
  already fine: confirmed 0 of 20 real call sites thread `repo_id`, and the real fix is comparable
  in size to Cluster N, not a Tier 3 item.
- Q102: ~~`on_heartbeat()` confirmed wired in `base.py`'s path, not confirmed wired into the main
  `base_graph.py::run_agent_graph()` path — verification, likely a 1-line fix if actually missing.~~
  **RESOLVED BY INVESTIGATION 2026-08-04, moved to Cluster N above** — it was not a 1-line fix; it's
  confirmed missing, and the real fix is L-sized, not a Tier 3 item.
- Q117: ~~no unified cross-category quality score (architecture/prompts/tools/docs/tests/security) —
  aggregation layer over data that mostly already exists (`benchmark_manager.py`,
  `dependency_security_agent`, test counts).~~ **VERIFIED 2026-08-05, moved to Cluster Q above** —
  the "data mostly already exists" assumption was wrong: confirmed 0 real numeric scores exist for
  security/docs/architecture categories (the 2 named agents produce narrative findings, not
  scores), so this is a new subsystem, not an aggregation query.
- Q119: ~~CEO Dashboard doesn't surface active-agent status/tech-debt/security-warnings together —
  the underlying data exists scattered; this is a dashboard-wiring task, not new data collection.~~
  **PARTIALLY DONE 2026-08-05, rest blocked on Cluster Q** — verified per-field first rather than
  trusting "data exists scattered": `/api/fleet/reports/health` (`app/api/fleet_dashboard.py`) was
  already real and correct (per-agent-type active-run count, failure rate, avg heartbeat staleness,
  all server-side Postgres aggregates) but **never fetched by the frontend at all** —
  `apps/web/app/fleet/page.tsx` only ever called `/api/fleet/requests`. Wired it in: new
  `refreshHealth()` fetch + a real "Agent Health" table section (active runs / failure rate /
  heartbeat staleness per agent type), non-fatal on failure (doesn't clobber the main
  pending-review error banner). 2 new Vitest tests (`app/fleet/page.test.tsx`, new file — this page
  had no test coverage before), `tsc --noEmit` clean, `eslint` clean, full frontend suite (34/34)
  green. Tech-debt and security-warning surfacing were **not** added: per Cluster Q's finding, those
  categories have no structured data to surface yet (`tech_debt_agent`/`dependency_security_agent`
  both return narrative `AgentResult`, not counts) — wiring a UI field to nothing would be
  fabrication, not a fix. That part is genuinely blocked on Cluster Q, not bounded Tier 3 work.

---

## Suggested staging order (updated 2026-08-05 — Tier 3 complete, 4 clusters now discovered)

Following `PLAN.md`'s own philosophy (root causes and cheap wins first, architecturally heavy work
gets dedicated days instead of being bundled):

1. ~~**Cluster N (orphan recovery is dead in production)**~~ — **DONE + PRODUCTION VERIFIED
   2026-08-04**, same day found.
2. ~~**Tier 3 cheap items**~~ — **DONE 2026-08-05.** 8 of 9 remaining items completed for real
   (Q4, Q6\*, Q7, Q17, Q20, Q42\*, Q43, Q92 — \*Q6 deliberately scoped/left as policy, Q42 blocked
   on Cluster P not independently fixable); 2 items (Q95, Q117) turned out to be real subsystems on
   inspection and were promoted to Cluster O and Cluster Q respectively rather than force-fit as
   small fixes; Q119 partially done (real data wired), remainder blocked on Cluster Q. Net: the
   Tier-3-cheap-wins hypothesis mostly held (matches this section's own original prediction that
   "a few of these may turn out to already be fine on inspection") — 2 of 11 items expanded, not
   more.
3. **Cluster O (`repo_id` scoping built but never wired)** — promoted next, ahead of everything
   below. Reasoning: confirmed 0 of 20 real `query_*`/`embed_*` call sites thread `repo_id` — this
   is a live cross-repo memory-leakage risk in a multi-repo deployment, not just a missing feature,
   making it the one remaining cluster with a correctness/security dimension comparable to Cluster
   N's. Design proposal owed to the user next (7 questions: repo_id source of truth, explicit-param
   vs auto-injection, call-site elimination via centralization, cache safety, backward
   compatibility, E2E leakage verification, zero-cross-repo-leakage guarantee) before any code.
4. **Cluster P (cost tracking uses flat Haiku-labeled rate for all model tiers)** — cost-governance
   correctness gap (`requires_approval` gating may silently under-trigger for expensive Sonnet-tier
   epics); real but not safety-critical, sequenced after Cluster O.
5. **Cluster C (agent lifecycle/selection)** and **Cluster D (self-improvement completeness)** —
   these extend `FleetManager`/`failure_ladder.py`, code with deep familiarity from Stage 0-2 and
   this session's Cluster N work.
6. **Cluster Q (unified cross-category quality score has no real inputs to aggregate)** — bundle
   with **Tier 1 items #8, #9, #12** (pattern recognition / tool evolution / capability-gap
   detection): all four are "build the missing structured signal, then aggregate" work sharing one
   likely aggregation layer. Lowest urgency of the 3 new clusters — reporting/visibility only, no
   other subsystem depends on it.
7. **Cluster F (file formats)**, **Cluster G (WebSocket)**, **Cluster I (deployment)** — mostly
   additive, low architectural risk.
8. **Cluster H, J, K, L, M** — medium items, sequence flexibly.
9. **Tier 1 remaining items (#1-7, #10, #11)** — the standalone new subsystems.
10. **Cluster A (cross-process scale) and Cluster B (agent-to-agent collaboration)** — deliberately
   last: these are the two largest, highest-risk architectural changes (per `answer2.md`'s own
   "Critical blockers" list), and every other cluster above touches code that becomes more complex
   to change once agents can talk to each other or run across multiple processes.

**Before locking this into day numbers**: repeat `PLAN.md`'s Day-1 baseline pass — grep the actual
call-site counts / current state for each cluster (the same discipline that turned "~75 file-count
figure" into "exactly 8 call sites" for the original Stage 0, and "data mostly exists" into "0 real
scores exist" for Cluster Q). Sizes above (S/M/L/XL) are `answer2.md`-informed estimates for
untouched clusters, not fresh measurements — Cluster N/O/P/Q sizes ARE fresh, this-session
measurements.

---
*Compiled 2026-08-03 from `answer2.md`'s 120-question strict audit. Every item above traces to a
specific Q# and named gap in that file — no item here was invented for this document.*
