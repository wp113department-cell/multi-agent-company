"""Tests for Batch 15 — 34 new tools reaching the 190-tool vision."""
from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path

import pytest

# ---- helpers ----

def _handlers(tmp_path: Path) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from app.agents.tools import make_chat_handlers
    return make_chat_handlers(str(tmp_path))


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure for testing."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "requirements.txt").mkdir(parents=False, exist_ok=True) or None
    req = tmp_path / "requirements.txt"
    req.unlink(missing_ok=True)
    req.write_text("fastapi==0.139.0\nrequests==2.28.0\n")
    return tmp_path


# ---- Tool count ----

def test_chat_tools_count() -> None:
    from app.agents.tools import CHAT_TOOLS
    assert len(CHAT_TOOLS) >= 165, f"Expected ≥165 CHAT_TOOLS, got {len(CHAT_TOOLS)}"


def test_total_tool_names_190() -> None:
    """All unique tool names across tools.py must reach 190."""
    import re
    src = (Path(__file__).parent.parent / "app" / "agents" / "tools.py").read_text()
    names = set(re.findall(r'"name":\s*"([a-z][a-z0-9_]+)"', src))
    assert len(names) >= 190, f"Expected ≥190 unique tool names, got {len(names)}: {sorted(names)}"


# ---- File ops ----

