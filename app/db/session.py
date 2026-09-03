"""Async SQLAlchemy engine and session factory — lazy initialisation."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

# Engine and session factory are created lazily on first use.
# This avoids calling get_settings() at import time (which would fail in tests
# before environment variables are set).
_engine = None
_AsyncSessionFactory = None


def _get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=s.app_env == "development",
        )
    return _engine


def _get_session_factory():
    global _AsyncSessionFactory
    if _AsyncSessionFactory is None:
        _AsyncSessionFactory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _AsyncSessionFactory


# Keep backward-compatible names used elsewhere in the codebase
@property  # type: ignore[misc]
def engine():
    return _get_engine()


@property  # type: ignore[misc]
def AsyncSessionFactory():
    return _get_session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async database session."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
