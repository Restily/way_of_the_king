"""Структурное логирование через structlog.

Конфигурация:

* В ``APP_ENV=development`` — human-readable вывод с цветами,
  для удобства dev'а в терминале.
* В ``staging`` / ``production`` — JSON (одна строка = один event),
  чтобы log shipper (Loki / Vector) парсил без heuristics.

Везде:

* ``contextvars`` processor — подхватывает ``request_id`` / ``method`` /
  ``path`` из :class:`wotk.core.middleware.RequestIdMiddleware`.
* Уровень — из ``settings.log_level``.

Вызывается один раз на startup из :mod:`wotk.api.main` (lifespan).
"""

from __future__ import annotations

import logging

import structlog

from wotk.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Сконфигурировать stdlib + structlog.

    Идемпотентна: повторный вызов перезатирает конфигурацию (полезно
    в тестах когда test client пересоздаёт app).

    :param settings: :class:`Settings` инстанс — читаем app_env + log_level.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # stdlib root logger — иначе uvicorn/sqlalchemy/aiogram пишут мимо structlog.
    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,
    )

    is_prod = settings.app_env in ("staging", "production")

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    final_renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if is_prod
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            final_renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
