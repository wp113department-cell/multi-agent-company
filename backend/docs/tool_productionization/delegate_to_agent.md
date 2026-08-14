# Tool #3 — `delegate_to_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Unlike tools #1 and #2, `delegate_to_agent` started from a genuinely
mature base: `app/agents/delegation.py` (plan14 Day 4) already implements
real depth limits, cycle detection (checked against the resolved target
agent, not the requested capability), a config-driven per-source-agent
allowed-capability matrix, a shared budget, a wall-clock timeout via a
daemonized worker thread, structured `DelegationError` subclasses, and
real event/audit publication — all with 19 pre-existing adversarial tests
in `tests/test_delegation.py` (each guard proven to actually BLOCK, not
just log).

**A real inventory-tooling gap, found and worth noting**: the AST-based
tool inventory reported `test_file_count: 0` for this tool. That's a
false negative — the scanner only greps test files for the exact quoted
string `"delegate_to_agent"`, and `test_delegation.py` tests the
underlying `delegate()`/`DelegationRequest` functions and
`make_delegate_to_agent_handler` directly, never the literal tool-name
string. Confirmed by reading the file, not by trusting the inventory.
Lesson for future tools in this series: always verify a reported
zero-test-coverage tool by grepping for its real underlying functions
too, not just its registered name.

## Problems found (real, from reading the code — not assumed)

1. **Budget didn't actually decrement across multiple calls in one run.**
   `config.py`'s own `delegation_default_budget_usd` docstring claims
   "every subsequent delegation in that chain draws down from this same
   allocation" — but `make_delegate_to_agent_handler` captured
   `budget_remaining_usd` once at construction time and reused it
   UNCHANGED on every call through that same handler. An agent calling
   `delegate_to_agent` twice in one run (nothing prevented this, up to
   `delegation_max_delegations_per_run`, default 5) got the full budget
   both times — a real mismatch between documented and actual behavior.
2. **`backend_dev`/`frontend_dev` wiring gap.** `config.py`'s
   `delegation_allowed_matrix` already listed both as allowed source
   agents (`"backend_dev": ["security_review", "research_spike"]`,
   `"frontend_dev": [...]`) — real, intended policy — but neither agent's
   `AGENT_CONTRACT["allowed_tools"]` included `delegate_to_agent`, and
   neither `run_backend_dev`/`run_frontend_dev` ever wired the handler.
   The capability was configured but silently unreachable. Not a
   security hole (the matrix, plus tool #2's dispatch-authorization gate
   in `base_graph.py`, already refuse an unadvertised/unauthorized call
   either way) — a real functionality gap, found by cross-checking policy
   config against actual agent wiring (an AGENT ALIGNMENT check).
3. **Timeout mechanism cannot forcibly kill a hung child call** — a real,
   already-honestly-documented limitation in `_run_with_timeout` (a
   daemonized worker thread; Python threads cannot be forcibly
   terminated). Evaluated, not silently left: the thread is daemonized
   (won't outlive the process, unlike the bash tool's orphaned-container
   bug from tool #1), and a genuine fix (process-based delegation
   execution, or cooperative cancellation inside every adapter) is a
   materially larger architecture change than this pass's real findings
   justify. Logged as a real, known, non-blocking limitation.

## Changes made

- **`app/tools/agents/delegate.py`** (new): `make_delegate_to_agent_handler`
  now tracks `budget_remaining_usd` in a mutable single-element list
  (matching this codebase's own established idiom for a closure that
  needs to rebind a captured value across calls, already used in
  `app/agents/base_graph.py`), decremented by each real call's
  `outcome.cost_usd` — so a second call in the same run genuinely sees
  the reduced balance, and `delegate()`'s own existing
  `budget_remaining_usd <= 0` check now enforces a real running total.
- **`app/agents/backend_dev.py`** / **`app/agents/frontend_dev.py`**:
  added `delegate_to_agent` to `AGENT_CONTRACT["allowed_tools"]`, wired
  `handlers["delegate_to_agent"]` via `make_delegate_to_agent_handler`
  (ancestry starting at each agent's own name), and included
  `DELEGATE_TO_AGENT_TOOL` in the `tools=` spec list passed to
  `run_agent_graph` — closing the real dead-policy gap in problem #2.

## Modularization (tool_enhance.md §7/§8)

Extracted `DELEGATE_TO_AGENT_TOOL` (schema) and
`make_delegate_to_agent_handler` out of `app/agents/tools.py` into
`app/tools/agents/delegate.py` — following the same pattern established
for tools #1 and #2. `app/agents/delegation.py` (the real safety/
orchestration engine — depth/cycle/policy/budget/timeout, the `delegate()`
entry point) was already properly separated from `tools.py` before this
pass and did not need moving; only the tool-layer wrapper did.

Full TOOL PATH MIGRATION REPORT lives in the new module's own docstring.
Real consumers found by repository search and updated: `app/agents/
bug_fix.py`, `app/agents/backend_dev.py`, `app/agents/frontend_dev.py`
(all three updated to import directly from the new module — they were
already being touched in this same pass), `tests/test_delegation.py`
(updated its direct import). `app/agents/tools.py` keeps a compatibility
shim (`X as X` re-export convention) so nothing else breaks.
`scripts/generate_tool_inventory.py`'s one mention is a comment, not a
real reference — confirmed, not assumed.

## Tests (real, not mocked at the mechanism level)

- `tests/test_delegation.py` (+1 test): proves the budget-decrement fix
  directly — a handler constructed once, called three times, with the
  third call refused once the running balance is genuinely exhausted
  (would have passed incorrectly against the pre-fix code, since the old
  code never decremented at all).
- Pre-existing 19 adversarial tests in the same file re-run to confirm no
  regression in any safety guard (disabled/depth/per-run-limit/budget/
  disallowed-capability/matrix-is-per-source/no-available-agent/cycle/
  no-adapter/timeout/success/child-exception/events-audit/handler
  validation/handler policy-denied/handler success/GridironEvent fields/
  real end-to-end spike_agent delegation).
- Targeted sweep of every test file touching `backend_dev`/`frontend_dev`
  (agent registry, orchestration, quality gates, dispatcher, dynamic
  subtasks, failure ladder, critique, fleet-manager dispatch, topological
  subtask order, checkpoint/trace-id wiring, hierarchy chain, manager
  git-commit/slot-timeout, priority dispatch, session migrations, subtask
  fanout, task images, dead-contract-fix, dispatch-authorization-gate):
  502 passed — confirms wiring the new tool into two more agents broke
  nothing.

## Regression

Targeted sweep: 502 passed (plus the delegation suite's own 20). Full
suite re-run after this pass: **4773 passed, 52 skipped, 18 deselected,
0 failures.**

## Final verdict

**GREEN FLAG.**

Both real problems found during the audit — the budget-decrement bug and
the backend_dev/frontend_dev wiring gap — are fixed with real,
evidence-backed tests, not assumed. The timeout mechanism's real,
already-honestly-documented limitation (cannot forcibly kill a hung
child thread) is a known, non-blocking constraint, not a hidden gap —
consistent with how bash tool's `infra_dry_run` exception and create_pr's
own logged follow-ups were handled in this same series.
