"""Telegram бот (aiogram 3) — entrypoint ``python -m wotk.bot``.

В MVP минимальная функциональность:

* ``/start [referral_code]`` — приветствие + кнопка с web_app
* ``/help`` — текст помощи
* ``/wallet`` — placeholder (Phase 7)

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


#: Окно начислений реферальных бонусов в днях.
REFERRAL_WINDOW_DAYS = 30

#: Префикс реферального кода в deeplink ``?startapp=ref_<telegram_id>``.
REFERRAL_PREFIX = "ref_"


def _build_dispatcher(miniapp_url: str, fallback_url: str) -> Dispatcher:
    """Собрать aiogram :class:`Dispatcher` с зарегистрированными handler'ами.

    :param miniapp_url: Прямой HTTPS URL Mini App для ``WebAppInfo`` кнопки.
        Если пустой — используется ``fallback_url`` как обычная URL-кнопка
        (Telegram ``WebAppInfo`` не принимает ``t.me/...`` — только реальный hosting).
    :param fallback_url: ``t.me/<bot>/<short_name>`` — открывает Mini App через
        Telegram-deeplink, когда прямой hosting не настроен.
    :returns: Настроенный диспетчер.
    """
    dp = Dispatcher()

    if miniapp_url:
        button = InlineKeyboardButton(
            text="⚔️ Открыть игру",
            web_app=WebAppInfo(url=miniapp_url),
        )
    else:
        button = InlineKeyboardButton(
            text="⚔️ Открыть игру",
            url=fallback_url,
        )
    welcome_kb = InlineKeyboardMarkup(inline_keyboard=[[button]])

    @dp.message(CommandStart(deep_link=True))
    async def start_with_param(message: Message, command: CommandObject) -> None:
        """``/start <param>`` — обработка приглашения по реферальному коду."""
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
        """``/start`` без параметра — простое приветствие."""
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
        """``/help`` — список команд."""
        await message.answer(
            "<b>Команды:</b>\n"
            "/start — открыть игру\n"
            "/wallet — кошелёк (скоро)\n"
            "/help — это сообщение"
        )

    @dp.message(F.text == "/wallet")
    async def wallet_cmd(message: Message) -> None:
        """``/wallet`` — placeholder, реальный функционал в Phase 7."""
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
    """Записать реферал если код валиден и оба профиля существуют.

    Если ``referred`` ещё не создан (приглашённый не успел открыть Mini App) —
    запись теряется. В v1.x можно ввести ``pending_referral`` для отложенного
    matching при первом login.

    Дублирующиеся записи (один и тот же ``referred``) ловятся
    ``IntegrityError`` от ``uq_referral_referred``.

    :param referrer_telegram_id_or_code: Строковый код из deep-link
        (без префикса ``ref_``). Должен парситься в int.
    :param referred_telegram_id: Telegram ID приглашённого юзера.
    """
    try:
        referrer_telegram_id = int(referrer_telegram_id_or_code)
    except ValueError:
        log.info("referral_code_not_int", code=referrer_telegram_id_or_code)
        return

    if referrer_telegram_id == referred_telegram_id:
        return

    async with session_scope() as session:
        profiles = (
            await session.scalars(
                select(Profile).where(
                    Profile.telegram_id.in_(
                        [referrer_telegram_id, referred_telegram_id]
                    )
                )
            )
        ).all()
        by_tg = {p.telegram_id: p for p in profiles}
        referrer = by_tg.get(referrer_telegram_id)
        referred = by_tg.get(referred_telegram_id)

        if referrer is None:
            log.info("referral_referrer_not_found", tg_id=referrer_telegram_id)
            return
        if referred is None:
            log.info("referral_referred_not_found_yet")
            return

        session.add(
            Referral(
                referrer_profile_id=referrer.id,
                referred_profile_id=referred.id,
                expires_at=datetime.now(UTC)
                + timedelta(days=REFERRAL_WINDOW_DAYS),
            )
        )
        try:
            await session.flush()
        except IntegrityError:
            log.info(
                "referral_already_recorded",
                referred_telegram_id=referred_telegram_id,
            )


async def main() -> None:
    """Entry point бота: создаёт Bot + Dispatcher и стартует polling.

    В проде должна запускаться отдельным процессом (контейнер ``bot``
    в docker-compose). Логирует и выходит с кодом 1 если
    ``TELEGRAM_BOT_TOKEN`` пуст.

    :returns: Ничего (бесконечно polling до SIGTERM).
    """
    settings = get_settings()
    bot_token = settings.telegram_bot_token.get_secret_value()
    if not bot_token:
        log.error("telegram_bot_token_not_set")
        sys.exit(1)

    miniapp_url = settings.telegram_miniapp_url.strip()
    if miniapp_url and not miniapp_url.startswith("https://"):
        log.error("telegram_miniapp_url_must_be_https", url=miniapp_url)
        sys.exit(1)
    fallback_url = (
        f"https://t.me/{settings.telegram_bot_username}/{settings.telegram_miniapp_short_name}"
        if settings.telegram_bot_username
        else "https://t.me/"
    )
    if not miniapp_url:
        log.warning(
            "telegram_miniapp_url_not_set_using_fallback",
            fallback=fallback_url,
            hint="Set TELEGRAM_MINIAPP_URL in .env (cloudflared/ngrok URL in dev)",
        )

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = _build_dispatcher(miniapp_url=miniapp_url, fallback_url=fallback_url)
    log.info("bot_starting", username=settings.telegram_bot_username)
    try:
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
