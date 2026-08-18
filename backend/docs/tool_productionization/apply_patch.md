# Tool #27 — `apply_patch` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch — the only real,
   reachable caller.
2. `make_chat_handlers()`'s own `apply_patch` — already correctly
   guarded, per a prior, cited audit finding in its own comment
   ("Blocker 1 fix", `audit_v1.md` 4.5/4.8).

## Problems found (real, empirically verified — severe: a proven, live
protected-path bypass)

`apply_patch`'s schema has **no top-level `path` field** — the file(s)
it touches are embedded entirely inside the diff's own `+++`/`---`
header lines. `chat_agent.py`'s dispatch wrote the LLM-controlled `patch`
content straight to a temp file and ran the real `patch` CLI against it
with zero inspection of what those headers actually named. Proved
directly, before writing any fix: a real unified diff targeting `.env` —
a file every other write-capable tool in this codebase refuses to touch
— was applied successfully, genuinely overwriting its content:

```python
result = await agent._execute_tool("apply_patch", {
    "patch": "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-SECRET_KEY=original_value\n+SECRET_KEY=PWNED_VALUE\n",
    "strip": 1,
})
# -> "patching file .env"
# .env's real content was overwritten
```

`make_chat_handlers`'s own implementation already closed this via
`_extract_patch_target_paths()` (parses every real target path out of
the diff's own headers, applying the same `-pN` strip the `patch` CLI
itself applies) + `_is_protected_path()` on each — but `chat_agent.py`'s
dispatch, the actual live path real users talk to, never had it wired
in.

**Separately investigated**: the classic patch-path-traversal exploit
(absolute paths or `../` inside the diff headers, letting `patch` write
outside the intended directory). Could not reproduce it — this system's
GNU `patch` binary already refuses those with its own built-in
`"Ignoring potentially dangerous file name"` check, confirmed across
three real attack shapes (a `../`-relative header, an absolute-path
header, and a `/dev/null`-sourced new-file-creation header). That
protection is external to this codebase and version/OS-dependent, so the
fix still validates every target path itself — matching
`make_chat_handlers`'s already-correct, defense-in-depth approach —
rather than relying solely on whatever `patch` binary happens to be
installed.

## Changes made

- **`app/tools/filesystem/apply_patch.py`** (new): `APPLY_PATCH_TOOL`
  (schema, unchanged) and `apply_patch_handler(repo_path, inp)` — the
  already-correct logic from `make_chat_handlers`, extracted so both
  real call sites share one implementation.
- **`app/agents/chat_agent.py`**: its real dispatch now calls the shared
  handler via `asyncio.to_thread` instead of duplicating the unguarded
  logic inline.
- **`app/agents/tools.py`**: `make_chat_handlers`'s own `apply_patch` now
  delegates to the shared function.

## Tests (real, not mocked at the mechanism level — real `patch`
subprocess execution throughout)

`tests/test_apply_patch_hardening.py` (new, 8 tests):

- Schema shape check.
- **The exact proven exploit, verified closed**: the real `.env`-
  targeting payload rejected through both the shared handler directly
  and the real `chat_agent.py` dispatch, content confirmed unchanged. A
  second protected-path case (`secrets/` directory). A patch with no
  extractable target path rejected cleanly.
- Regression: a real, legitimate patch applies correctly and produces
  the exact expected file content, through the shared handler,
  `chat_agent.py`'s dispatch, and `make_chat_handlers` — all three
  proven with real `patch` subprocess execution, not mocked.

## Regression

Targeted sweep (new test file + batch11 policy chokepoint/chat_tools/
fleet_tool_manifest/fleet_metrics/session1_migration/append_file
hardening): **284 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live protected-path bypass — proven by actually overwriting
`.env` through the tool — closed by wiring in an already-correct,
already-audited implementation. No functionality lost: a real,
legitimate patch continues to apply exactly as before.
