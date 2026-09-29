"""Evidence script (Audit 02): per-agent scorecard built from RUNTIME capture.

For every app/agents/*.py module that declares AGENT_CONTRACT, this calls the
module's real run_* entry point with run_agent_graph() intercepted — so no LLM
call happens — and records the exact kwargs the agent passes to the graph:
tools, verification config, model, Fleet OS flags, task_id, role_name.
Static checks (role file sections, capability uniqueness, dispatch call sites)
are layered on top.

Run from backend/:
    .venv/bin/python ../What_is/AUDIT_REPORT/evidence/agent_scorecard.py <tmp_repo>
Writes agent_scorecard.out.json next to this file.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.getcwd())
TMP_REPO = sys.argv[1]

from app.agents import base_graph  # noqa: E402
from app.fleet import capability_registry as cr  # noqa: E402
from app.fleet.model_router import get_model_router  # noqa: E402
from app.fleet.tool_manifest import TOOL_MANIFEST, is_high_risk  # noqa: E402

cr.ensure_all_agents_registered()
REG = {e.name: e for e in cr._registry.all()}
ROUTER = get_model_router()
ROUTED = set(ROUTER.all_agents()) if hasattr(ROUTER, "all_agents") else set()
ROLES = Path("roles")
SECTIONS = [
    "Non-Responsibilities",
    "Success Criteria",
    "Failure Conditions",
    "Output Contract",
    "Quality Gates",
    "Edge Cases",
    "Escalation",
]
WRITE_TOOLS = {
    "write_file", "edit_file", "apply_patch", "insert_before", "insert_after",
    "delete_block", "delete_file", "move_file", "rename_file", "create_file",
    "replace_in_file", "multi_edit", "git_commit", "git_commit_change",
}
EXEC_TOOLS = {"bash", "run_command", "run_background", "run_parallel_commands"}

# every app/ source file, for dispatch call-site search (excluding the agent
# module itself and tests)
APP_SRC = {
    str(p): p.read_text(errors="ignore")
    for p in Path("app").rglob("*.py")
}


class _Captured(Exception):
    pass


captured: dict[str, Any] = {}


def _fake_run_agent_graph(*args: Any, **kwargs: Any) -> Any:
    captured.clear()
    captured.update(kwargs)
    raise _Captured()


def _timeout(*_: Any) -> None:
    raise TimeoutError()


def _fill_args(fn: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, p in inspect.signature(fn).parameters.items():
        if p.default is not inspect.Parameter.empty:
            if name == "repo_path":
                out[name] = TMP_REPO
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        low = name.lower()
        if "task_id" in low:
            out[name] = 424242
        elif "repo" in low or "path" in low or "worktree" in low:
            out[name] = TMP_REPO
        elif "images" in low or "files" in low or low.endswith("s"):
            out[name] = []
        else:
            out[name] = "audit scorecard probe"
    return out


def _role_sections(name: str) -> tuple[bool, int, list[str]]:
    p = ROLES / f"{name}.md"
    if not p.exists():
        return False, 0, SECTIONS
    txt = p.read_text(errors="ignore")
    missing = [s for s in SECTIONS if s.lower() not in txt.lower()]
    return True, len(txt), missing


def _dispatch_sites(module: str, fn_names: list[str], agent_name: str) -> list[str]:
    hits = []
    own = f"app/{module.split('.', 1)[1].replace('.', '/')}.py"
    for path, src in APP_SRC.items():
        if path == own:
            continue
        if any(f in src for f in fn_names) or f'"{module}"' in src:
            hits.append(path)
    return sorted(set(hits))


rows = []
tag_owner: dict[str, list[str]] = {}
for path in sorted(Path("app/agents").glob("*.py")):
    mod_name = f"app.agents.{path.stem}"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:  # noqa: BLE001
        rows.append({"module": mod_name, "import_error": repr(e)})
        continue
    contract = getattr(mod, "AGENT_CONTRACT", None)
    if not isinstance(contract, dict):
        continue
    name = contract.get("name", path.stem)
    run_fns = [
        n
        for n, obj in vars(mod).items()
        if n.startswith("run_")
        and inspect.isfunction(obj)
        and obj.__module__ == mod_name
    ]
    vcfgs = [v for v in vars(mod).values() if isinstance(v, base_graph.VerificationConfig)]

    # --- runtime capture -------------------------------------------------
    cap: dict[str, Any] = {}
    cap_err = None
    orig_mod = getattr(mod, "run_agent_graph", None)
    orig_base = base_graph.run_agent_graph
    for fn_name in run_fns:
        fn = getattr(mod, fn_name)
        if inspect.iscoroutinefunction(fn):
            continue
        try:
            if orig_mod is not None:
                setattr(mod, "run_agent_graph", _fake_run_agent_graph)
            base_graph.run_agent_graph = _fake_run_agent_graph
            signal.signal(signal.SIGALRM, _timeout)
            signal.alarm(20)
            try:
                fn(**_fill_args(fn))
            except _Captured:
                pass
            except Exception as e:  # noqa: BLE001
                if not captured:
                    cap_err = f"{fn_name}: {type(e).__name__}: {str(e)[:120]}"
            finally:
                signal.alarm(0)
            if captured:
                cap = dict(captured)
                cap["_fn"] = fn_name
                break
        finally:
            if orig_mod is not None:
                setattr(mod, "run_agent_graph", orig_mod)
            base_graph.run_agent_graph = orig_base

    tools_passed = [
        t.get("name") for t in (cap.get("tools") or []) if isinstance(t, dict)
    ]
    vcfg = cap.get("verification_cfg") or (vcfgs[0] if vcfgs else None)
    enforce = dict(getattr(vcfg, "enforce_in_result", {}) or {})
    settable = set((getattr(vcfg, "set_by", {}) or {}).values())
    for attr in ("bash_patterns", "bash_set_by", "set_by_bash"):
        settable |= set((getattr(vcfg, attr, {}) or {}).keys())
    dead_keys = sorted(k for k in enforce.values() if k not in settable)
    allowed = contract.get("allowed_tools") or []
    perms = contract.get("permissions") or []
    read_only = not any(p in perms for p in ("write_repo", "write", "execute"))
    write_in_ro = sorted(set(tools_passed) & (WRITE_TOOLS | EXEC_TOOLS)) if read_only else []
    undeclared_high_risk = sorted(
        t for t in tools_passed if is_high_risk(t) and t not in allowed
    )
    not_in_manifest = sorted(t for t in tools_passed if t not in TOOL_MANIFEST)
    role_ok, role_len, missing_sections = _role_sections(name)
    reg = REG.get(name)
    for tag in (reg.capabilities if reg else []):
        tag_owner.setdefault(tag, []).append(name)
    routed_model = ROUTER.route(name).model
    rows.append(
        {
            "agent": name,
            "module": mod_name,
            "run_fns": run_fns,
            "contract_io": bool(contract.get("input_types")) and bool(contract.get("output_types")),
            "verification_cfg": vcfg is not None,
            "enforce_in_result": enforce,
            "dead_enforce_keys": dead_keys,
            "registered": reg is not None,
            "role_file": role_ok,
            "role_chars": role_len,
            "role_missing_sections": missing_sections,
            "permissions": perms,
            "read_only": read_only,
            "tools_passed": tools_passed,
            "write_or_exec_in_read_only": write_in_ro,
            "undeclared_high_risk": undeclared_high_risk,
            "tools_not_in_manifest": not_in_manifest,
            "routed_model": routed_model,
            "in_agent_models_json": name in ROUTED,
            "captured_role_name": cap.get("role_name"),
            "captured_task_id": cap.get("task_id"),
            "flags": {
                k: cap.get(k)
                for k in ("enable_planning", "enable_memory", "enable_reflection", "enable_lesson")
            },
            "capture_error": None if cap else cap_err,
            "dispatch_sites": _dispatch_sites(mod_name, run_fns, name),
        }
    )

collisions = {t: o for t, o in tag_owner.items() if len(o) > 1}
out = {
    "agents": rows,
    "capability_tag_collisions": collisions,
    "registered_without_contract_module": sorted(
        set(REG) - {r.get("agent") for r in rows}
    ),
}
Path(__file__).with_name("agent_scorecard.out.json").write_text(json.dumps(out, indent=1, default=str))
print(f"agents={len(rows)} collisions={len(collisions)}")
