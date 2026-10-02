# 11 — Master Zero Policy Audit (Hallucination, Hardcoding, Leakage, Dead Code, Duplicates, Loops, Cycles, Silent Exceptions, Blockers)

- **Audit ID:** 11
- **Baseline commit:** `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02 11:11 +0530) — **baseline drift note:** HEAD advanced during the series (`ecd4905a` "Production audit 12" → `33bbd03c` "Production audit 13"). Everything below is audited **as it exists on disk at `33bbd03c`**. No cited file changed while this audit ran.
- **Run date:** 2026-10-02
- **Method:** read-only static verification + scanner-assisted enumeration, all hygiene-preserving (`PYTHONDONTWRITEBYTECODE=1`). Live tooling used: (1) a **definition-usage scanner** over all 496 `backend/app/**/*.py` files collecting every top-level `def`/`class` name and counting word-boundary occurrences tree-wide (159 zero-caller candidates → 156 manually classified as route decorators / dynamically-dispatched agent modules / test helpers / genuine dead members); (2) a **module reachability scanner** counting occurrences of every `app.x.y` dotted module path across all of `backend/**/*.py` (**0 never-imported modules**); (3) the earlier **AST import-cycle scan** (496 modules, 98 cycle groups); (4) targeted greps + full reads of `base_graph.py` policy/enforcement blocks, `tools.py` registries, `event_bus/`, `policy/engine_v2.py`, `fleet/approval_gate.py`, `fleet/scratchpad.py`, `pipeline/dispatcher.py`, `api/specialized_agents.py`. Both temporary scanners live under this audit folder, deleted after use. **Static analysis only — not live-tested** (stated per finding where relevant).
- **Scope per brief:** 10 zero policies — hallucination, hardcoding, prompt/context leakage, memory leakage, dead code/orphan files, duplicate logic, infinite loops, circular dependencies, silent exceptions, production blockers.

---

## 1. Executive Summary

This is the strictest layer of the series and the system comes out of it **mostly clean, with no production blockers**. The hallucination-prevention stack is genuinely enforced at the single tool-submission chokepoint: schema-invalid LLM output now **deterministically fails the quality gate** (`checks.get("policy:schema_valid", True)` is part of `gate.passed`, `base_graph.py:2387` — the audit_v1.md 4.3 #1 fix), which flips `_requires_human_approval`; citation verification flags file:line fabrications into `_citation_check` + telemetry (non-blocking by documented design); key agents carry real `VerificationConfig`s (94 instantiations; `blocking_until={"edit_file": "read"}` mechanically forbids read-before-edit violations in bug-fix runs); and role prompts command `read_file`/`search_code` evidence. Hardcoding, prompt/context leakage, infinite loops, and circular dependencies are **fully compliant** — the cycle scan found only **one** pure top-level cycle (a benign `event_bus` package re-export resolved by Python's submodule fallback); every `while True` is bounded; the graph's stall loop terminates via `n_stalls >= max_stalls` (default 3) into checkpoint + escalation + human review.

Three Low findings, all in the dead-code/duplicate families: **(PROD-11-101)** `app/pipeline/dispatcher.py` — the module whose docstring advertises "capability-tag dispatch, zero code change for new agents" — has **zero production importers**; it is kept alive only by its own tests, while production selection actually runs through `FleetManager.select()` and `specialized_agents.py`'s registry/discovery. **(PROD-11-102)** a cluster of genuinely zero-reference members (an unused ORM model whose table is written via raw SQL, two unused event constructors, one unused policy check, one unused trend reader, one unused test-reset helper, four unused Pydantic response models). **(PROD-11-103)** a pattern of *test-only* production APIs (sync/async duplicate pairs, "public helpers" with zero production callers) — each tested, none wired; tests maintain a surface the product does not use.

Cross-referenced (counted once, in their originating audit): **PROD-09-103** (context cache unbounded + never-matching invalidation) and **PROD-09-106** (`_subtask_sems` never pruned) are the two real Memory-Leakage violations; **PROD-09-105** (dead budget methods) is the other Dead-Code item; **PROD-09-101** (High, cost-approval dead-end) is the nearest-to-blocker artifact in the whole series — a workflow dead-end, not a blocker by the definition used here (§5).

**Verdict: READY FOR PRODUCTION — zero production blockers; 0 Critical / 0 High / 0 Medium / 3 Low new findings. Score: 82/100.**

---

## 2. Zero Policy Compliance Table (required deliverable)

| # | Policy | Status | Evidence summary (this run) |
|---|---|---|---|
| 1 | **Zero Hallucination** | **FULLY COMPLIANT** | Schema validation of every `submit_*` payload (`jsonschema.validate` → `_validation_warning`, `base_graph.py:2884-2893`) is wired into the quality gate's `passed` (`:2387`) → `_requires_human_approval`; citation verification flags fabrications (`:2920-2934` → `_citation_check` + `citation_hallucination_flagged_this_turn`, consumed at `:3119` — flag-and-telemetry by documented design); 94 `VerificationConfig` instantiations incl. `enforce_in_result` overrides (reviewer/security/architecture) and `blocking_until` read-before-edit (bug_fix); role prompts (86 files) require read/search tool evidence before asserting. |
| 2 | **Zero Hardcoding** | **FULLY COMPLIANT** | Models/routing in `app/fleet/agent_models.json` + `config.py` (single settings source); CORS, event-bus retries, LLM timeouts, budgets, pool sizes all config fields; no hardcoded secrets/tokens anywhere (grep); `agent_name ==` conditionals exist only in dispatch/routing branches (e.g. `manager.py:597` frontend_dev special case — legitimate), not as hidden policy. |
| 3 | **Zero Prompt/Context Leakage** | **FULLY COMPLIANT** | Agent context is per-run state (`AgentRunState`); chat memory scoped per session with bounded restore (`chat_history_restore_limit=200`); `bash` extra_env redaction for secrets (`bash.py:101-128,229-249`); no cross-agent or cross-tenant bleed found in any sampled path. |
| 4 | **Zero Memory Leakage** | **PARTIALLY COMPLIANT** | `LessonStore` bounded (capacity from `lesson_store_capacity`, FIFO `pop(0)` eviction); all fire-and-forget task sites either tracked (`_spawn_tracked`) or internally caught; **but** two unbounded structures: `_context_cache` (PROD-09-103, Medium — also stale after re-index) and `_subtask_sems` (PROD-09-106, Low). |
| 5 | **Zero Dead Code / Unused Imports / Orphan Files** | **PARTIALLY COMPLIANT** | Module level: **0 orphan modules** (reachability scan: every dotted module imported somewhere). Member level: `pipeline/dispatcher.py` production-orphan (PROD-11-101), zero-reference member cluster (PROD-11-102), test-only APIs (PROD-11-103), dead budget methods (PROD-09-105). |
| 6 | **Zero Duplicate Logic** | **PARTIALLY COMPLIANT** | Two policy engines coexist — `policy/engine.py` (security denylists; live in production) and `policy/engine_v2.py` (DB-active policies; production uses exactly one of its functions, `record_approval`); duplicate daily-cap implementations (`budget_manager.check_daily*` vs the live `spend_guard`); sync/async API duplicate pairs where one side is unused (PROD-11-103); `dispatcher.py` routing duplicates `FleetManager.select()` (PROD-11-101). |
| 7 | **Zero Infinite Loops** | **FULLY COMPLIANT** | All four `while True` sites bounded by sleep+timeout/deadline/empty-break (`failure_ladder.py:550`, `consolidation.py:337`, `bhaskar_sandbox.py:485`, `process_manager.py:103`); graph loop terminates via `n_stalls >= max_stalls` (default 3) → stop + escalate + `request_human_review` (`base_graph.py:3365-3368,4235-4270`); no `recursion_limit` override — LangGraph default backstop stands. |
| 8 | **Zero Circular Dependencies** | **FULLY COMPLIANT** | AST scan of 496 modules → 98 cycle groups; 97 broken by deferred (function-local) imports by design; the single pure top-level cycle is the `app.event_bus` package `__init__` re-export (`bus ↔ __init__`), resolved benignly by Python's submodule fallback; `import app.main` clean. |
| 9 | **Zero Silent Exceptions (emergency brakes)** | **PARTIALLY COMPLIANT** | 781 broad `except Exception` sites, 61 of them `pass`-swallows; every sampled critical-path swallow is deliberate, documented telemetry/fallback (agent-switch telemetry, model-router fallback, stream-push guards); reflection/critique nodes log-and-continue; historical fire-and-forget launch shape fixed via `_spawn_tracked`. Sampling cannot prove all 781 — hence Partial. |
| 10 | **Zero Production Blockers** | **NONE FOUND** | See §5. Zero Criticals across the series; the one High (PROD-09-101) is a bounded workflow dead-end (spend guard caps exposure), not a blocker under the definition used. |

---

## 3. Per-Policy Detail

### 3.1 Hallucination prevention — FULLY COMPLIANT

- **Blocking layer (schema):** every `submit_*` tool call is validated against the tool's JSON schema (`base_graph.py:2884-2893`); failure sets `_validation_warning`; the quality gate records `checks["policy:schema_valid"] = False` (`:2318-2322`) and `passed` **includes** that check (`:2387`), so malformed output cannot masquerade as success — `_requires_human_approval` becomes True (`:2976-2978`).
- **Flagging layer (citations):** `verify_file_line_citations` (`:2920-2934`) annotates `_citation_check` and raises `citation_hallucination_flagged_this_turn`, consumed as a telemetry counter (`:3119`). The in-code comment documents the non-blocking choice ("flags via `_citation_check`, doesn't fail the gate").
- **Behavioral layer (verification configs):** 94 `VerificationConfig` instantiations; `reviewer.py:69-75` (`set_by={"git_diff": "diff_reviewed"}` + `enforce_in_result`), `bug_fix.py:69-80` (`blocking_until={"edit_file": "read", "write_file": "read"}` — mechanical read-before-edit), security/architecture reviewers enforce their scan flags into result fields.
- **Prompt layer:** role files require `read_file`/`search_code` evidence before assertions (`reviewer.md:54,56`; `bug_fix.md:22,38,42`; `architecture_reviewer.md:31,38,41`).

### 3.2 Hardcoding — FULLY COMPLIANT

Configuration is centralized: models per agent in `app/fleet/agent_models.json` (85 agents incl. `ux_design_agent`, `mobile_dev`, `agentic_ai_architect` at lines 87-98); thresholds/timeouts/limits as `config.py` settings (cost thresholds, pool sizes, retention, rate limits); no secret/token/credential literal anywhere (grep). Name-based conditionals are confined to real dispatch/routing branches. No finding.

### 3.3 Prompt/Context Leakage — FULLY COMPLIANT

Per-run state isolation (`AgentRunState` fields per agent run); scoped chat memory (per-session, bounded restore); subprocess env redaction (`bash.py:101-128,229-249`); no path found where one agent's context/prompt reaches another's model call. No finding.

### 3.4 Memory Leakage — PARTIALLY COMPLIANT

- Bounded by construction (verified clean): `LessonStore` (capacity `lesson_store_capacity`, `base_graph.py:689-691`; FIFO eviction `:544`); activity stream registry capped (256 streams, idle/terminal eviction) and per-subscriber queues bounded (`maxsize=500`, drop-on-full); chat restore bounded (200).
- Fire-and-forget inventory: all sites verified to either track or catch — `api/agents.py:36-51` `_spawn_tracked` (set + done callback), `epics.py:380-416` (`logger.exception`), `terminal.py:224-226` (cancel + await), `failure_ladder._dispatch` catch, `fleet_dashboard._run_apply_phase` try, `chat.py:202/345` internal catches.
- **Violations (cross-ref, counted in Audit 09):** `_context_cache` unbounded + invalidation that can never match (PROD-09-103, Medium); `_subtask_sems` per-epic dict never pruned (PROD-09-106, Low).

### 3.5 Dead Code / Unused Imports / Orphan Files — PARTIALLY COMPLIANT

- **Module level — clean:** the reachability scan (496 modules) found **0 modules never imported**. The nuance lives at member level and in *who* imports.
- **PROD-11-101:** `pipeline/dispatcher.py` — production-orphan module (detail in §4).
- **PROD-11-102:** zero-reference member cluster (detail in §4).
- **PROD-11-103:** test-only production APIs (detail in §4).
- **Cross-ref:** PROD-09-105 (`check_daily()`/`check_daily_db()` dead).
- Minor observations (not findings): stale comment "36 CHAT_TOOLS" at `chat_agent.py:1284` (actual: **190** unique tools — verified by live probe); the `web_search` handler is provided but not advertised in any tool list.

### 3.6 Duplicate Logic — PARTIALLY COMPLIANT

- `policy/engine.py` (security: command/path denylists — live across `chat_agent`, `guardrails`, `ast_engine`) vs `policy/engine_v2.py` (DB-active policies — production uses only `record_approval`, `epics.py:356`; its `check_file_against_policies`/`has_approval`/`match_pattern_sync` are test-only and `check_files_against_policies` is fully dead). Two engines are documented as distinct concerns, but the v2 check surface is unwired.
- Daily cap: `budget_manager.check_daily*` (dead) vs live `spend_guard` (PROD-09-105).
- Sync/async pairs where only one side is wired (PROD-11-103); `dispatcher.py` routing duplicates `FleetManager.select()` (PROD-11-101).

### 3.7 Infinite Loops — FULLY COMPLIANT

Enumerated every loop construct: four `while True` sites — `failure_ladder.py:550` (bounded sleep + guarded try), `consolidation.py:337` (config-interval sleep), `bhaskar_sandbox.py:485` (deadline + `break`), `process_manager.py:103` (empty-readline `break`). The agent-graph cycle terminates deterministically: stall counter increments in the router (`base_graph.py:3365`), threshold check `:3366-3368` (default `max_stalls=3`), and the run-end stall path checkpoints, escalates, and requests human review (`:4235-4270`). No `recursion_limit` override exists (only a comment, `delegation.py:17`) — LangGraph's default remains the backstop. No finding.

### 3.8 Circular Dependencies — FULLY COMPLIANT

AST import scan of all 496 modules found 98 static cycle groups; 97 contain at least one **deferred** edge (function-local import — the project's deliberate cycle-breaking pattern); the single pure top-level cycle is `app.event_bus.bus → app.event_bus.__init__ → app.event_bus.bus` — a package `__init__` re-export pattern that Python resolves via its submodule fallback (benign; `import app.event_bus.bus` and `import app.main` both clean). No finding.

### 3.9 Silent Exceptions / Emergency Brakes — PARTIALLY COMPLIANT

Census: **781** `except Exception` handlers; **61** with bare `pass` swallow. Every sampled critical-path instance verified deliberate and documented: agent-switch telemetry (`manager.py:573,750,832`), chat reader thread + model-router fallback (`chat_agent.py:496,966`), stream pushes (`pm.py:127`, `decomposer.py:146`), flag housekeeping (`tasks.py:59`); sites that matter log with `exc_info=True` (`tasks.py:756,1052`, `bash.py:287`). Reflection/critique nodes log-and-continue non-fatally (`base_graph.py:2063-2064, 2205-2206`). The historical unchecked-launch shape was fixed (`_spawn_tracked`, `api/agents.py:36-51`). Status is Partial only because 781 sites were sampled, not proven exhaustively.

### 3.10 Production Blockers — NONE FOUND

Definition used: a defect causing data loss/corruption, security breach, unrecoverable hang/crash, silent financial loss, or a broken core operation with no workaround. Result: **zero Critical findings across all audits 01–09 + 11**; the single High (PROD-09-101) blocks only the cost-approval *resume* flow (workaround: raise the threshold; exposure is bounded by the $25/day fleet spend guard). See §5.

---

## 4. Findings (new, this audit)

### PROD-11-101 — `pipeline/dispatcher.py` is a production-orphan module kept alive only by its own tests
- **Severity:** Low · **File:** `backend/app/pipeline/dispatcher.py` · **Line:** whole module (`dispatch_subtask` at 76) · **Confidence:** High
- **Finding:** zero importers anywhere outside `tests/` (`test_dispatcher.py`, `test_agent_registry.py`). The module's docstring advertises the platform claim: "Phase 6 upgrade: capability-tag dispatch … new agents inserted via SQL get dispatched with zero code change" and calls `pick_agent_by_tag` "the proof point". In reality production selection flows through `app/fleet/fleet_manager.py::FleetManager.select()` (fleet_manager.py:78) and `app/api/specialized_agents.py`'s `_REGISTRY`/`_discover_agent_fn` (dynamic `run_*` discovery from AGENT_CONTRACT). Docs referencing it: `docs/reports/PHASE_4_TEST_REPORT.md`, `PHASE_6_TEST_REPORT.md`, `AUDIT_01_ARCHITECTURE.md`.
- **Evidence:** `grep -rn "pipeline.dispatcher" app/` → 0; total non-test occurrences of `dispatch_subtask` = 0; `get_agent_for_type`/`pick_agent_by_tag` called only from within `dispatch_subtask` itself.
- **Production impact:** none at runtime (dead path); maintenance hazard — its tests pass forever regardless of production routing, and the docstring's dispatch claim is false for the shipped system.
- **Recommendation:** delete the module + its tests, or wire it in and delete `FleetManager.select`'s duplicated concerns. Effort: S.

### PROD-11-102 — zero-reference member cluster (10 members, 6 files)
- **Severity:** Low · **Files/lines:** `db/models.py:474` (`FailedEvent` ORM — table `failed_events` is written via raw SQL at `event_bus/bus.py:161`, `main.py:358`, `pipeline/queue_adapter.py:377`; the ORM class itself is never referenced); `event_bus/models.py:187` (`architecture_ready`), `:229` (`review_completed`) — constructor helpers never called (siblings are test-only API too); `policy/engine_v2.py:85` (`check_files_against_policies`); `fleet/test_score.py:167` (`get_test_score_trend`); `agents/temporary_agent.py:494` (`reset_temporary_agent_pool` — not even tests call it); `api/registry.py:27,32` (`AgentResponse`, `MetricsResponse`), `api/epics.py` (`EpicResponse`), `api/repo.py` (`RepoResponse`) — four Pydantic response models with zero references; the three API files use no `response_model=` at all (grep).
- **Evidence:** definition-usage scanner over 496 modules: each name's tree-wide word-boundary count equals its definition count (1–2). 156 of 159 scanner candidates classified as false positives (FastAPI route decorators, `importlib`-dispatched agent `run_*` modules via `specialized_agents._discover_agent_fn`, standard test-reset helpers).
- **Production impact:** none; maintenance/readability cost, and two constructors advertise a bus API surface that production never exercises.
- **Recommendation:** delete the listed members (or annotate as deliberately-kept API stubs); keep the `failed_events` raw-SQL path as-is. Effort: S.

### PROD-11-103 — test-only production APIs: tests exercise a surface the product does not wire
- **Severity:** Low · **Files:** enumerated below · **Confidence:** High
- **Finding:** a consistent pattern of functions whose only callers live in `tests/`: `policy/engine_v2.py` check surface (`check_file_against_policies`, `has_approval`, `match_pattern_sync` — production uses only `record_approval`); `fleet/approval_gate.py` sync wrappers `get_pending`/`record_decision` (production uses `aget_pending`/`arecord_decision`); `fleet/scratchpad.py::expire_stale_entries`; `services/retention.py::enforce_retention_policy` ("public helper" — production runs `_run_cleanup` via `start_retention_loop`); `artifacts/s3_store.py::delete_artifact_s3`/`list_artifacts_s3`; `fleet/metrics.py::configure_tracer_provider`/`new_trace_id`; `event_bus/redis_streams.py::stream_length`; `fleet/fleet_events.py::memory_created`/`translate_legacy_to_fleet`/`get_fleet_bus`; `fleet/tool_manifest.py::get_high_risk_tools`; `fleet/architecture_score.py`/`security_score.py` trend readers.
- **Evidence:** per-name occurrence counts (definition + test files only), cross-checked against production import sites. (Standard test-reset helpers — `reset_for_testing`, `reset_client`, `reset_docker_probe_cache`, etc. — were excluded as legitimate test infrastructure.)
- **Production impact:** none at runtime; the hazard is drift — a test suite that keeps green on code paths the product abandoned gives false confidence and tax on every refactor.
- **Recommendation:** triage deliberately: wire each into production, or delete with its tests. Effort: S–M.

---

## 5. Zero Production Blockers — final list

**None.** For the record, the nearest items across the whole audit series:

| Item | Severity | Why it is not a blocker |
|---|---|---|
| PROD-09-101 cost-approval dead-end | High | Workflow dead-end for >$1 epics; nothing runs/stalls unsafely; bounded by $25/day fleet spend guard; operator workaround exists (raise threshold). |
| PROD-09-103 stale/unbounded context cache | Medium | Degrades memory + serves stale context after re-index; restart clears; no data loss. |
| PROD-08-101 shared-bucket rate limiting | Medium | Throttling, not breach; single-user deployments unaffected. |

---

## 6. Verdict & Score

**Verdict: READY FOR PRODUCTION.** Zero policy layer: 6 of 10 policies FULLY COMPLIANT, 4 PARTIALLY, 0 NOT COMPLIANT; zero production blockers; zero Critical/High/Medium new findings in this layer (3 Low).

**Score: 82/100.** Deductions: memory leakage (2 unbounded/correctness-relevant structures, one Medium), dead code at member level and one orphan module, duplicate unwired surfaces, and sampling-only coverage of the 781 exception handlers. Offsets: the hallucination enforcement stack is real and mechanized at the submit chokepoint; loops, cycles, and fires-and-forgets are structurally bounded; the module graph has zero orphan files.
