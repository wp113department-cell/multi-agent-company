"""estimate_complexity tool — tool_enhance.md productionization pass,
tool #110 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: estimate_complexity
Old path: app/agents/tools.py (`_ESTIMATE_COMPLEXITY_TOOL` schema
    dict) with TWO real, byte-identical implementations:
    `sp_estimate_complexity` (`make_sprint_planner_handlers`) and
    `estimate_complexity_h` (inside `make_chat_handlers()`).
    `app/agents/chat_agent.py` had ZERO dispatch branch for this tool
    despite it being advertised in `CHAT_TOOLS` — the same "advertised
    but never dispatched" class already established for tools
    #4/#6/#22/#25/#33/#44/#45/#46/#48/#100/#103.
New path: app/tools/execution/estimate_complexity.py (this file) —
    `ESTIMATE_COMPLEXITY_TOOL`, `estimate_complexity_handler`. Both
    real implementations now delegate to this one shared handler, and
    a new real dispatch has been wired into `chat_agent.py`.
Affected agents: per tool_inventory.json, agents declaring
    `estimate_complexity` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (new
    real dispatch added).
Affected registries: none — app/fleet/tool_manifest.py's
    "estimate_complexity" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_estimate_complexity_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/estimate_complexity.md.
---------------------------------------------------------------------------

One real, empirically-verified finding: **"advertised but never
dispatched"** (see migration report above) — every real interactive
call would have hit "Unknown tool".

No LLM-controlled input can cause any real effect beyond the returned
text: `description` is only measured with `str.split()` (word count),
and `context_paths` is only measured with `len()` — the actual path
STRINGS are never read from disk, resolved, or passed to any
subprocess, so the usual worktree-escape/injection classes established
throughout this initiative are structurally impossible here regardless
of what a caller puts in that list. The heuristic itself (word count +
`10 * file count`, bucketed into XS/S/M/L/XL) was already correct and
identical across both implementations — reused verbatim, not
reinvented.
"""

from __future__ import annotations

from typing import Any


def estimate_complexity_handler(inp: dict[str, Any]) -> str:
    """Core estimate_complexity logic shared by both real call sites."""
    description = str(inp.get("description", ""))
    context_paths = list(inp.get("context_paths", []))
    word_count = len(description.split())
    file_count = len(context_paths)
    score = word_count + file_count * 10
    if score < 30:
        size = "XS"
    elif score < 80:
        size = "S"
    elif score < 200:
        size = "M"
    elif score < 500:
        size = "L"
    else:
        size = "XL"
    return f"Estimated complexity: {size} (word_count={word_count}, context_files={file_count}, score={score})"


ESTIMATE_COMPLEXITY_TOOL: dict[str, Any] = {
    "name": "estimate_complexity",
    "description": "Estimate task complexity as XS/S/M/L/XL based on heuristics (description token count, file scope).",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Task or feature description to estimate",
            },
            "context_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of files/dirs likely involved",
            },
        },
        "required": ["description"],
    },
}
