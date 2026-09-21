"""Verification batch B1, items #26-#31 (create/edit/delete files, synchronize,
refactor, PRESERVE FORMATTING, PRESERVE COMMENTS).

Defects proven live before the fix (each test below fails on the original code):

* every line-editing tool converted a CRLF file to LF (`Path.read_text` folds
  CRLF on read, `write_text` writes LF), so a one-word edit rewrote every line;
* replace_function/replace_class found a block's end with an indentation
  heuristic: a function holding an unindented multi-line string (SQL, template,
  help text) was only partly replaced — success was reported, the tail of the old
  body was left behind and the file no longer parsed; blank lines separating the
  block from the next symbol were also swallowed;
* delete_block with an end_pattern that never matched silently deleted from the
  start pattern to end-of-file;
* sync_files converted CRLF sources to LF, called a CRLF-vs-LF difference "already
  in sync", could not sync binary files and dropped the exec bit.
"""

from __future__ import annotations

import ast
import os
import stat
from pathlib import Path

import pytest

from app.tools.filesystem.append_file import append_file_handler
from app.tools.filesystem.delete_block import delete_block_handler
from app.tools.filesystem.delete_lines import delete_lines_handler
from app.tools.filesystem.edit_file import edit_file_handler
from app.tools.filesystem.insert_after import insert_after_handler
from app.tools.filesystem.insert_at_line import insert_at_line_handler
from app.tools.filesystem.insert_before import insert_before_handler
from app.tools.filesystem.replace_class import replace_class_handler
from app.tools.filesystem.replace_function import replace_function_handler
from app.tools.filesystem.sync_files import sync_files_handler
from app.tools.filesystem.write_file import write_file_handler


def _call(fn, tmp_path: Path, **inp) -> str:
    return fn(tmp_path, str(tmp_path), inp)


CRLF = b"alpha\r\nbeta\r\ngamma\r\n"


@pytest.mark.parametrize(
    "fn, inp, expected",
    [
        (
            edit_file_handler,
            dict(old_string="beta", new_string="BETA"),
            b"alpha\r\nBETA\r\ngamma\r\n",
        ),
        (
            edit_file_handler,
            dict(old_string="alpha\nbeta", new_string="A\nB"),
            b"A\r\nB\r\ngamma\r\n",
        ),  # multi-line LF old_string still matches a CRLF file
        (
            insert_before_handler,
            dict(pattern="beta", content="new"),
            b"alpha\r\nnew\r\nbeta\r\ngamma\r\n",
        ),
        (
            insert_after_handler,
            dict(pattern="beta", content="new"),
            b"alpha\r\nbeta\r\nnew\r\ngamma\r\n",
        ),
        (
            insert_at_line_handler,
            dict(line=2, content="new"),
            b"alpha\r\nnew\r\nbeta\r\ngamma\r\n",
        ),
        (delete_lines_handler, dict(start_line=2, end_line=2), b"alpha\r\ngamma\r\n"),
        (
            delete_block_handler,
            dict(start_pattern="alpha", end_pattern="beta"),
            b"gamma\r\n",
        ),
        (
            append_file_handler,
            dict(content="delta\n"),
            b"alpha\r\nbeta\r\ngamma\r\ndelta\r\n",
        ),
        (write_file_handler, dict(content="x\ny\n"), b"x\r\ny\r\n"),
    ],
)
def test_crlf_files_keep_crlf(tmp_path, fn, inp, expected) -> None:
    (tmp_path / "f.txt").write_bytes(CRLF)
    out = _call(fn, tmp_path, path="f.txt", **inp)
    assert not out.startswith(("[ERROR]", "[WARN]", "[BLOCKED]")), out
    assert (tmp_path / "f.txt").read_bytes() == expected


def test_replace_function_and_class_keep_crlf(tmp_path) -> None:
    src = "def f():\n    return 1\n\n\nclass C:\n    x = 1\n".replace("\n", "\r\n")
    (tmp_path / "m.py").write_bytes(src.encode())
    _call(
        replace_function_handler,
        tmp_path,
        path="m.py",
        function_name="f",
        new_code="def f():\n    return 2\n",
    )
    _call(
        replace_class_handler,
        tmp_path,
        path="m.py",
        class_name="C",
        new_code="class C:\n    x = 2\n",
    )
    data = (tmp_path / "m.py").read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b""), "a bare LF crept in"
    assert b"return 2" in data and b"x = 2" in data


