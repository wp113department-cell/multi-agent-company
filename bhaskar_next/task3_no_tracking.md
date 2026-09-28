# Task 3 — the 14 "NO" items, implemented one by one

Started 2026-09-25, after Task 2 (all 70 PARTIAL items) closed out. User's
own instruction: industry-grade, production-use implementation, easiest/
smallest items first, biggest/hardest last.

Verdicts: `PENDING` · `DONE` · `SKIPPED`

## Scope note — #169/#171/#494 fully skipped, not just deferred

#169 (distributed registries), #171 (horizontal scaling), and #494
(distributed AgentRegistry dispatch coordination) are the same underlying
distributed-systems problem (multi-instance backend coordination) at
different points in the original 519-item audit. User confirmed
(2026-09-25) all three are **fully skipped from this plan** — not "do
last", not "revisit later automatically" — genuinely out of scope unless
the user brings them back explicitly (e.g. once this actually runs more
than one backend instance). #169 was already tracked this way in
`enhance_partial_tracking.md`; #171/#494 are recorded here the same way
and removed from the ordered plan below.

## Ordered plan (12 real items, easiest → hardest)

| Order | Item(s) | Status |
|---|---|---|
| 1 | #500 Conversational "do that again" | DONE |
| 2 | #44 Agents create subtasks dynamically | DONE (real gap fixed; flag stays off pending user decision) |
| 3 | #454 Dependency checks as mandatory gate | DONE |
| 4 | #457 Documentation checks as mandatory gate | DONE |
| 5 | #297 Auto documentation lookup while coding | DONE |
| 6 | #58 Agent selection uses memory/past outcomes | DONE |
| 7 | #405 Company Brain (org knowledge for prompts/tools) | DONE |
| 8 | #66 Switch tools mid-run | DONE |
| 9 | #443 Detect hallucinating/leaking/desynced agents | DONE (scoped — see write-up) |
| 10 | #45 + #67 Agent-to-agent delegation | DONE (already built, no code needed) |
| 11 | #227 Human takeover / step-level plan editing | DONE (scoped — see write-up) |
| — | #169 + #171 + #494 Distributed registry / horizontal scaling | SKIPPED (user decision, all three) |

## #500 — Conversational "do that again" — DONE (2026-09-25)

Reused the existing deterministic task-repeat mechanism
(`POST /api/tasks/{id}/repeat` → `repeat_task()`) rather than building a
second one. Extracted the real orchestration (`repeat_task()` + transition
+ log + dispatch) out of the HTTP route into a new shared function
`repeat_and_dispatch_task()` (`app/api/tasks.py`) so both the HTTP route
and the new chat tool call the exact same real path — not two
independently-maintained copies. The chat tool has no real
`BackgroundTasks` in scope (no HTTP request), so it uses
`app.main._FireAndForgetBackgroundTasks` — the same shim #429's own
periodic dependency-auto-dispatch loop already built for this identical
problem, not a new one.

Two new chat tools (`app/agents/tools.py`, dispatched in
`app/agents/chat_agent.py`):
- `find_repeatable_tasks` — real candidates from `dev_tasks`, scoped to
  the chat session's own `repo_id`. Never resolves ambiguity itself: when
  more than one candidate matches, its own returned text explicitly
  instructs the model to call `ask_human_to_choose` before repeating
  anything — "never silently guess" enforced by the tool's own output,
  not left to prompt-level judgement alone.
