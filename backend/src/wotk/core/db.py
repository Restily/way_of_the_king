"""Async SQLAlchemy engine + session factory + FastAPI dependency.

Модуль использует module-level singleton'ы для engine и session_factory.
Создаются лениво при первом обращении (:func:`get_engine`).
"""

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
    """Маскирует пароль в URL для безопасного логирования.

    Заменяет ``user:password@`` на ``user:***@``.

    :param url: Database connection URL.
    :returns: URL с замаскированным паролем.
    """
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def get_engine() -> AsyncEngine:
    """Возвращает singleton :class:`AsyncEngine`. Создаёт лениво при первом вызове.

    Параметры пула:

    * ``pool_size=20`` — постоянных коннектов
    * ``max_overflow=10`` — пиковых сверх pool_size
    * ``pool_pre_ping=True`` — защита от stale connections (DB рестарт)
    * ``pool_recycle=3600`` — переподключение после часа

    :returns: Готовый async engine.
    """
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
    """Singleton :class:`async_sessionmaker` для создания сессий.

    Параметры:

    * ``expire_on_commit=False`` — атрибуты не expire после commit
      (избегаем сюрпризных SELECT при чтении после commit).
    * ``autoflush=False`` — flush только явный.

    :returns: Готовая фабрика сессий.
    """
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
    """Общая реализация open-session-with-tx для FastAPI dep и context manager.

    Открывает сессию, yield'ит её, на выходе:

    * При успехе → ``await session.commit()``.
    * При исключении → ``await session.rollback()`` + re-raise.

    :yields: Открытая :class:`AsyncSession`.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


#: FastAPI dependency: ``Depends(get_session)`` в обработчиках.
get_session = _open_session

#: Context manager для CLI / cron / Arq workers:
#: ``async with session_scope() as session: ...``
session_scope = asynccontextmanager(_open_session)


async def dispose_engine() -> None:
    """Закрывает engine и сбрасывает singleton'ы.

    Вызывается на shutdown FastAPI app в lifespan.

    :returns: Ничего.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("db_engine_disposed")
