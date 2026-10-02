# Audit 11: Zero Policy

**Spec:** `files/Audit/11_MASTER_ZERO_POLICY_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-10-02 · **JSON sidecar:** `json/AUDIT_11_ZERO_POLICY.json`
**Evidence:** `evidence/silent_excepts.py`, `evidence/unreferenced_functions.py` (+ `.out.json`)

## Result

🟢 **GREEN: no production blockers. 4 defects fixed (1 High, 2 Medium, 1 Low); the remaining items are Low and documented.**

**Zero Policy score: 85 / 100.**

## Compliance table

| Policy | Status | Evidence |
|---|---|---|
| Zero hallucination | **PARTIALLY COMPLIANT (1, Low)** | Submit tools are validated against their JSON schemas, but a mismatch is a soft warning, not a rejection (known since audit 02). Reflection is real: `reflection_unsatisfied_count` comes from state, triggers replanning (`base_graph.py:1348`) and feeds metrics; it is not a constant. |
| Zero hardcoding | **PARTIALLY COMPLIANT (4, Low)** | **No model ids outside config/model_router.** Fixed public API URLs (PyPI, npm, GitHub, Linear) are endpoints, not settings. 4 agent-name special cases outside the dispatcher: `test_coverage_agent` ×2 (`api/specialized_agents.py:532, :813`, same logic duplicated), `coder` (`api/approvals.py:132`), `frontend_dev` (`manager.py:597`). |
| Zero prompt leakage | **FULLY COMPLIANT** | No API route returns a role file or system prompt. The only prompt endpoints are the approver-only prompt-version admin screens (`api/fleet_dashboard.py`), which exist on purpose. |
| Zero context leakage | **PARTIALLY COMPLIANT (1 fixed, 1 Low open)** | Per-run context lives in `AgentRunState`, not globals. **Credential vault leak FIXED** (below). Open (Low): `LessonStore` lessons are shared across repos; they are generic lessons with no code or secrets, and the store is bounded. |
| Zero memory leakage | **FULLY COMPLIANT** (after audit 09) | `LessonStore` capped at 1,000 (FIFO + LLM compression). SSE queues bounded and removed on disconnect; stream registry now capped (audit 09). Fire-and-forget tasks are tracked and their errors logged (audit 08). |
| Zero dead code / orphan agents | **PARTIALLY COMPLIANT (Low)** | **0 of 85 registered agents are orphans** (`chat_agent` reached via the chat API; 15 via `/api/agents/{name}/run`; the rest via manager, delegation, gates or startup loops). **All tools have handlers:** CHAT_TOOLS 190/190, READ_ONLY 17/17, CODER 23/23 (`record_learning` added by each coder agent). **Removed:** `app/fleet/providers/` (dead since audit 01). Remaining: about 20 unused helpers (response models, event builders, trend helpers) and `pipeline/dispatcher.py` (test-only). |
| Zero duplicate logic / agents | **FULLY COMPLIANT** (1 Low) | Path validation is shared: one `check_path_in_worktree` with 181 call sites. Capability tags unique (audit 02, no regression). Only duplicate: the `test_coverage_agent` special case above. |
| Zero infinite loops | **FULLY COMPLIANT** | All 32 `while True:` loops checked: 22 background loops sleep on every iteration, the terminal loop ends on disconnect, and the sandbox poll loop has a deadline. Retry loops have enforced counters (audit 04); stalls end the graph at `max_stalls`. |
| Zero circular dependencies / routing | **FULLY COMPLIANT** | Import-time cycle scan over 497 modules: 1 cycle, `app.event_bus` re-exporting its own submodule (benign). Failure routing escalates (failure ladder) and never retries the same agent forever. |
| Zero silent exceptions | **FIXED → COMPLIANT on risky paths** | 756 broad handlers. Silent ones dropped from 103 to 74, and **silent ones around DB, LLM, subprocess or event operations dropped from 29 to 0** (the one remaining scan hit, `spend_guard.py:127`, logs via a helper). The other 74 wrap optional imports or cosmetic steps. |
| Zero security leakage | **FIXED** | See ZP-11-001 and ZP-11-002. |

## Findings

| ID | Sev | Status | Finding | Fix |
|---|---|---|---|---|
| ZP-11-001 | **High** | FIXED | **Host mode leaked server secrets to agents.** With `BASH_SANDBOX_ENABLED=false`, an agent's bash command inherited the backend's whole environment, so `env` or `echo $ANTHROPIC_API_KEY` printed the server's API keys and database URL into the LLM context and the logs. | Secret-looking variables (`*KEY*`, `*SECRET*`, `*TOKEN*`, `*PASSWORD*`, `DSN`, `DATABASE_URL`, `REDIS_URL`) are dropped in host mode (`tools/execution/bash.py::_host_env`). The default sandbox mode was already safe. |
| ZP-11-002 | Medium | FIXED | **Credential vault values appeared in tool output.** The docstring promised values never reach output, but `echo $SECRET` printed them, and they then flowed to the LLM, task logs and the activity stream. | Every `extra_env` value is masked as `[REDACTED]` in stdout, stderr and streamed output (`_redact_values`). |
| ZP-11-003 | Medium | FIXED | 29 silent `except: pass` around DB writes, event publishing, metrics recording, subprocesses and embeddings, the same shape as the hidden `launch_coder` bug. | Each now logs `logger.warning(..., exc_info=True)` with the function name, in 13 files. Behavior unchanged (still best-effort). |
| ZP-11-004 | Low | FIXED | Dead module `app/fleet/providers/` (never imported). | Removed. |
| ZP-11-005 | Low | OPEN | 4 agent-name special cases outside the dispatcher | Documented |
| ZP-11-006 | Low | OPEN | About 20 unused helpers (`evidence/unreferenced_functions.out.json`) | Documented; harmless |
| ZP-11-007 | Low | OPEN | LessonStore shared across repos | Documented; generic lessons only |
| ZP-11-008 | Low | KNOWN | Submit-schema validation is a soft warning | Known since audit 02 |

## Zero production blockers

**None.** Both security leaks (ZP-11-001/002) are fixed.

## Tests

- `tests/test_audit11_bash_secret_hygiene.py` (3): the vault value is masked in output **and** in streamed output; host mode hides `ANTHROPIC_API_KEY` and `DATABASE_URL` while `PATH` still works (real subprocesses).
- `tests/test_bash_sandbox_wiring.py`, `tests/test_credential_vault.py`: the "secret reaches the command" checks now test the value inside the command (`[ "$X" = value ] && echo SEEN`), because printing it is now (correctly) masked.
- Regression over every touched module: 744 passed. Bash, sandbox and vault suites: 152 + 32 passed.
