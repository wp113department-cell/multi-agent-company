# Remediation plan: independent production audit of 2026-10-06

**Source:** `What_is/PRODUCTION_AUDIT_2026-10-06.md`, an independent model audit of commit `bf0b4243` (this morning, before today's audit 15 fixes). Score: **53/100**, "not ready for unrestricted production".
**This plan:** each finding checked against the current code. **No code was changed for this plan.** Work starts only after the owner approves.

## 1. Is the report right?

**Mostly yes.** I checked 25 of its 44 findings directly in the current code, and **all 25 are real**. The rest are consistent with what I know of the code; they are marked "to verify" below, not assumed.

| Group | Findings | Status today |
|---|---|---|
| ✅ Confirmed in the current code | A01, A03, A04, A05, A06, A07, A08, A12, A13, A15, A16, A17, A21, A23, A24, A25, A29, A30, A32, A34, A40 | Real, open |
| 🟢 Already fixed today | **A02** Bhaskar sandbox. The report says "real container behaviour not verified". It is now: 10 real-container tests plus 17 attack scripts all blocked (audit 15) | Closed |
| 🟢 Partly addressed today | Fleet scan cost, isolated APPLY worktrees, barot reachability: the report saw these commits but did not re-audit them (audit 15 did) | Closed |
| 🔎 Plausible, to verify first | A09, A10, A11, A14, A18, A19, A20, A22, A26, A27, A28, A31, A33, A35–A39, A41–A44 | Verify before fixing |
| ℹ️ Feature gaps, not bugs | No SKILL.md framework, no MCP client, no crawler, no incoming webhooks, no editor/LSP | Product roadmap |
| ℹ️ Documentation drift | Guide counts (tools 213, head 063, 131 paths), "96% ready" arithmetic, competitor framing | Correct the guide |

**Where the report is wrong or outdated:** only A02 and the three concurrent changes it did not re-audit. It is not wrong about anything else I checked.

## 2. Why did our audits not catch these?

Being honest:

1. **Different yardstick.** Our 14 audits followed the 14 audit spec files for the owner's decided setup: **one owner, running locally, no domain, no public users** (owner decision, 2026-10-02). This report rates **public / multi-user / Docker-image production**. Ownership between users (A07), image distribution (A05), the production compose stack (A29–A31) and token revocation (A12) mostly matter in that setting. That's why we stayed GREEN for local use while this report scores 53 for public production. Both can be true.
2. **Real misses in our coverage**, which the specs' paths did not exercise and we didn't look beyond:
   - **A01** the `python_snippet` tool runs on the host. We hardened the bash sandbox and, today, bhaskar, but not this third executor.
   - **A04** protected-file checks via symlinks.
   - **A15 / A16** the `/run-sync` endpoint's arguments and the research/DevOps tuple results. We fixed the same argument bug in the eval runner today, but not in this endpoint.
   - **A17** the RQ worker's durable checkpoints.
   - **A19** plan dependency indices after a step is rejected.
   - **A21** quality gates that fail open.
   - **A24** the spend cap is not atomic. We even saw a $0.036 ledger jump on 2026-10-05 that I couldn't attribute to a run.
   - **A25** an agent with no runs scores "perfect".
3. **Mocked and unit tests passed** for most of these. The report found them by tracing the code paths and running adversarial probes, the same method that found 9 bugs during our live AI tests.

## 3. Does "fix all of this → about 90%" really follow?

**Not automatically.** The report itself says these are *"conditional target ranges, not guaranteed score gains"*:

- **Stage 1** (security blockers) → 65–70
- **Stage 2** (deployment and lifecycle) → 75–80
- **Stage 3** (quality evidence and UX) → 85–90
- **Stage 4** (multi-tenant, external security review) → 90–95

The score is one auditor's rubric. A re-audit gives the higher score only if the **evidence** exists: a fresh-volume compose install, a restore drill, crash and restart resume, a two-user access matrix, budget-edge tests, and held-out real tasks. That last one needs paid model runs.

So **85–90 is realistic after Stages 1–3 with proof**. 90+ needs Stage 4, an external security review and real-task evaluation with budget. Fixing code lines alone does not move the score.

## 4. Decisions needed from the owner before starting

| # | Decision | Why it matters |
|---|---|---|
| D1 | **Who uses Gridiron?** Only you, a trusted team, or separate customers? | Decides whether A07, A08 and A14 (ownership, tenancy, privacy) are P0 or optional |
| D2 | **Will Docker images be built and shared or deployed?** | A05, A29–A31 and A44 are P0 only for deployment |
| D3 | **Budget for Stage 3 evidence** (held-out real tasks with the live model) | About $3–10 depending on task count. Everything else is $0 |
| D4 | **Run code in Docker everywhere** (python_snippet, tests, package scripts) | It's the A01 fix; tasks need Docker running |

## 5. The plan (each step: fix → test that fails on the old code → full local CI → push)

### Phase 1: Security blockers ($0)
| Step | Findings | Work | Acceptance test |
|---|---|---|---|
| 1.1 | **A01** | Route `python_snippet` (and every other host executor found by a sweep) through the Docker sandbox, like bhaskar; no host fallback | Outside-workspace canary file and `.env` unreachable from Python, Node and child processes |
| 1.2 | **A04** | Protected-path check on both the written **and the canonical** path | Read, write and delete through a file or parent-dir symlink to `.env`, `.git` and keys are all denied |
| 1.3 | **A03** | Chat and terminal sessions take a registered `repo_id`; the server resolves the path | Unregistered, outside-root and symlinked paths rejected |
| 1.4 | **A05** | `.dockerignore` (root, backend, web) plus selective `COPY` | Build with a fake-secret canary; the canary is absent from every layer |
| 1.5 | **A06, A09, A10** | Browser: intercept every request and redirect, fail closed on DNS errors, check IPv6; pin validated IPs for fetch; confine screenshot paths | Fixture network: redirects, rebinding and private IPv6 all blocked |
| 1.6 | **A11** | Job sandboxes cannot reach the control-plane DB, Redis or metadata services; migrations use a test DB URL | Hostile job code cannot connect |
| 1.7 | **A12** | Token version per user; password change and logout invalidate old tokens | An old token gets 401 after a password change |
| 1.8 | **A13** | Sentry `before_send` redaction | Canary secrets are absent from outgoing events |
| 1.9 | **A07, A08, A14** | Depends on D1. **Trusted team:** document it and scope memory per repo (A08). **Customers:** owner and tenant fields plus a two-user matrix | Project A's facts never appear in project B |

### Phase 2: Reliability and lifecycle ($0)
| Step | Findings | Work |
|---|---|---|
| 2.1 | **A15, A16** | `/run-sync` uses the shared argument adapter; normalize tuple results (research, DevOps); signature-aware test over all 67 names |
| 2.2 | **A17, A18** | Start durable savers inside RQ jobs; production fails closed or reports degraded instead of silently using MemorySaver; restart and resume drill |
| 2.3 | **A19** | Stable step IDs; remap and validate the DAG when steps are rejected or edited |
| 2.4 | **A20** | Per-subtask worktrees when fan-out is on (reuse `enhancement_workspace.py`) |
| 2.5 | **A21** | Gate states: passed, failed, unavailable, skipped; risk-required gates block when unavailable |
| 2.6 | **A22** | One authoritative tool registry; unknown side-effect tools denied; consistency check in CI |
| 2.7 | **A23** | Atomic idempotency reservation (actor + route + body) |
| 2.8 | **A24** | Atomic spend **reservation** before each call, reconciled after; defined Redis-outage behaviour; concurrency test |
| 2.9 | **A29, A30, A31, A39, A40** | Compose: backend URL for the frontend, volume ownership init, execution worker, backups in compose, `/ready` endpoint (fleet, worker heartbeat, saver, storage, sandbox) → **fresh-volume install drill** |

### Phase 3: Evidence and UX
| Step | Findings | Work | Cost |
|---|---|---|---|
| 3.1 | **A25, A26** | "Insufficient data" instead of perfect scores; versioned baselines; held-out real-repo task suite | $0 code; **live run needs D3** |
| 3.2 | **A27, A28** | Effective output caps per model; dispatcher-enforced timeouts and verification; real environment probing | $0 |
| 3.3 | **A32–A38** | Task pagination, idempotent create plus attachments, priority sent, error and expired-session handling, stream dedup, chat history restore, batched rendering | $0 |
| 3.4 | **A41–A44** | Real-stack CI journeys, safe workflow inputs, dev-only `run.sh`, durable alert outbox, accessibility and non-root frontend and CSP | $0 |
| 3.5 | Docs | Correct the master guide with a dated evidence ledger (implemented, enabled, deployed, tested, verified) | $0 |

### Phase 4: Product roadmap (optional, after 1–3)
SKILL.md-style skill bundles · optional MCP client with explicit grants · signed incoming CI/GitHub webhooks · editor/LSP integration · write-scope temporary agents (audit 15 next task #1) · measured learning (memory off/on on held-out tasks).

## 6. Effort and order

| Phase | Size | Notes |
|---|---|---|
| 1 Security | Large: about 9 work items, 2–3 sessions | Highest value; all testable for free |
| 2 Reliability | Large: about 9 items including a deployment drill, 2–3 sessions | The compose drill needs Docker and disposable volumes |
| 3 Evidence and UX | Medium-large, 2 sessions plus the paid evaluation | Paid only for 3.1's live run |
| 4 Roadmap | As you choose | — |

**Rules (unchanged):**
- Before each fix, re-check the finding, since the code may have moved.
- Every fix gets a test that fails on the old code.
- Full local CI before every push.
- No Anthropic spend without your go.
- Never weaken a guard to make a test pass, for example by turning sandboxing off.

**Waiting for the owner's go and decisions D1–D4.**
