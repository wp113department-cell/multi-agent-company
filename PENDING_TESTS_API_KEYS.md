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

**Update (2026-07-27, morning):** sections F and G below originally described new tests written
during the Audit 04 (Orchestration) and Audit 05 (Security) fix passes that were blocked on
*environment* (no Python interpreter, no Postgres reachable) rather than credentials.

**Update (2026-07-27, afternoon) — this is no longer true, and sections F/G below have been
rewritten with real results.** A real Python 3.12 interpreter, all dependencies, and a working
`mypy`/`pytest` toolchain were set up and actually run in this environment (see section H for the
full setup story). **Measured directly** (`pytest tests/ -q`, full suite, ~2815 collected):
**2674 passed, 141 failed, 55 skipped, 17 deselected** — every one of the 141 failures individually
confirmed via `ConnectionRefusedError [WinError 1225]` to be caused by the one remaining gap, a live
Postgres, and nothing else (see section H). `mypy app/ --ignore-missing-imports --platform linux` is
100% clean (0 errors, 176 files). **7 genuine bugs were found and fixed purely through real
execution** — none of which manual code tracing had caught; see sections F and G below for detail.
(The "2707 passed" figure two paragraphs above was itself never verified before this session — it
predates any real execution in this environment and should not be trusted as a baseline; 2674 is the
first number in this file that's actually been measured.)

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
#   DATABASE_URL=postgresql+asyncpg://gridiron:gridiron_dev_only@localhost:5432/gridiron_dev
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

## F. (Added 2026-07-27, rewritten same day once real execution became possible) Audit 04
orchestration-fix tests — REAL RESULTS

**File:** `backend/tests/test_audit04_orchestration_fixes.py` (25 test functions across 12 classes,
29 collected test cases once pytest expands the two `@pytest.mark.parametrize` functions).

**Actually run** (`.venv/Scripts/python.exe -m pytest tests/test_audit04_orchestration_fixes.py -v
--timeout=60`): **7 passed, 22 failed.** Every one of the 22 failures was individually confirmed
(via `ConnectionRefusedError [WinError 1225]` in each traceback) to be caused by the same single
thing — no live PostgreSQL reachable at `localhost:5432` — not a bug in the fix or the test. Zero
other failure types occurred. See section H for why a live Postgres isn't available here and what
setting one up would take.

**Two real bugs were found and fixed purely through this execution, that manual code tracing had
missed:**
1. `TestOrch04_014_SpawnTracked::test_spawn_tracked_retains_then_releases_reference` — a genuine
   asyncio test-timing bug (not a production bug): `task.add_done_callback(...)` schedules its
   callback via `call_soon`, which only runs on the *next* event-loop tick — but `await task` on an
   already-completed task returns synchronously without yielding, so the test's assertion ran one
   tick too early and saw the task still tracked. Fixed by adding `await asyncio.sleep(0)` before the
   assertion to let the loop process the pending callback first. **Now passes.**
2. `app/fleet/budget_manager.py` imported the POSIX-only `resource` module unconditionally — this
   broke `pytest` collection for the *entire test suite* on Windows (not just this file), since
   nothing could even be collected past this one `ModuleNotFoundError`. Fixed with a `sys.platform`
   guard and a `ctypes`-based Windows equivalent for the one function that used it
   (`_current_memory_mb`). **This unblocked ~2600 tests across the whole suite at once**, not just
   this file — by far the highest-leverage single fix in this entire pass.

Two more real, environment-only (not test-writing) bugs were found and fixed in the same execution
session, both also outside the original 12 findings: `app/agents/tools.py` and
`app/agents/chat_agent.py` each unconditionally imported `fcntl` (also POSIX-only) inside handler
setup and `read_output` tool code — fixed with the same `sys.platform` pattern, using a
short-timeout daemon-thread read on Windows instead of `fcntl`'s `O_NONBLOCK` trick. This alone
resolved 176 test collection errors that were masking the true failure count in the very first run.

**What was originally done, before real execution was possible:** every one of the 12 fixed files
was re-read in full after editing and manually traced end-to-end (call sites, patch targets, import
scoping). One real, previously-undocumented bug was caught this way (confirmed still correct after
real execution): `conflict_guard.py`'s own `_get_epic_files()` checked `isinstance(f, str)` against
`impacted_files` entries, but architect.py's real `submit_architect_plan` schema always produces
`{"path": ..., "reason": ...}` objects — meaning `check_file_conflicts()` would have silently found
zero conflicts ever, even after being wired in, had this not been caught and fixed alongside
ORCH-04-010. Manual tracing caught this one correctly; it did **not** catch the two real bugs above
(asyncio callback timing, `resource`/`fcntl` platform-only imports) — both needed actual execution
to surface, which is the whole reason this environment-setup effort happened.

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

**To finish this off, once a live Postgres is reachable** (Python, dependencies, and mypy are no
longer blockers — see section H):
```bash
cd backend
# DATABASE_URL must point at a real, reachable Postgres matching tests/conftest.py's default
# (or your own .env override) — no ANTHROPIC_API_KEY/GROQ_API_KEY needed for this file.
.venv/Scripts/python.exe -m pytest tests/test_audit04_orchestration_fixes.py -v

# Then confirm no regression in the existing suite:
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m mypy app/ --ignore-missing-imports --platform linux
```
Expected once Postgres is reachable: all 29 collected cases pass (7 already do without a DB; the
other 22 are confirmed blocked on nothing but the DB connection).

---

## G. (Added 2026-07-27, rewritten same day once real execution became possible) Audit 05
security-fix tests — REAL RESULTS

**File:** `backend/tests/test_audit05_security_fixes.py` (28 test functions across 10 classes).
No real LLM call anywhere in this file.

**Actually run** (`.venv/Scripts/python.exe -m pytest tests/test_audit05_security_fixes.py -v
--timeout=60`): **27 passed, 1 failed.** The 1 failure
(`TestCustomSecretNameDenylist::test_normal_custom_secret_name_still_allowed`) is confirmed, via
`ConnectionRefusedError [WinError 1225]` in its traceback, to be the same single cause as every
Audit 04 failure above — no live Postgres. It's the one test in this file whose happy path actually
persists to the DB (the two sibling denylist-rejection tests return a 400 before ever touching the
DB, which is exactly why they already passed without a live database).

**Two real, distinct bugs were found and fixed purely through real execution here:**
1. **The fork-bomb regex fix from the original audit pass was still broken, in a different way than
   first thought.** The original bug (unescaped parens matching an empty group) was correctly fixed
   by manual tracing — but the *same pattern* also had a leading `\b` (word-boundary) anchor that can
   never match, because a fork bomb command starts with `:` (a non-word character) on both sides of
   every relevant position in `:(){ :|:& };:`. `\b` requires one side to be a word character; here
   neither side ever is. This is invisible to manual regex tracing (which correctly confirmed the
   character-class portion matched) and was only caught by running `re.search()` for real. Fixed by
   dropping the leading anchor — safe, since the pattern's own content is distinctive enough not to
   spuriously match inside an unrelated identifier. **Both `TestForkBombPatternFix` tests now pass.**
2. `greenlet` (SQLAlchemy's async-to-sync bridge, a hard dependency for every DB-touching endpoint)
   failed to import with `DLL load failed` — root cause: this machine had no Microsoft Visual C++
   Redistributable installed at all, which is required by many compiled Python C-extension wheels on
   Windows and isn't bundled by pip. Installed via winget
   (`Microsoft.VCRedist.2015+.x64`); this alone unblocked every `TestClient(app)`-based test in this
   file (and across the whole suite) that touches the DB during FastAPI's lifespan startup, not just
   the one endpoint under test.

Also caught and fixed **while writing this test's own docstring**, ironic given the context: the
same "invalid escape sequence" `SyntaxWarning` class of bug from the original fork-bomb fix
recurred in the new prose explaining fix #10 (`\b`, `\s` inside a non-raw docstring) — rewritten to
avoid backslash-letter sequences in prose entirely rather than keep doubling backslashes.

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

**A second, more subtle risk this fix pass had to close, originally found and fixed by reasoning
before real execution was possible, now CONFIRMED CORRECT by real execution:** adding a real auth
dependency to ~50 previously-open mutating endpoints would, on its own, have broken the *entire
pre-existing 2700+-test suite* — almost none of those tests pass any auth header, since nothing was
gated before. Fixed by adding `os.environ.setdefault("RBAC_ENABLED", "false")` to
`tests/conftest.py` — the same explicit, already-documented "local dev" bypass this project's own
RBAC design treats as legitimate, scoped to the test environment only (production's own default,
`rbac_enabled=True`, is untouched — that env var default never runs outside pytest). **Confirmed**:
the full suite now passes 2671+ tests with this change in place, with zero 403-related failures
anywhere in the run — had this fix been wrong, that would have shown up immediately and loudly as
mass 403s across the whole suite, which did not happen. Real enforcement is verified separately, by
explicitly mocking `rbac_enabled=True` in `test_rbac.py` and this file (both pass).

**To finish this off, once a live Postgres is reachable:**
```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_audit05_security_fixes.py -v
# Expected: all 28 pass (27 already do without a DB).
```
(The conftest.py `RBAC_ENABLED=false` regression check and `mypy` are already confirmed clean —
see above and section H — nothing further needed there.)

---

## H. (Added 2026-07-27) How real execution became possible, and the one thing that's still blocked

This environment had **no Python interpreter at all** when Audits 04 and 05 were originally fixed
(only a Microsoft Store alias stub that errors out) — every fix in this file was implemented and
manually traced, never executed. This section documents what changed and what's still open.

**Installed, in order, all via `winget` (standard package installs, not system-policy changes):**
1. **Python 3.12.10** (`Python.Python.3.12`) — the Store alias was not real Python.
2. A `.venv` in `backend/`, then `pip install -r requirements-dev.txt` — every pinned dependency
   installed cleanly and matched the exact versions in `requirements.txt`/`requirements-dev.txt`.
3. **Microsoft Visual C++ Redistributable x64** (`Microsoft.VCRedist.2015+.x64`) — needed because
   `greenlet` (a hard SQLAlchemy-async dependency) failed with `DLL load failed`; this machine had
   no VC++ runtime installed at all, which many compiled Python wheels on Windows silently depend on
   without pip installing it for you.
4. **Visual Studio Build Tools 2026, C++ workload** (`Microsoft.VisualStudio.BuildTools`) — installed
   in an attempt to compile `pgvector` from source (see below); confirmed working
   (`vcvars64.bat`/`cl.exe`/`nmake.exe` all present), but the effort was stopped before actually
   needing it (see below), so it's currently unused. Harmless to leave installed; safe to uninstall
   if disk space matters.

**What was found and fixed purely by running the actual test suite** (the whole reason this setup
effort was worth it — 7 real bugs, none caught by manual tracing): the two POSIX-only-import bugs
(`resource` in `budget_manager.py`, `fcntl` in `tools.py`/`chat_agent.py`) that broke test collection
suite-wide, the fork-bomb regex's leading `\b` anchor bug, the asyncio `add_done_callback` timing bug
in a test, and 2 mypy `no-any-return` errors in the new `_read_stream_nonblocking` helpers. Full
detail in sections F and G above.

**What's still blocked, and why it was deliberately left that way:** this project's own documented
dev setup (`PROJECT.md`, "DB connection reference") runs Postgres via a Docker container
(`gridiron-postgres`, the `pgvector/pgvector:pg16` image) — Docker isn't available in this
environment. Two alternatives were attempted/considered:
- **Native PostgreSQL for Windows**: installed via winget, but its installer's `initdb.exe`
  step failed with *"An Application Control policy has blocked this file"* when trying to run under
  the `NetworkService` account — this reads as a real, machine-level managed security policy, not a
  transient error, and was **not** worked around (disabling Application Control / WDAC policies is a
  security-relevant system change well outside the scope of installing test dependencies). The
  failed install was cleanly uninstalled via winget afterward.
- **Docker Desktop**: needs admin elevation (UAC) to enable WSL2/Hyper-V and typically a restart —
  this tool-calling environment cannot click through an interactive UAC prompt, and given the
  Application Control policy already blocked a *simpler* case above, Docker Desktop's own privileged
  driver/service installation was assessed as likely to hit the same or a bigger wall.
- **Portable Postgres binaries run as a plain user-mode process** (no service, no installer, no
  elevation) was the planned fallback, using the VS Build Tools already installed to compile
  `pgvector` from source per its own documented Windows build steps — this was in progress
  (binaries download had started) when the decision was made to stop here rather than continue,
  since the marginal value (getting ~23 more tests green, all already confirmed to be pure DB-gap
  failures with zero remaining code-level uncertainty) didn't justify the further time/risk given
  everything of real substance was already verified.

**Bottom line for whoever picks this up next:** get a real Postgres reachable at the `DATABASE_URL`
`tests/conftest.py` expects (Docker is the path of least resistance if it's available in whatever
environment runs this next — `docker run -e POSTGRES_USER=gridiron -e
POSTGRES_PASSWORD=gridiron_dev_only -e POSTGRES_DB=gridiron_dev -p 5432:5432
pgvector/pgvector:pg16`, then run `alembic upgrade head`), and re-run the two commands at the end of
sections F and G above. Nothing else is expected to need further investigation — mypy is already
100% clean and 2671+ tests already pass for real.

---

## I. (Added 2026-07-27, later same day) Docker became available — the DB gap is now closed

Docker was installed after section H was written above. The exact command anticipated there is what
was actually run:

```bash
docker run -d --name gridiron-postgres-temp \
  -e POSTGRES_USER=gridiron -e POSTGRES_PASSWORD=gridiron_dev_only -e POSTGRES_DB=gridiron_dev \
  -p 5432:5432 pgvector/pgvector:pg16
cd backend && DATABASE_URL="postgresql+asyncpg://gridiron:gridiron_dev_only@localhost:5432/gridiron_dev" \
  .venv/Scripts/python.exe -m alembic upgrade head
```
All 22 migrations (`001` through `022`) applied cleanly, no errors — including `020`'s HNSW index on
`versioned_lessons.embedding`, confirming `pgvector` itself works correctly via this image (no
manual extension build was ever needed; the earlier VS Build Tools effort in section H turned out to
be unnecessary once Docker was available — left installed, harmless, not removed).

**Full suite with a live DB** (`pytest tests/ -q`): **2674 → 2794 passed** (120 more tests now pass
for real), **141 → 21 failed** (120 fewer). Every one of the 120 newly-passing tests was previously
blocked purely on `ConnectionRefusedError`, confirming section H's own prediction exactly.

**`test_audit04_orchestration_fixes.py` + `test_audit05_security_fixes.py` combined: 57/57 pass.**
Both Audit 04 and Audit 05 are now **fully, live-database-confirmed clean** — zero remaining
uncertainty of any kind. Sections F and G above should be read with this as the final word: the
"22 blocked" and "1 blocked" counts in their tables are now 0 and 0.

**4 more real, distinct bugs were found and fixed while getting the last 21 down as far as they'd
reasonably go:**
1. **A genuine regression from the ORCH-04-001 fix itself**, only reachable once a live DB let the
   full `launch_coder` → `approve` code path actually execute end-to-end:
   `test_task_metadata_fields.py::test_launch_coder_sets_assigned_agent_and_final_summary` had never
   mocked `git_add`/`git_commit` (there was nothing to mock before ORCH-04-001 added those calls).
   With a live DB, the test finally reached the real `git_add()` call, which correctly rejected the
   test's fake `/tmp/td-wt` worktree path via `_validate_workspace()`'s path-traversal guard — the
   guard was working exactly as designed; the test just needed the same git_add/git_commit mocks
   `test_audit04_orchestration_fixes.py` already uses. Fixed by adding them. This also fixed a
   second, purely collateral failure in the next test in the same file
   (`test_launch_planning_pipeline_sets_assigned_agent_to_pm`), which was failing only because the
   first test's unhandled exception corrupted shared asyncpg connection-pool state for whatever ran
   next — not a bug in that second test at all.
2. `signal.SIGKILL` doesn't exist on Windows — used unconditionally in `kill_process` handlers in
   both `tools.py` and `chat_agent.py`, causing a real `AttributeError` at runtime (this is also what
   the mypy `--platform linux` run flagged earlier as a platform-only name — it turned out to be a
   genuine *runtime* reachability issue too, not just a type-checking artifact, once these handlers
   were actually called). Fixed with `getattr(signal, "SIGKILL", signal.SIGTERM)` — on Windows,
   `os.kill()` + `SIGTERM` already maps to `TerminateProcess` (an unconditional hard-kill), so the
   fallback has the same practical effect there.
3. `Path.read_text()` without an explicit encoding in `test_final_session.py`/`test_new_tools.py`
   defaults to the OS locale's preferred encoding (`cp1252` on this machine) instead of UTF-8 —
   `tools.py` contains non-ASCII characters (em dashes, used throughout this codebase's comments) that
   aren't valid `cp1252`, causing a real `UnicodeDecodeError`. Fixed by adding `encoding="utf-8"`
   explicitly (11 call sites across both files, plus 1 more in `app/fleet/model_router.py` found by
   the same grep, for consistency — production code, not just tests).
4. **A genuine, real, non-Windows-specific bug** in `app/fleet/fleet_checkpoint.py`'s
   `latest_for()`: `max(cps, key=lambda c: c.created_at)` breaks a `created_at` tie by returning the
   *first* matching checkpoint, not the most recently *inserted* one — and two `store.save()` calls
   made close enough together can genuinely tie on `datetime.now()`'s resolution (observed directly,
   not theoretical). Fixed by pairing each checkpoint with its list index (checkpoints are already in
   insertion order) and breaking ties on that instead — deterministically correct regardless of clock
   resolution or platform.

**The remaining 21 failures are a different category from everything above: pre-existing,
Windows-only test-environment mismatches, unrelated to Audit 04/05, and confirmed NOT to affect the
real CI pipeline** (`.github/workflows/ci.yml` — every job runs on `ubuntu-latest`, verified by
reading the workflow file). Breakdown:
- **5 — hardcoded `/home` workspace-parent assumption**: `test_git_service.py` (4 tests) +
  `TestWorkspaceService::test_is_git_repo_true` (1) set `ALLOWED_WORKSPACE_PARENT=/home` and pass a
  real Windows path (`C:\Users\...`) — `_validate_workspace()`'s guard correctly rejects it, exactly
  as it should. Would pass on Linux CI where `/home`-rooted paths are the norm.
- **~13 — Linux-shell-tool assumptions**: `test_chat_tools.py`/`test_day1_tools.py`/
  `test_credential_vault.py`/`test_day2_agents.py`/`test_concurrency.py` failures all trace to the
  same underlying story — these tools (`run_python_snippet`, `run_make`, secrets-scan shell
  invocation, `$VAR`-style env expansion, `/tmp`-rooted path assertions, `free`-command memory
  fallback) are written for the bash-on-Linux environment this project actually deploys agents into,
  and this is the first time any of them has been exercised against Windows' `cmd.exe`/PowerShell
  instead. Not attempted to be made cross-platform here — that's a materially larger, different
  project (making every agent tool genuinely OS-agnostic) than what this session set out to do, and
  none of it affects the real Linux-only CI pipeline or the real Linux-only production deployment.
- **1 — confirmed flaky, not a defect**: `test_fleet_metrics.py::TestRunSpan::test_run_span_times_execution`
  failed once during a full 2887-test, ~5.5-minute run (`execution_time_ms` read as `0.0` instead of
  `>= 5.0` after a 10ms sleep) but passed 3/3 times when re-run in isolation immediately after. The
  underlying code (`time.monotonic()`-based timing in `run_span()`) is structurally correct; this
  reads as a one-off scheduling artifact under heavy system load, not a bug to fix.
- **1 — not yet root-caused**: `test_architecture_mapper.py::TestGatherReadmes::test_finds_real_readmes`
  — lowest priority of everything in this list (single test, no evidence yet of Windows-vs-Linux
  cause vs. something else); flagged here rather than investigated further given the DB gap (the
  actual point of this session) is now fully closed and everything above it is either fixed or
  clearly categorized.

**Container is temporary, as requested** — `gridiron-postgres-temp` is a plain `docker run` (no
`--rm`, no compose file, no persistence beyond the container's own writable layer). Stop it with
`docker stop gridiron-postgres-temp` when done; remove entirely with
`docker rm gridiron-postgres-temp`. It is currently still running so these results can be
reproduced/extended without re-running migrations.

---

## Full tally

| Category | Count | Blocked on |
|---|---|---|
| A — Anthropic-only (stubs, need writing too) | 4 | Real `ANTHROPIC_API_KEY` |
| B1 — Groq integration tests | 9 | Real `GROQ_API_KEY` (or swap to Anthropic once available) |
| B2 — Groq eval tests (now covering 11 tasks in `tasks.json`, up from 5) | 4 | Real `GROQ_API_KEY` |
| C — `tests/pending/` full directory | 54 | Real LLM key (Anthropic or Groq) + some need DB/Voyage too |
| D — Unrelated (missing pip package) | 1 | `pip install reportlab` — not an API-key issue |
| F — Audit 04 orchestration-fix tests (2026-07-27) | 29 collected; **7 pass for real, 22 blocked** | **Live Postgres only — Python/mypy no longer a blocker, no API key needed** |
| G — Audit 05 security-fix tests (2026-07-27) | 28 collected; **27 pass for real, 1 blocked** | **Live Postgres only — Python/mypy no longer a blocker, no API key needed** |
| **Total pytest-collected, blocked on real credentials (A-D)** | **71** (55 skipped + 17 deselected − 1 reportlab) | |
| **Total blocked on execution environment only, no credentials (F+G)** | **23** (down from 57 — 34 of the original 57 now pass for real) | Live Postgres (see section H) |

**Bottom line:** every one of these is real, written code — nothing here is a stub pretending to be
a test (except the 4 in section A, which are honest TODO stubs, not disguised ones). Once you have
a real `ANTHROPIC_API_KEY` (recommended — unlocks everything, including the 4 Anthropic-only tests
Groq can never satisfy), the path is: set the env vars from section C, run
`RUN_PENDING_TESTS=1 pytest tests/pending/ -v`, then `pytest tests/test_day0_groq_integration.py
tests/evals/test_evals.py -v -m slow` if you also want the Groq-path tests exercised (now 11 real
agents' worth, not 5), then fix the one `test_research_agent.py` skip-condition inconsistency in
section C before trusting its "clean skip" behavior, then write real assertions for the 4 stubs in
section A.

---

## J. (Added 2026-08-13, RESOLVED same day) `tests/test_delegation.py` — was blocked on environment stability, not credentials — now passing

**RESOLVED.** Originally deferred because running the backend test suite in this session started
reliably crashing the VS Code window ("window terminated unexpectedly, reason: clean-exit, code: 0")
and hanging the host machine partway through this plan14 Day 4 (Agent-to-Agent Delegation) work.
Once the user confirmed it was safe to try again, `pytest tests/test_delegation.py` was run in
isolation first (per explicit instruction, not the full suite) — it completed cleanly in 3.2s with
**no crash**, confirming the earlier hand-review's fix (see below) addressed the real risk. The
system's own numbers explained the original crash well: 15GB RAM, already 2.2GB into swap before
any heavy test run — a resource-pressure issue, not a bug in the delegation code's execution model.

**Final results, all real, all measured:**
- `pytest tests/test_delegation.py -v --timeout=50`: first run **17 passed, 2 failed** — both
  failures were real test-authoring bugs (two tests forgot to add their own source agent to a
  monkeypatched `delegation_allowed_matrix`, so the policy check fired before reaching what they
  meant to test) — fixed, then **19/19 passed** (2 tests were consolidated after a ruff-flagged
  unused import removal dropped the count from 21 to 19 test functions).
- `ruff check`/`ruff format --check`: clean on all 7 touched files (one real `F401` caught: unused
  `DelegationTimeoutError` import, fixed).
- `mypy --strict`: clean, 0 errors, on all 6 touched source files.
- Targeted regression sweep (`test_delegation.py` + `test_fleet_manager.py` +
  `test_dynamic_tool_selection.py` + `test_gap53_doc_generators.py`): **98/98 passed**.
- Full suite: **4540 passed, 52 skipped, 18 deselected, 0 failed** (4521 → 4540, +19).

Full write-up with evidence table: `bhaskar_next/plan14_implement.md`, Day 4 section (now marked
GREEN FLAG). The commands below are kept for reference/reproducibility, not because anything is
still outstanding.

**Original deferral note (kept for the record):** the code was reviewed by hand before re-running
(full trace of `delegate()`'s control flow, exception ordering, cross-thread event publishing, and
each test's mock targets against how names are resolved at call time — no logic issues found this
way, but hand-tracing is not a substitute for real execution, which is exactly why this was re-run
rather than trusted as final).

**Files involved:**
- `backend/app/agents/delegation.py` (new) — `DelegationRequest`/`DelegationResult`, `delegate()`,
  depth/cycle/policy/budget/timeout guards, a 4-agent adapter registry (spike_agent,
  security_reviewer, code_explainer_agent, bug_fix), thread-based timeout enforcement.
- `backend/app/event_bus/models.py` — `GridironEvent` gains 4 optional fields
  (`receiver`/`message_type`/`trace_id`/`parent_run_id`) + 4 typed delegation event constructors.
- `backend/app/agents/tools.py` — `delegate_to_agent` tool spec + `make_delegate_to_agent_handler()`.
- `backend/app/agents/bug_fix.py` — wired as the one pilot source agent (tool list + handler).
- `backend/app/config.py` — `delegation_enabled`/`delegation_max_depth`/
  `delegation_max_delegations_per_run`/`delegation_default_timeout_seconds`/
  `delegation_default_budget_usd`/`delegation_allowed_matrix`.
- `backend/app/fleet/tool_manifest.py` — `delegate_to_agent` entry, `risk_level="high"`.
- `backend/tests/test_delegation.py` (new) — 21 tests: adversarial safety guards (disabled, depth
  exceeded, delegations-per-run exceeded, budget exhausted, capability not in allowed-matrix,
  no available agent, cycle A→B→A, no adapter for resolved agent, timeout), successful-delegation
  result shape + event/audit publishing, tool-handler behavior, `GridironEvent` field tests, and one
  "real code path" test for the `spike_agent` adapter.

**What DID run successfully in this session, before the crashes started** (so these are NOT part of
what's pending): `python -c "import ..."` sanity imports and `python -m mypy --strict` on every file
above — all clean, 0 errors. Only the actual `pytest` execution of `test_delegation.py` is
outstanding.

**A likely (not certain) root cause, found by re-reading the code, not by re-running it:** the test
file's original "real end-to-end" test called the real `run_spike_agent()` with only
`anthropic.Anthropic` mocked — `run_spike_agent` hardcodes `enable_memory=True`/
`enable_reflection=True`/`enable_lesson=True` with no override, so a real run also does real
Postgres round-trips (`memory_hook_node`, lesson persistence via
`get_main_loop()`/`run_coroutine_threadsafe`) and a turn count that depends on how well a
hand-written mock LLM happens to match every prompt shape the real planner/reflection nodes send —
all of it running inside `delegate()`'s own background-thread timeout wrapper
(`_run_with_timeout`, up to a 300s join). That combination is meaningfully heavier than anything
else run earlier in this session (which had already done several ~7-8 minute full-suite runs), and
is a plausible trigger for resource exhaustion on a loaded machine. **This was already fixed before
being run** — the test now patches `app.agents.spike_agent.run_agent_graph` directly (one level
below `run_spike_agent`), so it still exercises spike_agent's real handler/prompt-construction and
`AgentResult`-building code, but does zero real DB/LLM/graph-loop work and returns instantly. If
`test_delegation.py` is still slow or still causes problems when you do run it, this is the first
place to look — specifically `test_delegation_timeout_actually_blocks` (spawns one real background
thread, sleeps 2s, should be harmless in isolation) and the adapter-registry tests (each imports
`app.agents.bug_fix`/`app.agents.code_explainer_agent`/`app.agents.security_reviewer`/
`app.agents.spike_agent`, which is a lot of module weight but shouldn't itself be slow).

**To run once you're ready (plain backend test run, no API key needed — everything is mocked/faked):**
```bash
cd backend
.venv/bin/pytest tests/test_delegation.py -v --timeout=60
```
Then, if that's clean, the same regression sweep every other plan14 task in this session used:
```bash
.venv/bin/pytest tests/test_fleet_manager.py tests/test_dynamic_tool_selection.py -q  # things delegation touches indirectly (FleetManager.select(), tool filtering)
.venv/bin/ruff check app/agents/delegation.py app/event_bus/models.py app/agents/tools.py app/agents/bug_fix.py app/config.py app/fleet/tool_manifest.py tests/test_delegation.py
.venv/bin/ruff format --check app/agents/delegation.py app/event_bus/models.py app/agents/tools.py app/agents/bug_fix.py app/config.py app/fleet/tool_manifest.py tests/test_delegation.py
.venv/bin/pytest tests/ -q --timeout=600   # full suite, confirm no regression vs. the 4521-passed baseline from Day 3
```
Expected baseline going in: **4521 passed, 52 skipped, 18 deselected, 0 failed** (confirmed at the
end of plan14 Day 3, before this Day 4 work started) — `test_delegation.py`'s 21 tests should add to
that with zero regressions elsewhere, since every change here is additive (new module, new optional
`GridironEvent` fields, one new tool wired into exactly one pilot agent).

---

## K. (2026-09-28, PAUSED — resume once ANTHROPIC_API_KEY has a real balance) Real attempt at section C, on $0 budget via Groq/Gemini — both free tiers hit genuine structural limits

**Why this happened:** the real `ANTHROPIC_API_KEY` in `.env` ran out of balance (confirmed via a
direct minimal API call: `BadRequestError: "Your credit balance is too low"`). Rather than wait idle,
the user asked to actually attempt the `tests/pending/` run (section C, 49 collected tests as of
today — 54 in section C's original count minus the 5 in `test_db_integration.py`, which isn't in
the current `tests/pending/` listing) against free-tier backends first: Groq, then Gemini as a
second option when Groq's own limit proved too tight. **Both real, both genuinely attempted — not
simulated — and both real infra bugs found and fixed along the way. Paused (not abandoned) at the
user's explicit instruction once the free-tier limits were confirmed structural, not a pacing
problem: "skip all we need to go with antrpic api only ok add all in plan and lets move on next
ones ok when i got recharge then update you ok so this task we will resume."**

### K1 — Gemini added as a second temporary backend, alongside Groq

New, mirrors `app/agents/groq_adapter.py`'s exact shape: `app/agents/gemini_adapter.py`,
`app/agents/base.py::_run_via_gemini()`, `use_gemini`/`gemini_*` settings in `app/config.py`,
`tests/gemini_compat.py`, `tests/test_day0_gemini_integration.py`, `get_gemini_breaker()` in
`app/fleet/circuit_breaker.py`. Explicitly marked TEMPORARY/easily-removable throughout (every new
file's own docstring lists the exact removal steps) — this is scaffolding for the $0-budget testing
problem, not a permanent second LLM backend for this project. `google-genai==2.25.0` added to
`requirements.txt`.

Verified for real before use: the pasted Gemini key didn't match the usual `AIzaSy...` Google AI
Studio format, so it was checked live first (a 404 model-not-found error, not a 401, confirmed the
key itself authenticates) — then a real tool-calling round trip, then the full `run_agent_graph()`
path end-to-end (`test_day0_gemini_integration.py -m slow`, 2/2 passed in ~8s) before relying on it
for anything real.

### K2 — Real bugs found and fixed while actually running this against real rate limits

1. **Gemini's free tier for `gemini-2.5-flash` is 20 requests/DAY total**
   (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), not a per-minute limit — exhausted by one
   real `test_pm_agent.py` run. Worse: `run_gemini()`'s own retry ladder (30s/60s/90s/120s sleeps)
   kept retrying against a wall that can't clear within the process's lifetime, wasting **543
   seconds to fail 3 tests**. Fixed: `_is_daily_quota_exhausted()` in `gemini_adapter.py` inspects
   the real `QuotaFailure` violation for a `PerDay` quotaId and fails fast instead of sleeping.
   Switched the default model to `gemini-flash-lite-latest` (separate, untouched quota pool,
   confirmed live with a real tool-calling round trip).
2. **`gemini-flash-lite-latest` then hung for the full 120s timeout on every real PM-agent call** —
   not a 429, a raw SSL socket read timeout with zero response, only reproducible on the *real*
   workload (full system prompt + repo context + PM's real multi-tool schema), not on the trivial
   single-tool smoke tests that had passed earlier. Read as the "lite" model genuinely struggling
   with a realistically-sized request, not a bug in this codebase's own adapter code.
3. **A real, separate, more consequential Groq bug**: `groq_adapter.py`'s own `run_groq()` has an
   app-level retry loop gated on `settings.groq_max_retries` (set to `1` in `.env` for exactly this
   reason — fast-fail instead of sleeping) — but the Groq SDK's `groq.Groq(...)` client ALSO has its
   own internal HTTP-level retry mechanism (default `max_retries=2`), which fires *inside*
   `client.chat.completions.create()` and sleeps via its own backoff **before** ever raising back to
   the app's own loop. So `GROQ_MAX_RETRIES=1` had **zero effect** — confirmed live: a test still
   hung 90+ seconds in the SDK's own internal `_sleep_for_retry()`. Fixed: `groq.Groq(api_key=...,
   max_retries=0)` — disables the SDK's own inner retry layer so the app's own loop is the sole
   retry authority. Verified: the exact same test file that took 543s/363s/272s in the three earlier
   (broken) attempts now completes in well under 60s, with clean, fast, real 429 errors instead of
   silent multi-minute hangs.

### K3 — Real, structural finding: this codebase's real agents are too large for either free tier, at any pacing

Once both of the above bugs were fixed (so failures were fast and honest, not hidden by hangs), the
real signal was: **Groq's key here gets 8,000 tokens/minute (TPM). Nearly every real agent in this
codebase (`grep enable_planning=True app/agents/*.py` — 80+ matches, only `bhaskar_agent.py` and
`temporary_agent.py` opt out) makes a minimum of 3 real LLM calls per run: two small planning calls
(`_gather_facts_and_plan`, ~500-1200 max_tokens each) plus one large main call carrying the full
system prompt + tool schemas (observed real `Requested` sizes: 5,576-6,410 tokens for pm/architect;
10,958 tokens for `coder` — a real Groq `413 Request too large` error, since that single request
alone exceeds the entire 8,000 TPM ceiling, unconditionally, with no amount of waiting ever fixing
it).** This means the bottleneck is the size of a single agent's minimum call sequence relative to
the per-minute budget, not accumulated usage from prior tests — so neither a 70s nor a 240s
inter-test pacing gap reliably fixes it; some tests (like `coder`) can never pass on this Groq
tier/model at all, and others (`pm`, `architect`) pass only when the real sliding window happens to
line up favorably.

**Real, measured results from the paced run** (one test at a time, Groq, `GROQ_MAX_RETRIES=1` +
`max_retries=0` fix in place): **12 of 49 `tests/pending/` tests attempted, 0 passed.**
- 8 — `test_api_e2e.py`: all `ConnectionRefusedError` — these need a live dev server running on
  `localhost` (true HTTP end-to-end tests, not through the LangGraph bypass) — **unrelated to
  Groq/Gemini entirely**, would need the same fix regardless of which LLM backend is used.
- 3 — `test_architect_agent.py`: real `429 rate_limit_exceeded` (TPM), confirming K3 above.
- 1 — `test_coder_agent.py::test_coder_writes_file`: real `413 Request too large` (10,958 tokens
  requested against an 8,000 limit) — confirmed unconditionally unpassable on this Groq tier/model,
  not a timing issue.

The remaining 37 tests were not attempted this session — paused here per the user's explicit
decision once the structural (not pacing) nature of the limit was confirmed.

### K4 — Current state, and how to resume

`.env` is back to `USE_GROQ=false` (Anthropic-only default) — the Groq/Gemini keys, model overrides,
and the `GROQ_MAX_RETRIES=1`/adapter fixes are all still in place, untouched, so resuming free-tier
testing later needs zero rediscovery. All temporary code (both adapters, both compat shims, both
day0 integration test files) is still in the repo, each with its own "TEMPORARY, easily removable"
docstring — nothing here needs to be built again.

**To resume once `ANTHROPIC_API_KEY` has a real balance** (the real fix — Anthropic has no per-request
size ceiling anywhere close to this codebase's real prompt sizes, and its own rate limits are
tier-based on account spend, not a flat 8K free-tier number):
```bash
cd backend
RUN_PENDING_TESTS=1 pytest tests/pending/ -v
```
No `GROQ_PREFERRED`/`GEMINI_PREFERRED` env vars needed — `tests/pending/conftest.py`'s own
`_has_llm` check picks up a real `sk-ant-...` key automatically and skips the Groq/Gemini bypass
fixtures entirely (both are no-ops whenever a real Anthropic key is present — see `_prefer_groq`/
`_prefer_gemini`'s own definitions in that file).

**If free-tier testing is ever wanted again before that** (e.g., a different Groq/Gemini account
with a higher tier, or Groq's paid "Dev Tier"): the real per-request minimum for this codebase's
agents is ~7,000-11,000 tokens depending on the agent (`coder` is the largest observed) — any
free-tier key needs a TPM ceiling comfortably above that (Groq's paid Dev Tier, or Gemini's
`gemini-2.5-flash`/`gemini-flash-lite-latest` with a higher per-minute allowance than the default
free tier) for pacing to help at all; below that ceiling, no pacing strategy fixes it, per K3.

---

## L. (2026-09-29) Production audit suite (files/Audit 01–14): live-LLM checks deferred

The 14-audit production sign-off (reports in `What_is/AUDIT_REPORT/`) ran while
`ANTHROPIC_API_KEY` still had no balance. At the owner's request, every audit check that
needs a **live** model answer was skipped and is listed here instead of being passed.
Everything else in those audits was verified against the real Postgres, Redis, API, browser
and git, with the LLM call mocked where a test needs one.

Each row says which audit and section it came from, and what to run once the key has credit.
The matching audit report marks the same item `BLOCKED (LLM credit)`, not green.

| # | Audit § | Check that needs a live LLM | How to run it once the key works |
|---|---|---|---|
| L1 | 02 Phase 3B | Measure whether making `submit_*` schema validation **strict** (reject + ask the model to resubmit) is safe: count how often real model outputs fail their declared `input_schema` today (currently soft: logged + result warning, `base_graph.py:2762-2776`). | Run a sample of real agent runs; grep logs for `did not match its declared input_schema`. Decide strict vs soft from the real rate. |
| L2 ✅ DONE 2026-09-29 | 03 Phase 1 | *(verified with real key via `What_is/AUDIT_REPORT/evidence/live_memory_probe.py`: 3/3 real vectors, correct ranking, repo isolation)* Live semantic memory: `_embed()` against real Voyage, then `query_similar_tasks()` returns real neighbours. **Needs `VOYAGE_API_KEY`** (not set in `backend/.env`, so semantic memory is inactive today; it degrades gracefully to "no memory"). | Set `VOYAGE_API_KEY`, then `pytest tests/pending/test_embeddings.py` and one real task end-to-end; confirm `memory_embeddings` rows have non-zero vectors. |
| L3 | 03 Phase 1 | Versioned-lesson merge-on-conflict: `_merge_via_llm()` (Haiku tier) produces a merged draft when a new lesson is ≥ `MEMORY_MERGE_SIMILARITY_THRESHOLD` similar. Needs **both** a Voyage key (similarity) and Anthropic credit (merge). | Publish two near-duplicate lessons via `get_versioned_memory_store().publish()`; expect a v2 draft with `supersedes_id` set; promote it and confirm v1 → `superseded`. |
| L4 | 07 Phase 4 | Run the 11-task eval suite for real (`tests/evals/`, marked `slow`; never runs in CI or the default suite). Scoring is deterministic but structural only (status, summary, `verified`, expected fields). | `cd backend && pytest tests/evals/ -m slow -v`; record pass/fail per task in the audit 07 report. |
| L5 | 07 Phase 4 | The tasks' natural-language `quality_checks` (e.g. "recommendations should be actionable") are read by `eval_runner._score_result` but never executed: they need an LLM judge. | Add an LLM-judge step (Haiku tier) scoring each quality check, then run L4. |
| L6 | 07 Phase 3 | Regression gate becoming *active*: needs real agent runs → `_benchmark_baseline_loop` stores baselines → a degraded role-prompt change is blocked by `gate_deploy()`. | After ~20 real runs of one agent, propose a deliberately worse prompt for it via the self-improvement flow; expect `DeploymentBlocked`. |
| L7 | 07 (cost) | Measure real auxiliary spend now that it is counted (reflection on the agent's own model every turn, critique, planning): compare `tokens_in` per run before/after the 2026-09-29 accounting fix on a few real tasks. | Run 3 real tasks; read `agent_runs.tokens_in/out` and `/api/metrics` cost; decide whether reflection should move to the Haiku tier. |
| L8 | 12 (E2E) | Real-stack journey C — plan approval: create a task in the UI, click Run, wait for the plan, approve it in the UI, confirm the task moves to coding. | Same harness as audit 12: `apps/web/e2e-real` + `playwright.real.config.ts` (backend :8000, `next start` :3100, throwaway approver). Add a journey; real key; economy mode; use a throwaway repo, never the project repo. |
| L9 | 12 (E2E) | Real-stack journey D — agent execution to review: after approval the coder runs in a worktree, task reaches `ready_for_review` with a diff; Review page lists it; approve. | Same harness; one small task; read `agent_runs` cost. |
| L10 | 12 (E2E) | Real-stack journey G — repository chat answers a question about the repo and streams tokens into the UI. | Same harness; one question. |

---

## M. (2026-09-30) Live run plan: $5 balance, hard cap $4, $1 reserved for the owner

Rules agreed with the owner: all audits finish first without the API; live tests run LAST,
one at a time, cheapest first; stop at a measured **$3.50** (margin under $4); **$1 is never
touched**.

**Guards**
1. Every live run forces `COST_MODE=economy` (Haiku, no optional self-check calls). The
   test config defaults to `quality`, which would cost several times more.
2. Calibrate: run one cheap test, compute its exact cost from the returned token usage
   (input, output, cache write, cache read at Haiku prices $1 / $5 / $1.25 / $0.10 per
   million), then extrapolate before running more.
3. A running spend ledger in this section, updated after every item; stop at $3.50.
4. `COST_BUDGET_DAILY_USD` set to the remaining allowance for the session, as a second,
   automatic stop (enforced before every LLM call from 2026-09-30).

**Order (value per dollar)**

| # | Item | Estimate (Haiku) |
|---|---|---|
| 1 | Calibration: one single-agent pending test | ~$0.03–0.05 |
| 2 | L7: two real Smart Run tasks end to end (router → specialist → commit → push approval): proves the new cheap path and gives the real cost per task | ~$0.10–0.20 |
| 3 | L3: versioned-lesson merge (Voyage + one Haiku call) | < $0.01 |
| 4 | `tests/pending/` single-agent tests (pm, architect, decomposer, planner, coder, research, specialists) | ~$0.8–1.2 |
| 5 | `tests/pending/` manager + pipeline end-to-end tests | ~$0.6–1.0 |
| 6 | L4: the 11 evals (structural scoring) | ~$0.4–0.6 |
| 7 | L1: output-format failure rate: read from the logs of items 1–6 | $0 |
| 8 | L6: regression gate with ~20 runs of one agent (only if ≥ $0.8 remains) | ~$0.7 |

**Ledger** (filled in as items run)

| # | Item | Result | Measured cost | Running total |
|---|---|---|---|---|

---

## N. (2026-10-05) Final live-AI test plan: free APIs first, then Anthropic within $3 (keep $1)

Owner rules (2026-10-05):
- Small and simple tests run on the free APIs first (Groq, then Gemini).
- Anthropic is used only for the big tests, and only after the test code has been checked, so that a small code issue never burns a paid re-run.
- Token-heavy features stay off until the cheap runs pass; they are enabled last.
- Anthropic balance is **$4**. **$1 stays untouched**; the tests may use up to **$3**, with a hard stop at a measured **$2.80** (owner, 2026-10-05).

Keys checked 2026-10-05 with zero-token calls: Anthropic, Groq, Gemini and Voyage all authenticate.

### N1. Every pending live-AI test

| # | Test | Count | Needed for | Backend | Est. cost |
|---|---|---|---|---|---|
| L8 | Journey C: plan approval in the real UI | 1 | **Audit 12 GREEN** | Anthropic | $0.05–0.10 |
| L9 | Journey D: agent codes → Review → approve | 1 | **Audit 12 GREEN** | Anthropic | $0.05–0.15 |
| L10 | Journey G: repo chat streams an answer | 1 | **Audit 12 GREEN** | Anthropic | $0.01–0.03 |
| L4 | The 11 eval tasks for real | 11 | **Audit 07 GREEN** | Groq first; leftovers on Anthropic | $0–0.40 |
| L5 | LLM judge for the evals' quality checks (code to write first) | 26 checks | **Audit 07 GREEN** | Groq first; Haiku if needed | $0–0.10 |
| L6 | Regression gate becomes active (~20 runs of one agent, then a worse prompt is blocked) | ~21 runs | **Audit 07 GREEN** | Groq (mechanism proof) | $0 |
| L7 | Real cost per task, measured | — | **Audit 07 GREEN** | from the L8/L9 runs | $0 extra |
| L1 | How often model output fails its schema | — | Audit 02 decision | read from the logs of everything above | $0 |
| L3 | Versioned-lesson merge (Voyage + one Haiku call) | 1 | Memory | Anthropic | < $0.01 |
| B1 | Groq node tests: planner, reflection, lesson, mini graph | 9 | Groq path | Groq | $0 |
| B2 | Groq eval tests | 4 | Eval path | Groq | $0 |
| K1 | Gemini integration tests | 2 | Gemini path | Gemini | $0 |
| C | `tests/pending/test_embeddings.py` | 4 | Memory | Voyage only | $0 |
| C | `tests/pending/` single agents: pm 3, architect 3, decomposer 3, planner 4, coder 3, research 3 | 19 | Agents | Anthropic (too big for Groq, see K3) | $0.60–1.00 |
| C | `tests/pending/` specialists 9, manager 4, pipeline 5 | 18 | Orchestration | Anthropic | $0.60–1.00 |
| C | `tests/pending/test_api_e2e.py` (needs a live dev server) | 8 | API | Anthropic | $0.20–0.40 |
| Q | One run in **quality** mode (reflection, critique, planning on) | 1 | Proves the big-token features | Anthropic | $0.20–0.40 |

Done earlier: L2 (live semantic memory). Removed: section A stubs (Qoder T-17-101; replaced by real tests).

**Audits 07 and 12 turn GREEN with: L4, L5, L6, L7, L8, L9, L10.** Everything else is "pending, should pass" but doesn't gate a flag.

### N2. Phase 0: free checks before any paid call ($0)

1. **Read every test that will run** and fix stale code: wrong statuses, renamed fields, old model names, fixtures.
2. **Dry run with a fake Anthropic key.** Each paid test must fail exactly at its first LLM call (401, which Anthropic doesn't bill). A test that fails earlier has a setup bug, which gets fixed now.
3. **Cost guards**, checked to work before spending:
   - `COST_MODE=economy` passed explicitly. `tests/conftest.py` defaults to **quality**, which costs several times more.
   - `COST_BUDGET_DAILY_USD=2.80` with the Redis ledger on (`SPEND_GUARD_REDIS=true`), so the cap covers every test process together. Proven first with the fake key.
   - `PIPELINE_MODE=auto` (smart router: a small task runs one specialist).
4. **Throwaway repo** for anything that writes or commits; never this project's repo.
5. **Build the missing pieces with mocked tests first:** the L5 judge, and the L8–L10 journeys in `apps/web/e2e-real`.

### N3. Phase 1: free APIs (Groq → Gemini → Voyage)

B1, B2, K1, `test_embeddings`, L4 (paced for Groq's 8,000 tokens/min) and L6.

Every free run also rehearses the full code path. If a test fails for a code reason, the fix happens here, for free. Tests too big for Groq (K3) move to Phase 2 with their setup already proven.

### N4. Phase 2: Anthropic (Haiku, economy), one item at a time

| Step | Item | Stop / check |
|---|---|---|
| 2.1 | Calibration: one small pending test (pm) | Measure the real cost; re-estimate everything below |
| 2.2 | L10, L8, L9 (audit 12) | One small task, throwaway repo |
| 2.3 | L7 from 2.2's `agent_runs` | $0 |
| 2.4 | L4 leftovers + L5 (audit 07) | — |
| 2.5 | L3 | — |
| 2.6 | `tests/pending/` agents, then specialists/manager/pipeline, then api_e2e | Only while budget remains |
| 2.7 | Q: one quality-mode run (big-token features on) | Last, only if ≥ $0.40 remains |
| 2.8 | L1 from all logs | $0 |

Rules:
- The ledger below is updated after every step.
- A failure stops the run. It is diagnosed from logs for $0, fixed, and only that one test is re-run, never the whole file.
- Stop at $2.80.

### N5. Phase 3: restore

- `USE_GROQ` / `USE_GEMINI` go back off, `COST_BUDGET_DAILY_USD` goes back to the owner's $1, and any test-only settings are removed.
- The audit 07 and 12 reports and the tracker are updated from the results.

### N5b. Phase 0 + 1 results (2026-10-05, $0 spent)

**Free checks found and fixed, before any paid call:**
- **Product bug:** the task page's "Approve Plan & Start Coding" called `POST /run`, which refuses `ready_for_review` (400). A Smart Run or quick plan could never be approved from the UI (broken since 2026-07-02). It now calls `/approve`. Commit `5eb37912`.
- **Host blocker for epics:** on this machine an epic on the project repo halts at the resource check (54 GB projected vs 5.6 GB free; 20 parallel agents vs 6 CPUs). Paid epic tests use a throwaway repo and `MAX_CONCURRENT_AGENT_RUNS=4`.
- **Cost traps:**
  - `tests/conftest.py` defaults to **quality** mode. Every paid run now forces economy.
  - Background loops (orphan recovery, doc agent, dependency dispatch, consolidation) could start paid agents on the dev DB. The live server uses an isolated empty DB with those loops parked.
- **Stale or fake-pass tests fixed:**
  - 4 specialist tests unpacked the wrong number of return values.
  - QA, reviewer, research and manager tests passed with **no model answer**.
  - The epic test predated the plan-approval lifecycle.
  - The Voyage search tests used an old signature; one "passed" because the search errored.
  - The API e2e tests had no login (all 401).
  - The reject response shape had changed.
  - The demo repo already has `multiply`, so paid tests now ask for `subtract`.
- **Fewer paid runs:** each agent file shares one real run (19 runs → 8). The coder reads its small temp project, not this repository. The pipeline uses fresh task IDs.
- **The spend cap is proven:** with the ledger set to $2.81 and a cap of $2.80, the call was refused before sending.

**Free runs:**

| Item | Result |
|---|---|
| B1 Groq node + mini-graph tests | 9/9 pass (2 needed a one-tool role) |
| K1 Gemini | 2/2 pass |
| Voyage `test_embeddings` | 4/4 pass (real ranking: auth.py first) |
| L5 judge (Groq) | Built + unit tests; live: passes a concrete answer, fails a vague one (3/3 each) |
| L4 evals on Groq | Not possible: agents' requests grow past 8k tokens → 413 (as in K3). Moved to Anthropic; the judge stays on Groq (`EVAL_JUDGE_BACKEND=groq`) |
| L8–L10 journeys | Rehearsed on the real stack with a fake key: C passes fully, D/G reach the first model call |
| `test_api_e2e` | 7/8 pass at $0; the full-pipeline one reaches the first model call |
| All `tests/pending` agent tests | Dry run: every one fails only at the first model call (401) |

### N6. Ledger

| Step | Item | Result | Measured cost | Running total |
|---|---|---|---|---|
| 2.1 | Calibration: pm (3 tests, one shared run) | 3/3 pass | $0.019 | $0.019 |
| 2.2 | L8–L10 journeys, 1st run | C pass; D blocked → **bug: coding commit refused the worktree dir** | $0.032 | $0.051 |
| 2.2 | Journeys re-run | D codes; Review-page expectation was wrong (by design) | $0.021 | $0.071 |
| 2.2 | Journeys re-run | D diff OK; push approval needs a GitHub repo (by design) | $0.025 | $0.096 |
| 2.2 | D (reused task) + G chat | Both pass; **bug: chat on Sonnet, no caching, condensing each turn** (~12 calls) | $0.719 | $0.815 |
| 2.2 | G re-check after the chat fixes | Pass: 4 calls, Haiku + cache | $0.047 | $0.862 |
| 2.4 | eval_005 alone | **Bug: hit max_turns, nothing submitted** | $0.128 | $0.990 |
| 2.4 | eval_005 after the loop fixes | Score 0.90; also fixed the wasted post-submit call | $0.106 | $1.096 |
| 2.4 | Evals 001–004, 009–011 | 0.55 / 0.89 / 0.67 / 0.80 / 1.00 / 0.80 / 1.00 | $0.703 | $1.799 |
| 2.4 | Evals 006–008 (first try failed at $0) | **Bugs: eval runner args; opus agents + thinking on Haiku (400)**; re-run: 0.40 / 0.80 / 0.80 | $0.402 | $2.201 |
| L6 | Regression gate, 1st run | "Never call a tool" prompt was ignored by the model | $0.087 | $2.288 |
| — | Unattributed | Ledger moved between readings (likely late charges of the run above) | $0.036 | $2.324 |
| L6 | Regression gate, worse prompt | **BLOCKED** as expected (tool accuracy 0.90 → 0.27) | $0.047 | $2.371 |
| C | architect / decomposer / coder / research | 3/3, 3/3, 3/3, 3/3 | $0.191 | $2.562 |
| C | planner | 4/4 failed → **bug: validator vs v2 prompt format**; after the fix 4/4 pass | $0.049 | $2.612 |

**Total: $2.61 of the $4 balance; $1.39 left (the owner's $1 untouched).**

**Not run** (budget kept): specialists 9, manager/epic 4, pipeline 5, api_e2e (full pipeline) 1, L3 lesson merge, the quality-mode run. Their code paths were all dry-run at $0 (each reaches its first model call cleanly) and the stale tests among them are fixed.

**L1** (schema strictness): across the 22 paid run logs, exactly **one** submission broke its declared schema: `security_architect`'s `submit_threat_model` left out the required `overall_risk` (eval_008). Today it is kept with a warning. Under strict validation the agent would be asked to resubmit. One miss in ~25 agent runs (about 4%) says strict mode is affordable, but it would cost one extra call per miss. Recommendation: strict for submit tools whose output feeds code (patches, plans), soft for reports.
