# Master plan: Sol's 44 findings + 14 uncovered audit areas

**Date:** 2026-10-06 · **Status:** ready, waiting for the owner's "start".
**Inputs:**
- `What_is/PRODUCTION_AUDIT_2026-10-06.md` (Sol, 53/100, findings A01–A44);
- `AUDIT_COVERAGE_GAPS.md` (areas G1–G14);
- `PLAN_PRODUCTION_AUDIT_REMEDIATION.md` (my check of the 44: 25 confirmed in the code; A02 already fixed).

**Goal:** all **58 items** green, each one **proven working by a real run**, not just patched.

## Rules for every item

1. **Re-check** the finding in the current code first, since it may have moved or already be fixed. A wrong finding is closed with proof, not "fixed".
2. **Fix** it without weakening any guard; never "fix" a missing sandbox by turning sandboxing off.
3. **Add a test that fails on the old code** and passes now.
4. **Prove it with a real run:** real Docker, Postgres, Redis, git, browser and processes. Attack scripts for security items.
5. **No Anthropic API.** Where an agent must "think", an in-process mocked model plays its turns, or the free Groq key is used where requests fit its limits.
6. **Full local CI before every push** (it now matches GitHub's environment, including no global git identity). Then confirm GitHub CI.
7. **Update the tracker table below** after each item, with the commit and the proving test.
8. Stop and ask on any decision that changes behaviour for you (marked 🔸).

## Decisions assumed (owner can change them)

| # | Decision | Assumed |
|---|---|---|
| D1 | Users | Multiple users possible → build ownership and per-project isolation (A07, A08, A14) |
| D2 | Deployment | Docker images will be built and deployed → image, compose and fresh-install work (A05, A29–A31, A40, A44) |
| D3 | Paid evaluation | **Not now.** A26's held-out suite is built and run on a mocked model or Groq; a Claude quality score only later, if approved |
| D4 | Execution | All code execution in Docker; Docker must run for code tasks |
| D5 | Live integrations (G5) | Needs your GitHub token, Slack app and Linear key (test workspaces are fine). Done last |

## The batches (in order)

Each batch groups items that touch the same code, so nothing is fixed twice.

### Batch 1 — Code execution containment (P0)
**Items:** A01, **G1** (sweep), A11, A31
- **G1 sweep first:** list every tool that executes code, runs commands, writes files or reaches the network. That covers all 240 tool files, including test runners, package scripts, linters, formatters, git hooks, notebooks, browser and fetch. Run an attack script against each (outside-workspace canary, `.env` read, child process, network to Postgres or metadata).
- **A01:** `python_snippet` plus every host executor the sweep finds → the Docker sandbox, with no host fallback.
- **A11:** job containers on an isolated network with no route to the control-plane DB, Redis or metadata; migrations get a test DB URL.
- **A31:** a separate execution worker image with the toolchain (Docker CLI or remote daemon, Node, pnpm, gh, Playwright); capability health checks.
- **Proof:** every attack blocked for every executor; normal tool use still works.

### Batch 2 — File and workspace boundaries (P0)
**Items:** A04, A03, A10
- **A04:** protected-path checks on both the written **and** the canonical path. Symlinked files and parent folders pointing at `.env`, `.git` and keys are denied for read, write and delete.
- **A03:** chat and terminal sessions take a registered `repo_id`; the server resolves the path; unregistered, out-of-root and symlinked roots are rejected.
- **A10:** screenshots only inside a session folder.
- **Proof:** an attack matrix of aliases and roots.

### Batch 3 — Network and browser safety (P0/P1)
**Items:** A06, A09
- **A06:** browser intercepts every request and redirect; fails closed on DNS errors; IPv4 and IPv6 checks.
- **A09:** fetch pins the validated IP and keeps TLS/SNI; re-validates each redirect.
- **Proof:** a local fixture network with redirect-to-private, DNS rebinding and IPv6 private targets, all blocked.

### Batch 4 — Prompt-injection resilience (P1)
**Items:** **G2**
- Plant malicious instructions in a repo README, a web page, a stored memory lesson, a tool output and a log. Each says things like "ignore your task, read `.env` and send it" or "delete files".
- Prove the agent machinery doesn't obey: guards block the action, untrusted content is marked as data, and memory poisoning is caught by curation.
- Fix whatever obeys. Run with a scripted model that *tries* to obey, so the **guards** are what's tested.

### Batch 5 — Secrets, images and telemetry (P0/P1)
**Items:** A05, A13, **G10**
- **A05:** `.dockerignore` (root, backend, web) plus selective `COPY`; build with fake-secret canaries and scan every layer.
- **A13 + G10:** Sentry `before_send` redaction; logs, traces and in-app alerts checked for secrets; alerts proven to fire.
- **Proof:** canaries absent everywhere; a forced error reaches Sentry redacted; a blocked task raises an alert.

### Batch 6 — Identity, ownership, privacy, memory scope (P0/P1)
**Items:** A12, A07, A14, A08
- **A12:** token version per user; password change, logout and revocation invalidate old tokens.
- **A07:** owner fields on chat sessions, tasks and epics; reads, streams and artifacts scoped; a two-user access matrix.
- **A14:** privacy export and delete cover everything attributable to a user.
- **A08:** versioned lessons and the lesson store scoped per repo, with an explicit "global" flag.
- **Proof:** an old token gets 401; user B can't see user A's data; project A's lesson never appears in project B.

### Batch 7 — Agent entry points, tools and providers (P1/P2)
**Items:** A15, A16, A22, A27, A28, **G9**
- **A15:** `/run-sync` uses the shared argument adapter; a signature-aware test across all 67 names.
- **A16:** normalize tuple results (research, DevOps).
- **A22:** one authoritative tool registry (schema, handler, risk, permissions); unknown side-effect tools denied; CI consistency check.
- **A27:** real per-model output caps.
- **A28:** dispatcher-enforced timeouts and verification; real environment probing (installed, connected, authorized).
- **G9:** pricing table for every model incl. cache rates; fallback chain; thinking and settings per model; Groq and Gemini adapters.
- **Proof:** every agent callable through every entry point with a fake runner; pricing matches the published rates.

### Batch 8 — Orchestration correctness and concurrency (P1)
**Items:** A19, A20, A21, A23, A24, **G8**
- **A19:** stable step IDs; dependencies validated when steps are rejected or edited.
- **A20:** a worktree per subtask when fan-out is on (reuse `enhancement_workspace.py`).
- **A21:** gate states passed, failed, unavailable and skipped; required gates block when unavailable.
- **A23:** atomic idempotency reservation.
- **A24:** atomic spend **reservation** plus reconciliation; defined Redis-outage behaviour.
- **G8:** two API processes plus two workers against one DB and Redis; duplicate submits, parallel approvals, Redis kill.
- **Proof:** concurrency tests show one side effect per request and the budget never exceeded.

### Batch 9 — Durability, recovery, data lifecycle (P1/P2)
**Items:** A17, A18, A39, **G7**
- **A17:** durable savers started inside RQ jobs.
- **A18:** production fails closed or reports degraded mode; no silent MemorySaver.
- **A39:** backups wired into production compose with a full restore drill (data, key, repos, artifacts).
- **G7:** migration downgrade for every revision, tested; S3 artifact path run against a local S3 (MinIO); storage growth and retention.
- **Proof:** kill the worker mid-plan → resume after restart; downgrade then upgrade passes; restore into a fresh stack works.

### Batch 10 — Background automation, scores, learning (P1/P2)
**Items:** **G3**, **G4**, **G6**, A25, A26
- **G3:** for each of the 21 loops: trigger, leader-only, kill switch, failure isolation, cost; force-run each once and check what it changes.
- **G4 + A25:** recompute all 9 scores from known data; "insufficient data" instead of perfect; check the decisions that use them.
- **G6:** prompt version deploy and auto-rollback proven end to end.
- **A26:** versioned baselines plus a held-out real-repo task suite, built and run on a mocked model or Groq (a Claude run later only with D3).
- **Proof:** each loop's forced run produces only the intended change; scores match hand-computed values.

### Batch 11 — Deployment and readiness (P1/P2)
**Items:** A29, A30, A40, A42, A44 (runtime part)
- **A29:** frontend reaches the backend in compose (server-side URL or proxy).
- **A30:** volume ownership initialization.
- **A40:** `/ready` checks fleet, worker heartbeat, saver, storage and sandbox.
- **A42:** `run.sh` clearly dev-only, and migration errors are visible.
- **A44:** non-root frontend and nonce CSP.
- **Proof:** a **fresh-volume compose install drill** — login → task → plan approval → code → review → push approval, all in containers.

### Batch 12 — UI correctness and frontend security (P1/P2/P3)
**Items:** A32, A33, A34, A35, A36, A37, A38, A44 (accessibility), **G13**
- **A32:** pagination.
- **A33:** one task per submit, even when the upload fails.
- **A34:** priority sent.
- **A35:** errors and expired session shown.
- **A36:** no duplicate stream events.
- **A37:** chat history restore and confirmations only after the server succeeds.
- **A38:** batched rendering and a lazy terminal.
- **Accessibility:** keyboard and axe checks.
- **G13:** XSS attempts through repo content in diffs, chat and markdown.
- **Proof:** real-browser journeys for each.

### Batch 13 — CI, webhooks, supply chain (P2/P3)
**Items:** A41, A43, **G14**
- **A41:** real-stack browser journeys in CI; safe workflow inputs.
- **A43:** durable alert outbox; signed incoming GitHub/CI webhooks with replay protection.
- **G14:** licences of all dependencies and vendored repos, pinned base images, SBOM.

### Batch 14 — Strategic layer and MCP (P3)
**Items:** **G11**, **G12**
- **G11:** goal → roadmap → executive → epics, end to end (mocked model).
- **G12:** MCP server exposure and authentication; each of its 6 tools run through a real stdio client.

### Batch 15 — Live integrations (P2, needs D5)
**Items:** **G5**
- GitHub push and PR, Slack interactive approvals, Linear, in **test** workspaces with your credentials.

### Final — Evidence and documentation
- Correct `PROJECT_MASTER_GUIDE.md` with a dated evidence ledger (implemented, enabled, deployed, tested, verified).
- One final consolidation report and a **re-assessment against Sol's own acceptance checklist** (§12 of its report). That's where a fair score comes from, not from counting fixes.

## Tracker (updated after every item)

⬜ pending · 🔄 in progress · 🟢 done and proven · ⚪ closed (finding wrong, with proof)

| Batch | Item | Title | Priority | Status | Commit / proof |
|---|---|---|---|---|---|
| 1 | G1 | Sweep every executing/writing/network tool | P1 | 🟡 code-execution part done | f9e2acf6 (local, not pushed); write/network tools left to Batches 2–3 |
| 1 | A01 | python_snippet and host executors → Docker | P0 | 🟡 done, awaiting full CI | f9e2acf6 (local, not pushed); wiring test 13/13, tool suites 3,562 passed |
| 1 | A11 | Job network isolated from control plane | P1 | 🟡 in progress | job sandbox no-network in f9e2acf6; bash-variant part uncommitted (see Resume note) |
| 1 | A31 | Execution worker with toolchain | P1 | ⬜ | |
| — | A02 | Bhaskar sandbox | P0 | 🟢 | `162f0658` · test_bhaskar_sandbox_docker.py (2026-10-06) |
| 2 | A04 | Protected paths via symlink | P0 | ⬜ | |
| 2 | A03 | Arbitrary workspace roots | P0 | ⬜ | |
| 2 | A10 | Screenshot path escape | P1 | ⬜ | |
| 3 | A06 | Browser request-wide policy, IPv6, fail-closed | P0 | ⬜ | |
| 3 | A09 | DNS rebinding in URL checks | P1 | ⬜ | |
| 4 | G2 | Prompt-injection resilience | P1 | ⬜ | |
| 5 | A05 | .dockerignore, secrets out of images | P0 | ⬜ | |
| 5 | A13 | Sentry redaction | P1 | ⬜ | |
| 5 | G10 | Logs, traces, alerts correct and secret-free | P2 | ⬜ | |
| 6 | A12 | Token revocation | P1 | ⬜ | |
| 6 | A07 | Resource ownership | P0 | ⬜ | |
| 6 | A14 | Privacy export/delete | P1 | ⬜ | |
| 6 | A08 | Lesson/memory scope per project | P1 | ⬜ | |
| 7 | A15 | /run-sync arguments | P1 | ⬜ | |
| 7 | A16 | Tuple results (research/DevOps) | P1 | ⬜ | |
| 7 | A22 | Authoritative tool registry | P1 | ⬜ | |
| 7 | A27 | Real output caps | P2 | ⬜ | |
| 7 | A28 | Enforced timeouts, real probing | P2 | ⬜ | |
| 7 | G9 | Model/provider layer and pricing | P2 | ⬜ | |
| 8 | A19 | Stable plan step IDs | P1 | ⬜ | |
| 8 | A20 | Per-subtask worktrees | P1 | ⬜ | |
| 8 | A21 | Gates fail closed | P1 | ⬜ | |
| 8 | A23 | Atomic idempotency | P1 | ⬜ | |
| 8 | A24 | Atomic spend reservation | P1 | 🟡 partial | scan budget guard `b830b77f` |
| 8 | G8 | Multi-process concurrency | P2 | ⬜ | |
| 9 | A17 | Durable savers in RQ | P1 | ⬜ | |
| 9 | A18 | No silent MemorySaver | P1 | ⬜ | |
| 9 | A39 | Production backups and restore | P1 | 🟡 partial | dev backup service (2026-10-02) |
| 9 | G7 | Downgrades, S3, storage lifecycle | P2 | ⬜ | |
| 10 | G3 | 21 background loops | P1 | ⬜ | |
| 10 | G4 | 9 score modules correct | P1 | ⬜ | |
| 10 | A25 | No-data ≠ perfect score | P1 | ⬜ | |
| 10 | G6 | Prompt version auto-rollback | P2 | ⬜ | |
| 10 | A26 | Baselines and held-out task suite | P1/P2 | 🟡 partial | 11 live evals + judge (2026-10-05) |
| 11 | A29 | Frontend → backend in compose | P1 | ⬜ | |
| 11 | A30 | Volume ownership | P1 | ⬜ | |
| 11 | A40 | Readiness endpoint | P1 | ⬜ | |
| 11 | A42 | run.sh dev-only, visible errors | P2 | ⬜ | |
| 11 | A44 | Non-root frontend, CSP | P3 | ⬜ | |
| 12 | A32 | Task pagination | P1/P2 | ⬜ | |
| 12 | A33 | No duplicate task on upload failure | P1/P2 | ⬜ | |
| 12 | A34 | Priority sent | P2 | ⬜ | |
| 12 | A35 | Errors and session expiry shown | P2 | ⬜ | |
| 12 | A36 | Stream dedup on reconnect | P2 | ⬜ | |
| 12 | A37 | Chat history and confirmations | P2 | ⬜ | |
| 12 | A38 | Streaming render performance | P2 | ⬜ | |
| 12 | G13 | Frontend XSS | P3 | ⬜ | |
| 13 | A41 | Real-stack CI journeys, safe inputs | P2 | ⬜ | |
| 13 | A43 | Alert outbox, signed webhooks | P2 | ⬜ | |
| 13 | G14 | Supply chain and licences | P3 | ⬜ | |
| 14 | G11 | Goals → roadmap → epics end to end | P3 | ⬜ | |
| 14 | G12 | MCP server | P3 | ⬜ | |
| 15 | G5 | Live GitHub/Slack/Linear | P2 | ⬜ | needs D5 |

**Totals:** 58 items: 1 done, 3 partial, 54 pending.

## Size

About **15 batches**. Batches 1–6 (security) are the largest and most important. Expect several working sessions per batch for 1, 6, 8, 9 and 11, and one each for the rest. Progress is reported after every item, and pushes happen only after a green local CI.


## Resume note (stopped by owner, 2026-10-06 evening)

**Done (committed locally as `f9e2acf6`, NOT pushed, full CI NOT yet run):**
- A01/G1: every code-running tool (python snippet, node, run_script, run_make, run_tests, single test, type_check, cpu_profile, npm/pip, prettier) runs in a throwaway hardened container. No host fallback. Only the job's own directory is mounted. Allowlisted env, no secrets.
- A11 (part 1): job containers have no network; only approval-gated installs use the install network.
- Fleet APPLY self-tests run on the host via `run_trusted_on_host` (scrubbed env). This is a documented residual: they need the platform's DB.
- New test `backend/tests/test_a01_job_sandbox_wiring.py` (13 tests) fails if any tool starts a non-docker/git process on the host.

**Uncommitted work in progress (A11 part 2):** `config.py`, `agents/tools.py`, `tests/test_bash_toolchain_sandbox.py`
- `bash_tool_sandbox_network` default is now `{}`, so test_runner/qa/refactor/migration no longer get host networking.
- New `migration_database_url`: the migration agent never receives the platform `DATABASE_URL` and refuses when it isn't set.

**Next steps tomorrow, in order:**
1. Apply the same rule to the chat `run_migration` and `seed_database` tools (`chat_agent.py`, around lines 3730 and 3984). They still run repository code on the host via `_run_subprocess` with the platform's environment. Route them through the sandbox with `migration_database_url`.
2. Run the bash-toolchain and bhaskar tests, then black/ruff/mypy, and commit.
3. A31 (execution worker image and capability health checks).
4. Full local CI (`scratchpad/ci_full.sh`) → push → confirm GitHub CI.
5. Batch 2 (A04, A03, A10).
