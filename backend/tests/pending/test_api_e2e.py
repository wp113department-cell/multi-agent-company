"""Full API end-to-end tests — require ANTHROPIC_API_KEY + real DATABASE_URL.

Run against the live-AI server (plan §N: isolated DB, throwaway repo,
economy mode, spend cap) with E2E_USER / E2E_PASS of a throwaway approver.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.pending.conftest import requires_all


@requires_all
class TestAPIE2E:
    """
    True E2E: HTTP client → FastAPI → real DB → real agents → verify results.
    Requires the FastAPI server to be running on http://localhost:8000.
    Start it with: cd backend && .venv/bin/uvicorn app.main:app --port 8000
    """

    _BASE = "http://localhost:8000"
    _opener: Any = None

    @classmethod
    def _client(cls) -> Any:
        """Every API route needs a session now: log in once, keep the cookie.
        Credentials of a throwaway approver: E2E_USER / E2E_PASS."""
        import http.cookiejar
        import json
        import os
        import urllib.request

        if cls._opener is None:
            user, pw = os.environ.get("E2E_USER"), os.environ.get("E2E_PASS")
            if not user or not pw:
                pytest.skip(
                    "set E2E_USER / E2E_PASS (a throwaway approver on the live server)"
                )
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            )
            req = urllib.request.Request(
                f"{cls._BASE}/api/auth/login",
                data=json.dumps({"username": user, "password": pw}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opener.open(req, timeout=10)
            cls._opener = opener
        return cls._opener

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:  # type: ignore[type-arg]
        import json
        import urllib.request

        req = urllib.request.Request(
            f"{self._BASE}{path}",
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        return json.loads(self._client().open(req, timeout=30).read())

    def _get(self, path: str) -> dict:  # type: ignore[type-arg]
        return self._call("GET", path)

    def _post(self, path: str, body: dict) -> dict:  # type: ignore[type-arg]
        return self._call("POST", path, body)

    def _patch(self, path: str, body: dict) -> dict:  # type: ignore[type-arg]
        return self._call("PATCH", path, body)

    def test_server_is_running(self) -> None:
        """Health check: FastAPI server must be running before other E2E tests."""
        result = self._get("/health")
        assert result.get("status") == "ok", f"Server not healthy: {result}"

    def test_create_task(self) -> None:
        """POST /api/tasks creates a task and returns id + status=pending."""
        result = self._post(
            "/api/tasks",
            {
                "title": "E2E test: add health endpoint",
                "description": "Add GET /health returning {status: ok}",
            },
        )
        assert result.get("id") is not None
        assert result.get("status") == "pending"

    def test_get_task(self) -> None:
        """GET /api/tasks/:id returns the created task."""
        created = self._post(
            "/api/tasks",
            {
                "title": "E2E get test",
                "description": "Fetch me back.",
            },
        )
        task_id = created["id"]

        fetched = self._get(f"/api/tasks/{task_id}")
        assert fetched["id"] == task_id
        assert fetched["title"] == "E2E get test"

    def test_list_tasks(self) -> None:
        """GET /api/tasks returns a list with at least the task we just created."""
        self._post("/api/tasks", {"title": "List test task", "description": "x"})
        result = self._get("/api/tasks")
        assert isinstance(result.get("tasks"), list)
        assert len(result["tasks"]) >= 1

    def test_run_triggers_pipeline_and_updates_status(self) -> None:
        """POST /api/tasks/:id/run fires the planning pipeline in the background."""
        import time

        task = self._post(
            "/api/tasks",
            {
                "title": "E2E run test: add subtract",
                # "backend"/"python" route by keyword rules: no LLM call needed
                "description": "Backend Python only: add subtract(a, b) to demo_module.py",
            },
        )
        task_id = task["id"]

        # Fire the smart router explicitly (the production default)
        self._post(f"/api/tasks/{task_id}/run", {"mode": "auto"})

        # Poll until status changes from pending (max 120s for real Claude call)
        deadline = time.time() + 120
        while time.time() < deadline:
            t = self._get(f"/api/tasks/{task_id}")
            if t["status"] not in ("pending", "planning"):
                break
            time.sleep(5)

        final = self._get(f"/api/tasks/{task_id}")
        # "blocked" used to pass too, i.e. a run that never planned anything.
        assert final["status"] == "ready_for_review", final
        assert final.get("plan"), "no plan was produced"

    def test_pipeline_state_populated(self) -> None:
        """GET /api/tasks/:id/pipeline returns pm_brief after pipeline completes."""
        import time

        task = self._post(
            "/api/tasks",
            {
                "title": "E2E pipeline state test",
                "description": "Add a /ping endpoint to FastAPI.",
            },
        )
        task_id = task["id"]
        # pm_brief only exists in the full pipeline (PM → Architect →
        # Decomposer); the smart-router default plans small tasks without it.
        self._post(f"/api/tasks/{task_id}/run", {"mode": "full"})

        deadline = time.time() + 300
        while time.time() < deadline:
            t = self._get(f"/api/tasks/{task_id}")
            if t["status"] not in ("pending", "planning"):
                break
            time.sleep(5)

        pipeline = self._get(f"/api/tasks/{task_id}/pipeline")
        assert (
            pipeline.get("pm_brief") is not None
        ), "Pipeline state missing pm_brief after run"

    def test_reject_task(self) -> None:
        """POST /api/tasks/:id/reject returns the task in rejected status."""
        task = self._post(
            "/api/tasks",
            {
                "title": "E2E reject test",
                "description": "This task will be rejected.",
            },
        )
        task_id = task["id"]

        # Manually move to ready_for_review to allow rejection
        self._patch(f"/api/tasks/{task_id}", {"status": "planning"})
        self._patch(f"/api/tasks/{task_id}", {"status": "ready_for_review"})

        result = self._post(
            f"/api/tasks/{task_id}/reject", {"feedback": "Not needed anymore."}
        )
        # The endpoint returns {"rejected": true, "task": {...}}.
        assert result.get("rejected") is True
        assert result["task"]["status"] == "rejected"

    def test_append_and_fetch_logs(self) -> None:
        """POST then GET /api/tasks/:id/logs round-trips a log entry."""
        task = self._post("/api/tasks", {"title": "Log test task", "description": "x"})
        task_id = task["id"]

        self._post(
            f"/api/tasks/{task_id}/logs",
            {
                "category": "planning",
                "message": "E2E log entry",
            },
        )

        logs = self._get(f"/api/tasks/{task_id}/logs")
        assert isinstance(logs.get("logs"), list)
        messages = [lg["message"] for lg in logs["logs"]]
        assert "E2E log entry" in messages
