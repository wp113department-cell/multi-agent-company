"""Sentry init test (gap-closure, files/GAPS_ALL_FILES_REPORT.md, 2026-07-23).

Proves AsyncioIntegration is really passed to sentry_sdk.init() — without it,
exceptions raised inside fire-and-forget asyncio.create_task() tasks (e.g.
db/repository.py's heartbeat_agent_run(), which has no try/except of its own
and is launched via asyncio.create_task() in api/agents.py) never reach
Sentry, only asyncio's own "Task exception was never retrieved" warning.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.main import _init_sentry


def _settings(dsn: str | None = "https://example@sentry.io/1") -> MagicMock:
    settings = MagicMock()
    settings.sentry_dsn = dsn
    settings.sentry_environment = "test"
    settings.sentry_traces_sample_rate = 0.0
    return settings


class TestInitSentry:
    def test_noop_when_no_dsn(self) -> None:
        with patch("sentry_sdk.init") as mock_init:
            _init_sentry(_settings(dsn=None))
        mock_init.assert_not_called()

    def test_includes_asyncio_integration(self) -> None:
        with patch("sentry_sdk.init") as mock_init:
            _init_sentry(_settings())

        mock_init.assert_called_once()
        integrations = mock_init.call_args.kwargs["integrations"]
        integration_types = {type(i) for i in integrations}
        assert AsyncioIntegration in integration_types
        assert FastApiIntegration in integration_types
        assert SqlalchemyIntegration in integration_types

    def test_init_failure_does_not_raise(self) -> None:
        with patch("sentry_sdk.init", side_effect=RuntimeError("boom")):
            _init_sentry(_settings())  # must not raise
