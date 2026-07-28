# MASTER_AGENT_v2.md — Fleet-Wide Agent Upgrade Specification (v2)

**Purpose:** this document is a complete, evidence-based engineering specification for upgrading
every agent in this repository's fleet (`backend/app/agents/*.py`, currently 72 agents) to a single,
consistent, production-grade standard. It is written to be handed directly to an LLM coding agent
(Claude Code, Cursor, Codex, Gemini CLI, or equivalent) with the instruction: **"Implement this
file."** Every claim about the current codebase below is backed by a file:line citation, verified by
direct inspection — not assumed. Every requirement is phrased so its completion is checkable.

**v2 changelog (why this version exists):** v1 was reviewed against a request to expand it toward
enterprise-autonomous-platform scale (Claude Code / Cursor / Devin / Codex-level capability). Before
writing anything new, every one of the 20 requested capability areas was independently verified
against the real codebase. **The result changed the shape of this document materially: roughly half
of the requested capabilities already exist, several quite deeply** (a real function-level call graph
with PageRank, real cost/budget enforcement, real Sentry observability, a mature security policy
engine, a real LangGraph `interrupt()`-based approval system). Presenting those as new work to build
from scratch would make this document *less* trustworthy, not more. v2 therefore adds three things
v1 didn't have: **Part C, a citation-backed reference of everything already real** (so no
implementer wastes a week rebuilding a working system); **new phases sized to what's genuinely
missing**, integrated into the existing phase structure rather than bolted on; and **Appendix D**,
which honestly separates enterprise/hyperscale capabilities that do not match this project's current
real scale from what's actually required now — nothing requested was deleted, but nothing is
mis-sold as necessary either.

**Owner's five goals, verbatim intent, restated precisely as engineering requirements:**
1. All 72 agents run on LangGraph, with a real, consistent execution architecture — not just most.
2. All 72 agents have a tool contract genuinely tailored to their job — not a shared generic template.
3. All 72 agents are production-grade: they do the job their name and role prompt promise, and can
   verify their own claims, not just narrate them.
4. All 72 agents are capable in the same spirit as Claude Code — real file edit, real command
   execution, real test/lint verification, real iterative self-correction — appropriate to their role.
5. All agents share one real, persistent, semantically-searchable memory system, so that (the owner's
   own example) a future `cicd_agent` benefits automatically from what `debugger_agent` already
   learned, instead of starting from zero understanding every time.

---

## Reality check — read this before implementing, it changes what "done" means

This section exists because several of the goals above, and several of the v2 expansion requests,
bundle together things that are achievable and things that are not achievable in the form usually
implied — pretending otherwise would make this document dishonest.

**Achievable, and this document gets you there if fully implemented:** every agent verifiably does
its actual job — real tools, real verification against real tool output (not model narration), real
shared memory (declarative *and*, new in v2, procedural), real iterative self-correction and
self-critique bounded by retries, real workspace/repo intelligence (already substantially built —
see Part C), real operational maturity (cost, health, security — already substantially built). This
is what "production-grade," "Claude Code's *working pattern*," and "enterprise-engineered" concretely
mean for a fleet of narrow, verifiable specialist agents, and it is a fair, checkable bar.

**Not achievable, and not actually the right target: making all 72 agents individually equivalent to
Claude Code / ChatGPT / Claude.ai / Cursor as general-purpose, live, multi-turn conversational
assistants.** That requires open-ended dialogue with a human, arbitrary tool composition, and a very
large, continuously-adapting context — a *different interaction shape*, not a missing feature you
bolt onto a narrow single-shot task worker. No serious production multi-agent system (this project's
own `chat_agent` + fleet split, Devin, Cursor's background agents, or Anthropic's own internal agent
tooling) gives every narrow worker agent that shape — they all use the pattern this project already
has: **one capable conversational entry point, plus many narrow, verifiably-reliable task workers
behind it.** `env_checker_agent` does not need the ability to hold a 40-turn ambiguity-resolving
conversation; it needs to reliably check an environment and report the truth about what it found.

**Also not the right target right now, for a different reason: several v2-requested enterprise
capabilities (full multi-agent voting/arbitration, dynamic tool selection across redundant providers,
a generalized 6-category plugin architecture, distributed horizontal scaling for thousands of
concurrent tasks) do not match this project's actual current scale**, which runs on a single Postgres
instance with in-process concurrency primitives, not a distributed cluster. Building them now would
be speculative infrastructure with no current user — the exact anti-pattern this document elsewhere
insists on avoiding ("no placeholders," "no future work" dressed up as done). These are preserved in
full, not deleted, in **Appendix D**, each with the concrete trigger condition that would make it
worth building. Revisit Appendix D if and when a trigger fires; do not build ahead of it.

**The corrected, honest target for goals 3 and 4:** every agent matches Claude Code's *working
pattern* (read → act → verify against real output → critique → iterate within bounded retries →
report with evidence, and ask for clarification when a task is genuinely underspecified instead of
silently guessing) at a scope appropriate to its job. `chat_agent` remains the one agent with full
open-ended conversational depth. Phase 5 adds a structured way for *any* agent to escalate genuine
ambiguity instead of being forced to guess; Phase 3 (expanded in v2) adds formal self-critique and
quality gates so "verify" means something rigorous and measurable, not just a boolean.

If your actual requirement is "every one of the 72 agents must be able to hold an open-ended
conversation like ChatGPT," that is a different project — it means giving all 72 agents chat_agent's
interaction shape, which would also mean most of them no longer run unattended/dispatched, since a
conversational agent needs a human on the other end of the conversation. Flag this explicitly if it's
genuinely what you want; it can be scoped separately. It is not what the rest of this document
implements.

---

## 0. How to use this document

Read **Part C first** if you are already familiar with this codebase — it tells you what not to
rebuild. Then work through Part B in the phase order given (Phase 1 → 2 → 3 → 4 → 5 → 6). Each phase
has a **Definition of Done** — do not mark a phase complete until every item in its DoD is
independently verified (run the test, read the output, don't assume). After each phase, run the
**Full Regression Gate** in §9 before starting the next phase. Do not skip phases or reorder them —
later phases assume earlier ones are actually done, not just attempted. Read **Appendix D** before
proposing any of its items as "needed" — check the trigger condition first.

If anything in Part A or Part C ("Current State") appears to have changed since this document was
written, re-verify it against the live source before trusting the plan built on top of it — this
document is a snapshot, not a live oracle.

---

# PART A — Current State: gaps and integrity issues (verified, not assumed)

## A.1 LangGraph coverage: 70 of 72 agents, 2 deliberate exceptions

`app/agents/base_graph.py` (`run_agent_graph`, `build_agent_graph`, ~1379 lines) is a real,
substantial LangGraph implementation: an actual `langgraph.graph.StateGraph`
(`base_graph.py:892`), a verification contract that overrides model claims with actually-observed
tool results (`base_graph.py:640-669`), stall detection, a planner node, a memory-hook node, a
reflection node, context trimming, budget enforcement, and failure-recovery checkpointing. **70 of
72 agent modules call `run_agent_graph(...)` directly.**

The two exceptions, both deliberate and documented, not bugs, and both **scheduled for a real
LangGraph conversion in Phase 5** (§5.1, §5.2) rather than left permanently excluded — converting
either one carelessly or early would be a regression, which is why the conversion is deferred and
scoped precisely rather than treated as an afterthought:
- **`chat_agent.py`** — an interactive, open-ended, multi-turn session, not a single-shot graph task.
  Runs its own hand-built loop (`MAX_ITERATIONS = 30`) over 36 real tools with human-confirmation
  gating (`session.request_confirmation()`). This is the single most capable agent in the current
  fleet. Forcing it into the *same single-task graph shape* as the other 70 would be a regression —
  but LangGraph also supports interrupt-based, multi-turn graphs (this codebase already uses that
  pattern for approvals elsewhere — see A.11), which is the real conversion target; see §5.2.
- **`manager.py`** — an async orchestrator (`run_manager`, `run_epic_manager`) that *dispatches*
  `backend_dev`/`frontend_dev`/`qa`/`reviewer`, each of which individually calls `run_agent_graph`.
  The manager coordinates graph-based agents rather than being a single LLM-driven task itself, so it
  needs a supervisor-graph shape, not the standard single-task shape; see §5.1.

## A.2 Tool provisioning: a 3-tier split, not a gradient

**Tier A — ~15 core agents** (`pm`, `architect`, `decomposer`, `planner`, `coder`, `backend_dev`,
`frontend_dev`, `qa`, `reviewer`, `devops`, `docs`, `research`, `bug_fix`, plus the 5 fleet
self-improvement agents) have genuinely tailored tool lists defined individually in
`app/agents/tools.py`: `CODER_TOOLS` (`tools.py:288-382`, includes `edit_file`, `write_file`,
`bash`, `submit_patch`), `QA_TOOLS` (`tools.py:384-429`, a *restricted* `bash` scoped to test/build
commands, explicitly "NO write_file, NO edit"), `REVIEWER_TOOLS` (`tools.py:462`), `DEVOPS_TOOLS`
(`tools.py:508`), `RESEARCH_TOOLS` (`tools.py:1136`, includes a **real** `web_search` tool backed by
`duckduckgo_search.DDGS` — confirmed working, not a stub), `DOCS_TOOLS` (`tools.py:1245`).
`coder.py:83-96` runs `mypy`+`ruff` *outside* the LLM loop and retries the whole graph run on failure
(`coder.py:128-203`) — a real, working self-correction loop.

**Tier B — ~24 agents run on a byte-identical generic template.** Confirmed via
`grep -n '_TOOLS = READ_ONLY_TOOLS + \[_WRITE, _SUBMIT\]' app/agents/*.py` → exactly 24 matches,
one per file (`test_writer_agent.py`, `debugger_agent.py`, `load_test_agent.py`, `infra_agent.py`,
`code_explainer_agent.py`, `accessibility_agent.py`, `compliance_agent.py`, `cost_estimator_agent.py`,
`incident_responder_agent.py`, `onboarding_agent.py`, `localization_agent.py`, `pair_programmer_agent.py`,
`spike_agent.py`, `rollback_agent.py`, `runbook_generator_agent.py`, `slo_agent.py`,
`feature_flag_agent.py`, `env_checker_agent.py`, `api_designer_agent.py`, `data_pipeline_agent.py`,
`dependency_security_agent.py`, `version_manager_agent.py`, `devex_agent.py`, `code_quality_agent.py`
— confirm the exact current list with the grep above before starting, names may have shifted).
`READ_ONLY_TOOLS` (`tools.py:22-287`) is 16 read-only tools; `_WRITE` is one generic whole-file
`write_file`; `_SUBMIT` is one generic `submit_<agent_name>`. **None of these 24 agents can run
`bash`, `run_tests`, or make a surgical edit (`edit_file`).**

**Concrete, confirmed consequence — a contract the tools cannot fulfill:** `test_writer_agent`'s own
role prompt (`roles/test_writer_agent.md:46-52,66-70`) requires "All role-relevant checks pass with 0
errors (tests / typecheck / lint as applicable)" and lists "Submitting `done` while tests, typecheck,
or lint fail" as a hard failure condition — **but the agent has no tool to run tests, typecheck, or
lint.** This exact boilerplate block appears verbatim in at least 14 role files
(`grep -l "All role-relevant checks pass with 0 errors" backend/roles/*.md`).

**Concrete, confirmed bug — dead tool-contract entries:** at least ~20-30 of these agents declare
`"parse_ast"` and/or `"list_functions"` in their `AGENT_CONTRACT["allowed_tools"]`
(`grep -l '"parse_ast"' app/agents/*.py`), but neither tool is in `READ_ONLY_TOOLS`
(`tools.py:22-287`) nor in the actual `tools=` schema passed to `run_agent_graph` — they only exist as
real handlers inside `make_chat_handlers()`'s 36-tool dict (`chat_agent.py:1607`). Since the Anthropic
API only allows a model to call tools declared in that specific request's `tools=` schema, **these
agents can never call `parse_ast`/`list_functions` regardless of what their published contract
claims.** `code_explainer_agent.py:74` and `code_quality_agent.py:73` even map
`VerificationConfig.set_by["parse_ast"] = "read"` — dead verification logic keyed to a tool the model
never sees. Anything that trusts `capability_registry`'s published `tools` list (e.g.
`fleet_manager.select(verify_tool_availability=True)`, called from `manager.py:190-192`) is being
lied to by this mismatch.

