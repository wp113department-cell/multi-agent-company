"""Shared slowapi Limiter instance.

Split out of main.py so route modules (app/api/*.py) can import `limiter`
directly to apply per-route @limiter.limit(...) decorators without a
circular import (main.py imports every router module at startup).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

import slowapi.middleware as _slowapi_middleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.routing import BaseRoute, Match
from starlette.types import Scope

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


# ---------------------------------------------------------------------------
# k6 load-test gap-closure (2026-08-10) — SlowAPIMiddleware was silently
# NOT rate-limiting almost every real route in this app.
#
# Root cause, confirmed by direct reproduction (not guessed): slowapi==0.1.10
# (the latest release — no newer version exists upstream) resolves the
# matched route handler for a request via slowapi.middleware._find_route_handler(),
# which walks `app.routes` calling `route.matches(scope)` on each entry.
# That function predates a change in this project's installed Starlette
# (1.3.1, via fastapi==0.139.0): routes registered through
# `app.include_router(...)` — i.e. every real API route in this app except
# the handful defined directly with `@app.get(...)` on `app` itself
# (only `/health`) — are no longer stored as flat `Route`/`APIRoute`
# objects on `app.routes`. They're wrapped in an internal `_IncludedRouter`
# object that has neither `.matches()` nor `.endpoint`, so
# `_find_route_handler` silently returns `handler=None` for all of them.
# slowapi's own `_should_exempt()` then treats `handler is None` as
# "exempt from rate limiting" — so every included-router route (tasks,
# agents, metrics, chat, epics, approvals, ...) was never actually
# rate-limited at all, while `/health` (a plain top-level route, still
# correctly resolved) was the ONE endpoint actually enforcing
# rate_limit_default. Reproduced directly:
#   _find_route_handler(app.routes, {"type": "http", "method": "GET",
#       "path": "/api/agents", "path_params": {}})  ->  None
#   _find_route_handler(app.routes, {"type": "http", "method": "GET",
#       "path": "/health", "path_params": {}})       ->  <function health>
# This is exactly what the k6 load-test workflow surfaced: only `/health`
# (10 VUs x ~1 req/s each, well above its 200/minute-per-IP default limit)
# got 429s; every other tested endpoint, despite having the identical
# default limit, was silently unthrottled.
#
# Fix: monkeypatch _find_route_handler with a version that recurses into
# `_IncludedRouter`-style wrappers (duck-typed via `.original_router`, so
# this stays correct even if Starlette renames the internal class) instead
# of only walking the flat top-level list. Everything else about slowapi
# (Limiter, decorator-based per-route limits, storage backend, header
# injection) is untouched — only this one broken route-resolution helper
# is replaced.
# ---------------------------------------------------------------------------


def _find_route_handler_recursive(
    routes: Iterable[BaseRoute], scope: Scope
) -> Optional[Callable[..., Any]]:
    handler: Optional[Callable[..., Any]] = None
    for route in routes:
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            found = _find_route_handler_recursive(nested_router.routes, scope)
            if found is not None:
                handler = found
            continue
        matches = getattr(route, "matches", None)
        if matches is None:
            continue
        match, _ = matches(scope)
        if match == Match.FULL and hasattr(route, "endpoint"):
            handler = route.endpoint
    return handler


_slowapi_middleware._find_route_handler = _find_route_handler_recursive
