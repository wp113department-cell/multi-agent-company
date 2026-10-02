# 17 — Test Case Audit (fake / trivial / masking tests)

- **Audit ID:** 17
- **Type:** Test-quality audit deliverable — scan-level analysis of the entire test suite for fake, trivial, tautological, or defect-masking tests.
- **Run date:** 2026-10-02
- **Baseline:** HEAD `90dac23bad223ec39413c485d1ddb68f9646975e`
- **Method (all executed this audit):** two-pass Python AST scan of **675 backend test files / 7,057 test functions** (empty-body detection, assert/raises/mock-assert census, trivial-assert matcher, mock-passthrough matcher, skip inventory); executed collection (`8,962 collected / 25 deselected`) and skip verification (`tests/pending` → 49 skipped); **executed vitest suite (9 files / 52 tests — all passed)**; targeted code reads of every flagged body before classifying (no verdict from regex alone).
- **Companion sidecar:** `json/AUDIT_17_TEST_CASE_AUDIT.json`

---

## 1. Executive Summary

**The suite is overwhelmingly substantive — this is not a fake-test farm.** Out of 7,057 backend test functions plus 52 frontend vitest tests, the scan found: **4 empty stubs, 1 tautological assertion, and 0 fabricated-value assertions.** Everything else flagged by the scan resolved, on inspection, into legitimate test patterns (details in §3–§5).

The one genuinely consequential pattern is **structural, not fabricated**: mocks placed at a boundary that hides a broken production path from CI (the flagship case is the `bhaskar` feature, dead-on-arrival in production while its tests stayed green — §6, T-17-107).

| Metric | Count | Verdict |
|---|---:|---|
| Backend test files / test functions / collected | 675 / 7,057 / 8,962 | — |
| Empty stub tests (`pass` + TODO only) | **4** | T-17-101 (Low) |
| Tautological assertions (`assert True` etc.) | **1** | T-17-102 (Low) |
| `assert False` used as failure markers (try/except idiom) | 3 | Verified legitimate — not defects |
| No-assert tests — total flagged | 85 | see breakdown below |
| → assert-through-shared-helper (legit, e.g. 30× `test_fleet_flags`) | 37 | Verified legitimate |
| → intentional no-exception tests ("no raise", "accepts", "passes when under limit") | 44 | T-17-103 (Low, weakest legit style) |
| Interaction-only tests (mock call assertions only) | 29 | T-17-104 (Low, spot-checked legitimate) |
| Tests asserting values injected via their own mocks | 39 raw | T-17-105 (Low, mostly passthrough plumbing) |
| `xfail` masking | **0** | — (the one grep hit is a string literal) |
| Skip inventory | 24 module-level `pytestmark` files + 11 `skipif` decorators + 46 inline `pytest.skip()` | Environmental, documented (§5) |
| CI-blind surface | 25 slow-deselected + 49 pending + playwright e2e (11) + e2e-real (6) | T-17-106 (Low; cross-ref file 16) |
| Frontend vitest | 9 files / 52 tests / 109+ `expect()` — **executed: 52/52 pass** | Healthy ratios, no trivial-only files |
| Defect-masking via mock placement | flagged | **T-17-107 (Medium)** — see §6 |

---

## 2. What was scanned and how

- **Empty-body detection:** body after docstring == single `pass`.
- **No-check census:** no `assert`, no `pytest.raises`/`pytest.fail`, no `mock.assert_*` call in the function.
- **Trivial-assert matcher:** `assert <constant>`; `assert x == x`.
- **Mock-passthrough matcher:** `return_value=<literal>` in the same test as `assert ... == <same literal>` (documented false-positive: `return_value=None`).
- **Skip inventory:** decorators, module-level `pytestmark`, inline `pytest.skip()`.
- Every flagged case was **read in source** before classification — three heuristic buckets were materially corrected by these reads (§3.2, §5.1, §5.2).

---

## 3. Findings — true test-quality defects

### T-17-101 (Low) — 4 empty stub tests (`pass` + TODO), collected but can never fail

- **File:** `backend/tests/test_day0_groq_integration.py:361-385` — `test_prompt_caching_header_sent`, `test_image_block_param_in_call_llm`, `test_reflection_node_with_real_claude`, `test_full_pipeline_pm_to_qa_with_claude`.
- **Evidence:** bodies are docstring + `pass` with `# TODO` describing the intended assertion (verified at HEAD). They are honest stubs, not disguised fakes — but they are counted in the 8,962 collected total and pass unconditionally.
- **Impact:** an Anthropic-capability claim (prompt caching, vision blocks, structured reflection) has zero executable verification today; the green "collected" count includes them.
- **Recommendation:** write the assertions (each is a small mock-capture test for 3 of the 4) or mark `skip(reason="stub — pending funded key")` until then so the report doesn't count them as passing coverage. Cross-ref: file 16 §A1.

### T-17-102 (Low) — 1 tautological assertion

