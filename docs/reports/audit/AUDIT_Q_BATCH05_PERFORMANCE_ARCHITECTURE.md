# Batch 5 — Performance Audit, Project Architecture Audit, Scalability

Covers §8, §10, §46. Evidence-only, file:line cited.

---

## §8 Performance Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Response latency tracking | **YES** | `fleet/metrics.py::run_span()` (time.monotonic-based), `p50_latency_ms()`/`p95_latency_ms()` from a real ring buffer. Wired at `main.py`, `base_graph.py`. |
| Planning speed | **YES** | Covered by the same `record_phase_timing()` mechanism (planner_node is one of the timed phases). |
| Orchestration speed | **PARTIAL** | Per-agent-run timing exists; no end-to-end orchestration-level latency metric spanning the full manager loop was found. |
| File scanning speed | **YES** | SHA-256 content hashing (`scanner.py::_content_hash`) + `known_hashes` skip-unchanged-files logic. Notable: this was previously **built but unused** — `merge_indexes()` had "zero real callers anywhere" until a 2026-07-23 fix wired it into `_do_reindex()` (`api/repo.py:47-62, 355-379`). Now real. |
| Editing speed | **NOT FOUND** | No dedicated timing metric for edit operations specifically. |
| Tool execution speed | **YES** | `RunMetrics.record_tool()` captures `duration_ms` per call, real hot-path caller at `base_graph.py:1703`. |
| Memory retrieval speed | **YES** | `memory/analytics.py::record_retrieval_time()`, real callers in all 5 `query_*` functions in `store.py`. |
| Comparison with Claude Code/Cursor | **NO** | Not found — only a role-prompt flavor line, not a benchmark. |
| Bottleneck: sequential subtask execution | **Confirmed** | `manager.py:269`, plain `for` loop over topologically-sorted subtasks — no fan-out even for mutually independent subtasks (same finding as Batch 2 §2). |
| Bottleneck: sync blocking in async code | **Not confirmed as a bug** | `time.sleep()` calls found (`groq_adapter.py:347`, `base_graph.py:1476`, `tools.py:11701`) all sit in plain functions reached via `asyncio.to_thread`, so they block a worker thread, not the event loop — correctly isolated. |

**§8 overall: PARTIAL.** Real, granular timing instrumentation exists at the tool/memory/phase level (not fabricated), but there is no end-to-end orchestration latency metric, no editing-speed metric, and — most importantly — **no actual measured comparison against Claude Code/Cursor exists**, despite the question file asking for percentage estimates against them. Any number given for that comparison would be an unfounded estimate, not evidence.

---

## §10 Project Architecture Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Folder structure | **YES** | Clear separation: `api/agents/db/pipeline/policy/repo_tools/memory/fleet/security/services/tools/observability/middleware/queue/mcp/artifacts/auth/event_bus/models`. Matches CLAUDE.md's documented structure. |
| Modularity | **PARTIAL** | Agents are individually modular (own file, own `AGENT_CONTRACT`), but the shared execution layer is not: `tools.py` is **12,993 lines** (all tool schemas/handlers in one file) — a clear god-module. `chat_agent.py` (2,990 lines) and `base_graph.py` (2,906 lines) are also large but architecturally justified as the shared engine. |
| Dependency management | **YES** | `requirements.txt`: all 40 top-level packages pinned with exact `==`, zero `>=` — matches CLAUDE.md's zero-hardcoding rule. |
| Code quality | **YES — verified by actually running the tools** | `ruff check app --statistics` → zero violations. `mypy app --strict` → "Success: no issues found in 200 source files." Both commands were actually executed, not assumed. |
| Testing volume | **YES** | 219 test files, 54,100 total lines, **3927/3944 tests collected** (17 deselected — API-key-gated). Real, current count from an actual pytest run. |
| Observability | **YES** | `observability/logging_context.py` (structured logging) + Sentry + OpenTelemetry (`fleet/metrics.py::_get_tracer_provider`), all wired at FastAPI startup (`main.py:577-579, 86-88`). |
| Deployment readiness | **PARTIAL** | Real `backend/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` all exist and CI runs a real Postgres service + lint/typecheck/test job. **But `docker-compose.yml` self-documents as dev-only** ("not a production deployment manifest," dev-default Postgres password, localhost-bound ports) — there is no production deployment manifest in the repo. |

