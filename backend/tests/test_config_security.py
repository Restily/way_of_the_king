"""Тесты на жёсткие security-инварианты конфигурации.

Эти тесты гарантируют, что приложение НЕ может быть запущено в проде
с небезопасной конфигурацией.
"""

import pytest

from wotk.core.config import MIN_SECRET_LENGTH, Settings, _is_weak_secret


def _strong_secret(suffix: str = "") -> str:
    return ("Z" * MIN_SECRET_LENGTH) + suffix


class TestWeakSecretDetection:
    def test_empty_string_is_weak(self) -> None:
        assert _is_weak_secret("")

    def test_short_string_is_weak(self) -> None:
        assert _is_weak_secret("short")

    def test_change_me_marker_is_weak(self) -> None:
        assert _is_weak_secret("a" * 100 + "change_me")

    def test_example_marker_is_weak(self) -> None:
        assert _is_weak_secret("a" * 100 + "example_value")

    def test_strong_secret_passes(self) -> None:
        assert not _is_weak_secret(_strong_secret())


class TestProductionValidation:
    def _base_prod_env(self, **overrides: str) -> dict[str, str]:
        defaults = {
            "APP_ENV": "production",
            "APP_DEBUG": "false",
            "JWT_SECRET": _strong_secret("jwt"),
            "INTERNAL_HMAC_REALTIME_TO_API": _strong_secret("rt2api"),
            "INTERNAL_HMAC_API_TO_REALTIME": _strong_secret("api2rt"),
            "TELEGRAM_BOT_TOKEN": "1234567:bot_token_placeholder_value",
            "TON_NETWORK": "mainnet",
            "HOT_WALLET_MNEMONIC": " ".join(["abandon"] * 24),
            "WOTK_JETTON_MASTER_ADDRESS": "EQDDummyAddressForTest",
            "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/wotk",
        }
        return {**defaults, **overrides}

    def test_prod_with_valid_config_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for k, v in self._base_prod_env().items():
            monkeypatch.setenv(k, v)
        # Не должно бросить
        Settings()

    def test_prod_rejects_weak_jwt_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for k, v in self._base_prod_env(JWT_SECRET="dev_secret_change_me").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Settings()

    def test_prod_rejects_debug_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for k, v in self._base_prod_env(APP_DEBUG="true").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValueError, match="APP_DEBUG"):
            Settings()

    def test_prod_rejects_testnet_ton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for k, v in self._base_prod_env(TON_NETWORK="testnet").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValueError, match="TON_NETWORK"):
            Settings()

    def test_prod_rejects_same_hmac_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        same = _strong_secret("same")
        for k, v in self._base_prod_env(
            INTERNAL_HMAC_REALTIME_TO_API=same,
            INTERNAL_HMAC_API_TO_REALTIME=same,
        ).items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValueError, match="must be DIFFERENT"):
            Settings()

    def test_prod_rejects_missing_telegram_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for k, v in self._base_prod_env(TELEGRAM_BOT_TOKEN="").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            Settings()

    def test_dev_allows_weak_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """В dev validator не должен мешать локальной разработке."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("JWT_SECRET", "")
        # Не должно бросить
        Settings()
