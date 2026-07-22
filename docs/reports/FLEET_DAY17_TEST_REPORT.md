# Fleet Day 17 Test Report — Credential Vault
Date: 2026-07-22

## What was built

Per `docs/DAY17_PLAN.md`, grounded in REPO-FIRST research before any design (CLAUDE.md rule).

### Research

- `repos/open-hands/openhands/app_server/secrets/secrets_models.py`'s `Secrets` model — confirmed
  the real mechanism behind "SecretStr fields never serialized without expose_secrets=True": an
  explicit `field_serializer` + `SerializationInfo.context` gate, not incidental masking.
- **Verified empirically before designing** (installed `pydantic==2.13.4`): `SecretStr` already
  masks in `repr()`/`str()`/`model_dump()`/`model_dump_json()` by default. Built the SAME explicit
  gate open-hands uses anyway — deliberate, auditable, defense-in-depth on top of Pydantic's
  incidental default, matching the plan's literal rule.
- `file_secrets_store.py` — confirmed the store/load round-trip pattern via
  `model_dump_json(context={'expose_secrets': True})`.
- Verified real `cryptography.fernet.Fernet` API behavior directly (key format, encrypt/decrypt,
  invalid-key error) before writing any code against it, per CLAUDE.md's zero-hallucination rule.

### Plan/reality corrections (same class of finding as every prior day)

1. **No "project" entity exists in this codebase.** The plan's pseudocode is keyed by
   `project_id`; credentials here are already correctly GLOBAL-scoped via the `SystemSetting` table
   (Days 9/14). **Day 14's own comment already anticipated this exact day** (`api/settings.py`:
   "No credential vault exists yet (Day 17 doesn't either) — SystemSetting is already the real,
   established mechanism"). Built the vault as an encryption + audit layer wrapping
   `get_setting()`/`set_setting()` (repository.py's one real choke point for `SystemSetting` —
   confirmed by grep) rather than a parallel per-project table nothing would populate.
2. **`database_url` excluded from vault-manageable credentials.** The plan's example list includes
   it, but this project's `database_url` is core startup config, not a UI-enterable,
   agent-injectable value — CLAUDE.md's own Permanent Safety Rule ("No agent ever gets deploy
   credentials") makes this exclusion a safety requirement, not a scope cut.
3. **Policy engine `.env*`/`secrets/**`/`.github/workflows/**` blocking already exists and is
   already tested** (`app/policy/engine.py`'s `_matches_path_rule()`, `tests/test_policy.py`) —
   confirmed by reading both files before assuming this was new work. The plan's stated success
   criterion is already satisfied; re-ran the existing tests to confirm (still passing), wrote no
   duplicate test.
4. **Encryption key made optional-but-strongly-recommended**, matching the established
   `jwt_secret_key`/`jwt_auth_enabled` conditional-required pattern already in `config.py`, rather
   than a hard `Field(...)` requirement — avoids breaking every existing test/deployment that
   predates this day. When unset: plaintext storage (today's actual status quo) plus one clear
   startup warning log, never a silently hardcoded key.

## What was built

- `cryptography==49.0.0` added as an explicit direct dependency (already installed transitively via
  `python-jose[cryptography]`; pinned to the real installed/latest version per CLAUDE.md's
  zero-hallucination package rule).
- `app/config.py`: `credential_encryption_key` (optional Fernet key) + a validator that rejects an
  invalid key at Settings load time (clear error) while allowing it to be simply unset.
- `app/db/repository.py`: `get_setting()`/`set_setting()` gained transparent encrypt/decrypt via a
  versioned-prefix scheme (`"enc:v1:<fernet-token>"`) — legacy plaintext rows (every existing
  Anthropic/OpenAI/GitHub key, written before this day) keep working unchanged if encryption is
  enabled later; no migration needed. New `delete_setting()`/`list_setting_keys()` for the
  dynamically-named custom-secrets set.
- New `app/security/credential_vault.py`: `ProjectCredentials` (frozen `SecretStr` model with the
  explicit `expose_secrets` serialization gate + `get_env_vars()` as the one real extraction
  point), `CredentialVault` (`load`/`store`/`inject_into_env`, wrapping `get_setting`/`set_setting`,
  every access audit-logged via the existing `app/fleet/audit_log.py` — key names only, never
  values).
- `app/agents/tools.py`'s `make_coder_handlers()` gained `extra_env` — merged into the `bash` tool's
  subprocess env when present, the real "injected into agents" mechanism for custom secrets.
- Threaded `extra_env` through `run_coder()`/`run_backend_dev()`/`run_frontend_dev()` and both real
  pipeline entry points — `launch_manager()` ("full" mode) AND `launch_coder()` ("simple" mode),
  explicitly checking both per the Days 11-15 gap-closure's own lesson about wiring gaps. Neither
  GitHub token nor Anthropic key are ever injected into the generic bash env (popped before
  injection) — only genuinely-custom secrets flow into the coding sandbox, a deliberate,
  safety-conscious narrowing beyond what the plan's literal pseudocode specified.
- `POST/GET/DELETE /api/settings/custom-secrets(/{name})` (adapted from the plan's fictional
  `/api/projects/{id}/credentials` to this project's real global-settings routing, matching the
  existing github-token/api-key endpoint convention exactly).

## Testing

20 new tests (`test_credential_vault.py`): encrypt/decrypt passthrough-when-unconfigured and real
round-trip, empty-string never encrypted, legacy plaintext rows still readable once encryption is
enabled later, invalid Fernet key rejected at Settings load, real DB round-trip proving the stored
value is actual ciphertext while reads return the decrypted plaintext, `SecretStr` masking in
repr/str/model_dump (default masked, `expose_secrets=True` reveals), frozen-model immutability,
`get_env_vars()`'s single-extraction-point behavior, `CredentialVault` store/load/inject_into_env
real round-trip, a real log-capture test proving a stored secret value never appears in any log
line, audit-log entries carrying key names only (never values), the bash tool actually seeing an
injected custom secret (and NOT seeing one when none was injected), and the full custom-secrets API
lifecycle via `TestClient` (create/list/delete, invalid-name/empty-value rejection, 404 on unknown
name). Confirmed (not re-tested) the pre-existing `.env` policy-blocking tests still pass.

## Real-caller verification

```
encrypt_value()/decrypt_value() → app/db/repository.py (get_setting/set_setting — the one choke point)
delete_setting()/list_setting_keys() → app/security/credential_vault.py + app/api/settings.py
get_credential_vault() → app/api/agents.py, BOTH launch_manager() (full mode) AND launch_coder()
                          (simple mode) — explicitly checked both entry points this time
extra_env= → backend_dev.py, frontend_dev.py, coder.py, manager.py (run_manager), agents.py (x2)
```
4th clean day in a row — zero orphaned modules, and the first day to proactively wire BOTH real
pipeline entry points from the start rather than finding the gap afterward.

## Test Results

```
pytest tests/ -q
→ 2684 passed, 0 failed, 55 skipped, 17 deselected, 22 warnings in 91.26s (20 new tests)

mypy app/ --strict
→ 0 errors

Frontend: tsc --noEmit (clean — Day 17's own plan has no frontend section, unlike Day 16)
```

## Verdict
✅ GREEN FLAG — DAY 17 COMPLETE. Ready for Day 18 (Real-Time Streaming to Frontend).
