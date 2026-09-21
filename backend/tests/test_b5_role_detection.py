"""Verification batch B5 (#489) — professional-role detection sees the real agent roster and does not
block the event loop.

Defects proven before the fix: a freshly started server had only 4 agents registered (pm, bug_fix, qa,
executive) because agent modules register on import and are imported lazily, so every message was
classified against a 4-entry roster; and the classification is a blocking Anthropic request that was
called straight from the async chat handler.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parent.parent)


def test_a_fresh_process_classifies_against_the_full_roster() -> None:
    code = (
        "import app.main\n"
        "from app.fleet.capability_registry import get_capability_registry\n"
        "before = len(get_capability_registry().all())\n"
        "from app.agents.role_detection import _load_catalog\n"
        "print(before, len(_load_catalog()))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
        env={**__import__("os").environ, "RBAC_ENABLED": "false"},
    )
    assert out.returncode == 0, out.stderr[-500:]
    before, after = map(int, out.stdout.split()[-2:])
    assert before <= 10 and after >= 50


def test_the_chat_handler_runs_role_detection_off_the_event_loop() -> None:
    import inspect

    from app.agents import chat_agent

    source = inspect.getsource(chat_agent.ChatAgent.run)
    assert "asyncio.to_thread(" in source and "detect_professional_role" in source
    assert "= detect_professional_role(" not in source
