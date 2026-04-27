"""Тесты HMAC-валидации Telegram initData."""

from __future__ import annotations

import time

import pytest

from wotk.core.telegram_auth import (
    InvalidSignature,
    MalformedInitData,
    StaleInitData,
    verify_init_data,
)

from ._helpers import build_init_data

BOT_TOKEN = "test:bot_token_for_unit_tests_1234567890"


def test_verify_valid_init_data() -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN)
    result = verify_init_data(init_data, BOT_TOKEN)
    assert result.user.id == 12345
    assert result.user.username == "user12345"
    assert result.user.language_code == "en"


def test_verify_rejects_bad_hash() -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN, bad_hash=True)
    with pytest.raises(InvalidSignature):
        verify_init_data(init_data, BOT_TOKEN)


def test_verify_rejects_stale_auth_date() -> None:
    old = int(time.time()) - 100_000  # 27+ часов назад
    init_data = build_init_data(bot_token=BOT_TOKEN, auth_date=old)
    with pytest.raises(StaleInitData):
        verify_init_data(init_data, BOT_TOKEN, ttl_seconds=86400)


def test_verify_rejects_wrong_bot_token() -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN)
    with pytest.raises(InvalidSignature):
        verify_init_data(init_data, "wrong:token_value")


def test_verify_rejects_missing_hash() -> None:
    with pytest.raises(MalformedInitData):
        verify_init_data("user=%7B%22id%22%3A1%7D&auth_date=1", BOT_TOKEN)


def test_verify_rejects_empty() -> None:
    with pytest.raises(MalformedInitData):
        verify_init_data("", BOT_TOKEN)


def test_verify_rejects_missing_user_id() -> None:
    init_data = build_init_data(
        bot_token=BOT_TOKEN, user_extra={"id": None}
    )
    # Перетираем id на None — MalformedInitData
    init_data = init_data.replace(
        "%22id%22%3A12345", "%22id%22%3Anull"
    )
    with pytest.raises((MalformedInitData, ValueError)):
        verify_init_data(init_data, BOT_TOKEN)


def test_verify_with_premium_flag() -> None:
    init_data = build_init_data(
        bot_token=BOT_TOKEN, telegram_id=99, user_extra={"is_premium": True}
    )
    result = verify_init_data(init_data, BOT_TOKEN)
    assert result.user.is_premium is True
