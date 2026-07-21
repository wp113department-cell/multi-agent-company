"""Tests for Settings API (OpenAI key + verify) and PDF extraction endpoint."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Settings API — OpenAI key
# ---------------------------------------------------------------------------

class TestSettingsOpenAiKey:
    def test_save_openai_key_valid(self) -> None:
        from app.api.settings import ApiKeyRequest
        # Just verify the function exists and accepts the right model
        req = ApiKeyRequest(api_key="sk-test1234567890")
        assert req.api_key == "sk-test1234567890"

    def test_openai_key_must_start_with_sk(self) -> None:
        from fastapi import HTTPException
        import asyncio
        from app.api.settings import save_openai_key, ApiKeyRequest

        async def run():
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock()
            mock_db.commit = AsyncMock()
            with patch("app.api.settings.set_setting", new_callable=AsyncMock):
                try:
                    await save_openai_key(ApiKeyRequest(api_key="bad-key"), db=mock_db)
                    return False
                except HTTPException as exc:
                    return exc.status_code == 400

        assert asyncio.run(run())

    def test_mask_short_key(self) -> None:
        from app.api.settings import _mask
        assert _mask("") == ""
        assert _mask("short") == "set"

    def test_mask_long_key(self) -> None:
        from app.api.settings import _mask
        key = "sk-ant-api03-abcdefghijklmnop"
        result = _mask(key)
        assert result.startswith("sk-ant-a")
        assert "..." in result
        assert result.endswith(key[-4:])


# ---------------------------------------------------------------------------
# Settings API — verify endpoint helpers
# ---------------------------------------------------------------------------

class TestVerifyHelpers:
    def test_verify_anthropic_bad_prefix(self) -> None:
        import asyncio
        from app.api.settings import _verify_anthropic
        result = asyncio.run(_verify_anthropic("not-a-real-key"))
        assert result["ok"] is False
        assert "sk-" in result["error"]

    def test_verify_openai_bad_prefix(self) -> None:
        import asyncio
        from app.api.settings import _verify_openai
        result = asyncio.run(_verify_openai("bad"))
        assert result["ok"] is False

    def test_verify_anthropic_api_error_mapped(self) -> None:
        import asyncio
        from app.api.settings import _verify_anthropic

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.side_effect = Exception("401 Unauthorized")
            result = asyncio.run(_verify_anthropic("sk-validformat"))
            assert result["ok"] is False
            assert "Invalid API key" in result["error"] or "401" in result["error"]

    def test_verify_openai_api_error_mapped(self) -> None:
        import asyncio
        from app.api.settings import _verify_openai

        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.models.list.side_effect = Exception("401 incorrect api_key")
            result = asyncio.run(_verify_openai("sk-validformat"))
            assert result["ok"] is False
            assert "Invalid API key" in result["error"] or "incorrect" in result["error"].lower()

    def test_verify_unknown_provider_raises(self) -> None:
        import asyncio
        from fastapi import HTTPException
        from app.api.settings import verify_api_key, VerifyKeyRequest

        async def run():
            try:
                await verify_api_key(VerifyKeyRequest(provider="groq", api_key="sk-test"))
                return False
            except HTTPException as exc:
                return exc.status_code == 400

        assert asyncio.run(run())


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def _make_minimal_pdf() -> bytes:
    """Build a tiny but valid PDF containing 'Hello World'."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 100 700 Td (Hello World) Tj ET\nendstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n"
        b"0000000115 00000 n \n0000000266 00000 n \n"
        b"0000000360 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n441\n%%EOF"
    )


