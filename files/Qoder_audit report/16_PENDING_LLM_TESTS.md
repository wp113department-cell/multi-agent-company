# 16 — Pending LLM Testing Register (all live-LLM / real-service tests skipped by this audit series)

- **Audit ID:** 16
- **Type:** Inventory deliverable — every test that requires a live LLM (or a real external service) and therefore could NOT be executed in this audit series. **Nothing in this file is a PASS**; every row is `PENDING / UNVERIFIED` until run with a funded key.
- **Run date:** 2026-10-02
- **Baseline:** HEAD `90dac23bad223ec39413c485d1ddb68f9646975e` (current disk; collection-level verification executed this audit)
- **Method:** (a) **executed** collection-level verification on current HEAD (`pytest --collect-only`: 8,962 collected / 25 deselected; `pytest tests/pending/ -q`: 49 skipped in 0.35 s — skips cleanly, verified this audit); (b) the repository's own register `PENDING_TESTS_API_KEYS.md` (797 lines, sections A–M) reconciled against current disk — including re-verifying which of its items remain true; (c) cross-references to the audit-series deferrals in reports 02, 03, 07, 12, 14.
- **Companion sidecar:** `json/AUDIT_16_PENDING_LLM_TESTS.json`

---

## 1. Why these are pending (current blockers)

| Blocker | Status at HEAD | Evidence |
|---|---|---|
| `ANTHROPIC_API_KEY` | **no balance** (key present in `.env` historically; real call returned `BadRequestError: "Your credit balance is too low"`) | repo register §K; audit 07/12/14 deferrals |
| `VOYAGE_API_KEY` | **not set** → semantic memory inactive by default (degrades gracefully) | Audit 03 MEM-03-004 |
| Groq free tier | **structurally unusable** for real agents: 8,000 TPM ceiling vs coder's minimum single request of 10,958 tokens (unconditional `413`); paced run: 12 attempted, 0 passed | repo register §K3 |
| Gemini free tier | **unusable**: 20 requests/day for `gemini-2.5-flash`; "lite" models hang 120 s on real-size prompts | repo register §K2 |
| Conclusion | A funded Anthropic key is the only viable path; Groq/Gemini adapters remain in-repo as temporary $0-testing scaffolding | repo register §K4 |

This audit series (01–14) made **zero live LLM calls** — all LLM-gated checks were recorded as UNVERIFIED inside their audits and are consolidated here by reference.

---

## 2. Mechanical gate inventory (verified at HEAD)

| Gate | Where | Effect |
|---|---|---|
| `addopts = -m "not slow"` | `backend/pytest.ini` | **25 slow-marked tests deselected by default** (19 LLM + 6 network-real) |
| `RUN_PENDING_TESTS=1` + key-shape checks (`sk-ant-` / `gsk_` / gemini) | `backend/tests/pending/conftest.py:34-80` | 49 tests skip cleanly otherwise (verified: 49 skipped in 0.35 s) |
| `require_groq` fixture | `backend/tests/evals/test_evals.py:123-129` | Eval suite skips unless `settings.use_groq and settings.groq_api_key` |
| `ANTHROPIC_AVAILABLE` (`sk-ant` prefix check) | `backend/tests/test_day0_groq_integration.py:351-358` | 4 Anthropic-only tests skip without a real key |
| Playwright real-stack config | `apps/web/playwright.real.config.ts` + `e2e-real/journeys.spec.ts` | Non-LLM journeys runnable; LLM journeys deferred here (§5, L8–L10) |

**Measured this audit:** `8,962 collected / 25 deselected` (HEAD) — default run at series baseline `c927c44b`: `8,870 passed / 55 skipped / 25 deselected / 0 errors` (27:23).

**Fixed since the repo register was compiled (re-verified at HEAD):** `test_research_agent.py` now uses the shared `requires_anthropic` gate (the register §C inconsistency is closed).

---

## 3. Catalog A — the 19 slow-deselected LLM tests

### A1. `backend/tests/test_day0_groq_integration.py` — 13 tests (real LLM; Groq or Anthropic)

