"""HTTP middleware: request_id (structlog + Sentry tag) + request duration log."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import sentry_sdk
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: Имя header'а, в котором приходит/возвращается request_id.
REQUEST_ID_HEADER = "X-Request-ID"

#: Только эти ключи bind/unbind'ятся в structlog context.
#: Не затираем context от outer middleware (Sentry, OpenTelemetry).
_BOUND_KEYS = ("request_id", "method", "path")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Присваивает каждому request уникальный ``request_id`` и биндит в structlog + Sentry.

    Если клиент прислал свой ``X-Request-ID`` — используем его (для
    cross-service tracing). Иначе генерируем UUID4 hex (32 символа без дефисов).

    Sentry-сторона: ``request_id`` ставится тэгом на изолированный scope
    каждого запроса — error в Sentry содержит точный ID для корреляции с логами.
    После обработки возвращается в response header.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Обработать request, биндя ``request_id`` в structlog + Sentry."""
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        log = structlog.get_logger()
        started_at = time.perf_counter()
        status_code = 500  # default — overwritten при success
        with sentry_sdk.isolation_scope() as scope:
            scope.set_tag("request_id", request_id)
            try:
                response = await call_next(request)
                status_code = response.status_code
                return self._with_id(response, request_id)
            except Exception:
                log.exception(
                    "request_failed",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    status_code=status_code,
                )
                raise
            finally:
                # health-эндпоинты дёргаются Caddy/Cloudflare часто —
                # их успешные log-events заглушаем, иначе прод-лог захлебнётся.
                if not request.url.path.startswith("/health"):
                    log.info(
                        "request_completed",
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                        status_code=status_code,
                    )
                structlog.contextvars.unbind_contextvars(*_BOUND_KEYS)

    @staticmethod
    def _with_id(response: Response, request_id: str) -> Response:
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
