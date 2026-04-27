"""JWT issue/verify через :class:`JwtService`.

Сервис инжектируется в FastAPI-эндпоинты через
``Depends(get_jwt_service)``. В тестах можно либо переопределить
зависимость через ``app.dependency_overrides``, либо инстанцировать
``JwtService`` напрямую с тестовым секретом.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import jwt

from wotk.core.config import get_settings

#: Тип JWT-токена. Access — короткоживущий (~1ч), refresh — длинный (~30 дней).
TokenType = Literal["access", "refresh"]


# ============================================================================
# Exceptions
# ============================================================================


class JwtError(Exception):
    """Базовый класс JWT-ошибок."""


class JwtExpired(JwtError):
    """Токен истёк (``exp`` < now)."""


class JwtInvalid(JwtError):
    """Подпись невалидна, тип неверный, формат сломан, или missing claim."""


# ============================================================================
# Claims dataclass
# ============================================================================


@dataclass(frozen=True, slots=True)
class Claims:
    """Распарсенный payload JWT.

    :ivar profile_id: ID профиля (``sub`` после ``int()``).
    :ivar type: ``"access"`` или ``"refresh"``.
    :ivar jti: Уникальный идентификатор токена (для будущей revocation).
    :ivar iat: Unix-timestamp выдачи.
    :ivar exp: Unix-timestamp истечения.
    """

    profile_id: int
    type: TokenType
    jti: str
    iat: int
    exp: int


# ============================================================================
# JwtService
# ============================================================================


class JwtService:
    """Stateless сервис issue/verify JWT-токенов.

    Хранит конфигурацию (secret, algorithm, TTLs) в инстансе. Один
    инстанс на процесс — синглтон через :func:`get_jwt_service`.

    Можно создать руками с тестовым секретом::

        svc = JwtService(
            secret="test_secret_at_least_32_chars_long",
            algorithm="HS256",
            access_ttl_seconds=3600,
            refresh_ttl_seconds=86400,
        )
        token = svc.issue_access(profile_id=42)

    :ivar _secret: HMAC секрет для подписи.
    :ivar _algorithm: Алгоритм (``HS256`` / ``HS384`` / ``HS512``).
    :ivar _access_ttl: TTL access-токена в секундах.
    :ivar _refresh_ttl: TTL refresh-токена в секундах.
    """

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        """Создать сервис с заданной конфигурацией.

        :param secret: HMAC секрет (≥ 32 байта в проде).
        :param algorithm: ``HS256`` / ``HS384`` / ``HS512``.
            Алгоритм валидируется на уровне Pydantic Settings —
            здесь принимается уже проверенное значение.
        :param access_ttl_seconds: TTL access-токена.
        :param refresh_ttl_seconds: TTL refresh-токена.
        """
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    @staticmethod
    def _now() -> int:
        """Текущий Unix-timestamp (выделено в метод для удобства мокинга)."""
        return int(time.time())

    def _ttl_for(self, token_type: TokenType) -> int:
        """Вернуть TTL для указанного типа токена.

        :param token_type: ``"access"`` или ``"refresh"``.
        :returns: TTL в секундах.
        """
        return self._access_ttl if token_type == "access" else self._refresh_ttl

    def issue(
        self,
        profile_id: int,
        token_type: TokenType,
        *,
        now: int | None = None,
    ) -> str:
        """Выпустить токен указанного типа.

        :param profile_id: ID профиля (попадёт в ``sub`` как строка).
        :param token_type: ``"access"`` или ``"refresh"``.
        :param now: Override Unix-timestamp ``iat`` (для тестов).
            ``None`` → :meth:`_now`.
        :returns: Подписанная строка JWT.
        """
        iat = now if now is not None else self._now()
        payload: dict[str, Any] = {
            "sub": str(profile_id),
            "type": token_type,
            "jti": uuid.uuid4().hex,
            "iat": iat,
            "exp": iat + self._ttl_for(token_type),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def issue_access(self, profile_id: int, *, now: int | None = None) -> str:
        """Удобный wrapper для access-токена.

        :param profile_id: ID профиля.
        :param now: Override timestamp (для тестов).
        :returns: Подписанная строка access-JWT.
        """
        return self.issue(profile_id, "access", now=now)

    def issue_refresh(self, profile_id: int, *, now: int | None = None) -> str:
        """Удобный wrapper для refresh-токена.

        :param profile_id: ID профиля.
        :param now: Override timestamp (для тестов).
        :returns: Подписанная строка refresh-JWT.
        """
        return self.issue(profile_id, "refresh", now=now)

    def verify(
        self, token: str, *, expected_type: TokenType | None = None
    ) -> Claims:
        """Декодировать и валидировать JWT.

        Проверяет: подпись, ``exp``/``iat``, наличие required claims,
        соответствие типа (если указан).

        :param token: Строка JWT.
        :param expected_type: Если не ``None`` — требуемый тип токена.
            Используется чтобы access-токен не попал в refresh-эндпоинт
            и наоборот.
        :returns: Распарсенный :class:`Claims`.
        :raises JwtExpired: Токен истёк.
        :raises JwtInvalid: Подпись невалидна, missing claim, неверный
            тип, или ``sub`` не int.
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "type", "exp", "iat"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise JwtExpired("token expired") from e
        except jwt.InvalidTokenError as e:
            raise JwtInvalid(f"invalid token: {e}") from e

        token_type = payload.get("type")
        if expected_type is not None and token_type != expected_type:
            raise JwtInvalid(
                f"expected token type '{expected_type}', got '{token_type}'"
            )
        if token_type not in ("access", "refresh"):
            raise JwtInvalid(f"unknown token type: {token_type}")

        try:
            profile_id = int(payload["sub"])
        except (TypeError, ValueError) as e:
            raise JwtInvalid("sub is not int") from e

        return Claims(
            profile_id=profile_id,
            type=token_type,
            jti=payload.get("jti", ""),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
        )


# ============================================================================
# DI factory
# ============================================================================


@lru_cache(maxsize=1)
def get_jwt_service() -> JwtService:
    """Возвращает синглтон-инстанс :class:`JwtService` для FastAPI Depends.

    Кэшируется через ``lru_cache`` — конфигурация фиксируется на старте
    процесса, не меняется в runtime. Тесты могут переопределить через
    ``app.dependency_overrides[get_jwt_service] = lambda: JwtService(...)``.

    :returns: Готовый к использованию :class:`JwtService`.
    """
    settings = get_settings()
    return JwtService(
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
        refresh_ttl_seconds=settings.jwt_refresh_ttl_seconds,
    )
