# bot_app/main.py
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

# --- Django ORM bootstrap ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "config.settings"))
django.setup()

from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from django.db import transaction  # noqa: E402
from billing.models import TelegramUser, StarPayment, PremiumPlan  # noqa: E402

# Analytics
from analytics.services import log_event  # async wrapper
from analytics.models import BotEvent  # for event type constants

SEARCH_ENDPOINT = f"{API_BASE_URL}/api/search/"

FREE_GLASSES_LIMIT = int(os.getenv("FREE_GLASSES_LIMIT", "3"))
TG_MAX_MESSAGE = 3900  # безопасный лимит под HTML

# Порядок и набор планов, которые показываем в меню
PLAN_CODES_ORDER = ["premium_30", "premium_90", "premium_180", "premium_360"]

# Ссылки/токены
CHANNEL_URL = getattr(settings, "CHANNEL_URL", "https://t.me/your_channel")
CHAT_URL = getattr(settings, "CHAT_URL", "https://t.me/your_chat")
TG_PROVIDER_TOKEN = getattr(settings, "TG_PROVIDER_TOKEN", "")

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Статус"), KeyboardButton(text="Подписка")],
        [KeyboardButton(text="Информация")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Введите модель или выберите действие…",
)


# -------------------------
# HTTP
# -------------------------
async def api_search(query: str) -> Dict[str, Any]:
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(SEARCH_ENDPOINT, params={"q": query})
        r.raise_for_status()
        return r.json()


# -------------------------
# Payload helpers
# -------------------------
def make_payload(user_id: int, plan_code: str) -> str:
    nonce = secrets.token_urlsafe(8)
    payload = f"p:{plan_code}:{user_id}:{nonce}"
    return payload[:128]


def parse_payload(payload: str) -> Optional[Tuple[str, int]]:
    try:
        parts = (payload or "").split(":")
        if len(parts) < 4 or parts[0] != "p":
            return None
        plan_code = parts[1]
        user_id = int(parts[2])
        return plan_code, user_id
    except Exception:
        return None


# -------------------------
# ORM wrappers (sync -> async)
# -------------------------
def _upsert_tg_user_sync(tg_id: int, username: str, first_name: str, last_name: str) -> TelegramUser:
    defaults = {
        "username": username or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
    }

    obj, created = TelegramUser.objects.get_or_create(telegram_id=tg_id, defaults=defaults)
    if not created:
        changed = False
        for k, v in defaults.items():
            if getattr(obj, k) != v:
                setattr(obj, k, v)
                changed = True
        if changed:
            obj.save(update_fields=["username", "first_name", "last_name", "updated_at"])
    return obj


# async wrapper to use in handlers
upsert_tg_user = sync_to_async(_upsert_tg_user_sync, thread_sensitive=True)


def _is_premium_active_sync(tg_id: int) -> Tuple[bool, Optional[Any]]:
    user = TelegramUser.objects.filter(telegram_id=tg_id).first()
    if not user or not user.premium_until:
        return False, None
    return user.premium_until > timezone.now(), user.premium_until


is_premium_active = sync_to_async(_is_premium_active_sync, thread_sensitive=True)


def _get_plan_sync(plan_code: str) -> PremiumPlan:
    plan = PremiumPlan.objects.filter(code=plan_code, is_active=True).first()
    if not plan:
        raise RuntimeError(f"Premium plan '{plan_code}' not found or inactive. Create it in admin.")
    return plan


get_plan = sync_to_async(_get_plan_sync, thread_sensitive=True)


def _list_plans_sync() -> List[PremiumPlan]:
    qs = PremiumPlan.objects.filter(is_active=True, code__in=PLAN_CODES_ORDER)
    by_code = {p.code: p for p in qs}
    ordered = [by_code[c] for c in PLAN_CODES_ORDER if c in by_code]
    return ordered


list_plans = sync_to_async(_list_plans_sync, thread_sensitive=True)


def _precheckout_validate_sync(from_user_id: int, currency: str, total_amount: int, payload: str) -> Tuple[bool, str]:
    if currency != "XTR":
        return False, "Неверная валюта платежа."

    parsed = parse_payload(payload)
    if not parsed:
        return False, "Некорректный payload платежа."

    plan_code, uid = parsed
    if uid != from_user_id:
        return False, "Платёж не соответствует пользователю."

    plan = PremiumPlan.objects.filter(code=plan_code, is_active=True).first()
    if not plan:
        return False, "Тариф недоступен."

    if int(total_amount) != int(plan.price_stars):
        return False, "Неверная сумма платежа."

    return True, ""