**§10 overall: YES with one clear gap.** This is a well-organized, well-tested, clean-by-tooling codebase (zero ruff violations, zero strict-mypy errors, ~3900 real tests) — genuinely strong signal. The two real weaknesses: `tools.py`'s size, and the absence of any production (as opposed to dev) deployment manifest.

**Architecture score (evidence-based, not a vibe number): 8/10** — docked for the `tools.py` god-module and the missing production deploy manifest; everything else measured (dependency pinning, lint/type cleanliness, test volume, folder separation) is genuinely strong.

---

## §46 Scalability

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Hardcoded agent lists that wouldn't survive 10x growth | **NO — not found as a blocker** | No literal all-agent-names array found; one narrow frozenset (`_ARCHITECTURE_AGENT_NAMES`) is hook-scoped, not fleet-wide. |
| In-memory, single-process-only registries | **Confirmed — real scalability limit** | `CapabilityRegistry` (`fleet/capability_registry.py`) and `AgentRegistry` (`fleet/agent_registry.py`) are both explicitly documented in their own docstrings as "in-process singleton... Day 0 — no migration needed." `LessonStore`, `chat_agent.py`'s `_chat_agents` dict, and the retrieval-time/orchestration-time deques are all also in-process only. |
| DB indexing on frequently-filtered columns | **PARTIAL** | Most hot columns are indexed (`agent_name`, `status`, `task_id`, `repo_path`, `thread_id`). Two gaps found: `PendingApproval.agent_name` and `EpicScratchpad.agent_name` are **not** indexed while their sibling `status`/`epic_id` columns in the same tables are. |
| Horizontal scaling (multiple backend instances against shared DB) | **NO — not safely supported today** | The in-process registries above mean lessons learned, agent health state, and active chat sessions on instance A are invisible to instance B. No Redis-backed shared state, no sticky-session routing found. |
| Connection pooling | **YES** | Real, non-default async engine config: `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True` (`db/session.py:14-33`), explicitly documented as a fixed gap (SQLAlchemy's async default of 15 total connections was smaller than the app's own 20-concurrent-run ceiling). One gap: `new_isolated_async_engine()` for sync-bridging LangGraph nodes uses SQLAlchemy defaults, not the tuned pool size. |

**§46 overall: PARTIAL, and this is the most consequential finding of this batch.** The system is explicitly single-process by design in several load-bearing places (agent registry, capability registry, chat sessions, lesson store) — comments in the code itself call this out as an intentional "Day 0" simplification, not an oversight. Going from 72→720 agents doesn't break this (agent count isn't the constraint — it's *concurrent backend processes* that would break state consistency). This means **today the system cannot run more than one backend process without silent state divergence** — a real ceiling on horizontal scaling, distinct from and more serious than the agent-count question as literally asked.

---

## Summary — Batch 5 (26 checkpoints across 3 sections)

- **YES:** 13
- **PARTIAL:** 9
- **NO / NOT FOUND:** 4

**Findings worth flagging:**
1. **No production deployment manifest exists** — only a self-documented dev-only `docker-compose.yml`.
2. **Horizontal scaling is not currently safe** — multiple in-process singletons (agent registry, capability registry, lesson store, chat sessions) would silently diverge across backend instances; this is a bigger scalability constraint than agent count.
3. **Code quality tooling genuinely passes clean** (0 ruff violations, 0 strict-mypy errors across 200 files) — a real positive signal worth crediting, not just a risk list.

**Production Enhancement Plan for the scaling gap:** Move `AgentRegistry` and `CapabilityRegistry` state to Redis (or the existing Postgres, given `api/registry.py`'s DB-backed registry already exists as the docstring notes — "complements the DB-backed api/registry.py") so multiple backend processes see consistent agent health/capability state. Sticky-session routing (or moving chat session state to Redis) is required before running more than one backend replica for the interactive chat surface specifically, since `_chat_agents` is a plain in-process dict.
