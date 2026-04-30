"""FastAPI entrypoint.

Создаёт приложение, регистрирует middleware (CORS, RequestId, SlowAPI),
подключает v1-роутеры, обрабатывает lifespan (Sentry init, DB engine cleanup).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from wotk.api.v1 import auth as auth_v1
from wotk.api.v1 import dungeons as dungeons_v1
from wotk.api.v1 import heroes as heroes_v1
from wotk.api.v1 import inventory as inventory_v1
from wotk.api.v1 import me as me_v1
from wotk.core.config import get_settings
from wotk.core.db import dispose_engine, get_session
from wotk.core.limiter import limiter
from wotk.core.logging_setup import configure_logging
from wotk.core.metrics import export_prometheus
from wotk.core.middleware import RequestIdMiddleware
from wotk.core.sentry_setup import init_sentry

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """ASGI lifespan: startup/shutdown hooks для FastAPI app.

    Startup:

    * Инициализирует Sentry (если ``SENTRY_DSN`` задан).
    * Логирует CRITICAL если в non-dev окружении пуст ``SENTRY_DSN``
      (ошибки не будут отчитываться).

    Shutdown:

    * Закрывает DB engine (отпускает коннекты).

    :param _app: FastAPI app (не используется).
    :yields: Управление между startup и shutdown.
    """
    settings = get_settings()
    configure_logging(settings)
    init_sentry(settings)
    log.info("startup", env=settings.app_env)

    if settings.app_env != "development" and not settings.sentry_dsn.get_secret_value():
        log.critical(
            "sentry_dsn_missing_in_non_dev",
            message="SENTRY_DSN is empty — errors will not be reported!",
        )

    yield
    await dispose_engine()
    log.info("shutdown")


def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """SlowAPI exception handler для ответа 429 в JSON-формате.

    :param _request: Starlette Request (не используется).
    :param exc: Исключение от SlowAPI с описанием лимита.
    :returns: JSON-response 429 с полем ``error`` и ``detail``.
    """
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "detail": str(exc.detail)},
    )


def create_app() -> FastAPI:
    """Фабрика FastAPI app.

    Регистрирует middleware (CORS → SlowAPI → RequestId), эндпоинты,
    v1-роутеры. Скрывает OpenAPI/Swagger в production
    (не помогаем атакующим перечислить endpoints).

    :returns: Сконфигурированный :class:`FastAPI` инстанс.
    """
    settings = get_settings()
    is_prod = settings.app_env == "production"

    app = FastAPI(
        title="Way Of The King API",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.app_debug,
        openapi_url=None if is_prod else "/openapi.json",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
    )

    # Жёсткий CORS allowlist (никаких "*" даже в dev).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.effective_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Requested-With",
        ],
        max_age=600,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler) # type: ignore
    app.add_middleware(SlowAPIMiddleware)

    # Request-ID middleware (после rate limiter — чтобы 429 ответы тоже имели ID)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness check: процесс жив.

        Не раскрывает версию — не помогаем атакующим таргетить known CVEs.
        Используется для load-balancer'а / docker healthcheck.

        :returns: ``{"status": "ok"}``.
        """
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready(
        session: AsyncSession = Depends(get_session),
    ) -> JSONResponse:
        """Readiness check: backend готов принимать траффик.

        Проверяет:

        * postgres pingable (``SELECT 1``)
        * миграции применены (``alembic_version`` существует и НЕ пуст)
        * redis pingable (нужен для Arq + slowapi)
        * Arq queue length < threshold (защита от backlog'а)

        Используется в GitHub Actions deploy для подтверждения успешного
        rollout. Cloudflare/Caddy дёргают ``/health`` (liveness) — он лёгкий.
        """
        checks: dict[str, str | int] = {}
        ok = True

        # postgres + migrations
        try:
            await session.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
            row = await session.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            version = row.scalar()
            if version is None:
                ok = False
                checks["migrations"] = "no alembic_version row"
            else:
                checks["migrations"] = version
        except Exception as exc:  # noqa: BLE001
            ok = False
            checks["postgres"] = f"error: {type(exc).__name__}"

        # redis
        try:
            from redis.asyncio import Redis

            settings = get_settings()
            client: Redis = Redis.from_url(
                settings.redis_url, socket_connect_timeout=2
            )
            try:
                pong = await client.ping()
                checks["redis"] = "ok" if pong else "no_pong"
                if not pong:
                    ok = False
                # Arq queue depth: ZSET arq:queue:default (default name).
                # Если очередь длиннее 1000 — backlog, не готовы принять траффик.
                queue_len = await client.zcard("arq:queue:default")
                checks["arq_queue"] = int(queue_len)
                if queue_len > 1000:
                    ok = False
                    checks["arq_queue"] = f"backlog:{queue_len}"
            finally:
                await client.close()
        except Exception as exc:  # noqa: BLE001
            ok = False
            checks["redis"] = f"error: {type(exc).__name__}"

        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ready" if ok else "not_ready", "checks": checks},
        )

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        """Prometheus exposition format endpoint (W6-052).

        Возвращает все in-process counters в text/plain; version=0.0.4.
        Не требует аутентификации — предназначен для внутреннего Prometheus
        scraper (сеть изолирована на уровне ingress).

        :returns: :class:`starlette.responses.Response` с text/plain body.
        """
        body = export_prometheus()
        return Response(
            content=body,
            media_type="text/plain; version=0.0.4",
        )

    # API v1 routers
    app.include_router(auth_v1.router, prefix="/api/v1")
    app.include_router(me_v1.router, prefix="/api/v1")
    app.include_router(heroes_v1.router, prefix="/api/v1")
    app.include_router(dungeons_v1.router, prefix="/api/v1")
    app.include_router(inventory_v1.router, prefix="/api/v1")

    return app


#: Module-level FastAPI app instance — entry-point для uvicorn.
app = create_app()
