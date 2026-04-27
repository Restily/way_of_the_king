"""Тесты JWT issue/verify."""

from __future__ import annotations

import time

import jwt
import pytest

from wotk.core.config import get_settings
from wotk.core.jwt_auth import (
    JwtExpired,
    JwtInvalid,
    issue_access_token,
    issue_refresh_token,
    verify_token,
)


def test_access_token_roundtrip() -> None:
    token = issue_access_token(profile_id=42)
    claims = verify_token(token, expected_type="access")
    assert claims.profile_id == 42
    assert claims.type == "access"


def test_refresh_token_roundtrip() -> None:
    token = issue_refresh_token(profile_id=99)
    claims = verify_token(token, expected_type="refresh")
    assert claims.profile_id == 99
    assert claims.type == "refresh"


def test_access_token_rejected_when_refresh_expected() -> None:
    token = issue_access_token(profile_id=1)
    with pytest.raises(JwtInvalid):
        verify_token(token, expected_type="refresh")


def test_refresh_token_rejected_when_access_expected() -> None:
    token = issue_refresh_token(profile_id=1)
    with pytest.raises(JwtInvalid):
        verify_token(token, expected_type="access")


def test_expired_token_raises() -> None:
    long_ago = int(time.time()) - 10_000
    # Issue с iat в далёком прошлом так чтобы exp тоже был в прошлом
    token = issue_access_token(profile_id=1, now=long_ago)
    with pytest.raises(JwtExpired):
        verify_token(token, expected_type="access")


def test_tampered_token_rejected() -> None:
    token = issue_access_token(profile_id=1)
    tampered = token[:-4] + "XXXX"
    with pytest.raises(JwtInvalid):
        verify_token(tampered)


def test_token_with_wrong_secret_rejected() -> None:
    settings = get_settings()
    payload = {
        "sub": "1",
        "type": "access",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": "abc",
    }
    forged = jwt.encode(payload, "wrong_secret", algorithm=settings.jwt_algorithm)
    with pytest.raises(JwtInvalid):
        verify_token(forged)


def test_token_alg_none_rejected() -> None:
    """Известная JWT-уязвимость: alg=none → должен быть отклонён."""
    payload = {
        "sub": "1",
        "type": "access",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": "x",
    }
    forged = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(JwtInvalid):
        verify_token(forged)


def test_token_missing_required_claims_rejected() -> None:
    """sub/type/exp/iat — required."""
    settings = get_settings()
    payload = {"sub": "1"}  # missing type/exp/iat
    forged = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(JwtInvalid):
        verify_token(forged)
