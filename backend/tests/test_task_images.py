"""Day 16 — Image Input Pipeline.

Upload/list/get/delete endpoints tested via a real TestClient against a real
DB (matches the plan's own stated test scope: "Tests for the upload endpoint
+ base64 encoding (no real LLM call needed)"). run_agent_graph()'s
image-to-content-block construction tested with the Anthropic client mocked
at the SDK boundary (same pattern as test_day12_smoke_test.py).
"""

from __future__ import annotations

import asyncio
import base64
import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

# A real, valid 1x1 transparent PNG.
_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _create_task() -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.repository import create_task

    async def _run() -> int:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(session, "td image task", "desc")
                return task.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


class TestUploadTaskImages:
    def test_upload_and_round_trip(self) -> None:
        task_id = _create_task()
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/tasks/{task_id}/images",
                    files=[("files", ("shot.png", io.BytesIO(_MINIMAL_PNG), "image/png"))],
                )
                assert resp.status_code == 200, resp.text
                created = resp.json()["created"]
                assert len(created) == 1
                assert created[0]["mimeType"] == "image/png"
                image_id = created[0]["id"]

                list_resp = client.get(f"/api/tasks/{task_id}/images")
                assert list_resp.status_code == 200
                images = list_resp.json()["images"]
                assert len(images) == 1
                assert images[0]["id"] == image_id
                # Metadata response must never include the base64 blob.
                assert "base64Data" not in images[0]
                assert "base64_data" not in images[0]

                bytes_resp = client.get(f"/api/tasks/{task_id}/images/{image_id}")
                assert bytes_resp.status_code == 200
                assert bytes_resp.headers["content-type"] == "image/png"
                assert bytes_resp.content == _MINIMAL_PNG

                del_resp = client.delete(f"/api/tasks/{task_id}/images/{image_id}")
                assert del_resp.status_code == 200
                assert del_resp.json()["deleted"] is True

                list_resp2 = client.get(f"/api/tasks/{task_id}/images")
                assert list_resp2.json()["images"] == []
        finally:
            _cleanup(task_id)

    def test_rejects_unsupported_format(self) -> None:
        task_id = _create_task()
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/tasks/{task_id}/images",
                    files=[("files", ("doc.svg", io.BytesIO(b"<svg></svg>"), "image/svg+xml"))],
                )
                assert resp.status_code == 400
                assert "supported image format" in resp.json()["error"]["message"]
        finally:
            _cleanup(task_id)

    def test_rejects_oversized_file(self) -> None:
        from app.api.tasks import MAX_IMAGE_FILE_SIZE_BYTES

        task_id = _create_task()
        try:
            too_big = b"\x89PNG" + b"x" * (MAX_IMAGE_FILE_SIZE_BYTES + 1)
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/tasks/{task_id}/images",
                    files=[("files", ("big.png", io.BytesIO(too_big), "image/png"))],
                )
                assert resp.status_code == 400
                assert "5 MB" in resp.json()["error"]["message"]
        finally:
            _cleanup(task_id)

    def test_rejects_over_max_count(self) -> None:
        from app.api.tasks import MAX_IMAGES_PER_TASK

        task_id = _create_task()
        try:
            files = [
                ("files", (f"img{i}.png", io.BytesIO(_MINIMAL_PNG), "image/png"))
                for i in range(MAX_IMAGES_PER_TASK + 1)
            ]
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/images", files=files)
                assert resp.status_code == 400
                assert "Maximum" in resp.json()["error"]["message"]
        finally:
            _cleanup(task_id)

    def test_404_for_unknown_task(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks/999999999/images",
                files=[("files", ("shot.png", io.BytesIO(_MINIMAL_PNG), "image/png"))],
            )
            assert resp.status_code == 404

    def test_get_image_404_when_task_id_mismatches(self) -> None:
        task_id = _create_task()
        other_task_id = _create_task()
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/tasks/{task_id}/images",
                    files=[("files", ("shot.png", io.BytesIO(_MINIMAL_PNG), "image/png"))],
                )
                image_id = resp.json()["created"][0]["id"]

                mismatched = client.get(f"/api/tasks/{other_task_id}/images/{image_id}")
                assert mismatched.status_code == 404
        finally:
            _cleanup(task_id)
            _cleanup(other_task_id)


