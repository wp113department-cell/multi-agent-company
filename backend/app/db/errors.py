"""Classify database failures (production audit 13).

During a real outage drill (Postgres stopped under a running app) every DB-
backed endpoint answered a bare text/plain "Internal Server Error" and login
said "Auth configuration error". An operator (and the UI) could not tell an
outage from a bug. `is_db_unavailable` recognises "cannot reach / lost the
database" so callers can answer 503 + Retry-After instead.
"""

from __future__ import annotations

import asyncio

_DRIVER_CONNECTION_ERRORS = {
    "CannotConnectNowError",
    "ConnectionDoesNotExistError",
    "ConnectionFailureError",
    "TooManyConnectionsError",
    "InternalClientError",
}


def _chain(exc: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and all(cur is not e for e in out):
        out.append(cur)
        cur = cur.__cause__ or cur.__context__
    return out


def is_db_unavailable(exc: BaseException) -> bool:
    """True only when the failure came from the database layer AND means it
    could not be reached or the connection was lost. A plain OSError or
    timeout elsewhere in the app (a missing file, a slow HTTP call) is not
    classified as a database outage."""
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

    chain = _chain(exc)
    from_db = any(
        isinstance(e, DBAPIError) or type(e).__module__.startswith("asyncpg")
        for e in chain
    )
    for e in chain:
        if isinstance(e, (OperationalError, InterfaceError)):
            return True
        if isinstance(e, DBAPIError) and e.connection_invalidated:
            return True
        if type(e).__module__.startswith("asyncpg") and (
            type(e).__name__ in _DRIVER_CONNECTION_ERRORS
        ):
            return True
    # Raw socket errors raised while opening a pool connection surface without
    # a DBAPIError wrapper; accept them only when the traceback went through
    # the database driver / pool.
    if any(isinstance(e, (ConnectionError, asyncio.TimeoutError)) for e in chain):
        if from_db:
            return True
        tb = exc.__traceback__
        while tb is not None:
            mod = tb.tb_frame.f_globals.get("__name__", "")
            if mod.startswith(("asyncpg", "sqlalchemy")):
                return True
            tb = tb.tb_next
    return False
