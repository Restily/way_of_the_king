"""Geo-блокировка по IP-стране.

В MVP используется только Cloudflare-header ``cf-ipcountry``. В Phase 1+
интегрируется MaxMind GeoLite2 для случаев когда CF не проксирует
(прямые соединения, dev).
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from wotk.core.config import get_settings


def get_country_from_request(request: Request) -> str | None:
    """Извлечь ISO-код страны из заголовков запроса.

    Источники в порядке приоритета:

    1. Cloudflare ``cf-ipcountry`` — основной источник.
       Значение ``XX`` (Tor / неизвестно) трактуется как None.
    2. Generic ``x-country-code`` — для прокси-цепочек.
    3. None — fail-open (geo-block не сработает).

    MaxMind GeoLite2 интеграция запланирована в W2+ (требует ``mmdb``-файл
    и обновление periodically).

    :param request: Starlette Request.
    :returns: ISO-код страны uppercase, либо None если не определилась.
    """
    cf = request.headers.get("cf-ipcountry")
    if cf and cf != "XX":
        return cf.upper()
    fallback = request.headers.get("x-country-code")
    if fallback:
        return fallback.upper()
    return None


@lru_cache(maxsize=4)
def _parse_blocked_set(geo_block_str: str) -> frozenset[str]:
    """Парсит comma-separated список стран в frozenset.

    Кэшируется через ``lru_cache`` чтобы не сплитить строку
    на каждый вызов :func:`is_country_blocked` (login hot path).

    :param geo_block_str: Строка вида ``"US,GB,IR,KP"``.
    :returns: Замороженный set заглавных ISO-кодов.
    """
    return frozenset(c.strip().upper() for c in geo_block_str.split(",") if c.strip())


def is_country_blocked(country: str | None) -> bool:
    """Проверяет, заблокирована ли страна.

    Fail-open: если страна не определилась (``country is None``) —
    не блокируем. Это сознательный trade-off: альтернатива (fail-closed)
    ломает легитимных пользователей за прокси без CF-header.

    :param country: ISO-код страны или None.
    :returns: ``True`` если страна в списке заблокированных.
    """
    if country is None:
        return False
    blocked = _parse_blocked_set(get_settings().geo_block_countries)
    return country.upper() in blocked
