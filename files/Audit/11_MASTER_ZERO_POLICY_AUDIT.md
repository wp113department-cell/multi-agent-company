# MASTER ZERO POLICY AUDIT — Hallucination, Hardcoding, Leakage, Dead Code, Loops, Races

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.
# Follow 00b_AUDIT_STANDARDS.md's evidence schema and JSON output for every
# finding in this audit.

You are a Principal Staff Software Engineer running a strict "Zero Policy"
sweep — a set of properties this codebase should satisfy everywhere, not
just where it's convenient to check. Each policy below gets its own
sub-section in your report. For each, either show it holds (with evidence)
or show exactly where it's violated (with evidence). Partial compliance is
reported as partial, not rounded up.

## ZERO HALLUCINATION ARCHITECTURE

- For every agent that produces structured output (JSON/Pydantic), confirm
  the schema is actually validated before being trusted downstream — grep
  every `submit_*` tool handler in `backend/app/agents/tools.py` for
  Pydantic model validation vs. raw dict pass-through.
- Confirm agents that claim file paths, function names, or line numbers
  (reviewer, bug_fix, security_reviewer, architecture_reviewer) are
  required by their role prompt to have actually called a read/search tool
  before asserting them — check the role file's stated process AND whether
  `VerificationConfig` enforces evidence of a read call, not just trusts
  the prompt.
- Confirm the `reflection_node`'s `reflection_unsatisfied_count` (the
  hallucination-rate proxy per PROJECT.md's Day 10 work) is genuinely wired
  to something meaningful, not a constant.

## ZERO HARDCODING

- Grep the entire `backend/app/` tree for hardcoded: model names, API URLs,
  file paths outside `config.py`, magic numbers used as thresholds/limits/
  retry counts, and hardcoded credentials/secrets.
- Cross-check against PROJECT.md's own documented hardcoding fixes (CORS
  origins, event bus max retries, Groq max retries) — confirm these are
  STILL config-driven and no new hardcoded value has crept in near them.
- Any `if agent_name == "specific_name"` type conditional outside the
  dispatcher/registry pattern is a hardcoding smell — find and list any.

## ZERO PROMPT LEAKAGE / ZERO CONTEXT LEAKAGE

- Confirm no role file or system prompt is ever echoed back verbatim to an
  end user in an API response (check chat endpoint responses, error
  messages, and any "explain yourself" style tool).
- Confirm one task/epic's context (memory_context, repo_context, file
  contents) can't leak into a DIFFERENT task's agent run — trace how
  `memory_context`/`repo_context` are scoped per-run in `AgentRunState` and
  confirm no shared mutable global carries stale context across runs.
- Confirm credentials injected via `extra_env` (Day 17) are scoped to the
  single bash call they're meant for, not leaked into logs, activity-stream
  events, or agent output text.

## ZERO MEMORY LEAKAGE (process memory, not "engineering memory")

- Confirm `LessonStore` (in-process) has a bound (max size / eviction) or
  is explicitly documented as safe to grow unbounded for this deployment's
  expected lifetime — if unbounded and no eviction, flag as a real resource
  leak risk for long-running processes.
- Confirm SSE connections (`activity_stream.py`) and their per-task queues
  are actually cleaned up when a client disconnects or a task completes —
  trace the cleanup path, don't assume from the queue's existence.
- Confirm background `asyncio.create_task(...)` fire-and-forget calls are
  not silently accumulating unreferenced tasks (a real asyncio memory-leak
  pattern) — are they stored/awaited/tracked anywhere, or purely fired and
  forgotten with no reference retained (which is fine for gc, but confirm
  exceptions aren't lost too — cross-reference audit 08's observability
  findings if already run).

## ZERO DEAD CODE / ZERO ORPHAN AGENTS / ZERO UNREACHABLE AGENTS

- For every one of the ~72 registered agents, confirm a real (non-test)
  call site exists. List any agent registered in `capability_registry` with
  zero real callers — this exact pattern has recurred multiple times per
  PROJECT.md's gap-closure history (chat_agent once, versioned_memory once,
  fleet_checkpoint once, tool_discovery still borderline). Check current
  state fresh, don't trust the last report.
- For every tool in `CHAT_TOOLS`/`CODER_TOOLS`/`READ_ONLY_TOOLS`, confirm a
  real handler exists AND is reachable (no tool spec with a missing or
  stubbed handler).
- Grep for any function/class with zero call sites anywhere in `app/`
  (excluding tests and `__init__.py` re-exports).

## ZERO DUPLICATE LOGIC / ZERO DUPLICATE AGENTS

- Confirm no two agents have genuinely overlapping responsibility with no
  differentiation (e.g. two separate agents both silently reviewing the
  same class of code with different names) — this is a design-fit check,
  be conservative, only flag genuine duplication, not "similar category."
- Confirm capability tags are unique fleet-wide (cross-reference audit 02
  if already run — don't re-derive, just confirm no regression since).
- Grep for copy-pasted tool-handler logic across agent files that should be
  a shared helper (e.g. the same file-path-validation snippet duplicated
  in 5 places instead of imported from one).

## ZERO INFINITE LOOPS / ZERO HIDDEN INFINITE LOOPS

- Confirm every retry loop (coder self-correction, `run_manager`'s
  dev→qa→review loop, Groq nudge-on-empty-tool-call logic) has a real,
  enforced upper bound — trace the actual counter and break condition, not
  just the presence of a `MAX_RETRIES`-looking constant that might not
  actually be checked on every iteration.
- Confirm the stall-detection logic in `base_graph.py`'s router
  (`n_stalls` counter) actually terminates the graph rather than looping
  indefinitely under a stuck condition.
- Confirm no `while True:` in the codebase lacks a reachable break/return
  on every path (background loops like retention/benchmark-baseline are
  fine if they sleep+continue by design — confirm they're not spinning
  hot).

## ZERO CIRCULAR DEPENDENCIES / ZERO CIRCULAR ROUTING

- Check Python module imports under `app/` for cycles (A imports B imports
  A).
- Check agent dispatch routing (`dispatcher.py`, `manager.py`,
  `fleet_manager.select()`) for any path where Agent A's failure could
  route back to Agent A in a loop rather than escalating.

## ZERO SECURITY LEAKAGE / ZERO SILENT EXCEPTIONS / ZERO UNHANDLED ERRORS

- Grep for broad `except Exception:` blocks (or bare `except:`) and assess
  each one: does it log with enough detail to debug, or silently swallow?
  PROJECT.md documents at least one real case (`launch_coder`'s handler
  silently swallowing a real timezone `DataError`) where a broad except
  hid a real bug for a long time — actively hunt for OTHER instances of
  this exact shape (broad except near a DB write or external call, logging
  only a generic message).
- Confirm no exception handler re-raises a sanitized error to the API layer
  while logging (or leaking) full stack traces / secret values elsewhere.

## ZERO PRODUCTION BLOCKERS

- Consolidate: does anything found in this Zero Policy sweep, on its own,
  constitute a hard production blocker? List them explicitly, separate
  from the general findings list, so the final consolidation audit can
  weight them correctly.

## Final Report

Follow the evidence schema and JSON output format from
`00b_AUDIT_STANDARDS.md` exactly. Additionally produce:

1. A Zero Policy Compliance Table — one row per policy above, with
   status: FULLY COMPLIANT / PARTIALLY COMPLIANT (n violations) /
   NOT COMPLIANT (n violations), each with evidence
2. Zero Production Blockers list (subset of Critical findings)
3. Zero Policy Layer score (0-100)

Do not write code. Do not modify files. Evidence or NOT FOUND only.
