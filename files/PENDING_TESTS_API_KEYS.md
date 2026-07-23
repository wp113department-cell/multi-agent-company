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

## Full tally

| Category | Count | Blocked on |
|---|---|---|
| A — Anthropic-only (stubs, need writing too) | 4 | Real `ANTHROPIC_API_KEY` |
| B1 — Groq integration tests | 9 | Real `GROQ_API_KEY` (or swap to Anthropic once available) |
| B2 — Groq eval tests (now covering 11 tasks in `tasks.json`, up from 5) | 4 | Real `GROQ_API_KEY` |
| C — `tests/pending/` full directory | 54 | Real LLM key (Anthropic or Groq) + some need DB/Voyage too |
| D — Unrelated (missing pip package) | 1 | `pip install reportlab` — not an API-key issue |
| **Total pytest-collected, blocked on real credentials** | **71** (55 skipped + 17 deselected − 1 reportlab) | |

**Bottom line:** every one of these is real, written code — nothing here is a stub pretending to be
a test (except the 4 in section A, which are honest TODO stubs, not disguised ones). Once you have
a real `ANTHROPIC_API_KEY` (recommended — unlocks everything, including the 4 Anthropic-only tests
Groq can never satisfy), the path is: set the env vars from section C, run
`RUN_PENDING_TESTS=1 pytest tests/pending/ -v`, then `pytest tests/test_day0_groq_integration.py
tests/evals/test_evals.py -v -m slow` if you also want the Groq-path tests exercised (now 11 real
agents' worth, not 5), then fix the one `test_research_agent.py` skip-condition inconsistency in
section C before trusting its "clean skip" behavior, then write real assertions for the 4 stubs in
section A.
