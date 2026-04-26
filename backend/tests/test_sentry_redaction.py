"""Тесты на редакцию secrets перед отправкой в Sentry."""

from wotk.core.sentry_setup import REDACTED, _redact


def test_redacts_known_sensitive_keys() -> None:
    event = {
        "extra": {
            "jwt_secret": "abc123",
            "telegram_bot_token": "1234:secret",
            "user_id": 42,
        }
    }
    redacted = _redact(event)
    assert redacted["extra"]["jwt_secret"] == REDACTED
    assert redacted["extra"]["telegram_bot_token"] == REDACTED
    assert redacted["extra"]["user_id"] == 42


def test_redacts_mnemonic_strings_anywhere() -> None:
    mnemonic = " ".join(["abandon"] * 24)
    event = {
        "extra": {
            "harmless_field": mnemonic,
        }
    }
    redacted = _redact(event)
    assert redacted["extra"]["harmless_field"] == REDACTED


def test_redacts_jwt_tokens_anywhere() -> None:
    fake_jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjMifQ"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    event = {"extra": {"value": fake_jwt}}
    redacted = _redact(event)
    assert redacted["extra"]["value"] == REDACTED


def test_redacts_authorization_header() -> None:
    event = {"request": {"headers": {"authorization": "Bearer xxx", "host": "ok"}}}
    redacted = _redact(event)
    assert redacted["request"]["headers"]["authorization"] == REDACTED
    assert redacted["request"]["headers"]["host"] == "ok"


def test_handles_nested_structures() -> None:
    event = {
        "data": [
            {"password": "x"},
            {"username": "y"},
            [{"api_key": "z"}],
        ]
    }
    redacted = _redact(event)
    assert redacted["data"][0]["password"] == REDACTED
    assert redacted["data"][1]["username"] == "y"
    assert redacted["data"][2][0]["api_key"] == REDACTED


def test_does_not_crash_on_circular_or_deep() -> None:
    # Deep nested
    obj: dict = {"k": "v"}
    cur = obj
    for _ in range(100):
        cur["nested"] = {"k": "v"}
        cur = cur["nested"]
    # Не должно крашнуть
    _redact(obj)


def test_normal_strings_not_redacted() -> None:
    event = {"extra": {"hp": 100, "name": "Sir Lancelot", "level": 42}}
    redacted = _redact(event)
    assert redacted == event
