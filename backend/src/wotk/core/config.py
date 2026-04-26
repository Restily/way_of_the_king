"""Конфигурация приложения через Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://wotk:wotk_dev@localhost:5432/wotk"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Telegram
    telegram_bot_token: str = ""
    telegram_bot_username: str = "WayOfTheKingDevBot"
    telegram_initdata_ttl_seconds: int = 86400

    # JWT
    jwt_secret: str = "dev_secret_change_me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 3600
    jwt_refresh_ttl_seconds: int = 2_592_000
    jwt_ws_token_ttl_seconds: int = 30

    # Internal HMAC
    internal_hmac_secret: str = "dev_internal_secret_change_me"

    # TON
    ton_network: Literal["testnet", "mainnet"] = "testnet"
    ton_rpc_url: str = "https://testnet.toncenter.com/api/v2/jsonRPC"
    ton_rpc_api_key: str = ""
    wotk_jetton_master_address: str = ""
    hot_wallet_mnemonic: str = ""

    # Sentry
    sentry_dsn: str = ""

    # Geo
    geo_block_countries: str = "US,GB,IR,KP,SY,CU"


@lru_cache
def get_settings() -> Settings:
    return Settings()
