from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine
from app.config.settings import Settings
from typing import AsyncGenerator

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

async def get_async_engine():
    settings = Settings.get_instance()
    database_url = settings.get_database_url()

    # Convert sync URL to async URL if needed
    if database_url and database_url.startswith("postgresql"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url and database_url.startswith("sqlite"):
        async_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")
    else:
        raise ValueError(f"Database URL {database_url} not supported for async engine")

    return create_async_engine(
        async_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )

async def get_db() -> AsyncGenerator[sessionmaker, None]:
    engine = await get_async_engine()
    async_session_factory = sessionmaker(
        engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()