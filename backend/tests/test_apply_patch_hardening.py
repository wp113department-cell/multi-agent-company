"""apply_patch tool #27 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — a proven, live protected-
path bypass): chat_agent.py's real dispatch wrote the LLM-controlled
`patch` content straight to a temp file and ran the real `patch` CLI
against it with zero validation of what file(s) the patch actually
targets. apply_patch's schema has no top-level `path` field (targets
live in the diff's own +++/--- header lines), so none of this codebase's
usual path checks ever had anything to inspect.

Proved directly, before writing any fix: a real unified diff targeting
`.env` — a file every other write-capable tool in this codebase refuses
to touch — was applied successfully through chat_agent.py's dispatch,
genuinely overwriting its real content.

Separately investigated (and could not reproduce) a classic patch-path-
traversal exploit (absolute paths / ../ in the diff headers) — this
system's GNU `patch` binary already refuses those with its own built-in
safety check. That protection is external/version-dependent, so the
fix still validates every target path itself rather than relying on it.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler), and
real `patch` subprocess execution throughout — not a reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.apply_patch import APPLY_PATCH_TOOL, apply_patch_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_apply_patch_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_apply_patch_tool_schema_requires_patch() -> None:
    assert APPLY_PATCH_TOOL["name"] == "apply_patch"
    assert APPLY_PATCH_TOOL["input_schema"]["required"] == ["patch"]


# ---------------------------------------------------------------------------
# The real, proven exploit — verified closed
# ---------------------------------------------------------------------------


def test_handler_rejects_a_patch_targeting_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET_KEY=original_value\n")
    patch = (
        "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n"
        "-SECRET_KEY=original_value\n+SECRET_KEY=PWNED_VALUE\n"
    )
    result = apply_patch_handler(str(tmp_path), {"patch": patch, "strip": 1})
    assert result == "[POLICY DENIED] apply_patch target '.env' is denied by policy"
    assert (tmp_path / ".env").read_text() == "SECRET_KEY=original_value\n"


@pytest.mark.asyncio
async def test_chat_agent_apply_patch_rejects_dotenv_target(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET_KEY=original_value\n")
    agent = _agent(tmp_path)
    patch = (
        "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n"
        "-SECRET_KEY=original_value\n+SECRET_KEY=PWNED_VALUE\n"
    )
    result = await agent._execute_tool("apply_patch", {"patch": patch, "strip": 1})
    assert result.startswith("[POLICY DENIED]")
    assert (tmp_path / ".env").read_text() == "SECRET_KEY=original_value\n"


def test_handler_rejects_a_patch_targeting_secrets_directory(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "key.txt").write_text("realkey")
    patch = (
        "--- a/secrets/key.txt\n+++ b/secrets/key.txt\n@@ -1 +1 @@\n"
        "-realkey\n+PWNED\n"
    )
    result = apply_patch_handler(str(tmp_path), {"patch": patch, "strip": 1})
    assert result.startswith("[POLICY DENIED]")
    assert (tmp_path / "secrets" / "key.txt").read_text() == "realkey"


def test_handler_rejects_a_patch_with_no_extractable_target(tmp_path: Path) -> None:
    result = apply_patch_handler(str(tmp_path), {"patch": "not a real diff at all"})
    assert result.startswith("[ERROR]")
    assert "Could not determine any target file path" in result


# ---------------------------------------------------------------------------
# Regression — a real, legitimate patch must keep applying correctly
# ---------------------------------------------------------------------------


def _legit_patch() -> str:
    return (
        "--- a/mod.py\n+++ b/mod.py\n@@ -1,2 +1,2 @@\n"
        " def foo():\n-    return 1\n+    return 2\n"
    )


def test_handler_applies_a_real_legit_patch(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    result = apply_patch_handler(str(tmp_path), {"patch": _legit_patch(), "strip": 1})
    assert "patching file mod.py" in result
    assert (tmp_path / "mod.py").read_text() == "def foo():\n    return 2\n"


@pytest.mark.asyncio
async def test_chat_agent_apply_patch_applies_a_real_legit_patch(
    tmp_path: Path,
) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "apply_patch", {"patch": _legit_patch(), "strip": 1}
    )
    assert "patching file mod.py" in result
    assert (tmp_path / "mod.py").read_text() == "def foo():\n    return 2\n"


def test_make_chat_handlers_apply_patch_still_works(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["apply_patch"]({"patch": _legit_patch(), "strip": 1})
    assert "patching file mod.py" in result
    assert (tmp_path / "mod.py").read_text() == "def foo():\n    return 2\n"
