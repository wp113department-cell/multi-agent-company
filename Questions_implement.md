# Gridiron Platform — Master Production-Readiness Prompt (Final)

You are hardening an existing, largely-working codebase (72 real agents, 3,318+ passing tests,
`mypy --strict`/`black`/`ruff` clean). This is a **gap-closure task, not a rewrite**.

This prompt is built from two independent passes over `answers.md` (the 120-question audit of
this repo): a question-by-question read, and your own 811-sub-answer count and root-cause
clustering. Both agree on the shape of the work. Read `answers.md` and
`IMPLEMENTATION_PROGRESS.md` in full before starting anything.

**Ground truth (811 sub-answers total):** YES 315 (39%) — leave alone. PARTIAL 255 (31%) —
highest-leverage bucket, something real already exists, just needs finishing/wiring/enforcing.
NO 197 (24%) — mostly symptoms of 3 root causes, not 197 separate problems. NOT VERIFIED 43 (5%)
— needs live measurement, not code changes.

---

## Workflow — apply to every item in every stage

1. **Find the question number(s) in `answers.md`**, re-read the current verdict and evidence.
2. **Read the real files it cites** — verify against current code, don't trust the summary.
3. **Write a 3-5 line plan**: what changes, which files, what could break, rollback path. For
   anything touching schema/migrations/global state/fleet-wide defaults, **wait for my explicit
   go-ahead** before writing code.
4. **Implement the smallest change that satisfies the item.** Don't refactor beyond it.
5. **Run the full test suite**, record exact pass/fail/skip counts before and after. If something
   that was passing now fails, fix your change — never touch the test to make it pass.
6. **Add or update a test** that proves this item now works. No test, no YES.
7. **Update `answers.md`**: flip the verdict for that specific sub-item to YES, replace the old
   Plan/gap note with the new evidence (file:line + test name), same citation style as the rest of
   the document.
8. **Report**: item done, files touched, test counts, new verdict.
9. **Root-cause exception**: where one fix closes multiple sub-answers at once (see the three
   Stage 0 clusters below), implement it once, then re-verify and flip *all* the affected
   sub-answers together in one pass — don't artificially repeat the same fix 12 times.

Work through the stages **in order**. Finish and regression-test a whole stage before starting the
next one. Don't cherry-pick from a later stage or from SKIP because it looks easy or interesting.

---

## Stage 0 — Correctness & safety, MUST FIX (do this first, nothing else matters until it's done)

### A. Three root-cause clusters (these close ~20 of the 197 "NO" answers, but are 3 real tasks, not 20)

1. **Memory has no project/repo scoping** (root cause behind ~12 symptoms: cross-project bleed,
   "identify correct project," multi-repo isolation — spans Q5, Q51, Q94, Q95, Q114, Q120).
   Add `project_id`/`repo_id` column + migration to `MemoryEmbedding` (and `VersionedLesson`);
   filter every `query_*` function in `memory/store.py` by it; replace the global
   `_active_repo_path` with per-request/session context, no fallback to the global.
2. **Destructive operations are ungated** — file delete/overwrite, dependency-manifest edits can
   run without confirmation (Q39 area). Add confirmation gates to `delete_file`/`write_file`/
   `edit_file` and dependency-manifest edits, matching the existing pattern already used for
   `git_push`/`git_reset --hard`/`run_migration`.
3. **Shared memory auto-publishes with zero validation or approval** (Q75, Q93). Gate
   `versioned_memory.publish()` behind a confidence threshold or explicit `knowledge_curator`
   review before a lesson becomes queryable/published.

### B. Cheap, high-leverage security/correctness fixes (from the question-level pass)

- **Q21** — Sandbox bash-tool execution (container/chroot/AppContainer instead of regex-based `cd`
  boundary detection) — flagged as the single most important security fix available.
- **Q21** — Make credential encryption mandatory (hard-fail if `CREDENTIAL_ENCRYPTION_KEY` unset)
  in a production deployment profile.
- **Q24** — Fix the `ecdsa` CVE (PYSEC-2026-1325) — `pip-audit` must report zero known vulns after.
- **Q96** — Add the missing migration flagged in the audit (one-line-effort fix).
- **Q92** — Force a live `pip-audit`/`npm audit` run before `dependency_security_agent` can submit
  a CVE claim.
