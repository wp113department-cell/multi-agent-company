# MASTER_AGENT.md — Fleet-Wide Agent Upgrade Specification

**Purpose:** this document is a complete, evidence-based engineering specification for upgrading
every agent in this repository's fleet (`backend/app/agents/*.py`, currently 72 agents) to a single,
consistent, production-grade standard. It is written to be handed directly to an LLM coding agent
(Claude Code, Cursor, or equivalent) with the instruction: **"Implement this file."** Every claim
about the current codebase below is backed by a file:line citation, verified by direct inspection —
not assumed. Every requirement is phrased so its completion is checkable.

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

This section exists because two of the five goals above bundle together things that are achievable
and one thing that is not achievable in the form usually implied, and pretending otherwise would make
this document dishonest. Read this before starting Phase 2 or Phase 4.

**Achievable, and this document gets you there if fully implemented:** every agent verifiably does
its actual job — real tools, real verification against real tool output (not model narration), real
shared memory, real iterative self-correction bounded by retries. This is what "production-grade" and
"Claude Code's *working pattern*" concretely mean, and it is a fair, checkable bar.

**Not achievable, and not actually the right target: making all 72 agents individually equivalent to
Claude Code / ChatGPT / Claude.ai / Cursor as general-purpose, live, multi-turn conversational
assistants.** That requires open-ended dialogue with a human, the ability to ask clarifying questions
mid-task, arbitrary tool composition, and a very large, continuously-adapting context — this is a
*different interaction shape*, not a missing feature you bolt onto a narrow single-shot task worker.
No serious production multi-agent system (this project's own `chat_agent` + fleet split, Devin,
Cursor's background agents, or Anthropic's own internal agent tooling) gives every narrow worker
agent that shape — they all use the same pattern this project already has: **one capable
conversational entry point, plus many narrow, verifiably-reliable task workers behind it.**
`env_checker_agent` does not need the ability to hold a 40-turn ambiguity-resolving conversation; it
needs to reliably check an environment and report the truth about what it found.

**The corrected, honest target for goals 3 and 4:** every agent matches Claude Code's *working
pattern* (read → act → verify against real output → iterate within bounded retries → report with
evidence, and — new in this revision — **ask for clarification when a task is genuinely
underspecified, instead of silently guessing**) at a scope appropriate to its job. `chat_agent`
remains the one agent with full open-ended conversational depth, matching how this project already
treats it as the primary interactive surface. Phase 5 below adds the one piece of this that was
missing from the first draft: a real, structured way for *any* agent (not just chat_agent) to escalate
genuine ambiguity instead of being forced to guess.

If your actual requirement is "every one of the 72 agents must be able to hold an open-ended
conversation like ChatGPT," that is a different project — it means giving all 72 agents chat_agent's
interaction shape, which would also mean most of them no longer run unattended/dispatched, since a
conversational agent needs a human on the other end of the conversation. Flag this explicitly if it's
genuinely what you want, and it can be scoped separately; it is not what the rest of this document
implements.

---

## 0. How to use this document

Work through Part B in the phase order given. Each phase has a **Definition of Done** — do not mark
a phase complete until every item in its DoD is independently verified (run the test, read the
output, don't assume). After each phase, run the **Full Regression Gate** in §8 before starting the
next phase. Do not skip phases or reorder them — later phases assume earlier ones are actually done,
not just attempted.

If anything in Part A ("Current State") appears to have changed since this document was written,
re-verify it against the live source before trusting the plan built on top of it — this document is
a snapshot, not a live oracle.

---

# PART A — Current State (verified, not assumed)

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
  pattern for approvals elsewhere), which is the real conversion target; see §5.2.
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
(`tools.py:508`), `RESEARCH_TOOLS` (`tools.py:1136`), `DOCS_TOOLS` (`tools.py:1245`). `coder.py:83-96`
runs `mypy`+`ruff` *outside* the LLM loop and retries the whole graph run on failure
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
  falling back to the pre-run cost *estimate* as the reported "actual" cost.
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
isolated.** Verified directly: there is no code path anywhere that takes a `PUBLISHED`
`versioned_lessons` row and injects it into `LessonStore` (the only thing actually read before an
LLM call). Lessons curated and published through this system's real, careful lifecycle machinery are
written to the database and then never read by any running agent again.

**Net effect, stated plainly:** the owner's CI/CD-agent-should-know-what-debugger-agent-learned
scenario **does not work today**, for three independent reasons: (1) most non-manager-driven agents
never write any outcome memory at all; (2) the one memory store that IS read before every LLM call
is in-process, ephemeral, and keyword-only; (3) the one memory store built with real semantic search
and a real lifecycle is disconnected from live inference entirely.

