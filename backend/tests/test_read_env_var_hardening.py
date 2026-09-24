"""read_env_var tool #173 — tool_enhance.md productionization pass
(2026-09-15).

Audit: unlike sibling tool #163's `list_env_vars` (names only), this
tool's whole purpose is returning a VALUE by name, so it was checked
specifically for real secret disclosure. CONFIRMED ALREADY SAFE: the
existing implementation already routes every value through
`_mask_secret_value()` before returning it. Proved live: a real
`sk-`-prefixed secret value was genuinely redacted, while ordinary
plain values pass through unchanged.

One real finding: advertised in CHAT_TOOLS but never dispatched by
chat_agent.py. Fixed via a new chat_agent.py dispatch branch
delegating to the shared `read_env_var_handler()`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.read_env_var import READ_ENV_VAR_TOOL, read_env_var_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_read_env_var_hardening", repo_path=repo)
    return ChatAgent(session)


def test_read_env_var_tool_schema() -> None:
    assert READ_ENV_VAR_TOOL["name"] == "read_env_var"
    assert READ_ENV_VAR_TOOL["input_schema"]["required"] == ["name"]  # type: ignore[index]


def test_read_env_var_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_env_var") == 1


# ---------------------------------------------------------------------------
# Audit — re-confirmation of the pre-existing secret-masking safety contract
# ---------------------------------------------------------------------------


class TestSecretMaskingPreserved:
    def test_secret_shaped_value_is_redacted(self, monkeypatch) -> None:
        monkeypatch.setenv("TD_RD_SECRET_KEY", "sk-realsecretvalue1234567890")
        out = read_env_var_handler({"name": "TD_RD_SECRET_KEY"})
        assert "REDACTED" in out
        assert "realsecretvalue" not in out

    def test_secret_shaped_name_is_redacted_even_with_plain_value(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("TD_RD_API_TOKEN", "plainlookingbutnamedasSECRETTOKEN12345")
        out = read_env_var_handler({"name": "TD_RD_API_TOKEN"})
        assert "REDACTED" in out

    def test_plain_value_passes_through_unchanged(self, monkeypatch) -> None:
        monkeypatch.setenv("TD_RD_PLAIN_VAR", "hello-world")
        out = read_env_var_handler({"name": "TD_RD_PLAIN_VAR"})
        assert out == "TD_RD_PLAIN_VAR=hello-world"

    def test_unset_var_reports_not_set(self) -> None:
        out = read_env_var_handler({"name": "TD_RD_DEFINITELY_NOT_SET_XYZ"})
        assert out == "TD_RD_DEFINITELY_NOT_SET_XYZ=[NOT SET]"


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("TD_RD_DISPATCH_PLAIN", "reachable-now")
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool(
                "read_env_var", {"name": "TD_RD_DISPATCH_PLAIN"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert out == "TD_RD_DISPATCH_PLAIN=reachable-now"

    def test_chat_agent_dispatch_masks_secrets_too(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("TD_RD_DISPATCH_SECRET", "sk-dispatchsecretvalue1234567890")
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool(
                "read_env_var", {"name": "TD_RD_DISPATCH_SECRET"}
            )

        out = asyncio.run(_run())
        assert "REDACTED" in out
        assert "dispatchsecretvalue" not in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_var(self, monkeypatch) -> None:
        monkeypatch.setenv("TD_RD_LEGIT", "value123")
        out = read_env_var_handler({"name": "TD_RD_LEGIT"})
        assert out == "TD_RD_LEGIT=value123"

    def test_make_chat_handlers_real_var(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("TD_RD_LEGIT2", "value456")
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_env_var"]({"name": "TD_RD_LEGIT2"})
        assert out == "TD_RD_LEGIT2=value456"
