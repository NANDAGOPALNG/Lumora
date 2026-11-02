from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.config.settings import Settings
from typing import Any, AsyncGenerator, Dict, Tuple

def get_sync_engine() -> Engine:
    settings = Settings.get_instance()
    database_url = settings.get_database_url()

    if database_url and database_url.startswith("postgresql"):
        return create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
    else:
        raise ValueError(f"Database URL {database_url} not supported for sync engine")

def _build_async_url_and_connect_args(database_url: str):
    """Normalize a configured DATABASE_URL for the async SQLAlchemy engine.

    Handles two concerns:
      * picking the correct async driver (asyncpg / aiosqlite), via
        SQLAlchemy's URL object rather than a naive string replace, so it
        doesn't double up a driver that's already present.
      * for PostgreSQL, translating libpq-only query parameters (like
        `sslmode`, as used by Neon) into the connect-time arguments
        asyncpg actually understands, since asyncpg's connect() rejects
        an `sslmode` keyword outright.
    """
    url = make_url(database_url)
    connect_args: Dict[str, Any] = {}

    if url.drivername.startswith("postgresql"):
        query = dict(url.query)

        # asyncpg doesn't accept the libpq `sslmode` kwarg, but (since
        # asyncpg 0.24) it accepts the same values directly via its own
        # `ssl` connect argument - so translate rather than drop it,
        # preserving the TLS requirement for Neon.
        sslmode = query.pop("sslmode", None)
        if sslmode:
            connect_args["ssl"] = sslmode

        # Also libpq-only / not understood by asyncpg's connect().
        query.pop("channel_binding", None)

        url = url.set(drivername="postgresql+asyncpg", query=query)
    elif url.drivername.startswith("sqlite"):
        url = url.set(drivername="sqlite+aiosqlite")
    else:
        raise ValueError(f"Database URL driver '{url.drivername}' not supported for async engine")

    return url, connect_args

_engine = None
_session_factory = None


async def get_async_engine():
    """Return the process-wide async engine, creating it on first use.

    The engine (and its connection pool) must be created once and
    reused: building a new engine per request would open a fresh pool
    every time and never release it. `dispose_engine()` is called at
    application shutdown.
    """
    global _engine
    if _engine is not None:
        return _engine

    settings = Settings.get_instance()
    database_url = settings.get_database_url()

    if not database_url:
        raise ValueError("Database URL is not configured")

    async_url, connect_args = _build_async_url_and_connect_args(database_url)

    _engine = create_async_engine(
        async_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
        connect_args=connect_args,
    )
    return _engine


async def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        engine = await get_async_engine()
        _session_factory = sessionmaker(
            engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    """Release the shared engine's connections (application shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async_session_factory = await _get_session_factory()

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