## A.5 Wiring points to build on (do not reinvent these)

- **`AgentCapability`** dataclass (`app/fleet/capability_registry.py:22-45`): `name`, `description`,
  `tools`, `input_types`, `output_types`, `capabilities`, `limits`, `dependencies`,
  `requires_worktree`, `requires_db`, `risk_level`. This is the existing "per-agent contract" schema
  — extend it, don't replace it.
- **`ensure_all_agents_registered()`** (`capability_registry.py:122-…`): scans `app/agents/` at
  runtime (not a hardcoded name list) and imports every module so its `_register()` hook fires — new
  agents are picked up automatically. Any new per-agent metadata this plan adds should flow through
  this same `_register()` pattern.
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

---

# PART B — Implementation Plan

Work these phases in order. Each phase is independently regression-tested (§8) before moving on.

## Phase 1 — Fix the memory architecture first (everything else depends on this)

This is Phase 1, not Phase 5, deliberately: every later phase produces agents whose whole value
proposition is "benefits from and contributes to shared fleet knowledge" (goal #5). Building 57 more
tool-upgraded agents on top of a memory system that doesn't actually share anything would just widen
the gap the owner is actually pointing at.

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
gate is valuable and shouldn't be thrown away, it just needs to feed the live path.

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
- [ ] Full regression suite (§8) still green.

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
`check_allowlisted_command`) established across the rest of this codebase — do not bypass them.

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
- [ ] Full regression suite (§8) still green.

## Phase 3 — Production-grade verification for every agent

