# Day 9 Implementation Plan — 5 Fleet-Level Enhancement Agents
Prepared: 2026-07-20 (research/planning session — implementation starts next session)

## Source of truth for this day
- `docs/FLEET_ENHANCEMENT_PLAN.md` lines 792–820 (paraphrased spec)
- `files/agent_enhancement.md` lines 224–299 (original spec — richer responsibility lists;
  the plan doc's version is a summary of this)

## Repo-first research done today

- **`repos/swe-agent/sweagent/agent/reviewer.py`** — a second model reviews the first
  model's trajectory using independently-verifiable info (`ReviewSubmission`/`ReviewerResult`),
  never the model's own self-report. Same principle our `VerificationConfig` already
  enforces fleet-wide; directly informs **agent_performance_reviewer** and
  **quality_auditor**'s design — they must judge other agents by real `RunMetrics`/
  `AuditEntry`/`AgentResult` data, never by re-asking the target agent "how did you do?".
- **`repos/autogen/.../MemoryController`** (referenced in CLAUDE.md's repo table for
  "Memory update before inference, lesson extraction on failure") — the pattern our
  existing `LessonStore`/`memory_hook_node`/`lesson_node` already implements. Relevant to
  **knowledge_curator**: the curator's job is to operate on this same lesson/memory
  substrate (dedupe, quality-score, prune), not invent a new one.
- **`repos/roo-code/src/core/prompts/system.ts`** (from yesterday's Day 8 research) — still
  the reference for these 5 agents' role prompts: role definition + shared constitution,
  same as every other agent. No new prompting pattern needed.

## Codebase grounding done today (what already exists vs. what needs building)

| Need | Status | Where |
|---|---|---|
| `run_agent_graph` / `AGENT_CONTRACT` / `_register()` / `VerificationConfig` pattern | ✅ exists, just follow `debugger_agent.py` as the closest template (small, read-mostly, single `write_file` for a report) | `app/agents/debugger_agent.py` |
| Per-agent runtime performance data (latency, tool accuracy, error rate) for **agent_performance_reviewer** | ✅ exists — `MetricsCollector` (`by_agent`, `recent`, `p50/p95_latency_ms`, `avg_tool_accuracy`) | `app/fleet/metrics.py` |
| Audit trail (who did what, when, outcome) for **agent_debugger** | ✅ exists — `AuditLog` (`recent`, `by_trace`, `by_task`, `approvals`) — **missing a `by_agent()` filter, needs a small addition** (currently only `by_trace`/`by_task`) | `app/fleet/audit_log.py` |
| Fleet-wide agent state (SLEEP/RUNNING/ERROR, error_count, health) for **agent_debugger** | ✅ exists — `AgentRegistry.get(name)`, `.error_count`, `.health`, `.recover()` | `app/fleet/agent_registry.py` |
| Codebase read/search/architecture tools for **agent_advisor** | ✅ exists — standard `READ_ONLY_TOOLS` (`read_file`, `search_code`, `get_file_tree`, `search_symbols`, `list_functions`, `parse_ast`) | `app/agents/tools.py` |
| Persistent, searchable cross-agent memory for **knowledge_curator** | ⚠️ **two different systems exist — must pick one, see decision below** | see below |
| Prompt/tool/contract/test/architecture audit surface for **quality_auditor** | ✅ exists — same `READ_ONLY_TOOLS` + can literally call `verify_agent_contract()` and the Day 8 role-prompt test patterns as its own internal checks | `app/fleet/tool_manifest.py`, `backend/roles/`, `backend/tests/` |
| `fleet_metrics_read` / `audit_log_read` / `memory_search` as actual **tool specs + handlers** | ❌ none of these 3 tool names exist yet in `app/agents/tools.py` — must be built | — |

### Decision needed / resolved: which "memory" does knowledge_curator curate?

Two candidate systems found, both real:
1. **`LessonStore`** (`app/agents/base_graph.py`) — in-process, ephemeral (lost on restart),
   keyword-scored, written by `lesson_node` after every successful agent run. This is the
   "shared across agents" memory the plan's wording most directly matches.
2. **`memory_embeddings`** DB table + Voyage AI semantic search (`app/api/memory.py`,
   `app/memory/store.py::query_similar_tasks`) — persistent, real semantic search, already
   has a `category` field (`task | architecture | failure | learning`) from the 2026-07-16
   session. This is the actual durable "engineering memory" system, and the one Day 11's
   `versioned_memory.py` (lesson lifecycle DRAFT→PUBLISHED→SUPERSEDED→ARCHIVED, merge on
   duplicate) is designed to wrap.

**Resolution: use `memory_embeddings` (system 2).** It's persistent (curation of an
in-process store that resets on every restart makes no sense), already has the
category/dedup-relevant fields Day 11 will build on, and `LessonStore` has no `list()` /
`delete()` API to curate against anyway (only `add`/`retrieve`/`format_for_injection`).
`memory_search` tool → wrap `query_similar_tasks()`. `memory_read` → new query by id/category
(the existing `memory_read`/`memory_write` tools at `tools.py:3439` are a *different*,
simpler per-repo key-value scratch store — **do not reuse those**, they're semantically
unrelated to curating engineering memory). `memory_write` for the curator → needs a
new handler that can update/soft-delete a `MemoryEmbedding` row (e.g. mark a duplicate as
superseded) — this is intentionally a light precursor to Day 11's full versioned lifecycle,
not a reimplementation of it.

**Async-DB-from-sync-tool-handler resolution:** `app/db/session.py` only has an async
engine (no sync alternative). Tool handlers run synchronously inside `execute_tools`
(itself inside a plain, non-async `graph.invoke()` call) — so no event loop is already
running at that point, meaning a plain `asyncio.run(query_similar_tasks(...))` inside the
sync handler is safe and simple (no `run_coroutine_threadsafe` threading dance needed —
that pattern elsewhere in `tools.py` is for a *different* case: calling back into an
already-running async chat session for human confirmation).

## The 5 agents — concrete build spec

For each: follow `debugger_agent.py`'s exact shape (`AGENT_CONTRACT` dict → `_SUBMIT` tool →
`_TOOLS` list → `_CFG = VerificationConfig(...)` → `make_<name>_handlers()` →
`run_<name>()` → `_register()`).

