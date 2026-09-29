"""Evidence script (Audit 02/05): do "write_docs" agents really only write docs?

For every agent whose AGENT_CONTRACT permissions include write_docs (and not
write_repo/write_worktree/write_code), capture the REAL tool_handlers it passes
to run_agent_graph (graph intercepted, no LLM), then call its write_file /
edit_file handler against a throwaway git repo, trying to create/modify a .py
file. Reports which agents' handlers actually wrote code.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/docs_agent_write_probe.py <scratch_dir>
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.getcwd())
SCRATCH = Path(sys.argv[1])

from app.agents import base_graph  # noqa: E402
from app.fleet import capability_registry as cr  # noqa: E402

cr.ensure_all_agents_registered()


class _Captured(Exception):
    pass


def _fresh_repo(name: str) -> Path:
    d = SCRATCH / f"wprobe_{name}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "main.py").write_text("print('original')\n")
    (d / "README.md").write_text("# readme\n")
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "add", "."], cwd=d, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"],
        cwd=d,
        check=True,
    )
    return d


def _args(fn: Any, repo: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for n, p in inspect.signature(fn).parameters.items():
        if p.default is not inspect.Parameter.empty:
            if n == "repo_path":
                out[n] = repo
            continue
        low = n.lower()
        if "task_id" in low:
            out[n] = 1
        elif "repo" in low or "path" in low or "worktree" in low:
            out[n] = repo
        elif low.endswith("s"):
            out[n] = []
        else:
            out[n] = "probe"
    return out


results = []
for path in sorted(Path("app/agents").glob("*.py")):
    mod_name = f"app.agents.{path.stem}"
    try:
        mod = importlib.import_module(mod_name)
    except Exception:
        continue
    c = getattr(mod, "AGENT_CONTRACT", None)
    if not isinstance(c, dict):
        continue
    perms = set(c.get("permissions") or [])
    if "write_docs" not in perms or perms & {"write_repo", "write_worktree", "write_code"}:
        continue
    name = c["name"]
    repo = _fresh_repo(name)
    handlers: dict[str, Any] = {}
    offered: set[str] = set()

    def _fake(**kw: Any) -> Any:
        handlers.update(kw.get("tool_handlers") or {})
        offered.update(t.get("name") for t in (kw.get("tools") or []) if isinstance(t, dict))
        raise _Captured()

    for fn_name, fn in vars(mod).items():
        if not (fn_name.startswith("run_") and inspect.isfunction(fn)):
            continue
        if fn.__module__ != mod_name or inspect.iscoroutinefunction(fn):
            continue
        orig = getattr(mod, "run_agent_graph", None)
        try:
            if orig is not None:
                setattr(mod, "run_agent_graph", _fake)
            base_graph.run_agent_graph = _fake  # type: ignore[assignment]
            try:
                fn(**_args(fn, str(repo)))
            except _Captured:
                pass
            except Exception:
                pass
        finally:
            if orig is not None:
                setattr(mod, "run_agent_graph", orig)
        if handlers:
            break

    row: dict[str, Any] = {"agent": name, "write_tools": {}, "offered_write_tools": sorted(offered & {"write_file", "edit_file"})}
    for tool, args in (
        ("write_file", {"path": "evil.py", "content": "import os\n"}),
        ("edit_file", {"path": "main.py", "old_string": "original", "new_string": "hacked"}),
    ):
        # only tools actually OFFERED to the model matter: base_graph refuses
        # to dispatch any unadvertised tool (base_graph.py _allowed_tool_names)
        h = handlers.get(tool) if tool in offered else None
        if h is None:
            continue
        try:
            r = h(args)
        except Exception as e:  # noqa: BLE001
            r = f"[raised] {type(e).__name__}: {e}"
        wrote = (repo / "evil.py").exists() or "hacked" in (repo / "main.py").read_text()
        row["write_tools"][tool] = {"code_written": wrote, "result": str(r)[:140]}
    # overwriting EXISTING code must be refused for every write_docs agent
    h = handlers.get("write_file") if "write_file" in offered else None
    if h is not None:
        before = (repo / "main.py").read_text()
        try:
            r = h({"path": "main.py", "content": "OVERWRITTEN\n"})
        except Exception as e:  # noqa: BLE001
            r = f"[raised] {e}"
        row["overwrite_existing_code"] = {
            "overwritten": (repo / "main.py").read_text() != before,
            "result": str(r)[:140],
        }
    # and the legitimate case must still work
    h = handlers.get("write_file")
    if h is not None:
        try:
            h({"path": "docs/guide.md", "content": "# ok\n"})
        except Exception:
            pass
        row["md_write_works"] = (repo / "docs" / "guide.md").exists()
    results.append(row)
    shutil.rmtree(repo, ignore_errors=True)

bad = [r for r in results if any(v["code_written"] for v in r["write_tools"].values())]
overwrote = [r["agent"] for r in results if r.get("overwrite_existing_code", {}).get("overwritten")]
out = {"write_docs_agents_probed": len(results), "created_new_code_file": [r["agent"] for r in bad], "overwrote_existing_code": overwrote, "all": results}
Path(__file__).with_name("docs_agent_write_probe.out.json").write_text(json.dumps(out, indent=1))
print(f"probed={len(results)} created_new_code_file={[r['agent'] for r in bad]} overwrote_existing_code={overwrote}")
print("md write broken for:", [r["agent"] for r in results if r.get("md_write_works") is False])
