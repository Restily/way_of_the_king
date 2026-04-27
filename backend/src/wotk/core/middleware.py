"""HTTP middleware: request_id."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# Только эти ключи биндятся/анбиндятся, чтобы не затирать context от
# outer middleware (Sentry, OpenTelemetry, etc.)
_BOUND_KEYS = ("request_id", "method", "path")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Присваивает каждому request уникальный request_id и биндит в structlog.

    Если клиент прислал свой `X-Request-ID` — используем его. Возвращается
    в response header для tracing.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars(*_BOUND_KEYS)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
