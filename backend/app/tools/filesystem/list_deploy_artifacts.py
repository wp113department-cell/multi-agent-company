"""list_deploy_artifacts tool — tool_enhance.md productionization pass,
tool #220 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_deploy_artifacts
Old path: app/agents/tools.py (`_LIST_DEPLOY_ARTIFACTS_TOOL` schema
    dict, `make_list_deploy_artifacts_handler(repo_path)` — a closure
    factory bound to repo_path, matching this file's own established
    convention for per-repo-scoped tools).
New path: app/tools/filesystem/list_deploy_artifacts.py (this file) —
    `LIST_DEPLOY_ARTIFACTS_TOOL`, `make_list_deploy_artifacts_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `deployment_guide_doc_agent` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import make_list_deploy_artifacts_handler`
    unchanged.
Affected tests: `tests/test_audit_q_batch10_deployment_external_git_docs.py`'s
    `TestListDeployArtifacts` (3 tests: real deploy files found,
    empty-repo returns empty list, no duplicate entries across
    overlapping globs) and `TestDeploymentGuideDocAgent` already
    exercise this tool thoroughly via real filesystem operations
    against real tmp_path repos — re-run and confirmed passing
    unchanged. New tests added: see
    tests/test_list_deploy_artifacts_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_deploy_artifacts.md.
---------------------------------------------------------------------------

No security vulnerability and no functional bug found — this audit's
real conclusion. Takes no meaningful input at all (schema declares
zero properties, `inp` is unused) — the only variable is `repo_path`,
a trusted, framework-supplied value (never raw end-user input at the
tool-call layer), so there is no injection surface to test against.

Investigated and confirmed safe:
  - Every glob pattern is fixed/hardcoded (never built from `inp`), and
    every pattern is single- or double-directory-level only (no `**`
    recursive glob) — proved this cannot turn into an expensive
    full-tree walk even on a huge repo (the tool's own design goal,
    per its original comment: "never a full recursive tree walk (would
    hit node_modules/.venv/repos/)").
  - A nonexistent `repo_path` does not crash — `Path.glob()` on a
    missing directory returns no matches rather than raising, proved
    live: `make_list_deploy_artifacts_handler("/tmp/does-not-exist")({})`
    returns `{"deploy_artifacts": []}` cleanly.
  - A malicious symlink planted at one of the fixed artifact names
    (e.g. a `Dockerfile` symlink pointing outside the repo) cannot leak
    file contents through this tool — it only ever returns the
    relative NAME/path of a matched file, never reads or returns file
    contents (that happens later, if at all, via `read_file`, which
    has its own independent path-safety hardening).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

LIST_DEPLOY_ARTIFACTS_TOOL: dict[str, Any] = {
    "name": "list_deploy_artifacts",
    "description": "Real filesystem discovery of this project's actual deployment-relevant files: Dockerfiles, docker-compose files, Procfile, .github/workflows/*.yml, scripts/systemd/*.service|.timer, and k8s/terraform manifests if present. Read each with read_file before writing a deployment guide — never invent a deploy mechanism this project doesn't actually have.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_DEPLOY_ARTIFACT_GLOBS: tuple[str, ...] = (
    "Dockerfile",
    "*/Dockerfile",
    "*/*/Dockerfile",
    "Dockerfile.*",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "Procfile",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "scripts/systemd/*.service",
    "scripts/systemd/*.timer",
    "k8s/*.yaml",
    "k8s/*.yml",
    "kubernetes/*.yaml",
    "kubernetes/*.yml",
    "terraform/*.tf",
    "Vagrantfile",
)


def make_list_deploy_artifacts_handler(
    repo_path: str,
) -> Callable[[dict[str, Any]], str]:
    root = Path(repo_path)

    def list_deploy_artifacts(inp: dict[str, Any]) -> str:
        import json as _json

        found: list[str] = []
        seen: set[str] = set()
        for pattern in _DEPLOY_ARTIFACT_GLOBS:
            for p in sorted(root.glob(pattern)):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(root))
                if rel not in seen:
                    seen.add(rel)
                    found.append(rel)
        return _json.dumps({"deploy_artifacts": found}, indent=2)

    return list_deploy_artifacts
