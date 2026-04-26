"""FastAPI entrypoint."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from wotk.core.config import get_settings
from wotk.core.limiter import limiter
from wotk.core.sentry_setup import init_sentry

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_sentry(settings)
    log.info("startup", env=settings.app_env)

    if settings.app_env != "development" and not settings.sentry_dsn:
        log.critical(
            "sentry_dsn_missing_in_non_dev",
            message="SENTRY_DSN is empty — errors will not be reported!",
        )

    yield
    log.info("shutdown")


def _rate_limit_handler(_request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "detail": str(exc.detail)},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    is_prod = settings.app_env == "production"

    app = FastAPI(
        title="Way Of The King API",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.app_debug,
        # В проде скрываем OpenAPI/Swagger — не помогаем атакующим
        # перечислить endpoints и схемы.
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
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        # Публичный health НЕ раскрывает версию — не помогаем
        # атакующим таргетить known CVEs. Внутренний health с полной
        # информацией будет под auth (отдельный эндпоинт).
        return {"status": "ok"}

    return app


app = create_app()
