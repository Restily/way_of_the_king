"""Async DB engine + session factory + FastAPI dependency."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wotk.core.config import get_settings

log = structlog.get_logger()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _mask_url(url: str) -> str:
    """Маскирует пароль для логов."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def get_engine() -> AsyncEngine:
    """Singleton async engine. Инициализируется лениво."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        log.info("db_engine_created", url=_mask_url(settings.database_url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def _open_session() -> AsyncIterator[AsyncSession]:
    """Общий тело: open session, yield, commit on success / rollback on error."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# FastAPI dependency: используется как `Depends(get_session)`.
get_session = _open_session

# CLI / cron / воркеры: `async with session_scope() as session:`.
session_scope = asynccontextmanager(_open_session)


async def dispose_engine() -> None:
    """Закрыть engine (вызывается на shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("db_engine_disposed")
