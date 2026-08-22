"""slack_send_message tool — tool_enhance.md productionization pass,
tool #63 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: slack_send_message
Old path: app/agents/tools.py (`_SLACK_SEND_MESSAGE_TOOL` schema dict
    and the `slack_send_message_h` handler inside `make_chat_handlers()`)
    — already in CHAT_TOOLS but with NO app/agents/chat_agent.py
    dispatch.
New path: app/tools/integrations/slack_send_message.py (this file) —
    `SLACK_SEND_MESSAGE_TOOL`, `send_slack_message`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists — same "advertised but never dispatched" bug class as
    tools #4/#6/#22/#25/#33/#44/#45/#46/#48/#50. Verified
    `CHAT_TOOLS.count("slack_send_message") == 1` directly before making
    any change.
Affected modules: app/agents/tools.py (schema re-export;
    `slack_send_message_h` now calls the shared function), app/agents/
    chat_agent.py (NEW real dispatch branch, gated behind a real
    confirmation dialog).
Affected registries: none — app/fleet/tool_manifest.py's
    "slack_send_message" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_slack_send_message_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/slack_send_message.md.
---------------------------------------------------------------------------

Finding: `chat_agent.py` had zero dispatch branch for
`slack_send_message` despite it being advertised via `CHAT_TOOLS` —
every real interactive call would have hit "[ERROR] Unknown tool".

The handler's own request-building logic was already safe: `text` is
JSON-encoded (`json.dumps({"text": text})`) and sent as the request
body via `urllib.request` — never string-interpolated into a shell
command or a URL, so there is no injection surface. The webhook URL is
read from the `SLACK_WEBHOOK_URL` environment variable, never accepted
as a tool argument (so there is no LLM-controlled-destination SSRF
surface either — the same trust boundary this initiative already
established for `LINEAR_API_KEY`/database URLs/other env-sourced
credentials). `channel` is deliberately unused, matching its own schema
description ("informational only — webhook targets one channel"): a
Slack incoming webhook is bound to exactly one channel at creation
time, and there is no way to override that per-message without a
different, more privileged API — this is a correct, intentional
contract, not a bug.

Fixed by adding a real `chat_agent.py` dispatch, delegating to a new
shared `send_slack_message()` function (the existing webhook-post logic,
moved here verbatim). Since posting a Slack message is a real external
write with a real cost/consequence, publicly visible to a real channel's
members — the same risk category as `create_pr`/`github_comment`/
`github_create_issue`/`linear_create_issue` — the new dispatch gates the
actual send behind a real `self._confirm()` dialog showing the message
text, mirroring those tools' established confirmation pattern.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

SLACK_SEND_MESSAGE_TOOL: dict[str, object] = {
    "name": "slack_send_message",
    "description": "Send a Slack message via webhook. Requires SLACK_WEBHOOK_URL env var.",
    "input_schema": {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel name (informational only — webhook targets one channel)",
            },
            "text": {
                "type": "string",
                "description": "Message text",
            },
        },
        "required": ["text"],
    },
}


def send_slack_message(webhook_url: str, text: str) -> str:
    """Posts `text` to the configured Slack webhook. Shared by both real
    call sites — `text` only ever reaches the JSON request body, never
    string-interpolated into a command or URL."""
    payload = json.dumps({"text": text}).encode()
    try:
        req = urllib.request.Request(
            webhook_url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
        return f"Slack message sent: {body}"
    except urllib.error.HTTPError as e:
        return f"[ERROR] Slack webhook {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return f"[ERROR] {e}"
