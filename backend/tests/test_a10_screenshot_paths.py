"""Sol A10 (2026-10-09): a screenshot could be written to any path on the
server (Playwright's page.screenshot(path=...) with the model's path), so
a model could overwrite any file the backend can write. Now it always
lands in the browser session's own folder; only a plain .png/.jpg name may
be chosen; absolute paths, folders, `..` and symlinks are refused before
the browser is touched."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.repo_tools import browser_driver
from app.repo_tools.browser_driver import screenshot_path


@pytest.fixture(autouse=True)
def _own_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_driver.tempfile, "gettempdir", lambda: str(tmp_path))


def test_default_name_lands_in_the_session_folder(tmp_path: Path) -> None:
    p = screenshot_path(None, "sess-1")
    assert os.path.dirname(p) == str(tmp_path / "gridiron-screenshots" / "sess-1")
    assert p.endswith(".png")


def test_a_plain_name_is_kept(tmp_path: Path) -> None:
    p = screenshot_path("login-page.png", "sess-1")
    assert p == str(tmp_path / "gridiron-screenshots" / "sess-1" / "login-page.png")


@pytest.mark.parametrize(
    "name",
    [
        "/etc/cron.d/evil.png",
        "/home/me/.bashrc",
        "../../outside.png",
        "sub/dir.png",
        "..png",
        "notes.txt",
        "shot.png/../../x.png",
        "C:\\Windows\\x.png",
    ],
)
def test_escapes_are_refused(name: str) -> None:
    with pytest.raises(ValueError):
        screenshot_path(name, "sess-1")


def test_session_ids_cannot_escape_either(tmp_path: Path) -> None:
    p = screenshot_path("a.png", "../../etc")
    assert os.path.realpath(p).startswith(
        str(tmp_path / "gridiron-screenshots") + os.sep
    )


def test_symlinks_are_refused(tmp_path: Path) -> None:
    folder = tmp_path / "gridiron-screenshots" / "sess-2"
    folder.mkdir(parents=True)
    target = tmp_path / "precious.txt"
    target.write_text("keep me\n")
    os.symlink(target, folder / "shot.png")
    with pytest.raises(ValueError):
        screenshot_path("shot.png", "sess-2")
    os.symlink(tmp_path, tmp_path / "gridiron-screenshots" / "sess-3")
    with pytest.raises(ValueError):
        screenshot_path("x.png", "sess-3")
    assert target.read_text() == "keep me\n"


def test_the_tool_refuses_without_touching_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.browser.browser_tools import browser_screenshot_handler

    touched: list[Any] = []
    monkeypatch.setattr(browser_driver, "_get_page", lambda sid: touched.append(sid))
    monkeypatch.setattr(browser_driver, "_run", lambda fn, *a: fn(*a))
    out = browser_screenshot_handler({"path": "/etc/passwd"}, session_id="s")
    assert out.startswith("[ERROR]") and touched == []
