"""read_image tool #174 — tool_enhance.md productionization pass
(2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`read_image_h` inside `make_chat_handlers`).

1. SEVERE worktree-boundary escape — an ARBITRARY IMAGE FILE READ
   oracle, worse than the usual class since the original code
   explicitly special-cased absolute paths to bypass `root` entirely
   (`Path(path) if Path(path).is_absolute() else root / path`).
   Proved live on BOTH the absolute-path and relative-traversal
   vectors: real image metadata and a base64 thumbnail of a file
   outside the worktree were genuinely disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `read_image_handler()` using
`check_path_in_worktree()` on `path`, with the absolute-path bypass
removed entirely (an absolute `path` is now validated exactly like a
relative one).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from PIL import Image

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.read_image import READ_IMAGE_TOOL, read_image_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_read_image_hardening", repo_path=repo)
    return ChatAgent(session)


def _make_png(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    Image.new("RGB", (10, 10), color=color).save(str(path))


def test_read_image_tool_schema() -> None:
    assert READ_IMAGE_TOOL["name"] == "read_image"
    assert READ_IMAGE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_image_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_image") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary image file read
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_img = outside / "secret.png"
        _make_png(secret_img)

        out = read_image_handler(worktree, str(worktree), {"path": str(secret_img)})
        assert "POLICY DENIED" in out
        assert "base64" not in out.lower()
        assert "Thumbnail" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        secret_img = tmp_path / "secret.png"
        _make_png(secret_img)

        out = read_image_handler(worktree, str(worktree), {"path": "../secret.png"})
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_img = outside / "secret.png"
        _make_png(secret_img)

        handlers = make_chat_handlers(str(worktree))
        out = handlers["read_image"]({"path": str(secret_img)})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_img = outside / "secret.png"
        _make_png(secret_img)

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool("read_image", {"path": str(secret_img)})

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        _make_png(tmp_path / "legit.png")
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("read_image", {"path": "legit.png"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "Format: PNG" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree image, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_image_relative_path(self, tmp_path: Path) -> None:
        _make_png(tmp_path / "photo.png")
        out = read_image_handler(tmp_path, str(tmp_path), {"path": "photo.png"})
        assert "10x10" in out
        assert "PNG" in out
        assert "Thumbnail" in out

    def test_direct_handler_real_image_absolute_in_worktree_path(
        self, tmp_path: Path
    ) -> None:
        img_path = tmp_path / "photo2.png"
        _make_png(img_path)
        out = read_image_handler(tmp_path, str(tmp_path), {"path": str(img_path)})
        assert "10x10" in out
        assert "PNG" in out

    def test_make_chat_handlers_real_image(self, tmp_path: Path) -> None:
        _make_png(tmp_path / "photo3.png")
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_image"]({"path": "photo3.png"})
        assert "PNG" in out

    def test_nonexistent_in_worktree_file_errors_gracefully(self, tmp_path: Path) -> None:
        out = read_image_handler(tmp_path, str(tmp_path), {"path": "nope.png"})
        assert "[ERROR]" in out

    def test_jpeg_format_detected(self, tmp_path: Path) -> None:
        img_path = tmp_path / "sample.jpg"
        Image.new("RGB", (200, 150), color=(0, 128, 255)).save(str(img_path), format="JPEG")
        out = read_image_handler(tmp_path, str(tmp_path), {"path": "sample.jpg"})
        assert "200x150" in out or "JPEG" in out
