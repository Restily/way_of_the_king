"""Rate limiter (slowapi на Redis).

Глобальный лимит — по IP. Per-user лимиты применяются на уровне
эндпоинтов через явные декораторы с ``key_func``, основанным на
``profile_id`` из JWT.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from wotk.core.config import get_settings

_settings = get_settings()

#: Module-level singleton :class:`Limiter` instance.
#: Используется в FastAPI app: ``app.state.limiter = limiter``
#: и в декораторах эндпоинтов: ``@limiter.limit("20/minute")``.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{_settings.rate_limit_per_ip_per_min}/minute"],
    storage_uri=_settings.redis_url,
    strategy="fixed-window",
    headers_enabled=True,
)