### 1. `agent_performance_reviewer`
- Capability tag: `agent_performance_review` (checked — no collision; note existing
  `performance_reviewer` agent already owns the plain `performance_review` tag, don't reuse)
- Tools: `read_file`, `list_files`, `search_code`, **new** `fleet_metrics_read`, `submit_review`
- risk_level: `low`, permissions: `["read_repo", "read_metrics"]`
- `set_by`: `{"fleet_metrics_read": "metrics_read"}`, `enforce_in_result: {"metrics_read": "metrics_read"}`
  (mirrors the existing "read-only auditor" pattern — proves it actually pulled real metrics
  before making a claim, not just read source code)
- New tool `fleet_metrics_read`: input `{agent_name: string, n?: int}` → wraps
  `get_metrics_collector().by_agent(name, n)` + `p50/p95_latency_ms` + `avg_tool_accuracy`,
  returns a formatted summary string

### 2. `agent_debugger`
- Capability tag: `agent_debugging`
- Tools: `read_file`, `search_code`, `bash` (scoped via existing `check_command`/
  `check_allowlisted_command` guardrails — no new "limited bash" tool needed, same pattern
  every other bash-using agent already follows), **new** `audit_log_read`, `submit_fix`
- risk_level: `medium`, permissions: `["read_repo", "read_audit_log", "bash_scoped"]`
- `set_by`: `{"audit_log_read": "diagnosed", "bash": "checks_run"}`,
  `enforce_in_result: {"diagnosed": "diagnosed"}`
- New tool `audit_log_read`: input `{agent_name?: string, trace_id?: string, n?: int}` →
  wraps `get_audit_log().recent(n)` filtered by agent_name (needs the small `by_agent()`
  addition to `AuditLog`, or filter client-side in the handler — client-side filtering is
  simpler and doesn't touch `audit_log.py` at all, **prefer that** to keep the change scope
  minimal)
- Scope note from the plan's literal tool list: no `write_file`/`edit_file` given — "repair"
  here means things like clearing a stuck `agent_registry` ERROR state via a small, scoped
  bash/python one-liner or recommending the fix, **not** editing agent source code. If real
  code-repair turns out to be wanted, that's a deliberate scope increase (and a risk_level
  bump to `high`) to raise explicitly, not to assume.