## A.3 Production-grade: no hard stubs, but real integrity gaps

No `NotImplementedError`/stub markers gate any agent's execution — every agent runs to completion.
But "runs to completion" is not "does the job":
- The 24 Tier-B agents produce plausible-sounding markdown reports, not verified artifacts, because
  they have no way to check their own claims.
- **Confirmed real placeholder inside otherwise-solid code:** `manager.py:775-782` — `run_epic_manager`'s
  epic cost tracking does a literal placeholder sum instead of real token accounting, silently
  falling back to the pre-run cost *estimate* as the reported "actual" cost. (Note: this is despite
  the *rest* of the cost infrastructure being real and working — see A.8. This is a narrow, specific
  bug in one aggregation, not evidence the cost system is generally unreliable.)
- Test coverage exists for every agent, but for the 24 Tier-B agents it's wiring checks only
  (`tests/test_gap_agents.py`: `test_tools_include_read_only`, `test_submit_handler_present`,
  `test_role_file_exists` — never "did this agent's output solve the task"). The tests that *would*
  validate real task-solving output for the Tier-A core agents live in `tests/pending/` and are
  **skipped by default**, only running with a real `ANTHROPIC_API_KEY`
  (`tests/pending/README.md:3`) — so ironically the better-built agents have less CI confidence
  behind them today than the thinner ones.

## A.4 Memory: three real, disconnected systems — only the weakest one is actually live

This is the most important finding for goal #5, and it was not obvious without tracing every call
site directly. There are **three separate memory subsystems**, and they do not talk to each other:

**System 1 — `LessonStore` (`base_graph.py:142-200`), what's ACTUALLY injected into every agent run.**
Explicitly documented as *"Thread-safe **in-process** lesson registry"* — pure Python, in a module
global, `capacity=1000` with FIFO eviction, retrieval by **keyword overlap only** (`base_graph.py:161`,
no embeddings). Read by `memory_hook_node` (`base_graph.py:350-389`) at the start of every
`run_agent_graph` call — this is the one, real, universal per-agent-run hook, confirmed wired for all
70 graph-based agents. Written by `lesson_node` after a submit (`base_graph.py:767`,
`get_lesson_store().add(lesson)` — the only call site of `.add()` in the entire codebase).
**Critical limitation: this store has zero persistence.** It is wiped completely on every process
restart/deploy/crash, and if the app ever runs more than one worker process, each process has its own
isolated copy — lessons learned by one worker are invisible to every other worker, permanently.

**System 2 — `memory_embeddings` (`app/memory/store.py`), DB-backed, pgvector, semantically
searchable, 4 categories — but only 2 of 4 write paths are ever called.**
- `embed_task_outcome` / `query_similar_tasks`: called for real, from `manager.py:816,836,877` (task
  pipeline) and `pipeline/graph.py:159-164` (PM planning graph). **Only agents driven through
  `run_manager()` ever write outcome memories** — the 24 Tier-B agents (and most Tier-A agents run
  standalone via `POST /api/agents/{name}/run`, not through the manager) never write here at all.
- `embed_learning_signal` / `query_learning_signals`: called only from `fleet_dashboard.py:177,180`,
  gated behind a human approving a fleet self-improvement suggestion.
- **`embed_architecture_note`, `query_architecture_notes`, `embed_failure`, `query_failures`: fully
  implemented, fully dead.** Verified directly: `grep -rn "embed_architecture_note\|embed_failure(\|query_architecture_notes\|query_failures(" app/`
  returns **zero real call sites** anywhere outside their own definitions in `store.py`. Two of the
  four documented memory categories have never been written to or read from by any agent, ever.

**System 3 — `versioned_lessons` (Day 11 Fleet OS, `app/fleet/versioned_memory.py`), DB-backed,
pgvector, HNSW-indexed, a full DRAFT → PUBLISHED → SUPERSEDED/MERGED_INTO → ARCHIVED lifecycle, with
`knowledge_curator.py` providing curation tools (`memory_search`, `memory_curate_read`,
`memory_curate_write`) — the most sophisticated memory system in the codebase, and it is completely
isolated.** Uses a genuinely novel similarity-based merge-on-conflict algorithm with LLM-assisted
merging (`versioned_memory.py:200-219`, explicitly documented as having no precedent in reference
repos it was built from). Verified directly: there is no code path anywhere that takes a `PUBLISHED`
`versioned_lessons` row and injects it into `LessonStore` (the only thing actually read before an
LLM call). Lessons curated and published through this system's real, careful lifecycle machinery are
written to the database and then never read by any running agent again.

**Net effect, stated plainly:** the owner's CI/CD-agent-should-know-what-debugger-agent-learned
scenario **does not work today**, for three independent reasons: (1) most non-manager-driven agents
never write any outcome memory at all; (2) the one memory store that IS read before every LLM call
is in-process, ephemeral, and keyword-only; (3) the one memory store built with real semantic search
and a real lifecycle is disconnected from live inference entirely.

**What memory this codebase captures is exclusively declarative ("what happened").** There is no
capture of *procedure* ("the sequence of steps that fixed a similar problem") anywhere — see A.15,
a genuine, newly-identified gap distinct from the three-systems problem above.

## A.5 Wiring points to build on (do not reinvent these)

- **`AgentCapability`** dataclass (`app/fleet/capability_registry.py:22-45`): `name`, `description`,
  `tools`, `input_types`, `output_types`, `capabilities`, `limits`, `dependencies`,
  `requires_worktree`, `requires_db`, `risk_level`. This is the existing "per-agent contract" schema
  — extend it, don't replace it.
- **`ensure_all_agents_registered()`** (`capability_registry.py:122-145`): scans `app/agents/` at
  runtime (not a hardcoded name list) and imports every module so its `_register()` hook fires — new
  agents are picked up automatically. This **is** a real dynamic-discovery mechanism already (see
  A.14) — any new per-agent metadata this plan adds should flow through this same pattern.
- **`app/fleet/agent_models.json`**: per-agent model-tier overrides (most agents `claude-sonnet-5`;
  `architect`/`decomposer`/`planner`/`executive`/`manager`/`research`/`architecture_reviewer`/
  `security_architect`/`rag_engineer_agent` get `opus`). The current thinness problem is a
  tool/scope problem, not a model-quality problem — do not "fix" Tier B by just changing its model
  tier.
- **Role files** (`backend/roles/*.md`): all 72 exist, none are empty/placeholder, but the 24 Tier-B
  agents' role files are structurally near-identical (same section headings, nouns swapped) versus
  the bespoke, stack-specific Tier-A prompts (`roles/coder.md` is 111 lines and cites this repo's
  actual FastAPI/Next.js stack and exact `mypy`/`pytest` commands; `roles/qa.md`/`roles/reviewer.md`
  are 146-147 lines). Role file quality already correlates with tool depth — fixing tools without
  also sharpening the corresponding role prompt will not close the gap.

## A.6 Repository Intelligence — already real and substantial, not just file indexing

This directly addresses what was requested as a "Repository Knowledge Graph" — most of it already
exists, and in one respect (a real, ranked call graph) it goes beyond what was asked for.

- **`app/repo_tools/scanner.py:1-263`** — real tree-sitter parsing (Python + JS/TS/JSX), extracting
  a genuine symbol table (`SymbolInfo`: classes/functions/methods with real line ranges) and raw
  import edges. **Incremental**: re-indexes only changed files via content-hash comparison, not a
  full rescan every time. `build_call_graph()` (`scanner.py:237-263`) provides a basic import-string
  match graph.
- **`app/repo_tools/cross_file_graph.py`** (215 lines) — a **real, function-level cross-file call
  graph with PageRank ranking** of central/important files and symbols. This is the graph
  `context_builder.py:99-134` and `architecture_mapper.py:38,99` actually use for dependency-chain
  reasoning — a materially more sophisticated structure than the scanner's own basic import graph,
  and explicitly built to fix a prior, cruder heuristic (`context_builder.py:98-102`'s own comment
  documents this history).
- **`app/repo_tools/context_builder.py:1-165`** — combines keyword scoring, semantic search, and the
  real cross-file graph to assemble task-relevant context.
- **`app/repo_tools/architecture_mapper.py:1-182`** — LLM-driven architecture summary seeded by the
  real PageRank-central files/symbols from `cross_file_graph.py`, not an LLM guessing from scratch.
- **DB schema**: `indexed_files`, `symbols` (FK to `indexed_files`), `call_edges` (caller/callee
  file+symbol+edge_type) — `migrations/versions/001_initial_schema.py:145-205`,
  `app/db/models.py:225-266`. Plus `code_embeddings` (pgvector, semantic code search).

