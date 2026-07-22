"""Day 17 — Credential Vault.

Real DB round trips throughout (matches the plan's own stated test scope:
"Store a fake GitHub token. Load it. Inject into agent env. Confirm token
never appears in any log line"). The policy engine's .env-write-blocking
(the plan's own success criterion "agent cannot write token to .env file")
is NOT re-tested here — it already exists and is already covered by
tests/test_policy.py (test_env_denied, test_env_local_denied,
test_env_inside_worktree_still_denied), confirmed by reading both files
before writing this one, per docs/DAY17_PLAN.md's plan/reality correction #3.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from app.security.credential_vault import (
    ProjectCredentials,
    decrypt_value,
    encrypt_value,
)


@pytest.fixture(autouse=True)
def _reset_settings_and_warning_flag():
    from app.config import reset_settings_cache

    reset_settings_cache()  # noqa: E702
    import app.security.credential_vault as cv

    cv._warned_plaintext = False
    yield
    reset_settings_cache()  # noqa: E702
    cv._warned_plaintext = False


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# encrypt_value / decrypt_value
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    def test_passthrough_when_no_key_configured(self) -> None:
        assert encrypt_value("plaintext-secret") == "plaintext-secret"
        assert decrypt_value("plaintext-secret") == "plaintext-secret"

    def test_empty_string_never_encrypted(self, monkeypatch) -> None:
        from cryptography.fernet import Fernet

        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702
        assert encrypt_value("") == ""

    def test_real_roundtrip_with_key_configured(self, monkeypatch) -> None:
        from cryptography.fernet import Fernet

        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702

        encrypted = encrypt_value("super-secret-value")
        assert encrypted != "super-secret-value"
        assert encrypted.startswith("enc:v1:")
        assert decrypt_value(encrypted) == "super-secret-value"

    def test_legacy_plaintext_row_still_readable_once_encryption_enabled(
        self, monkeypatch
    ) -> None:
        """Backward compatibility: rows written before CREDENTIAL_ENCRYPTION_KEY
        was ever set (e.g. Day 9/14's original Anthropic/GitHub keys) must not
        break once a key gets configured later."""
        legacy_plaintext = "sk-ant-legacy-key-written-before-encryption"

        from cryptography.fernet import Fernet

        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702

        assert decrypt_value(legacy_plaintext) == legacy_plaintext

    def test_invalid_fernet_key_rejected_at_settings_load(self, monkeypatch) -> None:
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "not-a-valid-fernet-key")
        from app.config import Settings, reset_settings_cache

        reset_settings_cache()  # noqa: E702
        with pytest.raises(ValueError, match="not a valid Fernet key"):
            Settings()


# ---------------------------------------------------------------------------
# get_setting / set_setting — real DB, with real encryption
# ---------------------------------------------------------------------------


class TestSettingEncryptionAtRest:
    def test_stored_value_is_encrypted_but_reads_back_decrypted(self, monkeypatch) -> None:
        from cryptography.fernet import Fernet

        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702

        async def _run() -> None:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import SystemSetting
            from app.db.repository import delete_setting, get_setting, set_setting

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    await set_setting(db, "td_vault_enc_key", "top-secret-123")
                    row = (
                        await db.execute(
                            select(SystemSetting).where(SystemSetting.key == "td_vault_enc_key")
                        )
                    ).scalar_one()
                    assert "top-secret-123" not in row.value
                    assert row.value.startswith("enc:v1:")

                    value = await get_setting(db, "td_vault_enc_key")
                    assert value == "top-secret-123"

                    await delete_setting(db, "td_vault_enc_key")
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# ProjectCredentials — SecretStr masking + expose_secrets gate
# ---------------------------------------------------------------------------


class TestProjectCredentialsMasking:
    def test_repr_and_str_never_reveal_values(self) -> None:
        creds = ProjectCredentials(github_token=SecretStr("ghp_realtoken"))
        assert "ghp_realtoken" not in repr(creds)
        assert "ghp_realtoken" not in str(creds)

    def test_model_dump_default_masks_values(self) -> None:
        creds = ProjectCredentials(
            github_token=SecretStr("ghp_realtoken"),
            custom_secrets={"NPM_TOKEN": SecretStr("npm_realvalue")},
        )
        dumped = creds.model_dump()
        assert dumped["github_token"] == "**********"
        assert dumped["custom_secrets"]["NPM_TOKEN"] == "**********"
        assert "ghp_realtoken" not in str(dumped)
        assert "npm_realvalue" not in str(dumped)

    def test_model_dump_exposed_reveals_real_values(self) -> None:
        creds = ProjectCredentials(github_token=SecretStr("ghp_realtoken"))
        dumped = creds.model_dump(context={"expose_secrets": True})
        assert dumped["github_token"] == "ghp_realtoken"

    def test_get_env_vars_is_the_only_place_secrets_are_extracted(self) -> None:
        creds = ProjectCredentials(
            github_token=SecretStr("ghp_x"),
            anthropic_api_key=SecretStr("sk-ant-y"),
            custom_secrets={"NPM_TOKEN": SecretStr("npm_z")},
        )
        env = creds.get_env_vars()
        assert env == {
            "GITHUB_TOKEN": "ghp_x",
            "ANTHROPIC_API_KEY": "sk-ant-y",
            "NPM_TOKEN": "npm_z",
        }

    def test_frozen_model_cannot_be_mutated(self) -> None:
        creds = ProjectCredentials(github_token=SecretStr("ghp_x"))
        with pytest.raises(Exception):
            creds.github_token = SecretStr("ghp_changed")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CredentialVault — real DB round trip + audit logging
# ---------------------------------------------------------------------------


class TestCredentialVault:
    def test_store_load_inject_into_env_roundtrip(self) -> None:
        async def _run() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.repository import delete_setting
            from app.security.credential_vault import get_credential_vault

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    vault = get_credential_vault()
                    creds = ProjectCredentials(
                        github_token=SecretStr("ghp_faketoken"),
                        custom_secrets={"NPM_TOKEN": SecretStr("npm_fake")},
                    )
                    await vault.store(db, creds)

                    loaded = await vault.load(db)
                    assert loaded.github_token is not None
                    assert loaded.github_token.get_secret_value() == "ghp_faketoken"
                    assert loaded.custom_secrets["NPM_TOKEN"].get_secret_value() == "npm_fake"

                    env = await vault.inject_into_env(db)
                    assert env["GITHUB_TOKEN"] == "ghp_faketoken"
                    assert env["NPM_TOKEN"] == "npm_fake"

                    await delete_setting(db, "github_token")
                    await delete_setting(db, "custom_secret:NPM_TOKEN")
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())

    def test_load_and_store_never_log_the_real_value(self, caplog) -> None:
        """The plan's own success criterion: confirm the token never appears
        in any log line."""
        import logging

        async def _run() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.repository import delete_setting
            from app.security.credential_vault import get_credential_vault

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    vault = get_credential_vault()
                    with caplog.at_level(logging.DEBUG):
                        await vault.store(
                            db, ProjectCredentials(github_token=SecretStr("ghp_should_never_log"))
                        )
                        await vault.load(db)
                    await delete_setting(db, "github_token")
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())
        assert "ghp_should_never_log" not in caplog.text

    def test_audit_log_records_key_names_only(self) -> None:
        async def _run() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.repository import delete_setting
            from app.fleet.audit_log import get_audit_log
            from app.security.credential_vault import get_credential_vault

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    vault = get_credential_vault()
                    await vault.store(
                        db, ProjectCredentials(github_token=SecretStr("ghp_audit_test_value"))
                    )
                    entries = get_audit_log().recent(20)
                    store_entries = [e for e in entries if e.action_type == "credential_store"]
                    assert store_entries, "expected at least one credential_store audit entry"
                    latest = store_entries[-1]
                    assert "github_token" in latest.description
                    assert "ghp_audit_test_value" not in latest.description
                    await delete_setting(db, "github_token")
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# extra_env injection into the bash tool (Day 17's real "inject into agents")
# ---------------------------------------------------------------------------


class TestBashToolExtraEnv:
    def test_bash_tool_sees_injected_custom_secret(self, tmp_path) -> None:
        from app.agents.tools import make_coder_handlers

        handlers = make_coder_handlers(
            str(tmp_path), str(tmp_path), extra_env={"MY_CUSTOM_SECRET": "injected-value-123"}
        )
        result = handlers["bash"]({"command": "echo $MY_CUSTOM_SECRET"})
        assert "injected-value-123" in result

    def test_bash_tool_without_extra_env_does_not_see_unset_var(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("MY_CUSTOM_SECRET", raising=False)
        from app.agents.tools import make_coder_handlers

        handlers = make_coder_handlers(str(tmp_path), str(tmp_path))
        result = handlers["bash"]({"command": "echo $MY_CUSTOM_SECRET"})
        assert "injected-value-123" not in result


# ---------------------------------------------------------------------------
# Custom secrets API (POST/GET/DELETE /api/settings/custom-secrets)
# ---------------------------------------------------------------------------


class TestCustomSecretsApi:
    def test_full_lifecycle_via_http(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            list_resp = client.get("/api/settings/custom-secrets")
            assert list_resp.status_code == 200
            assert "TD_TEST_SECRET" not in list_resp.json()["names"]

            create_resp = client.post(
                "/api/settings/custom-secrets",
                json={"name": "TD_TEST_SECRET", "value": "some-real-value"},
            )
            assert create_resp.status_code == 200, create_resp.text
            assert create_resp.json() == {"saved": True, "name": "TD_TEST_SECRET"}

            list_resp2 = client.get("/api/settings/custom-secrets")
            assert "TD_TEST_SECRET" in list_resp2.json()["names"]
            # Values are never returned by the list endpoint.
            assert "some-real-value" not in list_resp2.text

            delete_resp = client.delete("/api/settings/custom-secrets/TD_TEST_SECRET")
            assert delete_resp.status_code == 200
            assert delete_resp.json()["deleted"] is True

            list_resp3 = client.get("/api/settings/custom-secrets")
            assert "TD_TEST_SECRET" not in list_resp3.json()["names"]

    def test_rejects_invalid_name(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/settings/custom-secrets",
                json={"name": "not a valid name!", "value": "x"},
            )
            assert resp.status_code == 400

    def test_rejects_empty_value(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/settings/custom-secrets",
                json={"name": "TD_EMPTY_TEST", "value": "   "},
            )
            assert resp.status_code == 400

    def test_delete_404_for_unknown_name(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.delete("/api/settings/custom-secrets/TD_DOES_NOT_EXIST")
            assert resp.status_code == 404
