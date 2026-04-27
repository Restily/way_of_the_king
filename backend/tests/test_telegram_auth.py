"""Тесты HMAC-валидации Telegram initData."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import quote

import pytest

from wotk.core.telegram_auth import (
    InvalidSignature,
    MalformedInitData,
    StaleInitData,
    verify_init_data,
)

BOT_TOKEN = "test:bot_token_for_unit_tests_1234567890"


def _build_init_data(
    bot_token: str = BOT_TOKEN,
    *,
    user: dict | None = None,
    auth_date: int | None = None,
    extra: dict | None = None,
    bad_hash: bool = False,
) -> str:
    if user is None:
        user = {
            "id": 12345,
            "first_name": "Sir",
            "username": "lancelot",
            "language_code": "en",
        }
    if auth_date is None:
        auth_date = int(time.time())

    params: dict[str, str] = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date),
        "query_id": "AAH123",
    }
    if extra:
        params.update(extra)

    data_check_string = "\n".join(
        f"{k}={params[k]}" for k in sorted(params.keys())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    h = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if bad_hash:
        h = "deadbeef" * 8

    parts = [f"{quote(k)}={quote(params[k])}" for k in params]
    parts.append(f"hash={h}")
    return "&".join(parts)


def test_verify_valid_init_data() -> None:
    init_data = _build_init_data()
    result = verify_init_data(init_data, BOT_TOKEN)
    assert result.user.id == 12345
    assert result.user.username == "lancelot"
    assert result.user.language_code == "en"


def test_verify_rejects_bad_hash() -> None:
    init_data = _build_init_data(bad_hash=True)
    with pytest.raises(InvalidSignature):
        verify_init_data(init_data, BOT_TOKEN)


def test_verify_rejects_stale_auth_date() -> None:
    old = int(time.time()) - 100_000  # 27+ часов назад
    init_data = _build_init_data(auth_date=old)
    with pytest.raises(StaleInitData):
        verify_init_data(init_data, BOT_TOKEN, ttl_seconds=86400)


def test_verify_rejects_wrong_bot_token() -> None:
    init_data = _build_init_data(bot_token=BOT_TOKEN)
    with pytest.raises(InvalidSignature):
        verify_init_data(init_data, "wrong:token_value")


def test_verify_rejects_missing_hash() -> None:
    with pytest.raises(MalformedInitData):
        verify_init_data("user=%7B%22id%22%3A1%7D&auth_date=1", BOT_TOKEN)


def test_verify_rejects_empty() -> None:
    with pytest.raises(MalformedInitData):
        verify_init_data("", BOT_TOKEN)


def test_verify_rejects_missing_user() -> None:
    init_data = _build_init_data(user={})  # no 'id'
    with pytest.raises(MalformedInitData):
        verify_init_data(init_data, BOT_TOKEN)


def test_verify_with_premium_flag() -> None:
    user = {"id": 99, "is_premium": True, "first_name": "Premium"}
    init_data = _build_init_data(user=user)
    result = verify_init_data(init_data, BOT_TOKEN)
    assert result.user.is_premium is True
