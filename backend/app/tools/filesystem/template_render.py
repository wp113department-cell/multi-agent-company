"""template_render tool — tool_enhance.md productionization pass, tool
#204 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: template_render
Old path: app/agents/tools.py (`_TEMPLATE_RENDER_TOOL` schema dict,
    `template_render_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/template_render.py (this file) —
    `TEMPLATE_RENDER_TOOL`, `template_render_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed:
    `CHAT_TOOLS` membership count is 1); grepped all other agent
    files, none reference `"template_render"` in their own
    `allowed_tools` — interactive chat is the only real consumer.
Affected modules: app/agents/tools.py (`template_render_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "template_render" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_new_tools.py`'s two existing tests
    (`test_template_render_string`, `test_template_render_file`) use
    only in-worktree relative paths / inline templates — unaffected
    by the new worktree-boundary check, re-run and confirmed passing
    unchanged. New tests added: see
    tests/test_template_render_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/template_render.md.
---------------------------------------------------------------------------

Three findings — two real and empirically-verified today, one a real
latent risk verified NOT currently reachable in this deployment
(documented honestly, not glossed over, per tool_enhance.md's "no
production claim based only on LLM judgment" and "real execution"
rules).

1. **Worktree-boundary escape — a genuine FULL FILE CONTENT disclosure
   oracle, on BOTH real code paths (jinja2-present and jinja2-absent).**
   `template_render_h` built `root / str(path)` in two separate places
   (inside the `try` when jinja2 is importable, and again inside the
   `except ImportError` fallback) with zero validation — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#202/#203
   this initiative, but WORSE here: with no matching `{{ var }}`
   placeholders and no `vars`, the naive string-substitution fallback
   returns the file's content completely unchanged — full, verbatim
   disclosure, not just metadata or partial structure. Proved live: a
   real secret string in a file outside the worktree was returned
   byte-for-byte through `template_render({"path": "<outside file>"})`.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203.**
   `template_render` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: template_render"`.
3. **Real but CURRENTLY UNREACHABLE latent risk, hardened as defense
   in depth, not treated as an active finding**: the `try` branch
   passes an LLM-controlled `template`/`path`-sourced string straight
   into Jinja2's plain, non-sandboxed `Template(...).render(**variables)`
   — classic Server-Side Template Injection surface (a crafted
   template body like `{{ self.__init__.__globals__...
   }}`-style payloads can reach arbitrary Python attribute access in
   an unsandboxed Jinja2 environment). Checked directly (not assumed):
   `jinja2` is NOT installed in this project's venv, NOT listed in
   `requirements.txt`/`requirements-dev.txt`, and NOT pulled in
   transitively by any installed package (verified via `pip list` and
   a real `import jinja2` `ModuleNotFoundError`) — so in this actual
   deployed environment the `try` branch's `import jinja2` always
   raises `ImportError` and the SSTI-vulnerable code path never
   executes; every real call takes the naive-substitution fallback
   instead. Not fixed as an "active" finding since it cannot currently
   fire, but hardened anyway (near-zero cost, real severity class if
   jinja2 is ever added to dependencies later) by switching to
   `jinja2.sandbox.SandboxedEnvironment`, which blocks attribute-based
   sandbox escapes.

Fixed via a shared `template_render_handler(root, worktree_path, inp)`:
`path` is validated with `check_path_in_worktree()` before either
read, closing finding #1 on both code paths. A new `chat_agent.py`
dispatch delegates to this same shared handler, closing finding #2.
The `try` branch now imports `jinja2.sandbox.SandboxedEnvironment`
instead of the plain `Template`, closing finding #3 as defense in
depth even though it is not currently exploitable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

TEMPLATE_RENDER_TOOL: dict[str, Any] = {
    "name": "template_render",
    "description": "Render a Jinja2 template string or file with provided variables. Returns the rendered output.",
    "input_schema": {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": "Template string (mutually exclusive with path)",
            },
            "path": {
                "type": "string",
                "description": "Template file path (relative to repo root)",
            },
            "vars": {
                "type": "object",
                "description": "Variables to inject into the template",
            },
        },
        "required": [],
    },
}


def template_render_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core template_render logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path` (both code paths) and the switch to a
    sandboxed Jinja2 environment (defense in depth — see this module's
    docstring finding #3)."""
    template_str = inp.get("template")
    path = inp.get("path")
    if path:
        policy = check_path_in_worktree(str(path), worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
    variables = dict(inp.get("vars") or {})
    try:
        from jinja2.sandbox import SandboxedEnvironment

        if path:
            template_str = (root / str(path)).read_text(encoding="utf-8")
        if not template_str:
            return "[ERROR] Provide either template or path"
        return str(
            SandboxedEnvironment().from_string(str(template_str)).render(**variables)
        )
    except ImportError:
        src = (
            str(template_str)
            if template_str
            else ((root / str(path)).read_text(encoding="utf-8") if path else "")
        )
        if not src:
            return "[ERROR] jinja2 not installed and no template provided"
        for k, v in variables.items():
            src = src.replace("{{" + k + "}}", str(v)).replace(
                "{{ " + k + " }}", str(v)
            )
        return src
    except Exception as e:
        return f"[ERROR] template_render: {e}"
