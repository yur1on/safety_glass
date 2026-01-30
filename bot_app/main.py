import asyncio
import os
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, List

import django
import httpx
from asgiref.sync import sync_to_async
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    LabeledPrice,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from bot_app.settings import BOT_TOKEN, API_BASE_URL
from bot_app.formatters import format_search_result

# ---------------- Django bootstrap ----------------
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "config.settings"),
)
django.setup()
from django.conf import settings
from django.utils import timezone  # noqa
from django.db import transaction  # noqa
from billing.models import TelegramUser, StarPayment, PremiumPlan  # noqa

# ---------------- Analytics ----------------
from analytics.services import log_event
from analytics.models import BotEvent

# ---------------- Config ----------------
SEARCH_ENDPOINT = f"{API_BASE_URL}/api/search/"
FREE_GLASSES_LIMIT = int(os.getenv("FREE_GLASSES_LIMIT", "3"))
TG_MAX_MESSAGE = 3900



CHANNEL_URL = getattr(settings, "CHANNEL_URL", "https://t.me/your_channel")
CHAT_URL = getattr(settings, "CHAT_URL", "https://t.me/your_chat")


PLAN_CODES_ORDER = ["premium_30", "premium_90", "premium_180", "premium_360"]

# ---------------- Keyboards ----------------
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Статус"), KeyboardButton(text="Подписка")],
        [KeyboardButton(text="Информация")],
    ],
    resize_keyboard=True,
)

# ---------------- HTTP ----------------
async def api_search(query: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(SEARCH_ENDPOINT, params={"q": query})
        r.raise_for_status()
        return r.json()

# ---------------- Payload helpers ----------------
def make_payload(user_id: int, plan_code: str) -> str:
    return f"p:{plan_code}:{user_id}:{secrets.token_urlsafe(8)}"[:128]

def parse_payload(payload: str) -> Optional[Tuple[str, int]]:
    try:
        p, code, uid, _ = payload.split(":")
        return code, int(uid)
    except Exception:
        return None

# ---------------- ORM helpers ----------------
def _upsert_user_sync(tg) -> TelegramUser:
    obj, _ = TelegramUser.objects.get_or_create(
        telegram_id=tg.id,
        defaults={
            "username": tg.username or "",
            "first_name": tg.first_name or "",
            "last_name": tg.last_name or "",
        },
    )
    return obj

upsert_user = sync_to_async(_upsert_user_sync, thread_sensitive=True)

def _premium_status_sync(tg_id):
    u = TelegramUser.objects.filter(telegram_id=tg_id).first()
    return bool(u and u.premium_until and u.premium_until > timezone.now()), u.premium_until if u else None

is_premium_active = sync_to_async(_premium_status_sync, thread_sensitive=True)

# ---------------- Messages helpers ----------------
def split_html(text: str) -> List[str]:
    if len(text) <= TG_MAX_MESSAGE:
        return [text]
    res, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) < TG_MAX_MESSAGE:
            cur += line + "\n"
        else:
            res.append(cur)
            cur = line + "\n"
    res.append(cur)
    return res

async def send_long(message: Message, text: str):
    for part in split_html(text):
        await message.answer(part, reply_markup=MAIN_KB)

# ---------------- Commands ----------------
async def cmd_start(message: Message):
    user = await upsert_user(message.from_user)
    await log_event(user, BotEvent.EventType.START)

    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Отправьте модель телефона или стекла — я подберу взаимозаменяемые варианты.\n\n"
        "Кнопки:\n"
        "• Статус — проверка Premium\n"
        "• Подписка — оформить Premium\n"
        "• Информация — о боте и ссылки",
        reply_markup=MAIN_KB,
    )

async def cmd_status(message: Message):
    active, until = await is_premium_active(message.from_user.id)
    if active:
        await message.answer(f"✅ Premium активен до <b>{until:%d.%m.%Y}</b>")
    else:
        await message.answer("❌ Premium не активен")

async def cmd_premium(message: Message):
    user = await upsert_user(message.from_user)
    await log_event(user, BotEvent.EventType.PREMIUM_OPEN)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 дней — ⭐", callback_data="buy:premium_30")],
        [InlineKeyboardButton(text="90 дней — ⭐⭐", callback_data="buy:premium_90")],
    ])
    await message.answer("Выберите тариф:", reply_markup=kb)

async def cmd_info(message: Message) -> None:
    """
    Информация о боте + ссылки на канал и чат.
    Подробно про Premium: зачем нужен и что даёт.
    """
    try:
        user_obj = await upsert_user(message.from_user)
    except Exception:
        user_obj = None

    # логируем открытие информации
    try:
        if user_obj:
            await log_event(user_obj, BotEvent.EventType.INFO)
    except Exception:
        pass

    text = (
        "<b>ℹ️ О боте</b>\n\n"
        "Этот бот помогает подобрать взаимозаменяемые защитные стёкла для телефонов — "
        "введите модель, и бот покажет подходящие варианты.\n\n"

        "<b>Премиум — зачем он нужен</b>\n\n"
        "Premium — это способ поддержать проект и его развитие.\n"
        "Средства от подписки идут на оплату серверов, поддержку базы данных, "
        "разработку новых функций и регулярные обновления.\n\n"

        "Что даёт Premium:\n"
        "• Полный доступ ко всем совместимым вариантам без ограничений.\n"
        "• Более удобную и подробную выдачу результатов.\n"
        "• Поддержку и развитие бота в будущем.\n\n"
        "Оформляя Premium, вы помогаете проекту жить и становиться лучше — спасибо\n\n"

        "<b>Канал и чат</b>\n\n"
        "Подпишитесь на канал, чтобы следить за обновлениями и новыми проектами.\n"
        "Если бот временно недоступен или у вас есть вопросы — в чате всегда можно "
        "связаться и получить обратную связь.\n\n"
        "Выберите, куда перейти:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Канал (новости и обновления)", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="💬 Чат (вопросы и связь)", url=CHAT_URL)],
    ])

    await message.answer(text, reply_markup=kb)


# ---------------- Callbacks ----------------
async def on_buy(callback: CallbackQuery):
    plan_code = callback.data.split(":")[1]
    await callback.answer()
    await callback.message.answer(f"💳 Покупка тарифа: {plan_code}")

# ---------------- Text handler ----------------
async def handle_text(message: Message):
    if message.text == "Статус":
        return await cmd_status(message)
    if message.text == "Подписка":
        return await cmd_premium(message)
    if message.text == "Информация":
        return await cmd_info(message)

    user = await upsert_user(message.from_user)
    await log_event(user, BotEvent.EventType.SEARCH, {"query": message.text})

    data = await api_search(message.text)
    active, _ = await is_premium_active(message.from_user.id)

    text = format_search_result(data, is_premium=active, free_glasses_limit=FREE_GLASSES_LIMIT)
    await send_long(message, text)

# ---------------- Main ----------------
async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(cmd_premium, Command("premium"))
    dp.message.register(cmd_info, Command("info"))

    dp.callback_query.register(on_buy, F.data.startswith("buy:"))
    dp.message.register(handle_text, F.text)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
