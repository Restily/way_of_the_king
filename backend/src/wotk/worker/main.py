"""Arq worker — cron-задачи + фоновая обработка.

Запуск: ``uv run python -m wotk.worker`` или ``arq wotk.worker.main.WorkerSettings``.

Зарегистрированные cron'ы (MVP):

* :func:`cleanup_expired_idempotency_keys` — каждые 30 минут.
* :func:`cleanup_expired_runs` — каждые 5 минут (заглушка до Phase 4 dungeon_runs).

При добавлении новой задачи:

1. Написать ``async def task_name(ctx, ...) -> ...``.
2. Добавить в :attr:`WorkerSettings.functions` (для on-demand enqueue) или
   :attr:`WorkerSettings.cron_jobs` (для расписания).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.core.config import get_settings
from wotk.core.db import dispose_engine, session_scope
from wotk.domain.enums import Rarity, RunStatus
from wotk.domain.models import DungeonRun, Item

log = structlog.get_logger()


async def cleanup_expired_idempotency_keys(ctx: dict[str, Any]) -> int:
    """Удалить просроченные idempotency-записи.

    Прямой ``DELETE WHERE expires_at < now()`` — простая операция, не
    требует stored procedure. Использует ``ix_idem_expires`` индекс из
    миграции 0006.

    :param ctx: Arq context (не используется, требуется по сигнатуре).
    :returns: Количество удалённых строк.
    """
    _ = ctx
    async with session_scope() as session:
        result = await session.execute(
            text("DELETE FROM idempotency_keys WHERE expires_at < now()")
        )
        affected = result.rowcount or 0
    log.info("cleanup_expired_idempotency_keys", deleted=affected)
    return int(affected)


async def _partial_escrow_release(
    session: AsyncSession,
    run_id: UUID,
    profile_id: int,
) -> int:
    """Переместить 50% лучших escrow items данного run'а в inventory (W6-054).

    Выбирает ``floor(N/2)`` лучших items (по rarity DESC, ilvl DESC) и
    переносит их в первые свободные inventory_position (0-47). Если слотов
    не хватает — items остаются в escrow для ручного /claim.

    :param session: Async DB session (внутри active transaction).
    :param run_id: UUID завершаемого run'а.
    :param profile_id: ID профиля-владельца.
    :returns: Количество перемещённых items.
    """
    # SELECT escrow items sorted best-first.
    escrow_items = (
        await session.scalars(
            select(Item)
            .where(Item.escrow_run_id == run_id)
            .order_by(Item.rarity.desc(), Item.ilvl.desc())
        )
    ).all()

    if not escrow_items:
        return 0

    # Take floor(N/2) best items.
    move_count = len(escrow_items) // 2
    if move_count == 0:
        return 0

    to_move = escrow_items[:move_count]

    # Find occupied inventory positions.
    used_positions = set(
        (
            await session.scalars(
                select(Item.inventory_position).where(
                    Item.owner_profile_id == profile_id,
                    Item.inventory_position.is_not(None),
                )
            )
        ).all()
    )
    free_iter = (p for p in range(48) if p not in used_positions)

    moved = 0
    for item in to_move:
        free_pos = next(free_iter, None)
        if free_pos is None:
            # Inventory full — остаток остаётся в escrow.
            break
        # Must clear escrow_run_id BEFORE setting inventory_position
        # to satisfy CHECK ck_item_state_exclusive.
        item.escrow_run_id = None
        item.inventory_position = free_pos
        moved += 1

    return moved


async def cleanup_expired_runs(ctx: dict[str, Any]) -> int:
    """Перевести зависшие IN_PROGRESS dungeon_runs в ABANDONED.

    Run автоматически expires через 24h (см. enter handler:
    ``expires_at = now() + 24h``). Cron находит протухшие, помечает
    ABANDONED и применяет grace-policy (RUN-LIFECYCLE.md §6):

    * 50% лучших escrow items (по rarity DESC, ilvl DESC) переносятся
      в свободные inventory slots.
    * Остаток остаётся в escrow для ручного /claim endpoint (W7).

    :param ctx: Arq context (не используется).
    :returns: Количество переведённых run'ов.
    """
    _ = ctx
    async with session_scope() as session:
        # Загрузить все expired IN_PROGRESS runs.
        expired_runs = (
            await session.scalars(
                select(DungeonRun).where(
                    DungeonRun.status == RunStatus.IN_PROGRESS,
                    DungeonRun.expires_at < text("now()"),
                )
            )
        ).all()

        if not expired_runs:
            return 0

        from datetime import UTC, datetime

        now = datetime.now(UTC)
        total_moved = 0

        for run in expired_runs:
            # Apply 50% escrow grace policy BEFORE status flip (cleaner ordering).
            moved = await _partial_escrow_release(
                session, run_id=run.id, profile_id=run.profile_id
            )
            total_moved += moved

            run.status = RunStatus.ABANDONED
            run.finished_at = now

            if moved > 0:
                log.info(
                    "cleanup_partial_escrow_moved",
                    run_id=str(run.id),
                    profile_id=run.profile_id,
                    items_moved=moved,
                )

        await session.flush()

    affected = len(expired_runs)
    if affected:
        log.info("cleanup_expired_runs", abandoned=affected, escrow_items_moved=total_moved)
    return affected


async def reconcile_balances(ctx: dict[str, Any]) -> int:
    """Сверка ``balance.gold`` против последней ``transaction.balance_after``.

    Реализует RUNBOOK.md §2.5. При расхождении — CRITICAL log + Sentry alert.
    Не правит данные сам — это manual incident response.

    :returns: Количество найденных drift'ов (0 = здоровая система).
    """
    _ = ctx
    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                SELECT b.profile_id, b.gold, t.balance_after AS last_tx
                FROM balance b
                LEFT JOIN LATERAL (
                    SELECT balance_after FROM "transaction"
                     WHERE profile_id = b.profile_id
                     ORDER BY id DESC LIMIT 1
                ) t ON true
                WHERE t.balance_after IS NOT NULL
                  AND b.gold != t.balance_after
                """
            )
        )
        drifts = result.fetchall()
    for row in drifts:
        log.critical(
            "balance_drift_detected",
            profile_id=row.profile_id,
            balance_gold=row.gold,
            last_transaction_balance=row.last_tx,
            drift=row.gold - row.last_tx,
        )
    return len(drifts)