| Class / test | What it verifies |
|---|---|
| `TestPlannerNodeRealLLM` (3) | Planner node produces real JSON with steps; sets `status=running`; survives a bad model response |
| `TestReflectionNodeRealLLM` (2) | Reflection returns a `satisfied` field; non-fatal on partial JSON |
| `TestLessonExtractionRealLLM` (2) | A lesson is really extracted+stored from a run; retrieval finds it |
| `TestFullGraphRunGroq` (2) | A mini task runs end-to-end on the real graph; `trace_id` propagates |
| `test_prompt_caching_header_sent` | **ANTHROPIC-ONLY — still a `pass` TODO stub** (verified at HEAD); cache_control header assertion to be written |
| `test_image_block_param_in_call_llm` | **ANTHROPIC-ONLY — still a `pass` TODO stub**; vision `ImageBlockParam` serialization |
| `test_reflection_node_with_real_claude` | **ANTHROPIC-ONLY — still a `pass` TODO stub**; structured JSON reliability |
| `test_full_pipeline_pm_to_qa_with_claude` | **ANTHROPIC-ONLY — still a `pass` TODO stub**; full pm→…→qa pipeline on real Claude |

(The 4 stubs are honest `# TODO` placeholders — they must be **written** as well as run. They are also listed in file 17.)

### A2. `backend/tests/test_day0_gemini_integration.py` — 2 tests
Temporary Gemini backend (`gemini_adapter.py`, marked removable). Verifies full graph run + trace propagation. Not part of production verification — run only if the temporary path is retained.

### A3. `backend/tests/evals/test_evals.py::TestAgentEvals` — 4 tests
The 11-task eval suite (`tests/evals/tasks.json`), structural scoring only: status, summary, `verified`, expected fields.
- `test_sprint_planner_eval` (≥0.5), `test_business_analyst_eval` (≥0.5), `test_style_reviewer_eval` (≥0.4), `test_all_evals_pass_threshold` (full suite, avg ≥0.6).
- Cross-ref: Audit 07 **EVAL-07-102** (suite excluded from CI and default runs; never executed in the audited series).
- The tasks' natural-language `quality_checks` are **never executed** (EVAL-07-101); they need an LLM judge (§5, L5).

**Command (all A):**
```bash
cd backend
# Anthropic path:
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/pytest tests/test_day0_groq_integration.py -v -m slow
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/pytest tests/evals/ -v -m slow
```

---

## 4. Catalog B — `backend/tests/pending/` (49 tests, gated by `RUN_PENDING_TESTS=1` + keys)

| File | Tests | Real requirement |
|---|---|---|
| `test_pm_agent.py` | 3 | LLM |
| `test_architect_agent.py` | 3 | LLM |
| `test_decomposer_agent.py` | 3 | LLM |
| `test_planner_agent.py` | 4 | LLM |
| `test_coder_agent.py` | 3 | LLM (largest prompts; unpassable on Groq free tier) |
| `test_pipeline_e2e.py` | 5 | LLM (full PM→Architect→Decomposer graph) |
| `test_research_agent.py` | 3 | LLM |
| `test_embeddings.py` | 4 | **`VOYAGE_API_KEY`** |
| `test_manager_integration.py` | 4 | LLM + DB |
| `test_specialist_agents.py` | 9 | LLM (+DB for 3) |
| `test_api_e2e.py` | 8 | LLM + DB + **live dev server on :8000** (true HTTP journeys; historically failed with `ConnectionRefusedError` when no server was running — start uvicorn first) |
| **Total** | **49** | |

**Command:**
```bash
cd backend
RUN_PENDING_TESTS=1 ANTHROPIC_API_KEY=sk-ant-... \
  DATABASE_URL="postgresql+asyncpg://gridiron:gridiron_dev_only@localhost:5432/gridiron_dev" \
  .venv/bin/pytest tests/pending/ -v
# Voyage-only subset:
RUN_PENDING_TESTS=1 VOYAGE_API_KEY=pa-... .venv/bin/pytest tests/pending/test_embeddings.py -v
# For test_api_e2e.py also: start the API first (uvicorn app.main:app --port 8000)
```
Note (repo register §C): running the whole directory in one process historically exceeded 10 minutes — run file-by-file if needed.

---

## 5. Catalog C — Audit-series deferred live-LLM checks (cross-referenced to this series)

