# Tool Enhancement Tracking List

Generated programmatically from tool_inventory.json — 274 tools total.

Status legend: PENDING | IN_PROGRESS | GREEN_FLAG | YELLOW_FLAG | RED_FLAG

Order: risk_level (high->medium->low->unknown), then agent_count desc (most-used first), then name.

| # | Tool | Risk | Agents | Manifest | Tests | Status |
|---|---|---|---|---|---|---|
| 1 | bash | high | 23 | yes | 48 | GREEN_FLAG — see docs/tool_productionization/bash.md (9/10 remaining variants sandboxed via a real toolchain image + verified DB reachability; orphaned-container-on-timeout bug found+fixed; read-only root FS + tmpfs + non-root hardening added; tests/security/test_bash_security.py added, 84 adversarial tests; ChatGPT 20-item checklist evaluated item-by-item — applied where real, explicitly skipped w/ reasoning where not. 2 real non-blocking limitations logged: network not deny-by-default, cancellation-triggered cleanup not wired. infra_dry_run stays unsandboxed by design, documented. CORRECTED 2026-08-16 during tool #9 audit: real cwd sandbox-boundary escape found + fixed, see bash.md's own "Correction" section — GREEN FLAG reaffirmed after the fix) |
| 2 | create_pr | high | 1 | yes | 27 | GREEN_FLAG — see docs/tool_productionization/create_pr.md. Pass 1: 2 real implementations found, confirmation gate added to chat_agent.py, timeouts fixed, shared dispatch-authorization gap in base_graph.py fixed (~76 agents). MODULARIZED into app/tools/git/pull_request.py (initially missed, corrected after user caught it) with full TOOL PATH MIGRATION REPORT. Pass 2 (2nd ChatGPT review, evaluated item-by-item): repo/branch/base identity verification, no-diff guard (real regression closed — explicit title+body used to skip the check), fail-closed approval gate on the standalone handler (create_pr_require_approval), LLM/caller output sanitization, secrets redacted from diff before LLM (biggest finding), gh auth preflight, duplicate-PR idempotency, real PR-URL extraction. Full suite re-confirmed clean (4772 passed) after both passes |
| 3 | delegate_to_agent | high | 1 | yes | 21 | GREEN_FLAG — see docs/tool_productionization/delegate_to_agent.md. Started from a mature base (real depth/cycle/policy/budget/timeout guards already existed in app/agents/delegation.py, 19 pre-existing adversarial tests — inventory's "0 test files" was a false negative from its exact-string-match heuristic, verified by reading the file). Real fixes: budget wasn't actually decrementing across repeated calls in one run (contradicted config.py's own documented contract); backend_dev/frontend_dev were listed in delegation_allowed_matrix but never had the tool wired in (real dead-policy gap, an AGENT ALIGNMENT finding). MODULARIZED into app/tools/agents/delegate.py with full TOOL PATH MIGRATION REPORT; every real consumer (bug_fix, backend_dev, frontend_dev, test_delegation.py) updated to import from the new location. Full suite clean (4773 passed) |
| 4 | git_push | high | 1 | yes | 30 | GREEN_FLAG — see docs/tool_productionization/git_push.md. Fixed force-push not getting the "extra confirmation" its own tool description promised (now distinguishes protected-branch force-push with a stronger warning, config-driven branch list). Bigger finding: confirmed via repo-wide grep that `session` is never non-None for any real caller of make_chat_handlers() — removed dead session.request_confirmation() plumbing from 8 handlers (git_push, bash-dangerous, docker_compose, undo_changes, run_migration, seed_database, npm_install, pip_install). docker_compose('up') was the one LIVE exception (docker_agent genuinely has it in allowed_tools) — fixed with a fail-closed config gate + added a real confirmation gate to chat_agent.py's own docker_compose('up') dispatch, which had none. Also found+fixed: npm_install/npm_run/pip_install advertised to the interactive chat LLM via CHAT_TOOLS but never dispatched in chat_agent.py — always returned "Unknown tool". MODULARIZED into app/tools/git/push.py. Full suite clean (4794 passed) |
| 5 | git_reset | high | 1 | yes | 14 | GREEN_FLAG — see docs/tool_productionization/git_reset.md. Found + fixed a REAL, empirically-verified confirmation bypass: `git reset --soft --hard HEAD` actually performs a hard reset (git takes the last mode flag as authoritative, verified against a real repo — an uncommitted change was silently discarded). Neither implementation validated `ref`, so mode="soft" + ref="--hard" bypassed the hard-mode confirmation entirely and silently discarded uncommitted work. Fixed via a shared validate_git_reset_inputs() chokepoint (rejects out-of-schema modes + flag-shaped refs) used by both real call sites. MODULARIZED into app/tools/git/reset.py. Full suite clean (4807 passed) |
| 6 | github_create_pr | high | 1 | yes | 7 | GREEN_FLAG — see docs/tool_productionization/github_create_pr.md. Found a live "advertised but never dispatched" bug in chat_agent.py (same class as npm_install/pip_install from tool #4 — always returned "Unknown tool"). Found it was also a second, unhardened, separately-maintained duplicate of create_pr (bare `gh pr create`, zero confirmation, zero repo/branch/base checks). Fixed by delegating both real call sites to the already-hardened create_pr implementation instead of duplicating its hardening a second time — verified the delegation is real (create_pr's no-diff guard + branch-safety check both genuinely fire under the github_create_pr name). MODULARIZED (schema added to the existing app/tools/git/pull_request.py rather than a new near-empty file, since it has no logic of its own anymore). Full suite clean (4813 passed) |
| 7 | propose_subtask | high | 1 | yes | 35 | GREEN_FLAG — see docs/tool_productionization/propose_subtask.md. Started from a mature base (real validation/integration logic already in app.pipeline.dynamic_subtasks, 33 pre-existing tests — inventory's "0 test files" was another false negative from its exact-string heuristic, same class as tool #3). Found the same gap class as tool #3: config.py's dynamic_subtask_allowed_matrix already listed frontend_dev as an allowed proposer, and manager.py's own comment explicitly named frontend_dev wiring as pending ("a trivial, identical-shape follow-up") — never actually done. Wired it for real (AGENT_CONTRACT, subtask_proposal_sink param, generalized the manager.py gating condition), verified end-to-end. MODULARIZED into app/tools/agents/propose_subtask.py. Full suite clean (4815 passed) |
| 8 | run_migration | high | 1 | yes | 17 | GREEN_FLAG — see docs/tool_productionization/run_migration.md. Found + fixed a REAL, empirically-verified shell-injection vulnerability (most severe finding of this initiative so far): chat_agent.py's real dispatch interpolated LLM-controlled direction/revision directly into a shell=True command with zero validation — proved with a real payload (revision="head; touch /tmp/PWNED...") that actually executed. Fixed via a shared validate_run_migration_inputs() chokepoint (strict allowlist covering every real Alembic revision shape, rejects all shell metacharacters). MODULARIZED into app/tools/database/migration.py (new domain folder). Full suite clean (4829 passed). NOTE: the identical bug pattern was found (not fixed) in seed_database — see that row below, flagged for its own turn
| 9 | run_parallel_commands | high | 1 | yes | 9 | GREEN_FLAG — see docs/tool_productionization/run_parallel_commands.md. Found + fixed a REAL, empirically-verified sandbox boundary escape: cwd (per-command, LLM-controlled) was passed unvalidated to run_sandboxed(), which mounts it read-write as the container's /workspace — proved by reading a real file from an arbitrary outside directory through the sandbox. The IDENTICAL bug also existed in the generic bash tool (tool #1, already GREEN-FLAGGED) — fixed both together per explicit user direction rather than splitting across turns (see bash.md's own "Correction" section). Fixed via check_path_in_worktree validation on cwd before it reaches the sandbox, for both tools' real chat_agent.py dispatches and their tools.py handlers. MODULARIZED into app/tools/execution/parallel.py (matches tool_enhance.md's own suggested execution/parallel.py location exactly). Full suite clean (4837 passed) |
| 10 | seed_database | high | 1 | yes | 13 | GREEN_FLAG — see docs/tool_productionization/seed_database.md. Closed the shell-injection bug diagnosed during tool #8's audit (proven with a real crafted-filename payload that executed). Also found a SECOND, distinct vulnerability while fixing it: `root / script` in Python's pathlib silently discards `root` entirely when `script` is an absolute path — proved with script="/etc/hostname" resolving outside the repo, despite the schema documenting "relative to repo root." Fixed via a shared validate_seed_database_script() (allowlist + check_path_in_worktree, mirroring validate_run_migration_inputs). MODULARIZED into app/tools/database/seed.py. Full suite clean (4848 passed) |
| 11 | undo_changes | high | 1 | yes | 3 | GREEN_FLAG — see docs/tool_productionization/undo_changes.md. undo_changes itself proved safe in isolation (git checkout -- already refuses paths outside the repo, verified directly). Auditing its missing `_is_protected_path` worktree argument surfaced the most severe cross-tool finding of this initiative: ALL 14 `_is_protected_path()` call sites in chat_agent.py's real dispatch (write_file/edit_file/append_file/rename_file/copy_file/delete_file/insert_at_line/replace_function/delete_lines/parse_merge_conflicts/resolve_merge_conflict/explain_merge_conflict/replace_class/undo_changes) were missing worktree-boundary validation — proved with a real arbitrary-file-write outside the repo via write_file (zero confirmation gate on new-file writes) and a real cross-repo exfiltration via copy_file's unchecked from_path. Same root-cause bug also found+fixed in tools.py's make_chat_handlers (copy_file, parse/resolve/explain_merge_conflict), make_fleet_apply_handlers (write_file/edit_file, used by 4 real fleet self-enhancement agents), and make_git_commit_change_handler (secret-leak oracle). Fixed via check_path_in_worktree everywhere. User explicitly approved fixing the whole class now rather than deferring (same pattern as tool #9's bash correction). Full suite clean — see below |
| 12 | write_file | medium | 60 | yes | 35 | GREEN_FLAG — see docs/tool_productionization/write_file.md. Its severe bug (worktree-boundary escape in chat_agent.py's real dispatch, zero confirmation on new-file writes) was already found+fixed during tool #11's audit. This turn audited all ~12 independently-maintained implementations across the codebase — the other 9 were all already correctly guarded (proved with a real security sweep, not assumed). MODULARIZED the 4 generic (unscoped) call sites (chat_agent.py's dispatch, _make_write_file_handler [reused by 5 factories], make_chat_handlers [~35 one-shot agents], make_fleet_apply_handlers' non-role-prompt branch [4 fleet agents]) into app/tools/filesystem/write_file.py; also consolidated 2 duplicate schema definitions onto one canonical WRITE_FILE_TOOL. Deliberately left 6 domain-scoped implementations (docs/readme/api_docs/doc_generator's *.md-only, migration_agent's migrations/-only, schema_agent/ai_engineer's already-correct generic ones) untouched — real, intentional policy differences, not duplication, and already secure. Full suite clean — see below |
| 13 | edit_file | medium | 19 | yes | 14 | GREEN_FLAG — see docs/tool_productionization/edit_file.md. Its severe bug (chat_agent.py's real dispatch had NO protected-path check at all, not even the denylist) was already found+fixed during tool #11's audit. This turn audited the other 6 real implementations — all already correctly guarded. MODULARIZED the generic (unscoped) call sites (chat_agent.py's dispatch, _make_edit_file_handler [4 factories], make_chat_handlers [~35 one-shot agents]) into app/tools/filesystem/edit_file.py; consolidated 2 duplicate schema definitions onto one canonical EDIT_FILE_TOOL. Left 4 implementations untouched: coder/cleanup_agent (already correct, generic), dependency_agent (real *_DEP_EDITABLE*-only policy), fleet_apply (already correct from tool #11, but its role-prompt branch shares read/write logic in a way that isn't a clean drop-in — left as-is rather than risk an unsafe restructure). Full suite clean — see below |
| 14 | run_python_snippet | medium | 5 | yes | 4 | GREEN_FLAG — see docs/tool_productionization/run_python_snippet.md. `code` was already safe (shlex.quote'd). Found+fixed a real, moderate-severity resource-exhaustion gap: both real implementations (chat_agent.py dispatch + make_chat_handlers) accepted an LLM-controlled `timeout` with NO upper bound, passed straight to subprocess.run — proved directly (999999999 reached subprocess.run unclamped). Fixed via MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS=300 clamp. **Found but explicitly did NOT fix** the identical unbounded-timeout pattern in run_parallel_commands (chat_agent.py ~L1623, already GREEN_FLAGGED as tool #9), fetch_url (~L2095), and one more timeout field (~L3042) — flagged as a known issue for those tools' own turns. MODULARIZED into app/tools/execution/python_snippet.py. make_ai_engineer_handlers's ae_run_python_snippet (fixed 30s, no LLM-controlled timeout) deliberately left untouched — never had this bug. 13 new tests, including previously-missing coverage of chat_agent.py's real dispatch. Full suite clean — see below |
| 15 | run_sql | medium | 5 | yes | 4 | GREEN_FLAG — see docs/tool_productionization/run_sql.md. Most severe finding since the high-risk tier: a REAL, empirically-verified SQL injection in both real params-accepting implementations (chat_agent.py dispatch + make_chat_handlers) — naive `query.replace(f"${i}", f"'{p}'")` with zero quote-escaping. Proved live against the real project database (safe, read-only, 3-statement-stacking proof): a crafted param broke out of its literal and executed a second, attacker-controlled statement. Investigated psql's own `:'var'` safe-substitution feature — empirically found it doesn't work with `-c` (only `-f` script files), reinforcing the need for a real fix. User's explicit scope decision (chose the robust option over a minimal quote-escaping patch): switched to real psycopg2 parameter binding (`$N` → `%s`, values bound out-of-band over the wire protocol, never string-interpolated) instead of hand-rolled escaping. MODULARIZED into app/tools/database/sql.py. sq_run_sql/pr_run_sql/mg_run_sql/sa_run_sql deliberately left untouched — never accepted `params`, never exposed to this bug. 17 new tests (real DB required, skip otherwise) proving the exact proven exploit is now closed. Full suite clean — see below |
| 16 | run_tests | medium | 5 | yes | 9 | GREEN_FLAG — see docs/tool_productionization/run_tests.md. Found+fixed a REAL, empirically-verified shell injection (same bug class as tool #8's run_migration): chat_agent.py's real dispatch interpolated `path`/`flags` directly into an f-string shell=True command with zero validation — proved with a real payload (path="; touch /tmp/PWNED...; echo ") that actually created a marker file outside the intended pytest invocation. make_chat_handlers's own run_tests (the OTHER real implementation, used by the same 5 agents) was ALREADY correctly guarded (shlex.quote(path) + shell-metachar denylist on flags) — fix reuses that already-proven-correct pattern. make_fleet_apply_handlers's run_tests_h also already safe, deliberately left untouched (real behavioral differences: pytest-only, tail-truncation, no summary parsing). MODULARIZED into app/tools/execution/run_tests.py. 13 new tests, closed a real coverage gap (chat_agent.py's dispatch had zero test coverage for this tool before this). Full suite clean — see below |
| 17 | delete_file | medium | 2 | yes | 6 | GREEN_FLAG — see docs/tool_productionization/delete_file.md. No new path-escape vuln (already fixed in tool #11, re-verified). Real AGENT ALIGNMENT finding: DELETE_FILE_TOOL's schema has always required a `reason` field but NONE of the 3 handlers ever read it — silently discarded every time, worst for cleanup_agent (a one-shot agent with no confirmation channel at all, whose own transcript is its only audit trail). Fixed: chat_agent.py's real confirmation dialog now shows the reason to the human before they approve, and all 3 real call sites' success messages now include it. MODULARIZED into app/tools/filesystem/delete_file.py, also closing a minor UX inconsistency (cu_delete_file was missing the is_file() friendly-error check the other two had). 13 new tests. Full suite clean — see below |
| 18 | docker_build | medium | 2 | yes | 5 | GREEN_FLAG — see docs/tool_productionization/docker_build.md. REAL, severe finding: a proven host-file exfiltration primitive — none of the 3 implementations validated `context`/`dockerfile` stayed inside the repo. Proved live: a real `docker build` with an absolute, outside-repo context succeeded, and a file from that outside directory was extracted from the resulting image (real COPY-into-image chain, not theoretical). Same root-cause class as tool #11's file-op fix, never checked for this tool. Fixed via a shared validate_docker_build_inputs() chokepoint (check_path_in_worktree, same mechanism as tool #9) used by all 3 real call sites — each site's own distinct output formatting deliberately left untouched (validator-only pattern, matching run_migration/seed_database/git_reset). MODULARIZED into app/tools/execution/docker_build.py. 11 new tests (real docker build execution, images cleaned up, skip if no docker binary) proving the exact exploit is now closed + a real legit build still works. Full suite clean — see below |
| 19 | docker_compose | medium | 2 | yes | 2 | GREEN_FLAG — see docs/tool_productionization/docker_compose.md. Found+fixed a REAL shell injection (same class as tools #8/#16/#18): chat_agent.py's real dispatch joined `services` with `" ".join(...)` and interpolated raw into an f-string shell=True command — proved with a real payload that created a marker file. make_chat_handlers's own docker_compose was ALREADY safe (list-args, no shell=True) — no fix needed. dk_docker_compose never accepted `services` at all — never exposed. Fixed via shared build_docker_compose_command() (per-argument shlex.quote, same pattern as tool #18's docker_build fix). MODULARIZED into app/tools/execution/docker_compose.py. 12 new tests. Full suite clean — see below |
| 20 | docker_exec | medium | 2 | yes | 6 | GREEN_FLAG — see docs/tool_productionization/docker_exec.md. chat_agent.py's real dispatch had THREE gaps, none present in tools.py's own 2 implementations of the same tool: (1) shell injection via `container` — only `command` was shlex.quote'd, proved with a real payload creating a marker file; (2) NO `_docker_container_risk_reason` check at all (both tools.py impls already had this — rejects exec into privileged/host-mounted containers; the real interactive dispatch never had it wired in — a genuine host-escape surface); (3) NO destructive-command check (make_chat_handlers's own already used check_command()). Fixed by reusing all 3 already-existing, already-correct pieces rather than writing anything new. MODULARIZED into app/tools/execution/docker_exec.py. 7 new tests (real docker execution, skip if no docker binary) including a real command in a real running container. Full suite clean — see below |
| 21 | docker_restart | medium | 2 | yes | 3 | PENDING |
| 22 | git_tag | medium | 2 | yes | 1 | PENDING |
| 23 | rename_symbol | medium | 2 | yes | 3 | PENDING |
| 24 | replace_function | medium | 2 | yes | 2 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 25 | semver_bump | medium | 2 | yes | 2 | PENDING |
| 26 | append_file | medium | 1 | yes | 0 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 27 | apply_patch | medium | 1 | yes | 4 | PENDING |
| 28 | browser_click | medium | 1 | yes | 1 | PENDING |
| 29 | browser_navigate | medium | 1 | yes | 0 | PENDING |
| 30 | browser_open | medium | 1 | yes | 1 | PENDING |
| 31 | browser_type | medium | 1 | yes | 0 | PENDING |
| 32 | create_branch | medium | 1 | yes | 0 | PENDING |
| 33 | delete_block | medium | 1 | yes | 1 | PENDING |
| 34 | delete_lines | medium | 1 | yes | 1 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 35 | git_checkout | medium | 1 | yes | 0 | PENDING |
| 36 | git_cherry_pick | medium | 1 | yes | 1 | PENDING |
| 37 | git_commit | medium | 1 | yes | 1 | PENDING |
| 38 | git_merge | medium | 1 | yes | 2 | PENDING |
| 39 | git_pull | medium | 1 | yes | 0 | PENDING |
| 40 | git_rebase | medium | 1 | yes | 1 | PENDING |
| 41 | git_restore | medium | 1 | yes | 0 | PENDING |
| 42 | git_stash | medium | 1 | yes | 0 | PENDING |
| 43 | git_worktree | medium | 1 | yes | 1 | PENDING |
| 44 | github_comment | medium | 1 | yes | 0 | PENDING |
| 45 | github_create_issue | medium | 1 | yes | 0 | PENDING |
| 46 | insert_after | medium | 1 | yes | 1 | PENDING |
| 47 | insert_at_line | medium | 1 | yes | 1 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 48 | insert_before | medium | 1 | yes | 1 | PENDING |
| 49 | kill_process | medium | 1 | yes | 2 | PENDING |
| 50 | linear_create_issue | medium | 1 | yes | 0 | PENDING |
| 51 | memory_write | medium | 1 | yes | 1 | PENDING |
| 52 | move_file | medium | 1 | yes | 2 | PENDING |
| 53 | npm_install | medium | 1 | yes | 2 | PENDING |
| 54 | npm_run | medium | 1 | yes | 0 | PENDING |
| 55 | pip_install | medium | 1 | yes | 2 | PENDING |
| 56 | rename_file | medium | 1 | yes | 1 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 57 | replace_class | medium | 1 | yes | 1 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 58 | run_background | medium | 1 | yes | 3 | PENDING |
| 59 | run_make | medium | 1 | yes | 1 | PENDING |
| 60 | run_node | medium | 1 | yes | 1 | PENDING |
| 61 | run_script | medium | 1 | yes | 1 | PENDING |
| 62 | run_single_test | medium | 1 | yes | 1 | PENDING |
| 63 | slack_send_message | medium | 1 | yes | 1 | PENDING |
| 64 | sync_files | medium | 1 | yes | 1 | PENDING |
| 65 | read_file | low | 82 | yes | 24 | PENDING |
| 66 | record_learning | low | 81 | yes | 8 | PENDING |
| 67 | get_file_tree | low | 79 | yes | 1 | PENDING |
| 68 | list_files | low | 79 | yes | 6 | PENDING |
| 69 | search_code | low | 77 | yes | 7 | PENDING |
| 70 | file_exists | low | 76 | yes | 0 | PENDING |
| 71 | read_files | low | 72 | yes | 3 | PENDING |
| 72 | file_info | low | 69 | yes | 0 | PENDING |
| 73 | search_symbols | low | 68 | yes | 2 | PENDING |
| 74 | find_references | low | 65 | yes | 1 | PENDING |
| 75 | search_imports | low | 65 | yes | 0 | PENDING |
| 76 | analyze_file | low | 61 | yes | 0 | PENDING |
| 77 | find_todos | low | 60 | yes | 0 | PENDING |
| 78 | git_log | low | 43 | yes | 3 | PENDING |
| 79 | git_status | low | 39 | yes | 1 | PENDING |
| 80 | git_show | low | 38 | yes | 0 | PENDING |
| 81 | git_blame | low | 34 | yes | 1 | PENDING |
| 82 | list_functions | low | 32 | yes | 6 | PENDING |
| 83 | parse_ast | low | 32 | yes | 5 | PENDING |
| 84 | git_diff | low | 10 | yes | 4 | PENDING |
| 85 | submit_docs | low | 8 | yes | 5 | PENDING |
| 86 | fetch_url | low | 7 | yes | 5 | PENDING |
| 87 | list_classes | low | 7 | yes | 3 | PENDING |
| 88 | web_search | low | 7 | yes | 7 | PENDING |
| 89 | find_api | low | 5 | yes | 2 | PENDING |
| 90 | find_route | low | 5 | yes | 2 | PENDING |
| 91 | find_sql | low | 5 | yes | 3 | PENDING |
| 92 | submit_patch | low | 5 | yes | 6 | PENDING |
| 93 | call_graph | low | 4 | yes | 3 | PENDING |
| 94 | dead_code_detect | low | 4 | yes | 4 | PENDING |
| 95 | import_graph | low | 4 | yes | 4 | PENDING |
| 96 | inspect_schema | low | 4 | yes | 3 | PENDING |
| 97 | circular_dep_detect | low | 3 | yes | 4 | PENDING |
| 98 | explain_query | low | 3 | yes | 4 | PENDING |
| 99 | find_config | low | 3 | yes | 2 | PENDING |
| 100 | generate_changelog | low | 3 | yes | 3 | PENDING |
| 101 | run_linter | low | 3 | yes | 2 | PENDING |
| 102 | secrets_scan | low | 3 | yes | 2 | PENDING |
| 103 | check_license_compliance | low | 2 | yes | 0 | PENDING |
| 104 | coverage_report | low | 2 | yes | 2 | PENDING |
| 105 | cpu_usage | low | 2 | yes | 3 | PENDING |
| 106 | diagnose_deployment_failure | low | 2 | yes | 2 | PENDING |
| 107 | disk_usage | low | 2 | yes | 4 | PENDING |
| 108 | docker_logs | low | 2 | yes | 4 | PENDING |
| 109 | docker_ps | low | 2 | yes | 3 | PENDING |
| 110 | estimate_complexity | low | 2 | yes | 1 | PENDING |
| 111 | find_function_body | low | 2 | yes | 2 | PENDING |
| 112 | generate_release_notes | low | 2 | yes | 3 | PENDING |
| 113 | health_check | low | 2 | yes | 4 | PENDING |
| 114 | memory_usage | low | 2 | yes | 3 | PENDING |
| 115 | organize_imports | low | 2 | yes | 2 | PENDING |
| 116 | read_logs | low | 2 | yes | 2 | PENDING |
| 117 | request_clarification | low | 2 | yes | 3 | PENDING |
| 118 | task_history_query | low | 2 | yes | 0 | PENDING |
| 119 | task_progress | low | 2 | yes | 2 | PENDING |
| 120 | yaml_validate | low | 2 | yes | 3 | PENDING |
| 121 | analyze_error | low | 1 | yes | 2 | PENDING |
| 122 | base64_encode | low | 1 | yes | 1 | PENDING |
| 123 | browser_close | low | 1 | yes | 0 | PENDING |
| 124 | browser_read_dom | low | 1 | yes | 0 | PENDING |
| 125 | browser_screenshot | low | 1 | yes | 0 | PENDING |
| 126 | check_url_status | low | 1 | yes | 2 | PENDING |
| 127 | compare_files | low | 1 | yes | 1 | PENDING |
| 128 | copy_file | low | 1 | yes | 1 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 129 | count_lines | low | 1 | yes | 1 | PENDING |
| 130 | cpu_profile | low | 1 | yes | 0 | PENDING |
| 131 | create_directory | low | 1 | yes | 1 | PENDING |
| 132 | csv_preview | low | 1 | yes | 1 | PENDING |
| 133 | decision_log_append | low | 1 | yes | 0 | PENDING |
| 134 | deps_outdated | low | 1 | yes | 0 | PENDING |
| 135 | env_diff | low | 1 | yes | 1 | PENDING |
| 136 | explain_merge_conflict | low | 1 | yes | 2 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 137 | export_markdown | low | 1 | yes | 1 | PENDING |
| 138 | find_file | low | 1 | yes | 1 | PENDING |
| 139 | find_queue | low | 1 | yes | 1 | PENDING |
| 140 | find_test | low | 1 | yes | 1 | PENDING |
| 141 | find_unused_imports | low | 1 | yes | 1 | PENDING |
| 142 | find_worker | low | 1 | yes | 1 | PENDING |
| 143 | format_file | low | 1 | yes | 1 | PENDING |
| 144 | generate_api_docs_text | low | 1 | yes | 0 | PENDING |
| 145 | generate_commit_msg | low | 1 | yes | 2 | PENDING |
| 146 | generate_diagram | low | 1 | yes | 2 | PENDING |
| 147 | generate_patch | low | 1 | yes | 1 | PENDING |
| 148 | git_branch | low | 1 | yes | 0 | PENDING |
| 149 | git_fetch | low | 1 | yes | 0 | PENDING |
| 150 | git_log_file | low | 1 | yes | 0 | PENDING |
| 151 | git_stash_list | low | 1 | yes | 1 | PENDING |
| 152 | github_inspect_repo | low | 1 | yes | 1 | PENDING |
| 153 | github_list_prs | low | 1 | yes | 0 | PENDING |
| 154 | hash_file | low | 1 | yes | 1 | PENDING |
| 155 | http_request | low | 1 | yes | 1 | PENDING |
| 156 | inspect_github_repo | low | 1 | yes | 2 | PENDING |
| 157 | inspect_openapi_spec | low | 1 | yes | 2 | PENDING |
| 158 | json_query | low | 1 | yes | 0 | PENDING |
| 159 | json_validate | low | 1 | yes | 2 | PENDING |
| 160 | known_issues_read | low | 1 | yes | 0 | PENDING |
| 161 | known_issues_write | low | 1 | yes | 1 | PENDING |
| 162 | list_background_processes | low | 1 | yes | 1 | PENDING |
| 163 | list_env_vars | low | 1 | yes | 1 | PENDING |
| 164 | list_open_ports | low | 1 | yes | 0 | PENDING |
| 165 | list_processes | low | 1 | yes | 1 | PENDING |
| 166 | loc_stats | low | 1 | yes | 1 | PENDING |
| 167 | memory_read | low | 1 | yes | 1 | PENDING |
| 168 | mermaid_from_schema | low | 1 | yes | 0 | PENDING |
| 169 | openapi_inspect | low | 1 | yes | 1 | PENDING |
| 170 | parse_docker_compose | low | 1 | yes | 1 | PENDING |
| 171 | parse_dockerfile | low | 1 | yes | 1 | PENDING |
| 172 | pip_list | low | 1 | yes | 1 | PENDING |
| 173 | read_env_var | low | 1 | yes | 1 | PENDING |
| 174 | read_image | low | 1 | yes | 1 | PENDING |
| 175 | read_notebook | low | 1 | yes | 1 | PENDING |
| 176 | read_output | low | 1 | yes | 1 | PENDING |
| 177 | read_pdf | low | 1 | yes | 1 | PENDING |
| 178 | record_preference | low | 1 | yes | 0 | PENDING |
| 179 | review_diff | low | 1 | yes | 2 | PENDING |
| 180 | submit_ai_result | low | 1 | yes | 1 | PENDING |
| 181 | submit_arch_review | low | 1 | yes | 2 | PENDING |
| 182 | submit_ba_result | low | 1 | yes | 1 | PENDING |
| 183 | submit_cicd_report | low | 1 | yes | 1 | PENDING |
| 184 | submit_cleanup | low | 1 | yes | 1 | PENDING |
| 185 | submit_dependency_report | low | 1 | yes | 1 | PENDING |
| 186 | submit_docker_report | low | 1 | yes | 1 | PENDING |
| 187 | submit_health_report | low | 1 | yes | 2 | PENDING |
| 188 | submit_migration | low | 1 | yes | 1 | PENDING |
| 189 | submit_monitoring_report | low | 1 | yes | 2 | PENDING |
| 190 | submit_perf_review | low | 1 | yes | 1 | PENDING |
| 191 | submit_qa_result | low | 1 | yes | 3 | PENDING |
| 192 | submit_refactor_report | low | 1 | yes | 1 | PENDING |
| 193 | submit_research | low | 1 | yes | 1 | PENDING |
| 194 | submit_result | low | 1 | yes | 18 | PENDING |
| 195 | submit_review | low | 1 | yes | 3 | PENDING |
| 196 | submit_schema | low | 1 | yes | 1 | PENDING |
| 197 | submit_security_report | low | 1 | yes | 1 | PENDING |
| 198 | submit_sprint_plan | low | 1 | yes | 1 | PENDING |
| 199 | submit_sql_report | low | 1 | yes | 1 | PENDING |
| 200 | submit_style_review | low | 1 | yes | 1 | PENDING |
| 201 | submit_tech_debt | low | 1 | yes | 1 | PENDING |
| 202 | summarize_folder | low | 1 | yes | 0 | PENDING |
| 203 | summarize_repo | low | 1 | yes | 1 | PENDING |
| 204 | template_render | low | 1 | yes | 1 | PENDING |
| 205 | type_check | low | 1 | yes | 1 | PENDING |
| 206 | unzip_files | low | 1 | yes | 1 | PENDING |
| 207 | wait_for_port | low | 1 | yes | 0 | PENDING |
| 208 | xml_validate | low | 1 | yes | 1 | PENDING |
| 209 | zip_files | low | 1 | yes | 2 | PENDING |
| 210 | capability_gap_scan | low | 0 | yes | 0 | PENDING |
| 211 | submit_bug_fix | low | 0 | yes | 1 | PENDING |
| 212 | submit_enhancement_request | NO_MANIFEST | 5 | NO | 3 | PENDING |
| 213 | git_commit_change | NO_MANIFEST | 4 | NO | 0 | PENDING |
| 214 | submit_fix | NO_MANIFEST | 4 | NO | 0 | PENDING |
| 215 | fleet_metrics_read | NO_MANIFEST | 3 | NO | 0 | PENDING |
| 216 | audit_log_read | NO_MANIFEST | 2 | NO | 0 | PENDING |
| 217 | ask_human_to_choose | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 218 | check_last_release | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 219 | list_all_tool_specs | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 220 | list_deploy_artifacts | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 221 | list_migrations | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 222 | list_registered_agents | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 223 | memory_curate_read | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 224 | memory_curate_write | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 225 | memory_list_draft_lessons | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 226 | memory_promote_lesson | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 227 | memory_search | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 228 | parse_merge_conflicts | NO_MANIFEST | 1 | NO | 2 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 229 | resolve_merge_conflict | NO_MANIFEST | 1 | NO | 2 | PENDING  — NOTE: worktree-boundary validation gap found+fixed 2026-08-17 during tool #11's (undo_changes) cross-cutting audit (see docs/tool_productionization/undo_changes.md and tests/test_file_ops_worktree_boundary_hardening.py / test_tools_py_file_ops_worktree_boundary_hardening.py); this fix closed the path-escape bug for this tool's real call sites, but its own full tool_enhance.md audit/modularization turn is still pending |
| 230 | score_tech_options | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 231 | submit_accessibility_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 232 | submit_agentic_ai_architect | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 233 | submit_api_designer_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 234 | submit_architect_plan | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 235 | submit_brief | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 236 | submit_changelog | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 237 | submit_code_explainer_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 238 | submit_code_quality_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 239 | submit_compliance_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 240 | submit_cost_estimator_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 241 | submit_data_pipeline_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 242 | submit_db_design | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 243 | submit_debugger_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 244 | submit_dependency_security_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 245 | submit_devex_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 246 | submit_env_checker_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 247 | submit_eval_result | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 248 | submit_feature_flag_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 249 | submit_incident_responder_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 250 | submit_infra_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 251 | submit_load_test_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 252 | submit_localization_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 253 | submit_mcp_developer_agent | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 254 | submit_onboarding_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 255 | submit_pair_programmer_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 256 | submit_plan | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 257 | submit_prompt_engineer_agent | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 258 | submit_rag_design | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 259 | submit_release_notes | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 260 | submit_roadmap_agent | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 261 | submit_rollback_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 262 | submit_runbook_generator_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 263 | submit_slo_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 264 | submit_spike_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 265 | submit_subtasks | NO_MANIFEST | 1 | NO | 3 | PENDING |
| 266 | submit_tech_advisor_agent | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 267 | submit_test_coverage_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 268 | submit_test_writer_agent | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 269 | submit_threat_model | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 270 | submit_user_stories | NO_MANIFEST | 1 | NO | 2 | PENDING |
| 271 | submit_ux_design_agent | NO_MANIFEST | 1 | NO | 0 | PENDING |
| 272 | submit_version_manager_agent | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 273 | summarize_output | NO_MANIFEST | 1 | NO | 1 | PENDING |
| 274 | submit_scaffold_plan | NO_MANIFEST | 0 | NO | 0 | PENDING |