class TestRunAgentGraphImages:
    def test_images_become_multimodal_content_blocks(self) -> None:
        """The real point of this day's feature: when images are passed,
        the first user message sent to the Anthropic API is a real
        text+image content block list, not a plain string."""
        from app.agents.base_graph import VerificationConfig, run_agent_graph

        captured: dict = {}

        def _fake_create(**kwargs):
            captured.update(kwargs)
            return type(
                "R",
                (),
                {
                    "content": [type("B", (), {"type": "text", "text": "{}"})()],
                    "usage": type("U", (), {"input_tokens": 5, "output_tokens": 5})(),
                    "stop_reason": "end_turn",
                },
            )()

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.side_effect = _fake_create
            run_agent_graph(
                role_name="architect",
                model="claude-haiku",
                tools=[],
                tool_handlers={},
                verification_cfg=VerificationConfig(
                    set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
                ),
                initial_message="Scaffold a landing page matching this design.",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                max_turns=1,
                images=[{"media_type": "image/png", "data": "ZmFrZQ=="}],
            )

        sent_messages = captured["messages"]
        content = sent_messages[0]["content"]
        assert isinstance(content, list)
        assert content[0] == {
            "type": "text",
            "text": "Scaffold a landing page matching this design.",
        }
        assert content[1] == {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "ZmFrZQ=="},
        }

    def test_no_images_keeps_plain_string_content(self) -> None:
        """Backward compatibility: every existing caller that never passes
        images must see byte-for-byte the same content shape as before."""
        from app.agents.base_graph import VerificationConfig, run_agent_graph

        captured: dict = {}

        def _fake_create(**kwargs):
            captured.update(kwargs)
            return type(
                "R",
                (),
                {
                    "content": [type("B", (), {"type": "text", "text": "{}"})()],
                    "usage": type("U", (), {"input_tokens": 5, "output_tokens": 5})(),
                    "stop_reason": "end_turn",
                },
            )()

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.side_effect = _fake_create
            run_agent_graph(
                role_name="architect",
                model="claude-haiku",
                tools=[],
                tool_handlers={},
                verification_cfg=VerificationConfig(
                    set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
                ),
                initial_message="Plain text task, no images.",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                max_turns=1,
            )

        content = captured["messages"][0]["content"]
        assert content == "Plain text task, no images."


_SUBMITTED_STATE = {
    "messages": [],
    "verification": {},
    "result": {},
    "turns": 1,
    "submitted": True,
    "requires_human_approval": False,
    "tokens_in": 10,
    "tokens_out": 10,
}


class TestImagesForwardedToDevAgents:
    """Verifies the plan's own agent list (pm, architect, frontend_dev,
    reviewer — NOT backend_dev) is threaded correctly: run_frontend_dev()
    and run_reviewer() must forward images into run_agent_graph(); the
    wiring itself (not agent internals, already covered elsewhere)."""

    def test_run_frontend_dev_forwards_images(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.agents.frontend_dev import run_frontend_dev

        images = [{"media_type": "image/png", "data": "ZmFrZQ=="}]

        with patch(
            "app.agents.frontend_dev.run_agent_graph", return_value=_SUBMITTED_STATE
        ) as mock_graph, patch(
            "app.agents.frontend_dev.make_coder_handlers",
            return_value={"_patch_result": {"files_changed": ["apps/web/app/page.tsx"]}},
        ), patch("app.agents.frontend_dev._run_frontend_checks", return_value=None):
            files, error = run_frontend_dev(1, 1, "Build the page", "/tmp/wt", images=images)

        assert error is None
        assert files == ["apps/web/app/page.tsx"]
        assert mock_graph.call_args.kwargs["images"] == images

    def test_run_reviewer_forwards_images(self) -> None:
        from unittest.mock import patch

        from app.agents.reviewer import run_reviewer

        images = [{"media_type": "image/png", "data": "ZmFrZQ=="}]

        with patch(
            "app.agents.reviewer.run_agent_graph",
            return_value={**_SUBMITTED_STATE, "result": {"findings": []}},
        ) as mock_graph, patch(
            "app.agents.reviewer.make_reviewer_handlers", return_value={}
        ):
            run_reviewer(1, 1, "diff", "plan", images=images)

        assert mock_graph.call_args.kwargs["images"] == images


class TestPlanningPipelineImageFetch:
    def test_run_planning_pipeline_populates_images_from_db(self) -> None:
        """run_planning_pipeline() must fetch the task's images and put them
        in initial_state — verified by patching get_graph() to capture the
        state ainvoke() was actually called with, so this doesn't need a
        real multi-node LLM run."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.repository import create_task_image

        async def _run() -> None:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    from app.db.repository import create_task

                    task = await create_task(db, "img pipeline test", "desc")
                    await create_task_image(db, task.id, "ZmFrZQ==", "image/png", 0)

                    from unittest.mock import AsyncMock, MagicMock

                    from app.pipeline import graph as graph_module

                    captured_state = {}

                    async def _fake_ainvoke(state, config):
                        captured_state.update(state)
                        return {**state, "stage": "blocked", "error": "short-circuit"}

                    fake_graph = MagicMock()
                    fake_graph.ainvoke = AsyncMock(side_effect=_fake_ainvoke)

                    with patch.object(graph_module, "get_graph", return_value=fake_graph):
                        await graph_module.run_planning_pipeline(
                            task_id=task.id,
                            title="img pipeline test",
                            description="desc",
                            repo_path="/tmp",
                            db=db,
                        )

                    assert captured_state["images"] == [
                        {"media_type": "image/png", "data": "ZmFrZQ=="}
                    ]

                    from sqlalchemy import delete as sa_delete

                    from app.db.models import DevTask

                    await db.execute(sa_delete(DevTask).where(DevTask.id == task.id))
                    await db.commit()
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())
