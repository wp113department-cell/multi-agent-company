"""read_pdf tool #177 — tool_enhance.md productionization pass
(2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`read_pdf_h` inside `make_chat_handlers`) — same
class as sibling tool #174 (`read_image`), fixed the same day.

1. SEVERE worktree-boundary escape — an ARBITRARY PDF FILE READ
   oracle. The original code explicitly special-cased absolute paths
   to bypass `root` entirely. Proved live: a real PDF's text content
   (including a secret-shaped string) outside the worktree was
   genuinely extracted and returned.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `read_pdf_handler()` using
`check_path_in_worktree()` on `path`, with the absolute-path bypass
removed entirely.

Test PDFs are hand-crafted minimal valid PDF files (no external PDF-
writing library like reportlab is installed in this environment;
pdfplumber itself only reads) — a simple single-object-stream PDF
that pdfplumber can genuinely open and extract text from.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.read_pdf import READ_PDF_TOOL, read_pdf_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_read_pdf_hardening", repo_path=repo)
    return ChatAgent(session)


def _make_minimal_pdf(path: Path, text: str) -> None:
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET"
    content_bytes = content.encode("latin-1")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n",
        (f"<< /Length {len(content_bytes)} >>\nstream\n{content}\nendstream").encode(
            "latin-1"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    objects[3] = b"4 0 obj\n" + objects[3] + b"\nendobj\n"

    pdf = b"%PDF-1.4\n"
    offsets: list[int] = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode()
    path.write_bytes(pdf)


def test_read_pdf_tool_schema() -> None:
    assert READ_PDF_TOOL["name"] == "read_pdf"
    assert READ_PDF_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_pdf_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_pdf") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary PDF file read
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_pdf = outside / "secret.pdf"
        _make_minimal_pdf(secret_pdf, "TOPSECRET sk-secretpdf1234567890")

        out = read_pdf_handler(worktree, str(worktree), {"path": str(secret_pdf)})
        assert "POLICY DENIED" in out
        assert "TOPSECRET" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        secret_pdf = tmp_path / "secret.pdf"
        _make_minimal_pdf(secret_pdf, "TOPSECRET")

        out = read_pdf_handler(worktree, str(worktree), {"path": "../secret.pdf"})
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_pdf = outside / "secret.pdf"
        _make_minimal_pdf(secret_pdf, "TOPSECRET")

        handlers = make_chat_handlers(str(worktree))
        out = handlers["read_pdf"]({"path": str(secret_pdf)})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_pdf = outside / "secret.pdf"
        _make_minimal_pdf(secret_pdf, "TOPSECRET")

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool("read_pdf", {"path": str(secret_pdf)})

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        _make_minimal_pdf(tmp_path / "legit.pdf", "Hello Legit World")
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("read_pdf", {"path": "legit.pdf"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "Hello Legit World" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree PDF, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_pdf_relative_path(self, tmp_path: Path) -> None:
        _make_minimal_pdf(tmp_path / "doc.pdf", "Hello World")
        out = read_pdf_handler(tmp_path, str(tmp_path), {"path": "doc.pdf"})
        assert "Hello World" in out
        assert "Page 1" in out

    def test_direct_handler_real_pdf_absolute_in_worktree_path(
        self, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "doc2.pdf"
        _make_minimal_pdf(pdf_path, "Hello World Two")
        out = read_pdf_handler(tmp_path, str(tmp_path), {"path": str(pdf_path)})
        assert "Hello World Two" in out

    def test_make_chat_handlers_real_pdf(self, tmp_path: Path) -> None:
        _make_minimal_pdf(tmp_path / "doc3.pdf", "Hello World Three")
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_pdf"]({"path": "doc3.pdf"})
        assert "Hello World Three" in out

    def test_nonexistent_in_worktree_file_errors_gracefully(self, tmp_path: Path) -> None:
        out = read_pdf_handler(tmp_path, str(tmp_path), {"path": "nope.pdf"})
        assert "[ERROR]" in out

    def test_max_pages_respected(self, tmp_path: Path) -> None:
        _make_minimal_pdf(tmp_path / "doc4.pdf", "Only Page")
        out = read_pdf_handler(
            tmp_path, str(tmp_path), {"path": "doc4.pdf", "max_pages": 1}
        )
        assert "Only Page" in out