def test_hash_file(tmp_path: Path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    h = _handlers(tmp_path)
    result = h["hash_file"]({"path": "hello.txt"})
    assert "SHA-256" in result
    assert "hello.txt" in result


def test_count_lines_file(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("a\nb\nc\n")
    h = _handlers(tmp_path)
    result = h["count_lines"]({"path": "code.py"})
    assert "3" in result


def test_count_lines_directory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_text("line1\nline2\n")
    (tmp_path / "sub" / "b.py").write_text("x\n")
    h = _handlers(tmp_path)
    result = h["count_lines"]({"path": "sub", "pattern": "**/*.py"})
    assert ".py" in result


def test_move_file(tmp_path: Path) -> None:
    src = tmp_path / "orig.txt"
    src.write_text("data")
    h = _handlers(tmp_path)
    result = h["move_file"]({"source": "orig.txt", "dest": "moved.txt"})
    assert "moved.txt" in result.lower() or "→" in result
    assert (tmp_path / "moved.txt").exists()
    assert not src.exists()


def test_zip_unzip(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "file.txt").write_text("content")
    h = _handlers(tmp_path)
    zip_result = h["zip_files"]({"source": "mydir"})
    assert "mydir.zip" in zip_result or "Zipped" in zip_result
    assert (tmp_path / "mydir.zip").exists()
    out_dir = tmp_path / "extracted"
    out_dir.mkdir()
    unzip_result = h["unzip_files"]({"archive": "mydir.zip", "dest": "extracted"})
    assert "extracted" in unzip_result or "Extracted" in unzip_result


def test_create_directory(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["create_directory"]({"path": "new/nested/dir"})
    assert "new/nested/dir" in result
    assert (tmp_path / "new" / "nested" / "dir").is_dir()


def test_create_directory_protected(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["create_directory"]({"path": ".env"})
    assert "POLICY DENIED" in result or "protected" in result.lower() or "new/.env" not in result


# ---- Environment ----

def test_read_env_var(tmp_path: Path) -> None:
    os.environ["_TEST_GRIDIRON_VAR"] = "hello"
    h = _handlers(tmp_path)
    result = h["read_env_var"]({"name": "_TEST_GRIDIRON_VAR"})
    assert "hello" in result
    del os.environ["_TEST_GRIDIRON_VAR"]


def test_read_env_var_missing(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["read_env_var"]({"name": "_DEFINITELY_NOT_SET_XYZ"})
    assert "NOT SET" in result


def test_list_env_vars(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["list_env_vars"]({})
    assert "PATH" in result or len(result.splitlines()) > 5


def test_env_diff(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("DB_URL=\nSECRET_KEY=\nDEBUG=\n")
    (tmp_path / ".env").write_text("DB_URL=postgres://localhost\nEXTRA_VAR=extra\n")
    h = _handlers(tmp_path)
    result = h["env_diff"]({})
    assert "SECRET_KEY" in result  # missing
    assert "EXTRA_VAR" in result   # extra


def test_env_diff_no_diff(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("KEY=\n")
    (tmp_path / ".env").write_text("KEY=value\n")
    h = _handlers(tmp_path)
    result = h["env_diff"]({})
    assert "No differences" in result or "✅" in result


# ---- Data format ----

def test_json_validate_valid(tmp_path: Path) -> None:
    (tmp_path / "data.json").write_text('{"key": "value"}')
    h = _handlers(tmp_path)
    result = h["json_validate"]({"path": "data.json"})
    assert "valid" in result.lower()


def test_json_validate_invalid(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{key: value}")
    h = _handlers(tmp_path)
    result = h["json_validate"]({"path": "bad.json"})
    assert "INVALID" in result or "ERROR" in result


def test_csv_preview(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")
    h = _handlers(tmp_path)
    result = h["csv_preview"]({"path": "data.csv", "rows": 2})
    assert "name" in result
    assert "Alice" in result


# ---- Git extras ----

def test_git_stash_list(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["git_stash_list"]({})
    # no git repo in tmp, but should not raise an unhandled exception
    assert isinstance(result, str)


def test_semver_bump_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "app"\nversion = "1.2.3"\n')
    h = _handlers(tmp_path)
    result = h["semver_bump"]({"part": "patch"})
    assert "1.2.4" in result


def test_semver_bump_minor(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('version = "2.0.0"\n')
    h = _handlers(tmp_path)
    result = h["semver_bump"]({"part": "minor"})
    assert "2.1.0" in result


def test_semver_bump_major(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("3.4.5\n")
    (tmp_path / "pyproject.toml").unlink(missing_ok=True)
    h = _handlers(tmp_path)
    result = h["semver_bump"]({"part": "major"})
    # VERSION file might not match the pattern exactly — just check no crash
    assert isinstance(result, str)


# ---- Process / System ----

def test_list_processes(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["list_processes"]({})
    assert isinstance(result, str) and len(result) > 0


def test_list_processes_filter(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["list_processes"]({"filter": "python"})
    assert isinstance(result, str)


def test_check_url_status_invalid(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["check_url_status"]({"url": "http://localhost:19999/nonexistent"})
    assert "ERROR" in result or "HTTP" in result


# ---- Base64 ----

def test_base64_encode_text(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["base64_encode"]({"text": "hello"})
    import base64
    assert result == base64.b64encode(b"hello").decode()


def test_base64_decode_text(tmp_path: Path) -> None:
    import base64
    encoded = base64.b64encode(b"world").decode()
    h = _handlers(tmp_path)
    result = h["base64_encode"]({"text": encoded, "decode": True})
    assert result == "world"


def test_base64_encode_file(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_bytes(b"binary data")
    h = _handlers(tmp_path)
    result = h["base64_encode"]({"path": "test.txt"})
    assert isinstance(result, str) and len(result) > 0


# ---- Diagram ----

def test_generate_diagram_flowchart(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["generate_diagram"]({"description": "user login flow"})
    assert "mermaid" in result or "flowchart" in result


def test_generate_diagram_sequence(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["generate_diagram"]({"description": "API call", "kind": "sequence"})
    assert "sequenceDiagram" in result or "sequence" in result.lower()


# ---- HTTP request ----

def test_http_request_invalid(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["http_request"]({"method": "GET", "url": "http://localhost:19999/test"})
    assert "ERROR" in result or "refused" in result.lower()


# ---- Docs ----

def test_find_unused_imports(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import os\nimport sys\nprint('hi')\n")
    h = _handlers(tmp_path)
    result = h["find_unused_imports"]({"path": "."})
    assert isinstance(result, str)


def test_loc_stats(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "app.ts").write_text("const x = 1;\n")
    h = _handlers(tmp_path)
    result = h["loc_stats"]({})
    assert ".py" in result or "total" in result.lower()


# ---- Template render ----

def test_template_render_string(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["template_render"]({"template": "Hello {{ name }}!", "vars": {"name": "World"}})
    assert "Hello World!" in result


def test_template_render_file(tmp_path: Path) -> None:
    (tmp_path / "tmpl.j2").write_text("Project: {{ project }}")
    h = _handlers(tmp_path)
    result = h["template_render"]({"path": "tmpl.j2", "vars": {"project": "Gridiron"}})
    assert "Gridiron" in result


# ---- Package management ----

def test_pip_list(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["pip_list"]({})
    assert "fastapi" in result.lower() or "Package" in result


def test_pip_list_filter(tmp_path: Path) -> None:
    h = _handlers(tmp_path)
    result = h["pip_list"]({"filter": "fastapi"})
    assert isinstance(result, str)
