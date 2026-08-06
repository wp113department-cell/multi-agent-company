# Batch 11 — Security Audit, Safety Audit, Enterprise Security, Governance & Policy Engine

Covers §21, §22, §96, §85. Evidence-only, file:line cited.

---

## §21 Security Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Credential protection | **YES** | `credential_vault.py` — Fernet encryption, `SecretStr` fields with serializer gate, audit-logged (key names only). |
| Secret management | **PARTIAL** | All secrets are plain env vars via Pydantic `BaseSettings` — real startup-crash validation on critical ones (`jwt_secret_key`, `default_admin_password`), but **no secrets-manager integration** (no Vault/AWS Secrets Manager) — the only `boto3` usage is for S3 artifact storage, unrelated to secret loading. |
| Sandboxing | **PARTIAL** | Real Docker sandboxing with fail-closed behavior — but confirmed, again, that `chat_agent.py`'s own `bash` handler bypasses it entirely (same finding as Batch 1, now cross-validated a third time). |
| Dangerous command detection | **YES** | Substantial denylist + strict-mode metacharacter blocking, `realpath`-based boundary checks. |
| Permission system | **PARTIAL** | Real RBAC middleware, default-deny when JWT enabled — but the 5 files with unauthenticated GET routes (Batch 6 finding) remain open. |
| Prompt injection resistance | **PARTIAL — real but inconsistently scoped** | `_wrap_untrusted_tool_content`/`_flag_suspicious_tool_output` are genuine, non-trivial defenses (delimiter-wrapping + injection-pattern flagging with a visible `[SECURITY WARNING]` banner), applied at the real tool-execution chokepoint. **But only 5 tools get the untrusted-content wrap** (`web_search`, `read_file`, `read_files`, `fetch_url`, `http_request`) and **only 2 get the injection-pattern flag** (`bash`, `web_search`). Dozens of other read-capable tools (`search_code`, `list_files`, `git_show`/`git_blame`, and many agent-specific read variants) return raw, unwrapped, unflagged content despite being equally capable of surfacing adversarial repo content (e.g. a comment in a malicious PR branch instructing the agent to exfiltrate secrets). |
| Data leakage prevention | **PARTIAL — real but narrowly scoped** | Two real regex-based secret detectors exist (`_mask_secret_value`, `_scan_content_for_secrets`) — but each is wired into exactly one call site (`read_env_var_h` masking, `git_commit_change` pre-commit denial respectively). **No general scan of arbitrary agent output/chat responses before they reach the user** — a secret an agent encountered via `read_file` and then quoted in its chat reply would not be caught by either scanner. |

**§21 overall: PARTIAL.** Every individual mechanism found is genuinely well-engineered (not superficial) — the pattern across this whole section is **narrow, correct implementations that don't cover their full intended surface area**. This is a more dangerous shape of gap than "missing entirely," because a reader who finds `_wrap_untrusted_tool_content` or `_scan_content_for_secrets` and stops there would reasonably over-trust the system's actual coverage.

---

## §22 Safety Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Refuses malware/ransomware/credential-theft/phishing/cybercrime requests | **PARTIAL — model-level only, no application check** | Zero application-level refusal logic found (no keyword/classifier check for these request categories anywhere in `backend/app`). This relies entirely on the underlying Anthropic model's own safety training. `_GLOBAL_STANDARDS.md`'s "Security Guidelines" section covers the *agents'* own defensive posture (credential handling, injection awareness) — not user-request content moderation. |
| Code-level block on generating harmful code categories | **NO** | No pattern-match/classifier runs on agent-generated code before it's written to disk. The only pre-write checks gate on file *path* (protected paths) or *credential-shaped strings* (secret scanner) — neither addresses malicious code semantics/intent. |

**§22 overall: PARTIAL, and worth being direct about.** This is not a defect specific to this codebase — no production LLM coding assistant implements a code-level "is this code malicious" classifier (it's a genuinely hard, largely unsolved problem, and the underlying model's training is the standard mitigation industry-wide). Flagging this as a gap without that context would be misleading; it should be scored as "consistent with industry norms," not "missing a normal safeguard."

---

