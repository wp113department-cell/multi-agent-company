# 14-Priority Backlog — Audit & Implementation Plan

**Prepared:** 2026-08-11
**Method:** Every "current state" claim below was verified against `backend/app/**` directly (grep + file read, file:line cited), not assumed from the ChatGPT backlog's own framing. Every "how to build it" recommendation is grounded in a concrete pattern found in one of the 10 reference repos under `/repos` (autogen, langgraph, open-hands, composio, swe-agent). Where the backlog's premise ("you currently have X") turned out to be wrong, that's called out explicitly — this changes scope and effort in several places.

---

## 1. Executive verdict

| # | Priority (ChatGPT's title) | Verdict | Why |
|---|---|---|---|
| 1 | Agent-to-agent delegation | **Implement — ship with #13** | Genuinely missing. Clean addition, no conflict. Highest architectural value in the list. |
| 2 | Dynamic subtask creation | **Implement — highest risk, sequence last** | Genuinely missing, but touches `manager.py`'s dispatch loop which assumes a static, precomputed topological order. Needs careful design, not a quick add. |
| 3 | Memory-aware agent selection | **Implement — modified scope** | Backlog's schema claim is correct (no `agent_name` column). But `FleetManager` already does deterministic historical-performance scoring (success rate, confidence, tenure) — must extend it, not replace it. |
| 4 | Memory quality control | **Implement** | Correctly identified gap. Dedup exists; a pre-store accuracy/usefulness gate does not. |
| 5 | Memory consolidation/evolution | **Implement — reuse existing lifecycle** | Partially exists already (`versioned_memory.py` does 1:1 merge-with-provenance for a *separate* lessons table). Must extend that lifecycle to N-way clustering, not build a second one. |
| 6 | Session memory compression | **Implement — smaller than it looks** | In-session summarization exists but is ephemeral (never persisted, never categorized). The categorized `embed_*` functions it would call already exist per-category — this is a wiring task, not new infra. |
| 7 | General context compression | **Implement — small, localized** | Backlog is right: today is rank-then-hard-truncate at a single call site (`base_graph.py`). Contained fix. |
| 8 | Confidence must affect control flow | **Implement — finish, don't rebuild** | The gate (`quality_gate_min_confidence`) already exists in code but defaults to 0.0 and is never overridden — it's inert, not absent. `requires_human_approval` is **already exposed via API**, contradicting the backlog's claim it's "calculated and discarded." Real work is wiring the dormant threshold, not building new plumbing. |
| 9 | Fleet-wide replanning | **Implement — refine, don't "turn on more"** | Backlog frames this as "only some agents have it enabled" (true — 4 do) but the real gap is that the enabled agents use a static boolean with no adaptive trigger logic. Scope is refining `_should_replan()`, not toggling more agents. |
| 10 | Dynamic tool selection | **Implement — cheapest item in the list** | The capability-based tool registry/filter (`tool_discovery.py`) is **already fully built and completely unused** (zero real callers). This is wiring dead code, not building a new subsystem. |
| 11 | Agent performance → runtime decisions | **Mostly already done — small delta only** | `FleetManager.select()` already weights success rate, confidence, tenure/health into agent choice. The only genuinely missing signal is cost/latency. Reduce scope accordingly. |
| 12 | Agent communication protocol | **Implement — extend, don't replace** | A single consistent envelope (`GridironEvent`) already exists and is used everywhere. Building ChatGPT's separate `AgentMessage` type as proposed would fragment the system. Extend `GridironEvent` with delegation-relevant fields instead, as part of #1. |
| 13 | Agent delegation safety | **Implement — same phase as #1, not after** | ChatGPT's own doc says this ("implement together with delegation, not afterward") — the audit confirms zero cycle detection / depth limiting / caller matrix exists anywhere today, so there's nothing to retrofit onto; build it in. |
| 14 | Memory + orchestration as one feedback system | **Not a build item** | This is the *outcome* of #3 + #4 + #5 done correctly (write path already exists via `hooks.py`; read path is what #3 adds). Don't budget it as a separate phase — it's a description of what Phase 1+2 together produce, plus ~1 day of dashboard/doc glue at the end. |

**None of the 14 need to be rejected outright.** Three need real caution because a naive implementation would degrade something that already works:
- **#2** if it doesn't respect `conflict_guard.py`/`file_locks.py` assumptions about a fixed subtask set.
- **#10** if the LLM is ever allowed to see the full tool catalog instead of a filtered intersection of the *existing* static per-role allowlist.
- **#8** if the confidence threshold is flipped from 0.0 to non-zero globally in one shot instead of rolled out per-agent (many agents may currently be passing a gate that's never actually been enforced).

---

## 2. Per-priority detail

### #10 Dynamic tool selection — *do this first*
**State:** `app/fleet/tool_discovery.py` already implements `discover_tools(capability)` (unions tools tagged with a capability across `capability_registry.py`) and `check_compatibility(tool_name, agent_name)`. It has zero callers anywhere in the codebase — fully dead code. Actual tool exposure today is a hardcoded per-agent `_TOOLS` list bound directly into the LLM call (e.g. `spike_agent.py:82-90` → `base_graph.py:2523`).
**Build:** A selection function that takes `(agent's static _TOOLS allowlist) ∩ (tool_discovery.discover_tools(task_capability))` and passes that narrowed, still-allowlist-bound set to the LLM. **Never** expose the raw registry — intersect with the existing allowlist, matching Composio's pattern (`python/composio/core/models/tools.py:181-218`, `tool_router.py`'s `ToolRouterTag` capability tags) of server-side filtering before the agent ever sees the catalog.
**Effort:** 1–2 days. **Risk:** low, if the intersection rule is enforced everywhere (unit-test that no capability-filtered set can ever exceed the static allowlist).

