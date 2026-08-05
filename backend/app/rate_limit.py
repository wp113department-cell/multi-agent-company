"""Shared slowapi Limiter instance.

Split out of main.py so route modules (app/api/*.py) can import `limiter`
directly to apply per-route @limiter.limit(...) decorators without a
circular import (main.py imports every router module at startup).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

# Keyed by remote IP; the blanket default_limits below apply to every route
# automatically via SlowAPIMiddleware (see main.py). Routes that need a
# tighter limit than the default (login, task/epic/agent dispatch) apply
# their own @limiter.limit(...) decorator, which overrides the default for
# that route rather than stacking with it.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[get_settings().rate_limit_default],
    enabled=get_settings().rate_limit_enabled,
)
