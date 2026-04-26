"""Конфигурация приложения через Pydantic Settings.

В staging/production environment Pydantic-валидатор отказывается стартовать
если найдены небезопасные значения (слабые секреты, debug=true, и т.д.).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Маркеры небезопасных дефолтов в секретах. Если строка содержит любой из них,
# в staging/production приложение откажется стартовать.
WEAK_SECRET_MARKERS = (
    "change_me",
    "dev_",
    "_dev",
    "example",
    "placeholder",
    "replace_me",
)
MIN_SECRET_LENGTH = 32


def _is_weak_secret(value: str) -> bool:
    if not value or len(value) < MIN_SECRET_LENGTH:
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in WEAK_SECRET_MARKERS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Application ===
    app_env: Literal["development", "staging", "production"] = "development"
    # Безопасный дефолт: debug=False. Включается ТОЛЬКО явно через env.
    app_debug: bool = False
    log_level: str = "INFO"

    # === Database ===
    database_url: str = Field(
        default="postgresql+asyncpg://wotk:wotk_dev@localhost:5432/wotk"
    )

    # === Redis ===
    redis_url: str = Field(default="redis://localhost:6379/0")

    # === CORS ===
    # Жёсткий allowlist origins для Mini App. Никаких "*".
    cors_origins: list[str] = Field(
        default=[
            "https://t.me",
            "https://web.telegram.org",
            "https://k.web.telegram.org",
            "https://z.web.telegram.org",
            "https://a.web.telegram.org",
        ]
    )
    # Доп. origins для локальной разработки. Применяются только в dev.
    cors_dev_origins: list[str] = Field(
        default=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # === Telegram ===
    telegram_bot_token: str = ""
    telegram_bot_username: str = "WayOfTheKingDevBot"
    telegram_initdata_ttl_seconds: int = 86400

    # === JWT ===
    # ОБЯЗАТЕЛЬНО задать в env для staging/production. ≥ 32 байта.
    jwt_secret: str = ""
    # Literal — защита от прокидывания "none" или асимметричных алгоритмов
    # (известная JWT уязвимость).
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_ttl_seconds: int = 3600
    jwt_refresh_ttl_seconds: int = 2_592_000
    jwt_ws_token_ttl_seconds: int = 30

    # === Internal HMAC ===
    # Разные секреты для разных направлений (defense in depth).
    # Если realtime скомпрометирован — атакующий не может выдать FastAPI→realtime
    # admin-команду; и наоборот.
    internal_hmac_realtime_to_api: str = ""
    internal_hmac_api_to_realtime: str = ""

    # === TON ===
    ton_network: Literal["testnet", "mainnet"] = "testnet"
    ton_rpc_url: str = "https://testnet.toncenter.com/api/v2/jsonRPC"
    ton_rpc_api_key: str = ""
    wotk_jetton_master_address: str = ""
    # ВНИМАНИЕ: для production использовать Docker secrets / systemd LoadCredential
    # вместо обычных env vars (см. docs/SECURITY.md §3).
    hot_wallet_mnemonic: str = ""

    # === Sentry ===
    sentry_dsn: str = ""

    # === Geo blocking ===
    geo_block_countries: str = "US,GB,IR,KP,SY,CU"

    # === Rate limiting (per minute) ===
    rate_limit_per_user_per_min: int = 600
    rate_limit_per_ip_per_min: int = 1200
    rate_limit_login_per_ip_per_min: int = 20

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        """Жёсткие требования к secrets и опасным настройкам для staging/production.

        Падение здесь — by design. Лучше упасть на старте чем работать
        с дырявой конфигурацией.
        """
        if self.app_env not in ("staging", "production"):
            return self

        problems: list[str] = []

        for field_name, value in [
            ("JWT_SECRET", self.jwt_secret),
            ("INTERNAL_HMAC_REALTIME_TO_API", self.internal_hmac_realtime_to_api),
            ("INTERNAL_HMAC_API_TO_REALTIME", self.internal_hmac_api_to_realtime),
        ]:
            if _is_weak_secret(value):
                problems.append(
                    f"{field_name} must be a secure secret of at least {MIN_SECRET_LENGTH} chars "
                    f"and must not contain weak markers in {self.app_env} environment"
                )

        if not self.telegram_bot_token:
            problems.append("TELEGRAM_BOT_TOKEN is required in non-development environments")

        if self.app_debug:
            problems.append("APP_DEBUG must be false in staging/production")

        if self.internal_hmac_realtime_to_api == self.internal_hmac_api_to_realtime:
            problems.append(
                "INTERNAL_HMAC_REALTIME_TO_API and INTERNAL_HMAC_API_TO_REALTIME "
                "must be DIFFERENT secrets"
            )

        if self.app_env == "production":
            if self.ton_network != "mainnet":
                problems.append("TON_NETWORK must be 'mainnet' in production")
            if not self.hot_wallet_mnemonic:
                problems.append("HOT_WALLET_MNEMONIC is required in production")
            if not self.wotk_jetton_master_address:
                problems.append("WOTK_JETTON_MASTER_ADDRESS is required in production")

        if problems:
            raise ValueError(
                "Insecure configuration detected:\n  - " + "\n  - ".join(problems)
            )

        return self

    @property
    def effective_cors_origins(self) -> list[str]:
        """Финальный список CORS origins в зависимости от окружения."""
        if self.app_env == "development":
            return [*self.cors_origins, *self.cors_dev_origins]
        return self.cors_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