- **Q120** — Fix the archived-memory filter bug (`WHERE archived = false` missing from several
  queries) — mechanical, high-leverage, do before the bigger Stage 2 memory-quality work.

**Acceptance for Stage 0:** a test proves Project A's memory never returns Project B's rows; a
test proves two concurrent sessions on two repos never share `_active_repo_path`; a test proves
delete/overwrite operations require confirmation; a test proves an unreviewed lesson cannot reach
`published` state; `pip-audit` clean; bash tool calls run sandboxed.

---

## Stage 1 — Convert the 255 PARTIALs (fastest path to more real YESes)

Something already exists for each of these — the work is finishing, wiring, or enforcing it, not
building from zero. Work through in this order:

**1.1 Agent intelligence defaults** — flip `enable_critique=True` for Tier-A agents first (coder,
backend_dev, frontend_dev, qa, reviewer), then `enable_replanning=True` for the high-risk/
high-cost tier, staged with a before/after cost & latency check, not flipped fleet-wide blind.
Make `FleetManager.select()`'s output the actual dispatch decision (currently a side-channel
event). Topologically sort subtasks by `depends_on` before dispatch.

**1.2 Verification & trust** — turn the already-declared `expected_verification` contracts into a
real blocking check in `execute_tools`/`_execute_tool_node`. Parse the test runner's actual exit
code/summary into the verification flag programmatically instead of inferring success. Build the
"propose realistic alternatives when blocked" step + a temporary-vs-fundamental limitation
taxonomy.

**1.3 Reliability & durability** — extend `AsyncPostgresSaver` checkpointing from just the
pm/architect/decomposer pipeline to the remaining ~70 worker agents. Add a circuit breaker around
the Anthropic/Groq client calls. Persist background-process PIDs and add a session-close hook to
terminate orphans.

**1.4 Frontend/backend robustness** — add `error.tsx` boundaries at top-level and major route
groups; add reconnect-with-backoff to the SSE consumer; thread `authHeaders()` through every
mutating API call, not just one page; add UI-level role gating.

**1.5 Context & token management** — add a model→context-window table; give `chat_agent.py`'s
graph the same budget check `base_graph.py` already has; replace drop-oldest truncation with a
real LLM-summarization condense step; push a `context_trimmed`/`approaching_limit` SSE event.

**1.6 Requirement compliance & clarification** — add an explicit rule: if a user names a specific
technology/constraint, treat it as hard, and stop + `request_clarification` on conflict instead of
silently substituting. Add an explicit "difficult user" / emotional-de-escalation section to
`chat.md`. Add a "check if this is already done" step before starting new work.

**1.7 Wire existing quality tools into CI** — invoke `regression_detector`'s check against stored
baselines before merge/deploy; run `tech_debt_agent` against PR diffs touching structural files.

**Acceptance:** each converted PARTIAL has a real test; report after finishing each sub-bucket
(1.1 through 1.7), not just at the very end.

---

## Stage 2 — "Should fix soon" (80 real gaps, not blocking, do after Stage 0+1 are verified)

Work through in roughly this order, but re-prioritize based on what you actually hit once Stage
0+1 is live:

1. **Resource/cost/size pre-flight checks (22 items)** — RAM/CPU/GPU/disk/Docker/version checks
   before expensive operations; runtime/size/time estimates before starting large tasks.
2. **Memory quality/prioritization/analytics (20 items)** — staleness handling, relevance ranking,
   dedup, retrieval-time metrics.
3. **Context compression/summarization, beyond the Stage-1 basics (15 items)** — dropped context
   should be summarized, not silently lost.
4. **CI/architecture-drift/code-health automated gates (11 items)**.
5. **Merge-conflict resolution + doc generators (5 items)** — architecture/agent/tool/migration
   doc generation from real code, PR-body generation from diffs.
6. **Performance/latency instrumentation (4 items)** — planning/orchestration/scan/retrieval
   speed timing.
7. **Load/stress tests + CI/CD inspection step (3 items)**.

---

## Stage 3 — NOT VERIFIED (43 items) — measure, don't build

