"""inspect_openapi_spec tool #157 — tool_enhance.md productionization
pass (2026-09-14).

One real, empirically-verified finding, discovered by this tool's own
audit and found to be cross-cutting: a real SSRF-via-redirect bypass.
`inspect_openapi_spec` already called `_ssrf_denial_reason(url)`
before fetching, but only validated the initial URL — curl's own
`-L` auto-redirect-following let a malicious/compromised external
server redirect the request to a private/internal target, completely
unvalidated. Proved live against a real, public redirect service.

Investigating further revealed the SAME bypass in three
already-GREEN_FLAGGED sibling tools: `fetch_url` (#86),
`check_url_status` (#126), and `http_request` (#155) — see
`tests/test_ssrf_redirect_bypass_cross_cutting_fix.py` for their own
regression coverage of the same shared fix.

Fixed via `_ssrf_safe_curl_fetch()` (`app.agents.tool_security`),
which re-validates every redirect hop instead of using curl's `-L`.
"""

from __future__ import annotations

import asyncio
import json

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, inspect_openapi_spec, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.integrations.inspect_openapi_spec import (
    INSPECT_OPENAPI_SPEC_TOOL,
    inspect_openapi_spec_handler,
)

_SAMPLE_SPEC = json.dumps(
    {
        "openapi": "3.0.0",
        "info": {"title": "Sample", "version": "1.0"},
        "paths": {
            "/widgets": {
                "get": {"summary": "list widgets", "operationId": "listWidgets"}
            }
        },
    }
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_inspect_openapi_spec_hardening", repo_path=repo)
    return ChatAgent(session)


def test_inspect_openapi_spec_tool_schema() -> None:
    assert INSPECT_OPENAPI_SPEC_TOOL["name"] == "inspect_openapi_spec"
    assert INSPECT_OPENAPI_SPEC_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_inspect_openapi_spec_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("inspect_openapi_spec") == 1


def test_old_module_level_wrapper_still_importable_and_delegates() -> None:
    out = inspect_openapi_spec({"spec_text": _SAMPLE_SPEC})
    assert "listWidgets" in out


# ---------------------------------------------------------------------------
# Finding — SSRF-via-redirect bypass, proved live against the real network
# ---------------------------------------------------------------------------


class TestSsrfRedirectBypassBlocked:
    def test_direct_handler_redirect_to_cloud_metadata_blocked(self) -> None:
        out = inspect_openapi_spec_handler(
            {
                "url": "https://httpbin.org/redirect-to?url=http%3A%2F%2F169.254.169.254%2Fspec.json"
            }
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_redirect_to_cloud_metadata_blocked(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["inspect_openapi_spec"](
            {
                "url": "https://httpbin.org/redirect-to?url=http%3A%2F%2F169.254.169.254%2Fspec.json"
            }
        )
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_redirect_to_cloud_metadata_blocked(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "inspect_openapi_spec",
                {
                    "url": "https://httpbin.org/redirect-to?url=http%3A%2F%2F169.254.169.254%2Fspec.json"
                },
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out
        assert "Unknown tool" not in out

    def test_direct_url_to_private_address_still_blocked(self) -> None:
        out = inspect_openapi_spec_handler({"url": "http://169.254.169.254/spec.json"})
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — spec_text (no network) and both real
# access paths for a real external redirect
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_spec_text_json(self) -> None:
        out = inspect_openapi_spec_handler({"spec_text": _SAMPLE_SPEC})
        assert "listWidgets" in out
        assert '"endpoint_count": 1' in out

    def test_make_chat_handlers_spec_text_json(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["inspect_openapi_spec"]({"spec_text": _SAMPLE_SPEC})
        assert "listWidgets" in out

    def test_chat_agent_dispatch_spec_text_json(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "inspect_openapi_spec", {"spec_text": _SAMPLE_SPEC}
            )

        out = asyncio.run(_run())
        assert "listWidgets" in out

    def test_direct_handler_follows_legit_external_redirect(self) -> None:
        out = inspect_openapi_spec_handler(
            {
                "url": "https://httpbin.org/redirect-to?url=https%3A%2F%2Fexample.com"
            }
        )
        # example.com's HTML is not a valid OpenAPI spec, but the fetch
        # itself must have genuinely followed the redirect (no POLICY
        # DENIED) to reach the parse-failure stage.
        assert "POLICY DENIED" not in out

    def test_missing_input_still_errors(self) -> None:
        out = inspect_openapi_spec_handler({})
        assert "[ERROR]" in out
