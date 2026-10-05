# Cross-check: Qoder audit vs. our audit

**Dates:** 2026-10-02 / 2026-10-05 · **Source:** `files/Qoder_audit report/` (17 reports + 17 JSON sidecars, 78 findings)
**Method:** every High and Medium finding, and every Low that names a concrete defect, was checked against the current code or a running system. Each fix is backed by a test that **fails on the old code**.

## Result

🟢 **GREEN after fixes.** Qoder is a strong audit: **every High and Medium finding I checked was real.** It found several bugs our own audits missed.

All 5 High root causes are fixed, as are 14 Medium and 13 Low findings, including the two feature gaps the owner decided on 2026-10-05 (epic lifecycle, policy engine v2). The remaining Lows are design limits, documentation notes or test-style observations, recorded and not changed.

Qoder's verdict was "NOT GREEN, production readiness not certified". That was correct for the code it audited (commits `c927c44b` → `90dac23b`). Its High findings are now closed.

## High findings (5 root causes, all fixed)

| Qoder ID | Finding | Fix | Proof |
|---|---|---|---|
| H-1 (ARCH-01-001, ORCH-04-101, PROD-12-102) | A `launch_manager` crash left the task "coding" forever | Task → blocked, with a log line | `test_qoder_h1_manager_failure_blocks_task.py` (old: stuck in `coding`) |
| H-2 (ARCH-01-002) | Simple-mode cost used Haiku-era rates for Opus/Sonnet runs (3.75–6× too low) | Priced at the routed model capped by cost mode | `test_qoder_h2_simple_mode_cost.py` |
| H-3 (AGENT-02-001, PROD-12-103, T-17-107) | `roles/bhaskar_agent.md` missing: the fallback tool offered to 83 agents always failed (tests mocked it away) | Role file written; a new guard requires a role file for every role the code runs | `test_every_run_role_has_a_role_file.py` (fails without the file) |
| H-4 (ORCH-04-102, PROD-14-101) | Leader pool sized 16 for 20 loops: 4 loops never ran; SIGTERM shutdown failed | Fixed the same day from a Sentry alert, independently | `test_leader_pool_sizing.py`; SIGTERM 3/3 clean (old code: shutdown failed, reproduced) |
| H-5 (PROD-09-101, PROD-12-101) | An approved epic cost re-blocked forever | Approval recorded (migration 063); the gate honours it | `test_qoder_h5_epic_cost_approval.py` (old: "approved epic re-blocked") |

## Medium findings

| Qoder ID | Verdict | Outcome |
|---|---|---|
| MEM-03-001 similar-tasks query returned bug/failure/preference rows | Real | **Fixed** (`category='task'`); test fails on old code |
| MEM-03-002 zero-vector repair skipped when consolidation is off | Real | **Fixed**; test fails on old code |
| MEM-03-003 7 duplicate Voyage embeddings per agent run | Real (paid calls) | **Fixed** (embedding memo, failures never cached) |
| ORCH-04-105 one AsyncSession shared by concurrent fan-out subtasks | Real | **Fixed** (own session per concurrent subtask); test fails on old code |
| SEC-05-101 wrong token + GIT_ASKPASS → clone hangs forever | Real (reproduced: killed at 90 s) | **Fixed** (non-interactive git, process-group timeout); 2.5 s now |
| PROD-08-101 one rate-limit bucket for every user behind the Next proxy | Real | **Fixed** (per user; trusted-proxy X-Forwarded-For) |
| PROD-09-102 cost gate never re-checked after planning | Real | **Fixed** (post-planning re-check, child task cancelled); test fails on old code |
| PROD-09-103 context cache unbounded; per-repo invalidation never matched | Real | **Fixed** (LRU 256, path-keyed invalidation); test fails on old code |
| PROD-13-101 autogenerate proposed dropping 7 live tables + 55 indexes | Real | **Fixed** (env.py `include_object`); test fails on old code. Remaining harmless drift: 5 nullability flags, 1 index, 2 constraints (our INFRA-06-007) |
| PROD-13-102 / 103 RTO/RPO undefined; backups dormant | Real at audit time | **Closed** the same day: backup service running, RTO measured (audit 13) |
| AGENT-02-002 submit-schema mismatch only warns | Real, known | Already recorded (our ZP-11-008) |
| EVAL-07-101 eval `quality_checks` never evaluated | Real, known | Live-LLM item L5 (`PENDING_TESTS_API_KEYS.md`) |
| ARCH-01-003 prompt_engineer / ux_design agents only reachable through the raw API | Real | Documented; reachable via `/api/specialized-agents/{name}/run` |
| ARCH-01-004 audit prompt premise stale | Informational | No change |
| ORCH-04-103 / 104 epic path never asks for plan approval, never transitions its child task, never opens a PR | Real (feature gap) | **Fixed** (owner decision 2026-10-05: build it). Plan → `pending_plan_approval` → approve-plan → coding from the saved plan → `ready_for_review` → approve requests the push/PR approval; reject closes the epic and its child task. UI buttons on the epic and Review pages. `test_epic_lifecycle.py` |
| SEC-05-102 policy engine v2 rules recorded but never enforced | Real (dead feature) | **Fixed** (owner decision 2026-10-05: wire it). A plan that touches files matching an active blocking policy stops at `pending_policy_approval`; plan approval is refused (409) until that policy is approved for the epic. `test_epic_lifecycle.py` |