## §96 Enterprise Security

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Secret scanning | **PARTIAL** | Real custom regex scanner exists (same as §21's data-leakage finding) — no third-party tool (gitleaks/truffleHog) integration, and scope is limited to 2 call sites, not a repo-wide scan capability. |
| Encrypted credential storage | **YES** | Confirmed (`credential_vault.py`). |
| Audit logs | **PARTIAL — real but not tamper-resistant** | `AuditLog` class does real structured logging (action_type, agent, task_id, outcome, approval fields) to both an in-process ring buffer (capped at 2000 entries, DB-write is fire-and-forget) and a real Postgres table. **Not hash-chained or otherwise tamper-resistant** — nothing prevents a direct `UPDATE`/`DELETE` at the DB layer; the append-only guarantee exists only in the application's exposed API surface, not the database. **Also a real functional gap**: query methods (`recent()`, `by_trace()`, `by_task()`) read only from the in-memory ring buffer, not the DB table — so query results are capped at the last 2000 entries per process and are lost across restarts even though the underlying DB rows persist. |
| Role-based permissions | **PARTIAL** | Covered in §21. |
| Least-privilege access | **YES — spot-checked and confirmed real** | `reviewer.py` and `architecture_reviewer.py`, both declared read-only, genuinely have no write/edit/delete/bash tools in their actual tool lists — this is not just a description, it's enforced by what's literally in the allowlist. (Noted for contrast: `compliance_agent.py` is *not* declared read-only and does have `write_file` — correctly consistent with its stated report-writing purpose, not a violation.) |
| Approval chains | **YES** | Covered elsewhere (`approval_gate.py`). |
| Compliance readiness | **PARTIAL** | Real data retention (archive, not hard-delete) exists. A `compliance_agent.py` exists but is an LLM report-writer (produces `.md` audit documents), not a code-level enforcement mechanism. **No GDPR/CCPA data-export or deletion-on-request API endpoint found** — a real gap if enterprise/regulated customers are a target market. |

**§96 overall: PARTIAL.** Least-privilege tool scoping is a genuine strength worth crediting explicitly. The audit log's tamper-resistance and query-completeness gaps are real and somewhat ironic for a system whose own audit trail is meant to be evidence of good governance — the query layer silently drops data older than the last 2000 in-process entries, which is exactly the kind of gap this very audit methodology (evidence over assumption) is designed to catch.

---

## §85 Governance & Policy Engine

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Central governance system beyond the security-focused policy engine | **NO** | No separate coding-standards/naming-convention/framework-approval module exists. "Governance" appears only as descriptive prose in comments, not as an enforcement engine. |
| All agents automatically follow policy (structural guarantee) | **PARTIAL** | Spot-checked 11 distinct write-tool handler implementations — all correctly call a real policy gate before writing. But this remains a **per-handler discipline, not a structural chokepoint** — there is no single interceptor in front of all file-write tool calls the way `_wrap_untrusted_tool_content` sits in front of all *read* tool results. Every sampled handler does it correctly today; nothing prevents a future handler from forgetting. |
| Licensing policy enforcement | **NO** | Zero license-compatibility/SPDX checking anywhere. |

**§85 overall: NO/PARTIAL.** There is no "governance engine" in the sense the question asks about (company-wide coding standards, framework allowlists, licensing rules) — what exists is a well-built *security* policy engine (command/path denylists) that gets conflated with governance in casual description but serves a narrower purpose.

---

## Summary — Batch 11 (18 checkpoints across 4 sections)

- **YES:** 5
- **PARTIAL:** 11
- **NO:** 2

**Findings worth flagging above the rest:**
1. **Prompt-injection and data-leakage defenses are real but narrow** — both cover a handful of specific tool call sites rather than the full read/write tool surface, meaning the *category* of defense exists and works, but coverage is incomplete in a way that isn't visible without tracing every tool individually (which is what this audit did).
2. **Audit log query layer silently caps at 2000 in-memory entries and loses history on restart**, despite the underlying DB table persisting everything — a real, fixable inconsistency between what's stored and what's queryable.
3. **§22 (safety refusal) should not be scored as harshly as a typical "NO" finding** — the absence of an application-level malware/cybercrime classifier is standard industry practice, not a gap unique to this project.

**Production Enhancement Plan:**
- Extend `_wrap_untrusted_tool_content`'s tool list to cover all read-capable tools that touch repo/external content (`search_code`, `list_files`, `git_show`, `git_blame`, and the agent-specific `read_file` variants), not just the 5 currently covered — this is a config-list change, not new infrastructure, since the wrapping mechanism itself is already correct.
- Fix `AuditLog`'s query methods (`recent()`/`by_trace()`/`by_task()`) to read from the DB table (with the ring buffer as a fast-path cache), so audit history survives restarts and isn't capped at 2000 entries — the DB write path is already real, only the read path needs to change.
- Add a hash-chain or append-only DB constraint (e.g. a trigger rejecting UPDATE/DELETE, or a chained-hash column) to `audit_log` if genuine tamper-resistance is a compliance requirement for target customers.
