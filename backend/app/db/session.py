from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url, echo=settings.debug, pool_pre_ping=True
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
    """
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


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
