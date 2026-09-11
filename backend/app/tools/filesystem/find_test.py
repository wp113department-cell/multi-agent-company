"""find_test tool — tool_enhance.md productionization pass, tool #140
(2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_test
Old path: app/agents/tools.py (`_FIND_TEST_TOOL` schema dict) with TWO
    real, DIVERGENT implementations: `find_test_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (a separately-drifted, narrower reimplementation
    — see findings below).
New path: app/tools/filesystem/find_test.py (this file) —
    `FIND_TEST_TOOL`, `find_test_handler`. BOTH real call sites now
    delegate to this one shared handler, built from the already-
    correct `make_chat_handlers()` implementation.
Affected agents: per tool_inventory.json, agents declaring `find_test`
    in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler, dropping its `shell=True`
    subprocess invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's "find_test"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_find_test_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_test.md.
---------------------------------------------------------------------------

No path field in this tool's schema at all (only `function_name`) —
worktree-boundary escape does not apply. Checked live for the
shell-injection / grep-own-flag-collision class already established
repeatedly this initiative for `chat_agent.py`'s `shell=True` grep
dispatches (find_api/find_route/find_sql/inspect_schema/explain_query/
find_config): does NOT apply here, verified directly rather than
assumed — every pattern this tool builds always embeds `function_name`
INSIDE a larger literal prefix (`f"def test_{fn}"` etc.), so the
constructed regex argument can never itself begin with `-`, and
`chat_agent.py`'s own `shlex.quote()` around the whole pattern
correctly neutralizes shell metacharacters. Proved live: a real
shell-metacharacter payload (`"; touch <marker>; echo x"`) produced no
injected command and no marker file.

One real finding — a functionality-divergence bug:
`chat_agent.py`'s dispatch is a separately-drifted, narrower
reimplementation of the same tool, missing real capability the
canonical `make_chat_handlers()` implementation already has:
1. Only 2 of the 3 search patterns (`def test_{fn}`, `def
   test.*{fn}`) — missing the third, `test.*["'].*{fn}`, which is what
   catches JS/TS `test("...")`/`it("...")`-style test descriptions.
2. `--include=*.test.ts --include=*.spec.ts` instead of the canonical
   `--include=*.ts` — narrower, missing plain `.ts` test files that
   don't follow the `.test.ts`/`.spec.ts` naming convention.
3. When nothing is found, it silently returns `_run_subprocess`'s own
   generic `"(no output)"` placeholder instead of the tool's intended,
   clear `"No tests found for '<name>'"` message.
Proved live: a real JS-style `test("special_widget renders correctly",
...)` file was found by the canonical implementation but silently
missed by `chat_agent.py`'s dispatch, returning the unhelpful
`"(no output)"` instead of either the real match or a clear
"not found" message.

Fixed via full replacement: `chat_agent.py`'s dispatch now delegates
to the same shared, canonical `find_test_handler()` (list-args
subprocess, no `shell=True`, all three patterns, the correct
`--include` filters, and the correct "No tests found" fallback
message) rather than keeping its own drifted reimplementation.
"""

from __future__ import annotations

import subprocess
from typing import Any

FIND_TEST_TOOL: dict[str, Any] = {
    "name": "find_test",
    "description": "Find test functions that test a specific function or feature by name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "function_name": {
                "type": "string",
                "description": "Name of the function or feature to find tests for",
            },
        },
        "required": ["function_name"],
    },
}


def find_test_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core find_test logic shared by both real call sites."""
    ftest_fn = str(inp["function_name"])
    patterns = [
        f"def test_{ftest_fn}",
        f"def test.*{ftest_fn}",
        f"test.*[\"'].*{ftest_fn}",
    ]
    exclude = [
        "--exclude-dir=node_modules",
        "--exclude-dir=.venv",
        "--exclude-dir=__pycache__",
    ]
    ftest_out: list[str] = []
    for pt in patterns:
        try:
            r = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-E",
                    pt,
                    repo_path,
                    "--include=*.py",
                    "--include=*.ts",
                ]
                + exclude,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.stdout.strip():
                ftest_out.append(r.stdout[:2000])
        except Exception:
            pass
    return (
        "\n".join(ftest_out)[:5000]
        if ftest_out
        else f"No tests found for '{ftest_fn}'"
    )