**What's genuinely missing relative to the original 10-graph-type request:** a distinct *class
graph* (inheritance/composition relationships as a queryable structure, not just symbols tagged
`kind="class"`), a distinct *package/module dependency graph* at the directory/package level (vs.
the current file-level `call_edges`), and an *ownership graph* (who/what agent last touched a given
symbol — this ties naturally into the audit log, see A.10). A *reference graph* (find-all-usages) is
partially covered by the existing `find_references` tool (`tools.py`, part of `READ_ONLY_TOOLS`) but
is not itself backed by a persisted graph structure — it's a live, per-call search. See Phase 6 for
the scoped extension (not a from-scratch rebuild).

## A.7 Observability — Sentry is real; distributed tracing is not

- **Sentry: genuinely wired, not configured-but-unused.** `config.py:213-221` defines
  `sentry_dsn`/`sentry_environment`/`sentry_traces_sample_rate`; `app/main.py:45-79`'s `_init_sentry()`
  actually calls `sentry_sdk.init()` with FastAPI, SQLAlchemy, and Asyncio integrations, guarded by an
  `ImportError` fallback and a `before_send` redaction hook (so secrets don't leak into error
  reports). This is real production error tracking, already running.
- **A home-grown span/metrics system exists**: `app/fleet/metrics.py:257-278`'s `run_span()` context
  manager (used at `base_graph.py:1042`) provides timing and status tracking per agent run — a
  lightweight, working substitute for distributed tracing, but not OpenTelemetry-compatible and not
  exportable to standard tracing backends (Jaeger, Tempo, etc.).
