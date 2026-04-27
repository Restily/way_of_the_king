"""Entrypoint для ``python -m wotk.bot``.

Запускает aiogram polling через :func:`wotk.bot.main.main`.
"""

from __future__ import annotations

import asyncio

from wotk.bot.main import main

if __name__ == "__main__":
    asyncio.run(main())