precheckout_validate = sync_to_async(_precheckout_validate_sync, thread_sensitive=True)


def _apply_success_payment_sync(
    tg_id: int,
    username: str,
    first_name: str,
    last_name: str,
    currency: str,
    total_amount: int,
    invoice_payload: str,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str,
) -> Tuple[bool, str, Optional[Any]]:
    """
    Возвращает (ok, msg, premium_until).
    ok=False -> ошибка/уже обработан.
    """
    if currency != "XTR":
        return False, "Платёж получен, но валюта не XTR.", None

    parsed = parse_payload(invoice_payload)
    if not parsed:
        return False, "Платёж получен, но тариф не распознан.", None

    plan_code, uid = parsed
    if uid != tg_id:
        return False, "Платёж получен, но пользователь не совпадает.", None

    plan = PremiumPlan.objects.filter(code=plan_code, is_active=True).first()
    if not plan:
        return False, "Платёж получен, но тариф сейчас недоступен.", None

    if int(total_amount) != int(plan.price_stars):
        return False, "Платёж получен, но сумма не совпала с тарифом.", None

    # идемпотентность
    if StarPayment.objects.filter(telegram_payment_charge_id=telegram_payment_charge_id).exists():
        user = TelegramUser.objects.filter(telegram_id=tg_id).first()
        return False, "Платёж уже был обработан.", user.premium_until if user else None

    with transaction.atomic():
        user = _upsert_tg_user_sync(tg_id, username, first_name, last_name)

        StarPayment.objects.create(
            user=user,
            telegram_payment_charge_id=telegram_payment_charge_id,
            provider_payment_charge_id=provider_payment_charge_id or "",
            currency=currency,
            total_amount=int(total_amount),
            invoice_payload=invoice_payload,
            status=StarPayment.STATUS_SUCCEEDED,
        )

        now = timezone.now()
        base = user.premium_until if user.premium_until and user.premium_until > now else now
        user.premium_until = base + timedelta(days=int(plan.duration_days))
        user.save(update_fields=["premium_until", "updated_at"])

    return True, "✅ Оплата получена. Premium активирован.", user.premium_until


apply_success_payment = sync_to_async(_apply_success_payment_sync, thread_sensitive=True)


# -------------------------
# Long message helpers
# -------------------------
def split_html_message(text: str, max_len: int = TG_MAX_MESSAGE) -> List[str]:
    if len(text) <= max_len:
        return [text]

    marker = "\n<b>Вариант "
    chunks: List[str] = []
    parts = text.split(marker)

    current = parts[0].strip()
    for i in range(1, len(parts)):
        piece = (marker + parts[i]).strip()
        if not current:
            current = piece
            continue

        if len(current) + 2 + len(piece) <= max_len:
            current += "\n\n" + piece
        else:
            chunks.append(current)
            current = piece

    if current:
        chunks.append(current)

    final: List[str] = []
    for ch in chunks:
        if len(ch) <= max_len:
            final.append(ch)
            continue

        lines = ch.split("\n")
        cur = ""
        for ln in lines:
            add = ln + "\n"
            if len(cur) + len(add) <= max_len:
                cur += add
            else:
                if cur.strip():
                    final.append(cur.strip())
                cur = add
        if cur.strip():
            final.append(cur.strip())

    return final


async def send_long_html(message: Message, text: str) -> None:
    for part in split_html_message(text):
        await message.answer(part, reply_markup=MAIN_KB)