@pytest.mark.parametrize(
    "raw",
    [
        b"a\nb\n",
        b"a\tb\n\tc\n",
        b"no newline at end",
        b"\xef\xbb\xbfhello\n",
        "héllo ✓\n".encode(),
    ],
)
def test_lf_tabs_bom_unicode_and_missing_final_newline_are_untouched(
    tmp_path, raw
) -> None:
    (tmp_path / "f.txt").write_bytes(raw)
    first = raw.decode("utf-8").split("\n")[0].replace("\ufeff", "")
    word = first.split("\t")[0][:1] or first[:1]
    out = (
        _call(
            edit_file_handler,
            tmp_path,
            path="f.txt",
            old_string=word,
            new_string="Z" + word,
        )
        if raw.decode("utf-8").count(word) == 1
        else "skip"
    )
    if out != "skip":
        assert (tmp_path / "f.txt").read_bytes() == raw.replace(
            word.encode(), ("Z" + word).encode(), 1
        )


def test_new_files_are_written_exactly_as_given(tmp_path) -> None:
    _call(write_file_handler, tmp_path, path="new_crlf.txt", content="a\r\nb\r\n")
    _call(write_file_handler, tmp_path, path="new_lf.txt", content="a\nb\n")
    assert (tmp_path / "new_crlf.txt").read_bytes() == b"a\r\nb\r\n"
    assert (tmp_path / "new_lf.txt").read_bytes() == b"a\nb\n"


def test_write_file_reports_real_byte_count(tmp_path) -> None:
    out = _call(write_file_handler, tmp_path, path="u.txt", content="✓✓")
    assert "(6 bytes)" in out  # 2 chars, 6 UTF-8 bytes


# ------------------------- replace_function / replace_class -----------------

SQL_MODULE = '''# top comment
import os


# about query
@staticmethod
def query(db):
    # inner comment
    sql = """
SELECT *
FROM users
WHERE active
"""
    return db.run(sql)  # trailing


# about other
def other():
    return 1
'''


def test_replace_function_with_an_unindented_multiline_string(tmp_path) -> None:
    (tmp_path / "m.py").write_text(SQL_MODULE)
    out = _call(
        replace_function_handler,
        tmp_path,
        path="m.py",
        function_name="query",
        new_code="def query(db):\n    return db.run('SELECT 1')\n",
    )
    assert out.startswith("Replaced"), out
    text = (tmp_path / "m.py").read_text()
    ast.parse(text)  # the file still parses (it did not before the fix)
    assert "WHERE active" not in text and "SELECT 1" in text
    # neighbours, decorator and the comments OUTSIDE the function are intact
    assert "# top comment" in text and "# about query" in text
    assert "@staticmethod" in text and "# about other" in text
    assert "def other():\n    return 1" in text
    # ... and the two blank lines separating it from the next symbol survive
    assert "SELECT 1')\n\n\n# about other" in text


