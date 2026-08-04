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

- Q1: remaining POSIX-only shell patterns (`source .venv/bin/activate`) not yet ported to the
  Windows branches.
- Q2: `DevTask.priority` not DB-enforced (ties into Cluster K, but the flag-only part is cheap).
- Q4: no automatic tool-level retry wrapper (retry currently only at the agent-run level).
- Q6: `enable_critique`/`enable_replanning` not universal — currently opt-in for 5 highest-risk
  agents only; decide whether to widen.
- Q7: no sentiment/satisfaction-detection code anywhere.
- Q17: `docker_logs` returns raw output only — no structured parsing/pattern-detection layer.
- Q20: `web_search`/`fetch_url` are scoped to `research_agent` only, not fleet-wide.
- Q42: no "recommend a cheaper approach" step (estimate exists, recommendation doesn't).
- Q43: `RunMetrics.confidence` is self-reported by the LLM, never independently verified.
- Q66: exponential backoff not re-confirmed this pass (prior-session claim, not re-derived) — a
  one-day verification task, not a build task.
- Q66: transaction-boundary/rollback-on-exception correctness not reviewed across all DB writes —
  also verification, not build.
- Q92: "detect abandoned libraries" not confirmed as distinct from "outdated" — verification task.
- Q95: `repo_id` threading at every `query_*`/`embed_*` call site — verification task (same item
  as Cluster L, listed here because it may resolve to "already fine" on inspection, not a build).
- Q102: `on_heartbeat()` confirmed wired in `base.py`'s path, not confirmed wired into the main
  `base_graph.py::run_agent_graph()` path every other agent uses — verification, likely a 1-line fix
  if actually missing.
- Q117: no unified cross-category quality score (architecture/prompts/tools/docs/tests/security) —
  aggregation layer over data that mostly already exists (`benchmark_manager.py`,
  `dependency_security_agent`, test counts).
- Q119: CEO Dashboard doesn't surface active-agent status/tech-debt/security-warnings together —
  the underlying data exists scattered; this is a dashboard-wiring task, not new data collection.

---

## Suggested staging order (preliminary — confirm after a baseline-verification pass)

Following `PLAN.md`'s own philosophy (root causes and cheap wins first, architecturally heavy work
gets dedicated days instead of being bundled):

1. **Tier 3 cheap items** first — same rationale as original Stage 0: fast, testable, builds
   momentum, and a few of these may turn out to already be fine on inspection (verification-only
   items), shrinking the backlog before the big build starts.
2. **Cluster C (agent lifecycle/selection)** and **Cluster D (self-improvement completeness)** —
   these extend `FleetManager`/`failure_ladder.py`, code you already have deep familiarity with
   from Stage 0-2.
3. **Tier 1 items #8, #9, #12** (pattern recognition / tool evolution / capability-gap detection)
   together — they share one aggregation layer.
4. **Cluster F (file formats)**, **Cluster G (WebSocket)**, **Cluster I (deployment)** — mostly
   additive, low architectural risk.
5. **Cluster H, J, K, L, M** — medium items, sequence flexibly.
6. **Tier 1 remaining items (#1-7, #10, #11)** — the standalone new subsystems.
7. **Cluster A (cross-process scale) and Cluster B (agent-to-agent collaboration)** — deliberately
   last: these are the two largest, highest-risk architectural changes (per `answer2.md`'s own
   "Critical blockers" list), and every other cluster above touches code that becomes more complex
   to change once agents can talk to each other or run across multiple processes.

**Before locking this into day numbers**: repeat `PLAN.md`'s Day-1 baseline pass — grep the actual
call-site counts / current state for each cluster (the same discipline that turned "~75 file-count
figure" into "exactly 8 call sites" for the original Stage 0). Sizes above (S/M/L/XL) are
`answer2.md`-informed estimates, not fresh measurements.

---
*Compiled 2026-08-03 from `answer2.md`'s 120-question strict audit. Every item above traces to a
specific Q# and named gap in that file — no item here was invented for this document.*
