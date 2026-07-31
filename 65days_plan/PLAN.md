# Gridiron Production-Readiness Gap Closure — Day-Wise Implementation Plan

> Copied into the repo on 2026-07-31 (Day 34) from local Claude Code plan storage
> (`~/.claude/plans/melodic-gliding-moore.md` on the original Windows machine) so it survives a
> machine/OS switch. This is the authoritative source for what "the plan" means throughout
> `IMPLEMENTATION_PROGRESS.md` and `answers.md` in this same folder.

## Context

`Questions_implement.md` (written from `answers.md`'s 120-question / 811-sub-answer audit) defines
4 stages of work: Stage 0 (3 root-cause clusters + 6 cheap fixes, ~20 sub-answers), Stage 1 (255
PARTIALs across 7 sub-buckets), Stage 2 (80 "should fix soon" items across 7 categories), Stage 3
(43 NOT VERIFIED items needing measurement), and a SKIP list (97 items, untouched unless requested).

That document is a correct, well-evidenced *scope* — it is not yet a *schedule*. The user wants a
concrete day-by-day plan where every day has one bounded, independently-testable deliverable, so
that "is anything missing" can always be answered by re-running evidence, not by re-reading intent.
That requirement — provable completeness, not claimed completeness — shapes everything below: a
fixed Definition of Done applied identically to every day, and a standing Gap Audit Protocol the
user can invoke at any point (not just at the stage boundaries where it's scheduled by default).

Baseline confirmed directly against the current repo before writing this plan (not assumed from
`Questions_implement.md`'s estimates):
- `get_active_repo_path()` — the global-fallback repo-scoping problem — has exactly **8** call
  sites, not the ~75 file-count figure `answers.md`'s J-cluster report used for a different,
  broader "repo_path" grep. Root-cause 1 (memory/repo scoping) is smaller than it may have read.
- **76 of 78** agent modules have no checkpointer reference at all — confirms Stage 1.3's
  "~70 worker agents lack durable checkpointing" claim almost exactly, and confirms the fix
  belongs in the **shared** `base_graph.py`/`build_agent_graph()` (which ~74 of those 76 route
  through), not 76 separate per-agent implementations.
- `enable_critique=True` / `enable_replanning=True`: **zero** matches anywhere in `app/agents/*.py`
  — Stage 1.1's "0/72 agents have this enabled" claim is exact, not approximate.
- `app/pipeline/cost_controller.py` already exists and is the right shape to extend for Stage 2's
  resource/size pre-flight work (historical-average-from-`agent_runs` + config-fallback +
  approval-gating) — reuse this pattern, don't build a parallel one.
- 765 test functions currently exist in `backend/tests/` — this is the baseline count Day 1 formalizes.

**One honest correction to `Questions_implement.md` before work starts:** Stage 0's "cheap,
high-leverage" bucket lists bash-tool sandboxing (container/chroot/AppContainer) alongside genuinely
cheap one-line fixes (CVE patch, missing migration). Sandboxing is not cheap — it's its own scoped
sub-project (pick a mechanism, prototype it, wire it into `policy/engine.py`, prove escape attempts
are actually blocked). This plan gives it 2 dedicated days instead of bundling it with the 1-day
cheap-fix batch, so it doesn't get rushed or silently descoped under time pressure.

---

## Definition of Done — applies to every single day below, no exceptions

A day is only marked complete when **all six** are true:

1. **Baseline diff** — full backend (`pytest`) and, if touched, frontend test suite run *before*
   the change and again *after*. Exact pass/fail/skip counts recorded both times. Any test that was
   passing and now fails is a blocker — fix the change, never the test.
2. **Smallest change that satisfies the item** — no drive-by refactors.
3. **New or updated test proves the specific item now works** — not just "suite still green." No
   test, no YES.
4. **`answers.md` updated** — the specific sub-item's verdict flipped to YES (or explicitly left at
   its current verdict with a note, if the day's work was partial), replacing the old Plan/gap note
   with `file:line` + test-name evidence, same citation style as the rest of the document.
5. **`IMPLEMENTATION_PROGRESS.md` updated** the same way the existing entries already are (what
   changed, why, evidence, regression numbers).
6. **Evidence report delivered**: files touched, exact before/after test counts, new verdict(s), and
   — for any day marked ⚠ below — explicit confirmation that go-ahead was given before code was
   written.

Days marked **⚠ GO-AHEAD REQUIRED** touch schema, migrations, global state, or a fleet-wide default.

**Operating-mode update (2026-07-30, explicit owner instruction):** the owner waived the per-⚠-day
stop-and-wait — "no need to give my permission... start when prior day completes." From Day 2
onward, ⚠ days proceed automatically once the prior day's Definition of Done is fully met, instead
of pausing for a text go-ahead. Nothing else about the Definition of Done changes: full regression
before/after, smallest change, a real test, `answers.md`/`IMPLEMENTATION_PROGRESS.md` updated, and
an evidence report every day — and the Gap Audit Protocol remains invokable by the owner at any
time. The ⚠ marker itself stays in this document as a visibility flag (which days are
schema/global-state/fleet-default-affecting), it just no longer blocks execution.

**Operating-mode update (2026-07-31, explicit owner instruction):** stage-to-stage progression is
NOT automatic — the owner explicitly stops the plan at each stage boundary ("no need to move stage
2 ok be ready for this... i will tell you then move it") and gives an explicit go-ahead before the
next stage starts, even though ⚠-day-level pauses within a stage remain waived per the above. Check
`IMPLEMENTATION_PROGRESS.md`'s latest entry for the current status before assuming it's OK to
proceed past a stage boundary.

---

## Gap Audit Protocol — how "what's missing" gets answered honestly, any time it's asked

This is a standing procedure, invokable at any point during or after implementation (not only at
the scheduled stage-end checkpoint days below). When invoked, it does NOT trust prior "done"
reports — it re-derives them:

1. List every sub-item claimed YES since the last audit (from `answers.md`'s diff / the day-by-day
   evidence reports).
2. For each: re-run its cited test right now. Re-read its cited `file:line` against current code —
   confirm it still says what the citation claims (code drifts; citations can go stale).
3. Run the full regression suite and diff against the last recorded baseline count — flag anything
   that regressed silently.
4. Anything that fails re-verification is reverted to its honest prior verdict (PARTIAL/NO) in
   `answers.md`, not left at a stale YES.
5. Produce a report: **X of Y claimed items independently re-confirmed; Z items found regressed or
   incomplete**, each with fresh `file:line` evidence — the same standard the original 12-pass audit
   that produced `answers.md` was held to.
6. Close any real gaps found *before* resuming the next scheduled day.

This is what makes "I did this with 0 missing" a checkable claim instead of an assertion — at any
checkpoint, re-running this protocol either confirms it or produces a specific, evidenced punch
list. Nothing is ever "probably fine."

**Operating cadence agreed with the user**: the 4 built-in checkpoint days (10, 34, 57, 65) are the
floor, not the schedule — the user will invoke this protocol roughly **weekly** regardless of which
day the plan is on. Treat every such request as a real re-verification, not a status summary.

---

## Stage 0 — Days 1-10: Correctness & Safety (MUST FIX, blocks everything else)

| Day | Deliverable | Key files | Acceptance test | `answers.md` items closed |
|---|---|---|---|---|
| 1 | Baseline only — no code. Full read of `answers.md` + `IMPLEMENTATION_PROGRESS.md`; run full backend + frontend suites; record exact counts. | — | Baseline snapshot recorded in the Day-1 evidence report | — |
| 2 ⚠ | Root cause 1a: add `repo_id`/`project_id` nullable column + migration to `MemoryEmbedding` and `VersionedLesson`. | `backend/app/db/models.py`, new `backend/migrations/versions/0XX_*.py` | Migration up/down test; existing rows backfill to a `legacy/unscoped` sentinel, not dropped | — |
| 3 | Root cause 1b: filter every `query_*` in `app/memory/store.py` by `repo_id`/`project_id`. | `backend/app/memory/store.py` | Test: Project A's memory query never returns Project B's rows (real DB, two seeded repos) | Q5, Q114 (Project Memory) |
| 4 ⚠ | Root cause 1c: remove the `_active_repo_path` global fallback at all 8 `get_active_repo_path()` call sites; thread per-request/session repo context explicitly instead. | `backend/app/api/repo.py` + the 8 call sites | Concurrency test: two repos activated back-to-back with in-flight dispatches, each dispatch proven to use the repo active at *its own* request time | Q51, Q94, Q95 |
| 5 | Root cause 2: gate `delete_file`/`write_file`/`edit_file`/`append_file`/`rename_file`/`copy_file` + dependency-manifest edits behind `self._confirm()`, mirroring the existing `git_push`/`git_reset --hard` pattern. | `backend/app/agents/chat_agent.py`, `backend/app/agents/dependency_agent.py` | Test mirroring `test_denied_git_push_never_runs`: denial genuinely blocks the write, approval genuinely allows it, exactly once | Q39 (delete/overwrite/dependency-upgrade gating) |
| 6 | Root cause 3: gate `versioned_memory.publish()` behind a confidence threshold or `knowledge_curator`-mediated review before a lesson reaches `published`. | `backend/app/fleet/versioned_memory.py`, `backend/app/agents/knowledge_curator.py` | Test: an unreviewed `record_learning` call cannot reach `state="published"` without either passing the threshold or curator approval | Q75, Q93 |
| 7 | Cheap-fix batch: mandatory credential encryption in prod profile (hard-fail if `CREDENTIAL_ENCRYPTION_KEY` unset); `ecdsa` CVE fix; missing `audit_log` migration; force live `pip-audit`/`npm audit` before `dependency_security_agent` CVE claims; archived-memory filter bug (`WHERE archived = false`). | `backend/app/security/credential_vault.py`, `backend/requirements.txt`, new migration, `backend/app/agents/dependency_security_agent.py`, `backend/app/memory/store.py` | `pip-audit` clean; new migration creates `audit_log` table and a write round-trips; archived rows confirmed excluded from `query_similar_tasks` | Q21 (credential enforcement), Q24 (CVE), Q96 (audit log), Q92 (live CVE check), Q120 (archived filter) |
| 8 | Sandbox design + prototype — pick a mechanism (container/seccomp/AppContainer, Windows-compatible), prove it isolates a real destructive command attempt in a standalone script before touching production code. | scratch/prototype only | Standalone repro script proves isolation | — |
| 9 ⚠ | Sandbox wiring — integrate the proven mechanism into bash-tool execution, replacing/augmenting the regex `cd`-boundary check. Changes execution behavior for every agent's bash calls fleet-wide. | `backend/app/policy/engine.py`, `backend/app/agents/tools.py` bash handlers | Test: a crafted command that bypasses the regex denylist is still blocked by the sandbox | Q21 (sandboxing) |
| 10 | **Stage 0 regression + Gap Audit Protocol run.** | — | All 4 Stage-0 acceptance criteria from `Questions_implement.md` re-verified live: cross-project memory test, concurrent-repo test, delete/overwrite confirmation test, unreviewed-lesson-blocked test, `pip-audit` clean, sandboxed bash proven | Stage 0 sign-off report |

---

## Stage 1 — Days 11-34: Convert the 255 PARTIALs

Each sub-bucket below already has something real to finish/wire/enforce — not build from zero.

| Days | Bucket | Deliverable | Key files | Acceptance |
|---|---|---|---|---|
| 11-14 ⚠ | 1.1 Agent intelligence defaults | Flip `enable_critique=True` for the 5 highest-output-risk agents (`coder`, `backend_dev`, `frontend_dev`, `qa`, `reviewer` — chosen by role, not by the existing `risk_level` tag, which marks *operational* danger, not *output-correctness* importance, and currently only covers `chat_agent`/`cicd_agent`/`docker_agent`/`manager`/`migration_agent`); before/after cost & latency measured, not blind. **Stop condition: the Day 11-14 cost/latency delta report is reviewed by the user before Day 15 starts — a large latency or cost jump stops the plan for a decision, it is not just logged and moved past.** Flip `enable_replanning=True` for the same tier once critique is stable and approved. Make `FleetManager.select()`'s score the actual dispatch decision in `manager.py` (currently a discarded side-channel). Topologically sort subtasks by `depends_on` before dispatch. | `backend/app/agents/{coder,backend_dev,frontend_dev,qa,reviewer}.py`, `backend/app/agents/manager.py`, `backend/app/fleet/fleet_manager.py` | Cost/latency delta report for the 5 agents; test proving `FleetManager.select()`'s output is what actually dispatches; test proving dependency order is honored |
| 15-17 | 1.2 Verification & trust | Turn `expected_verification` from tracked metadata into a real blocking check in `execute_tools`/`_execute_tool_node`. Parse the test runner's real exit code/summary into the verification flag instead of "tool ran cleanly." Add a "propose realistic alternative" step + temporary-vs-fundamental-limitation taxonomy when blocked. | `backend/app/agents/base_graph.py`, `backend/app/agents/chat_agent.py`, `backend/app/agents/tools.py` (`run_tests` handler) | Test: a write/bash call is actually refused when its declared read-flag is unset; test: a mock test run with real failing output sets the verification flag to `False`, not `True` |
| 18-23 ⚠ | 1.3 Reliability & durability (biggest single bucket) | Day 18: reproduce interrupt/checkpoint replay-safety for `base_graph.py`'s node shape with a standalone script first — same rigor this engagement already used for the `chat_agent.py` conversion, since `base_graph.py`'s nodes are structured differently and may hit the same "whole node replays" hazard. **Hard stop condition: if Day 18's repro finds a real replay-safety problem, Days 19-23 extend to however many days a safe per-node decomposition actually takes — do not compress back into the original 5-day window under schedule pressure.** Days 19-20: wire `AsyncPostgresSaver` checkpointing into `build_agent_graph()` (centralized — this is what makes 76 agents one change, not 76). Day 21: circuit breaker around Anthropic/Groq client calls. Day 22: persist background-process PIDs + session-close hook to terminate orphans. Day 23: fleet-wide regression (this change touches the shared graph builder — budget a full day for fallout). | `backend/app/agents/base_graph.py`, `backend/app/agents/tools.py` (`_session_bg_procs`) | Standalone repro script proving no duplicate side-effects across pause/resume (mirroring `test_confirmed_git_push_runs_exactly_once...`); circuit-breaker test (N consecutive failures → open); orphan-process test |
| 24-26 | 1.4 Frontend/backend robustness | `error.tsx` boundaries at top-level + major route groups; SSE reconnect-with-backoff on the task-activity stream; thread `authHeaders()` through every mutating call in `lib/api.ts`, not just one page; add UI-level role gating (courtesy, server already enforces) | `apps/web/app/error.tsx` + route groups, `apps/web/lib/api.ts`, `apps/web/app/stream/[taskId]/page.tsx`, `apps/web/components/NavBar.tsx` | e2e test: forced render error shows the boundary, not a blank crash; e2e test: killed SSE connection reconnects; test: mutating call carries the bearer token |
| 27-29 | 1.5 Context & token management | Model→context-window table; give `chat_agent.py`'s graph the same budget check `base_graph.py`'s `_trim_messages` already has; replace drop-oldest with a real LLM-summarization condense step; push `context_trimmed`/`approaching_limit` SSE event | `backend/app/agents/chat_agent.py`, `backend/app/agents/base_graph.py` | Test: a long conversation triggers summarization (content preserved in summary, not silently dropped); test: the SSE event fires at the configured threshold |
| 30-31 | 1.6 Requirement compliance & clarification | Explicit hard-constraint rule (stop + `request_clarification` on conflict instead of silent substitution) in `chat.md`/`_GLOBAL_STANDARDS.md`; explicit difficult-user/de-escalation section in `chat.md`; "check if already done" step before new work | `backend/roles/chat.md`, `backend/roles/_GLOBAL_STANDARDS.md` | Test: a scripted conflicting-tech-constraint prompt triggers `request_clarification`, not silent substitution |
| 32-33 | 1.7 Wire quality tools into CI | Invoke `regression_detector`'s baseline check before merge/deploy; run `tech_debt_agent` against PR diffs touching structural files | `.github/workflows/ci.yml`, `backend/app/fleet/regression_detector.py` | CI run demonstrably blocks a deliberately-regressed benchmark; CI run demonstrably triggers `tech_debt_agent` on a structural-file diff |
| 34 | **Stage 1 regression + Gap Audit Protocol run.** | — | Every sub-bucket's acceptance test re-run live; full report per bucket, not just an aggregate |

---

## Stage 2 — Days 35-57: "Should Fix Soon" (80 items, not blocking — do after Stage 0+1 verified)

| Days | Category | Deliverable | Reuse |
|---|---|---|---|
| 35-39 | Resource/cost/size pre-flight (22 items) | RAM/CPU/GPU/disk/Docker/Python/Node/CUDA/virtualization checks before expensive operations; runtime/size/time estimates before large tasks | Extend `app/pipeline/cost_controller.py`'s exact pattern (historical-average + config-fallback + approval-gate) — do not build a parallel module |
| 40-44 | Memory quality/prioritization/analytics (20 items) | Staleness handling, relevance ranking, dedup, frequency-of-reuse-based ranking (flagged in the original audit as the single largest concrete memory gap), retrieval-time metrics | `app/memory/store.py`, extends the `repo_id`-scoping work from Stage 0 Day 2-4 |
| 45-47 | Context compression beyond Stage-1 basics (15 items) | Dropped context summarized, not lost, across all remaining surfaces | Builds directly on Stage 1.5 |
| 48-50 | CI/architecture-drift/code-health gates (11 items) | Wire `architecture_reviewer`'s existing `dead_code_detect`/`circular_dep_detect` tools into a periodic or CI-triggered pass instead of on-demand only | `backend/app/agents/architecture_reviewer.py` — tools already real, just not scheduled |
| 51-53 | Merge-conflict resolution + doc generators (5 items) | Conflict-marker parsing + resolution-assist tool; architecture/agent/tool/migration-doc generators (same pattern as existing `readme_agent`/`api_docs_agent`); PR-body generation from the real diff, not the truncated task description | `backend/app/agents/readme_agent.py`, `api_docs_agent.py` as the template |
| 54 | Performance/latency instrumentation (4 items) | `record_tool()`-equivalent timing around planner/decomposer/scan/memory-retrieval | `backend/app/fleet/metrics.py` |
| 55-56 | Load/stress tests + CI/CD inspection step (3 items) | A real locust/k6 script against the FastAPI endpoints; add a CI/CD-config inspection step to general coding role prompts | new `backend/tests/load/` |
| 57 | **Stage 2 regression + Gap Audit Protocol run.** | | |

---

## Stage 3 — Days 58-63: NOT VERIFIED (43 items) — Measure, Don't Build

Each item gets converted to either a confirmed YES with benchmark evidence, or an honestly
ticketed gap — never left silently unresolved.

| Days | Focus |
|---|---|
| 58-59 | LLM-API outage/retry behavior under a simulated real outage; circuit-breaker interaction from Stage 1.3 |
| 60-61 | Repo-scan/search performance on the largest real repo available; large-file (9000+ line) handling |
| 62 | Frontend behavior under real concurrent load/multiple sessions |
| 63 | Remaining smaller NOT VERIFIED items batched; final Stage 3 write-up in `answers.md` |

---

## Final Full-System Gap Audit — Days 64-65

A fresh run of the same 12-cluster methodology that originally produced `answers.md`, against the
final code — not a summary of daily reports. Diffs every claimed-YES against live re-verification.
Produces the final confidence statement: exact counts of re-confirmed vs. regressed/incomplete
items, stage by stage. This is what "0 missing" means in practice — a number, not a feeling.

---

## SKIP list — unchanged from `Questions_implement.md`, 97 items, untouched without an explicit request

---

## Rules recap (apply throughout)

1. Zero hardcoding, zero hallucination — `file:line` before any claim; "I cannot verify this" over guessing.
2. Full regression suite before and after every day; a newly-broken passing test is always fixed in the change, never in the test.
3. ⚠-marked days no longer pause for a text go-ahead (waived 2026-07-30, see the operating-mode
   note above) — they proceed automatically once the prior day is fully verified done, but stay
   flagged in the daily evidence report as touching schema/global-state/fleet-wide defaults.
4. One day's item (or one root-cause cluster) at a time, fully verified with its own test, before the next.
5. No pulling from a later stage or SKIP ahead of schedule.
6. Evidence report after every day: files touched, exact test counts, new `answers.md` verdict(s).
7. `IMPLEMENTATION_PROGRESS.md` updated the same way it already is.
8. The Gap Audit Protocol can be invoked by the user at any point, not only at the 4 scheduled checkpoint days (10, 34, 57, 65) — when invoked, it re-verifies rather than re-reports.
9. **(Added 2026-07-31)** Stage boundaries pause for an explicit owner go-ahead — Stage 2 does not
   start automatically just because Day 34 is done, even though ⚠-day-level pauses within a stage
   remain waived.

**Total: 65 working days** (a "day" = one focused, fully-verified work unit — if a day's real
complexity exceeds its estimate, the day extends rather than shipping an unverified partial; this
plan is re-estimated, never cut short, when that happens).
