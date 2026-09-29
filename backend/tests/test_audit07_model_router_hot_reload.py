"""Production audit 07 (2026-09-29): editing agent_models.json takes effect
without a restart, and a half-saved (invalid) file never wipes the table.
reload() existed but nothing called it."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.fleet.model_router import ModelRouter


def _write(p: Path, table: dict) -> None:
    p.write_text(json.dumps(table))
    # make sure the mtime visibly changes even on coarse-mtime filesystems
    t = time.time() + 5
    os.utime(p, (t, t))


def _table(model: str) -> dict:
    return {
        "_tiers": {"sonnet": {"max_tokens": 10}},
        "DEFAULT": {"provider": "anthropic", "model": "dflt", "tier": "sonnet"},
        "coder": {"provider": "anthropic", "model": model, "tier": "sonnet"},
    }


def test_edit_takes_effect_without_restart(tmp_path: Path) -> None:
    f = tmp_path / "agent_models.json"
    _write(f, _table("model-a"))
    router = ModelRouter(f)
    assert router.route("coder").model == "model-a"
    _write(f, _table("model-b"))
    assert router.route("coder").model == "model-b"


def test_invalid_file_mid_edit_keeps_previous_table(tmp_path: Path) -> None:
    f = tmp_path / "agent_models.json"
    _write(f, _table("model-a"))
    router = ModelRouter(f)
    assert router.route("coder").model == "model-a"
    f.write_text('{"coder": {"model": "half-writ')  # truncated save
    t = time.time() + 10
    os.utime(f, (t, t))
    assert router.route("coder").model == "model-a"  # not the built-in default
    _write(f, _table("model-c"))
    assert router.route("coder").model == "model-c"
