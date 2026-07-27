# Pending Tests — Waiting on Real API Keys / Services

**Date compiled:** 2026-07-23
**Why this file exists:** these tests are written, committed, and skip/deselect *cleanly* in the
normal `pytest tests/ -q` run (no failures, no errors) — but they never actually execute against a
real LLM because no real `ANTHROPIC_API_KEY` (and, per your question, no `OPENAI_API_KEY` either)
is currently configured. This is the complete, grep-verified list of every one of them, why each
is blocked, and exactly how to run them once you have real keys.

**Current default test run:** `pytest tests/ -q` → **2707 passed, 0 failed, 55 skipped, 17
deselected**. This file accounts for all 55 + all 17 = **72 tests**, of which **71 are genuinely
blocked on a real API key or a real external service** (1 skip — `reportlab` — is an unrelated
missing pip package, not an API-key issue; included below for completeness so nothing is left out).

**Update (2026-07-27):** sections F and G below add a second, different category — new tests
written during the Audit 04 (Orchestration) and Audit 05 (Security) fix passes that are blocked on
*environment* (no Python interpreter, no Postgres reachable) rather than credentials. Keeping both
categories in this one file per user direction, since both boil down to "written, not yet confirmed
to pass." **Section G carries extra weight**: the Audit 05 fix pass added a real auth dependency to
essentially every mutating endpoint in the API — this is a real, structural change to how the whole
app behaves, and `tests/conftest.py` itself was changed to compensate (see section G) — running
`pytest tests/ -q` for the very first time after this fix pass is the single most important
verification step in this entire file, more so than any individual new test.

---

## Quick answer to "OpenAI too, right?"

**No test in this codebase is currently gated on `OPENAI_API_KEY`.** Verified by grep across all of
`backend/tests/` — zero matches. OpenAI only appears in one place in the real backend:
`backend/app/api/settings.py:264-283`'s `_verify_openai()` — a "test this key works" helper behind
the Settings/Credential Vault UI (calls `client.models.list()` to validate a key a user pastes in).
**No agent actually calls OpenAI to do real work** — the model tiers (`MODEL_PLANNER`/`MODEL_CODER`/
`MODEL_ROUTER`) are all Anthropic model names, and the only alternate LLM backend wired into agent
execution is Groq (`USE_GROQ`/`GROQ_API_KEY`, a temporary/dev-only substitute — see
`backend/app/agents/base.py`). So there is nothing to add here for OpenAI *today*; if an agent is
ever built that calls OpenAI directly, tests for it would need to be written then, and this file
updated.

Everything below is real, already-written, currently-blocked test code.

---

## A. Anthropic-ONLY tests — need a real `ANTHROPIC_API_KEY`, Groq cannot substitute

**File:** `backend/tests/test_day0_groq_integration.py` (lines 361-386)
**Count: 4 tests.** These test Claude-specific behavior that Groq/qwen3 doesn't have (prompt
caching headers, native vision blocks) or is unreliable at (structured JSON) — so a Groq key does
NOT unblock these, only a real Anthropic key does. All 4 are currently `pass`-only stubs (marked
`# TODO`) — they need to be *written* as well as run once a key exists:

| Test | What it must verify | Status |
|---|---|---|
| `test_prompt_caching_header_sent` | `cache_control: {"type": "ephemeral"}` is actually sent on the system prompt | Stub — `pass`, has a `# TODO` describing the exact assertion to add |
| `test_image_block_param_in_call_llm` | A real `ImageBlockParam` flows through `call_llm()` without serialization errors (Day 16 vision pipeline) | Stub — `pass` |
| `test_reflection_node_with_real_claude` | `reflection_node` gets reliable structured JSON from Claude Sonnet (Groq/qwen3 sometimes returns prose instead) | Stub — `pass` |
| `test_full_pipeline_pm_to_qa_with_claude` | Full pm→architect→decomposer→planner→coder→reviewer→qa pipeline run end-to-end with real Claude | Stub — `pass` |

Skip condition (`test_day0_groq_integration.py:351-358`):
```python
ANTHROPIC_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get(
    "ANTHROPIC_API_KEY", ""
).startswith("sk-ant")
anthropic_only = pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="...")
```

