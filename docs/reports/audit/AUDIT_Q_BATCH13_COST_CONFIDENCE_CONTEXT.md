# Batch 13 — Cost Awareness, Confidence & Uncertainty, Explainability, Multi-Session Continuity, Large Context Understanding, Token/Context Budget, Economic Awareness

Covers §42, §43, §44, §45, §52, §65, §101. Evidence-only, file:line cited.

**Remediated 2026-08-11** (Production Implementation Agent pass). Every implementable
checkpoint below was closed in this pass; the two remaining non-YES rows are documented
scope decisions, not defects — see their own rows for why. Full backend test suite
(4032 passed, 51 skipped, 17 deselected), `ruff check .`, `black --check .`, and
`mypy app/ --strict --ignore-missing-imports` all green after the change; migration 040
applied and smoke-tested against the live dev DB (`GET /api/tasks/{id}/explain` verified
end-to-end against a real task row).

---

## §42 Cost Awareness

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Pre-execution cost/token estimate | **YES — Production Ready** | `_cost_estimate_node` (`app/agents/manager.py:1227`) runs **before** planning/coding in the epic-manager graph, calls `estimate_epic_cost()` which computes tokens/cost/duration. Real, config-driven threshold: `cost > settings.cost_approval_threshold` → `Epic.status = "pending_cost_approval"`, hard-halts pending human approval. Not observability-only — a real gating state transition. |
| Recommend cheaper approaches | **YES — gap-closure 2026-08-11** | All 4 real dispatched agents (backend_dev/frontend_dev/qa/reviewer) are pinned sonnet-tier in `agent_models.json` — confirmed via `ModelRouter.route()` — so a tier-downgrade suggestion would be advisory fiction with no agent that could actually execute on it. The genuinely actionable lever is **scope**: cost scales linearly with `subtask_count`, so `CostEstimate` (`app/pipeline/cost_controller.py:58-81`) now carries `cost_per_subtask_usd` and `max_subtasks_within_threshold` (real division against `estimated_cost_usd`/`cost_approval_threshold`, not invented numbers). `_cost_estimate_node` (`app/agents/manager.py:1257-1310`) builds a concrete recommendation ("Reducing scope to ~N subtask(s) would fit within the threshold... or approve to proceed") and — a real bug found and fixed in the same pass — now actually **persists** it to `Epic.halt_reason` (previously this branch never set that column at all, unlike every other halt path in this file), so it reaches the human-facing `GET /epics/batch-review` endpoint's `haltReason` field, not just an in-memory value nothing reads. Also added to the `epic.pending_cost_approval` event payload. |

**§42 overall: YES.** Both the gating half and the advisory half are now real, computed, and exposed through a live human-facing surface.

---

## §43 Confidence & Uncertainty

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Every important answer has a confidence estimate | **YES — gap-closure 2026-08-11** | The shared planner (`base_graph.py::_gather_facts_and_plan`) already computed a real per-run confidence score into `final_state["confidence"]` for every `run_agent_graph()`-based agent (pm/qa/reviewer all call it with `enable_planning=True`) — it was being discarded at the three checked output boundaries instead of surfaced. Fixed at the source: `QAResult`/`ReviewResult` (`app/agents/qa.py`, `app/agents/reviewer.py`) gained a `confidence: float = 0.0` field populated from `final_state.get("confidence", 0.8)` at every real construction site; `pm_node` (`app/agents/pm.py:204-217`) merges `confidence` onto the brief dict before returning it. Exposure verified end-to-end, not just added as a dead field: pm's confidence rides the *existing* `pm_brief` → `save_artifact_async()` → `"pmBrief"` API field path (`app/api/tasks.py`); qa/reviewer's confidence was added to the real `qa.passed`/`qa.failed`/`review.completed` event-bus payloads (`app/agents/manager.py`) that already carried their other real fields (verdict, blocking_count, errors). |
| Distinguish verified facts from assumptions | **YES — exposed, not just internal** (unchanged) | `_quality_gate` results (`checks`, `warnings`, `passed`) are attached to every submit-tool result and surface through the API (`specialized_agents.py:295,477`). `AgentResult.verified` comes exclusively from real tool-derived `state["verification"]`, never the model's own claim — enforced with a logged override whenever they disagree. |
| Explicitly say "I don't know" | **YES — code-enforced, informational** (unchanged) | `limitation_type`/`proposed_alternative` checked and warned-on when missing for blocked/needs_human results — real code, mirrors the prompt-level `_GLOBAL_STANDARDS.md` rule. |

**§43 overall: YES.** All three checkpoints are now real, and the previously-missing confidence field reuses an already-computed value rather than inventing a new signal.

---

