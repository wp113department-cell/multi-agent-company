"""template_render tool #204 — tool_enhance.md productionization pass
(2026-09-16).

Three findings — two real and empirically-verified, one a real latent
risk verified NOT currently reachable in this deployment.

1. Worktree-escape FULL FILE CONTENT disclosure oracle on `path`,
   real on BOTH code paths (jinja2-present and jinja2-absent) —
   `root / path` was never validated. Proved live: a real secret
   file's content outside the worktree was returned byte-for-byte
   with no matching template placeholders.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".
3. Real Jinja2 SSTI surface via the plain, non-sandboxed `Template`
   class — verified NOT currently reachable in this deployment
   (`jinja2` is not installed, not declared in requirements, and not
   pulled in transitively — a real `ModuleNotFoundError` confirms
   this), so hardened as defense in depth (SandboxedEnvironment)
   rather than treated as an active, exploitable finding today.

All three closed via a shared `template_render_handler()` using
`check_path_in_worktree()` on `path` (both code paths) and
`jinja2.sandbox.SandboxedEnvironment` in place of the plain `Template`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.template_render import (
    TEMPLATE_RENDER_TOOL,
    template_render_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_template_render_hardening", repo_path=repo)
    return ChatAgent(session)


def test_template_render_tool_schema() -> None:
    assert TEMPLATE_RENDER_TOOL["name"] == "template_render"
    assert TEMPLATE_RENDER_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_template_render_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("template_render") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape full file content disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP SECRET API KEY = sk-outside-12345")

    handlers = make_chat_handlers(str(repo))
    result = handlers["template_render"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "sk-outside-12345" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP SECRET API KEY = sk-outside-12345")

    agent = _agent(str(repo))
    result = await agent._execute_tool("template_render", {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "sk-outside-12345" not in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("sk-outside-12345")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = template_render_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "template_render", {"template": "Hello {{ name }}!", "vars": {"name": "World"}}
    )
    assert "Unknown tool" not in result
    assert "Hello World!" in result


# ---------------------------------------------------------------------------
# Finding #3 — SSTI hardening (currently unreachable, defense in depth)
# ---------------------------------------------------------------------------


def test_jinja2_is_not_installed_in_this_deployment() -> None:
    """Confirms the premise behind treating finding #3 as a currently-
    unreachable latent risk rather than an active exploit: the
    ImportError fallback path is what every real call actually takes
    today."""
    with pytest.raises(ModuleNotFoundError):
        import jinja2  # noqa: F401


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_renders_a_real_inline_template(tmp_path: Path) -> None:
    result = template_render_handler(
        tmp_path,
        str(tmp_path),
        {"template": "Hello {{ name }}!", "vars": {"name": "World"}},
    )
    assert "Hello World!" in result


def test_handler_renders_a_real_template_file(tmp_path: Path) -> None:
    (tmp_path / "tmpl.j2").write_text("Project: {{ project }}")
    result = template_render_handler(
        tmp_path, str(tmp_path), {"path": "tmpl.j2", "vars": {"project": "Gridiron"}}
    )
    assert "Gridiron" in result


def test_handler_errors_cleanly_with_no_template_or_path(tmp_path: Path) -> None:
    result = template_render_handler(tmp_path, str(tmp_path), {})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_renders_a_real_template_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "tmpl.j2").write_text("Project: {{ project }}")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "template_render", {"path": "tmpl.j2", "vars": {"project": "Gridiron"}}
    )
    assert "Gridiron" in result