| # | Audit / finding | Check that needs a live LLM | How to run |
|---|---|---|---|
| L1 | 02 / AGENT-02-002 | Decide strict vs soft `submit_*` schema validation: count real outputs failing `input_schema` (currently logged + soft) | Run real agents; grep logs for `did not match its declared input_schema`; decide from the real rate |
| L2 | 03 / MEM-03-004 | Live semantic memory: `_embed()` against real Voyage; `query_similar_tasks()` returns real neighbours (Voyage unset today) | Set `VOYAGE_API_KEY`; `pytest tests/pending/test_embeddings.py`; confirm non-zero vectors in `memory_embeddings`. (A one-off probe was run by the parallel audit series on 2026-09-29 — **not re-verified by this series**) |
| L3 | 03 | Versioned-lesson merge-on-conflict: `_merge_via_llm()` produces merged draft; promote; v1 → `superseded` | Publish two near-duplicate lessons via `get_versioned_memory_store().publish()` |
| L4 | 07 / EVAL-07-102 | Run the 11-task eval suite for real (never runs in CI/default) | `pytest tests/evals/ -m slow -v`; record pass/fail per task into the audit 07 record |
| L5 | 07 / EVAL-07-101 | LLM judge for the `quality_checks` (read but never executed) | Add Haiku-tier judge step, then run L4 |
| L6 | 07 | Regression gate becoming **active**: real runs → baselines → degraded prompt blocked by `gate_deploy()` | After ~20 real runs of one agent, propose a deliberately worse prompt; expect `DeploymentBlocked` |
| L7 | 07/09 | Real auxiliary spend measurement (reflection/critique/planning tokens) on real tasks | Run 3 real tasks; read `agent_runs.tokens_in/out` + `/api/metrics`; decide reflection tier |
| L8 | 12 | Real-stack journey C: create task in UI → Run → plan appears → approve → task moves to coding | `apps/web` + `playwright.real.config.ts` (backend :8000, `next start` :3100, throwaway approver); add journey + real key; **throwaway repo only** |
| L9 | 12 | Real-stack journey D: coder runs in worktree → `ready_for_review` + diff → Review page → approve | Same harness; one small task; read `agent_runs` cost |
| L10 | 12 | Real-stack journey G: repository chat answers a question about the repo, streams into UI | Same harness; one question |

---

## 6. Non-LLM items in the same skip/deselect buckets (for completeness — not API-key gaps)

| Item | Count | Gate | Note |
|---|---|---|---|
| Network-real: GitHub inspect (`test_audit_q_batch09…`, `test_github_inspect_repo_hardening.py`) | 4 | `slow` marker | Real public-repo fetches; runnable now with network |
| Network-real: PyPI resolver (`test_t2b5_dependency_resolver.py`) | 2 | `slow` marker | Real PyPI queries |
| PDF test (`test_day2_tools.py`) | 1 | `reportlab` pip package missing | `pip install reportlab` — no key involved |
| Production-scale DR / chaos / soak / rollback | — | environment (not LLM) | Out of scope here; see Audit 13/14 reports |

---

## 7. Recommended execution plan (from repo register §M — $5 balance, hard cap $4, stop at $3.50, $1 reserved)

**Guards:** force `COST_MODE=economy`; calibrate one cheap test and extrapolate from returned token usage; keep a running spend ledger; set `COST_BUDGET_DAILY_USD` to the remaining allowance as an automatic stop.

| # | Item | Estimate (Haiku economy) |
|---|---|---|
| 1 | Calibration: one single-agent pending test | ~$0.03–0.05 |
| 2 | L7: two real Smart Run tasks end-to-end | ~$0.10–0.20 |
| 3 | L3: versioned-lesson merge (Voyage + one Haiku call) | < $0.01 |
| 4 | `tests/pending/` single-agent tests (pm, architect, decomposer, planner, coder, research, specialists) | ~$0.8–1.2 |
| 5 | `tests/pending/` manager + pipeline end-to-end | ~$0.6–1.0 |
| 6 | L4: the 11 evals (structural scoring) | ~$0.4–0.6 |
| 7 | L1: output-format failure rate (read from logs of items 1–6) | $0 |
| 8 | L6: regression gate (~20 runs of one agent; only if ≥ $0.8 remains) | ~$0.7 |
| | **Total** | **≈ $2.6–3.7 — fits the $3.50 stop with $1 never touched** |

**Acceptance rule:** each item run must be recorded PASS/FAIL and the corresponding audit finding updated (02 for L1; 03 for L2/L3; 07 for L4–L7; 12 for L8–L10; then the classification in report 15 updated). Until then, every row in this file remains **UNVERIFIED**.

---

## 8. Deliverable Note

This register adds no new findings; it is the complete inventory of what a funded key would still have to prove. Primary inputs: executed collection/skip measurements on current HEAD, `PENDING_TESTS_API_KEYS.md` (sections A–M, reconciled), and deferrals recorded in audits 02/03/07/12/14. Companion sidecar: `json/AUDIT_16_PENDING_LLM_TESTS.json`.
