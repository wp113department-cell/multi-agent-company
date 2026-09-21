"""Verification batch B1, items #29 (refactor projects), #35-#37 (multi-file
edits: safe, formatting-preserving), #2/#32 (stay inside the repo, avoid
restricted files).

Defects proven live in rename_symbol before the fix (each test fails on the
original code):

* CRLF files were rewritten as LF;
* a form-feed character in a .py file put every later edit on the wrong line and
  CORRUPTED the file (`tokenize` and `str.splitlines` disagree on what a line is);
* a symlinked file pointing OUTSIDE the repo was rewritten through the link;
* file_pattern="*" rewrote .env, .github/workflows/*.yml, secrets/ — paths the
  write tools' own policy protects;
* one unwritable file mid-batch escaped as an uncaught exception and left the
  project half-renamed with no rollback.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.repo_tools import ast_engine
from app.repo_tools.ast_engine import rename_symbol


def _r(tmp_path: Path, old="target_fn", new="renamed_fn", pattern="*.py", **kw) -> str:
    return rename_symbol(old, new, str(tmp_path), pattern, **kw)


def test_crlf_files_keep_crlf_python_and_plain(tmp_path) -> None:
    (tmp_path / "a.py").write_bytes(b"def target_fn():\r\n    return 1\r\n")
    (tmp_path / "b.ts").write_bytes(
        b"import { target_fn } from './a';\r\ntarget_fn();\r\n"
    )
    _r(tmp_path, pattern="*.py")
    _r(tmp_path, pattern="*.ts")
    assert (tmp_path / "a.py").read_bytes() == b"def renamed_fn():\r\n    return 1\r\n"
    assert (tmp_path / "b.ts").read_bytes() == (
        b"import { renamed_fn } from './a';\r\nrenamed_fn();\r\n"
    )


@pytest.mark.parametrize("sep", ["\x0c", " ", "\x85"])
def test_unusual_line_separators_do_not_corrupt_the_file(tmp_path, sep) -> None:
    src = f"x = 1\n{sep}\nfirst = target_fn\nsecond = target_fn  # target_fn\n"
    (tmp_path / "ff.py").write_text(src, encoding="utf-8")
    _r(tmp_path)
    assert (tmp_path / "ff.py").read_text(encoding="utf-8") == (
        f"x = 1\n{sep}\nfirst = renamed_fn\nsecond = renamed_fn  # target_fn\n"
    )


def test_strings_and_comments_are_untouched_identifiers_are_renamed(tmp_path) -> None:
    (tmp_path / "m.py").write_text(
        '"""target_fn doc"""\n# target_fn comment\n'
        "def target_fn():\n    return 'target_fn'\n\nx = target_fn()\n"
    )
    out = _r(tmp_path)
    assert out.startswith("Renamed")
    assert (tmp_path / "m.py").read_text() == (
        '"""target_fn doc"""\n# target_fn comment\n'
        "def renamed_fn():\n    return 'target_fn'\n\nx = renamed_fn()\n"
    )


def test_symlink_pointing_outside_the_tree_is_never_written(tmp_path) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (outside / "o.py").write_text("def target_fn():\n    return 1\n")
    (repo / "a.py").write_text("from x import target_fn\n")
    os.symlink(outside / "o.py", repo / "linked.py")
    out = _r(repo)
    assert (outside / "o.py").read_text() == "def target_fn():\n    return 1\n"
    assert "linked.py" in out and "SKIPPED" in out
    assert (repo / "a.py").read_text() == "from x import renamed_fn\n"


def test_symlink_inside_the_tree_is_fine(tmp_path) -> None:
    (tmp_path / "real.py").write_text("target_fn()\n")
    os.symlink(tmp_path / "real.py", tmp_path / "alias.py")
    _r(tmp_path)
    assert (tmp_path / "real.py").read_text() == "renamed_fn()\n"


def test_protected_paths_are_never_rewritten(tmp_path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "secrets").mkdir()
    files = {
        ".env": "TOKEN=target_fn\n",
        ".env.production": "TOKEN=target_fn\n",
        ".github/workflows/ci.yml": "run: target_fn\n",
        "secrets/s.txt": "target_fn\n",
        "server.pem": "target_fn\n",
        "id_rsa": "target_fn\n",
    }
    for rel, body in files.items():
        (tmp_path / rel).write_text(body)
    (tmp_path / "ok.txt").write_text("target_fn\n")
    out = _r(tmp_path, pattern="*")
    for rel, body in files.items():
        assert (tmp_path / rel).read_text() == body, f"protected file rewritten: {rel}"
    assert (tmp_path / "ok.txt").read_text() == "renamed_fn\n"
    assert "protected path" in out


def test_unwritable_file_aborts_before_anything_is_written(tmp_path) -> None:
    (tmp_path / "a.py").write_text("target_fn()\n")
    (tmp_path / "b.py").write_text("target_fn()\n")
    os.chmod(tmp_path / "b.py", 0o444)
    if os.access(tmp_path / "b.py", os.W_OK):
        pytest.skip("running as a user that ignores file modes (root)")
    out = _r(tmp_path)
    assert out.startswith("[ERROR]") and "b.py" in out
    assert (
        tmp_path / "a.py"
    ).read_text() == "target_fn()\n"  # untouched, not half-renamed
    assert (tmp_path / "b.py").read_text() == "target_fn()\n"


def test_midway_write_failure_rolls_back_files_already_written(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "a.py").write_bytes(b"target_fn()\r\n")
    (tmp_path / "b.py").write_text("target_fn()\n")
    real = ast_engine.write_text_lf
    calls = {"n": 0}

    def flaky(path, text, style="\n"):
        calls["n"] += 1
        if calls["n"] == 2:  # the second file fails (disk full, EIO, ...)
            raise OSError(28, "No space left on device")
        real(path, text, style)

    monkeypatch.setattr(ast_engine, "write_text_lf", flaky)
    out = _r(tmp_path)
    assert out.startswith("[ERROR]") and "rolled back" in out, out
    assert (
        tmp_path / "a.py"
    ).read_bytes() == b"target_fn()\r\n"  # restored byte-for-byte
    assert (tmp_path / "b.py").read_text() == "target_fn()\n"


def test_large_batch_dry_run_still_writes_nothing(tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rename_symbol_max_files", 2)
    for i in range(4):
        (tmp_path / f"f{i}.py").write_text("target_fn()\n")
    out = _r(tmp_path)
    assert "[DRY RUN]" in out
    assert all((tmp_path / f"f{i}.py").read_text() == "target_fn()\n" for i in range(4))
    out = _r(tmp_path, confirm_large_batch=True)
    assert out.startswith("Renamed")


def test_real_chat_dispatch_does_not_write_through_an_outside_symlink(tmp_path) -> None:
    import asyncio

    from app.agents.chat_agent import ChatAgent
    from app.models.chat import ChatSession

    repo, outside = tmp_path / "repo", tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (outside / "o.py").write_text("def target_fn(): pass\n")
    (repo / "a.py").write_text("target_fn()\n")
    os.symlink(outside / "o.py", repo / "linked.py")
    agent = ChatAgent(ChatSession(session_id="b1_rs_safety", repo_path=str(repo)))
    agent._confirm = AsyncMock(return_value=True)
    out = asyncio.run(
        agent._execute_tool(
            "rename_symbol", {"old_name": "target_fn", "new_name": "renamed_fn"}
        )
    )
    assert "Renamed" in out
    assert (outside / "o.py").read_text() == "def target_fn(): pass\n"


@pytest.mark.parametrize(
    "broken",
    [
        "def broken(:\n    return target_fn\n",
        's = """never closed\ntarget_fn\n',
        "x = (1,\ntarget_fn\n",
    ],
)
def test_one_unparsable_python_file_does_not_abort_the_whole_rename(
    tmp_path, broken
) -> None:
    """tokenize.TokenError (unbalanced brackets, unterminated string) used to
    escape as an uncaught exception and kill the whole call."""
    (tmp_path / "good.py").write_text("x = target_fn()\n")
    (tmp_path / "broken.py").write_text(broken)
    out = _r(tmp_path)
    assert out.startswith("Renamed"), out
    assert (tmp_path / "good.py").read_text() == "x = renamed_fn()\n"
    assert (
        "renamed_fn" in (tmp_path / "broken.py").read_text()
    )  # regex fallback for that file
