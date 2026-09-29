# Audit 05: Master Security Audit

**Spec:** `files/Audit/05_MASTER_SECURITY_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **JSON sidecar:** `json/AUDIT_05_SECURITY.json` · **Fix commit:** `77e45783`

## Result

🟢 **GREEN: every security control was verified by executing it, not by reading it; all gaps found were fixed.**

**Security score: 90 / 100** (July run: **22**, 4 Critical, "NOT READY"). All four July Criticals are closed and proven at runtime. This run found and fixed: 2 Critical dependency vulnerabilities (Next.js remote code execution), 2 command-policy bypasses, and (in audits 01/02) a dev password shipped in the login bundle and 3 agents able to overwrite code. What stops a perfect score: the command policy is still a denylist, so the Docker sandbox is the real containment boundary (on by default, fails closed), and login protection is rate limiting only (no account lockout).

## How it was verified (executed evidence)

| Probe | What it proves | Result |
|---|---|---|
| `evidence/route_auth_matrix.py` | the resolved FastAPI dependency tree of all 143 routes | 69 approver-only, 65 authenticated, 9 open by design (login/refresh/setup/logout/change-password/me/health/agent list/export-me, each checked) |
| `evidence/unauth_probe.py` | real HTTP calls, production-like auth (JWT + RBAC on) | **70/70** mutating routes reject anonymous callers (401/403); **0** approver routes reachable with a viewer token |
| `evidence/prod_config_guards.py` | constructs the real `Settings` with `DEPLOYMENT_ENV=production` | good config starts; **9/9** insecure configs refuse to start |
| `evidence/policy_probe.py` | real attack strings against the policy engine | 26/26 dangerous commands denied after the fix (was 24/26) |
| `evidence/docs_agent_write_probe.py` | real write handlers of all 36 "docs-only" agents | 0 can overwrite existing code (was 3) |
| `pip-audit -r requirements.txt` | backend supply chain | **0** known vulnerabilities (138 deps) |
| `pnpm audit` | frontend supply chain | **0** after fix (was 2 Critical, 4 High, 4 Moderate) |

## 1. Path and command policy

| Check | Result |
|---|---|
| `.env`, `.env.*`, `secrets/`, `.github/workflows/`, `id_rsa`, `.ssh/` writes blocked | ✅ `check_path` (probe) |
| Path traversal (`../../etc/passwd`, absolute paths) on write tools | ✅ `check_path_in_worktree` rejects both |
| `rm -rf`, `git push`, `kubectl`, `terraform`, `docker push`, `npm publish`, `curl \| sh`, `sudo`, fork bomb, `dd` | ✅ denied |
| **Quote/escape splitting** (`r''m -rf /`, `'rm' '-rf'`, `r\m`) | ❌ → ✅ **fixed (SEC-05-001)** |
| **Cloud CLIs** (`aws`, `gcloud`, `az`, `gsutil`, deploy CLIs) | ❌ → ✅ **fixed (SEC-05-002)**, matched in command position only; `grep az src` still allowed |
| QA/allowlisted agents: chaining (`;`, `&&`, `\|`, backticks, `$()`) | ✅ `check_allowlisted_command` = strict mode + prefix |
| Where generic `bash` really runs | ✅ Docker sandbox **by default** (`bash_sandbox_enabled=True`), fails closed if Docker is down; host execution only by explicit opt-out |
| `bash`/`run_background` `cwd` override | ✅ validated against the repo boundary before it is mounted (`validate_run_background_cwd`) |

## 2. Credential handling

| Check | Result |
|---|---|
| Encryption at rest | ✅ Fernet; production refuses to start without `CREDENTIAL_ENCRYPTION_KEY` (probe) |
| Platform credentials excluded from agent-injectable secrets | ✅ `_RESERVED_SECRET_NAMES` (includes `DATABASE_URL`), `api/settings.py:267-317` |
| `GITHUB_TOKEN` / `ANTHROPIC_API_KEY` never injected into agent bash | ✅ popped in **both** modes (`api/agents.py:520-521, 829-830`) |
| Secrets redacted from tool output before it reaches context, logs or SSE | ✅ single chokepoint in `base_graph.py` (every tool result) |
| Dev admin password in the frontend bundle | ❌ → ✅ fixed (ARCH-01-002) |

## 3. Authentication and authorization

| Check | Result |
|---|---|
| Every mutating endpoint guarded | ✅ 70/70 at runtime |
| Approve/reject endpoints approver-gated | ✅ viewer token rejected on every approver route |
| JWT / RBAC / no role-header shortcut in production | ✅ enforced at startup (July Critical SEC-05-014 closed) |
| Default admin password in production | ✅ refused at startup; the seeded admin has `must_change_password=True` (July SEC-05-015 closed) |
| JWT secret strength | ✅ empty or < 32 characters refused when JWT is on |
| CORS | ✅ config-driven; production compose **requires** `CORS_ORIGINS` (`docker-compose.prod.yml:117`) |
| Brute force | ⚠️ `rate_limit_login` on login and refresh (slowapi, per-IP). No per-account lockout. See SEC-05-005. |

## 4. Prompt-injection resistance

- Untrusted external content (web, files, PDFs) is wrapped in `<untrusted_external_data>` blocks, and the closing tag can't be spoofed (`base_graph.py:2349`).
- The graph refuses any tool the model wasn't offered (`base_graph.py:2643`), so an injected "call create_pr" can't reach an unadvertised handler.
- High-risk tools require a contract declaration (`filter_runtime_tools`).
- The command policy plus the sandbox apply regardless of how the model was persuaded. The chat agent's confirmation prompt is an extra layer, not the boundary.
- **Honest limit:** injection can't be fully prevented in an LLM system. Containment (sandbox, scoped writes, human approval for pushes and deploys) is the real control, and it was verified above.

## 5. Supply chain

| Item | Before | After |
|---|---|---|
| `next` 15.5.21 | **2 Critical** (unauthenticated RCE in image optimization; Windows-hosted RCE) + High `sharp` | 15.5.26: fixed |
| `vitest` 3.2 | Moderate path traversal (dev only) | 4.x (config migrated to Oxc JSX); 52/52 tests pass |
| nanoid, browserslist, baseline-browser-mapping, undici | High / Moderate (build and test tooling) | updated within range |
| Backend (138 packages) | 0 | 0 |
| CI gates | `pip-audit` and `pnpm audit` are hard gates (no `\|\| true`, July SEC-05-019 holds). **The `pnpm audit` gate was failing before this fix**; it passes now. | ✅ |

## 6. Findings

| ID | Sev | Status | Finding | Fix / proof |
|---|---|---|---|---|
| SEC-05-001 | High | FIXED | Shell quote/escape splitting bypassed the whole denylist (`r''m -rf /` allowed) | normalise quotes and backslashes for matching; `tests/test_audit05_policy_hardening.py` (8 bypass cases) |
| SEC-05-002 | Medium | FIXED | Cloud CLIs (`aws s3 rm --recursive`, `gcloud … delete`, deploy CLIs) allowed while kubectl/terraform were denied | command-position rules, human-overridable; 15 cases + 12 look-alike commands still allowed |
| SEC-05-003 | **Critical** | FIXED | `next@15.5.21`: 2 Critical RCE advisories (+ High `sharp`) | → 15.5.26; `pnpm audit` 0; build and tests green |
| SEC-05-004 | Low | FIXED | Dev-only vitest / tooling advisories kept the CI `pnpm audit` gate red | vitest 4 + transitive updates |
| SEC-05-005 | Low | ACCEPTED | Login brute force is limited per IP only (no per-account lockout); the in-process limiter is per-instance | Recommend a per-account lockout and a Redis-backed limiter for multi-instance. Listed for audit 13. |
| (ARCH-01-002) | Medium | FIXED | Dev admin password in the production bundle | see audit 01 |
| (AGENT-02-002) | High | FIXED | 3 "docs-only" agents could overwrite code | see audit 02 |

## 7. July (2026-07-27) findings: regression check

| July ID | Today |
|---|---|
| SEC-05-012 no auth on routes (Critical) | ✅ closed: 70/70 runtime probe |
| SEC-05-013 approvals without approver (Critical) | ✅ closed: viewer probe |
| SEC-05-014 JWT off / role header (Critical) | ✅ closed: production refuses to start |
| SEC-05-015 default admin password (Critical) | ✅ closed: production refuses to start; admin seeded once with a forced change |
| SEC-05-005/018 denylist without sandbox | ✅ sandbox on by default and fails closed; denylist hardened today |
| SEC-05-006 bash `cwd` override | ✅ validated |
| SEC-05-019 `pip-audit \|\| true` | ✅ hard gate |
| SEC-05-011 reserved secret names | ✅ `_RESERVED_SECRET_NAMES` |
| SEC-05-004 base_graph policy gate | ✅ unadvertised-tool refusal + policy check per call |
| SEC-05-007 confirm can override catastrophic commands | ✅ `_NON_OVERRIDABLE_PATTERNS` |

## Verdict

**READY:** 0 open Critical / High. Regression: 505 existing security, policy and sandbox tests + 36 new ones pass.
