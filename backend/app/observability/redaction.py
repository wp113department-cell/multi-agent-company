"""One redaction layer for everything that leaves the platform (Sol A13 +
G10, 2026-10-09): Sentry events and breadcrumbs, structured logs and alert
webhooks.

Before this, Sentry's before_send returned events unchanged (despite a
"never send secrets" comment), and logs/alerts had no redaction at all, so
an exception message, a request header or a tool input holding a key went
out as is. Three layers, applied to every string anywhere in the payload:

1. the platform's own secret VALUES (API keys, JWT secret, encryption key,
   database/redis passwords, GitHub token...) — exact matches, whatever the
   surrounding text;
2. well-known secret SHAPES (sk-ant-..., ghp_/github_pat_..., Bearer
   tokens, AWS keys, Slack tokens, JWTs, passwords inside URLs);
3. fields whose NAME says secret (password, token, api_key, authorization,
   cookie, dsn...) are replaced whole.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

REDACTED = "[REDACTED]"

_SHAPES = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    ),
]
# user:password@ inside any URL
_URL_PASSWORD = re.compile(r"([a-z][a-z0-9+.\-]*://[^/\s:@]+:)([^@\s/]+)(@)", re.I)
_SECRET_KEY_NAME = re.compile(
    r"(?i)(pass(word|wd)?|secret|token|api[_\-]?key|authorization|cookie|"
    r"credential|private[_\-]?key|dsn|session[_\-]?id|signature)"
)
_SETTING_NAMES = (
    "anthropic_api_key",
    "groq_api_key",
    "gemini_api_key",
    "voyage_api_key",
    "openai_api_key",
    "github_token",
    "jwt_secret_key",
    "credential_encryption_key",
    "default_admin_password",
    "sentry_dsn",
    "alert_webhook_url",
    "database_url",
    "redis_url",
    "migration_database_url",
)
_ENV_SECRET = re.compile(r"(?i)(KEY|SECRET|TOKEN|PASSWORD|PASSWD|DSN|CREDENTIAL)")
_cache: tuple[float, list[str]] | None = None


def _values_from(raw: str) -> list[str]:
    """A secret setting's value, plus the password part of a URL."""
    out = [raw]
    try:
        parts = urlsplit(raw)
        if parts.password:
            out.append(parts.password)
    except ValueError:
        pass
    return out


def secret_values() -> list[str]:
    """The platform's own secret values (cached briefly; longest first so a
    value containing another is replaced whole)."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < 60:
        return _cache[1]
    found: set[str] = set()
    try:
        from app.config import get_settings

        settings = get_settings()
        for name in _SETTING_NAMES:
            value: Any = getattr(settings, name, None)
            getter = getattr(value, "get_secret_value", None)
            if callable(getter):
                value = getter()
            if isinstance(value, str) and value:
                found.update(_values_from(value))
    except Exception:
        pass
    for name, value in os.environ.items():
        if value and _ENV_SECRET.search(name):
            found.update(_values_from(value))
    values = sorted((v for v in found if len(v) >= 8), key=len, reverse=True)
    _cache = (now, values)
    return values


def reset_cache() -> None:
    global _cache
    _cache = None


def redact_text(text: str) -> str:
    if not text:
        return text
    for value in secret_values():
        if value in text:
            text = text.replace(value, REDACTED)
    for shape in _SHAPES:
        text = shape.sub(REDACTED, text)
    return _URL_PASSWORD.sub(rf"\g<1>{REDACTED}\g<3>", text)


def redact(obj: Any, _depth: int = 0) -> Any:
    """A copy of `obj` (dicts, lists, tuples, strings) with secrets removed."""
    if _depth > 40:
        return obj
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            if isinstance(key, str) and _SECRET_KEY_NAME.search(key) and value:
                out[key] = REDACTED
            else:
                out[key] = redact(value, _depth + 1)
        return out
    if isinstance(obj, list):
        # request headers arrive as [[name, value], ...]
        if all(isinstance(i, (list, tuple)) and len(i) == 2 for i in obj) and obj:
            return [
                (
                    [k, REDACTED]
                    if isinstance(k, str) and _SECRET_KEY_NAME.search(k)
                    else [k, redact(v, _depth + 1)]
                )
                for k, v in obj
            ]
        return [redact(i, _depth + 1) for i in obj]
    if isinstance(obj, tuple):
        return tuple(redact(i, _depth + 1) for i in obj)
    return obj


def sentry_before_send(event: Any, hint: Any) -> Any:
    """Sentry hook: every string in the event (exception messages, frame
    variables, request data and headers, breadcrumbs, extra) is redacted."""
    return redact(event)


def sentry_before_breadcrumb(crumb: Any, hint: Any) -> Any:
    return redact(crumb)
