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
