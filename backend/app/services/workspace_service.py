"""Workspace path enforcement for Repo Console.

Scopes all file-browser operations to paths inside allowed_workspace_parent.
Prevents path traversal attacks.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _workspace_parent() -> str:
    try:
        from app.config import get_settings
        return get_settings().allowed_workspace_parent
    except Exception:
        return "/home"


def assert_in_workspace(path: str) -> str:
    """Return realpath if inside allowed parent, raise ValueError otherwise."""
    parent = os.path.realpath(_workspace_parent())
    real = os.path.realpath(path)
    if not real.startswith(parent):
        raise ValueError(
            f"Path '{path}' resolves to '{real}' which is outside "
            f"allowed workspace parent '{parent}'."
        )
    return real


def list_directory(path: str) -> list[dict[str, Any]]:
    """List a directory inside the workspace."""
    real = assert_in_workspace(path)
    p = Path(real)
    if not p.is_dir():
        raise ValueError(f"Not a directory: {path}")
    entries = []
    for child in sorted(p.iterdir()):
        entries.append({
            "name": child.name,
            "path": str(child),
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return entries


def is_git_repo(path: str) -> bool:
    """Return True if path is inside a git repository."""
    try:
        real = assert_in_workspace(path)
        return (Path(real) / ".git").exists()
    except ValueError:
        return False