def test_replace_function_keeps_blank_line_separator_in_a_plain_module(
    tmp_path,
) -> None:
    (tmp_path / "p.py").write_text(
        "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    )
    _call(
        replace_function_handler,
        tmp_path,
        path="p.py",
        function_name="a",
        new_code="def a():\n    return 10\n",
    )
    assert (tmp_path / "p.py").read_text() == (
        "def a():\n    return 10\n\n\ndef b():\n    return 2\n"
    )


def test_replace_method_async_and_first_match_in_source_order(tmp_path) -> None:
    (tmp_path / "k.py").write_text(
        "class A:\n    async def go(self):\n        return 1\n\n    def other(self):\n        pass\n"
    )
    _call(
        replace_function_handler,
        tmp_path,
        path="k.py",
        function_name="go",
        new_code="    async def go(self):\n        return 2\n",
    )
    text = (tmp_path / "k.py").read_text()
    ast.parse(text)
    assert "return 2" in text and "def other(self):" in text


def test_replace_function_falls_back_on_unparsable_file_and_keeps_separator(
    tmp_path,
) -> None:
    (tmp_path / "bad.py").write_text(
        "def a():\n    return 1\n\n\ndef b(:\n    return 2\n"  # b has a syntax error
    )
    out = _call(
        replace_function_handler,
        tmp_path,
        path="bad.py",
        function_name="a",
        new_code="def a():\n    return 10\n",
    )
    assert out.startswith("Replaced"), out
    assert (
        (tmp_path / "bad.py")
        .read_text()
        .startswith("def a():\n    return 10\n\n\ndef b(:")
    )


def test_replace_function_not_found(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def a():\n    pass\n")
    out = _call(
        replace_function_handler,
        tmp_path,
        path="m.py",
        function_name="zzz",
        new_code="x",
    )
    assert (
        out.startswith("[ERROR]")
        and (tmp_path / "m.py").read_text() == "def a():\n    pass\n"
    )


def test_replace_class_with_an_unindented_multiline_string(tmp_path) -> None:
    (tmp_path / "c.py").write_text(
        'class Q:\n    HELP = """\nunindented help\ntext\n"""\n\n    def run(self):\n        return 1\n\n\nclass Z:\n    pass\n'
    )
    out = _call(
        replace_class_handler,
        tmp_path,
        path="c.py",
        class_name="Q",
        new_code="class Q:\n    pass\n",
    )
    assert out.startswith("Replaced"), out
    text = (tmp_path / "c.py").read_text()
    ast.parse(text)
    assert "unindented help" not in text
    assert text == "class Q:\n    pass\n\n\nclass Z:\n    pass\n"


# ------------------------------- delete_block ------------------------------


def test_delete_block_unterminated_is_refused_and_deletes_nothing(tmp_path) -> None:
    body = "keep1\nSTART\nmiddle\nmore\nkeep-me-too\n"
    (tmp_path / "f.txt").write_text(body)
    out = _call(
        delete_block_handler,
        tmp_path,
        path="f.txt",
        start_pattern="START",
        end_pattern="NEVER-MATCHES",
    )
    assert out.startswith("[ERROR]"), out
    assert (tmp_path / "f.txt").read_text() == body


def test_delete_block_normal_and_repeated_blocks(tmp_path) -> None:
    (tmp_path / "f.txt").write_text("a\nS\nx\nE\nb\nS\ny\nE\nc\n")
    out = _call(
        delete_block_handler,
        tmp_path,
        path="f.txt",
        start_pattern="^S$",
        end_pattern="^E$",
    )
    assert "Deleted 6 lines" in out
    assert (tmp_path / "f.txt").read_text() == "a\nb\nc\n"


# --------------------------------- sync_files ------------------------------


def test_sync_copies_bytes_exactly_including_crlf_binary_and_mode(tmp_path) -> None:
    src = tmp_path / "src.sh"
    src.write_bytes(b"#!/bin/sh\r\necho hi\r\n")
    os.chmod(src, 0o755)
    blob = tmp_path / "blob.bin"
    blob.write_bytes(bytes(range(256)))
    out = _call(
        sync_files_handler, tmp_path, source="src.sh", paths=["a.sh", "sub/b.sh"]
    )
    assert "[ERROR]" not in out, out
    for name in ("a.sh", "sub/b.sh"):
        assert (tmp_path / name).read_bytes() == src.read_bytes()
        assert stat.S_IMODE(os.stat(tmp_path / name).st_mode) == 0o755
    out = _call(sync_files_handler, tmp_path, source="blob.bin", paths=["copy.bin"])
    assert "[ERROR]" not in out, out
    assert (tmp_path / "copy.bin").read_bytes() == bytes(range(256))


def test_sync_treats_crlf_vs_lf_as_a_real_difference(tmp_path) -> None:
    (tmp_path / "s.txt").write_bytes(b"a\r\nb\r\n")
    (tmp_path / "t.txt").write_bytes(b"a\nb\n")
    out = _call(sync_files_handler, tmp_path, source="s.txt", paths=["t.txt"])
    assert "updated" in out and "unchanged" not in out
    assert (tmp_path / "t.txt").read_bytes() == b"a\r\nb\r\n"
    out = _call(sync_files_handler, tmp_path, source="s.txt", paths=["t.txt"])
    assert "unchanged" in out


# ------------------------- real chat-agent dispatch ------------------------


def test_real_chat_dispatch_preserves_crlf_and_replaces_safely(tmp_path) -> None:
    import asyncio

    from app.agents.chat_agent import ChatAgent
    from app.models.chat import ChatSession

    (tmp_path / "w.txt").write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / "m.py").write_text(SQL_MODULE)
    agent = ChatAgent(ChatSession(session_id="b1_fileprs", repo_path=str(tmp_path)))

    def run(name, **inp):
        return asyncio.run(agent._execute_tool(name, inp))

    assert (
        run("edit_file", path="w.txt", old_string="two", new_string="TWO")
        == "Edited w.txt"
    )
    assert (tmp_path / "w.txt").read_bytes() == b"one\r\nTWO\r\n"
    out = run(
        "replace_function",
        path="m.py",
        function_name="query",
        new_code="def query(db):\n    return 1\n",
    )
    assert out.startswith("Replaced"), out
    ast.parse((tmp_path / "m.py").read_text())
