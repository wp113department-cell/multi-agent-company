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