## Low findings

**Fixed (13):**
- **ORCH-04-107:** double plan resume. Atomic claim; the old code resumed twice.
- **ORCH-04-108:** a crashed epic stuck in an in-between status. Now halted with the reason; test fails on the old code.
- **ORCH-04-109:** the Review page could approve nothing. It now lists plans awaiting approval; test fails on the old code.
- **PROD-08-102:** the 429 response used a different error format. Now the standard JSON envelope.
- **PROD-09-104:** the epic list was unbounded. Now `limit`, max 500.
- **PROD-12-105:** the page tour passed on a 404. It now fails on any 4xx/5xx page.
- **MEM-03-005:** `prompt_change` category, plus strict filtering.
- **INFRA-06-102:** `archived_at` is now written as naive UTC.
- **T-17-101 / 102:** stub tests removed; a real assertion and timeout added.
- **PROD-08-104 / INFRA-06-103 / EVAL-07-105:** documentation counts and links (README, DEPLOYMENT, ADD_A_NEW_AGENT, disaster recovery, agent count comments).

**Reviewed, not changed:** these are design limits, documentation notes or test-style observations, recorded here and not individually re-proven.
- ARCH-01-005 (import cycles; ours counts only import-time cycles: 1, benign)
- ARCH-01-006, ARCH-01-007
- AGENT-02-003, AGENT-02-004
- MEM-03-004, MEM-03-006
- ORCH-04-106, INFRA-06-101
- SEC-05-103/104/105
- EVAL-07-102/103/104
- PROD-08-103, PROD-09-105/106 (single-server limits, known)
- PROD-11-101/102/103, PROD-12-104/106 (dead or test-only code, consistent with our ZP-11-006)
- PROD-13-104/105/106, PROD-14-102 (operations features: pre-migration dump, quiesce mode, rotation tooling, release tags)
- T-17-103/104/105/106 (test style; CI-blind live suites)

## Where Qoder was wrong or out of date

- Several findings describe code that was fixed later the same day: H-4, PROD-13-102/103, PROD-12-101's root cause.
- **Correct where we were wrong:** our audit 13 said "no systemd timer is shipped", trusting an old doc; `scripts/systemd/gridiron-backup.{service,timer}` exist. Now corrected.

## What this cross-check proves

Three independent audits: Antigravity (code reading), Qoder (code reading + targeted execution), and ours (code + real-stack runs + drills).
- **Antigravity** found no real bug and made 4 false claims.
- **Qoder** found real bugs that our audits had missed: H-1, H-2, H-3, H-5, ORCH-04-105, SEC-05-101 and others.
- **Our audits** found real bugs that Qoder missed: the Review page crashes, logout, approver-can-erase-admin, outage mass-logout, onboarding blockers, and the spend cap.

Cross-checking with a second strong audit was worth it.
