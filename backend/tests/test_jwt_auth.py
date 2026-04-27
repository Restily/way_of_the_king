"""Тесты :class:`JwtService` issue/verify."""

from __future__ import annotations

import time

import jwt
import pytest

from wotk.core.jwt_auth import (
    JwtExpired,
    JwtInvalid,
    JwtService,
    get_jwt_service,
)


@pytest.fixture
def jwt_service() -> JwtService:
    """Свежий :class:`JwtService` с детерминированной конфигурацией."""
    return JwtService(
        secret="test-secret-at-least-thirty-two-bytes-long",
        algorithm="HS256",
        access_ttl_seconds=3600,
        refresh_ttl_seconds=86400,
    )


def test_access_token_roundtrip(jwt_service: JwtService) -> None:
    token = jwt_service.issue_access(profile_id=42)
    claims = jwt_service.verify(token, expected_type="access")
    assert claims.profile_id == 42
    assert claims.type == "access"


def test_refresh_token_roundtrip(jwt_service: JwtService) -> None:
    token = jwt_service.issue_refresh(profile_id=99)
    claims = jwt_service.verify(token, expected_type="refresh")
    assert claims.profile_id == 99
    assert claims.type == "refresh"


def test_access_token_rejected_when_refresh_expected(
    jwt_service: JwtService,
) -> None:
    token = jwt_service.issue_access(profile_id=1)
    with pytest.raises(JwtInvalid):
        jwt_service.verify(token, expected_type="refresh")


def test_refresh_token_rejected_when_access_expected(
    jwt_service: JwtService,
) -> None:
    token = jwt_service.issue_refresh(profile_id=1)
    with pytest.raises(JwtInvalid):
        jwt_service.verify(token, expected_type="access")


def test_expired_token_raises(jwt_service: JwtService) -> None:
    long_ago = int(time.time()) - 10_000
    token = jwt_service.issue_access(profile_id=1, now=long_ago)
    with pytest.raises(JwtExpired):
        jwt_service.verify(token, expected_type="access")


def test_tampered_token_rejected(jwt_service: JwtService) -> None:
    token = jwt_service.issue_access(profile_id=1)
    tampered = token[:-4] + "XXXX"
    with pytest.raises(JwtInvalid):
        jwt_service.verify(tampered)


def test_token_with_wrong_secret_rejected(jwt_service: JwtService) -> None:
    payload = {
        "sub": "1",
        "type": "access",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": "abc",
    }
    forged = jwt.encode(payload, "wrong_secret", algorithm="HS256")
    with pytest.raises(JwtInvalid):
        jwt_service.verify(forged)


def test_token_alg_none_rejected(jwt_service: JwtService) -> None:
    """Известная JWT-уязвимость: ``alg=none`` должен быть отклонён."""
    payload = {
        "sub": "1",
        "type": "access",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": "x",
    }
    forged = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(JwtInvalid):
        jwt_service.verify(forged)


def test_token_missing_required_claims_rejected(
    jwt_service: JwtService,
) -> None:
    """``sub``/``type``/``exp``/``iat`` — required."""
    payload = {"sub": "1"}
    forged = jwt.encode(
        payload,
        "test-secret-at-least-thirty-two-bytes-long",
        algorithm="HS256",
    )
    with pytest.raises(JwtInvalid):
        jwt_service.verify(forged)


def test_get_jwt_service_returns_singleton() -> None:
    """:func:`get_jwt_service` кэшируется через ``lru_cache``."""
    a = get_jwt_service()
    b = get_jwt_service()
    assert a is b