async def startup(ctx: dict[str, Any]) -> None:
    """Worker startup — логируем готовность.

    Engine инициализируется лениво при первом ``session_scope()``,
    поэтому здесь только log + опциональная инициализация Sentry.

    :param ctx: Arq context для kv-storage.
    """
    settings = get_settings()
    ctx["env"] = settings.app_env
    log.info("worker_startup", env=settings.app_env)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown — закрываем DB engine.

    :param ctx: Arq context.
    """
    _ = ctx
    await dispose_engine()
    log.info("worker_shutdown")


class WorkerSettings:
    """Конфигурация Arq worker'а.

    Подхватывается командой ``arq wotk.worker.main.WorkerSettings``
    или через :mod:`wotk.worker.__main__`.

    ``redis_settings`` резолвится на module-import time — для worker'а это
    корректно (отдельный процесс с собственным lifecycle), для тестов
    модуль не импортируется.
    """

    functions: list = []  # noqa: RUF012  — on-demand задач пока нет

    cron_jobs = [  # noqa: RUF012  — Arq читает class-level
        # idempotency cleanup: каждые 30 мин (TTL 2-24h, запас покрывает окно)
        cron(
            cleanup_expired_idempotency_keys,
            minute={0, 30},
            run_at_startup=False,
        ),
        # runs cleanup: каждые 5 мин (per RUN-LIFECYCLE.md grace policy)
        cron(
            cleanup_expired_runs,
            minute=set(range(0, 60, 5)),
            run_at_startup=False,
        ),
        # reconciliation: каждые 5 мин (drift detection, см. RUNBOOK §2.5)
        cron(
            reconcile_balances,
            minute=set(range(2, 60, 5)),  # offset на 2 мин от cleanup_runs
            run_at_startup=False,
        ),
    ]

    on_startup = startup
    on_shutdown = shutdown

    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
