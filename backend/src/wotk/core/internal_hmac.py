"""HMAC-SHA256 валидация для internal-эндпоинтов (Colyseus → FastAPI).

Используется в ``/api/v1/internal/*`` routes. Подпись считается над raw body
с использованием :attr:`Settings.internal_hmac_realtime_to_api` секрета —
отдельного от api→realtime (defense in depth).

Header: ``X-Internal-Sig: <hex>`` — 64-char hex для SHA-256 digest.
"""

from __future__ import annotations

import hashlib
import hmac

import structlog
from fastapi import HTTPException, Request, status

from wotk.core.config import get_settings

log = structlog.get_logger()


async def verify_internal_hmac(request: Request) -> None:
    """FastAPI dependency — поднимает 401 при невалидной подписи.

    Использование::

        @router.post("/internal/...", dependencies=[Depends(verify_internal_hmac)])
        async def handler(...): ...

    Constant-time сравнение через :func:`hmac.compare_digest`.

    :raises HTTPException: 401 если header отсутствует / hex невалиден /
        подпись не сошлась.
    """
    settings = get_settings()
    secret = settings.internal_hmac_realtime_to_api.get_secret_value()
    if not secret:
        # Жёсткий fail в dev/staging/prod если секрет не настроен — лучше
        # упасть громко, чем впустить unsigned request.
        log.error("internal_hmac_secret_not_configured")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal_hmac_secret_missing",
        )

    sig_header = request.headers.get("X-Internal-Sig")
    if not sig_header:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="missing_internal_signature"
        )

    body = await request.body()
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(sig_header, expected):
        log.warning(
            "internal_hmac_mismatch",
            path=request.url.path,
            received_prefix=sig_header[:8],
        )
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_signature"
        )


__all__ = ["verify_internal_hmac"]
