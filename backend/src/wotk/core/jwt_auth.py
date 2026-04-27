"""JWT issue/verify для access и refresh токенов."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import jwt

from wotk.core.config import get_settings

TokenType = Literal["access", "refresh"]


class JwtError(Exception):
    """Базовый класс JWT ошибок."""


class JwtExpired(JwtError):
    pass


class JwtInvalid(JwtError):
    pass


@dataclass(frozen=True, slots=True)
class Claims:
    profile_id: int
    type: TokenType
    jti: str
    iat: int
    exp: int


def _now() -> int:
    return int(time.time())


def issue_access_token(profile_id: int, *, now: int | None = None) -> str:
    settings = get_settings()
    iat = now if now is not None else _now()
    payload: dict[str, Any] = {
        "sub": str(profile_id),
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": iat,
        "exp": iat + settings.jwt_access_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def issue_refresh_token(profile_id: int, *, now: int | None = None) -> str:
    settings = get_settings()
    iat = now if now is not None else _now()
    payload: dict[str, Any] = {
        "sub": str(profile_id),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": iat,
        "exp": iat + settings.jwt_refresh_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(
    token: str, *, expected_type: TokenType | None = None
) -> Claims:
    """Декодирует и валидирует JWT.

    Raises:
        JwtExpired: токен истёк
        JwtInvalid: подпись неверная, тип неверный, формат сломан
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
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
