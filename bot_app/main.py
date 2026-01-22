import asyncio
from typing import Any, Dict

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot_app.settings import BOT_TOKEN, API_BASE_URL
from bot_app.formatters import format_search_result

SEARCH_ENDPOINT = f"{API_BASE_URL}/api/search/"


async def api_search(query: str) -> Dict[str, Any]:
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(SEARCH_ENDPOINT, params={"q": query})
        r.raise_for_status()
        return r.json()


async def cmd_start(message: Message) -> None:
    await message.answer(
        "Отправьте модель/название стекла, и я покажу взаимозаменяемые варианты.\n\n"
        "Примеры:\n"
        "• Samsung A13\n"
        "• A13 5G\n"
        "• m32\n\n"
        "Команды:\n"
        "/help — помощь"
    )


async def cmd_help(message: Message) -> None:
    await message.answer(
        "Как пользоваться:\n"
        "1) Напишите модель/название (можно алиас).\n"
        "2) Я верну группу взаимозаменяемости, бренды и список подходящих стёкол.\n\n"
        "Если не находит:\n"
        "• попробуйте другое написание\n"
        "• добавьте алиас рядом со стеклом в админке\n\n"
        f"Текущий endpoint: {SEARCH_ENDPOINT}"
    )


async def handle_text(message: Message) -> None:
    q = (message.text or "").strip()
    if not q:
        return

    if len(q) < 2:
        await message.answer("Слишком короткий запрос. Напишите подробнее.")
        return

    try:
        data = await api_search(q)
    except httpx.HTTPStatusError as e:
        await message.answer(
            "Ошибка ответа от сервера поиска.\n"
            f"HTTP: {e.response.status_code}\n"
            "Проверьте, что Django запущен и /api/search/ доступен."
        )
        return
    except httpx.RequestError:
        await message.answer(
            "Не могу подключиться к серверу поиска.\n"
            "Запустите Django: python manage.py runserver\n"
            f"API_BASE_URL сейчас: {API_BASE_URL}"
        )
        return
    except Exception:
        await message.answer("Неожиданная ошибка при поиске.")
        return

    await message.answer(format_search_result(data))


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(handle_text, F.text)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
