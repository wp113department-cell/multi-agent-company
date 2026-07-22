# Day 17 Plan — Credential Vault

Per `docs/FLEET_ENHANCEMENT_PLAN.md` lines 1144-1193. Goal: user-provided credentials (GitHub
token, Anthropic key, custom secrets) stored securely, injected into agents, never logged.



## Research (REPO-FIRST)

`repos/open-hands/openhands/app_server/secrets/`:
- `secrets_models.py`'s `Secrets` model uses a real, explicit Pydantic mechanism: `field_serializer`
  + `SerializationInfo.context` gating (`expose_secrets: bool`) so `model_dump()`/`model_dump_json()`
  only reveal real values when the caller explicitly opts in via serialization context — not
  incidental masking, a deliberate, auditable gate.
- `file_secrets_store.py`'s `FileSecretsStore.store()`/`.load()` — write with
  `model_dump_json(context={'expose_secrets': True})`, read back into a real `Secrets` object.
- **Verified empirically before designing anything** (installed `pydantic==2.13.4`, not assumed):
  `SecretStr` already masks in `repr()`/`str()`/`model_dump()`/`model_dump_json()` by default,
  requiring an explicit `.get_secret_value()` call to unwrap. Building the SAME explicit
  `field_serializer`+`expose_secrets` gate open-hands uses anyway (defense-in-depth, auditable in
  code — matches the plan's literal rule "SecretStr fields: never serialized without
  expose_secrets=True context") rather than relying on Pydantic's implicit default alone.
- `secrets_router.py` — confirms the plan's own endpoint shape (list-names-only, create, delete).

## Codebase grounding — plan/reality corrections (same class of finding as every prior day)

1. **No "project" entity exists in this codebase.** The plan's pseudocode is keyed by
   `project_id`; this project's real domain model has `Repo`, `DevTask`, no `Project`. Credentials
   here are already correctly GLOBAL-scoped (one Anthropic key, one GitHub token for the whole
   deployment) — Days 9 and 14 already built `SystemSetting`-backed storage for exactly this
   reason. **Day 14's own comment already anticipated this** (`api/settings.py` line 134-137):
   "No credential vault exists yet (Day 17 doesn't either) — SystemSetting is already the real,
   established mechanism for this." Built the vault as a transparent encryption + audit layer
   ON TOP of `SystemSetting` (wrapping its one real choke point, `get_setting()`/`set_setting()`
   in `repository.py`) rather than a parallel per-project table nothing would ever populate.
2. **`database_url` explicitly excluded from vault-manageable credentials.** The plan's own example
   list includes it, but this project's `database_url` is core startup config
   (`app/config.py`, required, sourced from env) — not something a UI form should let a human type
   in and have injected into agent environments. CLAUDE.md's own Permanent Safety Rule states "No
   agent ever gets deploy credentials. Deploy is a human action forever" — an arbitrary injectable
   DB URL is exactly the shape of credential that rule exists to keep out of agent reach. Kept
   `github_token` + `anthropic_api_key` (both already real, already agent-facing) plus a new
   `custom_secrets` dict (the plan's own escape hatch for anything else a task genuinely needs,
   e.g. a third-party API key a task's code integrates with) — never database/deploy credentials.
3. **Policy engine `.env*`/`secrets/**`/`.github/workflows/**` write-blocking already exists and is
   already tested**, from an earlier day (`app/policy/engine.py`'s `_matches_path_rule()`,
   `tests/test_policy.py`'s `test_env_denied`/`test_env_local_denied`/
   `test_env_inside_worktree_still_denied` etc.) — verified by reading both files before assuming
   this was new Day 17 work. The plan's stated success criterion ("Policy engine test: agent cannot
   write token to .env file") is **already satisfied**; nothing new needed here beyond citing it.
4. **Encryption key made optional-but-strongly-recommended, not hard-required.** Matches the
   established `jwt_secret_key`/`jwt_auth_enabled` pattern in `config.py` (`_require_jwt_secret_when_enabled`)
   rather than a bare `Field(...)` required value: making a brand-new Day 17 concept a hard startup
   requirement would break every existing test and deployment that predates this day. When
   `CREDENTIAL_ENCRYPTION_KEY` is unset, credentials remain stored in plaintext — the exact status
   quo of Days 9/14's existing keys today — with one clear startup warning log, never a silently
   hardcoded fallback key (CLAUDE.md: "never a silent default for secrets" — the warning makes the
   gap visible instead of hiding it).

## Design

**`app/config.py`**: `credential_encryption_key: str = Field(default="", ...)` + a
`_warn_credential_encryption_key_missing` startup-time log (not a hard validator, since "unset" is
a valid, if discouraged, state).

**`app/db/repository.py`** — `get_setting()`/`set_setting()` gain transparent encrypt/decrypt at
their one real choke point (confirmed via grep: `SystemSetting` is touched nowhere else in the
codebase). Versioned-prefix scheme (`"enc:v1:<fernet-token>"`) so already-stored plaintext rows
(every existing Anthropic/OpenAI/GitHub key, written before this day) keep working unchanged if
encryption gets enabled later — no migration, no data loss, no breaking change for existing
deployments.

**New `app/security/credential_vault.py`**:
- `ProjectCredentials(BaseModel)` — frozen, `github_token`/`anthropic_api_key: SecretStr | None`,
  `custom_secrets: dict[str, SecretStr]`. `field_serializer` + `expose_secrets` context gate
  (matches open-hands' real mechanism). `get_env_vars()` — the one place `.get_secret_value()` is
  called.
- `CredentialVault.load()` / `.store()` / `.inject_into_env()` — thin wrapper over
  `get_setting`/`set_setting` (github_token/anthropic_api_key keys already exist; custom secrets
  namespaced `custom_secret:{name}`). Every access (load or store) writes one audit-log entry via
  the existing `app/fleet/audit_log.py` (`audit()` — already the established mechanism, Day 13
  reused it too) — key name only, never the value.

**Custom secrets injection point**: `app/agents/tools.py`'s `make_coder_handlers()` gains an
optional `extra_env` param; its `bash()` tool handler merges it into the subprocess env when
present — the realistic, safety-bounded interpretation of "injected into agents" (a task's coding
agent can `os.environ["MY_API_KEY"]` inside a bash command it runs, nothing more privileged).

**API** (`api/settings.py`, alongside the existing github-token/api-key endpoints — matches this
project's real global-settings routing, not the plan's fictional `/api/projects/{id}/credentials`):
`POST/GET/DELETE /api/settings/custom-secrets(/{name})` — list returns names only, never values.

## Success criteria (from the plan, adapted to this project's real shape)

Store a fake GitHub token → load it → confirm it round-trips correctly and never appears in any
log line or masked-serialization path → policy engine already proven (pre-existing tests) to block
an agent writing it to `.env`. Tests for `SecretStr` serialization guard, env injection, encrypted
round-trip, and backward-compatible plaintext-row reads.