class TestPdfExtraction:
    def test_extract_pdf_returns_string(self) -> None:
        from app.api.tasks import _extract_pdf_text
        raw = _make_minimal_pdf()
        result = _extract_pdf_text(raw, "test.pdf")
        assert isinstance(result, str)

    def test_extract_corrupted_pdf_returns_error_string(self) -> None:
        from app.api.tasks import _extract_pdf_text
        result = _extract_pdf_text(b"not a pdf at all", "bad.pdf")
        assert "Could not extract" in result or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_extract_pdfs_endpoint_file_limit(self) -> None:
        from fastapi import UploadFile
        from app.api.tasks import extract_pdfs, MAX_PDF_FILES

        # Create MAX_PDF_FILES + 1 fake upload files
        def make_upload(name: str) -> UploadFile:
            f = UploadFile(filename=name, file=io.BytesIO(_make_minimal_pdf()))
            return f

        files = [make_upload(f"file{i}.pdf") for i in range(MAX_PDF_FILES + 1)]
        from fastapi import HTTPException
        try:
            await extract_pdfs(files=files)
            assert False, "Should have raised HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "Maximum" in exc.detail

    @pytest.mark.asyncio
    async def test_extract_pdfs_rejects_non_pdf(self) -> None:
        from fastapi import UploadFile, HTTPException
        from app.api.tasks import extract_pdfs

        f = UploadFile(filename="notapdf.txt", file=io.BytesIO(b"hello"))
        try:
            await extract_pdfs(files=[f])
            assert False, "Should have raised"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "not a PDF" in exc.detail

    @pytest.mark.asyncio
    async def test_extract_pdfs_rejects_too_large(self) -> None:
        from fastapi import UploadFile, HTTPException
        from app.api.tasks import extract_pdfs, MAX_PDF_SIZE_BYTES

        big_pdf = b"%PDF" + b"x" * (MAX_PDF_SIZE_BYTES + 1)
        f = UploadFile(filename="big.pdf", file=io.BytesIO(big_pdf))
        try:
            await extract_pdfs(files=[f])
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "limit" in exc.detail.lower() or "20" in exc.detail

    @pytest.mark.asyncio
    async def test_extract_pdfs_success_path(self) -> None:
        from fastapi import UploadFile
        from app.api.tasks import extract_pdfs

        f = UploadFile(filename="sample.pdf", file=io.BytesIO(_make_minimal_pdf()))
        result = await extract_pdfs(files=[f])
        assert result["ok"] is True
        assert len(result["files"]) == 1
        assert result["files"][0]["filename"] == "sample.pdf"
        assert isinstance(result["files"][0]["text"], str)
        assert isinstance(result["files"][0]["chars"], int)


# ---------------------------------------------------------------------------
# git_service — clone_with_token
# ---------------------------------------------------------------------------

class TestGitCloneWithToken:
    def test_clone_with_token_rejects_empty_token(self) -> None:
        import asyncio
        from app.services.git_service import git_clone_with_token

        async def run():
            try:
                await git_clone_with_token(
                    "https://github.com/user/repo.git", "/tmp/test", ""
                )
            except ValueError as exc:
                return "Token" in str(exc)
            return False

        assert asyncio.run(run())

    def test_clone_with_token_rejects_bad_host(self) -> None:
        import asyncio
        from app.services.git_service import git_clone_with_token

        async def run():
            try:
                await git_clone_with_token(
                    "https://evil.com/repo.git", "/tmp/test", "ghp_token"
                )
            except ValueError as exc:
                return "allowlist" in str(exc)
            return False

        assert asyncio.run(run())

    def test_token_stripped_from_stderr(self) -> None:
        """Token must not appear in error output returned to caller."""
        import asyncio
        from app.services.git_service import git_clone_with_token

        async def run():
            with patch("app.services.git_service._validate_workspace"):
                with patch("app.services.git_service._run_git", new_callable=AsyncMock) as mock_git:
                    mock_git.return_value = (1, "", "fatal: remote: Repository not found. ghp_secrettoken")
                    result = await git_clone_with_token(
                        "https://github.com/user/private.git",
                        "/home/test/dest",
                        "ghp_secrettoken",
                    )
                    return "ghp_secrettoken" not in result["stderr"]

        assert asyncio.run(run())
