"""Geo-блокировка по IP-стране."""

from __future__ import annotations

from fastapi import Request

from wotk.core.config import get_settings


def get_country_from_request(request: Request) -> str | None:
    """Извлечь ISO-код страны из запроса.

    Источники в порядке приоритета:
    1. Cloudflare header `cf-ipcountry`
    2. Generic `x-country-code` (proxy чейн)
    3. None (пока не интегрирован MaxMind GeoLite2)

    MaxMind GeoLite2 интеграция — Phase 1 W2+, требует mmdb-файл.
    """
    cf = request.headers.get("cf-ipcountry")
    if cf and cf != "XX":
        return cf.upper()
    fallback = request.headers.get("x-country-code")
    if fallback:
        return fallback.upper()
    return None


def is_country_blocked(country: str | None) -> bool:
    if country is None:
        return False  # неизвестная страна не блокируется (fail-open)
    settings = get_settings()
    blocked = {c.strip().upper() for c in settings.geo_block_countries.split(",")}
    return country.upper() in blocked
