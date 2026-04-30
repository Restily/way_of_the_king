"""Idempotency helper для POST-эндпоинтов.

Использование внутри хендлера::

    from wotk.api.idempotency import CachedHttpResponse, begin_idempotent

    @router.post("")
    async def create_hero(
        body: CreateHeroRequest,
        request: Request,
        profile: Profile = Depends(current_profile),
        session: AsyncSession = Depends(get_session),
        idem_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Response:
        ctx = await begin_idempotent(
            request=request, session=session,
            profile=profile, raw_key=idem_key,
        )
        if ctx.cached_response is not None:
            return JSONResponse(
                status_code=ctx.cached_response.status_code,
                content=ctx.cached_response.content,
            )

        ...создаём hero, формируем response_body...
        await ctx.store(
            session,
            response=CachedHttpResponse(status_code=201, content=response_body),
        )
        return JSONResponse(status_code=201, content=response_body)

Зачем не FastAPI dependency? Зависимости не могут "short-circuit" с
кастомным response shape (HTTPException всегда выдаёт ``{"detail": ...}``).
Cached response может быть произвольной формы.

См. DATABASE.md §11.2 — UUID key, BYTEA(32) hash, tiered TTL.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.models import IdempotencyKey, Profile

log = structlog.get_logger()


#: TTL для не-payment операций (equip, hero create). Покрывает retry-окно
#: клиента + flaky network, без раздувания таблицы.
NON_PAYMENT_TTL = timedelta(hours=2)

#: TTL для payment-critical операций (transaction, withdrawal). Защита от
#: двойной оплаты при долгом offline-окне.
PAYMENT_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class CachedHttpResponse:
    """Закэшированный ответ. Поля совпадают с ``JSONResponse`` kwargs."""

    status_code: int
    content: dict[str, Any] | None


@dataclass
class IdempotencyContext:
    """Результат :func:`begin_idempotent`.

    Caller должен:

    1. Проверить :attr:`cached_response`. Если не ``None`` — немедленно
       вернуть закэшированный ответ.
    2. После успешной работы хендлера вызвать :meth:`store` с тем же
       :class:`CachedHttpResponse`, что отправляется клиенту.

    Все остальные поля — internal (используются ``store()`` для INSERT).
    """

    cached_response: CachedHttpResponse | None
    _key: uuid.UUID | None
    _request_hash: bytes
    _endpoint: str
    _profile_id: int
    _is_payment_critical: bool

    async def store(
        self,
        session: AsyncSession,
        *,
        response: CachedHttpResponse,
    ) -> None:
        """Persist ответ после успешного хендлера. No-op если key не передан.

        ВНИМАНИЕ: ``IntegrityError`` от concurrent INSERT'а с тем же
        ``(key, profile_id)`` намеренно НЕ ловится — это unexpected condition
        (PK race), который должен прорываться 500'кой. Catching+rollback
        ломал бы основную работу хендлера: после ``await session.rollback()``
        исчезали бы все pending-INSERT'ы (например, только что созданный hero).
        Если 500 произойдёт, retry клиента найдёт committed-запись от
        конкурента и вернёт его response.

        :param session: Активная DB session (та же что у хендлера).
        :param response: Тот же объект что и для ответа клиенту — единый
            источник истины предотвращает рассинхронизацию cached vs sent.
        """
        if self._key is None:
            return

        ttl = PAYMENT_TTL if self._is_payment_critical else NON_PAYMENT_TTL
        record = IdempotencyKey(
            key=self._key,
            profile_id=self._profile_id,
            endpoint=self._endpoint,
            request_hash=self._request_hash,
            response_status=response.status_code,
            response_body=response.content,
            is_payment_critical=self._is_payment_critical,
            expires_at=datetime.now(UTC) + ttl,
        )
        session.add(record)
        await session.flush()


async def begin_idempotent(
    *,
    request: Request,
    session: AsyncSession,
    profile: Profile,
    raw_key: str | None,
    is_payment_critical: bool = False,
) -> IdempotencyContext:
    """Подготовить idempotency-контекст: hash тела + lookup существующей записи.

    Если ``raw_key is None`` — body НЕ читается и НЕ хэшируется (no-op
    путь — common case для not-yet-idempotent endpoints).

    :param request: Starlette ``Request``.
    :param session: Активная DB session.
    :param profile: Авторизованный профиль (для PK + ON DELETE CASCADE).
    :param raw_key: Сырое значение ``Idempotency-Key`` header.
    :param is_payment_critical: Если ``True`` — TTL 24h, иначе 2h.
    :returns: :class:`IdempotencyContext`. Если в БД нашёлся matching key с
        тем же hash — ``cached_response`` заполнен.
    :raises HTTPException: 400 при невалидном UUID, 422 при mismatch hash.
    """
    endpoint = request.url.path

    if raw_key is None:
        return IdempotencyContext(
            cached_response=None,
            _key=None,
            _request_hash=b"",
            _endpoint=endpoint,
            _profile_id=profile.id,
            _is_payment_critical=is_payment_critical,
        )

    try:
        key = uuid.UUID(raw_key)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="invalid_idempotency_key_format",
        ) from e

    body_bytes = await request.body()
    request_hash = hashlib.sha256(body_bytes).digest()

    cached = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.key == key,
            IdempotencyKey.profile_id == profile.id,
        )
    )

    common_kwargs: dict[str, Any] = {
        "_key": key,
        "_request_hash": request_hash,
        "_endpoint": endpoint,
        "_profile_id": profile.id,
        "_is_payment_critical": is_payment_critical,
    }

    if cached is None:
        return IdempotencyContext(cached_response=None, **common_kwargs)

    if cached.request_hash != request_hash:
        log.info(
            "idem_body_mismatch",
            key=str(key),
            profile_id=profile.id,
            endpoint=endpoint,
        )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="idempotency_key_body_mismatch",
        )

    return IdempotencyContext(
        cached_response=CachedHttpResponse(
            status_code=cached.response_status,
            content=cached.response_body,
        ),
        **common_kwargs,
    )


__all__ = [
    "CachedHttpResponse",
    "IdempotencyContext",
    "NON_PAYMENT_TTL",
    "PAYMENT_TTL",
    "begin_idempotent",
]
