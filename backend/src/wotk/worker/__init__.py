"""Arq-воркеры для фоновых задач (cleanup-cron, loot materialization, payouts).

Entrypoint: ``python -m wotk.worker`` (см. :mod:`wotk.worker.__main__`).
В docker-compose поднимается отдельным сервисом ``worker``.
"""