- `repeat_previous_task` — requires a specific `task_id` (no "just repeat
  the most recent one" shortcut exists), so by construction the model
  must have already resolved which task it means — either unambiguously
  from `find_repeatable_tasks`, or via a real `ask_human_to_choose` pause
  — before this tool can be called at all. Supports `description_override`
  for "repeat it but change X" requests.

`roles/chat.md` updated with the expected usage pattern.

Tests: `tests/test_chat_repeat_task.py` (9 tests, real Postgres — real
Repo/DevTask rows, no mocked DB) — unambiguous match, ambiguous match,
zero matches, cross-repo isolation (a task in a different repo never
shows up as a candidate), real clone+dispatch, description override,
missing/invalid task_id errors, and one full graph-level test proving the
LLM-driven ambiguous flow end-to-end with a fake Anthropic stream (same
pattern as `test_phase52_chat_graph_interrupt.py`) — confirms the graph
genuinely pauses at a real `interrupt()` before repeating anything, and
only repeats after the human's choice resolves it.

Regression: 30/30 on the direct test set, 850/850 on a broader
chat_agent/repeat_task/task sweep. Full backend suite pending re-run
after a mid-session power outage interrupted the previous one (Docker/
Postgres/Redis recovered automatically once Docker Desktop was
restarted).

## #44 — Agents create subtasks dynamically — DONE (2026-09-25)

**Real finding before writing anything**: this item was already
extensively built by an EARLIER, separate initiative
("plan14 follow-on #2", predating this Task 1/Task 2/Task 3 thread) —
`app/pipeline/dynamic_subtasks.py` (validation: allow-matrix, depth cap,
count cap, duplicate-title/files rejection; real file-lock reservation
via the existing `reserve_epic_files()`; wave-boundary integration into
`run_manager()`'s own dispatch loop, refilling the wave queue so new work
is discovered without restarting the epic), `app/tools/agents/
propose_subtask.py` (the real tool), and 30 existing tests
(`tests/test_dynamic_subtask_creation.py`). Sitting behind
`Settings.dynamic_subtask_creation_enabled_agents` — empty by default,
same "built but zero consumers" shape as #12 before today.

This matches the audit's own rule: "if the current source shows that an
old gap has already been fixed, do not recreate it. Verify it and move to
the remaining gap." Verifying now, not rebuilding from scratch.

**Real gap confirmed by direct reading (`app/agents/manager.py:913`)**: a
dynamically-integrated subtask NEVER gets a real `Subtask` DB row created
for it — `_dispatch_one_subtask`'s own status-persistence line
(`if db is not None and subtask_idx < len(db_subtask_rows):`) is
unconditionally False for any index beyond the original static count.
Concretely: a dynamically-proposed subtask is invisible to
`GET /api/tasks/{id}/subtasks`, and a crash mid-epic after it was
integrated (or even mid-dispatch) leaves zero DB trace it ever existed —
the "persist enough state for crash/recovery" requirement from the
original audit item is not met. This is the one real gap to fix; the
"respect existing token/cost budget" requirement is judged satisfied by
the existing `dynamic_subtask_max_per_epic`/`dynamic_subtask_max_depth`
caps — there is no other epic-level $ budget mechanism anywhere in this
codebase to plug into, and building one from scratch is out of scope for
this specific item.

**Fix applied**: `app/db/repository.py::add_subtask()` (new) — single-row
counterpart to the existing bulk `save_subtasks()`, same field mapping,
same 0-based-index `depends_on` convention (confirmed not a real foreign
key despite the `ARRAY(BigInteger)` column type — `save_subtasks()`
already passes indices straight through with no translation).
`app/pipeline/dynamic_subtasks.py::integrate_proposals()` gained optional
`task_id`/`db_subtask_rows` params — when given, a real `Subtask` row is
created for every integrated proposal, attempted BEFORE the in-memory
`subtasks.append()` (not after): if persistence fails, the WHOLE proposal
is rejected rather than partially degraded, because `db_subtask_rows` must
stay in exact position-lockstep with `subtasks` — that positional
correlation is the ONLY link `_dispatch_one_subtask`'s own status-
persistence check has (the decomposer's transient "id" field is not the
real DB primary key). `app/agents/manager.py`'s one real call site now
passes both. Backward compatible: both params default `None`, and a third
new test proves every pre-existing caller that omits them gets the exact
original in-memory-only behavior, unchanged.

Tests: 3 new in `tests/test_dynamic_subtask_creation.py` (persists a real
row + position lockstep verified against real Postgres; rejects cleanly
and keeps lockstep on a simulated persistence failure; zero-behavior-
change proof for callers without task_id) — all 38 tests in that file
pass (35 pre-existing + 3 new), zero regressions. Full backend suite:
8668 passed, 6 failed — 5 match the exact known pre-existing baseline,
1 (`test_gap54_phase_timing.py`) reproduced passing standalone (confirmed
order/resource-dependent flake, unrelated to this change).

**Deliberately left for the user to decide, not flipped unilaterally**:
`dynamic_subtask_creation_enabled_agents` stays empty (off) by default.
Turning it on for `backend_dev`/`frontend_dev` (already policy-configured
in `dynamic_subtask_allowed_matrix` and tool-wired — literally one config
change away) would let real autonomous agents spawn genuinely new work
mid-epic without a human approving it first — a real increase in agent
autonomy and cost exposure, not a pure UX/streaming toggle like #12's own
flag flip. The audit's own original characterization of this item
("highest-risk item in the backlog... genuine risk of destabilizing an
existing, working invariant if rushed") plus its own recommended rollout
("enabled only for specific epics/agents initially") both argue for
asking rather than deciding this one alone.

## #454 — Dependency checks as a mandatory pipeline gate — DONE (2026-09-25)

**Real finding before writing anything (third surprise in a row)**: this
was ALSO already substantially built. `dependency_security_agent` already
runs as a real, mandatory, blocking gate — `Settings.
enable_security_architecture_gates` defaults **True** (flipped during
Task 2's T2-B5/#453/#455), running security_reviewer/architecture_reviewer/
dependency_security_agent concurrently after every subtask, with
`security_architecture_gates_block_severities` defaulting to
`["critical", "high"]` (non-empty — genuinely mandatory-by-default, not
opt-in-and-inert).

**Real gap confirmed by direct reading**: `_gate_block_reason`'s own
"dependency" branch only ever checked `vulnerable_package_count` (a real,
deterministic, independently-re-run pip-audit count — never the model's
narrative). `check_target_repo_license_compliance` (#331) was already one
of this agent's `allowed_tools`, but nothing in its own role file, its
gate-invocation prompt, or the blocking logic ever actually required or
acted on a license check — a real license-policy violation had **no path
into the mandatory gate's blocking decision at all**, despite the
underlying capability already existing.

**Fix applied**, same rigor as the existing vulnerability check (never
trust the model's narrative for a blocking decision):
- `app/agents/dependency_security_agent.py`: `run_dependency_security_agent()`
  independently re-scans `requirements.txt` via the real
  `scan_target_repo_dependency_licenses()` (real PyPI metadata) whenever
  the run is graph-verified, exposing a real, deterministic
  `license_disallowed_count` on `AgentResult.raw` — same "graph's own
  recorded truth wins over the model's claim" pattern #462 already
  established for abandoned-package detection, applied here to a
  different field.
- `app/agents/manager.py::_gate_block_reason`: the "dependency" branch now
  also blocks on `license_disallowed_count > 0`.
- `roles/dependency_security_agent.md` and the gate's own invocation
  prompt updated to document license checking as a real, expected part of
  this role (documentation only — the actual enforcement is code-driven,
  independent of whether the model remembers to call the tool).

**Deliberate scope boundary, not a gap left open**: #462 (abandoned/
unmaintained packages) and #463 (real dependency-conflict solver) live on
a DIFFERENT, separate agent (`dependency_agent`, not
`dependency_security_agent`) with their own tools
(`check_last_release`/`check_dependency_conflicts`). Bringing those into
this SAME hot-path mandatory gate would mean a genuinely new, additional
LLM agent call on every subtask (real added cost/latency), not a cheap
prompt extension to an agent already being called — the same class of
cost/behavior-increasing decision as #44's autonomy-flag question.
Deliberately left OUT of the mandatory gate for now (available on-demand
via `dependency_agent` as before) rather than silently expanding gate
cost without a decision; #454's own core ask — "dependency checks
mandatory, not merely available" — is satisfied by vulnerabilities +
license both now genuinely blocking by default.

Tests: 3 new in `tests/test_batch16_quality_gates.py` (blocks on a real
`license_disallowed_count`, doesn't block when unverified, doesn't block
when zero — mirrors the pre-existing vulnerability tests exactly) + 3 new
in `tests/test_dependency_gate_license_check.py` (real end-to-end through
`run_dependency_security_agent()` itself — mocked PyPI fetch only, per
the sibling `test_t2b10_target_repo_license_compliance.py`'s own
established caution against a live "this package is GPL" fixture that
could drift; real pip-audit side of the same code path short-circuited
since it's irrelevant to this specific fix). 44/44 across the direct +
broader regression set (2 known pre-existing baseline failures excluded —
same CVE-count-drift issue confirmed unrelated all day), 341/342 on a
broader dependency/gate/manager sweep. Full backend suite: 8678 passed, 5
failed — all 5 match the exact known pre-existing baseline
(`test_docker_ps_hardening.py` ×3, `test_stage4_cluster_q_security_score.py`
×2), zero new regressions. Committed `96729da2`.

## #457 — Documentation checks as a mandatory pipeline gate — DONE (2026-09-25)

Per the audit's own IMPLEMENTATION PLAN, deliberately did **not** reuse
`docs.py` (the existing epic-level, LLM-driven README/changelog writer) —
too slow/expensive to run per subtask, and not what "pre-completion gate"
means anyway. Built the scoped-diff check the plan explicitly asked for
instead: a fifth, free (no LLM call) gate alongside security/architecture/
dependency/performance in `manager.py::_run_advisory_quality_gates`.

- `app/repo_tools/doc_coverage.py` (new): `check_subtask_doc_coverage()` —
  pure-AST scan (stdlib `ast`, same convention as `code_hygiene.py`/
  `reliability_review.py`) of ONLY the subtask's own changed `.py` files
  (`files_changed`, already computed by the dev-agent dispatch call
  immediately above the gate call site — no new data needed), flagging
  top-level PUBLIC (non-underscore) functions/classes with no docstring.
  Nested/local functions are deliberately out of scope (same documented
  boundary `reliability_review.py` already accepts for its own nested-call
  limitation) — proven by a dedicated test
  (`test_nested_function_is_not_flagged`).
- `app/agents/manager.py`: `_run_advisory_quality_gates` gained
  `worktree_path`/`files_changed` params, threaded through from the one
  real call site inside `_dispatch_one_subtask` (both already in scope
  there). New `_run_documentation()` gate runs concurrently with the other
  four; handled with its own shape (`DocCoverageReport`, not `AgentResult`)
  the same way `regression_gate` already is, not forced into the generic
  security/architecture/dependency loop. Inert when `worktree_path`/
  `files_changed` aren't passed — same "no data yet is neutral" convention
  as the regression gate.
- `app/config.py`: new `documentation_gate_max_undocumented_public_symbols`
  (default 2, not 0) — the scan can't distinguish "this subtask just added
  an undocumented symbol" from "this file already had one before this
  subtask touched it", so a hard 0 would occasionally block on pre-existing
  debt the subtask didn't create; a small non-zero threshold absorbs that
  honest imprecision without making the gate toothless. No separate opt-in
  flag — runs whenever `enable_security_architecture_gates=True` (already
  the "gates enabled" umbrella #454 extended the same way), consistent with
  not requiring operators to discover and set a second flag.
- Benefits from the SAME retry-before-block safety net #453/#455 built:
  a subtask that trips this gate gets one real self-correction attempt
  (the dev agent sees the missing-docstring finding as a `qa_errors` entry
  and can add docstrings) before the subtask actually blocks — not a
  first-strike hard stop.

Tests: 8 new in `tests/test_doc_coverage.py` (undocumented function/class
flagged, documented function not flagged, private symbols not flagged,
non-.py files skipped, missing/unparseable files skipped without raising,
only the given changed files are scanned — not the whole worktree, nested
functions out of scope) + 5 new in
`tests/test_batch16_quality_gates.py::TestDocumentationGate` (no-data
skip, over-threshold blocks, within-threshold doesn't block, fully
documented doesn't block, check failure is non-fatal). 33/33 on
`test_doc_coverage.py` + `test_batch16_quality_gates.py` together;
`mypy --strict` clean on all 3 touched files. Broader sweep
(`quality_gate or doc_coverage or batch16 or manager`): 274 passed, 1
failed — reproduced passing standalone (a real-RAM-dependent resource-check
test, unrelated, flaky only under concurrent test-suite memory pressure).

## #297 — Auto documentation lookup while coding — DONE (2026-09-28)

The audit's own IMPLEMENTATION PLAN explicitly rejected a generic "looks
stuck, fetch docs" heuristic as too fragile ("no reliable non-regex signal
exists") and named the ONE narrow, high-confidence trigger it trusts:
"only fire when an import fails to resolve ... treat it as an opt-in
suggestion the agent surfaces, not a silent automatic fetch." Built exactly
that, reusing #396's own real import-resolution engine rather than a new
one.

- `app/repo_tools/code_hygiene.py`: refactored `find_broken_imports`'s
  per-file scan into a shared `_scan_file_for_broken_imports()` helper, and
  added `find_broken_imports_in_files(directory, files)` — the same real
  resolution logic (stdlib `importlib.util.find_spec`, real on-disk
  resolution for relative imports, `try/except (ImportError\|...)`-guarded
  imports correctly never flagged), scoped to a specific file list instead
  of a whole-directory scan, so it's cheap enough to run on every subtask
  attempt.
- `app/repo_tools/doc_lookup.py` (new): `lookup_package_doc_hint(package)`
  — real PyPI JSON metadata fetch (same curl-based invocation convention
  as `check_last_release.py`, not a new pattern), returning the package's
  real summary/homepage if a PyPI project of that exact name exists, or an
  honest "no PyPI package named X" note if it doesn't (the single most
  common real cause: import name ≠ pip install name, e.g. `import cv2`
  needs `opencv-python`). Never an LLM guess — real registry data or a
  plain degraded string, never a raise.
- `app/agents/manager.py`: wired into `_dispatch_one_subtask`'s retry loop
  at the SAME tier as the existing `dev_error` check — right after the dev
  agent produces its diff, before commit/QA/review. When the subtask's own
  changed `.py` files contain an unresolvable import, up to
  `auto_doc_lookup_max_imports_per_attempt` (default 3) real PyPI lookups
  are done and fed into `qa_errors` — the SAME mechanism that already
  becomes `retry_context` in the dev agent's next-attempt plan. This is the
  literal mechanism for "documentation surfaces automatically, no explicit
  call" — the dev agent never has to call a search/lookup tool itself; the
  real registry data is simply present in its next prompt.
- `app/config.py`: new `enable_auto_doc_lookup_on_broken_import` (default
  **True** — a broken import is, by construction, already a bug the
  subtask needs to fix on its next retry regardless, so this only makes
  that fix faster with real data instead of a bare `ImportError`; bounded
  to a handful of real HTTP calls, no LLM cost) and
  `auto_doc_lookup_max_imports_per_attempt` (default 3, bounds real network
  calls per attempt).
- Deliberately non-blocking on its own: this never sets `gate_blocked_reason`
  the way #453–457 do — it only forces a normal dev-retry cycle (same as a
  `dev_error`), consistent with the plan's "opt-in suggestion... not a
  silent automatic fetch" framing — it's advisory context for the very next
  real attempt, not a new blocking gate.

Tests: 7 new in `tests/test_t2b5_code_hygiene.py` (scoped-file variant:
detects, only scans given files not the whole directory, missing/non-.py
files skipped, guarded/stdlib imports not flagged) + 6 new in
`tests/test_doc_lookup.py` (2 REAL live pypi.org lookups — a real package,
a guaranteed-nonexistent name — plus curl-not-found/timeout/malformed-JSON/
unexpected-shape all degrading cleanly, matching `check_last_release.py`'s
own established real-network-test convention) + 4 new in
`tests/test_auto_doc_lookup_gate.py` (real broken-import file on a real
tmp_path worktree end-to-end through `run_manager()`: blocks after
retries exhausted with the real hint text present in the SECOND dev-agent
call's own `plan` argument — proving actual automatic delivery, not just
that a variable was set; a self-corrected import on retry completes
normally; disabled via config skips the scan entirely; a clean import
doesn't affect normal completion). 36/36 new+touched tests pass;
`mypy --strict` clean on all 4 touched files. Broader sweep (`code_hygiene
or doc_lookup or doc_coverage or auto_doc_lookup or quality_gate or batch16
or manager or hygiene`): after a mid-session Docker/Postgres outage (fixed
via `systemctl --user start docker-desktop` + `docker compose up -d db
redis`, same recovery as before), 311 passed, 4 failed — all 4 are the
same real-RAM-dependent resource-check tests (machine had genuinely only
673Mi free at the time, confirmed via `free -h`/`ps aux --sort=-%mem` —
Docker's own VM, VSCode/Pylance, and open browsers accounted for the
load), reproduced failing standalone under the same real low-memory
condition — not a regression, the resource check is correctly reporting
real system state. Full backend suite pending before this is pushed.

## #58 — Agent selection uses memory/past outcomes — DONE (2026-09-28)

**Real finding before writing anything (this session's pattern held
again)**: a much earlier initiative ("plan14 follow-on #3, Memory-Aware
Agent Selection") had already built almost the entire mechanism this item
asks for, end to end and on by default: `memory_embeddings.agent_name`
(migration 048), a scheduled `agent_historical_performance` rollup table +
background loop (`agent_historical_performance_enabled=True`,
recomputed every 6h, cache loaded at startup), and
`FleetManager.select()` already multiplying its score by a real, capped
`memory_performance_factor` derived from that table. All of this was
already covered by `tests/test_memory_aware_agent_selection.py` and
already running in production.

**Real gap confirmed by direct reading**: `success_rate` (the only signal
`memory_performance_factor` consults) is only ever computed for
`category='task'` rows, and `agent_name` was ONLY ever populated by
`app.memory.hooks.record_agent_run_outcome` — which is wired into
`app/api/specialized_agents.py`'s solo-agent dispatch paths (the ~55
standalone agents), but was **never called from `manager.py`'s own
per-subtask dev/QA/review dispatch loop** — the highest-volume real path
in the entire pipeline (every backend_dev/frontend_dev/qa/reviewer
subtask inside every epic). `run_manager()`'s own two `embed_task_outcome`
calls are correctly epic-level (aggregating however many different agents
worked the epic's subtasks — no single attributable agent there, and the
existing code comments already say so), so they were never going to close
this gap; the fix had to live at the per-subtask level instead.

**Fix applied**: `app/agents/manager.py::_dispatch_one_subtask` now calls
`record_agent_run_outcome()` once per subtask, right after its final
status is determined (completed or blocked), with the REAL agent that
worked THAT subtask (`selected_agent_name` — e.g. `backend_dev` — not a
guess or the epic-wide default). Builds a minimal `AgentResult` from data
already computed at that point (review/QA summary, review findings, files
changed) — no new computation, just routing what already exists into the
one function (`record_agent_run_outcome`) that already knew how to
attribute it. Resolves `repo_id` via the existing cached
`get_task_repo_id()`. Wrapped in the same non-fatal
try/except-log-and-continue shape every other memory write in this
codebase uses — a memory-write failure must never break subtask dispatch.

Tests: 4 new in `tests/test_manager_per_subtask_memory_outcome.py` — real
`run_manager()` end-to-end (mocked dev/qa/reviewer, mocked `publish_event`
so a plain sentinel can stand in for `db` without a real Postgres
session — same convention as `test_gap_closure_days0_18.py`'s own
`TestManagerTraceIdAndCheckpointWiring`): a completed subtask records
`agent_name="backend_dev"`/`task_id`/`epic_id` correctly; a blocked
subtask records `status="blocked"`; no `db` session is a harmless no-op
(mirrors `record_agent_run_outcome`'s own "memory never breaks dispatch"
guarantee); a `record_agent_run_outcome` failure never breaks the
subtask's own completion. 4/4 pass; `mypy --strict` clean on
`manager.py`. Broader sweep (`memory_aware or manager or memory_outcome or
hooks or fleet_manager`): 232 passed, 4 failed — the same real-RAM-
dependent resource-check tests as #297 above (machine genuinely under
memory pressure at test time), reproduced as pre-existing/environmental,
not caused by this change. Full backend suite pending before push.

## #405 — Company Brain (org knowledge for prompts/tools) — DONE (2026-09-28)

Per the audit's own IMPLEMENTATION PLAN: "Fold PromptVersion diffs into
memory_hook_node's embedding-based retrieval as searchable text: add a new
embed_prompt_change() function mirroring the existing embed_bug/
embed_preference category pattern." Built exactly that — a real diff,
mirroring every step of the existing `embed_bug`/`query_bugs` pair rather
than inventing a parallel storage/retrieval mechanism.

- `app/memory/store.py`: new `embed_prompt_change()` (+`_sync` bridge, same
  shape as `embed_bug_sync` since `PromptRegistry.deploy()` is a plain sync
  method) and `query_prompt_changes()` — same near-duplicate/quality-gate/
  importance/verified handling as every other category, category=
  `"prompt_change"`, `task_id=f"prompt:{role_name}"` (a prompt/role change
  has no owning DevTask, same `"fleet-{agent_name}"`-style convention
  `embed_learning_signal` already uses). `_default_importance` gained a
  `"prompt_change" -> 0.7` branch — the same weight as `"architecture"`,
  since an approved+deployed prompt change is a deliberate governance
  decision, not a routine task log line. Wired into
  `query_memory_context()`/`query_memory_context_sync()`'s returned dict
  (new `"prompt_changes"` key, including the sync bridge's own error-
  fallback dict) and a new section in `format_full_memory_context()`.
- `app/agents/base_graph.py::memory_hook_node`: now passes
  `mem.get("prompt_changes", [])` into `format_full_memory_context()` —
  this is the literal "folded into memory_hook_node's retrieval" the plan
  asked for; every future agent run's pre-inference memory context can now
  surface a relevant past prompt/role change the same way it already
  surfaces bugs/preferences/procedures.
- `app/fleet/prompt_registry.py::PromptRegistry.deploy()`: after a real,
  successful deploy (file already written, DB already transitioned), computes
  a REAL unified diff (`difflib.unified_diff`) between the version being
  superseded (`parent_version_id`'s own content, or empty string for a
  role's first-ever version) and the newly deployed content, then calls
  `embed_prompt_change_sync()`. Best-effort (try/except, logged) — a
  memory-write failure must never undo or fail a deployment that already
  genuinely succeeded.

Tests: 7 new in `tests/test_prompt_change_memory.py` (real Postgres,
mocked only at the Voyage embedding boundary, same convention as
`test_memory_aware_agent_selection.py`: persists a real row with
category/outcome/task_id/files_changed correct, real semantic retrieval
finds it back, `query_memory_context`'s dict includes the new key,
`format_full_memory_context` includes/omits the section correctly, the
sync bridge works and degrades to `False` on failure) + 3 new in
`tests/test_prompt_registry_memory_wiring.py` (real `PromptRegistry`
lifecycle, `embed_prompt_change_sync` mocked: first deploy diffs against
empty content, second deploy diffs against the REAL parent version's
content — proving actual content lineage, not a placeholder — and a
memory-write failure never breaks a real deploy). 10/10 new tests pass;
`mypy --strict` clean on all 3 touched files; all 10 pre-existing
`test_prompt_registry.py` tests still pass unchanged. Broader sweep
(`prompt_registry or memory_store or memory_aware or prompt_change or
base_graph or memory_hook`): 126 passed, 0 failed. Full backend suite
pending before push.

## #66 — Switch tools mid-run — DONE (2026-09-28)

The audit's own IMPLEMENTATION PLAN was explicit: "Before writing any
code, define the concrete trigger conditions ... This is a product
decision first," and gave exactly one concrete illustrative example: "a
reviewer-flagged security issue unlocks a specialized `security_scan`
tool." Built exactly that example, as a real conditional branch in the
graph that adds a tool spec based on a real state signal — not a blanket
"anything goes" expansion, per the plan's own explicit warning.

- Reused the already-existing, already-tested `secrets_scan` tool
  (`app/tools/filesystem/secrets_scan.py`, the same tool `security_reviewer`
  itself already has) rather than inventing a new scanner — `backend_dev`/
  `frontend_dev` don't normally have it in `CODER_TOOLS`.
- `app/agents/backend_dev.py` / `app/agents/frontend_dev.py`: both
  `run_backend_dev`/`run_frontend_dev` gained a new
  `security_scan_unlocked: bool = False` parameter (default preserves
  today's exact behavior for every existing caller). When True, that one
  retry attempt's tool list gains `SECRETS_SCAN_TOOL` and a real
  `secrets_scan` handler bound to the subtask's own worktree, plus a short
  prompt note telling the dev agent the tool is now available and why.
- `app/agents/manager.py::_dispatch_one_subtask`: a new
  `security_scan_unlocked` flag, set True only when
  `_gate_block_reason`'s own deterministic "security_reviewer reported
  ...finding(s)" message (never model-authored text — this codebase's own
  generated diagnostic string, the same "graph's own recorded truth"
  pattern used throughout this session) triggered THIS attempt's block.
  Explicitly reset to False in every OTHER retry-triggering branch
  (dev_error, the #297 auto-doc-lookup broken-import check, a QA failure,
  reviewer-blocking-findings) so a stale unlock from an earlier, unrelated
  attempt never leaks forward past an intervening non-security retry.
  Threaded through to both dev-agent call sites.
- Scoped to exactly one retry attempt (the one right after the block),
  never a permanent grant — matches the plan's own "not a blanket
  expansion" requirement.

**Real bug found and fixed while writing this item's own tests**:
`tests/conftest.py` sets `ENABLE_SECURITY_ARCHITECTURE_GATES=false` as the
test-environment default (documented reason: most of this suite never
mocks security_reviewer/architecture_reviewer/dependency_security_agent
and would otherwise make real Anthropic calls) — any new test exercising
gate-triggered behavior must explicitly opt back in via
`patch.object(get_settings(), "enable_security_architecture_gates", True)`,
the same thing `test_batch16_quality_gates.py` already does. Missed this
on the first pass (silent 1-attempt no-op instead of the expected 2), caught
by comparing a standalone reproduction (worked) against the same code
running under pytest (didn't) before concluding the implementation itself
was correct.

Tests: 4 new unit-level (`test_security_scan_tool_unlock.py`, mocking
`run_agent_graph` directly, same convention as
`test_gap11_14_agent_critique.py`) proving the tool+handler are present
only when unlocked, for both dev agents — plus 3 new manager-level
end-to-end tests: a real security gate block unlocks the tool on exactly
the next attempt; a non-security (architecture) block never unlocks it;
and an unrelated QA failure sandwiched between a security block and a
later attempt correctly leaves the unlock reset, not stale. 7/7 pass;
`mypy --strict` clean on all 3 touched app files (test-file strictness
matches this codebase's own existing convention — pre-existing test files
have the identical untyped-helper pattern). Broader sweep (`backend_dev or
frontend_dev or security_scan or quality_gate or batch16 or
dynamic_subtask or gap11_14`): 168 passed, 0 failed. Full backend suite
pending before push.

## #443 — Detect hallucinating agents / memory leaks / sync failures — DONE (2026-09-28, scoped per the audit's own plan)

The audit's own IMPLEMENTATION PLAN explicitly named this "genuinely
missing capability, lowest priority of the NO items... treat as a
separate research/infrastructure initiative, not a quick fix," and split
it into two distinct sub-problems with very different real feasibility:

1. **Hallucination detection** — the plan's own suggestion (an LLM self-
   consistency check) turned out to already have a real, code-checked
   equivalent sitting unused: #502 (T2-B10) already runs
   `verify_file_line_citations()` at every real `submit_*` call across
   ~76 agents, independently re-checking every cited file:line and
   function/class name against the real repo — but it only ever LOGGED a
   warning, never persisted or aggregated the signal into anything a
   human or the fleet could actually query. Closed this real gap.
2. **Memory leaks / sync failures** — the plan is explicit and correct
   that there is **no existing hook to build on**: this platform edits
   and reviews target repos, it does not run them under sustained load,
   so there is nothing to profile. Left genuinely out of scope, same
   "needs infrastructure that doesn't exist" verdict already established
   for #169/#171/#494 elsewhere in this initiative — not silently
   dropped, explicitly documented here as correctly unbuildable today.

**Fix applied (sub-problem 1)**:
- `app/agents/base_graph.py`: `AgentRunState` gained
  `citation_hallucination_count: int` (new state key, defaulted to 0 in
  `initial_state`). `execute_tools`'s existing citation-check block (the
  one #502 already ran) now also sets a local
  `citation_hallucination_flagged_this_turn` flag, folded into the node's
  own final return as `state.get("citation_hallucination_count", 0) + (1
  if flagged else 0)` — the exact same read-old-value-add-this-turn's-
  delta pattern `reflection_unsatisfied_count` already uses for its own
  cross-turn accumulation, not a new mechanism.
- `app/fleet/metrics.py::RunMetrics` gained `citation_hallucinations: int
  = 0`, wired at the same finalization point `reflection_unsatisfied`
  already uses (`final_state.get("citation_hallucination_count", 0)`).
- `app/db/models.py::AgentRun` gained `citation_hallucination_count`
  (migration 061, applied to the real dev DB) — NULL for a run that
  crashed before finishing or predates this column, never a fabricated 0.
  `finish_agent_run`/`finish_agent_run_sync` persist it from the same
  `RunMetrics` instance already in scope, same wiring shape as #407's own
  four columns.
- `app/fleet/agent_registry.py`: new `compute_citation_hallucination_rate()`
  — real fraction of an agent type's runs with `citation_hallucination_count
  > 0`, excluding NULL rows from the denominator (a crashed run has no real
  signal either way), mirroring `compute_live_success_rate`'s exact
  aggregation shape. Returns `(None, 0)` with zero real data — "never
  hallucinated" and "never checked" are different claims.
- `app/api/registry.py::GET /api/agents/{name}/metrics` now surfaces
  `hallucinationFlagRate`/`hallucinationSampleSize` alongside the existing
  `userSatisfactionRate`/`avgRetries` — the real, queryable "which agents
  are actually hallucinating citations, how often" signal §88 Agent
  Health Monitoring asked for.

Tests: 4 new in `tests/test_batch18_citation_verification.py::
TestCitationHallucinationCount` (bad citation increments, good citation
doesn't, the counter genuinely accumulates across turns — not reset each
call, no-repo_path stays a no-op) + 5 new in
`tests/test_t443_hallucination_detection.py` (real Postgres:
`finish_agent_run` persists/nulls the column correctly on success/failure
paths; `compute_citation_hallucination_rate` returns `None` with no data,
a real fraction with mixed flagged/clean runs, and correctly excludes
NULL rows from the denominator) + 2 new in
`tests/test_t443_hallucination_metrics_endpoint.py` (real TestClient +
real Postgres: the endpoint surfaces a real rate/sample-size, and `None`
when an agent has no hallucination data at all). 11/11 new tests pass;
`mypy --strict` clean on all 6 touched app files. Broader sweep (`citation
or t443 or agent_registry or t2b7 or registry or hallucination`): 226
passed, 0 failed.

**Real regression caught by the full backend suite, fixed same-day**: #405's
own earlier addition of a 7th `query_memory_context` key (`prompt_changes`)
broke two PRE-EXISTING tests that hardcoded the old 6-key shape —
`test_b4_memory_categories.py::test_context_query_returns_all_six_sections_and_formats_them`
and `test_memory_context_query.py::test_query_memory_context_sync_returns_empty_on_failure`.
Both updated to include `prompt_changes` (renamed the first test to "all
seven sections" and added an explicit `assert mem["prompt_changes"] == []`
proving the new key is present and correctly empty for a query that never
seeded one) — a real, deliberate shape change on my own part that I'd
missed testing for at #405's own commit time; caught by this session's own
"always run the full suite before calling an item done" discipline rather
than shipped silently. 18/18 in both files pass after the fix.

## #45 + #67 — Agent-to-agent delegation — ALREADY DONE, no code needed (2026-09-28)

Confirmed via direct reading, no new code written: `app/agents/delegation.py`
+ `app/tools/agents/delegate.py` (`delegate_to_agent` tool) already satisfy
every requirement BOTH items' own IMPLEMENTATION PLAN asked for, built
as its own unit ("plan14 Day 4") **well before this Task 3 initiative
began** — the audit's "NO" verdict for both is simply stale, the same
class of discovery this session already made for #58/#129/#90/#98.

- **#45's 3 requirements** ("an explicit allow-list per agent role", "a
  delegation-depth cap", "cost/budget propagation"): all three are real,
  live, config-driven, and already covered by 20 passing tests
  (`tests/test_delegation.py`) — `delegation_allowed_matrix` (source
  agent → allowed target CAPABILITIES, default-deny outside the list),
  `delegation_max_depth` (chain-length cap, refused before dispatch, not
  after) + real cycle detection, and `delegation_default_budget_usd` with
  a genuinely decrementing running balance across multiple delegations in
  one run (a real bug in this exact area — budget not actually
  decrementing — was found and fixed during an EARLIER productionization
  pass, tool_enhance.md tool #3, 2026-08-15, confirmed via that file's own
  documented "real gaps found" section).
- **#67** ("call additional agents mid-run"): literally the same
  mechanism from the calling agent's own perspective — `delegate_to_agent`
  is an ordinary tool available during any covered agent's turn, invoked
  whenever the model chooses to, mid-run, by construction (not a separate
  pre-run-only registration).
- Routing is capability-based (`FleetManager.select()` resolves the
  concrete agent — never a hardcoded target name), reusing the SAME
  performance-aware scoring mechanism #58 also depends on, not a second
  routing system.
- Currently wired for 3 source agents (`backend_dev`, `frontend_dev`,
  `bug_fix`) via `delegation_allowed_matrix` — a deliberate, small,
  curated allow-list per the plan's own "a security boundary, not
  open-ended" requirement, not a coverage gap; expanding it to more
  agents is an additive config change, not a redesign (per
  `delegation.py`'s own module docstring).

No production code changes — verified existing behavior with
`pytest tests/test_delegation.py` (20/20 pass) rather than duplicating an
already-real, already-tested mechanism, per this session's own standing
rule: "if the current source shows that an old gap has already been
fixed, do not recreate it."

## #227 — Human takeover / step-level plan editing — DONE, deliberately scoped (2026-09-28)

The audit's own IMPLEMENTATION PLAN is explicit that a FULL solution ("a
plan data model with individually addressable steps... the pipeline graph
resumable from a specific mid-plan checkpoint instead of only the single
compiled-in human_review interrupt point") is "a graph-topology change...
not a small endpoint addition — plan it as its own project." Built the
real, bounded, honest slice that fits inside this session instead of
either skipping the item or silently overclaiming the full redesign:
**edit or reject individual plan steps at the existing human_review
interrupt**, as part of the SAME approval decision — no new interrupt
point, no graph-topology change, because the plan's own subtasks are
already sitting in state right there, individually addressable by
position.

**What this closes for real**: "edit plan" (yes — change a step's title/
description before approving) and "reject one step" (yes — remove a
specific step from the plan while approving the rest) are both real,
tested, end-to-end capabilities now. "Take over a task" in the sense of
"a human can directly modify the AI's plan instead of only accepting or
rejecting it wholesale" is real.

**What this deliberately does NOT close** (documented, not silently
dropped): "resume exactly there" in the sense of re-entering the PM→
Architect→Decomposer chain at an ARBITRARY mid-point (e.g., "redo just
the Architect's output, keep the PM brief") would need real per-node
checkpointing across that 3-node chain — the actual graph-topology
change the plan calls "its own project." That remains open for a future,
dedicated session.

**Backend** (`app/pipeline/graph.py`):
- New `apply_subtask_edits(subtasks, edits)` — pure, position-based
  (subtasks have no independent stable id beyond list position, the same
  convention #44's dynamic-subtask-creation work already established for
  this exact list). Each edit is `{"index": int, "action": "edit"|
  "reject", ...fields}`. "edit" overlays given fields onto that position;
  "reject" removes it — but refuses (raises `SubtaskEditError`) if any
  REMAINING subtask's `depends_on` still references the rejected index,
  rather than silently producing a broken dependency graph. Rejecting a
  step AND everything that depends on it together in one request is
  allowed.
- `human_review_node` now reads `subtask_edits` from the resume decision
  and applies them via `apply_subtask_edits` before finalizing the plan.
- `resume_pipeline()` gained an optional `subtask_edits` param, threaded
  through `Command(resume={...})` — `None` (the default) is the exact
  prior all-or-nothing behavior for every existing caller.
- `app/api/agents.py::resume_planning_pipeline` threads it through;
  `SubtaskEditError` is caught distinctly and logged — since the graph
  raises BEFORE `human_review_node` returns any state update, LangGraph's
  own checkpoint is untouched on a rejected edit, so the task stays
  exactly `awaiting_approval` and a retry is always safe.
- `app/api/tasks.py::POST /{task_id}/pipeline/approve` gained an optional
  `subtask_edits` request body field, validated SYNCHRONOUSLY against the
  currently-persisted plan (`PipelineState.subtasks_json`) for a fast
  `400` on an obviously malformed request before dispatching the
  background resume (which re-validates for real against whatever the
  plan's actual current state is at that moment — defense in depth
  against a race, not a duplicate source of truth).

**Frontend** (real UI gap closed, matching this session's own established
"backend without a UI is not actually usable" precedent from #3/#5/#12/
#498/#439/#381): `PipelineView.tsx`'s existing read-only subtask list had
no way to submit an edit at all. Added inline Edit/Reject controls per
subtask, shown only while `stage === "awaiting_approval"` — Edit reveals
title/description inputs, Reject dims the card with an Undo option. Local
edit/reject state is lifted to the parent page
(`app/tasks/[id]/page.tsx`) via a new `onSubtaskEditsChange` callback and
sent through the existing `approvePipeline()` API call
(`apps/web/lib/api.ts`, new optional `subtaskEdits` param) — approving
with edits pending is the SAME "Approve Plan & Start Coding" button,
no new button needed.

Tests: 10 new in `tests/test_subtask_plan_edits.py` (pure
`apply_subtask_edits` unit tests: no-op with no edits, edit overlays
correctly without mutating the input, reject removes a leaf step, reject
refuses when a remaining step still depends on it, rejecting a step and
its only dependent together is allowed, out-of-range/negative index and
unknown action are rejected, edit+reject combined in one request) + 4 new
in `tests/test_pipeline_approve_subtask_edits.py` (real HTTP + real
Postgres + mocked Anthropic, mirroring `test_day12_smoke_test.py`'s own
established convention: an edit reaches `launch_manager` with the edited
title; a rejected leaf step is actually removed from what reaches
`launch_manager`; rejecting a step its sibling depends on returns a real
`400` and leaves the task's status untouched; a plain approve with no
body at all still works exactly as before). 14/14 new backend tests pass;
`mypy --strict` clean on all 3 touched backend files; all 11 pre-existing
pipeline/approval tests still pass unchanged.

Frontend: 6 new in `components/PipelineView.test.tsx` (vitest +
testing-library: Edit/Reject buttons shown only while awaiting approval;
editing a title reports the exact edit shape the backend expects;
rejecting reports a reject entry and Undo correctly removes it; a step
edited then rejected reports only the reject, not a stale edit; local
edit state resets when the underlying plan itself changes). Full frontend
suite: 49/49 passed; `tsc --noEmit`, `eslint`, and `next build` all clean.
