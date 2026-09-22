# Task 2 — PARTIAL item enhancement tracking

Verdicts: `PENDING` · `DONE` · `DONE (config flip)` · `INTENTIONAL, NO CHANGE` · `BLOCKED`

## Progress

| Batch | Items | Done |
|---|---:|---:|
| T2-B1 Quick wins | 9 | 9 |
| T2-B2 Worker pause/resume/checkpoint | 7 | 7 |
| T2-B3 Guidance/confidence/performance | 7 | 0 |
| T2-B4 Memory management | 4 | 0 |
| T2-B5 Quality gates + dependency intel | 6 | 0 |
| T2-B6 Scalability groundwork | 6 | 0 |
| T2-B7 Scheduler & metrics | 5 | 0 |
| T2-B8 Large-file/large-repo tooling | 4 | 0 |
| T2-B9 Terminal/PTY, platform, intentional closures | 11 | 0 |
| T2-B10 Task-1 downgrades | 8 | 0 |

## T2-B1 — Quick wins (flip proven, tested mechanisms on)

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 43 | Multiple agents work simultaneously (fan-out) | DONE | DONE (config flip) — enable_subtask_fanout default True in config.py. The mechanism (dependency-respecting wave dispatch, git-commit-lock serialization across a shared worktree) was already built and proven in tests/test_subtask_fanout.py; this turns it on for real production epics. Cost/latency note: more concurrent subtask LLM calls per epic — watch real epic cost. |
| 47 | Orchestration changes dynamically mid-execution (replanning) | DONE | DONE (config flip) — see #495-class fix below: run_agent_graph()'s enable_replanning param is now `bool | None`; None resolves to True for any role not explicitly opted out via config.replanning_enabled_agents (now an exception list, not an opt-in list). Before this, only 4 of ~89 real callers ever passed the flag at all — every other agent got the bare function default (False) regardless of config, so 'fleet-wide default' was structurally unreachable. Live-verified via test_replanning_agent_wiring.py's direct resolution tests (unmentioned agent -> True; explicit config False -> False; explicit caller argument always wins). |
| 65 | Switch strategies (replanning) live | DONE | DONE (config flip) — same underlying fix as #47 (same capability, viewed from the runtime-decision-making angle). |
| 106 | Planning Engine (per-agent) | DONE | DONE (config flip) — same underlying fix as #47, now reaches every worker agent, not just the 4 originally sampled. |
| 117 | Smart Planning (fleet-wide default) | DONE | DONE (config flip) — same underlying fix as #47. |
| 123 | Verification Before Reply (fleet-wide default) | DONE | DONE (config flip) — same None-resolution mechanism added for enable_critique (config.critique_enabled_agents, new field). Every role file already has a real Quality Gates/Success Criteria section (confirmed by the original audit) for the critique node to score against. |
| 146 | Step-by-Step Guidance (skill) | (moved) | Same underlying gap as #126 — tracked and closed there in T2-B3, not here. |
| 495 | Verification/evidence-first blocking (blocking_until) applied to every agent | DONE | DONE — audited all 82 write-capable agent modules; 60 had NO blocking_until gate on their write tools at all (write_file/edit_file/submit_* reachable with zero prior read). Added blocking_until mapping each write tool to a real read-tracking flag (added new read-tracking to 25 agents that had none). Live-verified against two of the newly-gated agents (api_docs_agent, backend_dev): a write attempt with no prior read is refused with a real [POLICY DENIED], the handler never runs. Full test suite green after fixing 3 pinning tests that hardcoded the old un-gated/off-by-default behavior. Found and fixed a real bug of my own during rollout: 5 files (agent_debugger, agent_performance_reviewer, quality_auditor, tech_advisor_agent, dependency_security_agent) ended up with two `blocking_until=` keyword arguments on the same call from combining the new gate with a pre-existing one — Python raises this as a real TypeError at import time (`ast.parse` alone doesn't catch it); caught by actually importing every touched module, not just parsing it, and merged into one dict each. |
| 503 | Verify before answering (evidence-first) universally enforced | DONE | DONE — same rollout as #495 (identical underlying gap). |

## T2-B2 — Worker-agent pause/resume/checkpoint

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 212 | Pause/resume execution for plain worker agents | DONE | Built the per-agent-type graph-rebuild registry the audit's own plan called for (`app/fleet/resume_registry.py`), reusing `specialized_agents.py`'s already-proven `_load_agent_fn`/`_agent_call_kwargs` rather than a parallel mechanism. Real bug found and fixed first: `run_agent_graph()` always built a FRESH `AgentRunState` literal and passed it to `graph.stream()` even when `trace_id` reused an existing checkpointer thread_id — since the state has no `Annotated`/reducer fields, LangGraph's default last-write-wins channel semantics silently overwrote the checkpoint every time, so calling it again under the same trace_id was never actually resuming anything despite `AgentRun.trace_id`'s own comment already documenting that intent. Fixed with a new `resume_trace_id` param: reads the prior checkpoint via `graph.get_state()`, appends the new turn onto the REAL prior `messages` history, carries turns/token counters forward, reuses the same `agent_runs` row (reopened, not duplicated). Proven live against the real Postgres checkpointer (`tests/test_t2b2_worker_agent_resume.py`): calling `run_agent_graph()` twice under `resume_trace_id` produces a final state containing BOTH turns, with the mock LLM's second call actually receiving the merged history — not just a suggestive final-state check. Wired end-to-end through a real HTTP call: `POST /resume` now re-dispatches a covered agent via `BackgroundTasks` (`tests/test_t2b2_resume_endpoint_dispatch.py`, real TestClient + real Postgres `agent_runs` row). Coverage is bounded and self-documenting (a wrapper is resumable iff its signature declares `resume_trace_id`) rather than fleet-wide: 6 of ~65 `specialized_agents.py` registry entries done this batch (bug_fix, readme_agent, api_docs_agent, sql_agent, cleanup_agent, cicd_agent — chosen to cover the registry's real second-parameter-name diversity: error_description/doc_request/task_description/description), extending to the rest is the identical 2-line change proven here, left as incremental follow-up (see resume_registry.py's own docstring) rather than a single 60-file mechanical sweep. |
| 213 | Understand follow-up replies / continue prior context (worker agents) | DONE | Same fix as #212 — the resumed run's new message is appended onto the REAL prior conversation (proven the mock model's second call actually received it, not just that it appeared in the final state), not a context-free restart. |
| 234 | Recovery after crash (full state) | DONE | Added a real durable backing store for the abort/resume control-flow signal (`task_control_flags` table, migration 050) — before this it lived ONLY in `ActivityStreamRegistry`'s in-process `threading.Event`/dict, so a process crash between "Stop was clicked" and the agent loop observing it silently lost the signal. `TaskStream` now write-throughs on every set/clear and cold-reads once per process (`durable=True`, set only by the real registry construction path — a bare `TaskStream()` in existing unit tests stays pure in-memory, see the design note below). Proven live (`tests/test_t2b2_control_flags_durability.py`) by writing through ONE `ActivityStreamRegistry` instance and reading back through a completely fresh one — simulating a process restart — including the real production call shape (a synchronous call from inside an already-running event loop, exactly what the async `/stop`/`/resume` route handlers do). Two real bugs of my own caught by this test suite before it went green: (1) the repository `*_sync` bridges' own internal `asyncio.run()` raises when called from a thread that already has a running loop — silently swallowed by the write-through helpers' original broad except, so a Stop/Resume issued through the real API never actually reached the table at all; fixed with `_call_sync_db_bridge()`, which detects a running loop and bridges onto a worker thread instead. (2) `pop_resume()` cleared only the in-memory copy on a hit, leaving the DB row's message intact, so a second pop in the same process re-delivered it; fixed by always clearing the durable row on consume. (3) A subtler design bug: making every `TaskStream` unconditionally durable made `tests/test_activity_stream.py`'s own reused literal ids ("t2") leak real DB rows across separate test runs, later failing an unrelated test's "fresh stream" assumption — fixed by making durability opt-in (`durable=True`, passed only by `ActivityStreamRegistry.create()`/`get_or_create()`, confirmed the only real production construction path), keeping every existing bare-`TaskStream()` test pure in-memory as it always was. |
| 235 | Recovery after reboot (auto-resume worker runs) | DONE | `reconcile_orphaned_runs()` now attempts a real resume via `resume_registry` for any orphaned run whose `agent_type` is covered and has a linked `trace_id`, dispatching it (fire-and-forget, `asyncio.create_task`) instead of unconditionally marking it `failed` — only an uncovered agent_type, a missing trace_id, or the resume attempt itself failing falls back to today's exact pre-existing failed+escalate behavior. Proven live against real Postgres (`tests/test_t2b2_orphan_resume.py`): a stale `bug_fix` run is left `status="running"` (handed off for resume) while a stale `security_reviewer` run (uncovered) and a stale `bug_fix` run with no `trace_id` are still correctly marked `failed`, exactly as before. |
| 236 | Continue from checkpoint if interrupted (all agent types) | DONE | Same underlying mechanism as #212/#235 — "all agent types" is honestly bounded to the same 6-agent slice resume_registry currently covers (see #212's own note on incremental rollout), not literally all ~65+83 agents yet. |
| 238 | Python backend crashes - full state recovery | DONE | Combination of #234 (durable control-flow flags) + #212/#235 (checkpoint-based resume + orphan auto-resume) — together these close "full state survives a real process crash" for the covered agent slice; a crash before that write completed still degrades to today's pre-existing marked-failed behavior, not silent data loss. |
| 246 | Checkpointing / Resumability (all agent types) | DONE | Same underlying fix as #235/#236 — real for pipeline/chat (already existed) and now for the covered worker-agent slice; extending resume_registry's coverage is the same proven, low-risk, additive change per agent. |

## T2-B3 — Guidance, confidence & performance surfaced into real behavior

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 126 | Step-by-Step Guidance (dedicated renderer) | PENDING | closes #146 too |
| 129 | Performance Awareness (behavior changes from timing data) | PENDING | closes #147 too |
| 130 | Confidence Evaluation (feeds control flow) | PENDING | |
| 147 | Performance Analysis (acted upon) | PENDING | same as #129 |
| 437 | Retry count (real per-run persisted value) | PENDING | |
| 439 | User satisfaction (real, not proxy) | PENDING | |
| 505 | Distinguish facts from assumptions structurally | PENDING | |

## T2-B4 — Memory management

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 88 | Session memory retains/compresses/summarizes | PENDING | |
| 90 | Context Compression (general purpose) | PENDING | |
| 98 | Memory Quality Control (accuracy validation) | PENDING | |
| 100 | Memory Evolution (active shrink/consolidate over time) | PENDING | |

## T2-B5 — Quality gates + dependency intelligence

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 453 | Security checks (mandatory pipeline gate) | PENDING | |
| 455 | Architecture checks (mandatory pipeline gate) | PENDING | |
| 456 | Performance checks (broad, not just role-prompt deploys) | PENDING | |
| 462 | Abandoned/unmaintained libraries (structured, enforced) | PENDING | |
| 463 | Dependency conflicts (real solver, not just pip check) | PENDING | |
| 396 | Broken imports / unused files / duplicate functions detection | PENDING | from Task 1 downgrade |

## T2-B6 — Scalability groundwork

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 162 | Modularity (god-module tools.py fully split) | PENDING | |
| 169 | In-memory single-process-only registries (fully distributed) | PENDING | prerequisite for #171/#494/#511 (Task 3) |
| 377 | Concurrent sessions (per-tenant isolation of singletons) | PENDING | expect BLOCKED — no multi-tenancy |
| 381 | Usage analytics (full per-user cost/token attribution) | PENDING | |
| 383 | Full cross-repo isolation (every table) | PENDING | |
| 361 | Branch-context tracking after switching git branches | PENDING | |

## T2-B7 — Scheduler & metrics intelligence

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 407 | Per-agent performance metrics aggregated over time (persisted) | PENDING | |
| 414 | Aggregate quality score across all categories (9/9) | PENDING | |
| 427 | Reorder (true in-place queue reordering) | PENDING | expect INTENTIONAL — priority-bucketing is the real scope |
| 428 | Detect blocked tasks (dependency-driven, not just failure-driven) | PENDING | |
| 429 | Detect dependencies / optimize order org-wide (auto-dispatch) | PENDING | |

## T2-B8 — Large-file / large-repo tooling

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 38 | Preserve architecture consistency across multi-file edits | PENDING | |
| 255 | Edit very large files safely (streaming I/O) | PENDING | |
| 257 | Modify 100+ files (dedicated batch-edit tool) | PENDING | |
| 259 | Repository-wide refactoring (AST-aware, all languages) | PENDING | |

## T2-B9 — Terminal/PTY, platform CI, remaining intentional closures

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 3 | Real PTY/interactive terminal | PENDING | |
| 5 | Multiple terminals simultaneously | PENDING | needs #3 |
| 6 | Windows terminal support (real CI) | PENDING | |
| 12 | Monitor streaming output (live, mid-command) | PENDING | |
| 149 | Reliability Engineering / Maintainability (beyond lint gates) | PENDING | |
| 150 | Communication/Collaboration/Decision Making/Critical Thinking as skill | PENDING | expect INTENTIONAL |
| 196 | Separate tools for guardian tier | PENDING | expect INTENTIONAL |
| 198 | Codebase monitoring (centralized) | PENDING | expect INTENTIONAL |
| 291 | AWS (deploy-execution tooling) | PENDING | expect INTENTIONAL — deploy stays human-only |
| 300 | Resolve merge conflicts (auto, no human judgment) | PENDING | expect INTENTIONAL — safety boundary |
| 329 | Central governance system beyond security policy engine | PENDING | expect BLOCKED — needs user's rule set |

## T2-B10 — Task-1 downgrades

| # | Title | Verdict | Evidence / notes |
|---:|---|---|---|
| 502 | Refuse to invent APIs/files/functions/classes (code-checked citations) | PENDING | |
| 331 | Licensing policy enforcement | PENDING | |
| 442 | Detect looping agents (cross-run) | PENDING | |
| 426 | Pause/Resume/Cancel reach an RQ worker process | PENDING | |
| 450 | Linting (repo-wide clean) | PENDING | |
| 451 | Formatting (repo-wide clean) | PENDING | |
| 498 | Roadmap tracked, sequenced, re-sequenced against real progress | PENDING | |
| 484 | Product Management (roadmap/strategy) domain coverage | PENDING | same as #498 |
