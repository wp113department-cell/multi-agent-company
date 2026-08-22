# Tool #63 — `slack_send_message` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only 1 real implementation existed: `app/agents/tools.py`'s
`make_chat_handlers()` `slack_send_message_h`. `chat_agent.py` had NO
dispatch branch for this tool at all — the same "advertised but never
dispatched" bug class as tools #4/#6/#22/#25/#33/#44/#45/#46/#48/#50.
`CHAT_TOOLS.count("slack_send_message") == 1` verified.

## Problems found

**"Advertised but never dispatched."** `slack_send_message` is fully
advertised via `CHAT_TOOLS`, so the interactive model can be told this
tool exists and attempt to call it — but every real call through
`chat_agent.py`'s `_execute_tool()` fell through to `"[ERROR] Unknown
tool"`.

**No new security vulnerability in the existing handler.** Audited
directly: `text` is JSON-encoded (`json.dumps({"text": text})`) and
sent as the raw request body via `urllib.request` — never
string-interpolated into a shell command or into the destination URL,
so there is no injection surface. The webhook URL is read from the
`SLACK_WEBHOOK_URL` environment variable, never accepted as an
LLM-controlled tool argument — the same trust boundary this initiative
already established for other env-sourced credentials/destinations
(`LINEAR_API_KEY`, database URLs). `channel` is deliberately unused,
matching its own schema description ("informational only — webhook
targets one channel") — a Slack incoming webhook is bound to exactly
one channel at creation time and cannot be redirected per-message
through this API; this is a correct, intentional contract, not a gap.

## Changes made

- **`app/tools/integrations/slack_send_message.py`** (new):
  `SLACK_SEND_MESSAGE_TOOL` schema (moved verbatim),
  `send_slack_message(webhook_url, text)` — the existing webhook-post
  logic, moved here verbatim, shared by both real call sites.
- **`app/agents/chat_agent.py`**: NEW real dispatch branch. Since
  posting a Slack message is a real external write with a real
  cost/consequence, publicly visible to a real channel's members — the
  same risk category as `create_pr`/`github_comment`/
  `github_create_issue`/`linear_create_issue` (tool #50's own
  precedent) — the new dispatch gates the actual send behind a real
  `self._confirm()` dialog showing the message text.
- **`app/agents/tools.py`**: `slack_send_message_h` now delegates to
  the shared function (zero behavior change on this side — it never had
  a confirmation gate to begin with, matching how `linear_create_issue`'s
  own standalone `tools.py` handler works too, since one-shot batch
  agents have no confirmation channel).

## Tests (real, not mocked — uses a real local HTTP server standing in
for the Slack webhook; `urllib.request` itself is never replaced, so
the real request/response path is exercised end-to-end)

`tests/test_slack_send_message_hardening.py` (new, 8 tests):

- Schema shape check.
- `send_slack_message()` posts a real JSON payload to a real local
  server and the server genuinely receives it.
- **The proven "advertised but never dispatched" finding, verified
  closed**: `ChatAgent._execute_tool("slack_send_message", ...)` now
  reaches a real dispatch — approved sends genuinely POST to the real
  webhook with the correct payload; denied sends never touch the
  webhook at all (`[DENIED]` returned, zero real network requests
  received).
- Regression: a missing `SLACK_WEBHOOK_URL` still errors cleanly on
  both real call sites; `make_chat_handlers`'s own handler still works
  unchanged; `slack_send_message` appears exactly once in
  `CHAT_TOOLS`.

Also re-ran `tests/test_stage4_tier3_tool_level_retry.py` (its
`slack_send_message` reference only checks `TOOL_MANIFEST` retry-policy
metadata against a mocked handler function, never the real one —
confirmed unaffected) and `tests/test_gap60_61_scan_and_large_file_performance.py`
(10 total, all passing).

## Regression

Full suite: **5396 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5388 before this tool).

## Final verdict

**GREEN FLAG.**
