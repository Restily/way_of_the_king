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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from wotk.api.main import app
from wotk.core.config import get_settings
from wotk.core.db import get_session


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


# TRUNCATE-cleanup в отдельном connection: asyncpg не уживается с nested
# transactions через shared connection ("another operation in progress").
# `transaction` обязан быть TRUNCATE (не DELETE) — на нём append-only
# BEFORE DELETE trigger, который RAISE'ит на любой DELETE.
_USER_TABLES = (
    "campaign_progress",
    "daily_dungeon_entries",
    "run_encounters",
    "dungeon_runs",
    '"transaction"',
    "idempotency_keys",
    "item",
    "affix_definition",
    "item_base",
    "dungeons",
    "referral",
    "hero",
    "balance",
    "profile",
)
# Reference-таблицы (item_base, affix_definition, dungeons) тоже чистим —
# тесты создают свои seed'ы локально через factory-helpers.


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


@pytest.fixture
def anyio_backend() -> str:
    """Используем asyncio backend для anyio (если кто-то добавит anyio тесты).

    :returns: ``"asyncio"``.
    """
    return "asyncio"


# ============================================================================
# HTTP client fixture (для всех e2e тестов через ASGI transport)
# ============================================================================

from ._helpers import (  # noqa: E402  — local import below imports
    E2E_BOT_TOKEN,
    E2E_INTERNAL_HMAC_SECRET,
)


@pytest_asyncio.fixture
async def client(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """E2E HTTP-клиент через ASGI transport.

    Подменяет :func:`wotk.core.db.get_session` на factory против test_engine
    с production-семантикой commit/rollback. Подменяет TELEGRAM_BOT_TOKEN
    на стабильный test-token.

    :param test_engine: Session-scoped engine с применёнными миграциями.
    :param monkeypatch: Для подмены env переменных.
    :yields: Готовый :class:`httpx.AsyncClient`.
    """
    test_factory = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, autoflush=False
    )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with test_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", E2E_BOT_TOKEN)
    monkeypatch.setenv(
        "INTERNAL_HMAC_REALTIME_TO_API", E2E_INTERNAL_HMAC_SECRET.decode()
    )
    monkeypatch.setenv(
        "INTERNAL_HMAC_API_TO_REALTIME", "test_internal_hmac_api_to_realtime_e2e"
    )
    get_settings.cache_clear()

    # Disable rate-limiter в тестах — иначе пакет тестов превышает 20/min на /login
    # и тесты начинают рандомно падать. В prod limiter полностью активен.
    from wotk.core.limiter import limiter

    limiter.enabled = False
    limiter.reset()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    get_settings.cache_clear()
