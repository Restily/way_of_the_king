"""Telegram бот (aiogram 3) — entrypoint `python -m wotk.bot`.

В MVP минимальная функциональность:
- /start [referral_code] — приветствие + кнопка с web_app
- /help — текст помощи
- /wallet — placeholder (Phase 7)

Бот живёт отдельным процессом. В docker-compose поднимается вместе с api.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from wotk.core.config import get_settings
from wotk.core.db import session_scope
from wotk.domain.models import Profile, Referral

log = structlog.get_logger()


REFERRAL_WINDOW_DAYS = 30
REFERRAL_PREFIX = "ref_"


def _build_dispatcher(miniapp_url: str) -> Dispatcher:
    dp = Dispatcher()

    welcome_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ Открыть игру",
                    web_app=WebAppInfo(url=miniapp_url),
                )
            ]
        ]
    )

    @dp.message(CommandStart(deep_link=True))
    async def start_with_param(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return
        param = (command.args or "").strip()
        ref_code = (
            param[len(REFERRAL_PREFIX) :]
            if param.startswith(REFERRAL_PREFIX)
            else None
        )
        await _handle_start(message, ref_code)

    @dp.message(CommandStart())
    async def start_plain(message: Message) -> None:
        await _handle_start(message, None)

    async def _handle_start(message: Message, ref_code: str | None) -> None:
        if message.from_user is None:
            return
        if ref_code:
            await _try_record_referral(
                referrer_telegram_id_or_code=ref_code,
                referred_telegram_id=message.from_user.id,
            )
        await message.answer(
            "Добро пожаловать в <b>Way Of The King</b>!\n\n"
            "Тёмное средневековье ждёт твоего рыцаря. "
            "Открывай игру — и в путь.",
            reply_markup=welcome_kb,
        )

    @dp.message(F.text == "/help")
    async def help_cmd(message: Message) -> None:
        await message.answer(
            "<b>Команды:</b>\n"
            "/start — открыть игру\n"
            "/wallet — кошелёк (скоро)\n"
            "/help — это сообщение"
        )

    @dp.message(F.text == "/wallet")
    async def wallet_cmd(message: Message) -> None:
        await message.answer(
            "💰 Кошелёк появится в следующем обновлении.\n"
            "Пока что золото копится в игре."
        )

    return dp


async def _try_record_referral(
    *,
    referrer_telegram_id_or_code: str,
    referred_telegram_id: int,
) -> None:
    """Записываем реферал если код парсится в telegram_id и есть такой профиль.

    Защита: не записываем если referrer == referred, или если у referred
    уже есть запись (uq_referral_referred ловит).
    """
    try:
        referrer_telegram_id = int(referrer_telegram_id_or_code)
    except ValueError:
        log.info("referral_code_not_int", code=referrer_telegram_id_or_code)
        return

    if referrer_telegram_id == referred_telegram_id:
        return

    try:
        async with session_scope() as session:
            referrer = await session.scalar(
                select(Profile).where(Profile.telegram_id == referrer_telegram_id)
            )
            if referrer is None:
                log.info("referral_referrer_not_found", tg_id=referrer_telegram_id)
                return

            referred = await session.scalar(
                select(Profile).where(Profile.telegram_id == referred_telegram_id)
            )
            if referred is None:
                # Профиль ещё не создан — это нормально, создастся после login
                # в Mini App. Тогда мы потеряем эту попытку, но это OK.
                # В v1.x можно сделать pending_referrals таблицу.
                log.info("referral_referred_not_found_yet")
                return

            if referrer.id == referred.id:
                return

            session.add(
                Referral(
                    referrer_profile_id=referrer.id,
                    referred_profile_id=referred.id,
                    expires_at=datetime.now(UTC)
                    + timedelta(days=REFERRAL_WINDOW_DAYS),
                )
            )
    except IntegrityError:
        log.info(
            "referral_already_recorded",
            referred_telegram_id=referred_telegram_id,
        )


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.error("telegram_bot_token_not_set")
        sys.exit(1)

    miniapp_url = (
        f"https://t.me/{settings.telegram_bot_username}/app"
        if settings.telegram_bot_username
        else "https://t.me/"
    )

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = _build_dispatcher(miniapp_url=miniapp_url)
    log.info("bot_starting", username=settings.telegram_bot_username)
    try:
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