- **File:** `backend/tests/test_concurrency.py:62` — `assert True  # No deadlock = pass` (in `test_subtask_slot_per_epic`).
- **Evidence:** the statement is a no-op; the test's real check is implicit (if `asyncio.gather` deadlocked, the run would hang/timeout). The sibling test `test_subtask_slot_different_epics_independent` asserts on the `entered` list, showing the intended style.
- **Impact:** the assertion documents intent but verifies nothing; a regression that keeps concurrency without preserving per-epic scoping could pass.
- **Recommendation:** assert the post-condition (`len(active_a) == 0` and all 4 completions observed).
- **Note:** the 3 `assert False` hits in `test_enhancements_settings_pdf.py` are **legitimate failure markers** inside `try/except HTTPException` blocks — verified in source, not defects.

### T-17-103 (Low) — 44 intentional no-exception tests (weakest legitimate style)

- **Pattern:** body calls the unit and relies on "it did not raise" (comments such as `# must not raise`, `# no raise`). Examples: `test_git_service.py:95,113` (`_validate_url(...) # no raise`), `test_budget_manager.py:20,68,95,108` (`check_run/check_daily # must not raise`), `test_gap_day4.py` ×3 `test_module_importable`, `test_audit09_spend_guard.py:115` `test_zero_disables_the_cap`.
- **Assessment:** not fake — a raise fails the test. But there is no positive verification of the result.
- **Recommendation:** opportunistic strengthening only (add a post-condition where a cheap observable exists, e.g. assert returned `(allowed, reason)` tuples from the budget checks); no mass rewrite warranted.

### T-17-104 (Low) — 29 interaction-only tests (mock-call assertions only)

- **Pattern:** every check is a mock interaction (`assert_not_called`, `assert_called_once`), no value assertions. Samples read: `test_gap52_doc_agent_auto_trigger.py:225` (skip-when-sha-unchanged), `test_batch15_prompt_auto_rollback.py` (4 × "skips/never triggers" guards), `test_confidence_gated_control_flow.py` (3 × "does not request human input").
- **Assessment:** these are **negative-path tests**, and asserting "X was NOT called" is the correct way to test skip/guard behavior — spot-checks show real preconditions (real repo, real settings objects). Legitimate.
- **Residual risk:** a change that makes the guard unreachable-but-silent (e.g. early return before the not-called point) can still show green. Advisory note only.

### T-17-105 (Low) — 39 tests assert against literals they injected via their own mocks

- **Pattern:** raw heuristic (documented false-positive: `return_value=None`); meaningful samples read: `test_summarize_output_hardening.py:134,145` (mock LLM returns `"• delegated summary"`, assert the handler result equals it), `test_generate_commit_msg_hardening.py:142`, `test_audit04_orchestration_fixes.py:157` (mock git diff literal flows into the commit step).
- **Assessment:** standard boundary-mocking — the test verifies the unit's **plumbing** (the mocked value is routed through the unit unchanged), not the mocked component's behavior. Legitimate and common; recorded as a pattern so future readers calibrate what these tests can and cannot catch.

---

## 4. Execution reality — what actually runs (T-17-106, Low)

| Bucket | Count | Runs where |
|---|---:|---|
| Default pytest run (CI) | 8,962 collected / 25 deselected | CI ubuntu (+Windows platform subset): `pytest tests/ -v` under `pytest.ini` `-m "not slow"` |
| Slow-deselected (LLM + network-real) | 25 | never in CI — file 16 §3/§6 |
| `tests/pending/` gate | 49 | never without `RUN_PENDING_TESTS=1` + funded keys — verified skips cleanly (49 skipped, 0.35 s) |
| Vitest (frontend) | 52 | CI (Node 22 job) — **executed this audit: 52/52 pass** |
| Playwright e2e (mocked API) | 11 (4 specs) | NOT in CI |
| e2e-real (real stack, real backend) | 6 journeys (A1–A4, B, page tour) | NOT in CI; requires :8000 + `next start` :3100 + throwaway approver |

**Implication:** "CI green" means the deterministic core is green. It does **not** cover: live LLM behavior, real-network tools, browser journeys, or real-stack E2E. This is deliberate and documented (`pytest.ini` comment; PENDING register), but any reader of the CI badge must discount the unexecuted surface listed above (cross-ref T-17-106 → file 16).

---

## 5. Verified-clean classes (checked and dismissed — no finding)

