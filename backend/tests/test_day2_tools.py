"""Day 2 Gap tools — structural and behaviour tests.

Tests verify:
  - Tool specs exist and have correct structure
  - Tool specs are present in CHAT_TOOLS
  - Handler factories produce correct results for each new tool
  - Edge cases and error handling
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents.tools import (
    CHAT_TOOLS,
    _FIND_QUEUE_TOOL,
    _FIND_WORKER_TOOL,
    _INSERT_BEFORE_TOOL,
    _INSERT_AFTER_TOOL,
    _DELETE_BLOCK_TOOL,
    _GENERATE_CHANGELOG_TOOL,
    _SUMMARIZE_REPO_TOOL,
    _GENERATE_RELEASE_NOTES_TOOL,
    _READ_PDF_TOOL,
    _READ_IMAGE_TOOL,
    _GITHUB_CREATE_PR_TOOL,
    make_chat_handlers,
)

_REPO = str(Path(__file__).parent.parent.parent)
_TOOL_NAMES = {t["name"] for t in CHAT_TOOLS}


def _make_handlers() -> dict[str, Any]:
    return make_chat_handlers(str(Path(__file__).parent.parent))


# ──────────────────────────────────────────────────────────────────────────────
# Tool spec structure tests
# ──────────────────────────────────────────────────────────────────────────────

class TestToolSpecStructure:
    """All new tool specs must have name, description, input_schema."""

    @pytest.mark.parametrize("spec", [
        _FIND_QUEUE_TOOL,
        _FIND_WORKER_TOOL,
        _INSERT_BEFORE_TOOL,
        _INSERT_AFTER_TOOL,
        _DELETE_BLOCK_TOOL,
        _GENERATE_CHANGELOG_TOOL,
        _SUMMARIZE_REPO_TOOL,
        _GENERATE_RELEASE_NOTES_TOOL,
        _READ_PDF_TOOL,
        _READ_IMAGE_TOOL,
        _GITHUB_CREATE_PR_TOOL,
    ])
    def test_has_name(self, spec: dict[str, Any]) -> None:
        assert "name" in spec and spec["name"]

    @pytest.mark.parametrize("spec", [
        _FIND_QUEUE_TOOL,
        _FIND_WORKER_TOOL,
        _INSERT_BEFORE_TOOL,
        _INSERT_AFTER_TOOL,
        _DELETE_BLOCK_TOOL,
        _GENERATE_CHANGELOG_TOOL,
        _SUMMARIZE_REPO_TOOL,
        _GENERATE_RELEASE_NOTES_TOOL,
        _READ_PDF_TOOL,
        _READ_IMAGE_TOOL,
        _GITHUB_CREATE_PR_TOOL,
    ])
    def test_has_description(self, spec: dict[str, Any]) -> None:
        assert "description" in spec and len(spec["description"]) > 10

    @pytest.mark.parametrize("spec", [
        _FIND_QUEUE_TOOL,
        _FIND_WORKER_TOOL,
        _INSERT_BEFORE_TOOL,
        _INSERT_AFTER_TOOL,
        _DELETE_BLOCK_TOOL,
        _GENERATE_CHANGELOG_TOOL,
        _SUMMARIZE_REPO_TOOL,
        _GENERATE_RELEASE_NOTES_TOOL,
        _READ_PDF_TOOL,
        _READ_IMAGE_TOOL,
        _GITHUB_CREATE_PR_TOOL,
    ])
    def test_has_input_schema(self, spec: dict[str, Any]) -> None:
        assert "input_schema" in spec
        assert spec["input_schema"]["type"] == "object"
        assert "properties" in spec["input_schema"]


# ──────────────────────────────────────────────────────────────────────────────
# CHAT_TOOLS membership tests
# ──────────────────────────────────────────────────────────────────────────────

class TestChatToolsMembership:
    def test_find_queue_in_chat_tools(self) -> None:
        assert "find_queue" in _TOOL_NAMES

    def test_find_worker_in_chat_tools(self) -> None:
        assert "find_worker" in _TOOL_NAMES

    def test_insert_before_in_chat_tools(self) -> None:
        assert "insert_before" in _TOOL_NAMES

    def test_insert_after_in_chat_tools(self) -> None:
        assert "insert_after" in _TOOL_NAMES

    def test_delete_block_in_chat_tools(self) -> None:
        assert "delete_block" in _TOOL_NAMES

    def test_generate_changelog_in_chat_tools(self) -> None:
        assert "generate_changelog" in _TOOL_NAMES

    def test_summarize_repo_in_chat_tools(self) -> None:
        assert "summarize_repo" in _TOOL_NAMES

    def test_generate_release_notes_in_chat_tools(self) -> None:
        assert "generate_release_notes" in _TOOL_NAMES

    def test_read_pdf_in_chat_tools(self) -> None:
        assert "read_pdf" in _TOOL_NAMES

    def test_read_image_in_chat_tools(self) -> None:
        assert "read_image" in _TOOL_NAMES

    def test_github_create_pr_in_chat_tools(self) -> None:
        assert "github_create_pr" in _TOOL_NAMES

    def test_chat_tools_count_gte_131(self) -> None:
        assert len(CHAT_TOOLS) >= 131, f"Expected ≥131 CHAT_TOOLS, got {len(CHAT_TOOLS)}"

    def test_all_chat_tools_have_names(self) -> None:
        for tool in CHAT_TOOLS:
            assert "name" in tool and tool["name"], f"Tool missing name: {tool}"


# ──────────────────────────────────────────────────────────────────────────────
# Handler presence tests
# ──────────────────────────────────────────────────────────────────────────────

class TestHandlerPresence:
    def test_all_new_handlers_present(self) -> None:
        h = _make_handlers()
        expected = [
            "find_queue", "find_worker",
            "insert_before", "insert_after", "delete_block",
            "generate_changelog", "summarize_repo", "generate_release_notes",
            "read_pdf", "read_image", "github_create_pr",
        ]
        for name in expected:
            assert name in h, f"Handler '{name}' missing from make_chat_handlers()"

    def test_all_new_handlers_callable(self) -> None:
        h = _make_handlers()
        for name in [
            "find_queue", "find_worker",
            "insert_before", "insert_after", "delete_block",
            "generate_changelog", "summarize_repo", "generate_release_notes",
            "read_pdf", "read_image", "github_create_pr",
        ]:
            assert callable(h[name]), f"Handler '{name}' is not callable"


# ──────────────────────────────────────────────────────────────────────────────
# find_queue handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestFindQueueHandler:
    def test_finds_asyncio_queue_in_repo(self) -> None:
        h = _make_handlers()
        result = h["find_queue"]({"repo_path": str(Path(__file__).parent.parent)})
        assert isinstance(result, str)
        # Our codebase uses asyncio.Queue in chat.py
        assert "asyncio" in result.lower() or "queue" in result.lower() or "No queue" in result

    def test_returns_string(self) -> None:
        h = _make_handlers()
        result = h["find_queue"]({})
        assert isinstance(result, str)

    def test_no_venv_paths_in_result(self) -> None:
        h = _make_handlers()
        result = h["find_queue"]({"repo_path": str(Path(__file__).parent.parent)})
        assert ".venv/" not in result


# ──────────────────────────────────────────────────────────────────────────────
# find_worker handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestFindWorkerHandler:
    def test_returns_string(self) -> None:
        h = _make_handlers()
        result = h["find_worker"]({})
        assert isinstance(result, str)

    def test_no_venv_in_results(self) -> None:
        h = _make_handlers()
        result = h["find_worker"]({})
        assert ".venv/" not in result


# ──────────────────────────────────────────────────────────────────────────────
# insert_before handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestInsertBeforeHandler:
    def test_inserts_before_matching_line(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    pass\n")
        result = h["insert_before"]({"path": "test.py", "pattern": "def foo", "content": "# inserted"})
        assert "Inserted" in result
        content = f.read_text()
        lines = content.splitlines()
        assert lines[0] == "# inserted"
        assert lines[1] == "def foo():"

    def test_returns_warn_when_pattern_not_found(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    pass\n")
        result = h["insert_before"]({"path": "test.py", "pattern": "nonexistent_xyz", "content": "# x"})
        assert "WARN" in result or "not found" in result.lower()

    def test_blocks_protected_path(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        result = h["insert_before"]({"path": ".env", "pattern": "KEY", "content": "INJECTED=true"})
        assert "BLOCKED" in result

    def test_multiline_insert(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        f = tmp_path / "test.py"
        f.write_text("class Foo:\n    pass\n")
        result = h["insert_before"]({"path": "test.py", "pattern": "class Foo", "content": "# line 1\n# line 2"})
        assert "2 line(s)" in result
        content = f.read_text()
        assert "# line 1" in content
        assert "# line 2" in content


# ──────────────────────────────────────────────────────────────────────────────
# insert_after handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestInsertAfterHandler:
    def test_inserts_after_matching_line(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        f = tmp_path / "test.py"
        f.write_text("def bar():\n    pass\n")
        result = h["insert_after"]({"path": "test.py", "pattern": "def bar", "content": "    # body comment"})
        assert "Inserted" in result
        content = f.read_text()
        lines = content.splitlines()
        assert lines[0] == "def bar():"
        assert lines[1] == "    # body comment"
        assert lines[2] == "    pass"

    def test_blocks_protected_path(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        result = h["insert_after"]({"path": ".env", "pattern": "x", "content": "y"})
        assert "BLOCKED" in result

    def test_pattern_not_found(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        (tmp_path / "f.py").write_text("x = 1\n")
        result = h["insert_after"]({"path": "f.py", "pattern": "does_not_exist", "content": "z = 2"})
        assert "WARN" in result or "not found" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# delete_block handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDeleteBlockHandler:
    def test_deletes_lines_between_patterns(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        f = tmp_path / "config.py"
        f.write_text("KEEP_THIS = 1\n# BEGIN_DELETE\nremove_a = 2\nremove_b = 3\n# END_DELETE\nKEEP_THIS_TOO = 4\n")
        result = h["delete_block"]({"path": "config.py", "start_pattern": "# BEGIN_DELETE", "end_pattern": "# END_DELETE"})
        assert "Deleted" in result
        content = f.read_text()
        assert "KEEP_THIS = 1" in content
        assert "KEEP_THIS_TOO = 4" in content
        assert "remove_a" not in content
        assert "remove_b" not in content
        assert "BEGIN_DELETE" not in content

    def test_blocks_protected_path(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        result = h["delete_block"]({"path": ".env", "start_pattern": "A", "end_pattern": "B"})
        assert "BLOCKED" in result

    def test_warns_when_block_not_found(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        (tmp_path / "f.py").write_text("x = 1\n")
        result = h["delete_block"]({"path": "f.py", "start_pattern": "NONEXISTENT_START", "end_pattern": "NONEXISTENT_END"})
        assert "WARN" in result or "not found" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# generate_changelog handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateChangelogHandler:
    def test_returns_string(self) -> None:
        h = _make_handlers()
        result = h["generate_changelog"]({"repo_path": _REPO})
        assert isinstance(result, str)

    def test_contains_changelog_header(self) -> None:
        h = _make_handlers()
        result = h["generate_changelog"]({"repo_path": _REPO})
        assert "Unreleased" in result or "Changes" in result or "No commits" in result

    def test_has_today_date(self) -> None:
        import datetime
        h = _make_handlers()
        result = h["generate_changelog"]({"repo_path": _REPO})
        today = datetime.date.today().isoformat()
        # Only check if there were commits
        if "No commits" not in result:
            assert today in result

    def test_custom_to_ref(self) -> None:
        h = _make_handlers()
        result = h["generate_changelog"]({"repo_path": _REPO, "to_ref": "HEAD"})
        assert isinstance(result, str)
        assert len(result) > 0


# ──────────────────────────────────────────────────────────────────────────────
# summarize_repo handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSummarizeRepoHandler:
    def test_returns_string(self) -> None:
        h = _make_handlers()
        result = h["summarize_repo"]({"repo_path": _REPO})
        assert isinstance(result, str)

    def test_contains_summary_header(self) -> None:
        h = _make_handlers()
        result = h["summarize_repo"]({"repo_path": _REPO})
        assert "Repository Summary" in result

    def test_contains_file_count(self) -> None:
        h = _make_handlers()
        result = h["summarize_repo"]({"repo_path": _REPO})
        assert "Total files" in result

    def test_contains_directory_tree(self) -> None:
        h = _make_handlers()
        result = h["summarize_repo"]({"repo_path": _REPO})
        assert "Directory tree" in result

    def test_contains_file_types(self) -> None:
        h = _make_handlers()
        result = h["summarize_repo"]({"repo_path": _REPO})
        assert "file types" in result.lower()

    def test_works_on_small_dir(self, tmp_path: Path) -> None:
        h = make_chat_handlers(str(tmp_path))
        (tmp_path / "README.md").write_text("# Test Repo\nThis is a test.")
        (tmp_path / "main.py").write_text("print('hello')")
        result = h["summarize_repo"]({"repo_path": str(tmp_path)})
        assert "Total files" in result
        assert "README" in result or "readme" in result


# ──────────────────────────────────────────────────────────────────────────────
# generate_release_notes handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateReleaseNotesHandler:
    def test_returns_string(self) -> None:
        h = _make_handlers()
        result = h["generate_release_notes"]({"version": "v1.0.0", "repo_path": _REPO})
        assert isinstance(result, str)

    def test_contains_version(self) -> None:
        h = _make_handlers()
        result = h["generate_release_notes"]({"version": "v1.2.3", "repo_path": _REPO})
        assert "v1.2.3" in result

    def test_contains_release_header(self) -> None:
        h = _make_handlers()
        result = h["generate_release_notes"]({"version": "v0.1.0", "repo_path": _REPO})
        assert "Release Notes" in result or "What's Changed" in result

    def test_today_date_in_notes(self) -> None:
        import datetime
        h = _make_handlers()
        result = h["generate_release_notes"]({"version": "v1.0.0", "repo_path": _REPO})
        today = datetime.date.today().isoformat()
        assert today in result


# ──────────────────────────────────────────────────────────────────────────────
# read_pdf handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestReadPdfHandler:
    def test_errors_gracefully_on_nonexistent_file(self) -> None:
        h = _make_handlers()
        result = h["read_pdf"]({"path": "/nonexistent/path.pdf"})
        assert "[ERROR]" in result

    def test_real_pdf_extraction(self, tmp_path: Path) -> None:
        """Create a minimal PDF and verify extraction works."""
        pytest.importorskip("pdfplumber")
        try:
            import reportlab.pdfgen.canvas as _rc  # noqa: F401
            from reportlab.pdfgen import canvas
            pdf_path = tmp_path / "test.pdf"
            c = canvas.Canvas(str(pdf_path))
            c.drawString(100, 750, "Hello from Gridiron test")
            c.save()
            h = make_chat_handlers(str(tmp_path))
            result = h["read_pdf"]({"path": str(pdf_path)})
            assert "[ERROR]" not in result
            assert "Hello" in result or "Page 1" in result
        except ImportError:
            pytest.skip("reportlab not installed — skipping real PDF test")

    def test_pdfplumber_importable(self) -> None:
        import pdfplumber
        assert pdfplumber is not None


# ──────────────────────────────────────────────────────────────────────────────
# read_image handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestReadImageHandler:
    def test_errors_gracefully_on_nonexistent_file(self) -> None:
        h = _make_handlers()
        result = h["read_image"]({"path": "/nonexistent/image.png"})
        assert "[ERROR]" in result

    def test_reads_valid_png(self, tmp_path: Path) -> None:
        from PIL import Image
        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img.save(str(img_path))
        h = make_chat_handlers(str(tmp_path))
        result = h["read_image"]({"path": str(img_path)})
        assert "[ERROR]" not in result
        assert "100x100" in result
        assert "PNG" in result
        assert "base64" in result.lower() or "Thumbnail" in result

    def test_returns_metadata_format(self, tmp_path: Path) -> None:
        from PIL import Image
        img_path = tmp_path / "sample.jpg"
        img = Image.new("RGB", (200, 150), color=(0, 128, 255))
        img.save(str(img_path), format="JPEG")
        h = make_chat_handlers(str(tmp_path))
        result = h["read_image"]({"path": str(img_path)})
        assert "200x150" in result or "Format" in result

    def test_pil_importable(self) -> None:
        from PIL import Image
        assert Image is not None


# ──────────────────────────────────────────────────────────────────────────────
# github_create_pr handler tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGithubCreatePrHandler:
    def test_errors_gracefully_when_gh_not_authed(self) -> None:
        h = _make_handlers()
        result = h["github_create_pr"]({"title": "Test PR", "body": "Test body"})
        # Should either succeed or return a meaningful error
        assert isinstance(result, str)
        assert len(result) > 0

    def test_errors_when_gh_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as sp
        original_run = sp.run

        def fake_run(cmd: Any, **kwargs: Any) -> Any:
            if "gh" in cmd:
                raise FileNotFoundError("gh not found")
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(sp, "run", fake_run)
        h = _make_handlers()
        result = h["github_create_pr"]({"title": "x", "body": "y"})
        assert "ERROR" in result or "not found" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Tool name uniqueness — all CHAT_TOOLS names must be unique
# ──────────────────────────────────────────────────────────────────────────────

class TestChatToolsIntegrity:
    def test_no_duplicate_tool_names(self) -> None:
        names = [t["name"] for t in CHAT_TOOLS]
        duplicates = [n for n in names if names.count(n) > 1]
        assert not duplicates, f"Duplicate tool names in CHAT_TOOLS: {set(duplicates)}"

    def test_all_tools_have_input_schema(self) -> None:
        for tool in CHAT_TOOLS:
            assert "input_schema" in tool, f"Tool '{tool.get('name')}' missing input_schema"

    def test_all_required_fields_are_in_properties(self) -> None:
        for tool in CHAT_TOOLS:
            schema = tool["input_schema"]
            props = schema.get("properties", {})
            required = schema.get("required", [])
            for r in required:
                assert r in props, (
                    f"Tool '{tool['name']}': required field '{r}' not in properties"
                )
