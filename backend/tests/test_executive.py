"""Tests for Executive Agent."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.executive import _parse_json, run_executive


def _make_final_state(text: str, tokens_in: int = 100, tokens_out: int = 50) -> dict[str, Any]:
    """Build a fake AgentRunState with the given assistant text in messages."""
    return {
        "messages": [{"role": "assistant", "content": text}],
        "verification": {},
        "result": {},
        "turns": 1,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


class TestParseJson:
    def test_clean_json(self) -> None:
        text = '{"epics": [], "summary": "hello"}'
        result = _parse_json(text)
        assert result["summary"] == "hello"

    def test_json_with_surrounding_prose(self) -> None:
        text = 'Here is my plan: {"epics": [{"title": "T"}], "summary": "ok"} done.'
        result = _parse_json(text)
        assert result["epics"][0]["title"] == "T"

    def test_no_json_raises(self) -> None:
        with pytest.raises(ValueError, match="No JSON object found"):
            _parse_json("no json here")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_json("{bad json")


class TestRunExecutive:
    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        db = AsyncMock()
        db.flush = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        return db

    def _make_agent_response(self, epics: list[dict], summary: str) -> str:
        return json.dumps({"epics": epics, "summary": summary})

    @patch("app.agents.executive.run_agent_graph")
    @patch("app.agents.executive.get_settings")
    async def test_creates_goal_and_epics(
        self, mock_settings: MagicMock, mock_run: MagicMock, mock_db: AsyncMock
    ) -> None:
        mock_settings.return_value = SimpleNamespace(
            model_router="claude-haiku-4-5-20251001",
            executive_max_epics_per_goal=5,
        )
        mock_run.return_value = _make_final_state(
            self._make_agent_response(
                [{"title": "Epic A", "description": "desc A"},
                 {"title": "Epic B", "description": "desc B"}],
                "Two things to build.",
            )
        )

        goal_id, epic_ids, error = await run_executive("Build a dashboard", mock_db)

        assert error is None
        assert len(goal_id) == 36  # UUID
        assert len(epic_ids) == 2
        assert mock_db.flush.called

    @patch("app.agents.executive.run_agent_graph")
    @patch("app.agents.executive.get_settings")
    async def test_caps_epics_at_max(
        self, mock_settings: MagicMock, mock_run: MagicMock, mock_db: AsyncMock
    ) -> None:
        mock_settings.return_value = SimpleNamespace(
            model_router="claude-haiku-4-5-20251001",
            executive_max_epics_per_goal=2,
        )
        mock_run.return_value = _make_final_state(
            self._make_agent_response(
                [{"title": f"E{i}", "description": "d"} for i in range(5)],
                "summary",
            )
        )

        _, epic_ids, error = await run_executive("Build lots", mock_db)
        assert error is None
        assert len(epic_ids) == 2

    @patch("app.agents.executive.run_agent_graph")
    @patch("app.agents.executive.get_settings")
    async def test_agent_error_returns_error(
        self, mock_settings: MagicMock, mock_run: MagicMock, mock_db: AsyncMock
    ) -> None:
        mock_settings.return_value = SimpleNamespace(
            model_router="claude-haiku-4-5-20251001",
            executive_max_epics_per_goal=5,
        )
        mock_run.side_effect = RuntimeError("API timeout")

        _, epic_ids, error = await run_executive("something", mock_db)
        assert error is not None
        assert "API timeout" in error
        assert epic_ids == []

    @patch("app.agents.executive.run_agent_graph")
    @patch("app.agents.executive.get_settings")
    async def test_empty_epics_returns_error(
        self, mock_settings: MagicMock, mock_run: MagicMock, mock_db: AsyncMock
    ) -> None:
        mock_settings.return_value = SimpleNamespace(
            model_router="claude-haiku-4-5-20251001",
            executive_max_epics_per_goal=5,
        )
        mock_run.return_value = _make_final_state('{"epics": [], "summary": "nothing"}')

        _, epic_ids, error = await run_executive("vague thing", mock_db)
        assert error is not None
        assert "no epics" in error.lower()

    @patch("app.agents.executive.run_agent_graph")
    @patch("app.agents.executive.get_settings")
    async def test_bad_json_returns_error(
        self, mock_settings: MagicMock, mock_run: MagicMock, mock_db: AsyncMock
    ) -> None:
        mock_settings.return_value = SimpleNamespace(
            model_router="claude-haiku-4-5-20251001",
            executive_max_epics_per_goal=5,
        )
        mock_run.return_value = _make_final_state("not json at all")

        _, epic_ids, error = await run_executive("something", mock_db)
        assert error is not None
        assert "JSON" in error
