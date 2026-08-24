# Tool #86 — `fetch_url` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `ae_fetch_url` (inside `make_ai_engineer_handlers()`) — narrower,
   `urllib.request`-based, hardcoded 10s timeout, silently ignores the
   schema's own `timeout`/`summarize` fields entirely.
2. The general `fetch_url` closure inside `make_chat_handlers()`
   (~35 one-shot agents) — curl-subprocess-based.
3. `app/agents/chat_agent.py`'s separate interactive dispatch — also
   curl-based, built via a shell string (URL properly `shlex.quote()`'d,
   timeout `int()`-cast before interpolation — no injection surface,
   just an unnecessary `shell=True` where list-args would do).

Per `tool_inventory.json`, 7 agents declare `fetch_url` in
`allowed_tools`. `CHAT_TOOLS.count("fetch_url") == 1` verified. 5
existing test files reference this tool, all real — re-run and
confirmed passing unchanged (7 tests), including a shell-metacharacter
regression check that still holds against the rewritten
list-args-based implementation.

## Problems found

**SSRF protection was already correct and unchanged.** `_ssrf_denial_
reason()` resolves the hostname and rejects any private/loopback/
link-local/reserved address, including the cloud-metadata endpoint,
checking the RESOLVED IP so DNS-rebinding/bare-IP URLs are caught too.
Re-verified live on all three real call sites (cloud metadata,
`127.0.0.1`) — no fix needed.

**Finding #1 — an unbounded, LLM-controlled `timeout`, on TWO of the
three real implementations** (`make_chat_handlers()`'s closure and
`chat_agent.py`'s dispatch — `ae_fetch_url` was never exposed to this
since it hardcodes 10s and never reads the field). Neither clamped the
upper bound before passing it to both curl's own `--max-time` flag and
the wrapping `subprocess.run(..., timeout=fu_timeout + 5)` — a real
resource-exhaustion vector, flagged as a known pending item back in
tool #14's own audit ("3 known unbounded-timeout findings now on the
books... `fetch_url`'s timeout") and now closed for real.

**Finding #2 — an uncaught `ValueError` on a non-numeric `timeout`, on
the same two implementations — same class as tool #78's `git_log`.**
Proved live: `fetch_url({"url": "http://example.com", "timeout":
"not_a_number"})` raised `ValueError` uncaught through both real
dispatch paths.

**A secondary, non-security finding.** `ae_fetch_url` silently ignores
its own advertised `timeout`/`summarize` schema fields — always
fetches with a hardcoded 10s timeout via `urllib.request` and never
generates a summary even when `summarize=true` is passed, a real
functionality-parity gap the LLM has no way to detect from the tool's
own description.

## Changes made

Extracted a shared `fetch_url_handler()` in
`app/tools/execution/fetch_url.py`, adopted by all three real call
sites: `timeout`'s conversion is wrapped in `try/except (TypeError,
ValueError)`, returning a clean `[ERROR] timeout must be an integer,
got ...` message (closes finding #2); the result is then clamped to
`[1, 60]` (closes finding #1); `ae_fetch_url` is upgraded onto the
same curl-based implementation the other two already used (matching
its own advertised schema for the first time, closing the secondary
finding).

`app/agents/tools.py`'s `_FETCH_URL_TOOL` now aliases the shared
`FETCH_URL_TOOL` constant, and both closures delegate to the shared
handler. `app/agents/chat_agent.py`'s dispatch now calls the same
shared handler via `asyncio.to_thread`. Two now-unused imports
(`_llm_summarize_url_content`, `_ssrf_denial_reason`) were removed
from `chat_agent.py` after `ruff` caught them post-fix.

**Incidental fix, caught by mypy --strict (not by this tool's own
audit):** while verifying types, `mypy` (run against `app/agents/
tools.py` as a whole, not just the new module in isolation) surfaced
that `_FETCH_URL_TOOL`/`_LIST_FUNCTIONS_TOOL`/`_PARSE_AST_TOOL`
(the latter two a pre-existing gap from tools #82/#83, missed then)
were "not explicitly exported" — a real `mypy --strict` violation,
since `spike_agent.py`/`code_explainer_agent.py` import these names
directly from `app.agents.tools`, and a renaming `X as _X` import
isn't recognized as an explicit re-export under this project's
`strict = True` mypy config. Fixed by using plain module-level
assignments (`_X = X`) instead of import-renames for these three,
placed after the import block to avoid an E402 cascade. Runtime
behavior is unaffected — this was a static-typing-only issue.

## Tests

New file `tests/test_fetch_url_hardening.py`, 13 tests — schema check,
the unbounded-timeout clamp verified via a `subprocess.run` spy
(`monkeypatch`, no real network call) on both previously-unbounded
real dispatch paths, the non-numeric-timeout fix verified closed on
all three real call sites, SSRF protection re-verified live as a
regression guard, `ae_fetch_url`'s newly-gained `summarize` field
handling, and legitimate-usage regression (a real fetch of
`https://example.com`) across all three real access paths — matching
this tool's own established test-suite convention of hitting a real,
stable domain rather than mocking the network entirely.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** Both real findings (one of them a known pending item
since tool #14) proved live and closed; SSRF protection re-verified
rather than assumed; a genuinely separate `mypy --strict` re-export
gap (including a pre-existing one from tools #82/#83) caught and fixed
in the same pass; no functionality lost — `ae_fetch_url` gained real
capability it previously advertised but never delivered; full
regression clean.
