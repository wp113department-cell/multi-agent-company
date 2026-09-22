# Task 2 — PARTIAL item enhancement tracking

Verdicts: `PENDING` · `DONE` · `DONE (config flip)` · `INTENTIONAL, NO CHANGE` · `BLOCKED`

## Progress

| Batch | Items | Done |
|---|---:|---:|
| T2-B1 Quick wins | 9 | 0 |
| T2-B2 Worker pause/resume/checkpoint | 7 | 0 |
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
| 212 | Pause/resume execution for plain worker agents | PENDING | |
| 213 | Understand follow-up replies / continue prior context (worker agents) | PENDING | same as #212 |
| 234 | Recovery after crash (full state) | PENDING | |
| 235 | Recovery after reboot (auto-resume worker runs) | PENDING | needs #212 |
| 236 | Continue from checkpoint if interrupted (all agent types) | PENDING | needs #212 |
| 238 | Python backend crashes - full state recovery | PENDING | needs #212+#234 |
| 246 | Checkpointing / Resumability (all agent types) | PENDING | needs #212 |

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
