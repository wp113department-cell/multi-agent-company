"""AC6 — grep the new barot_agent source files for hardcoded literal values
that must instead be traceable to a config read: the concurrency default
(3), the TTL default (20), and any hardcoded Claude model string. Mirrors
the acceptance criterion's own wording as an enforced test, not just a
manual check.

Only app/config.py (the Field(default=...) declarations themselves) may
contain these literals — every other new file must read them from
get_settings()."""

from __future__ import annotations

import re
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_NEW_SOURCE_FILES = [
    _BACKEND_ROOT / "app" / "agents" / "barot_agent.py",
    _BACKEND_ROOT / "app" / "agents" / "temporary_agent.py",
    _BACKEND_ROOT / "app" / "fleet" / "dynamic_agent_runtime.py",
]

_MODEL_STRING_RE = re.compile(r"claude-[a-z0-9.\-]+", re.IGNORECASE)


def _strip_comments_and_docstrings(source: str) -> str:
    """Best-effort: drop full-line comments and triple-quoted docstring
    bodies so a literal mentioned only in prose (e.g. explaining *why* a
    value is config-driven) doesn't false-positive this check. Not a full
    parser — good enough for this repo's own consistent style."""
    lines = []
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()
        if in_docstring:
            if '"""' in stripped:
                in_docstring = False
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith('"""'):
            if stripped.count('"""') >= 2:
                continue  # single-line docstring
            in_docstring = True
            continue
        lines.append(line)
    return "\n".join(lines)


def test_no_hardcoded_concurrency_or_ttl_literal() -> None:
    for path in _NEW_SOURCE_FILES:
        code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
        # Whole-token match only — avoids false positives like "max_turns=12"
        # or a UUID slice length, which aren't the config values AC6 cares
        # about (concurrency default 3, TTL default 20).
        for literal in ("3", "20"):
            pattern = re.compile(rf"(?<![\w.]){literal}(?![\w.])")
            matches = pattern.findall(code)
            assert not matches, (
                f"{path.name} contains the literal {literal!r} outside "
                f"config.py — should be a get_settings() read"
            )


def test_no_hardcoded_claude_model_string() -> None:
    for path in _NEW_SOURCE_FILES:
        code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
        matches = _MODEL_STRING_RE.findall(code)
        assert not matches, (
            f"{path.name} contains a hardcoded model string {matches!r} — "
            f"should come from settings.barot_agent_model"
        )


def test_config_py_is_the_only_place_these_defaults_live() -> None:
    config_path = _BACKEND_ROOT / "app" / "config.py"
    code = config_path.read_text(encoding="utf-8")
    assert "barot_agent_max_concurrent_temp_agents" in code
    assert "default=3" in code
    assert "barot_agent_temp_agent_ttl_minutes" in code
    assert "default=20.0" in code
