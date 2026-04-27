"""pytest fixtures для интеграционных тестов с БД.

Стратегия:

* Используется dedicated test database (по env ``TEST_DATABASE_URL``,
  fallback на ``DATABASE_URL`` с суффиксом ``_test``).
* Перед сессией (session scope): миграции применяются один раз через
  subprocess ``alembic upgrade head`` (in-process вызов конфликтует
  с pytest-asyncio loop через ``asyncio.run`` в env.py).
* Каждый тест выполняется в SAVEPOINT внутри outer transaction,
  rollback после теста — состояние БД чистое.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def _test_database_url() -> str:
    """URL test-БД. Из ``TEST_DATABASE_URL`` или ``_test`` суффикс к dev DB.

    :returns: SQLAlchemy URL для async-driver postgres.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://wotk:wotk_dev@localhost:5432/wotk",
    )
    if "/" in base:
        prefix, db = base.rsplit("/", 1)
        return f"{prefix}/{db}_test"
    return base + "_test"


def _run_alembic(args: list[str], db_url: str) -> subprocess.CompletedProcess[str]:
    """Запустить alembic в subprocess с подменённым DATABASE_URL.

    Subprocess нужен потому что alembic env.py вызывает ``asyncio.run()``,
    что конфликтует с активным pytest-asyncio loop'ом при in-process вызове.

    :param args: Аргументы команды (``["upgrade", "head"]`` или ``["downgrade", "base"]``).
    :param db_url: SQLAlchemy URL для применения.
    :returns: Результат subprocess.run.
    """
    backend_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(backend_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine для test-БД. Применяет миграции один раз.

    :yields: Готовый :class:`AsyncEngine` подключённый к test-БД.
    """
    db_url = _test_database_url()

    # downgrade сначала на случай предыдущего неуспешного прогона.
    # Падение здесь некритично (БД может быть пустой), но лог нужен —
    # иначе потеряем настоящие OperationalError / CommandError.
    down_result = _run_alembic(["downgrade", "base"], db_url)
    if down_result.returncode != 0:
        print(f"[conftest] alembic downgrade skipped: {down_result.stderr.strip()}")

    up_result = _run_alembic(["upgrade", "head"], db_url)
    if up_result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed:\nstdout:\n{up_result.stdout}\n"
            f"stderr:\n{up_result.stderr}"
        )

    # NullPool — каждое подключение свежее, никакого shared-state между
    # тестами / fixtures. Asyncpg плохо переносит pooling в тестовом контексте.
    engine = create_async_engine(db_url, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


# TRUNCATE pattern вместо SAVEPOINT: asyncpg не уживается с nested transactions
# через shared connection ("another operation in progress"). DELETE+TRUNCATE
# через отдельный connection после теста — надёжнее и чище.
_USER_TABLES = (
    "referral",
    "hero",
    "balance",
    "profile",
)


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session. После теста все таблицы очищаются TRUNCATE.

    :param test_engine: Session-scoped engine.
    :yields: Изолированная :class:`AsyncSession`.
    """
    factory = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                f"TRUNCATE TABLE {', '.join(_USER_TABLES)} "
                "RESTART IDENTITY CASCADE"
            )
        )
        # transaction партиционирована — TRUNCATE на parent не работает
        # для всех партиций, проще DELETE.
        await conn.execute(text('DELETE FROM "transaction"'))


@pytest.fixture
def anyio_backend() -> str:
    """Используем asyncio backend для anyio (если кто-то добавит anyio тесты).

    :returns: ``"asyncio"``.
    """
    return "asyncio"