### 3. `agent_advisor`
- Capability tag: `architecture_advisory`
- Tools: `read_file`, `list_files`, `search_code`, `get_file_tree`, `submit_advice`
- risk_level: `low`, permissions: `["read_repo"]` — purely read-only, no new tools needed
- `set_by`: `{"read_file": "read", "search_code": "read"}`, `enforce_in_result: {"read": "read"}`
  (same minimal "read-only auditor" pattern as ~22 existing agents)

### 4. `knowledge_curator`
- Capability tag: `knowledge_curation`
- Tools: `read_file`, **new** `memory_search`, **new** `memory_curate_read` (list/inspect —
  named distinctly from the existing per-repo `memory_read` to avoid confusion), **new**
  `memory_curate_write` (mark duplicate/superseded, update category/quality), `submit_curation`
- risk_level: `low`, permissions: `["read_repo", "write_memory"]`
- `set_by`: `{"memory_search": "memory_searched"}`, `enforce_in_result: {"memory_searched": "memory_searched"}`
- All 3 new memory tools wrap `app/memory/store.py` + `MemoryEmbedding` via
  `asyncio.run(...)` per the resolution above

### 5. `quality_auditor`
- Capability tag: `fleet_quality_audit`
- Tools: `read_file`, `list_files`, `search_code`, `get_file_tree`, `submit_audit`
- risk_level: `low`, permissions: `["read_repo"]` — purely read-only
- `set_by`: `{"read_file": "read", "search_code": "read"}`, `enforce_in_result: {"read": "read"}`
- Role prompt should explicitly point this agent at the real audit surfaces that exist:
  `verify_agent_contract()` (`app/fleet/tool_manifest.py`), the capability-tag-uniqueness
  rule (CLAUDE.md #6), and the Day 8 role-prompt structural checks — so it's auditing
  against the same ground truth this session's audits used, not vibes

## Tests to write (mirrors the `test_day5b_agents.py` / `test_day8_role_prompts.py` shape)

`tests/test_day9_fleet_agents.py`:
- Contract shape test per agent (5×): required `AGENT_CONTRACT` keys present
- Role file exists + inherits `_GLOBAL_STANDARDS.md` + has the 7 role-specific sections
  (reuse `test_day8_role_prompts.py`'s pattern/constants rather than duplicating)
- `_register()` → agent appears in `capability_registry` with non-empty capabilities
- Capability tag uniqueness: assert none of the 5 new tags collide with the existing ~189
- `enforce_in_result` non-empty, no dead keys (reuse this session's audit-script logic as a
  real test rather than a one-off script)
- New tool handler unit tests: `fleet_metrics_read` / `audit_log_read` / the 3 memory tools
  against mocked collectors/DB
- `run_<agent>()` returns `AgentResult` on a mocked `run_agent_graph`

## Order of implementation tomorrow

1. Build the 3 new tool specs + handlers in `tools.py` (`fleet_metrics_read`,
   `audit_log_read`, `memory_search`/`memory_curate_read`/`memory_curate_write`) — test each
   in isolation first (they're the only genuinely new infrastructure; everything else is the
   well-established per-agent pattern).
2. Build the 5 agent files in the plan's own order (performance_reviewer → debugger →
   advisor → curator → auditor), each: contract → tools → verification config → handlers →
   run function → `_register()` → role prompt (`backend/roles/<name>.md`, following the v2.0
   `_GLOBAL_STANDARDS.md` + 7-section pattern, not the old 9-section one).
3. Add all 5 to `app/fleet/agent_models.json` (model routing) and `app/api/specialized_agents.py`
   dispatch table if they should be directly task-dispatchable (check whether Day 9's agents
   are meant to be user-facing task agents or purely internal/scheduled — the plan doesn't
   say; default to registering in `specialized_agents.py` for consistency with every other
   agent unless a reason emerges not to).
4. Write `tests/test_day9_fleet_agents.py`, run full suite, fix anything red.
5. Run `mypy app/ --strict` — must not add to the 32 pre-existing errors.
6. Update `PROJECT.md` + `docs/PROJECT_CONTROL_CENTER.md`, write
   `docs/reports/FLEET_DAY9_TEST_REPORT.md`, commit.
7. Re-audit Day 9's own success criteria before calling it done (ZERO-SKIP rule): all 5 in
   `capability_registry`, tests for each, full suite green — not just "looks done."
