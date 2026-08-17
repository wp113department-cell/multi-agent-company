# Tool #17 — `delete_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations, all generic (no domain-specific scoping, unlike
several `write_file`/`edit_file` variants):

1. `chat_agent.py`'s real interactive dispatch — confirmation-gated.
2. `make_chat_handlers()`'s own `delete_file` — reachable by `chat_agent`
   too (via the shared factory) and any other agent declaring it.
3. `make_cleanup_agent_handlers()`'s `cu_delete_file` — used by
   `cleanup_agent`, a real, one-shot agent with **no confirmation
   channel at all**.

Per `tool_inventory.json`: 2 real agents (`chat_agent`, `cleanup_agent`).

## Problems found

**No new path-escape vulnerability** — all 3 implementations already had
the worktree-boundary check fixed during tool #11's cross-cutting audit.
Re-verified directly this turn (absolute path outside repo, `.env`
denylist) rather than trusted from memory.

**Real AGENT ALIGNMENT finding** (a schema/implementation mismatch, not a
security bug): `DELETE_FILE_TOOL`'s schema has always required a `reason`
field —

```python
"reason": {"type": "string", "description": "Why this file is being deleted"},
"required": ["path", "reason"],
```

— telling the LLM this is mandatory information. **None of the 3
handlers ever read `inp["reason"]`.** It was silently discarded on every
call, for every agent, in every environment. This matters more than it
might first appear: `cleanup_agent` has no human-confirmation channel at
all (it's a one-shot batch agent) — its own transcript is the *only* real
record of why a file was deleted, and that transcript never captured the
reason the LLM itself was required to provide.

## Changes made

- **`app/tools/filesystem/delete_file.py`** (new): `DELETE_FILE_TOOL`
  (schema, unchanged) and `delete_file_handler(root, worktree_path, inp)`
  — the shared core. Now reads `reason` and includes it in the success
  message (`"Deleted {rel} (reason: {reason})"`), so a one-shot agent's
  transcript captures it.
- **`app/agents/chat_agent.py`**: its real dispatch now passes `reason`
  into the confirmation dialog's `details` (`"{rel}\nReason: {reason}"`)
  — the actual point of requiring it: a human approving an irreversible
  deletion should see *why* before clicking approve, not just *what*.
  Delegates the actual unlink to the shared handler after its own
  existence/is-file/confirm checks.
- **`app/agents/tools.py`**: both `make_chat_handlers`'s `delete_file`
  and `make_cleanup_agent_handlers`'s `cu_delete_file` now delegate to
  the shared function (the latter previously lacked the `is_file()`
  friendly-error check the other two had — a minor UX inconsistency also
  closed by the consolidation, not just the `reason` fix).

**One observable, intentional, low-risk change**: success messages now
include `(reason: ...)` when a reason was given. Checked every test
referencing `delete_file`'s exact output beforehand — none existed, only
loose checks.

## Tests (real, not mocked at the mechanism level)

`tests/test_delete_file_hardening.py` (new, 13 tests):

- Schema shape check (confirms `reason` is still required).
- Worktree-boundary re-verification: absolute path outside repo, `.env`
  denylist.
- **The reason gap, proven closed**: success message includes the
  reason; omits the suffix cleanly when no reason given; the real
  confirmation dialog (`self._confirm`'s `details` kwarg, inspected
  directly via mock) actually contains the reason text.
- Regression: user declining the confirmation, a missing file, a
  directory correctly rejected (with the friendly message), real
  deletion through both `make_chat_handlers` and
  `make_cleanup_agent_handlers`, and a real boundary-escape rejection
  through `make_cleanup_agent_handlers` specifically (the implementation
  that previously lacked the `is_file()` check, now sharing the fully
  guarded core).

## Regression

Targeted sweep (new test file + boundary-hardening tests from tool #11 +
audit_q_batch07/day3/phase52/session1/session3 migration tests +
run_tests hardening): **322 passed.** Full suite re-run after this pass
— see `tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

No new security vulnerability (already closed in tool #11); closed a
real requirements gap where mandatory LLM-provided context was silently
thrown away, mattering most for `cleanup_agent`'s unconfirmed, one-shot
deletions. No functionality lost.
