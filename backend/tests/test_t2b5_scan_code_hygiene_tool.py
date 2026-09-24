"""T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396) — the scan_code_hygiene tool
wiring itself (architecture_reviewer + cleanup_agent), on top of the
detector unit tests in test_t2b5_code_hygiene.py.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.tools import (
    ARCH_REVIEWER_TOOLS,
    CLEANUP_AGENT_TOOLS,
    make_arch_reviewer_handlers,
    make_cleanup_agent_handlers,
)


def _names(tools: list[dict[str, object]]) -> set[str]:
    return {str(t["name"]) for t in tools}


def test_tool_is_declared_for_both_real_consumer_agents() -> None:
    assert "scan_code_hygiene" in _names(ARCH_REVIEWER_TOOLS)
    assert "scan_code_hygiene" in _names(CLEANUP_AGENT_TOOLS)


def test_architecture_reviewer_handler_runs_a_real_scan(tmp_path: Path) -> None:
    (tmp_path / "orphan.py").write_text(
        "def never_called():\n    pass\n", encoding="utf-8"
    )
    handlers = make_arch_reviewer_handlers(str(tmp_path))
    result = handlers["scan_code_hygiene"]({"directory": ""})
    assert "unused files" in result or "duplicate" in result or "broken" in result


def test_cleanup_agent_handler_runs_a_real_scan(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "import totally_fake_module_xyz_never_real\n", encoding="utf-8"
    )
    handlers = make_cleanup_agent_handlers(str(tmp_path))
    result = handlers["scan_code_hygiene"]({"directory": ""})
    assert "totally_fake_module_xyz_never_real" in result


def test_agent_contracts_declare_the_new_tool() -> None:
    from app.agents.architecture_reviewer import AGENT_CONTRACT as ARCH_CONTRACT
    from app.agents.cleanup_agent import AGENT_CONTRACT as CLEANUP_CONTRACT

    assert "scan_code_hygiene" in ARCH_CONTRACT["allowed_tools"]
    assert "scan_code_hygiene" in CLEANUP_CONTRACT["allowed_tools"]
