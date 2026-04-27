"""Alembic environment — async с SQLAlchemy 2.0.

Конфигурируется из :mod:`wotk.core.config` (database_url подставляется
программно). target_metadata = :attr:`wotk.domain.models.Base.metadata` —
позволяет ``alembic revision --autogenerate`` видеть все ORM-модели.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from wotk.core.config import get_settings
from wotk.domain.models import Base

#: Metadata всех ORM-моделей — нужно для autogenerate.
target_metadata = Base.metadata

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Offline-режим: генерация SQL без подключения к БД.

    Использование: ``alembic upgrade head --sql > migration.sql``.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Применить миграции в существующем соединении.

    :param connection: Sync wrapper async-соединения от run_sync.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async-режим: открыть engine, прогнать миграции, dispose."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Online-режим: запустить async-миграции через :func:`asyncio.run`."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
