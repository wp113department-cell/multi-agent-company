# Tool #7 — `propose_subtask` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Like `delegate_to_agent` (tool #3), this started from a mature base:
`propose_subtask`'s handler (`app/agents/tools.py`) does deliberately
cheap shape validation only, deferring real policy checks (allow-matrix,
duplicate-work, spawn-depth/count limits, file-lock reservation) to
`app.pipeline.dynamic_subtasks.integrate_proposals()` — a well-designed,
already-separated module with real Postgres-backed file-lock reservation
and a genuine "never raise past the boundary" contract. 33 pre-existing
tests in `tests/test_dynamic_subtask_creation.py`.

**Another inventory-tooling false negative, same class as tool #3's**:
the AST-based inventory reported `test_file_count: 0`. The scanner only
greps for the exact quoted string `"propose_subtask"`; the real test
file exercises the underlying functions
(`make_propose_subtask_handler`/`integrate_proposals`/
`validate_and_build_subtask`) directly, never the literal tool-name
string. Confirmed by reading the file, not by trusting the inventory —
same lesson reinforced twice now.

## Problems found (real — from reading config.py against actual agent wiring)

**The same real gap class found in tool #3 (`delegate_to_agent`):** a
config matrix promises a capability that the code doesn't deliver.
`config.py`'s `dynamic_subtask_allowed_matrix` already listed:

```python
"frontend_dev": ["frontend", "test"],
```

as real, intended policy — `frontend_dev` is allowed to propose
`frontend`/`test` subtasks. But `app/agents/manager.py`'s own dispatch
code only ever wired `propose_subtask` into `backend_dev`, with an
explicit, honest comment: *"only backend_dev is wired at the code level
for now... frontend_dev is a trivial, identical-shape follow-up."* That
follow-up was never actually done — `frontend_dev` never had the tool in
its `allowed_tools`, never had a `subtask_proposal_sink` parameter on
`run_frontend_dev`, and the dispatch-gating condition in `manager.py`
checked `selected_agent_name == "backend_dev"` specifically, so even
enabling `frontend_dev` in
`settings.dynamic_subtask_creation_enabled_agents` would have been a
silent no-op.

Unlike tool #3's version of this finding, this one's own code comment
already named it explicitly as pending — a real, honestly-labeled
incomplete rollout rather than a silent bug, but still a real,
concrete gap between documented policy and delivered capability, closed
here as the code's own comment already called for.

## Changes made

- **`app/agents/frontend_dev.py`**: added `propose_subtask` to
  `AGENT_CONTRACT["allowed_tools"]`; added a `subtask_proposal_sink`
  parameter to `run_frontend_dev` (identical shape to `run_backend_dev`'s
  pre-existing one); wires `handlers["propose_subtask"]` and adds
  `PROPOSE_SUBTASK_TOOL` to the `tools=` spec list only when a sink is
  passed — `None` (the default) remains a complete no-op, exactly
  preserving prior behavior for every existing caller/test.
- **`app/agents/manager.py`**: generalized the gating condition from
  `selected_agent_name == "backend_dev" and ...get("backend_dev", False)`
  to a lookup keyed by whichever agent was actually selected
  (`get(selected_agent_name, False)`) — covers both real callers without
  a second hardcoded branch, and passes `subtask_proposal_sink=propose_sink`
  through to `run_frontend_dev`'s call site too.
  `dynamic_subtask_creation_enabled_agents` stays empty by default, so
  this remains a no-op for every existing caller/test that never opts in.

## Modularization (tool_enhance.md §7/§8)

Extracted `PROPOSE_SUBTASK_TOOL` (schema) and `make_propose_subtask_handler`
out of `app/agents/tools.py` into `app/tools/agents/propose_subtask.py`,
alongside `delegate.py` (the same domain — agent-orchestration tools).
The real validation/integration logic
(`app.pipeline.dynamic_subtasks.integrate_proposals`) already lived in
its own module and did not need moving. Full TOOL PATH MIGRATION REPORT
lives in the new module's own docstring. Real consumers found by
repository search and updated: `app/agents/backend_dev.py`,
`app/agents/frontend_dev.py` (both updated to import directly from the
new module), `tests/test_dynamic_subtask_creation.py` (updated its
direct import). `app/agents/tools.py` keeps a compatibility shim.

## Tests (real, not mocked at the mechanism level)

- `tests/test_dynamic_subtask_creation.py` (+2 tests): a real,
  end-to-end proof mirroring the pre-existing `backend_dev` tests exactly
  — `run_frontend_dev` is called with `subtask_proposal_sink=None` when
  the feature is disabled (regression proof, default behavior unchanged);
  and, with `dynamic_subtask_creation_enabled_agents={"frontend_dev": True}`,
  a real proposal made by a `frontend` subtask is genuinely validated and
  dispatched in a later wave through a real `run_manager()` call — proving
  the wiring isn't just a config/schema entry with no working code behind
  it, the same standard tool #3's delegate_to_agent fix was held to.
- Pre-existing 33 tests re-run to confirm zero regression in any of the
  already-working `backend_dev` behavior or the validation/integration
  layer itself.

## Regression

Targeted sweep (dynamic-subtask-creation + agent-registry/contract +
delegation test files): 297 passed. Full suite re-run after this pass:
**4815 passed, 52 skipped, 18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

The one real gap found — a documented, honestly-labeled-as-pending
mismatch between `frontend_dev`'s real policy entitlement and its actual
wiring — is closed with a real, evidence-backed end-to-end test, not
assumed. No functionality was lost: `backend_dev`'s pre-existing behavior
is provably unchanged (its own regression tests still pass), and the
feature stays fully opt-in (`dynamic_subtask_creation_enabled_agents`
empty by default) for both agents alike.