- **Genuinely missing:** OpenTelemetry itself — zero references anywhere in `app/` (`grep -r
  "opentelemetry\|OTEL"` returns nothing). No distributed trace correlation across the
  request → agent-dispatch → tool-call chain; `run_span()`'s output isn't queryable as a trace tree
  today, only as discrete metric records. See Phase 6.1 for the scoped fix (bridge `run_span` to
  OTEL-compatible spans, don't replace the whole metrics system).

## A.8 Cost Intelligence — already real and reasonably deep

- **`app/fleet/budget_manager.py`** (155 lines): `BudgetManager.check_run()` enforces real per-run
  token/wall-clock-time/memory limits (with a genuine cross-platform, Windows-compatible RSS-memory
  reader via `ctypes`, not just a Linux-only stub); `check_daily()` enforces `cost_budget_daily_usd`
  against actual accumulated `RunMetrics`, not an estimate.
- **`app/pipeline/cost_controller.py`** (131 lines): `estimate_epic_cost()` pulls real historical
  average token usage from the `agent_runs` table (a genuine SQL aggregation, not a hardcoded
  constant) and only falls back to config coefficients when there's no history yet; gates human
  approval via `requires_approval` when an epic's estimated cost crosses `cost_approval_threshold`.
- **Real DB columns, real writes**: `AgentRun.tokens_in`, `tokens_out`, `cost_estimate` (populated by
  `finish_agent_run()`, `app/db/repository.py:255-276`) are genuinely populated per run, not left at
  their defaults.
- **Genuinely missing:** a *reporting surface* over this already-collected data — there is real cost
  data per run/agent/day, but no dashboard/report endpoint that aggregates "cost per agent this
  week," "cost per model tier," or flags anomalies. The intelligence to *compute* these numbers
  already exists in the schema; what's missing is exposing it. See Phase 6.2.

## A.9 Health Monitoring — already real, functioning liveness tracking

- `AgentRun.last_heartbeat_at` (`app/db/models.py`) is a real column.
- `app/db/repository.py:246-252`'s `heartbeat_agent_run(db, run_id)` performs a genuine
  `UPDATE ... SET last_heartbeat_at=now()` + commit, called fire-and-forget via
  `asyncio.create_task()` during a live agent run — this is real per-run liveness tracking, not a
  static field nobody updates.
- `GET /health` (`app/main.py`, documented in `docs/DEPLOYMENT.md`) does a real DB `SELECT 1`,
  conditional Redis/S3 checks, and reports a real agent-registry count — confirmed in Audit 06 to
  return accurate, non-hardcoded values.
- **Genuinely missing:** aggregate fleet health (queue depth, per-agent failure rate, restart count
  trends over time) — the raw data exists (`agent_runs.status`, `last_heartbeat_at`) but nothing
  aggregates it into a fleet-wide health signal an operator or another agent could query. See Phase
  6.2 (folded into the same reporting-surface work as cost intelligence, since both are "aggregate
  what's already collected," not "collect something new").

## A.10 Security Hardening — already mature, not a green-field task

- **`app/policy/engine.py`** (322 lines): a real, battle-tested command/path denylist (`rm -rf` and
  its flag-order variants, `sudo`, `dd`, `mkfs`, fork bombs — with a documented history of real
  regex bugs found and fixed, not aspirational), `curl|wget https?` blocking, shell-chaining
  metacharacter rejection under `strict=True`, `.env`/`secrets/`/`*.pem`/SSH-key/`.git/` path
  denial, and a symlink-escape-safe worktree boundary check via `realpath`
  (`engine.py:121-141`), plus `check_command_stays_in_boundary()` (`engine.py:285-322`) catching
  `cd <absolute-path>` sandbox escapes.
- **`app/security/credential_vault.py`** (226 lines): real Fernet encryption at rest
  (`encrypt_value`/`decrypt_value`), with a documented plaintext fallback + one-time startup warning
  (not a silent, unsafe default) when no encryption key is configured; `ProjectCredentials` uses
  Pydantic `SecretStr` with an explicit `expose_secrets` gate before any value is ever serialized out.
- **`app/fleet/audit_log.py`** (274 lines): a real, append-only audit log (dual-write: in-memory ring
  buffer + async DB persistence), immutable by design — no update/delete method exists on it at all.
  Already called from the credential vault on every credential load/store.
- **Genuinely missing, and these are real, worth adding (not enterprise-scale speculation):**
  prompt-injection-specific defenses (untrusted content, e.g. a fetched web page or a file an agent
  reads, is not currently tagged/delimited as data-not-instructions anywhere in the prompt
  construction — a known, real risk class for any tool-using LLM agent) and malicious tool-output
  validation (a tool's return value is trusted as-is by the calling agent; there's no sanitization
  layer for, e.g., a `bash` command's stdout being crafted to look like a system message). See
  Phase 6.3.

## A.11 Human-in-the-Loop foundations — already substantial, not a green-field task

- **`app/fleet/approval_gate.py`** (266 lines): real DB-backed CRUD over `PendingApproval` rows —
  `record_pending()` correctly supersedes stale pending rows left over from a crashed process
  restart (`approval_gate.py:82-94`, a genuine crash-recovery detail, not an oversight), plus both
  sync and async variants for use from a background task vs. the live FastAPI event loop.
- **`app/pipeline/graph.py:87-134`**'s `human_review_node()` uses LangGraph's **real** `interrupt()`
  primitive with a real `AsyncPostgresSaver` checkpointer (`interrupt_before=["human_review"]`) —
  genuinely resumable execution across a process restart, not an in-memory-only pause. This is the
  exact mechanism Phase 5.2/5.3 (chat_agent conversion, `request_clarification`) are built on —
  it already works for one code path today.
- Table: `pending_approvals` (`migrations/versions/015_pending_approvals.py`).
- **What's genuinely missing** (this is where the v2 "HITL Framework" request has real substance):
  this mechanism today is specific to plan-review pauses. It is not yet generalized into a single,
  documented framework covering approvals + clarifications + escalation + override + audit trail as
  one coherent API other agents/endpoints can all use the same way. See Phase 5.5.

## A.12 Workspace Awareness — mostly real already

- **`app/services/git_service.py`**: real, async, subprocess-backed `git_status`, `git_log`,
  `git_diff`, `git_add`/`git_commit`/`git_push`, `git_branch_list`, `git_checkout`, `git_pull`, plus
  clone/init with real URL/host validation.
- **`app/repo_tools/worktree.py`** (136 lines): `create_worktree()` verifies a pre-existing directory
  via a real `git worktree list --porcelain` check before trusting it, with genuine stale/crashed
  worktree recovery (rebuild rather than silently reuse); `get_diff()`, `preserve_worktree()`,
  `remove_worktree()` are all real.
- `git blame` exists too, just as an agent tool (`app/agents/tools.py`) rather than in
  `git_service.py` — a location inconsistency, not a missing capability.
- **Genuinely missing:** a standalone, directly-callable `list_worktrees()` function (worktree
  listing currently only happens internally inside `create_worktree()`'s own validation, not exposed
  for other callers), and merge-conflict-state awareness (no code currently reads a repo's real
  conflict-marker state — this matters if any future agent is expected to help resolve a merge
  conflict). Both are small, targeted additions, not a rebuild. See Phase 4's checklist.

## A.13 Rate Limiting & Concurrency — already real

- `config.py:474-489`'s `rate_limit_enabled`/`rate_limit_default`/`rate_limit_tasks`/
  `rate_limit_agents` are genuinely wired: `app/main.py` sets up a real slowapi `Limiter` on
  `app.state.limiter` with a real `RateLimitExceeded` handler and `SlowAPIMiddleware` — not unused
  config fields.
- `app/pipeline/concurrency.py` (82 lines): real `asyncio.Semaphore`-based concurrency caps
  (`epic_slot()`, `agent_run_slot()`, `subtask_slot()`) already enforce `max_concurrent_epics`/
  `max_concurrent_agent_runs`/`max_concurrent_subtasks_per_epic` for real, in-process. This is the
  right-scoped concurrency primitive for this project's actual deployment shape (single process);
  see Appendix D.1 for when this would need to become distributed instead.

## A.14 Extensibility patterns — a real adapter pattern exists, narrowly

- `capability_registry.py:122-145`'s `ensure_all_agents_registered()` **is** real dynamic capability
  discovery for agents specifically: it globs `app/agents/*.py` at runtime and imports each module so
  its `_register()` hook fires, with no hardcoded dispatch table — new agent files are picked up
  automatically. This already satisfies the core of what "dynamic capability discovery" was asking
  for, scoped to agents.
- `app/pipeline/queue_adapter.py` (209 lines): a clean `QueueAdapter` ABC with a real default
  (`AsyncioQueueAdapter`), a real Redis-backed bridge (`RQAdapterBridge`), and an explicit,
  honestly-labeled stub (`BullMQQueueAdapter`, raises `NotImplementedError`) — this is a legitimate,
  working example of the adapter pattern the "Plugin Architecture" request was reaching for,
  successfully applied to exactly one thing (queue backend) that actually has more than one real
  implementation today.
- **Why this isn't generalized further in this document:** every other category requested for a
  "plugin architecture" (memory backend, model provider, retrieval backend, observability backend)
  currently has exactly one real implementation each in this codebase. Generalizing an adapter
  pattern before a second real implementation exists is speculative — you'd be designing an interface
  against a sample size of one, which tends to produce the wrong abstraction. See Appendix D.3 for
  the trigger condition.

## A.15 Procedural memory — a genuine, confirmed gap

- `app/fleet/failure_ladder.py` (191 lines) is real and complete for *failure handling*:
  `checkpoint`/`rollback` (real, re-exported from `fleet_checkpoint.py`), `should_retry()` (bounded,
  respects `manager_max_subtask_retries`), `escalate()` (publishes a real health event),
  `abort()`/`request_human_review()` (real DB status transitions). This is entirely about *what to do
  when something fails right now* — it is not memory.
- `app/fleet/versioned_memory.py` stores *declarative* lessons/insights ("what we learned"), with a
  real, novel merge-on-conflict lifecycle (A.4, System 3).
- **Confirmed via grep: no `repair_strategy`/`playbook`/`fix_pattern` structure exists anywhere in
  `app/`.** There is no capture of *procedure* — "given symptom X, the sequence of diagnostic and
  corrective steps that resolved it last time" — anywhere in this codebase. This is the one part of
  the original memory-architecture critique that both v1 and the verification pass agree is
  genuinely, currently missing, not just disconnected. See Phase 1.5 for the scoped fix.

---

# PART B — Implementation Plan

Work these phases in order: **1 → 2 → 3 → 4 → 5 → 6.** Each phase is independently regression-tested
(§9) before moving on. Phases are organized by theme, not by "old work" vs. "new work" — new
capabilities are integrated into the phase where they belong architecturally, not appended as an
afterthought.

## Phase 1 — Memory & Context Architecture (fix this first; everything else depends on it)

This is Phase 1, not last, deliberately: every later phase produces agents whose whole value
proposition is "benefits from and contributes to shared fleet knowledge" (goal #5). Building 57 more
tool-upgraded agents on top of a memory system that doesn't actually share anything — or that
captures only facts, never procedure — would just widen the gap the owner is actually pointing at.

**1.1 — Consolidate to one write path, DB-backed, semantically searchable, for every agent.**
Every agent that completes a run (success, blocked, or failed — not just the manager-driven ones)
must write an outcome record. Concretely:
- Add a single, universal post-run hook inside `base_graph.py`'s `run_agent_graph` (not per-agent
  code) that calls `app/memory/store.py`'s existing `embed_task_outcome` (success/blocked) — extend
  its call sites beyond `manager.py` so it fires for **every** `run_agent_graph` completion,
  regardless of whether it was manager-dispatched or dispatched directly via
  `POST /api/agents/{name}/run`.
- Wire `embed_failure` for real (it currently has zero callers): call it from the same universal
  post-run hook whenever a run ends in a failure/blocked state with a real error, using the actual
  error/root-cause text, not a placeholder.
- Wire `embed_architecture_note` for real (zero callers today): any agent whose role produces a
  design/architecture decision (`architect`, `database_architect`, `security_architect`,
  `api_designer_agent`, and any agent tagged `capabilities=["architecture"]` in its
  `AgentCapability`) should call this when it submits, not leave it dark.
- Every one of these writes must include `agent_name` in the stored record (the current schema
  supports this via the `task_id`/`epic_id` fields and the `learning` category's `fleet-{agent_name}`
  convention at `store.py:390` — generalize that convention to the other three categories too, so a
  query can filter/attribute "what did *debugger_agent* specifically learn" instead of only
  "what happened on task N").

**1.2 — Bridge the two DB systems, or retire one. Do not leave three.** Decide and implement one of:
- (a) Retire `versioned_lessons`' separate lifecycle and have `knowledge_curator` curate directly
  into `memory_embeddings`' `learning` category, or
- (b) Keep `versioned_lessons` as the curated, human-reviewed tier, and add a real sync: when a
  lesson reaches `PUBLISHED` state, also write/update a corresponding `memory_embeddings` row
  (category=`learning`) so it becomes reachable by the same query path every other memory read uses.
Pick (b) unless you find a concrete reason not to — `versioned_lessons`' DRAFT→PUBLISHED human-review
gate, and its genuinely novel similarity-based merge algorithm, are valuable and shouldn't be thrown
away; they just need to feed the live path.

**1.3 — Replace (or supplement) `LessonStore`'s read path with real semantic search.** The
in-process, keyword-only, ephemeral `LessonStore` should stop being the *only* thing
`memory_hook_node` reads. Change `memory_hook_node` (`base_graph.py:350-389`) to also query
`memory_embeddings` (via `query_similar_tasks`, `query_failures`, `query_learning_signals` — all
already implemented, just under-called) using the task description as the query, and merge those
results into `memory_context` alongside (not instead of — keep it as a fast, zero-latency
first-pass) whatever `LessonStore` returns. This is the single change that makes cross-agent,
cross-restart, cross-process shared memory real for the first time.

**1.4 — Give every agent an explicit memory-write step in its own tool contract**, not just an
automatic hook the agent doesn't control. Add a `record_learning` tool (thin wrapper around
`embed_learning_signal`, scoped to the calling agent's own name) to every agent's tool list —
this lets an agent explicitly flag "this was a non-obvious finding worth remembering" (e.g.
`debugger_agent` finding a root cause an obvious search wouldn't surface) rather than relying
purely on the generic post-submit hook to capture everything worth keeping.

**1.5 — Add procedural memory: capture *how*, not just *what*.** This closes the confirmed gap in
A.15. Add a new memory category (`category="procedure"` on `memory_embeddings`, matching the existing
`task`/`architecture`/`failure`/`learning` categories rather than inventing a parallel table) storing
a structured record: `symptom` (what the problem looked like), `steps_taken` (ordered list of real
actions — tool calls, diagnostic commands, the actual sequence, not a summary), `resolution` (what
fixed it), `agent_name`, and a reference back to the `task_id` where it happened. Write this from the
same universal post-run hook as 1.1, but only when a run required genuine iteration to succeed
(more than one retry, or the failure ladder's `should_retry()` fired at least once) — a task that
succeeded on the first attempt has no interesting procedure to record. On read, extend
`memory_hook_node` (already being changed in 1.3) to also query this category when a new task's
description keyword/semantically overlaps a past `symptom` — this is what makes the owner's
CI/CD-agent-benefits-from-debugger_agent's-prior-work scenario concretely real: a future `cicd_agent`
diagnosing a failing pipeline can retrieve *the actual steps* a past agent took to fix a similar
class of failure, not just a one-line summary of that it was fixed.

**1.6 — Context engine tiering, scoped to what this project's actual scale needs.** The current
system effectively has two tiers already (in-process `LessonStore` = ~session-scoped;
`memory_embeddings`/`versioned_lessons` = long-term/project-scoped) without naming them as such.
Make the tiering explicit and add the two genuinely missing tiers:
- **Working memory** (already exists: `AgentRunState` within a single `run_agent_graph` invocation —
  name it explicitly in documentation, no code change needed).
- **Session memory** (already exists: `LessonStore`, in-process, cleared on restart — this is
  correctly *session*-scoped, not a bug on its own; the bug was that nothing else backed it up,
  fixed by 1.3).
- **Project memory** (already exists: `memory_embeddings`/`versioned_lessons`, scoped by `task_id`/
  `epic_id` within one repo/project).
- **Fleet memory** (new, small addition): a query mode across `memory_embeddings` that does *not*
  filter by project/repo — for genuinely cross-project lessons (e.g. "this class of dependency-version
  bug has bitten 3 different repos"). Implement as an optional `cross_project=True` flag on
  `query_learning_signals`/`query_similar_tasks`, not a new table.
- **Archived memory** (already exists in spirit via `archived`/`archived_at` on `memory_embeddings`
  and `versioned_lessons`' `ARCHIVED` state, both fixed for real in `docs/reports/AUDIT_06_INFRASTRUCTURE.md`
  — confirm those fixes are still in place, don't reintroduce the timezone drift documented there).
- **Long-term memory**: this *is* `memory_embeddings`/`versioned_lessons` — do not build a fifth
  system; "long-term" and "project" memory are the same tier in this architecture, just described
  with two different words in the original request. Naming them as the same tier in documentation
  prevents a future implementer from building a redundant fifth memory system.
- **Automatic compression / hierarchical summarization / token budget optimization**: partially
  exists already — `base_graph.py`'s "Context trim" (Session 0 addition, per its own module
  docstring, using `LangGraph RemainingSteps` + a roo-code-derived condense pattern) already enforces
  `context_token_budget`. What's missing is *hierarchical* summarization (condensing old turns into a
  running summary rather than simply trimming) — add this as an enhancement to the existing trim
  logic, not a parallel system.
- **Context expiration/prioritization**: `memory_top_k` (existing config) already prioritizes by
  similarity score at read time. Expiration is what `archived_at`/retention already does at the
  storage layer. No new mechanism needed — document the existing ones as fulfilling this requirement.

**1.7 — Shared scratchpad: real, but scoped to actual multi-agent handoff, not speculative
generality.** Add a lightweight, ephemeral (not permanently persisted — this is explicitly *not*
long-term memory) key-value structure scoped to one `epic_id`, backed by a new small table or a
Redis-backed structure if `REDIS_STREAMS_ENABLED`/`QUEUE_BACKEND=rq` is already on (reuse the
existing Redis connection rather than adding a new dependency — see A.14's reasoning about not
generalizing infrastructure before it's needed). Agents dispatched within the same epic (e.g.
`backend_dev` and `qa` on sequential subtasks of the same epic, already coordinated by `manager.py`)
can read/write short-lived discoveries, hypotheses, and partial findings here, distinct from the
permanent memory writes in 1.1-1.5. Expire scratchpad entries when the epic completes or after a
bounded TTL, whichever is first — this must never become a fourth permanent memory system; if
something in the scratchpad is worth keeping, it should be explicitly promoted to `memory_embeddings`
via 1.4's `record_learning` tool, not left to accumulate indefinitely.

**Definition of Done — Phase 1:**
- [ ] `embed_task_outcome`, `embed_failure`, `embed_architecture_note`, `embed_learning_signal` each
      have real, non-test call sites reachable from *every* agent completion path, not just
      `manager.py`'s. Verify with `grep -rn` the same way this document's evidence was gathered —
      zero of the four should show only their own definition anymore.
- [ ] `memory_hook_node` demonstrably returns results sourced from `memory_embeddings` (DB), not only
      `LessonStore` (in-process) — write a test that seeds a `memory_embeddings` row via one "agent,"
      then asserts a *different* simulated agent's `memory_hook_node` call surfaces it.
- [ ] A published `versioned_lessons` row is provably reachable from the same query path a live agent
      run uses (either via bridge-sync per 1.2(b), or via retirement per 1.2(a) — either way, prove
      it with a test, not a reading of the code).
- [ ] A `category="procedure"` memory record, written after a real multi-retry run, is retrievable by
      a *different* simulated agent facing a symptom-overlapping task — proven with a test, not
      inferred from the write path existing.
- [ ] The five memory/context tiers (working, session, project/long-term, fleet, archived) are each
      documented with their real backing implementation (no tier should point at a system that
      doesn't exist) and a test exists demonstrating each tier's read and write path.
- [ ] The shared scratchpad demonstrably expires (TTL or epic-completion, whichever fires) — a test
      that writes a scratchpad entry, completes the epic, and asserts the entry is gone.
- [ ] Full regression suite (§9) still green.

## Phase 2 — Standardize tool provisioning: replace the Tier-B template with real, role-specific contracts

For each of the ~24 Tier-B agents (re-derive the exact current list via the grep in §A.2 before
starting — do not trust a possibly-stale list), do the following, **per agent, not as a bulk
find-replace**:

**2.1 — Classify the agent's real job** into one of these tool tiers (extend if a genuinely new
shape emerges, but justify why the existing tiers don't fit before adding a fifth):
- **Executor tier** (agents that must run/build/test something): needs `bash` (scoped — see 2.2),
  `edit_file`, `write_file`, `run_tests`/`run_linter` as appropriate, plus `READ_ONLY_TOOLS`.
  Examples from the current Tier B: `test_writer_agent` (must be able to *run* the tests it writes),
  `load_test_agent` (must be able to *execute* a load test), `debugger_agent` (must be able to
  reproduce — run the failing command/test), `infra_agent` (must be able to apply and verify an
  infra change in a sandboxed/dry-run mode at minimum).
- **Analyzer tier** (agents that produce a report/recommendation but genuinely don't mutate
  anything): `READ_ONLY_TOOLS` + real code-intelligence tools (`parse_ast`, `list_functions`,
  `list_classes`, `find_function_body` — the ones currently declared-but-unreachable per §A.2, now
  actually wired into `tools=`) + a structured `submit_<agent>` schema. Examples: `code_explainer_agent`,
  `compliance_agent` (if genuinely advisory-only in this org's process), `cost_estimator_agent`.
- **Editor tier** (agents that write/modify but don't need arbitrary bash): `READ_ONLY_TOOLS` +
  `edit_file` + `write_file` + a scoped verification tool (e.g. a syntax/type check, not full test
  execution) + `submit_<agent>`. Examples: `localization_agent`, `runbook_generator_agent`,
  `onboarding_agent` (writing docs/config that should at least be syntax-validated before submit).

**2.2 — `bash` access must be scoped, mirroring `QA_TOOLS`' existing pattern** (`tools.py:384-429`,
"NO write_file, NO edit" for QA's restricted bash) — do not just hand every Executor-tier agent
unrestricted `bash`. Each agent's `bash` scope should be an explicit allowlist/denylist appropriate
to its job (e.g. `load_test_agent` needs to run a load-testing tool and read its output, not arbitrary
shell). Route every new bash grant through the existing `app/policy/engine.py` checks (`check_command`,
`check_allowlisted_command`) established across the rest of this codebase — do not bypass them, and
do not reimplement ad hoc checks (this policy engine is mature — see A.10 — trust it).

**2.3 — Fix the dead-contract bug for real.** For every agent whose `AGENT_CONTRACT["allowed_tools"]`
currently lists a tool not present in its actual `tools=` schema (the `parse_ast`/`list_functions`
bug from §A.2), either (a) add the real tool implementation to that agent's tool list so the contract
is true, or (b) remove the false claim from the contract. Do not leave any published
`AgentCapability.tools` entry that the agent cannot actually invoke — this field is trusted
elsewhere (`manager.py:190-192`'s `verify_tool_availability=True` path) and a false entry there is a
correctness bug, not cosmetic.

**2.4 — Sharpen the corresponding role prompt alongside the tool upgrade**, not after. A role prompt
that says "run tests and confirm 0 failures" is only honest once the agent has a real `run_tests`
tool — update `roles/<agent>.md` in the same change as the tool contract, and make the prompt
specific to the agent's actual job (matching `roles/coder.md`'s bar: cite the real stack, real
commands, real file conventions) rather than leaving the generic templated boilerplate in place with
new tools bolted on.

**Definition of Done — Phase 2:**
- [ ] Zero agents remain on the literal `_TOOLS = READ_ONLY_TOOLS + [_WRITE, _SUBMIT]` template —
      verify with the same grep from §A.2; it should return 0 matches.
- [ ] Every agent classified as Executor tier has a real, working `bash`/`run_tests` path, verified
      by an actual test that has the agent run something and observes a real pass/fail result flow
      into `state["verification"]` (not just that the tool exists in the schema).
- [ ] `grep -l '"parse_ast"' app/agents/*.py` — for every file matched, `parse_ast` is either in that
      agent's real `tools=` list (verify by reading the `_TOOLS` construction, not just the contract)
      or removed from `AGENT_CONTRACT["allowed_tools"]`. Zero remaining mismatches, verified per-file.
- [ ] Every upgraded agent's role file no longer matches the 14-file boilerplate block
      (`grep -l "All role-relevant checks pass with 0 errors" backend/roles/*.md` should shrink, and
      every remaining match should correspond to an agent whose tools genuinely satisfy that claim).
- [ ] Every new `bash` grant is routed through `app/policy/engine.py` — verified by a test per agent
      that a denylisted command (e.g. `rm -rf /`) is still rejected for that agent specifically, not
      just at the policy-engine unit-test level.
- [ ] Full regression suite (§9) still green.

## Phase 3 — Production-grade verification, self-critique, and continuous replanning

**3.1 — Every agent must set `state["verification"]` flags from real tool output, not model claims**
— this pattern already exists in `base_graph.py` (per its own docstring: "the model's claims... are
OVERRIDDEN by this dict"); the work here is ensuring every *newly capable* Executor/Editor-tier
agent from Phase 2 actually participates in it (mutating tools invalidate `tests_passed`;
verification tools set flags only on a real, error-free completion — do not let a new agent's
`submit_*` handler accept an unverified boolean claim).

**3.2 — Fix `manager.py`'s fake cost placeholder** (`manager.py:775-782`). Replace the placeholder
sum with a real aggregation over `agent_runs.tokens_in`/`tokens_out`/`cost_estimate` for the epic's
actual runs — the underlying cost-tracking infrastructure is already real (A.8); this is fixing one
specific broken aggregation, not building cost tracking from scratch. Build on the verified-clean
schema from `docs/reports/AUDIT_06_INFRASTRUCTURE.md`'s ORM/DB timezone fixes to this same table
family — don't reintroduce that drift.

**3.3 — `chat_agent.py`'s and `manager.py`'s core shape are not touched in this phase** (§A.1) — their
LangGraph conversion is deliberately deferred to Phase 5 (§5.1, §5.2), after the rest of the fleet is
stable. Do apply the *memory* changes from Phase 1 to both of them now (both should read from and
write to the unified memory system), since goal #5 applies to the whole fleet immediately, not just
the `run_agent_graph` subset, and doesn't need to wait for their structural conversion.

**3.4 — Real output verification tests, not just wiring tests, for every agent.** The existing
`tests/test_gap_agents.py`-style tests (`test_tools_include_read_only`, `test_role_file_exists`)
check that an agent is *wired correctly*; add tests that check an agent's *verification loop actually
gates on real tool output* — e.g., for an Executor-tier agent, a test that mocks a failing test run
and asserts the agent's `submit_*` result correctly reports `tests_passed=False` (sourced from
`state["verification"]`, not from what the mocked LLM response merely claimed).

**3.5 — Formalize self-critique as a real, scored loop, building on the existing reflection node.**
`base_graph.py`'s `reflection_node` already implements an AutoGen-style "reflect on tool use" pattern
(per its own Session 0 changelog) — this is a real starting point, not a green field. Extend it into
an explicit Plan → Execute → Critique → Improve → Verify cycle:
- **Critique step**: after `reflection_node` runs, add a structured self-assessment against the
  agent's own submitted claim — a small, cheap LLM call (same or lower tier than the agent's own
  model) that scores the just-completed work against concrete criteria pulled from the agent's role
  file's own "Quality Gates"/"Success Criteria" section (already present in every role file per A.5 —
  parse it, don't duplicate it as a separate spec). Score as a structured `{criterion: bool, evidence:
  str}` list, not a single vague number — an unexplained "7/10" is not verifiable, an evidenced
  per-criterion checklist is.
- **Improve step**: when the critique finds a criterion unmet, feed it back into the graph as a new
  turn (reusing the existing retry/turn-budget machinery, `max_turns`) rather than a separate
  mechanism — this is "the graph runs again with new information," not a new control-flow system.
- **Require evidence-backed self-evaluation**: the critique step's output must cite the actual tool
  call/output it's evaluating (a real `state["verification"]` entry or a real file diff), never a bare
  claim — this mirrors the exact "model claims are overridden by observed results" contract the graph
  already enforces elsewhere; the critique step must be held to the same standard it's applying.

**3.6 — Continuous replanning, bounded, building on the existing planner node.** `base_graph.py`'s
`planner_node` (Session 0 addition) already produces an initial plan with a `confidence` field before
execution starts. Extend it so the graph can re-invoke a lightweight replanning step mid-execution
when: (a) a tool call reveals a fact that contradicts the initial plan's assumptions (detect this via
the reflection node noticing a plan-vs-reality mismatch, not a new detection mechanism), or (b) the
critique step from 3.5 repeatedly fails the same criterion across retries (signaling the *plan*, not
just the *execution*, needs to change). Bound this strictly: replanning consumes from the same
`max_turns`/`max_retries` budget as everything else — an agent that can replan indefinitely is
functionally an agent with no turn limit, which defeats the budget enforcement `base_graph.py`
already has (A.8-adjacent — don't create a loophole in the cost controls Phase 3.2 just fixed).

**3.7 — Formal quality gates before any `submit_*` is accepted as final.** Consolidate what's already
partially enforced (verification flags from 3.1, policy compliance from Phase 2.2, the critique
checklist from 3.5) into one explicit gate function every agent's submit path calls: verification
(3.1), reproducibility (can the claimed result be reproduced by re-running the same verification tool
— relevant for Executor-tier agents specifically), evidence validation (3.5's citation requirement),
consistency (the submitted result doesn't contradict `state["verification"]`), policy compliance
(every tool call in the run passed `app/policy/engine.py`, not just the final one), and a confidence
threshold (below which the result routes to `request_clarification` from Phase 5.3, or human review
via the existing `PendingApproval` mechanism from A.11, instead of auto-completing). This is
integration work over already-existing pieces, not a new subsystem.

**Definition of Done — Phase 3:**
- [ ] Every Executor/Editor-tier agent from Phase 2 has at least one test proving its verification
      flags are driven by real tool output, not model narration.
- [ ] `manager.py`'s epic cost reporting is real, tested against actual `agent_runs` aggregation.
- [ ] The self-critique loop produces a structured, evidenced per-criterion checklist (not a bare
      score) for at least one full end-to-end test per agent tier (Executor/Analyzer/Editor).
- [ ] Continuous replanning is demonstrably bounded — a test that forces repeated plan-vs-reality
      mismatches confirms the agent halts/escalates at the turn budget rather than looping forever.
- [ ] The formal quality gate function is the single path every agent's `submit_*` routes through —
      verified by confirming no agent has a `submit_*` handler that bypasses it.
- [ ] Full regression suite (§9) still green.

## Phase 4 — "Near Claude Code" capability baseline, applied fleet-wide

This phase is a checklist applied to every agent, cutting across the tiers above — it's the
concrete, checkable definition of goal #4 ("all types of functionality Claude Code has," corrected
per the Reality Check above to mean *working pattern* parity, not general-assistant parity).

For every agent, confirm and fix as needed:
- [ ] **Can it read broadly** (not just the one file it's told about)? — `search_code`,
      `get_file_tree`, `find_references` from `READ_ONLY_TOOLS` should be available to all 72; this
      is already mostly true (§A.2) — verify no agent lost this in the Phase 2 rework. Confirm it can
      also reach the real repository intelligence layer (A.6) — the call graph and PageRank ranking,
      not just flat file listing, for any agent whose job benefits from "what's actually central to
      this codebase" (most Analyzer-tier agents do).
- [ ] **Can it verify its own output** appropriate to its role (run the test it wrote; lint the code
      it edited; validate the config it generated)? — this is Phase 2/3's core deliverable.
- [ ] **Can it iterate on failure**, not just report it? — Tier-A's `coder.py:128-203` retry-until-
      static-checks-pass pattern is the reference implementation; every Executor-tier agent from
      Phase 2 should have an equivalent bounded retry loop (respecting `max_retries`/
      `manager_max_subtask_retries` config, not unbounded), now formalized via Phase 3's self-critique
      and quality-gate machinery.
- [ ] **Does it benefit from and contribute to fleet memory** (Phase 1), including procedural memory
      (1.5), not just declarative outcome records? — every agent, not only the Tier-A ones.
- [ ] **Does it have real workspace awareness** where relevant to its job — git status/diff/log/blame
      for any agent whose work depends on repo state (A.12)? Not every agent needs this (an
      `env_checker_agent` checking system dependencies has no reason to care about git blame) — apply
      it where the role genuinely calls for it, not universally.
- [ ] **Can it ask for clarification instead of silently guessing** on a genuinely underspecified task
      (Phase 5.3)?
- [ ] **Is its role prompt specific and honest** about what it can and cannot do (Phase 2.4), rather
      than generic boilerplate that overpromises?

This phase does not require every agent to have chat_agent's full 36-tool breadth — that would be
wrong-sized for a narrow-purpose agent like `env_checker_agent`. The bar is: **the agent's tools are
sufficient to actually and verifiably accomplish what its name and role prompt claim**, matching
Claude Code's actual working pattern (read → act → verify → critique → iterate → report with
evidence) rather than Claude Code's specific tool inventory or its general-assistant conversational
breadth.

**Definition of Done — Phase 4:**
- [ ] Every agent's checklist above is filled in and true, with a citation (test name or file:line)
      proving it, recorded in that agent's own module docstring or a shared tracking table.
- [ ] Full regression suite (§9) still green.

## Phase 5 — Complete LangGraph coverage, generalize HITL, close remaining recovery gaps

**5.1 — Convert `manager.py` to a LangGraph supervisor graph.** Of the two remaining exceptions, this
one is the more straightforward conversion: `run_manager`/`run_epic_manager`'s existing
dispatch-dev→qa→reviewer-with-retry logic maps onto a standard LangGraph supervisor pattern (a
top-level graph whose nodes each invoke a sub-agent's own `run_agent_graph`, with conditional edges
implementing the existing retry/halt logic instead of plain Python `for`/`while` loops). Preserve
every existing behavior exactly (retry counts from `manager_max_subtask_retries`, epic halting from
`manager_max_epic_failures`, the git-commit-before-review fix, checkpointing) — this is a structural
conversion, not a rewrite of what the manager decides, and must not change observable behavior for
any currently-passing test.

**5.2 — Convert `chat_agent.py` to an interrupt-based LangGraph graph.** This is the larger of the two
conversions. This codebase already has a working precedent for LangGraph human-in-the-loop via
`interrupt()` (A.11 — `app/pipeline/graph.py`'s `human_review_node`, tracked via the
`pending_approvals` table — see `PendingApproval`'s own model docstring for the exact pattern: write
the row once, *after* `invoke()` returns and the pause is confirmed, never inside the paused node
itself, since LangGraph re-runs the whole node body on resume). Model the chat session as a graph
where each user message resumes the graph via `interrupt()`/`Command(resume=...)`, tool calls are
graph nodes (reusing the same `state["verification"]` contract every other agent uses — chat_agent
currently has its own separate, undocumented verification approach), and
`session.request_confirmation()` becomes a real `interrupt()` call instead of the current bespoke
`asyncio.Event`-based mechanism. **Do this conversion last, after Phase 1-4 are done and stable** —
chat_agent is the fleet's most capable and most-used agent; converting it first would put the
highest-value, highest-usage code through the most invasive change while the rest of the plan is
still in flux.

**5.3 — Add a real clarifying-question / escalation tool, available to every agent whose task can be
genuinely underspecified** (not universal — a narrow, well-defined agent like `env_checker_agent`
does not need this; agents that interpret open-ended specs do: `pm`, `architect`, `planner`,
`decomposer`, and any Tier-B/C agent working from a loosely-specified task description). Add a
`request_clarification` tool, implemented via the same `PendingApproval`/`interrupt()` pattern as
5.2 — the agent pauses, a human (or an upstream agent, for sub-task delegation) answers, the graph
resumes with the answer injected into context. This directly closes the "silently guesses instead of
asking" gap found during review (confirmed zero agents had any clarification mechanism before this
phase). Do not make this the default path for every ambiguity — an agent that asks a clarifying
question for every minor judgment call is worse than one that makes a reasonable, disclosed
assumption and proceeds; gate it to genuine blockers, wired to the `confidence` field the planner
node already produces (Phase 3.6 already extends this same field for replanning — reuse the one
signal, don't invent a second ambiguity metric) and to Phase 3.7's confidence-threshold quality gate.

**5.4 — Wire `thinking_budget_opus` for real.** Confirmed dead: the config field exists
(`config.py`) but is never passed into any Anthropic API call anywhere in `app/agents/`. For agents
running on the `opus` tier per `agent_models.json` (`architect`, `decomposer`, `planner`,
`executive`, `manager`, `research`, `architecture_reviewer`, `security_architect`,
`rag_engineer_agent`), pass `thinking={"type": "enabled", "budget_tokens": settings.thinking_budget_opus}`
(or the current Anthropic SDK's equivalent parameter name — verify against the installed SDK version
before implementing, parameter names have changed across SDK versions) into the message construction
in `base_graph.py`'s `_make_call_llm_node` for those agents specifically. Do not enable it fleet-wide
by default — extended thinking has a real latency/cost cost, and most of the 72 agents are doing
well-scoped, non-exploratory work where it adds cost without adding value; scope it to the agents
already judged complex enough to warrant Opus.

**5.5 — Generalize the HITL mechanism into one documented framework.** A.11 confirmed the real
`interrupt()`/`PendingApproval` machinery already works for plan-review pauses; 5.2 and 5.3 add two
more real consumers of the same mechanism (chat confirmations, clarification requests). Before adding
a fourth (or letting a future agent invent a fifth, bespoke pause mechanism), formalize this into one
documented API: a single `request_human_input(kind: Literal["approval","clarification","review"],
details, blocking: bool)` entry point that all three (and any future) callers use, all writing to the
same `pending_approvals` table with a `kind` discriminator, all resuming via the same `interrupt()`
pattern, and all logged through the existing `app/fleet/audit_log.py` (A.10 — already real,
append-only) so every human-in-the-loop interaction has a permanent, immutable record of what was
asked, who answered, and when — this is override/audit coverage using infrastructure that already
exists, not a new logging system.

**5.6 — Close the remaining autonomous-recovery gaps.** `app/fleet/failure_ladder.py` and
`fleet_checkpoint.py` (A.15) already provide real retry/rollback/resume/escalate/abort — this is not
a rebuild. Two gaps are genuinely missing and worth closing at this project's real scale (not the
enterprise-distributed version in Appendix D.1):
- **Orphan task recovery**: if a process crashes mid-run, `AgentRun.last_heartbeat_at` (A.9, already
  real) stops updating — but nothing currently *notices* a stale heartbeat and reconciles that run's
  status. Add a lightweight startup/periodic sweep (matching the existing pattern of
  `app/services/retention.py`'s periodic cleanup loop, not a new scheduling mechanism) that finds
  `agent_runs` rows with `status="running"` and a heartbeat older than a configurable threshold, and
  transitions them to `failed` with a clear "orphaned — process died without a clean shutdown" error,
  so the failure ladder's normal retry/escalate path picks them up instead of a task silently hanging
  forever in "running" state.
- **Deadlock detection, scoped to what can actually deadlock here**: given this project's real
  concurrency model is `asyncio.Semaphore`-based (A.13, in-process, not a distributed lock manager),
  the realistic deadlock risk is a bounded one — e.g. an epic holding a subtask slot while waiting on
  another subtask that can never acquire a slot because the epic's own concurrency cap is exhausted.
  Add a timeout to every `agent_run_slot()`/`subtask_slot()` acquisition (`app/pipeline/concurrency.py`)
  with a clear, loud failure (not a silent hang) when a slot can't be acquired within a bounded wait —
  this is the correct, proportionate fix for this project's actual concurrency primitive; a general
  distributed deadlock detector is not needed here (see Appendix D.1 for when it would be).

**Definition of Done — Phase 5:**
- [ ] `manager.py` and `chat_agent.py` both call `run_agent_graph` (or a graph built with the same
      `StateGraph`/`state["verification"]` machinery) — the exception list in §A.1 is empty.
      `grep -c "run_agent_graph(" app/agents/*.py` (or equivalent for chat_agent's graph
      construction) should show every one of the 72 files participating in the shared graph
      architecture.
- [ ] Every existing `manager.py`/`chat_agent.py` test still passes unmodified in behavior (only
      internal implementation changed) — if a test needed to change, the reason is a genuine
      architecture-shape difference (e.g. mocking a graph node instead of a function), not a
      behavior regression.
- [ ] `request_clarification` is real, tested (an agent pauses via a real `interrupt()`, a simulated
      answer resumes it, the answer is demonstrably in the resumed context), and is present on the
      tool list of every agent identified as working from open-ended specs.
- [ ] `thinking_budget_opus` is demonstrably passed into the real Anthropic API call for every
      opus-tier agent — verify with a test that inspects the actual request payload, not just that
      the code path exists.
- [ ] `request_human_input()` is the single entry point for approvals, clarifications, and reviews —
      verified by confirming zero other code paths write to `pending_approvals` directly.
- [ ] Every human-in-the-loop interaction produces a real, queryable `audit_log.py` entry — tested by
      triggering one of each `kind` and confirming an immutable audit record exists for each.
- [ ] A crashed/orphaned run (simulated by stopping heartbeat updates without a clean status
      transition) is detected and reconciled to `failed` within the configured threshold, in a test.
- [ ] A slot-acquisition deadlock scenario (simulated) produces a loud, bounded-time failure, not a
      silent hang, in a test.
- [ ] Full regression suite (§9) still green.

## Phase 6 — Observability & Operational Maturity (new in v2)

This phase closes the remaining, genuinely scoped-to-this-project gaps in A.7-A.10 — it deliberately
does **not** attempt OpenTelemetry-at-enterprise-scale or a general plugin-based observability
backend (Appendix D); it closes the specific, real gaps found by extending what already works.

**6.1 — Bridge `run_span()` to OpenTelemetry-compatible spans, don't replace it.** `app/fleet/metrics.py`'s
`run_span()` (A.7, already real and used at `base_graph.py:1042`) already captures the right
boundaries (per-agent-run timing/status). Add an OTEL `Span` export from within the same context
manager (using the `opentelemetry-sdk`, exporting to whatever backend is configured — default to a
no-op exporter when unconfigured, matching this codebase's established "graceful degradation when a
key/URL isn't set" pattern used throughout, e.g. Sentry's own `ImportError` fallback in A.7). This
gives real distributed trace correlation (request → agent dispatch → individual tool calls, since
tool calls can nest as child spans within the same `run_span`) without discarding the existing,
working metrics collector — `run_span()`'s current consumers keep working unchanged.

**6.2 — Add a reporting surface over data that's already collected.** A.8 and A.9 both confirmed real
cost and health data already exists in the database (`agent_runs.tokens_in/tokens_out/cost_estimate`,
`last_heartbeat_at`, `status`) with no aggregate view over it. Add read-only endpoints (matching this
project's existing API patterns, e.g. `app/api/fleet_dashboard.py`'s existing structure) exposing:
cost per agent/day/model-tier (a `GROUP BY` over already-real columns), fleet health (failure rate,
average heartbeat staleness, active-run count per agent — all derivable from already-real columns),
and — using the newly-real procedural memory from Phase 1.5 — "most commonly recorded repair
patterns," which is itself a small, genuinely useful signal for prioritizing what to fix platform-wide
next. This is a reporting layer over existing data, not a new collection system.

**6.3 — Close the two real security gaps identified in A.10.** Prompt-injection defense: any tool
result that originates from untrusted content (a fetched web page via `research.py`'s real
`web_search`, a file read from a cloned repo the agent doesn't control) must be wrapped with an
explicit, model-visible delimiter marking it as *data, not instructions* in the prompt construction
(`base_graph.py`'s `_make_call_llm_node`) — a well-established, low-cost mitigation, not a novel
research project. Malicious tool-output validation: add a lightweight sanity check on `bash`/`web_search`
output before it's returned to the model — reject or flag output containing patterns that look like an
injected system/assistant-role message (matching the same denylist-pattern-matching approach
`app/policy/engine.py` already uses for commands, applied to tool *output* instead of tool *input*).

**6.4 — Extend the repository knowledge graph with the two narrow structures identified in A.6 as
genuinely missing.** Add a class/inheritance graph (extend `scanner.py`'s existing symbol extraction
— it already knows a symbol's `kind`; add parent-class edges for `kind="class"` symbols using the
same tree-sitter AST it's already walking, not a new parser) and a package/module-level dependency
graph (aggregate the existing file-level `call_edges` up to directory/package granularity — a query
over already-collected data, not new collection). Do not build a class graph via a new, separate
static-analysis pass — extend the existing one.

**Definition of Done — Phase 6:**
- [ ] `run_span()` calls demonstrably produce real OTEL spans (verified against a real, even if
      locally-run, OTEL collector/exporter in a test) with correct parent-child nesting for a tool
      call within an agent run.
- [ ] Cost and health reporting endpoints return real, verifiably-correct aggregates — tested against
      seeded `agent_runs` rows with known values, not mocked aggregation logic.
- [ ] A test confirms untrusted tool output (e.g. a `web_search` result containing text designed to
      look like a system instruction) is delimited as data in the constructed prompt, not concatenated
      as if it were trusted context.
- [ ] A test confirms a `bash` output crafted to mimic an injected instruction is flagged/rejected by
      the new output-validation check.
- [ ] The class graph and package-dependency graph are queryable and demonstrably correct against a
      small, known test repository fixture with real inheritance and cross-package imports.
- [ ] Full regression suite (§9) still green.

---

## 7. Non-negotiable constraints

- **Do not break the existing test suite.** As of the last verified run in this repository's history,
  the full suite passes cleanly against a live database with `mypy --strict` also clean — every phase
  above ends with the same full regression gate (§9); a phase is not done if it regresses this.
- **Do not invent a new registry/config mechanism.** Extend `AgentCapability`
  (`capability_registry.py:22-45`) and `agent_models.json` — both already exist and are already the
  source of truth other code reads from (`manager.py:190-192` and others).
- **Do not bypass `app/policy/engine.py`'s command/path checks** when granting new `bash`/file-write
  capability to previously read-only agents (§2.2) — this project has a documented, mature policy
  layer (A.10); route new capability through it, don't reimplement ad hoc checks.
- **`chat_agent.py` and `manager.py` conversion to LangGraph is scoped to Phase 5 only, and must not
  change either agent's observable behavior** (retry/halt logic, human-confirmation semantics,
  response streaming) — this is a structural conversion (§5.1, §5.2), not a rewrite of what either
  agent decides or how it behaves from a caller's perspective. Do not attempt this conversion as part
  of Phase 1-4 — those phases apply only the memory-system changes to both agents, per §3.3.
- **Do not build a second real implementation of anything that already has exactly one working
  implementation, without first checking Part C** — this document's whole premise is that a
  significant amount of this fleet's real infrastructure already exists and is reasonably good;
  rebuilding it "properly" from scratch is waste, not enhancement.
- **Do not implement anything from Appendix D without first confirming its trigger condition has
  actually fired.** These items are preserved, not deleted, because they may become relevant — but
  building them speculatively, ahead of an actual need, is the same anti-pattern this document
  elsewhere insists on avoiding.
- **Every "fixed" claim must be proven, not asserted.** For every Definition of Done checkbox above,
  the proof is a test that fails before the fix and passes after, or a live-execution
  reproduction-then-confirmation (matching the standard already established in this repository's own
  `docs/reports/AUDIT_04_ORCHESTRATION.md`/`AUDIT_05_SECURITY.md`/`AUDIT_06_INFRASTRUCTURE.md`) — not
  a description of what the code is now supposed to do.

## 8. Suggested sequencing note

Phase 1 (memory & context) unblocks the *value* of every later phase and should be done first, fully,
before starting Phase 2's per-agent tool work — otherwise you'll upgrade 24 agents' tools and still
not have solved the owner's stated goal #5. Phase 2 can be parallelized across agents once Phase 1 is
done and regression-clean (different agents' tool contracts don't depend on each other). Phase 3 and
Phase 4 are checklists that should be applied to each agent as part of its Phase 2 change, not as a
separate sweep afterward — closing an agent's tool gap and never re-touching it to also fix its
verification loop, self-critique participation, and role prompt would leave the job half-done for
that agent.

**Phase 5 comes after Phase 1-4 are stable, and 5.2 (`chat_agent`) comes last within Phase 5.** 5.1
(`manager`), 5.3 (`request_clarification`), 5.4 (extended thinking), 5.5 (HITL generalization), and
5.6 (recovery gaps) can happen any time after Phase 1 is stable, in any order relative to each other.
5.2 should wait until Phase 1-4 are fully done and regression-clean, because it is the highest-risk,
highest-blast-radius change in this entire document — it touches the fleet's most-used and most
capable agent, and the interrupt-based rewrite changes chat_agent's core execution shape, not just
its tool list. Doing it early would put the riskiest change on top of the least-tested version of the
rest of the plan.

**Phase 6 (observability/operational maturity) can run in parallel with Phase 2-4**, since it touches
different files (metrics/reporting/security-hardening layers, not individual agent tool contracts)
and has no dependency on the per-agent tool work being finished first. It does depend on Phase 1.5
(procedural memory) for one specific reporting item (6.2's "most commonly recorded repair patterns")
— sequence that one item after 1.5 specifically, not all of Phase 6 after all of Phase 1.

## 9. Full Regression Gate (run after every phase)

```bash
cd backend
# 1. Full suite against a real, live Postgres (a temporary Docker container matching
#    this project's documented dev credentials is sufficient — see docs/DEPLOYMENT.md
#    and docker-compose.yml for the exact image/credentials this repo already uses).
pytest tests/ -q --timeout=120

# 2. Type check, matching CI's exact command.
mypy app/ --strict --ignore-missing-imports

# 3. Formatting and lint, matching CI.
black --check .
ruff check .

# 4. Supply-chain check, matching CI's scoped ignore list.
pip-audit -r requirements.txt --ignore-vuln GHSA-jfh8-c2jp-5 --ignore-vuln PYSEC-2026-1325
```
All four must be clean before moving to the next phase. If `pytest` fails, distinguish real
regressions from this repository's known, pre-existing, non-blocking Windows-only test-environment
failures (documented in `PENDING_TESTS_API_KEYS.md`) before concluding a phase broke something — but
do not use that document as an excuse to wave away a failure without checking which category it's
actually in.

**New in v2 — testing strategy for new capabilities specifically:** every new capability added in
Phase 1.5-1.7, 3.5-3.7, 5.5-5.6, and all of Phase 6 must have at least one test that would **fail on
the pre-Phase code** (a real regression test, not just a smoke test that happens to pass because the
feature under test doesn't do much yet). For anything touching the memory system (Phase 1), the test
must exercise a real database, not a mock — mocking the exact system whose cross-process/cross-restart
persistence is the entire point of Phase 1 would validate nothing real.

---

# PART C — Verified Existing Systems (Reference — do not rebuild these)

This section exists so an implementer starting work on this document doesn't waste time re-verifying
or, worse, re-architecting something that already works. Every row below has a Part A citation with
the full evidence; this table is a navigation aid, not a separate source of truth.

| System | Status | Where | Detail |
|---|---|---|---|
| Repository knowledge graph (symbol table, function-level call graph, PageRank ranking) | Real, substantial | A.6 | `scanner.py`, `cross_file_graph.py`, `context_builder.py`, `architecture_mapper.py` + `indexed_files`/`symbols`/`call_edges` tables |
| Error tracking (Sentry) | Real | A.7 | `main.py:45-79`, real `sentry_sdk.init()` |
| Cost enforcement (per-run, daily, epic estimation) | Real | A.8 | `budget_manager.py`, `cost_controller.py`, real `AgentRun` cost columns |
| Health/liveness (heartbeat) | Real | A.9 | `AgentRun.last_heartbeat_at` + `heartbeat_agent_run()` |
| Security policy engine (command/path denylist, sandbox boundary) | Real, mature | A.10 | `app/policy/engine.py`, battle-tested with a documented bug-fix history |
| Credential encryption | Real | A.10 | `app/security/credential_vault.py`, Fernet + `SecretStr` |
| Audit logging | Real | A.10 | `app/fleet/audit_log.py`, append-only, dual-write |
| Human-in-the-loop pause/resume | Real | A.11 | `approval_gate.py` + `pipeline/graph.py`'s real `interrupt()` usage |
| Git operations (status/diff/log/branch/checkout/pull/blame) | Real | A.12 | `app/services/git_service.py`, `app/agents/tools.py` (blame) |
| Worktree management (create/verify/recover/remove) | Real | A.12 | `app/repo_tools/worktree.py` |
| Rate limiting | Real | A.13 | slowapi, wired in `main.py` |
| Concurrency caps | Real | A.13 | `app/pipeline/concurrency.py`, semaphore-based |
| Dynamic agent discovery | Real | A.14 | `capability_registry.py`'s `ensure_all_agents_registered()` |
| Queue backend adapter pattern | Real (one real alt. impl.) | A.14 | `app/pipeline/queue_adapter.py` |
| Declarative memory (task outcomes, learning signals) | Real, but under-wired | A.4 | `app/memory/store.py` — see Phase 1 for wiring gaps |
| Versioned lesson lifecycle (DRAFT→PUBLISHED, novel merge algorithm) | Real, but disconnected | A.4 | `app/fleet/versioned_memory.py` — see Phase 1.2 |
| Failure recovery ladder (retry/rollback/escalate/abort) | Real | A.15 | `app/fleet/failure_ladder.py` |
| Self-correction retry loop (static-check-then-retry) | Real, Tier-A only today | A.2 | `coder.py:83-203` |
| Reflection-on-tool-use | Real, basic | A.15/Phase 3.5 | `base_graph.py` reflection_node — Phase 3.5 extends this |
| Planning with confidence scoring | Real, basic | Phase 3.6 | `base_graph.py` planner_node — Phase 3.6/5.3 extend this |
| Context token-budget trimming | Real | Phase 1.6 | `base_graph.py`'s "Context trim" — Phase 1.6 adds hierarchical summarization on top |
| Web search | Real, working | A.2 | `RESEARCH_TOOLS`, backed by real `duckduckgo_search.DDGS` |

---

# Appendix D — Future Considerations, Not Required For This Project's Current Scale

Every item below was explicitly requested. None are deleted. Each is preserved in full, with the
concrete condition under which it would become worth building — do not build any of these ahead of
its trigger firing; doing so is speculative infrastructure with no current user, which this document
elsewhere explicitly identifies as an anti-pattern to avoid.

## D.1 Enterprise horizontal scaling (distributed workers, sharding, distributed memory, distributed checkpoints)

**What was requested:** design for thousands of concurrent tasks, distributed workers, horizontal
scaling, sharding, queue prioritization, load balancing, distributed memory, distributed checkpoints.

**Why it's deferred:** this project's real, current deployment shape is a single Postgres instance
with in-process `asyncio.Semaphore` concurrency caps (A.13) and an optional-but-not-live Redis queue
adapter (A.14 — `RQAdapterBridge` is real but not wired into actual task dispatch, per its own
documented caveat). There is no current evidence of multi-worker-process deployment, let alone a
distributed cluster. Building sharded distributed memory/checkpointing now means designing against
zero real operational data about where the actual bottlenecks would be.

**Trigger condition:** this becomes worth building when the application genuinely runs more than one
worker process/replica in production (at which point `LessonStore`'s in-process-only limitation,
already flagged as a problem in A.4/Phase 1 for a *single*-process restart, becomes a much bigger
problem across replicas) — or when real usage data shows the single-instance concurrency caps in
`concurrency.py` are the actual throughput bottleneck, not a hypothetical one.

## D.2 Full multi-agent negotiation/voting/arbitration/consensus protocol

**What was requested:** negotiation, structured discussions, disagreement resolution, voting,
arbitration, consensus, confidence scoring, escalation, specialist consultation, recursive
delegation, collaborative planning — "the manager should become a true supervisor."

**Why it's deferred, partially:** confidence scoring (already real, A.15/Phase 3.6), escalation
(already real, `failure_ladder.py`), and specialist consultation/recursive delegation (achievable via
`manager.py`'s existing dispatch pattern once it's a real LangGraph supervisor per Phase 5.1 — a
supervisor graph node can already invoke another agent's sub-graph) are **not deferred** — they're
covered by Phase 1/3/5 at the scope this fleet actually needs. What's genuinely deferred is formal
voting/arbitration/consensus between multiple agents independently producing *conflicting*
recommendations on the same decision — there is no evidence this fleet's current task shape (mostly
sequential dev→qa→review pipelines, not parallel independent proposals needing reconciliation)
produces this scenario often enough to justify a formal protocol for it.

**Trigger condition:** this becomes worth building when you have a real, recurring case of two or
more agents independently producing genuinely conflicting recommendations on the same decision
(not just "agent A found a bug agent B didn't look for" — that's normal division of labor, not
conflict) — at that point, design the arbitration mechanism against real examples of what the
agents actually disagreed about, not a hypothetical.

## D.3 Dynamic tool selection (reliability/cost/latency/confidence scoring across redundant tool providers)

**What was requested:** agents should evaluate tools using reliability, historical success, latency,
cost, confidence, and permissions before selecting one, with automatic fallback tools.

**Why it's deferred:** this pattern is valuable when a capability has multiple *interchangeable*
implementations (e.g., three different web-search providers, two different LLM providers for the
same task). Verified directly: this fleet's tools are each a distinct capability
(`edit_file`/`bash`/`run_tests` are not redundant with each other), and the one place a genuinely
redundant/interchangeable-provider situation exists today (`QueueAdapter`'s `asyncio` vs. `rq`
backends, A.14) is already a static config choice (`QUEUE_BACKEND`), not something that benefits from
per-call dynamic scoring. Building a general dynamic-selection framework now means designing it
against zero real redundant-provider pairs.

**Trigger condition:** this becomes worth building the first time this fleet has two or more real,
interchangeable implementations of the same capability (e.g., a second web-search provider added
alongside `duckduckgo_search`, or a second LLM provider genuinely load-balanced rather than used only
as an availability fallback) — design the selection logic against that real pair, not speculatively.

## D.4 Full plugin architecture across 6 categories (agent, tool, memory, model, retrieval, observability plugins)

**What was requested:** allow future capabilities through plugins across all six categories without
changing core architecture.

**Why it's deferred:** A.14 confirmed a real, working adapter pattern already exists for exactly the
one category that currently has more than one real implementation (queue backend). Every other
category (memory backend, model provider, retrieval backend, observability backend) has exactly one
real implementation in this codebase today. Designing a general plugin interface against a sample
size of one per category is how you get the wrong abstraction — you can't know what varies across
implementations until you have at least two.

**Trigger condition:** generalize a given category's adapter pattern the first time a second real
implementation of that specific category actually exists — e.g., generalize a "model provider
plugin" interface when this fleet gets a second real, live model provider beyond
Anthropic/Groq-as-fallback (A.2/A.7's existing `groq_adapter.py` is arguably already a first data
point for this specific category and is the closest of the four to being worth generalizing — revisit
this one first if/when a third provider appears).

---

**End of MASTER_AGENT_v2.md.** This document supersedes v1 in scope but not in any of v1's original
findings — every citation from v1 is preserved above, either unchanged (Part A.1-A.5, Phase 1-5 core
content) or extended with new, equally evidence-based material (Part A.6-A.15, Phase 1.5-1.7,
3.5-3.7, 5.5-5.6, Phase 6, Part C, Appendix D). Nothing requested was silently dropped; the hyperscale
items are in Appendix D specifically so they remain one search away, not deleted, the next time this
project's actual scale changes enough to warrant them.
