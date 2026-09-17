# Tool #220 — `list_deploy_artifacts` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

A closure factory `make_list_deploy_artifacts_handler(repo_path)` in
`app/agents/tools.py`, bound to `repo_path` (matching the file's own
established convention for per-repo-scoped tools, e.g.
`_make_write_file_handler(root)`). Shared by exactly 1 real agent,
confirmed via direct grep — `deployment_guide_doc_agent` — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

Real filesystem discovery of a project's actual deployment-relevant
files (Dockerfiles, docker-compose files, Procfile, GitHub Actions
workflows, systemd units, k8s/terraform manifests) via a fixed set of
17 hardcoded glob patterns — designed so `deployment_guide_doc_agent`
can read what actually exists (via `read_file`) before writing a
deployment guide, rather than inventing a deploy mechanism the project
doesn't have. Takes no meaningful input at all — schema declares zero
properties, `inp` is unused.

Already has thorough real-filesystem test coverage in
`tests/test_audit_q_batch10_deployment_external_git_docs.py`
(`TestListDeployArtifacts`: real deploy files found and non-deploy
files correctly excluded, empty-repo returns an empty list, no
duplicate entries across overlapping glob patterns) — re-read and
re-verified as still passing before making any change.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion, not a premature green flag. Specifically
investigated and ruled out:

- **Injection surface**: none exists — every glob pattern is
  fixed/hardcoded, never built from `inp` (which is entirely unused).
  The only variable is `repo_path`, a trusted, framework-supplied
  value, never raw end-user input at the tool-call layer.
- **Expensive full-tree walk / DoS**: every pattern is single- or
  double-directory-level only (`Dockerfile`, `*/Dockerfile`,
  `*/*/Dockerfile`, etc.) — none use recursive `**` globbing, matching
  the tool's own original design comment ("never a full recursive tree
  walk — would hit node_modules/.venv/repos/"). Bounded cost
  regardless of repo size.
- **Crash on a nonexistent `repo_path`**: proved live —
  `make_list_deploy_artifacts_handler("/tmp/does-not-exist")({})`
  returns `{"deploy_artifacts": []}` cleanly; `Path.glob()` on a
  missing directory returns no matches rather than raising.
- **Symlink content-leak risk**: a malicious symlink planted at one of
  the fixed artifact names (e.g. a `Dockerfile` symlink pointing
  outside the repo) cannot leak file contents through this tool — it
  only ever returns the relative NAME/path of a matched file, never
  reads or returns file contents. Actual reading happens later, if at
  all, via `read_file`, which has its own independent path-safety
  hardening from earlier tools in this initiative.

## Changes made

Extracted into `app/tools/filesystem/list_deploy_artifacts.py`
(`LIST_DEPLOY_ARTIFACTS_TOOL`, `make_list_deploy_artifacts_handler`)
with zero behavior change. `app/agents/tools.py` re-exports both names
for backward compatibility — the real consumer agent
(`deployment_guide_doc_agent`) continues
`from app.agents.tools import make_list_deploy_artifacts_handler`
unchanged, verified by identity. Also removed the now-unused
`typing.Callable` import from `app.agents.tools` (its only remaining
use was this closure's own return-type annotation, now moved to the
new module).

## Tests

Existing `TestListDeployArtifacts` (3 tests) and
`TestDeploymentGuideDocAgent` re-run and confirmed passing unchanged —
full file (58 tests) also re-run clean.

New file `tests/test_list_deploy_artifacts_hardening.py`, 6 tests:
schema check, `CHAT_TOOLS` non-membership, the nonexistent-`repo_path`
robustness proof, an arbitrary-input-is-ignored proof (confirms this
tool never behaves differently based on `inp`, matching its
zero-property schema), and two object-identity proofs (the re-exported
schema in `tools.py`, and the real consumer agent's imported factory
function) that the modularization introduced no behavior change.

## Regression

This tool's own new hardening tests (6/6 pass) plus
`test_audit_q_batch10_deployment_external_git_docs.py` +
`test_new_tools.py` + `test_final_session.py` (125 passed total).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean, after removing the now-unused `Callable` import)
BEFORE claiming GREEN_FLAG. Also verified `CHAT_TOOLS` still has zero
duplicate names (186 entries) and that `app.agents.tools` reloads
cleanly.

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect — confirmed via live execution against a
nonexistent repo path, a review of every glob pattern for injection
and DoS surface, and a symlink content-leak analysis. Modularized
purely for consistency with this initiative's established pattern, no
functionality lost — the real consumer agent verified via identity to
still use the exact same shared factory function. Agent alignment
verified: PASS.