These aren't code gaps — they need real measurement, and doing that only makes sense once Stage
0-2 are in place (measuring a half-fixed system gives you false numbers). For each:
- Run it under real or simulated conditions (SDK retry behavior under a real outage, search/scan
  performance on your largest real repo, frontend behavior under real concurrent load).
- Convert each to either a confirmed YES with benchmark evidence, or an honestly documented,
  ticketed gap — never leave it silently unresolved after this stage.

---

## SKIP — 97 items, do not implement without a direct request from me

Grouped exactly as clustered from the full sub-answer count, reconciled with the question-level
skip list:

- **Self-improvement/learning-loop maturity beyond what already works (19)** — "Company Brain,"
  prompt/tool evolution APIs, pattern-recognition dashboards, retrospective agents, a unified
  quality score. Needs real production volume to be worth building; revisit in 3-6 months.
- **Agent-fleet governance/health/retirement automation (17)**.
- **Exotic file-format support (10)** — HTML/CSS/PHP/Jupyter/Audio/Video/XML/Excel/Word/PPT.
- **Cloud/deploy integrations beyond current scope (7)** — Vercel/Railway/Render/K8s/Azure/GCP —
  deliberate design choice, not a gap; `infra_agent`'s restricted tool access is intentional.
- **UX polish (11)** — confusion detection, beginner/expert mode, plan-editing on human override.
- **User-preference learning (8)** — persisted coding-style/tone memory.
- **MCP-specific polish (4)** — MCP isn't the primary tool path here (ADR-005 explicitly scopes
  a full MCP migration as its own large future project).
- **Agent-creation automation (4)** — manual creation is fine at 72-agent scale.
- **The 5-agent self-improvement group's own scope limits (5)** — deliberate scoping, not a bug.
- **Cross-agent delegation sophistication + misc small items (6)**.
- **Enterprise/hyperscale items (carried over):** distributed 100-1,000-agent concurrency, OIDC/
  SAML SSO, and full MCP re-architecture — all real, all premature before you have the usage or
  customer demand that justifies them.

---

## "Handle any situation the way Claude Code does" — what that actually means here

This isn't one feature, it's the sum of Stage 0 + Stage 1 done properly. By the end of Stage 1,
every agent in the fleet should have, without exception:

- **Verification-before-reply** — never claims tests passed, files exist, or code works without
  having actually run/checked it (Stage 1.2).
- **Honest uncertainty** — says "I cannot verify this" rather than guessing, same standard this
  whole audit was held to.
- **Graceful degradation on failure** — proposes an alternative or explains the real blocking
  constraint instead of just halting (Stage 1.2).
- **Human approval on anything destructive or ambiguous** — no silent deletes, overwrites, or
  unreviewed knowledge promotion (Stage 0).
- **Self-correction** — critique/replanning actually running for at least the Tier-A agents by the
  end of Stage 1, not shipped-but-dormant.

If you want to check whether the platform is "there," these five properties — not the raw YES
count — are the real test.

---

## Non-negotiable rules (apply throughout, no exceptions)

1. Zero hardcoding, zero hallucination — cite `file:line` before claiming anything; say "I cannot
   verify this" rather than guess.
2. Never break the existing test suite. Baseline it before you start, re-check after every item.
3. Plan before touching anything schema/global-state/fleet-default related; wait for my approval.
4. One item (or one root-cause cluster) at a time, fully verified with its own test, before moving
   on.
5. No pulling items from Stage 2/3 or SKIP ahead of schedule.
6. After each item: a short evidence report — what changed, files touched, exact test counts, new
   `answers.md` verdict.
7. Update `IMPLEMENTATION_PROGRESS.md` the same way the existing file already does.

---

## What "production use" means at each checkpoint

- **After Stage 0** — the platform is no longer unsafe: no cross-project data bleed, no
  ungated destructive operations, no unreviewed knowledge auto-publishing.
- **After Stage 0 + Stage 1** — this is genuinely safe for real single-team/single-org production
  use, and behaves like Claude Code on the five properties above.
- **After Stage 2** — robust and pleasant to operate at real scale, not just correct.
- **After Stage 3** — you have measured confidence numbers instead of estimates.
- **SKIP stays skipped** until real usage data — not this audit — says otherwise.