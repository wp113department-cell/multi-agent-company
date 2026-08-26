# Tool #116 — `read_logs` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations:

1. `chat_agent.py`'s own interactive dispatch.
2. `read_logs` inside `make_chat_handlers()`.
3. `bf_read_logs` (`make_bug_fix_handlers`).
4. `mon_read_logs` (`make_monitoring_agent_handlers`).

Per `tool_inventory.json`, agents declaring `read_logs` go through one
of these. `CHAT_TOOLS.count("read_logs") == 1` verified. 2 existing
test files reference this tool (`test_chat_tools.py::TestReadLogs`,
`test_day2_agents.py::test_read_logs_missing_file`) — re-run and
confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 (most severe) — a worktree-boundary escape that is a
genuine ARBITRARY FILE READ, on ALL FOUR real implementations.**
`bf_read_logs`/`mon_read_logs` built `root / log_path` without
checking whether `log_path` was already absolute — Python's own
`pathlib` semantics silently discard the left operand of `/` when the
right operand is an absolute path, so `root / "/etc/passwd"` resolves
to `/etc/passwd`, not an error. `read_logs` (`make_chat_handlers`) and
`chat_agent.py`'s dispatch made the same mistake explicitly and
deliberately:
```python
log_file = root / rl_path if not Path(rl_path).is_absolute() else Path(rl_path)
```
Proved live, on all four real access paths: a `path` value of an
absolute path outside the intended worktree (`/tmp/<marker>.log`) was
genuinely read and its content returned verbatim.

**Finding #2 — a real functionality-divergence bug:
`bf_read_logs`/`mon_read_logs` silently ignore the schema's own
documented `level` filter and never support the schema's documented
"or service name for journalctl" behavior** — they only ever read a
literal file via plain Python I/O. `read_logs` (`make_chat_handlers`)
and `chat_agent.py`'s dispatch already implement the full contract
(file tail, journalctl-by-service-name, level filtering, and
auto-discovery of the newest log when no `path` is given) — that
fuller, correct design is what the shared handler is built from. The
original file-tail branch of the fuller implementations was also
missing `try/except` + `timeout=` around its `subprocess.run()` call,
same robustness class already established for tools #105/#109/#114.

## Changes made

New shared `read_logs_handler()` in
`app/tools/execution/read_logs.py`:
- `path` (when it looks like a file path — contains `/` or ends in
  `.log`) is validated via `check_path_in_worktree()` before any
  filesystem access, closing finding #1.
- Implements the tool's full documented contract (file tail /
  journalctl-by-service / level filter / newest-log auto-discovery)
  for all four real call sites, closing finding #2 as a genuine
  capability increase for `bf_read_logs`/`mon_read_logs`.
- Every subprocess call now has `try/except` + `timeout=10`.
- `lines` is clamped to `[1, 5000]`.

All four real call sites (`chat_agent.py`'s dispatch, `read_logs` in
`make_chat_handlers`, `bf_read_logs`, `mon_read_logs`) now delegate to
this one handler. `app/agents/tools.py`'s `_READ_LOGS_TOOL` now
aliases the shared `READ_LOGS_TOOL` constant. No external
direct-importers of the old schema name were found.

## Tests

New file `tests/test_read_logs_hardening.py`, 16 tests: schema check,
duplicate-registration check, worktree-escape-blocked proof
(parametrized across all three `tools.py` factories, plus a direct
handler call and a `chat_agent.py` dispatch call) with an assertion
the secret content never leaks into the result, level-filter contract
proof (parametrized across all three factories), and legitimate-usage
regression across all four real access paths.

Existing tests re-run and confirmed passing:
`test_chat_tools.py::TestReadLogs` (3/3),
`test_day2_agents.py::test_read_logs_missing_file` (1/1).

## Regression

This tool is tool 3 of the #114-#118 batch. Its own new hardening
tests (16/16 pass) and directly-referencing existing tests (4/4 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
read_logs.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all `app/agents/` modules (all clean), a `ruff check` on
all touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across all
four real implementations; no functionality lost — legitimate usage is
proven to still work, and `bf_read_logs`/`mon_read_logs` now honor the
tool's full documented contract (level filter, journalctl) where
before they silently ignored it; tool-specific and
directly-referencing regression tests clean.
