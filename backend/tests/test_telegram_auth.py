"""Тесты :class:`TelegramInitDataValidator` HMAC-валидации."""

from __future__ import annotations

import time

import pytest

from wotk.core.telegram_auth import (
    InvalidSignature,
    MalformedInitData,
    StaleInitData,
    TelegramInitDataValidator,
)

from ._helpers import build_init_data

BOT_TOKEN = "test:bot_token_for_unit_tests_1234567890"


@pytest.fixture
def validator() -> TelegramInitDataValidator:
    return TelegramInitDataValidator(bot_token=BOT_TOKEN, ttl_seconds=86400)


def test_init_rejects_empty_bot_token() -> None:
    with pytest.raises(ValueError):
        TelegramInitDataValidator(bot_token="")


def test_verify_valid_init_data(
    validator: TelegramInitDataValidator,
) -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN)
    result = validator.verify(init_data)
    assert result.user.id == 12345
    assert result.user.username == "user12345"
    assert result.user.language_code == "en"


def test_verify_rejects_bad_hash(
    validator: TelegramInitDataValidator,
) -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN, bad_hash=True)
    with pytest.raises(InvalidSignature):
        validator.verify(init_data)


def test_verify_rejects_stale_auth_date(
    validator: TelegramInitDataValidator,
) -> None:
    old = int(time.time()) - 100_000  # 27+ часов назад
    init_data = build_init_data(bot_token=BOT_TOKEN, auth_date=old)
    with pytest.raises(StaleInitData):
        validator.verify(init_data)


def test_verify_rejects_wrong_bot_token() -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN)
    other_validator = TelegramInitDataValidator(bot_token="wrong:token_value")
    with pytest.raises(InvalidSignature):
        other_validator.verify(init_data)


def test_verify_rejects_missing_hash(
    validator: TelegramInitDataValidator,
) -> None:
    with pytest.raises(MalformedInitData):
        validator.verify("user=%7B%22id%22%3A1%7D&auth_date=1")


def test_verify_rejects_empty(
    validator: TelegramInitDataValidator,
) -> None:
    with pytest.raises(MalformedInitData):
        validator.verify("")


def test_verify_rejects_missing_user_id(
    validator: TelegramInitDataValidator,
) -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN)
    init_data = init_data.replace("%22id%22%3A12345", "%22id%22%3Anull")
    with pytest.raises(MalformedInitData):
        validator.verify(init_data)


def test_verify_with_premium_flag(
    validator: TelegramInitDataValidator,
) -> None:
    init_data = build_init_data(
        bot_token=BOT_TOKEN, telegram_id=99, user_extra={"is_premium": True}
    )
    result = validator.verify(init_data)
    assert result.user.is_premium is True