**3.1 — Every agent must set `state["verification"]` flags from real tool output, not model claims**
— this pattern already exists in `base_graph.py` (§A per its own docstring: "the model's claims...
are OVERRIDDEN by this dict"); the work here is ensuring every *newly capable* Executor/Editor-tier
agent from Phase 2 actually participates in it (mutating tools invalidate `tests_passed`;
verification tools set flags only on a real, error-free completion — do not let a new agent's
`submit_*` handler accept an unverified boolean claim).

**3.2 — Fix `manager.py`'s fake cost placeholder** (`manager.py:775-782`). Replace the placeholder
sum with a real aggregation over `agent_runs.tokens_in`/`tokens_out`/`cost_estimate` for the epic's
actual runs, matching the pattern `AgentRun`'s cost fields already support (see
`docs/reports/AUDIT_06_INFRASTRUCTURE.md` for the ORM/DB timezone fixes made to this same table
family earlier — build on that verified-clean schema, don't reintroduce drift).

**3.3 — Do not touch `chat_agent.py`'s or `manager.py`'s core shape in this phase** (§A.1) — their
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

**Definition of Done — Phase 3:**
- [ ] Every Executor/Editor-tier agent from Phase 2 has at least one test proving its verification
      flags are driven by real tool output, not model narration.
- [ ] `manager.py`'s epic cost reporting is real, tested against actual `agent_runs` aggregation.
- [ ] Full regression suite (§8) still green.

## Phase 4 — "Near Claude Code" capability baseline, applied fleet-wide

This phase is a checklist applied to every agent, cutting across the tiers above — it's the
concrete, checkable definition of goal #4 ("all types of functionality Claude Code has").

For every agent, confirm and fix as needed:
- [ ] **Can it read broadly** (not just the one file it's told about)? — `search_code`,
      `get_file_tree`, `find_references` from `READ_ONLY_TOOLS` should be available to all 72; this
      is already mostly true (§A.2) — verify no agent lost this in the Phase 2 rework.
- [ ] **Can it verify its own output** appropriate to its role (run the test it wrote; lint the code
      it edited; validate the config it generated)? — this is Phase 2/3's core deliverable.
- [ ] **Can it iterate on failure**, not just report it? — Tier-A's `coder.py:128-203` retry-until-
      static-checks-pass pattern is the reference implementation; every Executor-tier agent from
      Phase 2 should have an equivalent bounded retry loop (respecting `max_retries`/
      `manager_max_subtask_retries` config, not unbounded).
- [ ] **Does it benefit from and contribute to fleet memory** (Phase 1)? — every agent, not only the
      Tier-A ones.
- [ ] **Is its role prompt specific and honest** about what it can and cannot do (Phase 2.4), rather
      than generic boilerplate that overpromises?

This phase does not require every agent to have chat_agent's full 36-tool breadth — that would be
wrong-sized for a narrow-purpose agent like `env_checker_agent`. The bar is: **the agent's tools are
sufficient to actually and verifiably accomplish what its name and role prompt claim**, matching
Claude Code's actual working pattern (read → act → verify → iterate → report with evidence) rather
than Claude Code's specific tool inventory.

**Definition of Done — Phase 4:**
- [ ] Every agent's checklist above is filled in and true, with a citation (test name or file:line)
      proving it, recorded in that agent's own module docstring or a shared tracking table.
- [ ] Full regression suite (§8) still green.

## Phase 5 — Close the two remaining, genuinely addable gaps (added after owner review)

This phase exists because the owner explicitly requires literal 72/72 LangGraph coverage, and because
two real, concrete gaps were found that Phase 1-4 didn't cover: no agent can ask for clarification,
and extended thinking is configured but never actually used.

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
`interrupt()` (`app/pipeline/graph.py`'s `human_review_node`, tracked via the `pending_approvals`
table — see `PendingApproval`'s own model docstring for the exact pattern: write the row once,
*after* `invoke()` returns and the pause is confirmed, never inside the paused node itself, since
LangGraph re-runs the whole node body on resume). Model the chat session as a graph where each
user message resumes the graph via `interrupt()`/`Command(resume=...)`, tool calls are graph nodes
(reusing the same `state["verification"]` contract every other agent uses — chat_agent currently has
its own separate, undocumented verification approach), and `session.request_confirmation()` becomes a
real `interrupt()` call instead of the current bespoke `asyncio.Event`-based mechanism. **Do this
conversion last, after Phase 1-4 are done and stable** — chat_agent is the fleet's most capable and
most-used agent; converting it first would put the highest-value, highest-usage code through the most
invasive change while the rest of the plan is still in flux.

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
assumption and proceeds; gate it to genuine blockers (e.g. `pm`/`architect`-tier agents already have a
`confidence` field from the planner node, per `base_graph.py`'s planner_node — wire low confidence to
this tool rather than inventing a new ambiguity signal).

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
- [ ] Full regression suite (§8) still green.

---

## 6. Non-negotiable constraints

- **Do not break the existing test suite.** As of the last verified run in this repository's history,
  the full suite passes cleanly against a live database with `mypy --strict` also clean — every phase
  above ends with the same full regression gate (§8); a phase is not done if it regresses this.
- **Do not invent a new registry/config mechanism.** Extend `AgentCapability`
  (`capability_registry.py:22-45`) and `agent_models.json` — both already exist and are already the
  source of truth other code reads from (`manager.py:190-192` and others).
- **Do not bypass `app/policy/engine.py`'s command/path checks** when granting new `bash`/file-write
  capability to previously read-only agents (§2.2) — this project has a documented, tested policy
  layer; route new capability through it, don't reimplement ad hoc checks.
- **`chat_agent.py` and `manager.py` conversion to LangGraph is scoped to Phase 5 only, and must not
  change either agent's observable behavior** (retry/halt logic, human-confirmation semantics,
  response streaming) — this is a structural conversion (§5.1, §5.2), not a rewrite of what either
  agent decides or how it behaves from a caller's perspective. Do not attempt this conversion as part
  of Phase 1-4 — those phases apply only the memory-system changes to both agents, per §3.3.
- **Every "fixed" claim must be proven, not asserted.** For every Definition of Done checkbox above,
  the proof is a test that fails before the fix and passes after, or a live-execution
  reproduction-then-confirmation (matching the standard already established in this repository's own
  `docs/reports/AUDIT_04_ORCHESTRATION.md`/`AUDIT_05_SECURITY.md`/`AUDIT_06_INFRASTRUCTURE.md`) — not
  a description of what the code is now supposed to do.

## 7. Suggested sequencing note

Phase 1 (memory) unblocks the *value* of every later phase and should be done first, fully, before
starting Phase 2's per-agent tool work — otherwise you'll upgrade 24 agents' tools and still not have
solved the owner's stated goal #5. Phase 2 can be parallelized across agents once Phase 1 is done and
regression-clean (different agents' tool contracts don't depend on each other). Phase 3 and Phase 4
are checklists that should be applied to each agent as part of its Phase 2 change, not as a separate
sweep afterward — closing an agent's tool gap and never re-touching it to also fix its verification
loop and role prompt would leave the job half-done for that agent.

**Phase 5 comes last, deliberately, and 5.2 (`chat_agent`) comes last within Phase 5.** 5.1
(`manager`), 5.3 (`request_clarification`), and 5.4 (extended thinking) can happen any time after
Phase 1 is stable, in any order relative to each other. 5.2 should wait until Phase 1-4 are fully done
and regression-clean, because it is the highest-risk, highest-blast-radius change in this entire
document — it touches the fleet's most-used and most capable agent, and the interrupt-based rewrite
changes chat_agent's core execution shape, not just its tool list. Doing it early would put the
riskiest change on top of the least-tested version of the rest of the plan.

## 8. Full Regression Gate (run after every phase)

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
