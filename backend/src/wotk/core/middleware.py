"""HTTP middleware: request_id."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

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
    """Присваивает каждому request уникальный ``request_id`` и биндит в structlog.

    Если клиент прислал свой ``X-Request-ID`` — используем его (для
    cross-service tracing). Иначе генерируем UUID4 hex (32 символа без дефисов).

    После обработки возвращается в response header (для отладки на клиенте).

    Устанавливается в FastAPI app::

        app.add_middleware(RequestIdMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Обработать request, биндя ``request_id`` в structlog context.

        :param request: Starlette Request.
        :param call_next: Следующий middleware/handler в chain.
        :returns: Response с проставленным ``X-Request-ID``.
        """
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