**To run once you have a key:**
```bash
cd backend
ANTHROPIC_API_KEY=sk-ant-your-real-key .venv/bin/pytest tests/test_day0_groq_integration.py -v -m slow -k "anthropic or caching or image_block or reflection_node_with_real or full_pipeline_pm_to_qa"
```
(These 4 are also inside the `not slow` exclusion — see `pytest.ini`'s `addopts = -m "not slow"` —
so you need `-m slow` even with a key set, or they'll deselect silently.)

---

## B. Groq-specific tests — need a real `GROQ_API_KEY` (currently the only *working* real-LLM path)

**Count: 13 tests**, all currently **deselected** by `pytest.ini`'s default `-m "not slow"` — they
are not broken, just excluded from the default run because they're slow/real-network.

**B1 — `backend/tests/test_day0_groq_integration.py` (9 tests):**
| Class | Tests | What it verifies |
|---|---|---|
| `TestPlannerNodeRealLLM` | 3 | Planner node produces real JSON with steps, sets status=running, survives a bad model response |
| `TestReflectionNodeRealLLM` | 2 | Reflection node returns a `satisfied` field; non-fatal on partial JSON |
| `TestLessonExtractionRealLLM` | 2 | A lesson is really extracted+stored from a run; retrieval finds it |
| `TestFullGraphRunGroq` | 2 | A mini task runs end-to-end on the real graph; `trace_id` propagates into final state |

**B2 — `backend/tests/evals/test_evals.py::TestAgentEvals` (4 tests):**
sprint_planner, business_analyst, style_reviewer evals (score thresholds ≥0.5/≥0.5/≥0.4), plus
`test_all_evals_pass_threshold` (full 5-task suite, avg score ≥0.6). Gated by its own fixture
(`require_groq`, lines 91-97): skips unless `settings.use_groq and settings.groq_api_key`.

**To run once you have a Groq key:**
```bash
cd backend
USE_GROQ=true GROQ_API_KEY=gsk_your-real-key .venv/bin/pytest tests/test_day0_groq_integration.py tests/evals/test_evals.py -v -m slow
```

---

## C. Full `tests/pending/` directory — 54 tests, need `RUN_PENDING_TESTS=1` + real credentials

These are the most thorough pending tests — real agent runs against a real repo/DB, not just unit
mocks. All skip cleanly (verified: none error, none fail) until you set `RUN_PENDING_TESTS=1` *and*
supply whatever each file needs. Skip logic lives centrally in
`backend/tests/pending/conftest.py:62-83` (`requires_anthropic` — really "requires any real LLM,
Anthropic or Groq", `requires_voyage`, `requires_db`, `requires_all`).

| File | Tests | Real requirement | What it tests |
|---|---|---|---|
| `test_pm_agent.py` | 3 | LLM (Anthropic *or* Groq) | PM Agent produces a valid brief via a real model call |
| `test_architect_agent.py` | 3 | LLM | Architect Agent reads the repo + submits a structured plan |
| `test_decomposer_agent.py` | 3 | LLM | Decomposer Agent produces a typed subtask list |
| `test_planner_agent.py` | 4 | LLM | Planner Agent produces a validated markdown plan, retries on bad output |
| `test_coder_agent.py` | 3 | LLM | Coder Agent writes a file in a worktree, passes mypy+ruff |
| `test_pipeline_e2e.py` | 5 | LLM | Full PM → Architect → Decomposer LangGraph run |
| `test_research_agent.py` | 3 | LLM (**see caveat below**) | Research agent returns a valid report; disabled-flag behavior; tool list |
| `test_embeddings.py` | 4 | `VOYAGE_API_KEY` | Voyage AI embedding generation + semantic search |
| `test_db_integration.py` | 5 | Real `DATABASE_URL` (Postgres) | Full CRUD: tasks, logs, agent_runs, subtasks |
| `test_manager_integration.py` | 4 | LLM **and** DB | Manager dispatch, retry loop, epic halt against a real DB |
| `test_specialist_agents.py` | 9 | 6 need LLM only, 3 need LLM **and** DB | backend_dev/QA/reviewer agents, full pipeline, retry loops, manager |
| `test_api_e2e.py` | 8 | LLM **and** DB | `POST /tasks → /run → /pipeline → /approve → /diff` over real HTTP |
| **Total** | **54** | | |

**⚠️ One real inconsistency found while compiling this list:** `test_research_agent.py`'s skip
condition (lines 9-12) does **not** use the shared `conftest.py` markers — it only checks
`RUN_PENDING_TESTS` is set, not whether a real key is actually present:
```python
SKIP = not os.environ.get("RUN_PENDING_TESTS")
pytestmark = pytest.mark.skipif(SKIP, reason="Requires RUN_PENDING_TESTS=1 + ANTHROPIC_API_KEY")
```
So setting `RUN_PENDING_TESTS=1` **without** a real key would let these 3 tests attempt a real API
call and fail with an auth error, instead of skipping cleanly like every other file in this
directory. Fix before the first real run: swap this file to use the shared `requires_anthropic`
marker from `conftest.py`, same as every other agent-test file here.

**To run once you have keys (from `tests/pending/README.md`):**
```bash
cd backend
# Add to backend/.env:
#   ANTHROPIC_API_KEY=sk-ant-your-key   (or USE_GROQ=true + GROQ_API_KEY=gsk_...)
#   DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost:5432/gridiron_dev
#   VOYAGE_API_KEY=pa-your-voyage-key   (optional — only needed for test_embeddings.py)

RUN_PENDING_TESTS=1 .venv/bin/pytest tests/pending/ -v
# or just the LLM-key-only ones:
RUN_PENDING_TESTS=1 .venv/bin/pytest tests/pending/ -v -k "agent"
```
Note (from `PROJECT.md`'s own history): running the *entire* `tests/pending/` directory in one
process can exceed 10 minutes cumulatively — it was previously run file-by-file for that reason.

---

## D. Unrelated skip (not an API-key gap — listed only so nothing is missed)

`backend/tests/test_day2_tools.py:504` — `test_...` real PDF generation test, skipped with
`"reportlab not installed — skipping real PDF test"`. This is a missing **pip package**, not a
missing credential. Fix: add `reportlab` to `backend/requirements-dev.txt` (or a dedicated
optional-extras group) and it will run in CI like everything else — no API key involved.

---

## E. (Retired 2026-07-23) The second, standalone eval system was consolidated

**Update:** `backend/evals/` (the standalone CLI this section used to describe) has been retired —
consolidated into `backend/tests/evals/` (section B2), the pytest-wired system, as part of gap-
closure Batch 6 (`files/GAPS_ALL_FILES_REPORT.md`). Its 8 `EvalCase`s covered 8 agents; 2
(`tech_debt_agent`, `performance_reviewer`) already had equivalent coverage in
`tests/evals/tasks.json`, so only the 6 genuinely new ones were ported (`bug_fix`,
`security_reviewer`, `security_architect`, `database_architect`, `user_story_generator`,
`evaluation_agent` — now `eval_006` through `eval_011` in `tasks.json`, 11 tasks total, up from 5).
While consolidating, `tests/evals/eval_runner.py`'s own agent dispatch was also fixed: it used to
keep a separate, hardcoded 12-agent map instead of `app.api.specialized_agents`'s real, comprehensive
60-agent registry (the same one the actual `/api/agents/{name}/run` endpoint uses) — now it dispatches
through that real registry instead, closing a second small "could silently drift out of sync" gap.
No new pending-test count changes here — `test_all_evals_pass_threshold` (section B2) already
iterates every task in `tasks.json`, so the 6 new cases are exercised by an existing pytest method,
not a new one.

---

## F. (Added 2026-07-27) Audit 04 orchestration-fix tests — blocked on environment, not credentials

**File:** `backend/tests/test_audit04_orchestration_fixes.py` (25 test functions across 12 classes (29 collected test cases once
pytest expands the two `@pytest.mark.parametrize` functions), one per
Audit 04 finding — see `docs/reports/AUDIT_04_ORCHESTRATION.md` §12 "Fixes Applied").

**This is a different blocking reason than sections A-D above — not an API key gap.** Every test in
this file mocks the LLM/agent layer directly (no real Anthropic/Groq call anywhere in it — verified
by grep: zero references to `anthropic.Anthropic` or real model calls). What actually blocks it:

1. **No Python interpreter exists in the environment this fix pass was written in.** Checked
   directly: no `python`/`python3`/`py` binary (only a Windows Store stub alias that errors out), no
   `.venv` anywhere in the repo, no WSL, no Docker. This means `pytest`/`mypy` could not be executed
   at all during this session — not for this new file, and not to confirm the 12 fixed files
   (`backend/app/api/agents.py`, `tasks.py`, `approvals.py`, `backend/app/agents/manager.py`,
   `backend_dev.py`, `frontend_dev.py`, `backend/app/db/models.py`, `repository.py`,
   `backend/app/repo_tools/worktree.py`, `backend/app/pipeline/conflict_guard.py`,
   `backend/app/fleet/failure_ladder.py`, `backend/app/pipeline/queue_adapter.py`) didn't introduce a
   regression in the existing 2707-test suite.
2. **A real Postgres instance is also required** (same as every other DB-touching test in this repo
   — see `tests/conftest.py`'s `DATABASE_URL` default) — most of this file's tests create/query real
   `DevTask`/`Subtask`/`Epic`/`PipelineState`/`PendingApproval` rows via an isolated engine, matching
   the established pattern in `test_launch_coder_bootstrap.py`/`test_approvals_api.py`/
   `test_git_push_approval_dispatch.py`.

**What was done instead, to compensate for not being able to execute anything:** every one of the 12
fixed files was re-read in full after editing and manually traced end-to-end (call sites, patch
targets, import scoping — this codebase's convention of deferred `from X import Y` inside function
bodies rather than module-level imports means `unittest.mock.patch` targets must point at the
*definition* site, not the call site; verified this was done correctly throughout). One real,
previously-undocumented bug was found this way (not just assumed away): `conflict_guard.py`'s own
`_get_epic_files()` checked `isinstance(f, str)` against `impacted_files` entries, but architect.py's
real `submit_architect_plan` schema always produces `{"path": ..., "reason": ...}` objects — meaning
`check_file_conflicts()` would have silently found zero conflicts ever, even after being wired in,
had this not been caught and fixed alongside ORCH-04-010. This is exactly the class of bug a live
test run would have caught immediately — treat every fix in this pass as **implemented and reasoned
through carefully, not test-confirmed**, until this file (and the existing 2707-test suite) actually
run green.

**What each test class covers** (all in `test_audit04_orchestration_fixes.py`):

| Class | Finding | What it proves |
|---|---|---|
| `TestOrch04_001_LaunchCoderCommits` | ORCH-04-001 | `launch_coder` now calls `git_add`/`git_commit` before computing the diff; skips cleanly when there's nothing to commit |
| `TestOrch04_002_TerminalState` | ORCH-04-002 | `can_transition("ready_for_review","completed")`; `/approve` 409s on an already-coded task; `/complete` endpoint's both guard conditions; a successful push auto-transitions to `completed` |
| `TestOrch04_004_RestartGuard` | ORCH-04-004 | `/restart` 409s on `planning`/`coding`/`testing`; still works from `blocked`/`failed`/`rejected` |
| `TestOrch04_007_ApprovalRace` | ORCH-04-007 | `_decide_or_409()`'s second call 409s immediately (not just after the whole background dispatch resolves); `git_push`-action rows now actually leave `"pending"` |
| `TestOrch04_014_SpawnTracked` | ORCH-04-014 | `_spawn_tracked()` retains a reference while running, releases it via the done-callback after completion |
| `TestOrch04_008_015_RetryWiring` | ORCH-04-008, ORCH-04-015 | `run_manager()`'s retry count matches `manager_max_subtask_retries` (not the larger, separate `max_retries`); backoff (`asyncio.sleep`) actually fires between retries |
| `TestOrch04_009_ConcurrencySlots` | ORCH-04-009 | `run_manager()` doesn't deadlock/leak `agent_run_slot()` across a full dev→qa→review cycle at cap=1; `run_epic_manager()` releases `epic_slot()` on the early `pending_cost_approval` return path (two sequential calls at `max_epics=1` must not hang) |
| `TestOrch04_010_ConflictGuard` | ORCH-04-010 | `_get_epic_files()` correctly extracts real dict-shaped `impacted_files` (locks in the bug fix above); `check_file_conflicts()` detects a real overlap and clears a real non-overlap |
| `TestOrch04_011_SubtaskStatusPersistence` | ORCH-04-011 | A real `Subtask` row's `status` actually flips to `"completed"` after `run_manager()` |
| `TestOrch04_012_WorktreeCleanup` | ORCH-04-012 | `create_worktree()` detects and rebuilds a stale/unregistered directory at the same path instead of silently reusing it; `/reject` calls `remove_worktree()` |
| `TestOrch04_016_QueueAdapterDocumented` | ORCH-04-016 | Sanity-checks the module still imports; documents (doesn't newly test) that real dispatch bypasses it |

**To run once Python + Postgres are available:**
```bash
cd backend
# .venv with backend/requirements.txt installed, real Postgres reachable at
# the DATABASE_URL in tests/conftest.py (or your own .env override) — no
# ANTHROPIC_API_KEY/GROQ_API_KEY needed for this file specifically.
.venv/bin/pytest tests/test_audit04_orchestration_fixes.py -v

# Then confirm no regression in the existing suite:
.venv/bin/pytest tests/ -q
mypy app/ --strict
```
If anything fails: re-read the failing test against the real source first (this file was written by
tracing the code, not by running it) — the bug is as likely to be in the test's assumptions as in the
fix itself, and either is useful signal. Update this note once it's actually been run.

---

## G. (Added 2026-07-27) Audit 05 security-fix tests — same environment blocker as section F

**File:** `backend/tests/test_audit05_security_fixes.py` (28 test functions across 10 classes).
Same category as section F — blocked on *environment* (no Python interpreter, no Postgres),
**not** credentials. No real LLM call anywhere in this file either.

**What each test class covers:**

| Class | Finding | What it proves |
|---|---|---|
| `TestLegacyRoleHeaderGating` | SEC-05-014 | `X-User-Role: approver` no longer grants approver rights by default; still works when `ALLOW_LEGACY_ROLE_HEADER=true` is explicitly set; `get_current_user` (the second, previously-dormant duplicate in `auth/dependencies.py`) returns an anonymous viewer, not a trusted legacy user, when the flag is off |
| `TestRequireAuthenticated` | SEC-05-012/013 | The new lighter dependency: no identity -> 403; any resolvable identity (any role) -> passes; `rbac_enabled=False` still bypasses (the sanctioned "local dev" escape hatch) |
| `TestAllMutatingEndpointsHaveAuth` | SEC-05-012/013 | **The single highest-value test in this file** — walks every route in the live FastAPI app and asserts every POST/PATCH/DELETE has `require_approver`/`require_authenticated`/`get_current_user` in its dependency tree, except the 2 deliberately-public auth-bootstrap routes. A real regression guard: if a future PR adds a new mutating endpoint and forgets auth, this test fails immediately instead of silently reopening the gap. Uses FastAPI's internal `route.dependant` tree — flagged as the one test in this file with framework-version risk beyond the general "not executed" caveat |
| `TestCommandStaysInBoundary` | SEC-05-005/006/018 | `cd <absolute-path-outside-worktree>` denied; relative `cd` and no-`cd` commands unaffected |
| `TestForkBombPatternFix` | Bug found while writing SEC-05-007 tests, not in the original audit | The fork-bomb denylist pattern had unescaped parens (`()` is an empty regex group, not a literal-paren match) and never matched a real fork bomb since it was written — fixed as a bonus, zero pre-existing test coverage so zero regression risk |
| `TestCommandOverrideEligibility` | SEC-05-007 | `rm -rf`/`dd`/fork-bomb are NOT overridable via chat confirmation even after a human clicks approve; `git push`/`kubectl` still are (the non-overridable set is deliberately narrow) |
| `TestChatBashCwd` | SEC-05-006 | The chat agent's bash tool now ignores an LLM-supplied `cwd` override entirely — always uses `repo_path` |
| `TestGuardrailsDelegatesToStrongEngine` | SEC-05-004 | `guardrails.py` (base_graph.py's policy gate for all 72+ agents) now catches `curl https://`, `sudo`, and private-key filenames — all previously missed by the old standalone weaker implementation; the chaining-vulnerable `check_bash_allowlist` now rejects `cmd && malicious` (confirmed zero real callers today, so this was a dormant not live gap) |
| `TestCustomSecretNameDenylist` | SEC-05-011 | `DATABASE_URL` (any case) rejected when saved as a custom secret; a normal name still works |
| `TestChangePasswordEndpoint` | SEC-05-015 | The legacy `X-User-Role` header cannot be used to change a password (needs a real JWT); the new-password-length validation is reachable |

**A second, more subtle risk this fix pass had to close, found and fixed while writing these
tests (not by running anything):** adding a real auth dependency to ~50 previously-open mutating
endpoints would, on its own, have broken the *entire pre-existing 2700+-test suite* — almost none
of those tests pass any auth header, since nothing was gated before. Fixed by adding
`os.environ.setdefault("RBAC_ENABLED", "false")` to `tests/conftest.py` — the same explicit,
already-documented "local dev" bypass this project's own RBAC design treats as legitimate, scoped
to the test environment only (production's own default, `rbac_enabled=True`, is untouched — that
env var default never runs outside pytest). Real enforcement is verified separately, by explicitly
mocking `rbac_enabled=True` in `test_rbac.py` and this file. **This conftest.py change is itself
unexecuted and should be the very first thing confirmed when this suite is finally run** — if it's
wrong, most of the existing suite will fail with 403s, which is an unambiguous, loud signal (not a
silent one) that would show up immediately.

**To run once Python + Postgres are available:**
```bash
cd backend
.venv/bin/pytest tests/test_audit05_security_fixes.py -v

# Then confirm the conftest.py RBAC_ENABLED=false fix actually prevents regression
# in the pre-existing suite (this is the most important check in this whole section):
.venv/bin/pytest tests/ -q

# And confirm test_rbac.py's own pre-existing 6 tests (which mock settings directly,
# unaffected by the conftest.py change either way) still pass:
.venv/bin/pytest tests/test_rbac.py -v

mypy app/ --strict
```

---

## Full tally

| Category | Count | Blocked on |
|---|---|---|
| A — Anthropic-only (stubs, need writing too) | 4 | Real `ANTHROPIC_API_KEY` |
| B1 — Groq integration tests | 9 | Real `GROQ_API_KEY` (or swap to Anthropic once available) |
| B2 — Groq eval tests (now covering 11 tasks in `tasks.json`, up from 5) | 4 | Real `GROQ_API_KEY` |
| C — `tests/pending/` full directory | 54 | Real LLM key (Anthropic or Groq) + some need DB/Voyage too |
| D — Unrelated (missing pip package) | 1 | `pip install reportlab` — not an API-key issue |
| F — Audit 04 orchestration-fix tests (2026-07-27) | 29 (25 functions) | **Python interpreter + Postgres in the audit environment — no API key needed** |
| G — Audit 05 security-fix tests (2026-07-27) | 28 | **Python interpreter (+ Postgres for the TestClient-based tests) — no API key needed** |
| **Total pytest-collected, blocked on real credentials (A-D)** | **71** (55 skipped + 17 deselected − 1 reportlab) | |
| **Total blocked on execution environment only, no credentials (F+G)** | **57** | |

**Bottom line:** every one of these is real, written code — nothing here is a stub pretending to be
a test (except the 4 in section A, which are honest TODO stubs, not disguised ones). Once you have
a real `ANTHROPIC_API_KEY` (recommended — unlocks everything, including the 4 Anthropic-only tests
Groq can never satisfy), the path is: set the env vars from section C, run
`RUN_PENDING_TESTS=1 pytest tests/pending/ -v`, then `pytest tests/test_day0_groq_integration.py
tests/evals/test_evals.py -v -m slow` if you also want the Groq-path tests exercised (now 11 real
agents' worth, not 5), then fix the one `test_research_agent.py` skip-condition inconsistency in
section C before trusting its "clean skip" behavior, then write real assertions for the 4 stubs in
section A.