## §44 Explainability

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Explain why this approach / these agents / these tools were chosen | **YES — gap-closure 2026-08-11** | New `GET /api/tasks/{task_id}/explain` endpoint (`app/api/tasks.py`) synthesizes a coherent, plain-language explanation from real, already-persisted data: PM-brief goals, the architect's `technical_approach`/`risk_level`, and agent-dispatch rationale (see next row). `_synthesize_explanation()` never invents content — a section is omitted, not guessed, when the underlying data doesn't exist yet (verified live: a fresh task with no planning run returns "No structured planning or agent-dispatch rationale has been recorded for this task yet."). Smoke-tested against the live dev DB. |
| Structured decision-log/rationale field in DB | **YES — gap-closure 2026-08-11** | Added `task_logs.rationale` (nullable `Text`, migration `040_task_logs_rationale.py`) — the first typed rationale/reasoning column in the schema (`extra_data` remains generic/untyped JSONB used for ~30+ unrelated purposes). `append_log()` (`app/db/repository.py`) gained an optional `rationale` kwarg (every existing caller unaffected). Wired to a real source: `FleetManager.select()`'s `DispatchPlan.reason` (`app/fleet/fleet_manager.py:195-203` — a real, already-computed "capability=X, score=Y, health=Z" string) was being discarded at its one call site in `manager.py`'s subtask dispatch; now persisted via `append_log(..., category="agent_dispatch", rationale=dispatch_plan.reason)` and surfaced through both `GET /api/tasks/{id}/logs` (`_log_to_dict` now includes `rationale`) and the new `/explain` endpoint's `agentDispatchDecisions` list. |

**§44 overall: YES.** Both the DB-schema gap and the synthesis-endpoint gap are closed, built from real, already-computed data — no new fabricated signal was introduced.

---

## §45 Multi-Session Continuity

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Context persists across app restart | **YES — corrected 2026-08-11** | This batch's original NO/PARTIAL for chat state was itself stale: `chat_agent.py` migrated to a real `AsyncPostgresSaver` checkpointer in AUDIT_Q_BATCH08 §14 (`init_chat_checkpointer()`/`close_chat_checkpointer()`, wired into `app/main.py`'s FastAPI lifespan at startup/shutdown) — the migration was real and already live; only this file's **top-of-file module docstring** (lines ~43-50) still described the old in-process `MemorySaver` design, which is what the original audit pass evidently read instead of the actual init function. Docstring corrected in this pass to describe the real Postgres-backed mechanism, with `MemorySaver` correctly noted as the module-level default / fallback-on-init-failure only. DB task/epic state was already durable and unaffected. |
| Branch-context tracking after switching branches | **PARTIAL — genuine scope note, not a defect** (unchanged) | `DevTask.branch_name` persists the per-task **isolation worktree branch** (`agent/task-{id}`, set once at git-push time) — real, but there is no "which branch was the user last on" concept for the main repo anywhere in the codebase, and inventing one is a distinct, larger feature outside this batch's scope (no existing mechanism to reuse, unlike every other row in this batch). |

**§45 overall: YES for durable continuity** (task/epic DB state and now-confirmed chat LangGraph state); the remaining branch-tracking row is an honest scope boundary, not a bug.

---

## §52 Large Context Understanding