1. **`assert False` failure markers (3):** legitimate try/except idiom (`test_enhancements_settings_pdf.py:256,269,283`).
2. **`is not None` validator tests (heuristic hits):** e.g. `test_git_merge_hardening.py:68-74`, `test_ssrf_nat64.py:47` — the validator's contract is "returns error string or None", so `is not None` **is** the precise assertion. False positive; 93 tests matched the weak-assert heuristic and the sampled ones (≥12 read) are legitimate.
3. **Helper-based assertion (37 tests):** `test_fleet_flags` ×30 (day2/day3/day4 agent-contract files) and `test_handlers_are_valid` ×7 (`test_gap_agents.py`) — assertions live in shared helpers (`_assert_all_flags` asserts 8 conditions incl. all 4 fleet flags + non-empty description/repo_path/model_haiku, verified at `test_day2_agent_contracts.py:109-121`). Legitimate; the scan's first pass flagged them only because the assert calls carry no dot-prefix.
4. **No fabricated-value tests:** no `assert x == x`; no asserting a hardcoded expected equal to the function's own hardcoded constant (spot-checked across matcher hits); no empty test classes; **0 real `xfail`** (the single grep hit is a string literal inside a test about JUnit output parsing).
5. **Skip gates are environmental and honest:** docker-absent (`_HAS_DOCKER`), browser-absent, win32-only markers (24 pytestmark files incl. `test_docker_build_hardening.py`, `test_browser_tools_hardening.py`, `test_b1_venv_activation.py: sys.platform == "win32"`), and key gates. No unconditional `skip()` shortcuts on regular tests.
6. **Generated-family quality (105 `test_batch*/test_audit*/test_gap*` files):** these are the AI-generated fix-pass regression files (audits 04/05, gap-closure batches). Spot-checks (`test_audit04_orchestration_fixes.py`, `test_audit05_security_fixes.py`, `test_gap_agents.py`) show real behavioral tests with 1-12 asserts per test and real fixtures (real git repos via `_init_real_repo_with_one_commit`, real settings objects) — materially stronger than typical generated suites.
7. **Frontend vitest (executed 52/52):** expect-per-test ratios 1.3–4.3 (109 expects); `lib/api.test.ts` verifies security-relevant header behavior (no `Authorization` leak on GET/DELETE, `X-User-Id` preservation) — substantive, not "renders without crashing" filler. The 44 `toBeDefined/toBeTruthy/toBeInTheDocument` occurrences are components of richer assertions, not standalone trivial checks (spot-checked `api.test.ts` in full, `TerminalPanel`/`fleet` samples).
8. **Playwright e2e (11 tests):** intentional mocked-network UI tests via `page.route` fixtures — legit UI-contract testing (the real-stack alternative exists separately as e2e-real).

---

## 6. T-17-107 (Medium) — mocks that mask broken production paths

**Finding.** The suite contains tests that legitimately isolate a lower boundary **but are the only reason CI stayed green while the corresponding production path was 100% non-functional**. Three confirmed instances from the audit series:

1. **`bhaskar` (flagship; cross-ref H-3 / PROD-12-103):** `test_bhaskar_tool.py:983-1008` patches `run_agent_graph` on the module — so the real graph-construction path (`build_agent_graph → load_role → roles/bhaskar_agent.md`) never executes in any test. The role file does not exist, `bhaskar_tool` fails on every real call (`ok=false`, 0 tokens), and **849 lines of bhaskar tests remained green** because the mock sits above the failure point. Verified in source (the three tests at :978, :996, :1013 all patch `run_agent_graph`).
2. **`pipeline/dispatcher.py` (PROD-11-101):** kept alive only by its own tests (`test_dispatcher.py`, `test_agent_registry.py`) while production routing flows through `FleetManager.select()` — green forever regardless of the production-orphan reality.
3. **Test-only production APIs (PROD-11-103):** ~14 functions whose only callers are tests (v2 policy checks, sync approval-gate wrappers, s3 delete/list, etc.) — the tests maintain a surface the product abandoned.

**Impact.** This is the systemic risk class of "green CI + broken feature": no individual test is fake, yet the aggregate gives false confidence on exactly the paths the product actually uses. It is how a High-severity defect (H-3) survived a 8,900-test suite.

**Recommendation (targeted, not a mass rewrite).**
- Add contract tests that exercise each agent's **real** graph construction from its declared `role_name` (the H-3 fix explicitly recommends `load_role()` for every `role_name=` literal) — this single test class would have caught the bhaskar gap.
- For the dispatcher and test-only API clusters: delete-with-tests or wire-into-production (PROD-11-101/103 recommendations).
- Convention going forward: when mocking, prefer mocking the *external* boundary (LLM client, network, clock) over the project's own composition functions.

---

## 7. Scan limitations (disclosed)

- Classification is scan-level with source-read verification for every flagged case, but the buckets are heuristics: "no-check" ≠ "no-value" (implicit no-exception semantics), and the mock-passthrough matcher has a documented `None` false-positive class.
- The scan cannot detect semantic weakness that compiles like strength (e.g. asserting an intermediate the unit merely forwarded — T-17-105 describes exactly this class).
- `test_fleet_flags`-style helper assertions are invisible to assert-counting scans by construction (documented here so the next audit doesn't re-flag them).
- Frontend scan covered the 9 vitest files + 4 e2e specs + e2e-real spec; no per-test semantic review of every TS assertion was performed beyond samples.

---

## 8. Deliverable Note

Verdict: **the suite is real** — 4 empty stubs, 1 tautological assert, and one Medium structural masking pattern; no fabricated-assertion farm. The Medium is actionable and small (§6). Findings T-17-101…T-17-107 feed into the series register (report 15) under the test-quality section. Companion sidecar: `json/AUDIT_17_TEST_CASE_AUDIT.json`.