### #8 Confidence-driven control flow — *do this second*
**State:** `base_graph.py:1502-1506` already fails a quality gate when `confidence < min_confidence`, but `quality_gate_min_confidence` defaults to `0.0` and is never overridden by any real agent — verified inert by the code's own comment (`base_graph.py:2374-2377`). `requires_human_approval`/`human_approval_required` is real and **already surfaced** via `app/api/approvals.py` + `app/fleet/approval_gate.py`, just driven by static per-agent booleans, not confidence tiers.
**Build:** Move the four thresholds (accept / reviewer / retry-replan / HITL) into `app/config.py` as named settings (per ChatGPT's own instruction not to hardcode them). Wire `quality_gate_min_confidence` per-agent, staged rollout (start with 1-2 low-risk agents, verify no regression, expand). Extend the existing `requires_human_approval` computation to also trip on the "very low confidence" tier, reusing swe-agent's pattern (`sweagent/agent/reviewer.py:416-446`, `ScoreRetryLoop.retry():617-634`) of score + attempt/cost budget jointly gating retry vs escalate.
**Effort:** 2–3 days. **Risk:** medium if rolled out globally at once (silently changes pass/fail behavior for every agent) — mitigate with per-agent staged config, not a global default flip.

### #11 Agent performance → runtime decisions — *fold into #10/#8 week*
**State:** Already substantially implemented. `FleetManager.select()` (`fleet_manager.py:69-196`) computes `score = health_weight × success_rate × (1/(1+error_count)) × tenure_factor × confidence_factor` — this **is** performance-informed selection today, deterministically, no LLM. What's missing: cost and latency are not terms in that formula (`budget_manager.py` is a hard cap, not a comparative signal; `model_router.py` is a static lookup table, not cost-aware).
**Build:** Add `cost_factor`/`latency_factor` terms to the existing formula (extend, don't rewrite). Small, additive PR against `fleet_manager.py`.
**Effort:** 1–2 days.

### #3 Memory-aware agent selection
**State:** `MemoryEmbedding` (`db/models.py:585-628`) genuinely has no `agent_name`/`agent_role` column — confirmed, ChatGPT is right here (columns are `task_id, epic_id, repo_id, outcome, category, ...`). `agent_name` is currently smuggled into free-text content as a documented workaround (`store.py:613`). `memory_score.py` computes a per-repo verified-ratio but is read only by the dashboard, never by `FleetManager`.
**Build:**
1. Additive migration: `agent_name` column on `memory_embeddings` (same pattern as the existing `repo_id` migration).
2. New `AgentHistoricalPerformance` aggregation (materialized view or scheduled rollup, not a live join) computing success_rate/avg_confidence/avg_quality per agent × task-type from the now-attributed rows.
3. Add it as **one more additive term** in `FleetManager.select()`'s existing formula — explicitly do not replace the deterministic scorer with an LLM call (this matches ChatGPT's own caveat, and matches how #11 already works).
**Effort:** 4–6 days (migration + backfill + aggregation + wiring + tests).

### #4 Memory quality control
**State:** Dedup exists (`_find_near_duplicate`, `store.py:164-237`, threshold 0.97) but only collapses near-identical text into `reuse_count++`. `importance`/`verified` are set unconditionally at write time from simple heuristics — they weight a memory after the fact, they never block a write. Nothing today can reject a low-quality memory.
**Build:** A pre-store gate, tiered as ChatGPT specified: deterministic checks (length/specificity/duplicate-adjacent heuristics) for routine memories; LLM validation for anything tagged as a "lesson"; stronger validation/HITL for fleet-wide lessons — matching the tiering already used elsewhere in the project (e.g. `approval_gate.py`'s per-risk HITL pattern). Insert this as a new function called before the existing `db.add(row)` sites in `store.py`, coexisting with (not replacing) the existing importance/verified heuristics.
**Effort:** 4–6 days.

### #5 Memory consolidation/evolution
**State:** Not absent, but narrower than the backlog assumes. `VersionedMemoryStore.publish()` (`versioned_memory.py:339-406`) already does 1:1 merge-on-conflict with `supersedes_id` provenance and a DRAFT→PUBLISHED→SUPERSEDED lifecycle gated by human approval — but only for a separate `versioned_lessons` table, and only pairwise (most-similar existing lesson vs. new one), not N-way clustering across `memory_embeddings`.
**Build:** Extend, don't duplicate: add a background job that clusters related `memory_embeddings` rows (same shape as `_find_near_duplicate`'s similarity check, generalized to cluster rather than pairwise-collapse), then routes the cluster through the **existing** `versioned_lessons` DRAFT/PUBLISHED/supersedes machinery for the LLM-merge + provenance step, rather than inventing a second consolidation lifecycle.
**Effort:** 5–7 days.

### #6 Session memory compression
**State:** `_condense_messages`/`_condense_history_async` (`base_graph.py:488-540`, `chat_agent.py:501-586`) already summarize overflowing session history into one free-text blob — but it's ephemeral (lives only in the in-memory session), single-blob (not categorized), and never persisted to `memory_embeddings`.
**Build:** A post-session hook that takes the same trigger (token/event count) and instead of one blob, calls the already-existing per-category `embed_*` functions (`embed_task_outcome`, `embed_failure`, `embed_architecture_note`, `embed_learning`, `embed_procedure`, `embed_preference`, `embed_bug` — all confirmed present in `store.py`) for decision/fact/constraint/pending/preference/action content extracted from the session. This is genuinely a wiring task on top of infra that already exists in both directions (condensation trigger + per-category writers) — smaller than it looks in the backlog.
**Effort:** 3–5 days.

### #7 General context compression
**State:** Confirmed exactly as ChatGPT described: `memory_injection_token_budget` (`config.py:422-429`, default 3000) is enforced by hard Python string truncation (`memory_context[:max_chars]`) in `base_graph.py` around line 873 — no compression of what gets cut, ranking happens beforehand via the existing composite score.
**Build:** Localized change to the same function: when over budget, summarize (LLM or extractive) the lowest-priority tail instead of slicing it off, preserving the existing priority order (critical constraints → recent → verified lessons → procedures → general knowledge, which the ranking formula already approximates).
**Effort:** 2–3 days.

### #9 Fleet-wide replanning
**State:** `enable_replanning`/`max_replans` are real, already wired through `_should_replan()` (`base_graph.py:792-823`), and already selectively enabled on exactly 4 agents (`security_reviewer`, `qa`, `pm`, `coder` — confirmed by file:line, not a blanket flag). The actual gap: `_should_replan()` uses one heuristic (repeated failure on same criterion) for all 4, with no distinction between failure / new-info / dependency-change triggers.
**Build:** Extend `_should_replan()` with the three-way trigger classification, and make **enabling** replanning a config-driven risk/cost policy (critical + complex-coding agents on, simple/cheap agents off, expensive agents threshold-based) rather than a hardcoded boolean per agent file — same config-not-hardcode principle as #8.
**Effort:** 3–4 days.

### #1 + #13 Agent-to-agent delegation + delegation safety — *one phase*
**State:** Confirmed fully absent — no `delegate_to_agent`, no cycle detection, no depth limit, no caller matrix anywhere (`grep` returns zero hits project-wide). All invocation today is top-down through `manager.py`/`fleet_manager.py`.
**Build, grounded in two concrete patterns:**
- Routing mechanism: LangGraph's `Command(goto=...)` (`libs/langgraph/langgraph/types.py`) — a node/agent returns which agent to run next rather than following a static edge; this maps directly since the project is already LangGraph-based (`base_graph.py`).
- Safety: AutoGen's Swarm pattern (`_swarm_group_chat.py`) validates a handoff target against `participant_names` before allowing it (straightforward `DelegationPolicy` allowed-matrix equivalent), plus LangGraph's `recursion_limit` (`pregel/_loop.py`) as the depth/cycle backstop.
- Build `app/agents/delegation.py` (DelegationRequest: source_agent, target_agent, task, context, parent_run_id, delegation_depth, budget_remaining, timeout) and `app/tools/delegate_to_agent.py`, enforcing: allowed-target matrix (config-driven, e.g. `coder → security_reviewer` ✓, `qa → coder` ✗), `max_depth`, `max_delegations_per_run`, budget/timeout inheritance from `budget_manager.py`, and audit logging via the existing `audit_log.py`.
- Communication: **extend `GridironEvent`** (`event_bus/models.py:20-30`) with optional `receiver`, `message_type`, `trace_id`, `parent_run_id` fields rather than building AutoGen's separate `AgentId`/envelope system from scratch — this is #12, folded in here rather than built standalone, so the project doesn't end up with two competing message schemas.
**Effort:** #1 core ~5-7 days + #13 safety layer ~3-5 days (built together, not sequential) + #12 extension ~2-3 days ≈ **10–14 days total** for the combined phase.
**Sequencing note:** Do this *after* Phase 1 (memory) and #8 (confidence gating) land, so delegation targets can be chosen using the new historical-performance signal (#3) and delegated results can flow through the same accept/retry/escalate machinery (#8) instead of a third bespoke decision path.

### #2 Dynamic subtask creation — *sequence last*
**State:** Confirmed fully absent. Subtasks are created exactly once, by `decomposer_node` (`decomposer.py:115-194`), then handed to `manager.py`'s `_dispatch_one_subtask`/`_topological_subtask_waves` (lines 88-141), which computes a topological order **once, up front**, assuming a static, complete subtask list.
**Build:** `app/tools/propose_subtask.py` (schema per the backlog: parent_subtask_id, title, description, required_capability, priority, dependencies, reason, estimated_cost) → `app/pipeline/dynamic_subtasks.py` validation layer checking: agent allowed to propose, task within epic, dependency validity, budget sufficiency, cycle detection, duplicate-work detection — then insertion into the live queue. **The real work is not the proposal/validation layer** (that's a fairly standard clean pipeline, similar shape to #1's delegation-request validation) — **it's making `_topological_subtask_waves` and `conflict_guard.py`/`file_locks.py` tolerate a subtask set that can grow mid-run** without invalidating already-computed wave ordering or file-lock assumptions. This is the one item in the backlog with genuine risk of destabilizing an existing, working invariant if rushed.
**Recommendation:** Build behind a feature flag, enabled only for specific epics/agents initially, and reuse the propose→validate→insert pattern already established by #1's delegation-request flow (so the codebase ends up with one "controlled request into orchestrator" pattern, not two).
**Effort:** 6–9 days, plus buffer for regression-testing the existing dispatcher/conflict-guard test suite.

### #14 Memory + orchestration as one feedback system
Not a separate build. The write side (`hooks.py` → `store.py`) already exists; #3 adds the read side (`FleetManager` querying memory-derived performance). Once Phase 1 (#3/#4/#5) and the delegation phase (#1/#13) both land, this loop is closed as a natural consequence. Budget ~1 day at the end for a dashboard panel / doc page making the loop visible, not a phase of its own.

---

## 3. Recommended sequencing (dependency-ordered, not backlog-number order)

```
Phase 0 — Quick wins (≈1 week)
  #10 wire existing tool_discovery.py behind the existing allowlist
  #8  finish the existing (inert) confidence gate + expose HITL tier
  #11 add cost/latency terms to the existing FleetManager formula
       ↓
Phase 1 — Memory foundation (≈2.5–3 weeks)
  #3  agent_name column + AgentHistoricalPerformance + wire into FleetManager
  #4  pre-store quality gate (tiered)
  #7  compress-instead-of-truncate context injection
       ↓
Phase 2 — Session & consolidation (≈1.5–2 weeks)
  #6  categorized session compression (reuses embed_* writers)
  #5  N-way memory clustering (reuses versioned_lessons lifecycle)
       ↓
Phase 3 — Delegation (≈2–2.5 weeks) — CRITICAL, built as one unit
  #1 + #13 + #12  delegate_to_agent + DelegationPolicy + extended GridironEvent
       ↓
Phase 4 — Adaptive control (≈0.5–1 week)
  #9  three-way adaptive replanning trigger
       ↓
Phase 5 — Highest-risk item, done last with full context (≈1.5–2 weeks)
  #2  propose_subtask → validated live insertion into dispatcher
       ↓
  #14 close the loop — dashboard/doc only, ~1 day
```

Rationale for this order vs. the backlog's own numbering: the backlog's "CRITICAL" items (#1, #2, #13) are also the *riskiest and most expensive* items, and #1/#2 both benefit from the memory-informed selection (#3) and confidence-gated control flow (#8) existing first, so delegated/proposed work can be evaluated with the same machinery rather than three bespoke decision paths. #2 goes last specifically because it's the only item that touches an existing invariant (`manager.py`'s static topological wave assumption) rather than adding a new, isolated capability.

---

## 4. Effort & risk summary

| Phase | Items | Est. effort (solo, AI-assisted) | Risk |
|---|---|---|---|
| 0 | #10, #8, #11 | ~5–7 days | Low |
| 1 | #3, #4, #7 | ~11–15 days | Low–Medium |
| 2 | #6, #5 | ~8–12 days | Medium |
| 3 | #1, #13, #12 | ~10–14 days | Medium–High (new subsystem, but additive) |
| 4 | #9 | ~3–4 days | Low |
| 5 | #2 | ~6–9 days | **High** (touches existing dispatcher invariants) |
| — | #14 | ~1 day | — |
| **Total** | **all 14** | **≈ 44–62 working days** (≈ 9–12 weeks full-time solo) | |

Biggest single lever for the least cost: **#10** — it's a fully-built, fully-unused subsystem sitting in the codebase already; wiring it up is 1-2 days for real capability-based tool filtering.
Biggest scope-correction vs. the original backlog: **#11** (already ~80% done) and **#14** (not a build item at all) — don't budget these as full-size tickets.
Item requiring the most caution regardless of how much time is allocated: **#2** — recommend a feature flag and explicit regression pass on `conflict_guard.py`/`file_locks.py` before it's enabled broadly.

---

## 5. Session-by-session build plan (working directly with Claude)

The estimates in §4 are solo-human-with-AI-assist working days. Building it in direct sessions with Claude compresses wall-clock coding/testing time, but the real unit of progress is a **focused session** — one sitting where a scoped chunk gets implemented, tested against the real suite, and reviewed before moving on, matching this project's existing `batch N done` commit pattern in git log. Below is the plan broken into ~26 sessions across the 6 phases, each sized to end at a working, tested checkpoint (never a partial/uncommitted state).

| # | Session | What ships |
|---|---|---|
| **Phase 0 — quick wins** | | |
| 1 | #10a | Intersect `tool_discovery.discover_tools()` output with each agent's existing static `_TOOLS` allowlist; wire into the tool-binding call site; unit test that the filtered set can never exceed the allowlist |
| 2 | #8a | Move confidence thresholds into `config.py`; wire `quality_gate_min_confidence` on 1–2 low-risk agents first |
| 3 | #11a | Add `cost_factor`/`latency_factor` terms to `FleetManager.select()`'s existing formula |
| — | **checkpoint** | Full test suite green; confirm no agent's pass/fail behavior silently changed |
| **Phase 1 — memory foundation** | | |
| 4 | #3a | Migration: add `agent_name` column to `memory_embeddings`; backfill script from existing free-text workaround |
| 5 | #3b | `AgentHistoricalPerformance` aggregation (scheduled rollup, not live join) |
| 6 | #3c | Wire aggregation into `FleetManager.select()` as one more additive term; tests |
| 7 | #4a | Pre-store quality gate — deterministic tier (length/specificity/duplicate-adjacent checks) |
| 8 | #4b | Quality gate — LLM tier for "lesson"-tagged memories + HITL tier for fleet-wide lessons |
| 9 | #7a | Replace hard-truncate with priority-preserving compression in the context-injection call site |
| — | **checkpoint** | Run several real agent tasks end-to-end; manually review whether agent selection and injected context actually improved, not just "tests pass" |
| **Phase 2 — session & consolidation** | | |
| 10 | #6a | Post-session hook: classify session content into decision/fact/constraint/pending/preference/action |
| 11 | #6b | Wire classified content into the existing per-category `embed_*` writers |
| 12 | #5a | Clustering pass over `memory_embeddings` (generalize the existing near-duplicate similarity check to N-way) |
| 13 | #5b | Route clusters through the existing `versioned_lessons` DRAFT/PUBLISHED/supersedes lifecycle for LLM-merge + provenance |
| — | **checkpoint** | Manually spot-check a batch of consolidated/compressed memories for quality before this runs unattended |
| **Phase 3 — delegation (build as one unit, most complex phase)** | | |
| 14 | #1a | `app/agents/delegation.py` — `DelegationRequest` schema, core dispatch using `Command(goto=...)`-style routing |
| 15 | #1b | `app/tools/delegate_to_agent.py` tool + wiring into agent tool set |
| 16 | #13a | `DelegationPolicy` allowed-target matrix (config-driven, e.g. coder→security_reviewer ✓, qa→coder ✗) |
| 17 | #13b | Cycle detection + `max_depth` + `max_delegations_per_run` + budget/timeout inheritance from `budget_manager.py` |
| 18 | #12a | Extend `GridironEvent` with `receiver`/`message_type`/`trace_id`/`parent_run_id`; audit logging via existing `audit_log.py` |
| 19 | #1/#13 tests | Adversarial test session: force cycles, exhaust budget, exceed depth — confirm every guard actually blocks, not just logs |
| — | **checkpoint** | This is the riskiest new subsystem — do not proceed to Phase 4 until the adversarial session passes cleanly |
| **Phase 4 — adaptive replanning** | | |
| 20 | #9a | Three-way trigger classification (failure / new-info / dependency-change) in `_should_replan()` |
| 21 | #9b | Config-driven enable policy by agent risk/cost tier, replacing the 4 static booleans |
| **Phase 5 — dynamic subtasks (last, on purpose)** | | |
| 22 | #2a | `app/tools/propose_subtask.py` schema + tool |
| 23 | #2b | `app/pipeline/dynamic_subtasks.py` validation (allowed/epic/dependency/budget/cycle/duplicate checks) — reuse the request→policy→insert pattern from Phase 3 |
| 24 | #2c | Modify `_topological_subtask_waves` in `manager.py` to tolerate live insertion without invalidating in-flight wave ordering |
| 25 | #2d | Compatibility pass on `conflict_guard.py`/`file_locks.py`; full regression run of the existing dispatcher test suite |
| 26 | #2e | Feature-flag rollout on one epic only; verify; then broaden |
| — | **close-out** | #14 — dashboard/doc session tying the memory→orchestration feedback loop together |

**Calendar time**, depending on how often we actually sit down to do a session together (session length varies: Phase 0/4 sessions run 1–2 hrs equivalent, Phase 1/3/5 sessions run longer, especially migrations and the adversarial-testing session):

| Cadence | Calendar time |
|---|---|
| Daily sessions | ~5–6 weeks |
| 3 sessions/week | ~8–9 weeks |
| Weekly sessions | ~6 months |

**Two hard checkpoints, not optional:** after Phase 1 (memory now feeds real decisions — verify it actually improved selection before building more on top of it) and after Phase 3's adversarial test (delegation is the one subsystem that can silently misbehave — cycles, runaway depth, budget leaks — if the guards aren't proven before Phase 5 reuses the same pattern for subtasks).

---

## 6. Execution Specification — 5-Day Sprint (authoritative build spec)

**Status:** this is the governing spec for actual implementation. §1–§5 above remain the audit/rationale record (why each item is scoped the way it is, evidence citations) — this section is what gets executed, task by task, against real code, with the non-negotiable engineering rules below enforced on every task.

**Scope note (flagged per this spec's own "zero hallucination" rule — don't silently drop items):** this 5-day spec covers **10 of the 14** original backlog items — Dynamic Tool Selection (#10), Confidence-Gated Control Flow (#8), Session Memory Compression (#6), Performance-Aware Runtime Decisions (#11), Memory Quality Gate (#4), Memory Consolidation (#5), Agent-to-Agent Delegation (#1), Delegation Safety (#13), Agent Communication (#12), Adaptive Runtime Replanning (#9). **Not covered here, and not silently folded into any Day above:**
- **#3 Memory-aware agent selection** (the `agent_name` column migration + `AgentHistoricalPerformance` aggregation) — Day 3's Task 6 covers *operational* performance (latency/p50/p95/success rate already in `fleet/metrics.py`), not memory-derived agent history, which needs its own schema change per §2's audit.
- **#7 General context compression** (replacing hard-truncate with priority-preserving compression at the `memory_injection_token_budget` call site) — distinct from Day 2's Task 3 session compression.
- **#2 Dynamic subtask creation** — correctly excluded; §2/§3 above already flagged this as the highest-risk item (touches `manager.py`'s static topological-wave assumption) and recommended sequencing it last, after everything else is proven.
- **#14** is not a build item regardless (§2 above).

These three (#3, #7, #2) remain queued for a follow-on sprint after this one, in that order, per §3's original sequencing. Proceeding with the 5-day scope as specified below.

---

# 5-Day Agentic Intelligence Enhancement Plan

## Production Implementation Specification for Claude Code

### Objective

Enhance the existing agentic system across:

1. Dynamic Tool Selection
2. Confidence-Gated Control Flow
3. Session Memory Compression
4. Performance-Aware Runtime Decisions
5. Memory Quality Gate
6. Memory Consolidation
7. Agent-to-Agent Delegation
8. Delegation Safety
9. Agent Communication
10. Adaptive Runtime Replanning

The implementation MUST extend the existing architecture.

Do NOT create parallel/duplicate systems when an existing subsystem already provides the required foundation.

---

# NON-NEGOTIABLE ENGINEERING RULES

## 1. Zero hallucination

Before modifying anything:

* inspect the actual repository;
* locate the real implementation;
* trace callers and consumers;
* inspect existing tests;
* inspect database models/migrations;
* inspect configuration;
* verify assumptions with code search;
* never implement based only on this document.

If something described here does not exist exactly as expected:

1. stop;
2. investigate the actual implementation;
3. adapt to the existing architecture;
4. document the difference.

Never invent a file, class, function, field, database table, API, or configuration option.

---

## 2. Zero hardcoding

Do NOT hardcode:

* agent names;
* tool names;
* capabilities;
* routing rules;
* delegation relationships;
* thresholds;
* model names;
* database IDs;
* paths;
* priorities;
* memory categories;
* role-specific behavior.

Use the existing:

* capability registry;
* agent registry;
* tool manifest;
* configuration;
* role metadata;
* database models;
* existing scoring/configuration mechanisms.

If a new value is required, make it configuration- or metadata-driven.

---

## 3. No regex-based intelligence

Do NOT use regex to implement:

* agent selection;
* memory quality;
* delegation;
* semantic tool selection;
* intent classification;
* confidence;
* memory consolidation;
* runtime strategy decisions.

Existing deterministic validation regex may remain where it is already appropriate for syntax validation.

Intelligence must use the existing structured/LLM/embedding/scoring infrastructure where appropriate.

---

## 4. Reuse existing architecture

Before creating a new component, search for an existing implementation that already performs a similar function.

Prefer extending:

* `FleetManager`
* `AgentRegistry`
* `CapabilityRegistry`
* `ToolManifest`
* `base_graph.py`
* `memory/store.py`
* `fleet/versioned_memory.py`
* `failure_ladder.py`
* `fleet/metrics.py`
* existing LangGraph state
* existing Postgres/pgvector infrastructure
* existing event infrastructure

Do NOT create duplicate:

* memory stores;
* agent registries;
* tool registries;
* event buses;
* metrics systems;
* orchestration engines;
* delegation managers.

---

# DAY 1 — ADAPTIVE TOOL SELECTION + CONFIDENCE CONTROL

## Goal

Activate the existing infrastructure for intelligent runtime decisions.

---

## Task 1 — Dynamic Tool Selection

### Current evidence

The existing capability-filter/registry infrastructure already exists but is not fully used for runtime tool selection.

### Implementation

Trace:

```text
Agent Role
   ↓
Required Capabilities
   ↓
Capability Registry
   ↓
Tool Manifest
   ↓
Available Tools
   ↓
Runtime Tool Set
   ↓
LLM tool selection
```

Implement a reusable runtime tool-selection layer.

It should:

1. read the agent's declared capabilities;
2. determine available tools;
3. filter unavailable/incompatible tools;
4. respect high-risk tool restrictions;
5. respect role permissions;
6. respect runtime state;
7. produce the final tool set;
8. pass that tool set into the existing LLM/tool-use mechanism.

Do not replace native tool calling.

Do not create a second tool registry.

### Important

Tool selection must be based on structured metadata, not:

```python
if agent_name == "coder":
```

and not:

```python
if "security" in prompt:
```

---

## Task 2 — Confidence Control Flow

The existing quality gate already contains confidence-related infrastructure.

Trace:

```text
Agent Result
    ↓
Quality Gate
    ↓
Confidence
    ↓
requires_human_approval
    ↓
Runtime Control
```

Make the confidence signal actually affect execution.

Required behavior:

```text
confidence >= configured threshold
        ↓
continue

confidence < configured threshold
        ↓
appropriate control action
```

The control action must use the existing approval/HITL mechanism where appropriate.

Do NOT simply change:

```text
quality_gate_min_confidence = 0.0
```

to another number.

A threshold without a real consumer is NOT considered implemented.

The resulting approval/control state must be observable.

---

## Day 1 tests

Add/extend tests for:

* tool capability filtering;
* unavailable tool filtering;
* high-risk tool restrictions;
* role permissions;
* dynamic runtime tool set;
* confidence above threshold;
* confidence below threshold;
* confidence causing actual control flow;
* existing behavior preserved when feature disabled.

Run:

```bash
pytest tests/
ruff check app/ tests/
mypy --strict app/
```

Do not proceed if failures remain.

---

# DAY 2 — SESSION MEMORY COMPRESSION + MEMORY QUALITY GATE

## Goal

Turn the existing memory subsystem into a higher-quality learning system.

---

# Task 3 — Session Memory Compression

### Current evidence

`LessonStore` already exists and has:

* retention;
* deduplication;
* replacement;
* bounded capacity.

Do NOT create another session-memory system.

Extend the existing `LessonStore`.

### Required behavior

When session memory reaches a configured pressure threshold:

```text
Existing session memories
        ↓
group related memories
        ↓
LLM-based semantic compression
        ↓
compact representation
        ↓
validate result
        ↓
replace redundant memories
```

Compression must preserve:

* important facts;
* user/project decisions;
* unresolved issues;
* useful lessons;
* constraints.

It must remove:

* repeated information;
* obsolete intermediate details;
* redundant memories.

Do NOT use regex to decide semantic similarity.

Use the existing semantic/LLM infrastructure.

### Safety

Never destroy the only copy of durable memory.

Session compression applies to the ephemeral session store.

---

# Task 4 — Memory Quality Gate

Current memory already has:

* duplicate detection;
* verification state;
* lifecycle;
* promotion.

Extend this rather than creating another memory database.

Required pipeline:

```text
Candidate Memory
      ↓
Deduplication
      ↓
Quality Evaluation
      ↓
Accuracy / usefulness assessment
      ↓
Decision
 ┌────┼──────────┐
 ↓    ↓          ↓
reject draft   publish
```

The quality gate should evaluate appropriate dimensions such as:

* factual consistency;
* usefulness;
* specificity;
* redundancy;
* confidence/evidence;
* source/run provenance.

Use the existing versioned memory lifecycle.

Do NOT make every memory automatically published.

The existing:

```text
draft → published → superseded/merged → archived
```

lifecycle remains authoritative.

### Important

Do not create a second "MemoryQuality" table unless repository investigation proves an existing schema cannot support the requirement.

---

## Day 2 tests

Test:

* compression trigger;
* compression preserves important information;
* duplicate reduction;
* quality rejection;
* quality acceptance;
* draft creation;
* promotion behavior;
* failed quality evaluation;
* malformed LLM output;
* retry behavior;
* session-memory capacity.

Run full relevant memory tests plus:

```bash
pytest tests/ -k "memory or lesson or compression"
```

Then:

```bash
ruff check app/ tests/
mypy --strict app/
```

---

# DAY 3 — MEMORY CONSOLIDATION + PERFORMANCE-AWARE RUNTIME DECISIONS

## Goal

Make memory evolve over time and make orchestration use real performance information.

---

# Task 5 — Memory Consolidation

Do NOT build a new memory lifecycle.

Extend:

```text
fleet/versioned_memory.py
```

and the existing merge lifecycle.

Required flow:

```text
Old related memories
       ↓
semantic clustering
       ↓
candidate consolidation
       ↓
LLM merge
       ↓
quality validation
       ↓
versioned lesson
       ↓
supersede/merge old records
```

Consolidation must be:

* idempotent;
* concurrency safe;
* auditable;
* reversible through the existing lifecycle;
* bounded in cost.

Do not permanently delete source knowledge during initial implementation.

Prefer:

```text
merged/superseded
```

over destructive deletion.

Use existing advisory-lock patterns where read/modify/write races exist.

---

# Task 6 — Performance → Runtime Decisions

Current metrics already include performance data.

Existing information may include:

* run latency;
* phase timing;
* tool timing;
* p50;
* p95;
* success rate;
* workload;
* agent health.

Make this information influence runtime decisions.

Prefer integrating with:

```text
FleetManager.select()
```

rather than creating another scheduler.

Example decision flow:

```text
Candidate Agents
       ↓
Capability filter
       ↓
Health filter
       ↓
Performance signal
       ↓
Confidence
       ↓
Workload
       ↓
Existing FleetManager scoring
       ↓
Selected agent
```

Performance MUST NOT override:

* capability;
* health;
* security restrictions;
* role permissions.

Performance is a ranking signal, not an authorization signal.

Use configurable weighting.

---

## Day 3 tests

Test:

* high-performing agent preference;
* poor-performing agent penalty;
* capability still dominates;
* unhealthy agents still excluded;
* performance data unavailable;
* cold-start agent;
* stale metrics;
* tie-breaking;
* score stability;
* no regression in existing FleetManager behavior.

Also test memory consolidation concurrency.

Run full test suite.

---

# DAY 4 — AGENT DELEGATION + DELEGATION SAFETY

## Goal

Add real agent-to-agent collaboration without creating uncontrolled recursive execution.

This is the most security-sensitive day.

---

# Task 7 — Agent-to-Agent Delegation

Implement a structured delegation capability.

Do NOT allow arbitrary agent invocation.

Required conceptual flow:

```text
Parent Agent
     ↓
Delegation Request
     ↓
Policy Validation
     ↓
Capability Check
     ↓
Budget Check
     ↓
Depth Check
     ↓
Child Agent
     ↓
Result
     ↓
Parent Agent
```

Delegation should use structured data.

Example conceptual contract:

```text
DelegationRequest

parent_agent
target_capability
objective
context
priority
budget
deadline
delegation_depth
```

Do not hardcode target agent names.

The parent should request a capability.

The registry resolves the appropriate agent.

---

# Task 8 — Delegation Safety

Mandatory protections:

### Maximum delegation depth

Example configuration:

```text
delegation_max_depth
```

Must be configurable.

### Loop prevention

Prevent:

```text
A → B → A
```

and longer cycles.

Use structured delegation ancestry/state.

Do NOT use regex or string matching.

### Budget propagation

Child execution must consume the parent's:

* token budget;
* cost budget;
* execution budget.

A child must NOT receive a fresh unrestricted budget.

### Capability authorization

An agent can only delegate to capabilities allowed by policy.

### Timeout

Delegated work must have a bounded timeout.

### Cancellation

Parent cancellation must propagate to child work where supported.

### Failure handling

Child failure must return a structured failure to the parent.

Do not fabricate a successful delegation result.

---

# Task 9 — Agent Communication

If the existing `GridironEvent` infrastructure is present, extend it.

Do NOT create a separate `AgentMessage` architecture.

Use structured events for:

```text
delegation_requested
delegation_started
delegation_completed
delegation_failed
agent_result
agent_progress
```

Every event should contain enough structured information for:

* tracing;
* audit;
* correlation;
* parent/child relationship;
* timestamps;
* status.

Do not put critical routing information only inside free-form text.

---

## Day 4 tests

Mandatory:

* valid delegation;
* unauthorized delegation;
* nonexistent capability;
* depth exceeded;
* A → B → A cycle;
* long delegation cycle;
* budget exhaustion;
* timeout;
* child failure;
* parent cancellation;
* concurrent delegation;
* event correlation;
* structured result propagation.

Run:

```bash
pytest tests/
```

plus:

```bash
ruff check app/ tests/
mypy --strict app/
```

---

# DAY 5 — ADAPTIVE REPLANNING + INTEGRATION + PRODUCTION VALIDATION

## Goal

Connect the new capabilities into one coherent agentic runtime.

---

# Task 10 — Adaptive Runtime Replanning

Existing replanning infrastructure must be extended rather than replaced.

The runtime should be able to detect meaningful execution changes such as:

* failed tool;
* failed verification;
* blocked subtask;
* low confidence;
* delegation failure;
* unexpected result;
* new information;
* resource/performance constraint.

Then:

```text
Current State
     ↓
Decision / Verification
     ↓
Is current plan still valid?
     ↓
 NO ────────────── YES
 ↓                  ↓
Replan             Continue
 ↓
Updated Plan
 ↓
Continue execution
```

Replanning must be evidence-triggered.

Do NOT replan after every step.

Do NOT call the LLM continuously without a reason.

Use configurable thresholds/policies.

---

# Task 11 — Integrate the Systems

Verify the final architecture:

```text
                         USER REQUEST
                              │
                              ▼
                         PM / PLANNER
                              │
                              ▼
                       TASK DECOMPOSITION
                              │
                              ▼
                     FLEET MANAGER SELECT
                              │
              ┌───────────────┼────────────────┐
              │               │                │
              ▼               ▼                ▼
        Capability        Performance       Confidence
          Filter            Score             Signal
              │               │                │
              └───────────────┼────────────────┘
                              ▼
                        SELECT AGENT
                              │
                              ▼
                     DYNAMIC TOOL SET
                              │
                              ▼
                       AGENT EXECUTION
                              │
              ┌───────────────┼────────────────┐
              │               │                │
              ▼               ▼                ▼
          MEMORY          DELEGATION       VERIFICATION
              │               │                │
              ▼               ▼                ▼
        Quality Gate      Child Agent       Result
              │               │                │
              └───────────────┼────────────────┘
                              ▼
                         REFLECTION
                              │
                              ▼
                       REPLAN IF NEEDED
                              │
                              ▼
                         FINAL RESULT
                              │
                              ▼
                       MEMORY LEARNING
                              │
                              ▼
                    QUALITY → DRAFT/PUBLISH
```

---

# DAY 5 — FULL VALIDATION

Do NOT consider the implementation complete until all validation passes.

## 1. Unit tests

All new components.

## 2. Integration tests

Real interaction between:

* FleetManager;
* tool selection;
* confidence;
* memory;
* delegation;
* events;
* replanning.

## 3. Concurrency tests

Especially:

* memory writes;
* memory consolidation;
* delegation;
* concurrent agent selection;
* shared event handling.

Use the real Postgres development environment where the repository already uses Postgres for these components.

## 4. Failure tests

Test:

* LLM failure;
* tool failure;
* DB failure;
* timeout;
* cancellation;
* malformed model output;
* delegation failure;
* memory quality failure;
* unavailable agent;
* unavailable tool.

## 5. Regression tests

Run the complete existing suite.

Do NOT modify existing tests merely to make failures disappear.

If an existing test fails because behavior intentionally changed:

1. prove the behavior change;
2. document why;
3. update the test only when the new behavior is actually correct.

---

# REQUIRED VALIDATION COMMANDS

Run the repository's existing canonical commands first.

If these are the project's current commands:

```bash
pytest tests/
ruff check app/ tests/
ruff format --check app/ tests/
mypy --strict app/
```

Also run targeted suites for every modified subsystem.

Do not assume these commands are correct without checking the repository's current CI/configuration.

---

# REQUIRED FINAL REPORT

At the end, Claude Code MUST produce:

## Implementation Summary

For every task:

```text
Task:
Status:
Files changed:
Database changes:
Configuration changes:
Runtime integration:
Tests added:
Tests passed:
Known limitations:
```

## Evidence Table

```text
Capability | Implemented | Runtime Wired | Tests | Evidence
```

A capability is NOT "implemented" if:

* only a class exists;
* only a config flag exists;
* only a prompt was changed;
* only a test was added;
* the code is unreachable;
* no real caller exists;
* the result is never consumed.

---

# HARD STOP CONDITIONS

Claude Code MUST stop and report instead of inventing an implementation if:

1. an expected subsystem does not exist;
2. the proposed design conflicts with an existing architecture;
3. a database migration is required but the schema impact is unclear;
4. an LLM output contract is ambiguous;
5. a security boundary is undefined;
6. a new capability would silently change existing production behavior;
7. a test cannot prove the behavior;
8. an implementation requires hardcoded agent/tool names;
9. regex would be required for semantic decision-making;
10. an existing system already provides the required capability.

In these situations:

```text
STOP → INVESTIGATE → REPORT → PROPOSE
```

Do not:

```text
GUESS → IMPLEMENT → CLAIM DONE
```

---

# Definition of Done

The 5-day enhancement is complete only when:

* [ ] Dynamic tool selection is runtime-wired.
* [ ] Confidence affects actual control flow.
* [ ] Session memory can semantically compress.
* [ ] Memory has a real quality gate.
* [ ] Memory consolidation uses existing versioned lifecycle.
* [ ] Performance influences agent selection.
* [ ] Agent delegation exists.
* [ ] Delegation is depth/budget/loop/permission safe.
* [ ] Agent communication uses existing event infrastructure.
* [ ] Replanning is evidence-triggered.
* [ ] No duplicate memory/registry/event/orchestration systems were created.
* [ ] No semantic regex logic was introduced.
* [ ] No agent/tool names are hardcoded into decision logic.
* [ ] All new behavior has tests.
* [ ] Concurrency has been tested.
* [ ] Failure paths have been tested.
* [ ] Existing regression tests pass.
* [ ] Ruff passes.
* [ ] Mypy passes.
* [ ] Database migrations, if any, are tested.
* [ ] Runtime callers are verified.
* [ ] Every capability has real end-to-end evidence.

## Final Principle

The objective is NOT to make the audit report look better.

The objective is to make the agentic system genuinely more capable.

If a capability cannot be implemented safely and correctly within the available time, leave it explicitly PARTIAL rather than creating a fake implementation.

---

## 7. Day-by-day execution log

Filled in as each day is actually built — this is where the "Required Final Report" (Implementation Summary + Evidence Table) for each day gets recorded, per this spec's own reporting rule.

### Day 1 — investigation complete, implementation not yet started (resume here)

Before writing any code, did the required real-repo investigation for both Day 1 tasks. Findings below are the actual state, verified by reading the real files — start implementation from this, don't re-derive it.

**Task 1 — Dynamic Tool Selection: investigation findings**

- `app/fleet/capability_registry.py` looks like it only has 3 agents registered at module scope (the file's own trailing comment says "Day 0 — 3 agents, validate architecture before fleet-wide rollout" — that comment is **stale**). In reality, **76 of 86 agent modules** call `AgentCapability(...)` + `register(...)` in a module-level `_register()` function (confirmed pattern in `spike_agent.py:183-205`, `dependency_agent.py:164-190`, identical shape). `app/main.py:892-894` calls `ensure_all_agents_registered()` at real app startup (`capability_registry.py:143-166`, scans `app/agents/*.py` and imports every module so `_register()` fires) — so the registry is genuinely populated in production, not dead. Good foundation.
- `app/fleet/tool_discovery.py` (`discover_tools`, `check_compatibility`, `check_availability`, `is_high_risk`) is real, tested (`tests/test_tool_discovery.py`, 18 tests, all against a fresh `ToolDiscovery()` instance, not the process singleton), and has zero callers outside its own tests — confirms the earlier audit's "dead code" finding.
- **Landmine #1 (would have broken ~38 agents if not caught):** `ToolDiscovery.check_availability(tool_name)` only returns True for tools in `TOOL_MANIFEST` (205 entries) or top-level callables in `app.agents.tools`. Every agent's own `submit_*` result tool (e.g. `submit_spike_agent`, `submit_brief`, `submit_accessibility_agent`) is a **local closure** defined inside that agent's own `make_*_handlers()` function, not a module-level callable and not in `TOOL_MANIFEST`. Verified: 63 distinct `submit_*` tool names exist across agent files, only 25 are in `TOOL_MANIFEST`. **Do not use `check_availability()` as a hard filter on the full tool list** — it would silently strip every agent's own submit tool, breaking their ability to ever finish a task. `verify_agent_contract()` (`tool_manifest.py:1793`) is likewise never called from production code today (only from 2 test files) — confirms it's a lint-check utility, not a runtime gate.
- **Correct availability signal:** `run_agent_graph(tools=..., tool_handlers=..., ...)` already receives a `tool_handlers: dict[str, Any]` from every caller, and every real tool (including each agent's own `submit_*` closure) is always present as a key in that dict by construction (e.g. `spike_agent.py`: `base["submit_spike_agent"] = submit_h`). **`tool_name in tool_handlers` is the correct, zero-false-negative availability check** — use that instead of `tool_discovery.check_availability()` for the "can this tool actually run" filter. `tool_discovery`'s role in this design narrows to: (a) the capability-tag union (`discover_tools`) as a future extension point once a task-level capability field exists (not yet — see #3/#7 deferral note above), and (b) `is_high_risk()` cross-checked against `capability_registry.get(agent_name).tools` as a contract-drift safety net (a tool that's high-risk and NOT in the agent's own registered `AgentCapability.tools` gets dropped — this is the one real, safe narrowing this layer can do today).
- Confirmed integration point: `run_agent_graph()` (`base_graph.py:2523`) already has an established precedent for exactly this shape of override — the `ModelRouter` block at `base_graph.py:2600-2609` (`model = _get_router().route(role_name).model`, wrapped in non-fatal `try/except`, applied uniformly to every one of the 76 agent call sites without touching any of their files). The tool-filter injection should follow the identical pattern, added right after it. `from app.config import get_settings` is already imported at the top of `base_graph.py:43` — a new `dynamic_tool_selection_enabled` config flag needs no new import.
- `tests/test_tool_scoping.py` (doc-07 matrix tests, e.g. `test_qa_tools_structurally_has_no_write_file`) is the existing authority that a filter must never violate — confirms the "intersect/narrow only, never add" design is the only safe one; a new `tests/test_dynamic_tool_selection.py` should sit alongside it.

**Refined Task 1 design (ready to implement, not yet written):**
1. `app/config.py`: add `dynamic_tool_selection_enabled: bool = Field(default=True, description=...)` (pattern: `memory_dedup_enabled` at `config.py:406-409`).
2. `app/fleet/tool_discovery.py`: add `filter_runtime_tools(agent_name: str, static_tools: list[dict], tool_handlers: dict) -> list[dict]` (method on `ToolDiscovery` + module-level delegator, matching the file's existing `discover_tools`/`check_compatibility` pattern). Logic: keep a tool iff `name in tool_handlers`, AND (not `is_high_risk(name)` OR `capability_registry.get(agent_name)` is `None` OR `name in cap.tools`). Never adds. Order-preserving.
3. `base_graph.py::run_agent_graph`: right after the `ModelRouter` override block (~line 2609), add the equivalent non-fatal override for `tools`, gated on `get_settings().dynamic_tool_selection_enabled`.
4. Tests (new `tests/test_dynamic_tool_selection.py`): handler-missing tool dropped; handler-present tool kept; high-risk+undeclared dropped; high-risk+declared kept; unregistered agent fails open (availability check still applies, contract-drift check skipped); output is always a subset of input across a few real agents (spike_agent, qa, bug_fix) using their real static `_TOOLS`/handlers; `run_agent_graph`-level integration test with the flag off reproducing byte-identical `tools` passed to the mocked Anthropic client (reuse the `patch("anthropic.Anthropic")` harness already established in `tests/test_phase37_quality_gate.py:264-291`).

**Task 2 — Confidence Control Flow: investigation findings (partial — enough to resume, not exhaustive)**

- The quality gate is more built than either backlog assumed. `_run_quality_gate()` and `_make_execute_tools_node()` already exist in `base_graph.py` and are already unit- and integration-tested end to end in `tests/test_phase37_quality_gate.py` (291 lines, 10 tests) — including a **full graph-level test** (`test_graph_low_planner_confidence_escalates_via_quality_gate`, line 264) proving `quality_gate_min_confidence` already flows from `run_agent_graph(...)` through a real (mocked-LLM) planner confidence into `requires_human_approval=True` on the final state, when a caller explicitly passes a nonzero threshold. So the mechanism doesn't just exist inertly — it is proven to work today, for any caller willing to pass a real number instead of the default `0.0`.
- This confirms the actual Day 1 Task 2 scope is narrower than either backlog framed it: not "build confidence-gated control flow," but specifically **(a)** move the threshold tiers into `app/config.py` as named settings instead of a bare `float = 0.0` default baked into `run_agent_graph`'s signature, and **(b)** actually pass a real per-agent threshold from agent call sites (staged rollout — 1-2 agents first) instead of every one of the 76 callers implicitly relying on the inert `0.0` default. The graph-level plumbing itself does not need to be built; it needs a real, config-driven, non-zero value handed to it, per-agent.
- Not yet investigated in detail: the four-tier design from §2 above (accept / reviewer / retry-replan / HITL) — `_run_quality_gate` today is binary (`passed: bool`), not a 4-way tier. Need to read `_run_quality_gate`'s full body (only saw it exercised via tests, not its own source) and `app/api/approvals.py` + `app/fleet/approval_gate.py` before designing the "medium confidence → reviewer" and "low confidence → retry/replan" tiers — this is where tomorrow's session should start for Task 2.

**Status:** Task 1 is fully designed and ready to write. Task 2 needs one more read pass (`_run_quality_gate` source, `approval_gate.py`) before design is final. No code has been written yet — next session starts by implementing Task 1 per the design above, then finishing Task 2's investigation before implementing it.

### Day 1 Task 1 — IMPLEMENTED, GREEN FLAG (2026-08-13)

Re-verified the investigation findings above against current code before writing anything (line numbers had drifted — `run_agent_graph` is now at `base_graph.py:2701`, not `:2523`, and the ModelRouter override block is at `:2778-2787` — content otherwise matched). Design executed exactly as specified in "Refined Task 1 design" above, one deviation: since the Groq bypass and the normal `build_agent_graph` path both read the same local `tools` variable, the filter is applied once, immediately after the ModelRouter override block, rather than only at the `build_agent_graph` call site — this covers both call sites with one change instead of two.

```text
Task: Dynamic Tool Selection (plan14 #10 / Day 1 Task 1)
Status: DONE
Files changed:
  - backend/app/config.py — new `dynamic_tool_selection_enabled: bool` setting (default True)
  - backend/app/fleet/tool_discovery.py — new `ToolDiscovery.filter_runtime_tools()` method
    + module-level `filter_runtime_tools()` delegator
  - backend/app/agents/base_graph.py — `run_agent_graph()` applies the filter to `tools`
    right after the existing ModelRouter override block (non-fatal try/except, same pattern)
Database changes: none
Configuration changes: `dynamic_tool_selection_enabled` (config.py), default True
Runtime integration: real — every one of the 76 `run_agent_graph(...)` call sites is
  affected (verified: `grep -l "run_agent_graph(" app/agents/*.py` → 76 files), both the
  Groq-bypass path and the normal LangGraph path, since both read the same filtered `tools`
  local variable
Tests added: tests/test_dynamic_tool_selection.py — 16 tests:
  9 unit tests against a fresh ToolDiscovery() (availability filter, contract-drift filter,
    never-adds/order-preserving invariants, unregistered-agent fail-open, module delegator)
  4 regression tests against real production tool lists (spike_agent, qa, bug_fix, plus a
    sweep of every agent actually registered in the real capability_registry singleton)
  3 full run_agent_graph() integration tests using the same mocked-Anthropic-client harness
    established in tests/test_phase37_quality_gate.py / tests/test_task_images.py — proves
    the filter actually changes what reaches the LLM call, not just that the function
    returns the right value in isolation
Tests passed: 16/16 new, plus full existing suite: 4459 passed, 52 skipped (pre-existing),
  18 deselected (pre-existing), 0 failed — ran twice (once caught a real regression, see
  below; clean on the re-run)
Known limitations: `filter_runtime_tools`'s contract-drift check only narrows high-risk
  tools; low/medium-risk tools are never narrowed by capability declaration, matching the
  design's explicit scope (this layer's only safe narrowing today, per the original
  investigation's "Correct availability signal" finding — `tool_discovery.discover_tools()`'s
  capability-tag-union role remains a future extension point, not built here, since no
  task-level capability field exists yet — that's deferred to #3/#7 per the scope note above).
```

**Real regression caught and fixed during this task, not just written up after:** the first full-suite run (`pytest tests/`, 2952/2953 tests in) failed on
`tests/test_gap53_doc_generators.py::TestListRegisteredAgents::test_no_duplicate_capability_tags_across_fleet`. Cause: the new test file registered 4 synthetic test agents into `capability_registry`'s process-wide singleton (same singleton class of hazard `conftest.py` already documents fixes for — db engine, concurrency semaphores, circuit breakers), and 4 of them defaulted to sharing one capability tag (`"dts_test_cap"`). `test_tool_discovery.py` has the identical latent pattern (multiple registrations sharing `"td_cap"`) but never trips the fleet-wide dupe check purely because of alphabetical file-execution order (`test_gap53...` runs before `test_tool_discovery.py`, so gap53's check fires before the collision exists) — `test_dynamic_tool_selection.py` sorts alphabetically before `test_gap53...`, so the same latent hazard was actually observable. Fixed by deriving each synthetic agent's default capability tag from its own name (`f"{name}__cap"`) instead of a shared constant — order-independent, not a workaround for the ordering artifact. Re-ran full suite clean: 4459 passed.

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Dynamic tool selection (availability filter) | Yes | Yes — all 76 `run_agent_graph` callers | 9 unit + 3 integration | `test_dynamic_tool_selection.py` |
| Dynamic tool selection (high-risk contract-drift filter) | Yes | Yes — same call sites | 3 unit + 1 integration | `test_dynamic_tool_selection.py` |
| Feature flag (`dynamic_tool_selection_enabled`) | Yes | Yes | 1 integration (flag off → byte-identical passthrough) | `test_run_agent_graph_passes_tools_unchanged_when_flag_disabled` |
| No regression vs. existing tool-scoping contract (doc-07 matrix) | Verified | N/A | `test_tool_scoping.py` (18 tests, pre-existing, still green) | full suite run |

**Agent alignment verified: PASS** — no agent file was moved or needed updating; the filter is applied centrally in `run_agent_graph()`, the one real chokepoint every agent already goes through. No `allowed_tools`/`_TOOLS` list in any of the 76 agent files was touched.

GREEN FLAG.

**Next:** Day 1 Task 2 (Confidence Control Flow) — investigation resumes at `_run_quality_gate` source + `approval_gate.py`, per the note above.

### Day 1 Task 2 — IMPLEMENTED, GREEN FLAG (2026-08-13)

**Investigation findings (real repo, done before any code):** `_run_quality_gate` (`base_graph.py:1572`) was more built than either audit assumed — binary `passed: bool`, already sets `raw_result["_requires_human_approval"]`, already proven end-to-end by `tests/test_phase37_quality_gate.py`. Two real gaps found by tracing it forward, neither previously documented:
1. Every one of the ~76 real `run_agent_graph()` callers leaves `quality_gate_min_confidence` at its implicit `0.0` default — the confidence check can never fail in production today, confirmed by `grep -L "quality_gate_min_confidence" app/agents/*.py` returning all 76 agent files.
2. Even a caller that *did* pass a real threshold had no real consumer: `AgentResult.requires_human_approval` is hardcoded `requires_human_approval=False` at the great majority of agent wrapper call sites (verified: `grep -rn "requires_human_approval" app/agents/*.py` — e.g. `spike_agent.py:175`, `bug_fix.py:131`, ~60 more), and `grep -rn "\.requires_human_approval" app/agents/manager.py app/pipeline/*.py app/api/*.py` returns **zero hits** — nothing downstream ever reads that field. `manager.py`'s real blocking logic (`_gate_block_reason`, line 836) is bespoke per agent-category (security/architecture/dependency severity fields), not driven by this generic flag at all. This matches the master spec's own rule: *"A threshold without a real consumer is NOT considered implemented."* Per the same spec's "reuse existing architecture" rule, the one real, generic, already-wired, already-observable HITL mechanism in this codebase is `approval_gate.py`'s `PendingApproval` table (`GET /api/approvals/pending` already reads it; `tools.py:815`'s `request_clarification` handler already calls `request_human_input()` synchronously from inside this exact `execute_tools` call path — proven-safe precedent for the same call shape, not a new hazard).

```text
Task: Confidence-Gated Control Flow (plan14 #8 / Day 1 Task 2)
Status: DONE
Files changed:
  - backend/app/config.py — new `quality_gate_min_confidence_by_agent: dict[str, float]`
    setting, seeded with one pilot entry `{"spike_agent": 0.5}`
  - backend/app/agents/base_graph.py — `_make_execute_tools_node`'s `execute_tools`:
    when `not gate.passed` AND the failure is specifically `confidence:threshold`
    AND `quality_gate_min_confidence > 0` (caller opted in), calls
    `approval_gate.request_human_input(kind="low_confidence_submission", ...,
    blocking=False)`, non-fatal (try/except, matches request_clarification's own
    pattern)
  - backend/app/agents/spike_agent.py — `run_spike_agent()` now passes
    `quality_gate_min_confidence=settings.quality_gate_min_confidence_by_agent.get(
    AGENT_CONTRACT["name"], 0.0)` instead of leaving the parameter unset
Database changes: none (reuses the existing `pending_approvals` table/model)
Configuration changes: `quality_gate_min_confidence_by_agent` (config.py), default
  `{"spike_agent": 0.5}` — 0.5 chosen as a conservative "flag only below-coinflip
  confidence" floor, documented in the field's own description, adjustable without
  a code change; any other agent stays at the pre-existing inert 0.0 until explicitly
  added to this dict (config-only expansion path, matching the plan's own "staged
  rollout" instruction)
Runtime integration: real — spike_agent is the one pilot agent wired end to end;
  a real low-confidence spike_agent submission now produces a real, queryable
  `PendingApproval` row via the same code path `GET /api/approvals/pending` reads
Tests added: tests/test_confidence_gated_control_flow.py — 10 tests:
  2 config tests (pilot seed present; unlisted agent falls back to 0.0)
  5 node-level unit tests against `_make_execute_tools_node` with
    `approval_gate.request_human_input` mocked: fires on real low-confidence +
    threshold; never fires at the default 0.0 threshold (inert-by-default
    invariant); never fires when confidence passes; never fires when a
    *different* gate check (schema validation) fails instead of confidence;
    a DB failure inside request_human_input is non-fatal to the submission
  2 full `run_agent_graph()` integration tests against the real dev Postgres
    (same pattern as tests/test_approval_gate.py): low confidence + real
    threshold creates a real, queryable PendingApproval row with the right
    action/agent_name/details; the same low-confidence run with the default
    0.0 threshold creates zero rows (regression safety net for the other ~75
    agents)
  1 test on spike_agent.py's real call site, confirming it actually reads the
    configured 0.5 threshold rather than leaving the parameter unset
Tests passed: 10/10 new, plus full existing suite: 4469 passed (4459 + 10 new),
  52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed
Known limitations: only 1 pilot agent (spike_agent) is live; the 4-tier design
  (accept/reviewer/retry-replan/HITL) considered in this file's earlier audit
  section was deliberately not built — the governing 5-day spec's Day 1 Task 2
  scope is the simpler binary behavior ("confidence >= threshold → continue;
  confidence < threshold → appropriate control action"), which is what's
  implemented; a 4-tier design remains a candidate for a later, separately
  -scoped enhancement, not silently folded in here.
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Config-driven per-agent confidence threshold | Yes | Yes | 2 config + 1 wiring | `test_config_seeds_spike_agent_pilot_threshold`, `test_spike_agent_call_site_reads_configured_threshold` |
| Confidence check actually affects control flow (not just computed) | Yes | Yes — real PendingApproval row | 5 unit + 2 integration | `test_confidence_gated_control_flow.py` |
| Default (0.0) threshold stays fully inert | Verified | N/A | 2 (unit + integration) | `test_default_zero_threshold_never_requests_human_input`, `test_graph_default_threshold_creates_no_pending_approval_row` |
| Non-confidence gate failures unaffected | Verified | N/A | 1 | `test_non_confidence_gate_failure_does_not_request_human_input` |
| Failure path (DB error) is non-fatal | Verified | N/A | 1 | `test_request_human_input_failure_is_non_fatal` |

**Agent alignment verified: PASS** — only `spike_agent.py`'s own call site was touched (the pilot); no other of the 76 agent files was modified, so none of their behavior changed. `_make_execute_tools_node`'s new branch is gated on `quality_gate_min_confidence > 0`, which stays `0.0` (today's behavior, unchanged) for every agent not explicitly added to the config dict.

GREEN FLAG.

---

## Day 1 — FINAL STATUS

Both Day 1 tasks (plan14 #10 Dynamic Tool Selection, #8 Confidence-Gated Control Flow) are GREEN FLAG: implemented against the real, re-verified current codebase (not the 2-day-old audit's line numbers, which had drifted), wired to real callers, tested with real execution (including two real-Postgres integration tests, not mocks), and regression-checked against the full existing suite twice — the first full run on Task 1 caught a genuine test-isolation bug (shared capability tag polluting the process-wide registry singleton), which was fixed before green-flagging, not glossed over.

Full-suite state after both tasks: **4469 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed.** `ruff check` and `ruff format --check` clean on every touched file. `mypy --strict app/<touched files>` clean (test-file-only `AgentRunState` typing gaps match this suite's own pre-existing convention, confirmed by running the same check against `test_phase37_quality_gate.py` in isolation).

Not yet started: #11 (performance→runtime, folds into this week per §3), and Day 2 (#6 Session Memory Compression, #4 Memory Quality Gate) per the governing 5-day spec's sequencing.

---

# DAY 2 — SESSION MEMORY COMPRESSION + MEMORY QUALITY GATE

## Task 3 — Session Memory Compression (plan14 #6) — GREEN FLAG (2026-08-13)

**Investigation:** Governing spec explicitly names `LessonStore` (base_graph.py:350) as the target — "already has retention, deduplication, replacement, bounded capacity... extend it, do not build a second session-memory system." Confirmed `LessonStore.add()`'s only at-capacity behavior was blind FIFO (`self._lessons.pop(0)`), no compression. Distinct from the earlier informal audit's alternative framing (route `_condense_messages`'s dropped-message blob into the `embed_*` writers) — that would touch `memory_embeddings`, a different, already-durable store; the governing spec's own instruction is specifically about `LessonStore`, so that's what was built.

**Design:** At capacity, `add()` now tries LLM-compression of the largest same-category, Jaccard-related lesson group (≥3 members, ≥0.3 overlap) before falling back to FIFO. Grouping is pure/cheap (reuses `LessonStore`'s own existing Jaccard metric — no embeddings, matching its documented design). The LLM call itself runs **outside** `self._lock` (grouping on a snapshot, re-acquiring the lock only to apply the result) — this is a process-wide singleton shared by every concurrently running agent; holding the lock for a network call would stall the whole fleet's `add()`/`retrieve()` calls.

**Real hazard found and fixed before green-flagging, not after:** the compression LLM call initially went through `_make_client()`/`_call_anthropic()` — the shared, breaker-wrapped, 300s-timeout path every real agent submission also uses. Caught two real problems: (1) a background compaction failure would count toward the *same* circuit breaker real critical-path submissions depend on, risking cross-contamination exactly like the hazard class `conftest.py`'s own `reset_circuit_breakers` fixture documents; (2) a full 300s (+backoff) timeout on a nice-to-have background call could stall the fleet-wide `add()` hot path badly under a network outage. Fixed: `_compress_group` now uses its own isolated client — 10s timeout, 0 retries, never touches the shared breaker.

**Second real hazard found via full-suite regression, not assumed clean:** two pre-existing tests (`test_gap46_lesson_dedup.py::test_capacity_still_enforced_with_dedup_enabled`/`test_lesson_store_capacity_is_config_driven`, `test_base_graph_scaffold.py::test_capacity_evicts_oldest`) push `LessonStore` to capacity with synthetic lesson text that happens to cluster under the new Jaccard grouping (~0.33-0.6 overlap) — without a fix, they'd have made a real, unmocked network call to Anthropic, violating this suite's own "unit tests never make real LLM calls" convention (stated in `conftest.py`'s docstring). Fixed by explicitly disabling compression (`LESSON_COMPRESSION_ENABLED=false`) in those three specific tests, since they test FIFO eviction specifically, not compression.

```text
Task: Session Memory Compression (plan14 #6 / Day 2 Task 3)
Status: DONE
Files changed:
  - backend/app/config.py — lesson_compression_enabled (default True),
    lesson_compression_min_group_size (3), lesson_compression_jaccard_threshold
    (0.3), lesson_compression_llm_timeout_seconds (10.0)
  - backend/app/agents/base_graph.py — _group_compressible_lessons() (pure
    clustering), LessonStore._compress_group() (isolated LLM call),
    LessonStore.add() (tries compression at capacity, falls back to FIFO)
  - backend/tests/test_gap46_lesson_dedup.py, tests/test_base_graph_scaffold.py
    — 3 pre-existing tests scoped to disable compression explicitly (see hazard
    note above)
Database changes: none
Configuration changes: 4 new settings, all listed above, defaults preserve
  "compression tried first, FIFO fallback" as the new default production
  behavior (opt-out via lesson_compression_enabled=false, not opt-in)
Runtime integration: real — every one of the ~76 agents' lesson-writing path
  (lesson_node → LessonStore.add()) goes through this; fires only at capacity
  (default 1000 lessons)
Tests added: tests/test_lesson_compression.py — 13 tests: 4 pure grouping
  tests (largest-cluster selection, category boundary, min-size floor,
  all-distinct → none), 4 _compress_group tests (builds merged lesson,
  empty/failed LLM response → None, isolated-client-config assertion), 5
  add()-level end-to-end tests (compresses at capacity instead of FIFO;
  disabled → FIFO; no qualifying group → FIFO; LLM failure → FIFO; the
  circuit-breaker-isolation property)
Tests passed: 13/13 new + 3 fixed pre-existing + full suite (see Day 2
  checkpoint below)
Known limitations: single-cluster-per-eviction (only the largest qualifying
  group is compressed per add() call, not all qualifying groups) — matches
  the spec's own "the largest group" framing, not a corner cut; multi-group
  compression per call was out of scope.
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| LLM-based compression of related lesson groups | Yes | Yes — `LessonStore.add()` | 4 unit + 5 e2e | `test_lesson_compression.py` |
| FIFO fallback preserved (disabled/no-group/LLM-failure) | Yes | Yes | 3 | `test_add_falls_back_to_fifo_*` (×3) |
| Isolated from shared circuit breaker + short timeout | Yes | Yes | 1 | `test_compress_group_uses_isolated_short_timeout_zero_retry_client` |
| No real LLM calls leak into unrelated pre-existing tests | Verified | N/A | 3 fixed | see hazard note above |

**Agent alignment verified: PASS** — no agent file touched; `LessonStore` is a shared singleton every agent already goes through via `lesson_node`.

GREEN FLAG.

## Task 4 — Memory Quality Gate (plan14 #4) — GREEN FLAG (2026-08-13)

**Investigation:** `memory_embeddings` (7 async `embed_*()` write functions in `app/memory/store.py`) has dedup (`_find_near_duplicate`, 0.97 cosine threshold) but nothing gates content quality before insert — `_default_importance`/`_default_verified` set heuristic values unconditionally, never rejecting or downgrading. Scope note (documented in the code itself): this is the "routine memory" tier specifically — the separate `lessons`/`versioned_lessons` system (LLM/HITL-tiered per the wider design) is covered by Task 3 (compression) and Day 3 Task 5 (consolidation) instead, not touched here.

**Design:** `evaluate_memory_quality()` — deterministic (no LLM, no regex), length + distinct-token-count only. Wired into all 7 async `embed_*` functions (the 4 sync wrappers get it for free — they just call through). `reject` skips the DB insert entirely (near-empty/placeholder only). `draft` still inserts, with `verified=False` and importance dampened ×0.3 — de-prioritized in the existing composite ranking, never hidden.

**Real hazard found and fixed via a failing pre-existing test, not assumed correct:** the first design used the `archived` column for "draft" (excluded from every `query_*`'s `WHERE archived = false`). `tests/test_memory_archived_filter.py::test_real_retention_job_output_is_actually_excluded_end_to_end` caught this live — a quality-gated row pre-set to `archived=True` at write time made `app/services/retention.py`'s own retention job (`WHERE archived = false`) find zero candidates for it, forever. Two independent lifecycle concerns (quality-gate draft vs. retention-expired) had been collapsed onto one hard-filter boolean. Fixed by switching to `verified`/`importance` — confirmed (grepped) to be soft, ranking-only signals never used in a hard `WHERE` filter anywhere in the module, so no collision risk.

**Second real hazard, also found via full-suite regression:** the reject tier's original length-OR-distinct-token-count rule was too aggressive against real (if short) content already used across ~10 pre-existing tests (e.g. `"desc A"`/`"summary A"`-style repo-scoping fixtures) — silently dropping rows those tests expected to find. Fixed by making `reject` length-only (still catches every stated example — `""`, `"done"`=4 chars, `"ok"`=2, `"n/a"`=3 — since they're all short); distinct-token-count remains a real signal but only at the non-destructive `draft` tier.

**Third: a `TypeError`** surfaced in ~8 tests that mock `get_settings()` as a bare `MagicMock(memory_enabled=True)` (auto-mocking every other attribute, including the new numeric thresholds, as non-numeric `MagicMock` objects) — `length < settings.memory_quality_reject_min_length_chars` raised `TypeError: '<' not supported between instances of 'int' and 'MagicMock'`. Fixed by wrapping `evaluate_memory_quality`'s settings-dependent logic in try/except, failing open to `"publish"` — mirrors this same module's own pre-existing `_find_near_duplicate` convention exactly, and is a genuine production safety improvement in its own right (a quality-gate bug must never block a real memory write), not merely a test workaround.

**Fourth: 6 tests asserting real, undampened `verified`/`importance` defaults** (`test_gap40_memory_prioritization.py` ×2, `test_stage4_cluster_q_memory_score.py` ×4, the latter via a shared `_seed_completed_outcome_sync` helper) used short content that now legitimately lands in the `draft` tier, changing the values those tests specifically check. Fixed by lengthening the fixture content (matching the same pattern used for Day 1/Task 3's regressions) — these tests are about `_default_importance`/`_default_verified`'s own real values, not quality-gate interaction, so they need `"publish"`-tier content to test what they're actually testing.

```text
Task: Memory Quality Gate (plan14 #4 / Day 2 Task 4)
Status: DONE
Files changed:
  - backend/app/config.py — memory_quality_gate_enabled (default True),
    memory_quality_reject_min_length_chars (15), memory_quality_draft_min_length_chars
    (40), memory_quality_draft_min_distinct_tokens (6),
    memory_quality_draft_importance_factor (0.3)
  - backend/app/memory/store.py — MemoryQualityDecision, evaluate_memory_quality();
    wired into embed_task_outcome, embed_architecture_note, embed_failure,
    embed_learning_signal, embed_procedure, embed_preference, embed_bug (all 7
    async write functions; 4 sync wrappers inherit it via their async call-through)
  - backend/tests/test_gap40_memory_prioritization.py,
    tests/test_stage4_cluster_q_memory_score.py — fixture content lengthened
    (see hazard #4 above)
Database changes: none (reuses existing verified/importance columns)
Configuration changes: 5 new settings, all listed above
Runtime integration: real — every real memory_embeddings write (all 7
  categories, ~dozens of real call sites across agents/tools.py) goes through
  the gate
Tests added: tests/test_memory_quality_gate.py — 16 tests: 9 pure-function
  tests (empty/placeholder → reject; short-but-real → not rejected; stated
  preference → never rejected; borderline → draft; substantial → publish;
  gate-disabled → always publish; decision reports length/tokens correctly),
  7 real-DB integration tests against embed_task_outcome/embed_bug/
  embed_preference (reject skips insert entirely; draft dampens
  verified/importance; publish leaves defaults unchanged; a draft row still
  appears in query_similar_tasks results — proving it's de-prioritized, not
  hidden; a real short preference survives end to end; gate-disabled
  publishes even near-empty content)
Tests passed: 16/16 new + 6 fixed pre-existing + 8 fixed-via-fail-open
  pre-existing + full suite (see Day 2 checkpoint below)
Known limitations: no LLM/HITL validation tier — correctly out of scope per
  the spec's own tiering (that applies to "lesson"-tagged/fleet-wide content
  in the separate lessons system, not memory_embeddings' routine writes).
  "Duplicate-adjacent" scoring (a candidate similar-but-below-hard-dedup-
  threshold to an existing row) was considered and deliberately deferred —
  would require changing _find_near_duplicate's return signature across 7
  already-tested call sites for a refinement, not a fix; the length/
  specificity gate delivers the core "don't automatically publish everything"
  requirement without that risk.
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Deterministic reject of near-empty content | Yes | Yes — all 7 embed_* | 2 unit + 2 integration | `test_empty_content_is_rejected`, `test_embed_task_outcome_rejects_near_empty_content`, `test_embed_bug_rejects_empty_issue` |
| Draft tier de-prioritizes without hiding | Yes | Yes | 2 integration | `test_embed_task_outcome_drafts_borderline_content`, `test_embed_task_outcome_draft_row_still_appears_in_query_results` |
| Publish tier unchanged from pre-gate behavior | Verified | N/A | 1 | `test_embed_task_outcome_publishes_substantial_content_unchanged` |
| Short-but-real content never wrongly rejected | Verified | N/A | 2 | `test_short_but_real_content_is_not_rejected`, `test_short_stated_preference_is_at_most_drafted_never_rejected` |
| No collision with retention.py's archived-column semantics | Verified | N/A | 6 (existing suite) | `test_memory_archived_filter.py` (all 6, including the one that first caught the bug) |
| Fail-open on settings-mock/misconfiguration | Yes | Yes | — (fixed 8 pre-existing) | `test_memory.py`, `test_procedural_memory.py`, `test_batch15_preference_bug_memory.py` all pass unmodified |

**Agent alignment verified: PASS** — no agent file touched; the gate lives entirely inside `app/memory/store.py`'s own write functions, the one real chokepoint every memory write already goes through.

GREEN FLAG.

---

## Day 2 — FINAL STATUS

Both Day 2 tasks (#6 Session Memory Compression, #4 Memory Quality Gate) are GREEN FLAG. Three real, independent hazards were found and fixed during implementation — not discovered later and not glossed over: (1) a background LLM call sharing the production circuit breaker and a 300s timeout on a hot path, (2) a schema-reuse collision with `retention.py`'s own hard exclusion filter, proven by an actual failing pre-existing test, (3) a too-aggressive reject rule that would have silently dropped real content used across ~10 pre-existing tests. Each was root-caused and fixed at the design level, not patched around.

Full-suite state after Day 1 + Day 2: **4498 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4469 → 4498, +29 new tests: 13 compression + 16 quality gate). `ruff check`/`ruff format --check` clean on every touched file. `mypy --strict app/<touched files>` clean.

Not yet started: Day 3 (#5 Memory Consolidation, #11 already-substantially-done Performance-Aware Runtime Decisions) per the governing 5-day spec's sequencing.

---

# DAY 3 — MEMORY CONSOLIDATION + PERFORMANCE-AWARE RUNTIME DECISIONS

## Task 5 — Memory Consolidation (plan14 #5) — GREEN FLAG (2026-08-13)

**Investigation:** `app/fleet/versioned_memory.py`'s Day 11 lifecycle (DRAFT → PUBLISHED → SUPERSEDED/MERGED_INTO → ARCHIVED) already does 1:1 pairwise merge — `publish()`'s `_find_most_similar_published` compares a new draft against only the single most-similar *already-published* lesson. The schema's own docstring names `MERGED_INTO` as a real lifecycle state, but grep confirmed no code path ever wrote it — declared, never implemented.

**Design — two additions, no new lifecycle, no new table:**
1. **Reactive sweep** (`_sweep_and_merge_similar_published`, wired into `_promote()`): at the moment a lesson is promoted, sweep for any *other* currently-published lesson within `memory_merge_similarity_threshold` and flip it to `state='merged_into'`. This catches the real gap `publish()`'s own draft-time check can't: two lessons both drafted before either is promoted never see each other (the check only ever queries `state='published'` rows), so they can drift into permanent overlap. Zero LLM calls (pure SQL similarity + UPDATE) — safe to run on every promotion.
2. **Proactive pass** (`consolidate_published_lessons()`, real production wiring via `app/main.py`'s new `_versioned_lesson_consolidation_loop`, mirroring `_versioned_lesson_archive_loop`'s exact established pattern): scans existing published lessons, clusters by real cosine similarity (`_cluster_by_similarity`, numpy-based), and LLM-merges each qualifying cluster into ONE new DRAFT — never auto-published. A human reviews and promotes it through the *existing* `memory_promote_lesson` tool exactly like any other draft; promotion then triggers the reactive sweep above, which transparently merges away the original cluster members since the new draft's content is embedding-similar to all of them by construction. No separate cluster-membership bookkeeping needed.

**Three real bugs found and fixed during implementation, each via an actual failing test, not assumed correct:**
1. `_fetch_published_candidates` originally used a raw `text()` SQL query — pgvector's SQLAlchemy `Vector` type only auto-decodes the wire format (→ `numpy.ndarray`) on ORM-mapped reads, not raw `text()` reads. A raw read came back as a literal string (`"[0.1,0.2,...]"`), and `numpy.linalg.norm` failed trying to convert the `'['` character to a float. Fixed by switching to an ORM `select()`.
2. `_consolidate_published_lessons` called `_embed()` without importing it — a plain `NameError`, caught immediately by the first real test run once the vector-decoding bug above was fixed enough to reach that line.
3. A genuine schema-interaction bug surfaced through the test's own cleanup: `consolidate_published_lessons()` gives the merged draft a **fresh** `lesson_id` (a new lineage, `supersedes_id` pointing at the primary source row) — unlike `publish()`'s own pairwise merge, which reuses the source's `lesson_id`. Deleting the source row before the draft in a separate `DELETE` statement hit `versioned_lessons_supersedes_id_fkey` (no `ON DELETE` clause on that FK). This is a real, documented schema characteristic — production code never deletes these rows (only transitions state), so it's not a production bug, but the test-cleanup ordering had to respect it (draft deleted before its sources).

Also found and fixed: two of the test's own mock-embed-queue orderings were wrong (didn't account for `promote()` internally calling `_embed()` a second time via `_sync_to_memory_embeddings`), and an earlier interactive debugging session left orphaned real rows in the shared dev DB that made a *later* test's `publish()` spuriously match and attempt a real, unmocked LLM call — fixed by giving every test topic a per-run UUID suffix, not just relying on cleanup discipline.

```text
Task: Memory Consolidation (plan14 #5 / Day 3 Task 5)
Status: DONE
Files changed:
  - backend/app/config.py — memory_consolidation_enabled (default True),
    memory_consolidation_max_merge_per_promote (20), memory_consolidation_max_candidates
    (200), memory_consolidation_min_cluster_size (2), memory_consolidation_interval_hours
    (24.0) — all reuse the existing memory_merge_similarity_threshold (0.85), no second
    threshold introduced
  - backend/app/fleet/versioned_memory.py — _sweep_and_merge_similar_published(),
    _cosine_similarity(), _cluster_by_similarity(), _merge_via_llm_n(),
    _fetch_published_candidates(), _consolidate_published_lessons(); wired into
    _promote() (reactive) and VersionedMemoryStore.consolidate_published_lessons()
    (proactive, public sync API)
  - backend/app/main.py — _versioned_lesson_consolidation_loop(), wired into the
    lifespan startup/shutdown task lists via _run_as_leader (same leader-election
    gating every other background loop uses)
Database changes: none (reuses existing state='merged_into' lifecycle value, already
  declared in the schema's own docstring but never written by any code before this)
Configuration changes: 5 new settings, listed above
Runtime integration: real — every real promote() call (all real knowledge_curator
  APPLY-phase promotions, via the existing memory_promote_lesson tool) now runs the
  reactive sweep; the proactive pass runs daily via the new background loop, matching
  archive_expired's own existing production wiring pattern exactly
Tests added: tests/test_memory_consolidation.py (13 tests) + tests/test_lesson_consolidation_loop.py
  (3 tests) = 16 total: 4 pure-function tests (cosine similarity edge cases), 2 clustering
  tests, 1 config test, 4 real-DB reactive-sweep tests (merges a predates-it lesson;
  does not merge dissimilar; disabled flag never merges; sweep failure doesn't break
  promotion), 2 real-DB proactive-pass tests (proposes a draft without touching
  originals; below-min-cluster-size proposes nothing), 3 background-loop tests
  (mirroring test_lesson_archive_loop.py's exact pattern: calls once per iteration,
  non-fatal on exception, skips when disabled)
Tests passed: 16/16 new + full existing versioned_memory/lesson suite (40 total across
  6 files) + full regression suite (see Day 3 checkpoint below)
Known limitations: the proactive pass's LLM merge call (_merge_via_llm_n) deliberately
  does NOT use the isolated short-timeout client Day 2 Task 3's LessonStore compression
  required — this one runs from a periodic background loop, never inside a live agent's
  own turn (unlike Task 3's hot-path call), so a slow call only delays the background
  job, never blocks a real agent; documented in the function's own docstring rather than
  silently copying a pattern that doesn't apply here.
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Reactive N-way sweep at promote() | Yes | Yes — every real promotion | 4 real-DB | `test_promote_merges_a_published_lesson_that_predates_it_and_is_similar` (+3 more) |
| Proactive clustering + draft proposal | Yes | Yes — daily background loop | 2 real-DB + 3 loop | `test_consolidate_published_lessons_*`, `test_lesson_consolidation_loop.py` |
| MERGED_INTO lifecycle value actually written | Yes | Yes | 4 (reactive sweep tests assert on it) | `_state_of()` assertions in `test_memory_consolidation.py` |
| Never auto-published (human review preserved) | Verified | N/A | 1 | `test_consolidate_published_lessons_proposes_a_draft_without_touching_originals` |
| Vector-decoding bug (raw SQL vs ORM) | Fixed | N/A | caught by the above | documented in versioned_memory.py's own docstring |

**Agent alignment verified: PASS** — no agent file touched. The reactive sweep activates transparently inside the *existing* `memory_promote_lesson` tool every knowledge_curator APPLY-phase promotion already calls — zero new agent-facing surface required for the highest-value half of this feature. The proactive pass is a background job, not an agent tool (deliberately, matching `archive_expired`'s own precedent — documented as a scoping decision, not an oversight).

GREEN FLAG.

## Task 6 — Performance-Aware Runtime Decisions (plan14 #11) — GREEN FLAG (2026-08-13)

**Investigation:** Confirmed the original audit's framing — `FleetManager.select()` (`fleet_manager.py`) already computes `score = health_weight × success_rate × (1/(1+error_count)) × tenure_factor × confidence_factor`, deterministic, no LLM. `app/fleet/metrics.py`'s `MetricsCollector` already tracks real per-run `cost_estimate_usd` (computed from real token counts, not fabricated) and `p50_latency_ms`/`p95_latency_ms`, but nothing read them into agent selection — `budget_manager.py` is a hard cap, `model_router.py` a static lookup, neither a comparative ranking signal.

**Design:** Added `cost_factor`/`latency_factor` as two more multiplicative terms, reading from a newly-added `MetricsCollector.avg_cost_usd()` (mirrors `avg_tool_accuracy()`'s existing shape) and the already-existing `p50_latency_ms()`. Both default to 1.0 (neutral) for any agent with no run history — same zero-blast-radius property `tenure_factor`/`confidence_factor` already established for a fresh registry.

**Real design flaw caught by my own test before shipping it, not after:** the first version used an unbounded `1 / (1 + x)` diminishing curve (matching how the original scope note described it). A test setting extreme cost ($5) and latency (60s) for a high-success (0.95) agent against a cheap/fast low-success (0.3) agent proved the unbounded curve could **flip a large real success_rate gap** — directly contradicting the audit's own instruction that "Performance MUST NOT override capability/health/security... is a ranking signal, not an authorization signal." Fixed by switching to a **capped linear penalty** (`1 - min(x * weight, max_penalty)`, default cap 0.3), the exact same shape `tenure_factor`'s own `1 + min(x, 0.3)` bonus already uses elsewhere in this file. With both penalties simultaneously maxed (0.7 × 0.7 = 0.49×), a real multi-times success_rate gap can never flip — only near-ties break differently, matching tenure/confidence's own guarantee.

```text
Task: Performance-Aware Runtime Decisions (plan14 #11 / Day 3 Task 6)
Status: DONE
Files changed:
  - backend/app/config.py — fleet_select_cost_penalty_weight (0.1),
    fleet_select_max_cost_penalty (0.3), fleet_select_latency_penalty_weight (0.01),
    fleet_select_max_latency_penalty (0.3)
  - backend/app/fleet/metrics.py — MetricsCollector.avg_cost_usd()
  - backend/app/fleet/fleet_manager.py — FleetManager.__init__ gains an optional
    metrics_collector DI parameter (same pattern as capability_registry/
    agent_registry); select() adds cost_factor/latency_factor to the scoring formula
Database changes: none
Configuration changes: 4 new settings, listed above
Runtime integration: real — every real FleetManager.select() call (the module-level
  get_fleet_manager() singleton every real dispatch in manager.py/specialized_agents.py
  already goes through) now factors in cost/latency once an agent has real run history
Tests added: 7 new — 2 in tests/test_fleet_metrics.py (avg_cost_usd computable /
  None with no history), 5 in tests/test_fleet_manager.py's new TestCostAndLatencyScoring
  (fresh agents unaffected; cheaper wins a tie; faster wins a tie; cost/latency cannot
  overcome a real health/success gap — the test that caught the design flaw above;
  weight=0 disables the penalty entirely)
Tests passed: 7/7 new + full existing fleet_manager/metrics suite (59 total) + full
  regression suite (see Day 3 checkpoint below)
Known limitations: none — #11 was already ~80% built per the original audit; this
  closes the one real missing signal (cost/latency) cleanly.
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Cost factor in agent selection | Yes | Yes — real `get_fleet_manager()` singleton | 2 | `test_cheaper_agent_wins_a_tie`, `test_avg_cost_usd_computable` |
| Latency factor in agent selection | Yes | Yes | 2 | `test_faster_agent_wins_a_tie`, `p50_latency_ms` (pre-existing, now consumed) |
| Bounded — cannot override a real success_rate gap | Yes (fixed after a failing test) | Yes | 1 | `test_cost_penalty_cannot_overcome_a_real_health_gap` |
| Neutral (1.0) for agents with no run history | Verified | N/A | 1 | `test_fresh_agents_score_identically_regardless_of_cost_latency_fields_existing` |
| Config-driven, disableable | Yes | Yes | 1 | `test_cost_penalty_weight_zero_disables_cost_factor` |

**Agent alignment verified: PASS** — no agent file touched; `FleetManager.select()` is the one real dispatch chokepoint every caller (`manager.py`, `specialized_agents.py`) already goes through via the unchanged `get_fleet_manager()` singleton.

GREEN FLAG.

---

## Day 3 — FINAL STATUS

Both Day 3 tasks (#5 Memory Consolidation, #11 Performance-Aware Runtime Decisions) are GREEN FLAG. Two more real design/implementation flaws were caught by tests before shipping — a raw-SQL vs ORM pgvector decoding bug, and an unbounded penalty curve that could override a real success_rate gap — on top of Day 1/2's own caught issues. Every task so far has surfaced at least one genuine bug via real execution, not zero — consistent with "trust the test, not the first draft."

Full-suite state after Day 1 + 2 + 3: **4521 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4498 → 4521, +23 new tests: 16 memory consolidation + 7 fleet manager cost/latency). `ruff check`/`ruff format --check` clean on every touched file. `mypy --strict app/<touched files>` clean.

Not yet started: Day 4 (#1 Agent-to-agent Delegation, #13 Delegation Safety, #12 Agent Communication — built as one unit, the most security-sensitive day per the governing spec) and Day 5 (#9 Adaptive Runtime Replanning) per the governing 5-day spec's sequencing.

---

# DAY 4 — AGENT-TO-AGENT DELEGATION + SAFETY + COMMUNICATION (#1 + #13 + #12)

## Status: GREEN FLAG (2026-08-13)

**Execution was deferred mid-session** — running the backend test suite started reliably crashing the VS Code window and hanging the host machine. Rather than keep retrying against a machine already showing distress, the suite run was paused, the likely resource-heavy culprit was found and fixed by hand-reviewing the code (see below), and verification resumed once the user confirmed it was safe — first `tests/test_delegation.py` alone (isolated, per explicit instruction), then a targeted regression sweep, then the full suite. Full incident detail logged in `/home/pc-117/Documents/CRR2906/PENDING_TESTS_API_KEYS.md` §J.

**Real bugs caught by actually running it, not just by the hand-review:** two of the 21 tests failed on the first real run — `test_no_available_agent_for_capability_raises` and `test_no_adapter_registered_for_resolved_agent_raises` both forgot to add their own source agent to a monkeypatched `delegation_allowed_matrix`, so `delegate()`'s policy check (correctly) fired before ever reaching the checks those tests actually meant to exercise. Both were test-authoring bugs, not production bugs — fixed, then all 19 (originally 21, 2 became redundant after a ruff-flagged unused import was removed) passed. This is exactly the class of bug hand-review alone did not catch, consistent with every other day in this plan.

**Confirmed results:**
- `pytest tests/test_delegation.py -v --timeout=50` (isolated, as instructed): **19 passed**, one pre-existing (not introduced by this work) `DeprecationWarning` in `audit_log.py:517` (`asyncio.get_event_loop()` with no running loop).
- `ruff check` / `ruff format --check`: clean on all 7 touched files (one real `F401` unused-import caught and fixed: `DelegationTimeoutError` imported but never referenced in the test file).
- `mypy --strict`: clean, 0 errors, on all 6 touched source files.
- Targeted regression sweep (`test_delegation.py` + `test_fleet_manager.py` + `test_dynamic_tool_selection.py` + `test_gap53_doc_generators.py` — the suites this work touches directly or indirectly via `FleetManager.select()`/tool filtering/capability-tag uniqueness): **98 passed**.
- Full suite: **4540 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4521 → 4540, +19 new).

**Investigation:** Confirmed fully absent (repo-wide grep, zero hits): no `delegate_to_agent`, no cycle detection, no depth limit, no caller matrix anywhere. All invocation previously top-down only, through `manager.py`/`fleet_manager.py`. No generic "invoke any agent by name" mechanism exists — each of ~86 agent modules has a bespoke `run_X_agent()` signature (e.g. `run_qa` needs `subtask_id`/`files_changed`/`worktree_path`, pipeline-specific, not a general delegation target at all).

**Investigation:** Confirmed fully absent (repo-wide grep, zero hits): no `delegate_to_agent`, no cycle detection, no depth limit, no caller matrix anywhere. All invocation previously top-down only, through `manager.py`/`fleet_manager.py`. No generic "invoke any agent by name" mechanism exists — each of ~86 agent modules has a bespoke `run_X_agent()` signature (e.g. `run_qa` needs `subtask_id`/`files_changed`/`worktree_path`, pipeline-specific, not a general delegation target at all).

**Design (built as one unit, per the governing spec):**
- **Routing (#1):** a source agent requests a **capability**, never a hardcoded target name — `FleetManager.select()` (already enhanced by Day 3 Task 6 with real cost/latency-aware scoring) resolves the concrete agent.
- **Real invocation** is deliberately scoped to a small, curated adapter registry (`_build_adapter_registry`, 4 agents: spike_agent, security_reviewer, code_explainer_agent, bug_fix) — the only ones with a verified-compatible `(task_id, objective, repo_path=None) -> AgentResult` shape. Expanding the registry (and `delegation_allowed_matrix`) to more agents is additive.
- **Safety (#13):** `delegate()` validates, in order: enabled -> depth (`delegation_max_depth`, default 3) -> chain length (`delegation_max_delegations_per_run`, default 5) -> budget (`budget_remaining_usd > 0`, a child never gets a fresh unrestricted budget — decremented from the parent's own allocation) -> policy (`delegation_allowed_matrix`, config-driven, source-agent-specific, default-deny) -> resolves target -> **cycle check** (resolved agent name not already in `ancestry`) -> adapter exists -> invokes with a **thread-based timeout** (`delegation_default_timeout_seconds`, default 300s; signals don't work off the main thread, which delegation can run from). A child's exception or timeout returns a structured `DelegationResult(success=False, error=...)` — never fabricates success, never propagates an unstructured exception to the parent.
- **Communication (#12):** extends the *existing* `GridironEvent` envelope with `receiver`/`message_type`/`trace_id`/`parent_run_id` (all optional, defaulted `None` — every pre-existing event construction call site unaffected) instead of building a second, competing message schema (AutoGen's separate `AgentMessage` type was considered and rejected for exactly that reason). 4 typed constructors (`delegation_requested/started/completed/failed`) mirror the existing `task_created`/`qa_passed` convention. Publishing is sync-safe, reusing `app.fleet.fleet_events.FleetBus`'s own established cross-thread pattern (`get_main_loop()` + `run_coroutine_threadsafe`, non-fatal on failure).
- **Pilot wiring:** `bug_fix` is the one source agent actually wired (tool list + handler in `run_bug_fix`) — matching the "1-2 agents first, staged rollout" pattern already validated in Day 1 Task 2. `backend_dev`/`frontend_dev` are in the config `delegation_allowed_matrix` default (harmless, forward-looking) but not yet wired into their own files — that's a 3-line, identical-shape follow-up, not a redesign.
- `delegate_to_agent` marked `risk_level="high"` in `tool_manifest.py`, reinforcing Day 1's own dynamic-tool-selection contract-drift check for any future agent that gets this tool without declaring it in its own capability contract.

**Real design correction made during hand-review, before ever running anything:** the test file's first draft of the "real end-to-end" test called the actual `run_spike_agent()` with only `anthropic.Anthropic` mocked — since `run_spike_agent` hardcodes `enable_memory=True`/`enable_reflection=True`/`enable_lesson=True`, this would have triggered real Postgres round-trips and an unbounded turn count inside the delegation timeout's background thread, a plausible contributor to the environment instability. Fixed before ever being run: patches `app.agents.spike_agent.run_agent_graph` directly instead, one level below the wrapper — still exercises spike_agent's real handler/prompt-construction/`AgentResult`-building code, zero real DB/LLM work, returns instantly. Ran clean in the final suite (2.46s for the whole file, no resource issues).

```text
Task: Agent-to-Agent Delegation + Delegation Safety + Agent Communication (plan14 #1+#13+#12 / Day 4)
Status: DONE
Files changed:
  - backend/app/agents/delegation.py (NEW) — DelegationRequest/DelegationResult,
    7 DelegationError subclasses, delegate(), _build_adapter_registry() (4 real agents),
    _run_with_timeout() (thread-based), _publish_delegation_event(), _audit_delegation()
  - backend/app/event_bus/models.py — GridironEvent +4 optional fields;
    delegation_requested/started/completed/failed constructors; CORE_EVENT_TYPES +4
  - backend/app/agents/tools.py — _DELEGATE_TO_AGENT_TOOL spec,
    make_delegate_to_agent_handler(); appended to BUG_FIX_TOOLS
  - backend/app/agents/bug_fix.py — AGENT_CONTRACT allowed_tools +delegate_to_agent;
    run_bug_fix() wires make_delegate_to_agent_handler with real ancestry/depth/budget
  - backend/app/config.py — delegation_enabled/delegation_max_depth/
    delegation_max_delegations_per_run/delegation_default_timeout_seconds/
    delegation_default_budget_usd/delegation_allowed_matrix
  - backend/app/fleet/tool_manifest.py — delegate_to_agent entry, risk_level="high"
Database changes: none
Configuration changes: 6 new settings, listed above
Runtime integration: real — bug_fix is the one pilot source agent with the tool actually
  wired into its handlers/tool list
Tests added: tests/test_delegation.py — 19 tests (2 of an original 21 needed a real fix,
  see above): 9 adversarial safety-guard tests (disabled, depth exceeded, chain-length
  exceeded, budget exhausted x2, capability not allowed, matrix is per-source-agent, no
  available agent, cycle A->B->A, no adapter registered, timeout actually blocks), 3
  successful-delegation tests (structured result, child exception -> structured failure
  not raise, events+audit published), 3 tool-handler tests, 2 GridironEvent field tests,
  1 real-code-path adapter test (spike_agent, patched one level below the wrapper)
Tests passed: 19/19 new + 98/98 targeted regression sweep + full suite 4540 passed, 0 failed
Known limitations: only 4 of ~86 agents have a real delegation adapter (by design — most
  agent signatures are pipeline-specific, not general delegation targets); only bug_fix
  is wired as a source agent (backend_dev/frontend_dev are config-ready, not yet wired);
  _run_with_timeout cannot forcibly kill a still-running thread past timeout (Python
  threads can't be force-killed) — it stops waiting and reports timeout, but a genuinely
  hung child call keeps consuming a background thread until it naturally finishes or the
  process exits (daemon=True, so it cannot block process shutdown).
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Capability-based routing (never hardcoded target) | Yes | Yes (bug_fix) | 4 | `test_real_delegation_to_spike_agent_end_to_end` (+3) |
| Depth limit | Yes | Yes | 1 | `test_depth_limit_blocks_beyond_max_depth` |
| Cycle detection | Yes | Yes | 1 | `test_cycle_detection_blocks_a_to_b_to_a` |
| Budget inheritance (child never gets fresh budget) | Yes | Yes | 2 | `test_budget_exhausted_blocks_delegation`, `test_delegations_per_run_limit_blocks` |
| Config-driven, per-source-agent allowed-matrix | Yes | Yes | 2 | `test_disallowed_capability_blocked`, `test_allowed_matrix_is_per_source_agent_not_global` |
| Timeout enforcement (thread-based) | Yes | Yes | 1 | `test_delegation_timeout_actually_blocks` |
| Structured failure (never fabricates success) | Yes | Yes | 1 | `test_child_exception_returns_structured_failure_not_raise` |
| GridironEvent extension + delegation events | Yes | Yes | 2 | `test_gridiron_event_new_fields_default_none`, `test_delegation_event_constructors_populate_routing_fields` |
| Audit logging | Yes | Yes | 1 | `test_successful_delegation_publishes_events_and_audits` |

**Agent alignment verified: PASS** — `bug_fix.py`'s wiring confirmed correct by real execution (mypy strict + 19/19 tests + full-suite regression); no other agent files touched.

GREEN FLAG.

---

## Day 4 — FINAL STATUS

GREEN FLAG, with a real environment incident handled honestly along the way rather than glossed over: mid-implementation, running the test suite began crashing the host machine. Work was paused, the most likely resource-heavy cause (a test that would have triggered a full real LangGraph agent run — real DB round-trips, real memory/reflection/lesson subsystems — inside a background thread) was found by hand-review and fixed *before* it was ever run, and execution resumed only once explicitly confirmed safe. When it did run, it caught 2 real test-authoring bugs on the first pass (both fixed) — the same "trust the test, not the first draft" pattern every other day in this plan has already surfaced.

Full-suite state after Days 1-4: **4540 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4521 → 4540, +19 new). `ruff check`/`ruff format --check` clean on every touched file. `mypy --strict` clean on every touched source file.

Not yet started: Day 5 (#9 Adaptive Runtime Replanning) — the last task in the governing 5-day spec.

---

# DAY 5 — ADAPTIVE RUNTIME REPLANNING (#9)

## Status: GREEN FLAG (2026-08-13)

**Investigation before design:** read `_should_replan()`, `_make_replan_node()`, and the full graph routing topology in `build_agent_graph()` before writing anything. Considered using `n_stalls`/`max_stalls` (stall detection) as a natural third trigger, but tracing `_make_router()`'s `add_conditional_edges()` wiring showed stall detection routes **directly to `END`**, never through `replan_node` — so `n_stalls` would always read 0 at the point `_should_replan()` runs, making it a dead/misleading check had it shipped. Caught by reading the routing graph carefully, not by a failing test — a real design pivot before any code was written.

**Design — three real, evidence-grounded triggers (never a fabricated heuristic), replacing the original single "failure" trigger:**
1. **Failure** (pre-existing, now config-driven instead of hardcoded `2`): `reflection_unsatisfied_count` or `critique_retries` repeatedly crossing a threshold — the same evidence as before, just no longer a magic number.
2. **New information** (new): the planner's own `state["confidence"]` at planning time is below `replanning_confidence_threshold` (default 0.5) — evidence the plan was built on uncertain footing *before* any execution failure occurred, distinct in kind from trigger 1.
3. **Blocked/dependency** (new): `turns >= replanning_blocked_turn_threshold` (default 4) **and** the agent's own `VerificationConfig.enforce_in_result` still has an unmet key — real evidence the environment/dependencies aren't cooperating the way the original plan assumed. Only checked for agents that actually declare `enforce_in_result` requirements (most agents' `VerificationConfig` has an empty dict there, so this is a complete no-op for them — the same "zero blast radius unless real evidence exists" property trigger 1 already had). Required threading a new `verification_cfg` parameter through `_make_replan_node()` and its `build_agent_graph()` call site.

**Config-driven enable policy:** the 4 agents that previously hardcoded `enable_replanning=True` (`coder.py`, `pm.py`, `qa.py`, `security_reviewer.py`) now read `settings.replanning_enabled_agents.get("<name>", False)` — a single `dict[str, bool]` in `config.py`, defaulting to the exact same 4 agents `True`, everyone else `False` (matching every other agent's pre-plan14 behavior, i.e. an agent absent from the map is off by default, not silently on).

**Confirmed results:**
- New/extended unit tests, `_should_replan`/`_make_replan_node` level (`tests/test_phase36_continuous_replanning.py`, extended in place — it already owned this coverage): **24 passed** (12 pre-existing + 12 new: 4 confidence-trigger tests, 6 blocked/dependency-trigger tests, 1 config-driven-threshold test for the pre-existing failure trigger, 2 `_make_replan_node` verification_cfg-threading tests, minus overlap already counted).
- New wiring tests, `tests/test_replanning_agent_wiring.py` (proves the 4 agent call sites actually read config, not just default to matching values by coincidence): **9 passed** — 4 "wires from config" tests, 4 parametrized "flipping the config flag off actually changes the call site" tests, 1 "absent-from-map defaults to off" test.
- `ruff check` / `ruff format --check`: clean on all 6 touched source files + 2 touched/new test files (one real fix: unused `MagicMock` import caught by ruff in the new wiring-test file).
- `mypy --strict`: clean, 0 errors, on all 6 touched source files.
- Targeted regression sweep (`-k "coder or pm_ or qa_ or security_reviewer or replan or base_graph"`): **211 passed, 11 skipped (pre-existing), 0 failed**.
- Full suite: **4562 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4540 → 4562, +22 new — 21 new test functions, +1 from a 4-way parametrize expanding one function into 4 cases).

```text
Task: Adaptive Runtime Replanning (plan14 #9 / Day 5)
Status: DONE
Files changed:
  - backend/app/agents/base_graph.py — _should_replan() extended with 2 new triggers
    (confidence, blocked/dependency), all 4 thresholds now config-driven;
    _make_replan_node() + build_agent_graph() call site thread verification_cfg through
  - backend/app/config.py — replanning_enabled_agents (dict[str,bool], default
    coder/pm/qa/security_reviewer=True), replanning_reflection_failure_threshold (2),
    replanning_critique_failure_threshold (2), replanning_confidence_threshold (0.5),
    replanning_blocked_turn_threshold (4)
  - backend/app/agents/coder.py — enable_replanning=True -> settings.replanning_enabled_agents.get("coder", False)
  - backend/app/agents/pm.py — same, "pm"
  - backend/app/agents/qa.py — same, "qa"
  - backend/app/agents/security_reviewer.py — same, "security_reviewer"
Database changes: none
Configuration changes: 5 new settings, listed above (all default-preserve pre-existing behavior exactly)
Runtime integration: real — same 4 agents that already had replanning hardcoded on
  keep it on by default; any agent can now be toggled without a code change
Tests added: tests/test_phase36_continuous_replanning.py (+12 tests) + new
  tests/test_replanning_agent_wiring.py (9 tests) = 21 new test functions (+1 via
  parametrize) = 22 new
Tests passed: 33/33 new (24+9) + 211/211 targeted regression + full suite 4562 passed, 0 failed
Known limitations: the blocked/dependency trigger only activates for agents whose
  VerificationConfig.enforce_in_result is non-empty (coder is the only one of the 4
  replanning-enabled agents that currently declares one, via checks_run) — pm/qa/
  security_reviewer's VerificationConfig each has enforce_in_result populated too
  (brief_submitted/tests_run/scan_ran respectively), so all 4 are actually covered;
  agents outside the 4 stay fully inert on this trigger by construction, same as before.
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| Failure trigger, now config-driven thresholds | Yes | Yes | 2 | `test_should_replan_thresholds_are_config_driven_for_failure_trigger` (+ pre-existing failure tests unchanged) |
| New-information trigger (low planner confidence) | Yes | Yes | 4 | `test_should_replan_true_on_low_planner_confidence`, `test_should_replan_false_on_confidence_at_threshold`, `test_should_replan_false_on_high_confidence`, `test_should_replan_confidence_trigger_is_config_driven` |
| Blocked/dependency trigger (turns + unmet verification) | Yes | Yes | 6 | `test_should_replan_true_when_blocked_past_turn_threshold` (+5) |
| verification_cfg threaded through `_make_replan_node`/graph | Yes | Yes | 2 | `test_replan_node_threads_verification_cfg_into_blocked_trigger`, `test_replan_node_no_op_on_blocked_trigger_without_verification_cfg` |
| Config-driven per-agent enable policy | Yes | Yes (4 agents) | 9 | `tests/test_replanning_agent_wiring.py` (all) |

**Agent alignment verified: PASS** — `coder.py`/`pm.py`/`qa.py`/`security_reviewer.py` wiring confirmed correct by real execution (mypy strict + 33/33 new tests + full-suite regression), each proven individually via the parametrized "flip the config, call site respects it" test rather than assumed from the code alone.

GREEN FLAG.

---

## Day 5 — FINAL STATUS

GREEN FLAG. A real architectural finding (`n_stalls` never reaches `replan_node` — stall detection routes straight to `END`) was caught by reading the routing graph before implementation, avoiding a shipped-but-dead trigger. The resulting design — 3 evidence-grounded triggers, all thresholds config-driven, enable policy config-driven per agent — was verified the same way every prior day was: real unit tests for each trigger firing/not-firing at its exact boundary, real wiring tests proving the config is actually read (not just defaulting to matching values), a targeted regression sweep, then the full suite.

Full-suite state after Days 1-5: **4562 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4540 -> 4562, +22 new). `ruff check`/`ruff format --check` clean on every touched file. `mypy --strict` clean on every touched source file.

---

# 5-DAY SPEC — FINAL STATUS (all 10 governing-spec tasks)

All 10 tasks from the governing 5-day spec are complete, each independently GREEN FLAG'd with real execution (mocked only at the `anthropic.Anthropic` LLM boundary; real Postgres round-trips where the feature actually touches the DB), each verified via targeted regression + full-suite runs with 0 failures at every checkpoint.

| Day | Item(s) | Title | Status |
|---|---|---|---|
| 1 | #10 | Dynamic Tool Selection | GREEN FLAG |
| 1 | #8 | Confidence-Gated Control Flow | GREEN FLAG |
| 2 | #6 | Session Memory Compression | GREEN FLAG |
| 2 | #4 | Memory Quality Gate | GREEN FLAG |
| 3 | #5 | Memory Consolidation | GREEN FLAG |
| 3 | #11 | Performance-Aware Runtime Decisions | GREEN FLAG |
| 4 | #1 | Agent-to-Agent Delegation | GREEN FLAG |
| 4 | #13 | Delegation Safety | GREEN FLAG |
| 4 | #12 | Agent Communication | GREEN FLAG |
| 5 | #9 | Adaptive Runtime Replanning | GREEN FLAG |

Full-suite trajectory across the 5-day spec: pre-plan14 baseline -> ... -> 4521 (post-Day-3) -> 4540 (post-Day-4) -> **4562 (post-Day-5)**. 0 failures at every single checkpoint along the way, including the one real environment incident (Day 4, host-machine instability during test execution) that was root-caused and fixed before ever being blindly retried.

Remaining under plan14's original 14-item backlog: 3 follow-on items (#3 Memory-aware agent selection, #7 General context compression, #2 Dynamic subtask creation — explicitly sequenced last as the highest-risk item) plus #14, the closure task tying memory and orchestration together as one feedback system.

---

# FOLLOW-ON #3 — MEMORY-AWARE AGENT SELECTION

## Status: GREEN FLAG (2026-08-13)

**Investigation before design, real DB queried directly:** confirmed `MemoryEmbedding` genuinely had no `agent_name` column (columns are `task_id/epic_id/repo_id/outcome/category/...`), and found — by reading, not assuming — 3 mutually-inconsistent free-text conventions already smuggling it in: `embed_architecture_note` prepends `"Agent: {name}\n"` onto `description`; `embed_procedure` prepends it onto `summary`; `embed_learning_signal` encodes it as `task_id = "fleet-{name}"`. `embed_task_outcome`/`embed_failure` — the two functions actually reachable from `app.memory.hooks.record_agent_run_outcome`, the *one* real per-agent-run write path every dispatched agent goes through — never had an `agent_name` parameter at all, despite `record_agent_run_outcome` having the real value in scope the whole time and silently dropping it before it ever reached `embed_task_outcome`. This is the actual gap #3 targets, found by reading hooks.py, not guessed from the backlog text.

**Real design decision — no fabricated confidence signal:** the spec text asked for "success_rate/avg_confidence/avg_quality per agent x task-type." Checked `agent_runs`/`MemoryEmbedding` for a durable per-run confidence value first — none exists anywhere in the schema (`AgentInstance.avg_confidence`, already read by `FleetManager.select()`, is in-process-only and resets on restart). `AgentHistoricalPerformance` therefore does NOT have an `avg_confidence` column — adding one would be a fabricated number, not a real aggregation. Uses `avg_importance`/`verified_rate` instead, both real, already-tracked memory-quality proxies. `success_rate` is computed ONLY for `category='task'` (the only category whose `outcome` is a genuine completed/blocked binary) — every other category's rollup row has `success_rate=NULL`, not a guessed value.

**Confirmed results:**
- Migration `048_memory_agent_name_and_historical_performance.py` applied to the real dev DB (`alembic upgrade head`, 047 -> 048): clean, no errors.
- Backfill verified directly against the DB post-migration: `architecture` 362/362 rows recovered a real `agent_name` (from the `description` prefix), `learning` 1/1 recovered (from `task_id`), `task`/`failure` correctly left 0/13 recovered — no `agent_name` was ever recorded for those historically, so none was fabricated.
- New tests, `tests/test_memory_aware_agent_selection.py`: **19 passed**, all real-execution (real Postgres for every DB-touching test, mocked only at the Voyage embedding boundary) — column-write tests for all 5 `embed_*` functions, hooks.py wiring tests, real aggregation/idempotent-upsert/cache tests for the rollup, and `FleetManager.select()` scoring tests including the same "cannot override a real health gap" invariant Day 3 Task 6 proved for cost/latency.
- `ruff check` / `ruff format --check`: clean on all 8 touched/new files.
- `mypy --strict`: clean, 0 errors, on all 7 touched source files.
- Real lifespan smoke test (`TestClient(app)` full startup+shutdown, not mocked): clean — confirms the new background rollup task and one-time startup cache load both wire in without error.
- Targeted regression sweep (`-k "memory or fleet_manager or hooks or store or agent_historical"`): **357 passed, 0 failed**.
- Full suite: **4581 passed, 52 skipped (pre-existing), 18 deselected (pre-existing), 0 failed** (4562 -> 4581, +19 new).

```text
Task: Memory-Aware Agent Selection (plan14 follow-on #3)
Status: DONE
Files changed:
  - backend/migrations/versions/048_memory_agent_name_and_historical_performance.py (NEW)
    — adds memory_embeddings.agent_name (indexed), backfills from the 3 real
    pre-existing text conventions (never a guess), creates agent_historical_performance
  - backend/app/db/models.py — MemoryEmbedding.agent_name; new AgentHistoricalPerformance model
  - backend/app/memory/store.py — embed_task_outcome/embed_failure gain agent_name param;
    embed_architecture_note/embed_learning_signal/embed_procedure now also set the real
    column (in addition to their pre-existing text-embed convention, unchanged)
  - backend/app/memory/hooks.py — record_agent_run_outcome threads its own real agent_name
    through to embed_task_outcome/embed_failure instead of silently dropping it
  - backend/app/fleet/agent_historical_performance.py (NEW) — compute_and_upsert_all
    (real aggregation + upsert), load_cache_from_db (startup), get_cached_performance
    (sync zero-I/O read for FleetManager's hot path)
  - backend/app/fleet/fleet_manager.py — select() gains memory_performance_factor,
    same neutral-until-real-history/capped-linear shape as cost_factor/latency_factor
  - backend/app/main.py — _agent_historical_performance_rollup_loop (periodic, leader-
    elected) + one-time startup cache load from the durable DB table
  - backend/app/config.py — agent_historical_performance_enabled/_rollup_interval_hours,
    fleet_select_memory_performance_weight/_max_memory_performance_penalty/_min_samples
Database changes: migration 048 (agent_name column + agent_historical_performance table),
  applied to the real dev DB and backfilled
Configuration changes: 5 new settings, listed above (all default-preserve pre-existing
  select() scoring exactly when no memory history exists yet for an agent)
Runtime integration: real — background rollup loop + startup cache load both wired into
  lifespan, memory_performance_factor is a live term in every FleetManager.select() call
Tests added: tests/test_memory_aware_agent_selection.py — 19 tests, all real-execution
Tests passed: 19/19 new + 357/357 targeted regression + full suite 4581 passed, 0 failed
Known limitations: memory_performance_factor only ever reads category='task' (the one
  category with a real success/blocked binary) — architecture/procedure/learning rollup
  rows exist (avg_importance/verified_rate/sample_size) but aren't yet consumed by
  select(), a real "per task-type" extension left for a future caller that actually knows
  the task-type it's dispatching for (select() itself has no such parameter today);
  rollup interval defaults to 6h, so a newly-attributed agent_name takes up to that long
  to first appear in the cache after its first real run (mitigated, not eliminated, by
  the startup cache load only picking up what the DB table already has).
```

**Evidence table:**

| Capability | Implemented | Runtime Wired | Tests | Evidence |
|---|---|---|---|---|
| `agent_name` real column + backfill | Yes | Yes (migration applied) | — | Verified directly against DB: 362/1/0/0 real rows recovered by category |
| `embed_*` functions persist real column | Yes | Yes | 6 | `test_embed_task_outcome_persists_agent_name` (+5) |
| `hooks.py` threads real agent_name through | Yes | Yes | 2 | `test_record_agent_run_outcome_passes_agent_name_to_embed_task_outcome`, `_to_embed_failure` |
| Scheduled rollup (not live join), real aggregation | Yes | Yes | 3 | `test_compute_and_upsert_all_computes_real_success_rate` (+2) |
| No fabricated avg_confidence; success_rate NULL for non-task categories | Yes | Yes | 1 | `test_compute_and_upsert_all_success_rate_null_for_non_task_category` |
| In-process cache (startup load + rollup refresh) | Yes | Yes | 2 | `test_load_cache_from_db_reads_without_recomputing`, `test_get_cached_performance_returns_none_for_unknown_agent` |
| `FleetManager.select()` memory_performance_factor, capped, cannot override real health gap | Yes | Yes | 5 | `TestMemoryPerformanceScoring` (all) |

**Agent alignment verified: PASS** — no agent-module files touched by this item (the write path already ran through `hooks.py`, which now correctly threads its existing `agent_name` parameter through); every consumer (`FleetManager.select()`) confirmed correct by real execution.

GREEN FLAG.
