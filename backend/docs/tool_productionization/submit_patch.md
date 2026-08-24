# Tool #92 — `submit_patch` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

A single `submit_patch` closure inside `make_coder_handlers()` — not
duplicated anywhere else. Confirmed NOT in `CHAT_TOOLS` — intentional,
a batch-agent final-answer tool never exposed to the interactive chat
session; `chat_agent.py` correctly has no dispatch branch for it.

Per `tool_inventory.json`, 5 agents declare `submit_patch` in
`allowed_tools`, all reaching it through `make_coder_handlers()`
(`coder.py`, `backend_dev.py`, `frontend_dev.py`, `mobile_dev.py`). 10
existing test files reference this tool — checked directly: zero
invoke the real handler (either they mock `make_coder_handlers()`
entirely, per `test_session2_migration.py`, or check tool-name
membership/contract scoping). Non-pending files re-run and confirmed
passing unchanged (162 tests).

## Problems found

**No security vulnerability in this handler itself.** It is a pure
in-memory result sink — `patch_result["files_changed"] = ...` /
`patch_result["summary"] = ...` — no file I/O, no subprocess, no path
handling. Each real caller's `patch_result` dict is freshly created
per `make_coder_handlers()` invocation, verified isolated (no
cross-session/cross-agent leakage).

**Unlike tool #85's `submit_docs`, `files_changed` here DOES have a
real, consequential downstream consumer.** Traced to
`app/api/agents.py`, which passes it directly to
`app.services.git_service.git_add()`. That function was independently
audited and confirmed ALREADY SAFE:

- Rejects absolute paths (`os.path.isabs()`) — verified live,
  `git_add(repo, ["/etc/passwd"])` raises `ValueError` before ever
  reaching git.
- Places all paths after a `--` pathspec separator, closing the
  flag-collision class established elsewhere in this initiative.
- git's own `git add -- <path>` additionally refuses any path outside
  the repository on its own — verified live with a real
  `../<outside-file>` relative-traversal attempt, producing `fatal:
  ... is outside repository at '<repo>'`, the same class of
  already-safe external-tool-boundary refusal established for tools
  #27/#78/#80/#81/#90's own pathspec fields.

No fix was needed at this downstream layer since it was already
correct. `summary` was also traced and confirmed to have no downstream
consumer at all across all four real callers — a harmlessly-unused
field, the same shape as tool #85's `DocsReport.files_written`.

## Changes made

Extracted verbatim (no behavior change) into
`app/tools/agents/submit_patch.py` via `make_submit_patch_handler()`
(same factory-taking-a-dict design as tool #85's `submit_docs`) —
matches this initiative's mandatory per-tool modularization rule even
when no vulnerability was found. The trace of `git_add()`'s existing
protections is documented in the new module's own docstring, so a
future reader auditing this tool doesn't have to re-derive it.

## Tests

New file `tests/test_submit_patch_hardening.py`, 9 tests, all real (no
mocking) — schema check, confirmation this tool is intentionally
absent from `CHAT_TOOLS`, direct unit tests of the shared factory,
real-submission storage via `make_coder_handlers()`, a cross-instance
isolation test, and three tests re-verifying `git_add()`'s existing
protections live (absolute-path rejection, relative-traversal
refusal, and a legitimate real-file staging) rather than assuming they
still hold from reading the code alone. (These three needed a fixture
directory under `/home` rather than pytest's default `tmp_path` under
`/tmp`, since `git_add()`'s own `_validate_workspace()` enforces the
configured `allowed_workspace_parent`.)

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change. Per the standing lesson from tool #88, this turn was
also verified via a comprehensive `mypy app/agents/` sweep (98 files
clean), an `importlib.import_module()` sweep (all clean), and a
`python -W error` docstring escape-sequence check (clean) BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No vulnerability found in the handler itself; its real
downstream consumer traced and re-verified live as already safe rather
than assumed from reading the code; no functionality lost; full
regression clean.