*(unchanged from the original pass — already the strongest-evidenced mechanism in this audit; re-verified, no regressions introduced by this batch's other changes, confirmed by the full test suite.)*

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Condensation trigger | **YES** | `_select_messages_to_condense` fires on a combined gate: `tokens_in > token_budget` **and** `len(messages) > 4` — both conditions required, not either alone. |
| Compression method | **YES — real LLM summarization, not truncation** | `_summarize_dropped_messages` calls Haiku with an explicit "preserve specifics" instruction over the dropped-message excerpt, splices the result back as a synthetic message. Structurally protects the first message and last 4 messages from ever being dropped. On summarization failure, returns an honest placeholder string rather than silently losing content or fabricating a summary. |
| Applied to chat_agent conversations too | **YES** | `chat_agent.py::_condense_history_async` directly reuses `base_graph.py`'s trigger logic and applies the same head/dropped/tail boundary with its own async summarization call — genuinely shared logic, not a reimplementation that could drift. |
| Multiple repos/documents in one context | **NO — genuinely out of scope** | Every relevant model and function signature uses a single `repo_path: str`; no list/multi-repo support anywhere. A distinct, much larger feature (multi-repo indexing, context assembly, and conflict resolution across repos) — not a fixable gap within this batch. |

**§52 overall: YES for single-repo context management.** Multi-repo support remains a distinct, larger feature, correctly left as NO rather than papered over.

---

## §65 Token & Context Budget Management

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Check against the model's real context limit (not just cost budget) | **YES — gap-closure 2026-08-11** | `TIER_CONTEXT_WINDOWS`/`context_window_for()` (`app/fleet/model_router.py`) previously had zero production callers. Now wired into both real call paths: `base_graph.py::_make_call_llm_node` resolves `_real_context_window = get_model_router().route(role_name).context_window` once at graph-build time (same pattern as the existing `_thinking_budget` resolution) and gates the actual LLM call — `if tokens_in_so_far >= _real_context_window:` hard-stops (mirrors the existing `max_tokens_per_agent_run` preventive-stop pattern exactly: same `health_updated`/`publish` event, same `{"submitted": True, "status": "blocked"}` return shape) **before** the Anthropic API call, not after a failure. `chat_agent.py::_call_llm_node` gets the equivalent check via `context_window_for("coder")` (the real agent-model-table entry for `settings.model_coder`, the model chat actually calls) and returns `{"stop": True, "last_error": ...}` with a pushed `error` event. Both checks are independent safety nets *below* the existing `context_token_budget` condense-trigger threshold (default 8000, tier windows are 200k-1M) — they only fire if that setting is ever misconfigured above the real ceiling, exactly the scenario this checkpoint asked to be caught. |
| Warn user when approaching limits | **YES** (unchanged) | `approaching_limit` SSE event fires at a real 80%-99.9%-of-budget threshold, confirmed live in both `base_graph.py` and `chat_agent.py`. |

**§65 overall: YES.** The previously-dead `TIER_CONTEXT_WINDOWS` mechanism is now a live safety net in both agent execution paths, reusing the exact preventive-stop pattern this codebase already established for token-budget enforcement.

---

## §101 Economic Awareness

Pre-execution estimate coverage (same real nodes as §42):

| Dimension | Verdict | Evidence |
|---|---|---|
| Token usage | **YES** (unchanged) | `estimated_tokens_in/out`. |
| API cost | **YES** (unchanged) | `estimated_cost_usd`, real gating threshold. |
| Execution time | **YES** (unchanged) | `estimated_duration_seconds`, historical-average-based with a config fallback. |
| Storage impact | **YES** (unchanged) | Real disk-space projection vs. actual free disk, in `_resource_check_node`. |
| Compute requirements | **YES — gap-closure 2026-08-11** | RAM: real projected-vs-available check (unchanged). CPU previously had only static presence/count probing. Added a real projected-load comparison: `ResourceCheckResult.projected_concurrent_cpu_demand` (`app/fleet/resource_check.py`) compares the app's own `max_concurrent_agent_runs` setting (the real, configurable ceiling on concurrent agent execution) against the real live `cpu_count`, and — for the first time — actually uses the previously-dead `cpu_percent` probe in the resulting message. **Deliberately informational-only** (feeds `recommendations`, never `reasons`/`sufficient`): unlike RAM/disk, CPU oversubscription degrades throughput rather than causing a hard failure, and `max_concurrent_agent_runs`'s default (20) exceeds this very dev machine's real core count (6) — gating epic start on it would have been a real functional regression on ordinary dev hardware, not a genuine safety net. Confirmed live via `test_default_thresholds_are_satisfied_on_this_dev_machine`, updated to assert the new advisory fires exactly as expected while `sufficient`/`reasons` are untouched. |

**§101 overall: YES — all 5 dimensions now have real, evidence-backed pre-execution projections.** CPU's is intentionally advisory rather than gating, for the safety reason documented above, not because the underlying signal is fake.

---

## Summary — Batch 13 (20 checkpoint rows across 7 sections)

- **YES:** 18
- **PARTIAL:** 1 (branch-context tracking — genuine, documented scope boundary)
- **NO:** 1 (multi-repo context — genuine, documented larger feature, out of this batch's scope)

**Real changes made this pass:**
1. `app/pipeline/cost_controller.py` — `CostEstimate.cost_per_subtask_usd`/`max_subtasks_within_threshold`; `app/agents/manager.py::_cost_estimate_node` now builds and — a real pre-existing bug fixed in the same edit — actually **persists** the cost-approval halt reason to `Epic.halt_reason` (previously never set on this path at all).
2. `app/agents/qa.py`, `app/agents/reviewer.py`, `app/agents/pm.py` — real `confidence` propagated from the shared planner's already-computed `final_state["confidence"]` to `QAResult`/`ReviewResult`/`pm_brief`, exposed via existing artifact/API/event-bus channels.
3. `app/db/models.py` (`TaskLog.rationale`), migration `040_task_logs_rationale.py`, `app/db/repository.py::append_log()`, `app/agents/manager.py` (persists `FleetManager.select()`'s real dispatch rationale), `app/api/tasks.py` (new `GET /{task_id}/explain` synthesis endpoint, `_log_to_dict` now includes `rationale`).
4. `app/agents/chat_agent.py` — corrected a stale module docstring describing an already-superseded `MemorySaver`-only design; no functional change needed (the real Postgres migration was already live).
5. `app/agents/base_graph.py`, `app/agents/chat_agent.py` — wired the previously-dead `context_window_for()`/`TIER_CONTEXT_WINDOWS` into a real preventive stop before the Anthropic API call, reusing the existing `max_tokens_per_agent_run` preventive-stop pattern.
6. `app/fleet/resource_check.py`, `app/agents/manager.py::_resource_check_node` — real, informational-only projected-CPU-load advisory (`max_concurrent_agent_runs` vs. real `cpu_count`), putting the previously-dead `cpu_percent` probe to use without introducing a regression risk on real dev hardware.

**Verification:** full backend suite (4032 passed / 51 skipped / 17 deselected), `ruff check .`, `black --check .`, `mypy app/ --strict --ignore-missing-imports` all green; migration 040 applied to the live dev DB; `/explain` endpoint smoke-tested end-to-end against a real task row.