# -------------------------
# UI: plans keyboard
# -------------------------
async def build_plans_kb() -> InlineKeyboardMarkup:
    plans = await list_plans()
    rows: List[List[InlineKeyboardButton]] = []
    for p in plans:
        btn_text = f"{p.duration_days} дней — {p.price_stars} ⭐"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy:{p.code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_invoice_for_plan(message: Message, plan_code: str) -> None:
    tg = message.from_user
    plan = await get_plan(plan_code)

    payload = make_payload(tg.id, plan.code)
    prices = [LabeledPrice(label=plan.title, amount=int(plan.price_stars))]

    # Log invoice sent (analytics)
    try:
        user_obj = await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")
    except Exception:
        user_obj = None

    if user_obj:
        try:
            await log_event(user_obj, BotEvent.EventType.INVOICE_SENT, {"plan_code": plan.code, "price": plan.price_stars})
        except Exception:
            pass

    await message.answer_invoice(
        title=plan.title,
        description=plan.description or f"Premium доступ на {plan.duration_days} дней",
        payload=payload,
        provider_token=TG_PROVIDER_TOKEN or "",
        currency="XTR",
        prices=prices,
    )


# -------------------------
# Commands
# -------------------------
async def cmd_start(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")
    try:
        user = TelegramUser.objects.filter(telegram_id=tg.id).first()
        if user:
            await log_event(user, BotEvent.EventType.START)
    except Exception:
        pass

    await message.answer(
        "Отправьте модель/название стекла, и я покажу взаимозаменяемые варианты.\n\n"
        "Кнопки:\n"
        "• Статус — статус Premium\n"
        "• Подписка — купить Premium (Stars)\n"
        "• Информация — о боте и контакты\n\n"
        "Команды:\n"
        "/status — статус подписки\n"
        "/premium — оформить Premium (Stars)",
        reply_markup=MAIN_KB,
    )


async def cmd_help(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")
    try:
        user = TelegramUser.objects.filter(telegram_id=tg.id).first()
        if user:
            await log_event(user, BotEvent.EventType.HELP)
    except Exception:
        pass

    await message.answer(
        "Как пользоваться:\n"
        "1) Напишите модель/название (можно алиас).\n"
        "2) Я верну варианты взаимозаменяемости и список подходящих стёкол.\n\n"
        "Кнопки:\n"
        "• Статус — покажет активность Premium\n"
        "• Подписка — оформить Premium (Stars)\n\n"
        f"Текущий endpoint: {SEARCH_ENDPOINT}",
        reply_markup=MAIN_KB,
    )


async def cmd_status(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")

    active, until = await is_premium_active(tg.id)
    if active and until:
        dt = timezone.localtime(until).strftime("%Y-%m-%d %H:%M")
        await message.answer(f"✅ Premium активен до: <b>{dt}</b>", reply_markup=MAIN_KB)
    else:
        await message.answer("ℹ️ Premium не активен.\n\nОформить: /premium", reply_markup=MAIN_KB)


async def cmd_premium(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")

    kb = await build_plans_kb()
    try:
        user = TelegramUser.objects.filter(telegram_id=tg.id).first()
        if user:
            await log_event(user, BotEvent.EventType.PREMIUM_OPEN)
    except Exception:
        pass

    await message.answer("Выберите тариф Premium:", reply_markup=kb)


async def cmd_info(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")

    try:
        user = TelegramUser.objects.filter(telegram_id=tg.id).first()
        if user:
            await log_event(user, BotEvent.EventType.INFO)
    except Exception:
        pass

    text = (
        "<b>ℹ️ О боте</b>\n\n"
        "Бот помогает подобрать взаимозаменяемые защитные стёкла для телефонов.\n\n"

        "<b>Зачем нужен Premium</b>\n\n"
        "Premium — это поддержка проекта.\n"
        "Подписка помогает оплачивать серверы, поддерживать базу данных, "
        "выпускать обновления и развивать новые функции.\n\n"

        "Что даёт Premium:\n"
        "• Полный доступ ко всем результатам без ограничений\n"
        "• Более удобную и подробную выдачу\n"
        "• Быстрые обновления и улучшения\n\n"

        "<b>Связь</b>\n\n"
        "Подпишитесь на канал — там новости и новые проекты.\n"
        "Если бот недоступен или есть вопросы — пишите в чат."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Канал (новости и обновления)", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="💬 Чат (вопросы и поддержка)", url=CHAT_URL)],
    ])

    await message.answer(text, reply_markup=kb)


# Reply keyboard wrappers (register these, not lambdas)
async def btn_status(message: Message) -> None:
    await cmd_status(message)

async def btn_premium(message: Message) -> None:
    await cmd_premium(message)

async def btn_info(message: Message) -> None:
    await cmd_info(message)


# -------------------------
# Inline callbacks (plans)
# -------------------------
async def on_buy_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    if not data.startswith("buy:"):
        await callback.answer()
        return

    plan_code = data.split("buy:", 1)[1].strip()
    await callback.answer()  # убираем "часики"

    if not callback.message:
        return

    # Отправляем инвойс в тот же чат
    await send_invoice_for_plan(callback.message, plan_code)


# -------------------------
# Payments
# -------------------------
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery) -> None:
    ok, err = await precheckout_validate(
        from_user_id=pre_checkout_query.from_user.id,
        currency=pre_checkout_query.currency,
        total_amount=int(pre_checkout_query.total_amount),
        payload=pre_checkout_query.invoice_payload or "",
    )
    if not ok:
        await pre_checkout_query.answer(ok=False, error_message=err)
        return
    await pre_checkout_query.answer(ok=True)


async def successful_payment_handler(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")

    sp = message.successful_payment
    ok, msg, until = await apply_success_payment(
        tg_id=tg.id,
        username=tg.username or "",
        first_name=tg.first_name or "",
        last_name=tg.last_name or "",
        currency=sp.currency,
        total_amount=int(sp.total_amount),
        invoice_payload=sp.invoice_payload or "",
        telegram_payment_charge_id=sp.telegram_payment_charge_id,
        provider_payment_charge_id=sp.provider_payment_charge_id or "",
    )

    if ok and until:
        dt = timezone.localtime(until).strftime("%Y-%m-%d %H:%M")
        await message.answer(f"{msg} До: <b>{dt}</b>", reply_markup=MAIN_KB)
    else:
        await message.answer(msg, reply_markup=MAIN_KB)
        await cmd_status(message)


# -------------------------
# Main text handler
# -------------------------
async def handle_text(message: Message) -> None:
    tg = message.from_user
    await upsert_tg_user(tg.id, tg.username or "", tg.first_name or "", tg.last_name or "")

    q = (message.text or "").strip()
    if not q:
        return

    if q == "Статус":
        await cmd_status(message)
        return
    if q == "Подписка":
        await cmd_premium(message)
        return
    if q == "Информация":
        await cmd_info(message)
        return

    try:
        user = TelegramUser.objects.filter(telegram_id=tg.id).first()
        if user:
            await log_event(user, BotEvent.EventType.SEARCH, {"query": q})
    except Exception:
        pass

    try:
        data = await api_search(q)
    except httpx.HTTPStatusError as e:
        await message.answer(
            "Ошибка ответа от сервера поиска.\n"
            f"HTTP: {e.response.status_code}\n"
            "Проверьте, что Django запущен и /api/search/ доступен.",
            reply_markup=MAIN_KB,
        )
        return
    except httpx.RequestError:
        await message.answer(
            "Не могу подключиться к серверу поиска.\n"
            f"API_BASE_URL сейчас: {API_BASE_URL}",
            reply_markup=MAIN_KB,
        )
        return
    except Exception:
        await message.answer("Неожиданная ошибка при поиске.", reply_markup=MAIN_KB)
        return

    try:
        user = TelegramUser.objects.filter(telegram_id=tg.id).first()
        if user:
            await log_event(
                user,
                BotEvent.EventType.SEARCH_RESULT,
                {
                    "query": q,
                    "found": data.get("found"),
                    "results_count": len(data.get("results", [])) if isinstance(data.get("results", []), list) else 0,
                },
            )
    except Exception:
        pass

    active, _until = await is_premium_active(tg.id)

    text = format_search_result(
        data,
        is_premium=active,
        free_glasses_limit=FREE_GLASSES_LIMIT,
    )
    await send_long_html(message, text)


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Commands
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(cmd_premium, Command("premium"))
    dp.message.register(cmd_info, Command("info"))

    # Reply keyboard buttons (register wrapper handlers)
    dp.message.register(btn_status, F.text == "Статус")
    dp.message.register(btn_premium, F.text == "Подписка")
    dp.message.register(btn_info, F.text == "Информация")

    # Inline callbacks for plan choice
    dp.callback_query.register(on_buy_callback, F.data.startswith("buy:"))

    # Payments
    dp.pre_checkout_query.register(pre_checkout_handler)
    dp.message.register(successful_payment_handler, F.successful_payment)

    # Search / default text
    dp.message.register(handle_text, F.text)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
