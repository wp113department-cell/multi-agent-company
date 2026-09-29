"""Production audit 06 (2026-09-29): every Settings field must be documented in
backend/.env.example (set, or listed commented-out with its default).

174 of 301 fields were missing — including operator-critical ones like
DEPLOYMENT_ENV, BASH_SANDBOX_ENABLED and BG_PROCESS_REGISTRY_PATH — after the
July audit had closed the same gap once; later features re-opened it because
nothing enforced it. This test is that enforcement.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_every_setting_is_documented_in_env_example() -> None:
    documented = set(
        re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.M)
    )
    fields = {name.upper() for name in Settings.model_fields}
    missing = sorted(fields - documented)
    assert missing == [], (
        f"{len(missing)} setting(s) not in backend/.env.example "
        f"(add them, commented out with their default): {missing}"
    )


def test_env_example_has_no_stale_keys() -> None:
    documented = set(
        re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.M)
    )
    fields = {name.upper() for name in Settings.model_fields}
    aliases = {
        (f.alias or "").upper() for f in Settings.model_fields.values() if f.alias
    }
    stale = sorted(documented - fields - aliases)
    assert stale == [], f"keys in .env.example that config.py no longer reads: {stale}"
