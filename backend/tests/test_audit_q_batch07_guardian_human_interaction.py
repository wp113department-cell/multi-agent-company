"""Tests for AUDIT_Q_BATCH07 (Guardian/Ranger Agents, Human Interaction,
Human Approval, Human Override) remediation, covering §12/§64/§13/§39/§103.

Covers:
  - §39: npm_install/pip_install now gated behind the same session-based
    confirmation pattern run_migration/seed_database already use.
  - §12/§64: monitoring_agent wired into the autonomous fleet scan loop
    (resource/health/Docker/git checks), and the fleet dashboard now
    surfaces which agents have no apply phase before a human approves.
  - §13: structured multi-choice options on the chat confirmation payload.
"""

from __future__ import annotations

import inspect
import subprocess
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agent_result import AgentResult
from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.config import get_settings
from app.db.models import EnhancementRequest
from app.models.chat import ChatSession


def _engine() -> object:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=str(path), capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(path), capture_output=True)


# ---------------------------------------------------------------------------
# §39 — npm_install / pip_install now confirmation-gated
# ---------------------------------------------------------------------------


class TestPackageInstallConfirmationGate:
    def test_npm_install_blocked_without_session(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))  # session defaults to None
        with patch("app.agents.tools.subprocess.run") as mock_run:
            result = handlers["npm_install"]({"directory": "."})
        assert "[BLOCKED]" in result
        mock_run.assert_not_called()

    def test_pip_install_blocked_without_session(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        with patch("app.agents.tools.subprocess.run") as mock_run:
            result = handlers["pip_install"]({"package": "requests"})
        assert "[BLOCKED]" in result
        mock_run.assert_not_called()

    def test_npm_install_runs_when_session_approves(self, tmp_path: Path) -> None:
        # A deterministic stand-in for asyncio.get_event_loop() — driving a
        # real global loop here is flaky under a full test-suite run (its
        # state depends on whatever other async tests ran earlier), exactly
        # mirroring run_migration_h's pre-existing, identically-shaped
        # is_running()/run_until_complete() branch a few functions above.
        # This fake loop makes the *outcome* (approved -> subprocess runs
        # exactly once) deterministic without depending on that global state.
        class _FakeLoop:
            def is_running(self) -> bool:
                return False

            def run_until_complete(self, coro: Any) -> Any:
                try:
                    coro.send(None)
                except StopIteration as e:
                    return e.value
                raise AssertionError("coroutine did not complete synchronously")

        session = MagicMock()
        session.request_confirmation = AsyncMock(return_value=True)
        handlers = make_chat_handlers(str(tmp_path), session=session)

        fake_proc = MagicMock(stdout="added 1 package", stderr="")
        with patch("app.agents.tools.subprocess.run", return_value=fake_proc) as mock_run, patch(
            "asyncio.get_event_loop", return_value=_FakeLoop()
        ):
            result = handlers["npm_install"]({"directory": "."})

        session.request_confirmation.assert_awaited_once()
        mock_run.assert_called_once()
        assert "added 1 package" in result

    def test_pip_install_denied_when_session_declines(self, tmp_path: Path) -> None:
        class _FakeLoop:
            def is_running(self) -> bool:
                return False

            def run_until_complete(self, coro: Any) -> Any:
                try:
                    coro.send(None)
                except StopIteration as e:
                    return e.value
                raise AssertionError("coroutine did not complete synchronously")

        session = MagicMock()
        session.request_confirmation = AsyncMock(return_value=False)
        handlers = make_chat_handlers(str(tmp_path), session=session)

        with patch("app.agents.tools.subprocess.run") as mock_run, patch(
            "asyncio.get_event_loop", return_value=_FakeLoop()
        ):
            result = handlers["pip_install"]({"package": "requests"})

        session.request_confirmation.assert_awaited_once()
        mock_run.assert_not_called()
        assert "[DENIED]" in result

    def test_npm_install_tool_manifest_documents_confirmation_gate(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        assert "confirmation" in TOOL_MANIFEST["npm_install"].notes.lower()
        assert "confirmation" in TOOL_MANIFEST["pip_install"].notes.lower()


# ---------------------------------------------------------------------------
# §12/§64 — Docker/git deterministic health pre-checks
# ---------------------------------------------------------------------------


class TestDockerHealthCheck:
    def test_returns_none_when_docker_unavailable(self) -> None:
        from app.fleet.docker_health import check_docker_containers

        with patch(
            "app.fleet.docker_health.subprocess.run", side_effect=FileNotFoundError()
        ):
            assert check_docker_containers() is None

    def test_returns_empty_list_when_all_healthy(self) -> None:
        from app.fleet.docker_health import check_docker_containers

        fake = MagicMock(
            returncode=0,
            stdout="CONTAINER ID   IMAGE   STATUS          NAMES\n"
            "abc123         app     Up 2 hours      app-1\n",
        )
        with patch("app.fleet.docker_health.subprocess.run", return_value=fake):
            assert check_docker_containers() == []

    def test_flags_unhealthy_container(self) -> None:
        from app.fleet.docker_health import check_docker_containers

        fake = MagicMock(
            returncode=0,
            stdout="CONTAINER ID   IMAGE   STATUS                    NAMES\n"
            "abc123         app     Up 2 hours (unhealthy)    app-1\n",
        )
        with patch("app.fleet.docker_health.subprocess.run", return_value=fake):
            issues = check_docker_containers()
        assert issues is not None
        assert len(issues) == 1
        assert "unhealthy" in issues[0].lower()


class TestGitWorktreeHealthCheck:
    def test_returns_none_when_not_a_git_repo(self, tmp_path: Path) -> None:
        from app.fleet.git_worktree_health import check_git_worktree

        assert check_git_worktree(str(tmp_path)) is None

    def test_clean_repo_reports_no_issues(self, tmp_path: Path) -> None:
        from app.fleet.git_worktree_health import check_git_worktree

        _init_git_repo(tmp_path)
        (tmp_path / "README.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True
        )
        assert check_git_worktree(str(tmp_path)) == []

    def test_flags_large_number_of_uncommitted_changes(self, tmp_path: Path) -> None:
        from app.fleet.git_worktree_health import check_git_worktree

        _init_git_repo(tmp_path)
        for i in range(20):
            (tmp_path / f"file_{i}.txt").write_text("x")
        issues = check_git_worktree(str(tmp_path), dirty_threshold=15)
        assert issues is not None
        assert any("uncommitted" in i for i in issues)

    def test_flags_branch_behind_upstream(self, tmp_path: Path) -> None:
        from app.fleet.git_worktree_health import check_git_worktree

        fake = MagicMock(
            returncode=0, stdout="## main...origin/main [behind 3]\n", stderr=""
        )
        with patch("app.fleet.git_worktree_health.subprocess.run", return_value=fake):
            issues = check_git_worktree(str(tmp_path))
        assert issues is not None
        assert any("behind" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# §12/§64 — monitoring_agent wired into the autonomous fleet scan loop
# ---------------------------------------------------------------------------


class TestMonitoringAgentScan:
    def test_scan_tools_excludes_old_submit_includes_enhancement_request(self) -> None:
        from app.agents.monitoring_agent import SCAN_TOOLS

        names = {t["name"] for t in SCAN_TOOLS}
        assert "submit_monitoring_report" not in names
        assert "submit_enhancement_request" in names
        assert "docker_ps" in names
        assert "docker_logs" in names

    def test_scan_tools_never_include_docker_write_tools(self) -> None:
        from app.agents.monitoring_agent import SCAN_TOOLS

        names = {t["name"] for t in SCAN_TOOLS}
        assert "docker_exec" not in names
        assert "docker_restart" not in names
        assert "docker_build" not in names
        assert "write_file" not in names

    def test_make_scan_handlers_includes_required_handlers(self, tmp_path: Path) -> None:
        from app.agents.monitoring_agent import make_scan_handlers

        handlers = make_scan_handlers(str(tmp_path), trace_id="test-trace")
        for name in (
            "cpu_usage",
            "memory_usage",
            "disk_usage",
            "health_check",
            "docker_ps",
            "docker_logs",
            "git_status",
            "submit_enhancement_request",
            "record_learning",
        ):
            assert name in handlers

    def test_run_monitoring_agent_scan_files_real_enhancement_request(self) -> None:
        """End-to-end (mocked LLM graph, real DB): the scan's own
        submit_enhancement_request handler, when actually invoked, writes a
        real EnhancementRequest row with agent_name='monitoring_agent'."""
        from app.agents.monitoring_agent import run_monitoring_agent_scan

        suffix = uuid.uuid4().hex[:8]
        title = f"batch07 real infra finding {suffix}"

        def _fake_run_agent_graph(**kwargs: object) -> dict[str, object]:
            handlers = kwargs["tool_handlers"]
            assert isinstance(handlers, dict)
            handlers["submit_enhancement_request"](
                {
                    "title": title,
                    "description": "disk usage at 97% on /",
                    "category": "performance",
                    "priority": "medium",
                    "evidence": {"disk_used_pct": 97},
                }
            )
            return {
                "result": {},
                "verification": {"scan_ran": True},
                "tokens_in": 10,
                "tokens_out": 5,
                "submitted": True,
            }

        settings = MagicMock()
        settings.model_coder = "sonnet-test"
        settings.model_router = "haiku-test"
        settings.fleet_self_repo_path = "."

        async def _verify_and_cleanup() -> EnhancementRequest:
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    row = (
                        await session.execute(
                            select(EnhancementRequest).where(
                                EnhancementRequest.title == title
                            )
                        )
                    ).scalar_one()
                    await session.execute(
                        delete(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                    await session.commit()
                    return row
            finally:
                await engine.dispose()

        try:
            with patch(
                "app.agents.monitoring_agent.run_agent_graph",
                side_effect=_fake_run_agent_graph,
            ), patch(
                "app.agents.monitoring_agent.get_settings", return_value=settings
            ), patch(
                "app.fleet.docker_health.check_docker_containers", return_value=None
            ), patch(
                "app.fleet.git_worktree_health.check_git_worktree", return_value=None
            ):
                result = run_monitoring_agent_scan(trace_id=f"batch07-{suffix}")

            assert isinstance(result, AgentResult)
            assert result.verified is True

            row = asyncio.run(_verify_and_cleanup())
            assert row.category == "performance"
            assert row.agent_name == "monitoring_agent"
            assert row.status == "pending"
        finally:

            async def _force_cleanup() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        await session.execute(
                            delete(EnhancementRequest).where(
                                EnhancementRequest.title == title
                            )
                        )
                        await session.commit()
                finally:
                    await engine.dispose()

            asyncio.run(_force_cleanup())

    def test_fleet_agents_scan_loop_includes_monitoring_agent(self) -> None:
        """Verify-real-callers guard: the scan must actually be wired into
        the real periodic loop, not just exist as an orphaned function."""
        import app.main as main_module

        source = inspect.getsource(main_module._fleet_agents_scan_loop)
        assert "monitoring_agent" in source
        assert "run_monitoring_agent_scan" in source


# ---------------------------------------------------------------------------
# §13 — ask_human_to_choose: real structured multi-choice + recommendation
# ---------------------------------------------------------------------------


class _FakeToolUseStream:
    """Minimal fake for `async with client.messages.stream(...) as stream`
    that ends the turn with a single tool_use block. Mirrors
    test_phase52_chat_graph_interrupt.py's own helper exactly."""

    def __init__(self, tool_name: str, tool_input: dict, tool_id: str) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self._tool_id = tool_id

    async def __aenter__(self) -> "_FakeToolUseStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeToolUseStream":
        return self

    async def __anext__(self) -> None:
        raise StopAsyncIteration

    async def get_final_message(self) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.id = self._tool_id
        block.name = self._tool_name
        block.input = self._tool_input
        final = MagicMock()
        final.stop_reason = "tool_use"
        final.content = [block]
        final.usage = MagicMock(input_tokens=10, output_tokens=5)
        return final


class _FakeTextStream:
    """Minimal fake for a plain end_turn text response — no tool calls."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> "_FakeTextStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeTextStream":
        return self

    async def __anext__(self) -> None:
        raise StopAsyncIteration

    async def get_final_message(self) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        final = MagicMock()
        final.stop_reason = "end_turn"
        final.content = [block]
        final.usage = MagicMock(input_tokens=10, output_tokens=5)
        return final


def _patched_agent(agent: ChatAgent, responses: list):
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object):
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    return (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    )


class TestAskHumanToChoose:
    def test_tool_registered_in_chat_tools(self) -> None:
        names = {t["name"] for t in CHAT_TOOLS}
        assert "ask_human_to_choose" in names

    @pytest.mark.asyncio
    async def test_full_pause_resume_cycle_with_selection(self) -> None:
        session = ChatSession(session_id="batch07_choose_1", repo_path="/tmp/repo")
        agent = ChatAgent(session)
        responses = [
            _FakeToolUseStream(
                "ask_human_to_choose",
                {
                    "question": "Which environment should this deploy to?",
                    "options": [
                        {"id": "staging", "label": "Staging"},
                        {"id": "prod", "label": "Production"},
                    ],
                    "recommended_option": "staging",
                },
                tool_id="toolu_choose1",
            ),
            _FakeTextStream("Got it, using staging."),
        ]
        p1, p2, p3 = _patched_agent(agent, responses)

        with p1, p2, p3:
            await agent.run("where should this deploy?")

            config = {"configurable": {"thread_id": session.session_id}}
            snapshot = await agent._graph.aget_state(config)
            interrupt_value = next(
                i.value for task in snapshot.tasks for i in task.interrupts
            )
            assert interrupt_value["options"][0]["id"] == "staging"
            assert interrupt_value["recommended"] == "staging"

            resumed = await agent.resume("toolu_choose1", True, selected="staging")
            assert resumed is True

        tool_result_texts = [
            block.get("content", "")
            for msg in session.history
            if msg.get("role") == "user"
            for block in (msg.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        assert any("staging" in str(t) for t in tool_result_texts)

    @pytest.mark.asyncio
    async def test_declining_to_choose_is_cancelled_not_a_random_pick(self) -> None:
        session = ChatSession(session_id="batch07_choose_2", repo_path="/tmp/repo")
        agent = ChatAgent(session)
        responses = [
            _FakeToolUseStream(
                "ask_human_to_choose",
                {
                    "question": "Which environment?",
                    "options": [
                        {"id": "staging", "label": "Staging"},
                        {"id": "prod", "label": "Production"},
                    ],
                },
                tool_id="toolu_choose2",
            ),
            _FakeTextStream("Understood, holding off."),
        ]
        p1, p2, p3 = _patched_agent(agent, responses)

        with p1, p2, p3:
            await agent.run("where should this deploy?")
            resumed = await agent.resume("toolu_choose2", False)
            assert resumed is True

        tool_result_texts = [
            block.get("content", "")
            for msg in session.history
            if msg.get("role") == "user"
            for block in (msg.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        assert any("CANCELLED" in str(t) for t in tool_result_texts)

    @pytest.mark.asyncio
    async def test_selected_id_not_in_options_is_ignored(self) -> None:
        """A malformed/stale resume payload (selected id not among the real
        options) must not be trusted as a valid choice."""
        session = ChatSession(session_id="batch07_choose_3", repo_path="/tmp/repo")
        agent = ChatAgent(session)
        responses = [
            _FakeToolUseStream(
                "ask_human_to_choose",
                {
                    "question": "Which environment?",
                    "options": [
                        {"id": "staging", "label": "Staging"},
                        {"id": "prod", "label": "Production"},
                    ],
                },
                tool_id="toolu_choose3",
            ),
            _FakeTextStream("Understood."),
        ]
        p1, p2, p3 = _patched_agent(agent, responses)

        with p1, p2, p3:
            await agent.run("where should this deploy?")
            resumed = await agent.resume("toolu_choose3", True, selected="not-a-real-option")
            assert resumed is True

        tool_result_texts = [
            block.get("content", "")
            for msg in session.history
            if msg.get("role") == "user"
            for block in (msg.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        assert any("CANCELLED" in str(t) for t in tool_result_texts)


# ---------------------------------------------------------------------------
# §13 — request_clarification: structured options for plain worker agents
# ---------------------------------------------------------------------------


class TestRequestClarificationOptions:
    def test_schema_accepts_options_and_recommended_option(self) -> None:
        from app.agents.tools import REQUEST_CLARIFICATION_TOOL

        props = REQUEST_CLARIFICATION_TOOL["input_schema"]["properties"]
        assert "options" in props
        assert "recommended_option" in props

    def test_handler_threads_options_into_recorded_details(self) -> None:
        from app.agents.tools import make_request_clarification_handler

        handler = make_request_clarification_handler("test_agent", task_id="1")
        with patch("app.fleet.approval_gate.request_human_input") as mock_record:
            handler(
                {
                    "question": "Which config?",
                    "options": [{"id": "a", "label": "Option A"}],
                    "recommended_option": "a",
                }
            )
        _, kwargs = mock_record.call_args
        assert kwargs["details"]["options"] == [{"id": "a", "label": "Option A"}]
        assert kwargs["details"]["recommended_option"] == "a"


# ---------------------------------------------------------------------------
# §39 — "Don't ask again this session"
# ---------------------------------------------------------------------------


def _patched_agent_with_git(agent: ChatAgent, responses: list, git_call_count: dict):
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object):
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    def fake_git(args: list, cwd: str, timeout: int = 30) -> str:
        git_call_count["n"] += 1
        return "pushed ok"

    return (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch("app.agents.chat_agent._git", side_effect=fake_git),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    )


class TestRememberConfirmationChoice:
    def test_chat_session_defaults_to_no_remembered_confirmations(self) -> None:
        session = ChatSession(session_id="batch07_remember_default", repo_path="/tmp")
        assert session.remembered_confirmations == set()

    @pytest.mark.asyncio
    async def test_remembered_choice_skips_future_pause_for_same_tool(self) -> None:
        session = ChatSession(session_id="batch07_remember_1", repo_path="/tmp/repo")
        agent = ChatAgent(session)
        git_call_count = {"n": 0}
        responses = [
            _FakeToolUseStream("git_push", {"branch": "main"}, tool_id="toolu_r1"),
            _FakeTextStream("Pushed."),
            _FakeToolUseStream("git_push", {"branch": "main"}, tool_id="toolu_r2"),
            _FakeTextStream("Pushed again."),
        ]
        p1, p2, p3, p4 = _patched_agent_with_git(agent, responses, git_call_count)

        with p1, p2, p3, p4:
            await agent.run("push")
            resumed = await agent.resume("toolu_r1", True, remember=True)
            assert resumed is True
            assert git_call_count["n"] == 1
            assert "git_push" in session.remembered_confirmations

            # Second turn, same tool: must complete in run() alone, no
            # resume() needed — the whole point of "remember".
            await agent.run("push again")
            assert git_call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_remember_does_not_leak_across_different_tools(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "foo.txt").write_text("bye")
        session = ChatSession(session_id="batch07_remember_2", repo_path=str(tmp_path))
        agent = ChatAgent(session)
        session.remembered_confirmations.add("git_push")

        responses = [
            _FakeToolUseStream(
                "delete_file", {"path": "foo.txt"}, tool_id="toolu_r3"
            ),
            _FakeTextStream("Deleted."),
        ]
        p1, p2, p3 = _patched_agent(agent, responses)

        with p1, p2, p3:
            await agent.run("delete foo.txt")

            config = {"configurable": {"thread_id": session.session_id}}
            snapshot = await agent._graph.aget_state(config)
            # Still paused — remembering git_push must not auto-approve
            # an unrelated tool (delete_file).
            assert any(task.interrupts for task in snapshot.tasks)

    def test_confirm_action_request_remember_defaults_false(self) -> None:
        from app.api.chat import ConfirmActionRequest

        body = ConfirmActionRequest(action_id="x", approved=True)
        assert body.remember is False
