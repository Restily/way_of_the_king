"""pytest fixtures для интеграционных тестов с БД.

Стратегия:
- Используется dedicated test database (по env TEST_DATABASE_URL,
  fallback на DATABASE_URL с суффиксом `_test`).
- Перед сессией (session scope): миграции применяются на чистую БД.
- Каждый тест выполняется в SAVEPOINT внутри outer transaction,
  rollback после теста — состояние БД чистое.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _test_database_url() -> str:
    """URL test-БД. Берёт из TEST_DATABASE_URL или конструирует _test суффикс."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://wotk:wotk_dev@localhost:5432/wotk",
    )
    # Замена имени БД на <db>_test
    if "/" in base:
        prefix, db = base.rsplit("/", 1)
        return f"{prefix}/{db}_test"
    return base + "_test"


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine для test-БД. Применяет миграции один раз."""
    engine = create_async_engine(_test_database_url(), echo=False)

    # Применяем миграции через программный вызов alembic
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _test_database_url())
    # downgrade сначала на случай предыдущего неуспешного прогона.
    # Падение здесь некритично (БД может быть пустой), но лог нужен —
    # иначе потеряем настоящие OperationalError / CommandError.
    try:
        command.downgrade(cfg, "base")
    except Exception as e:  # noqa: BLE001
        print(f"[conftest] alembic downgrade skipped: {e!r}")
    command.upgrade(cfg, "head")

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session с rollback после теста.

    Open connection → BEGIN → SAVEPOINT → yield session.
    После теста: ROLLBACK (откатывает всё что натестили).
    """
    async with test_engine.connect() as connection:
        async with connection.begin():
            # Nested SAVEPOINT для теста
            session_factory = async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                autoflush=False,
                class_=AsyncSession,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory() as session:
                yield session
            # Конец `async with connection.begin()` → rollback


@pytest.fixture
def anyio_backend() -> str:
    """Используем asyncio backend для anyio (если кто-то добавит anyio тесты)."""
    return "asyncio"
