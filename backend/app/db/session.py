from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _connect_args(settings: Settings) -> dict[str, Any]:
    """AUDIT_Q_BATCH08 §66 'Timeout handling': no statement_timeout/
    command_timeout anywhere in the session/engine config — a hung query
    (e.g. a lock wait against a busy table) could previously block its
    connection, and transitively whatever request handler or agent run was
    awaiting it, indefinitely. asyncpg applies server_settings via `SET` at
    connection time, so this is a real server-side enforced timeout, not a
    client-side guess. db_statement_timeout_ms=0 opts back out (Postgres's
    own default: no timeout) for a deployment that needs a longer-running
    query than the default allows."""
    if settings.db_statement_timeout_ms <= 0:
        return {}
    return {
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms)
        }
    }


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        # Blocker (audit_v1.md 4.7 #2): no explicit pool_size/max_overflow —
        # SQLAlchemy's async default (5 + 10 overflow = 15) is already
        # smaller than max_concurrent_agent_runs's own designed ceiling (20),
        # before accounting for request-handling connections and this
        # codebase's own isolated throwaway engines (new_isolated_async_engine
        # above). Under real concurrent load this risked QueuePool limit
        # exceeded surfacing as opaque 500s or silently-failed background
        # tasks. Real config values (db_pool_size/db_pool_max_overflow), not
        # hardcoded numbers.
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            connect_args=_connect_args(settings),
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


def new_isolated_async_engine() -> AsyncEngine:
    """A throwaway async engine for code that bridges sync -> async via its
    own asyncio.run() call (e.g. a LangGraph node, which is itself a sync
    callable). Never reuse the shared get_engine() singleton for this —
    asyncpg connections are bound to the event loop they were created on,
    and asyncio.run() tears down its loop after every call, so a connection
    borrowed from the shared pool raises "attached to a different loop" on
    the second such call. app/fleet/versioned_memory.py was the first place
    this pattern was needed; app/memory/store.py's query_memory_context_sync
    is the second.

    Callers dispose() this engine right after their single asyncio.run()
    call returns, so it never holds pool_size connections open concurrently
    — but it still shares the same explicit pool_size/max_overflow config as
    get_engine() (rather than silently falling back to SQLAlchemy's smaller
    async defaults) so a caller that batches multiple concurrent sessions
    against one isolated engine gets the same tuned ceiling as the shared
    pool (audit_v1.md 4.7 #2 follow-up: AUDIT_Q_BATCH05 §46 "Connection
    pooling").
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        connect_args=_connect_args(settings),
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for use in background tasks (not FastAPI dependencies)."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
