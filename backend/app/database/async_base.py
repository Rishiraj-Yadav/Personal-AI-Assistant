"""
Async Database Setup

Parallel async database setup using aiosqlite.
Does NOT modify existing sync database - runs alongside it.

Part of Phase 4: Async Database Migration

Usage:
    from app.database.async_base import get_async_db, init_async_db

    # Initialize at startup
    await init_async_db()

    # In routes/services
    async with get_async_session() as session:
        result = await session.execute(select(User).where(...))
        users = result.scalars().all()

Migration Strategy:
    1. Create parallel async database
    2. Gradually migrate routes to use async
    3. Both sync and async can coexist
    4. Remove sync version when fully migrated
"""

import os
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from loguru import logger

# Try to import async SQLAlchemy components
try:
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
        AsyncSession,
        AsyncEngine,
        async_sessionmaker
    )
    from sqlalchemy.pool import NullPool
    ASYNC_SQLALCHEMY_AVAILABLE = True
except ImportError:
    ASYNC_SQLALCHEMY_AVAILABLE = False
    logger.warning(
        "⚠️ Async SQLAlchemy not available. "
        "Install with: pip install sqlalchemy[asyncio] aiosqlite"
    )


# Async Database URL - uses aiosqlite driver
def get_async_database_url() -> str:
    """
    Get async database URL from environment or default.

    Converts sqlite:/// to sqlite+aiosqlite:///
    """
    sync_url = os.getenv("DATABASE_URL", "sqlite:///./data/sonarbot.db")

    # Convert to async URL
    if sync_url.startswith("sqlite:///"):
        # Use aiosqlite for SQLite
        return sync_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif sync_url.startswith("postgresql://"):
        # Use asyncpg for PostgreSQL
        return sync_url.replace("postgresql://", "postgresql+asyncpg://")
    else:
        return sync_url


# Global engine instance
_async_engine: "AsyncEngine" = None
_async_session_factory: "async_sessionmaker" = None
_initialized: bool = False


async def init_async_db() -> bool:
    """
    Initialize async database connection.

    Creates engine and session factory.
    Must be called at application startup.

    Returns:
        True if initialization successful
    """
    global _async_engine, _async_session_factory, _initialized

    if _initialized:
        return True

    if not ASYNC_SQLALCHEMY_AVAILABLE:
        logger.error("❌ Async SQLAlchemy not available")
        return False

    try:
        database_url = get_async_database_url()

        # Ensure data directory exists for SQLite
        if "sqlite" in database_url:
            db_path = database_url.split("///")[-1]
            data_dir = Path(db_path).parent
            data_dir.mkdir(parents=True, exist_ok=True)

        # Create async engine
        _async_engine = create_async_engine(
            database_url,
            echo=False,
            # Use NullPool for SQLite to avoid threading issues
            poolclass=NullPool if "sqlite" in database_url else None,
        )

        # Create session factory
        _async_session_factory = async_sessionmaker(
            _async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False
        )

        # Create tables if they don't exist
        async with _async_engine.begin() as conn:
            from app.database.models import Base
            await conn.run_sync(Base.metadata.create_all)

            # Enable WAL mode for SQLite
            if "sqlite" in database_url:
                from sqlalchemy import text
                await conn.execute(text("PRAGMA journal_mode=WAL"))

        _initialized = True
        logger.info(f"✅ Async database initialized: {database_url}")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to initialize async database: {e}")
        return False


async def close_async_db():
    """Close async database connections"""
    global _async_engine, _async_session_factory, _initialized

    if _async_engine:
        await _async_engine.dispose()
        logger.info("📊 Async database connections closed")

    _async_engine = None
    _async_session_factory = None
    _initialized = False


def get_async_engine() -> "AsyncEngine":
    """Get async engine instance"""
    if not _initialized or _async_engine is None:
        raise RuntimeError(
            "Async database not initialized. Call init_async_db() first."
        )
    return _async_engine


@asynccontextmanager
async def get_async_session() -> AsyncGenerator["AsyncSession", None]:
    """
    Get async database session.

    Usage:
        async with get_async_session() as session:
            result = await session.execute(query)
    """
    if not _initialized or _async_session_factory is None:
        raise RuntimeError(
            "Async database not initialized. Call init_async_db() first."
        )

    session = _async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_async_db() -> AsyncGenerator["AsyncSession", None]:
    """
    FastAPI dependency for async database session.

    Usage:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    """
    if not _initialized or _async_session_factory is None:
        # Try to initialize if not done
        await init_async_db()

    session = _async_session_factory()
    try:
        yield session
    finally:
        await session.close()


class AsyncDatabaseManager:
    """
    Context manager for async database operations.

    Usage:
        async with AsyncDatabaseManager() as db:
            await db.add_user(...)
    """

    def __init__(self):
        self.session: "AsyncSession" = None

    async def __aenter__(self) -> "AsyncSession":
        if not _initialized:
            await init_async_db()

        self.session = _async_session_factory()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            if exc_type:
                await self.session.rollback()
            else:
                await self.session.commit()
            await self.session.close()
