from asgiref.sync import sync_to_async
from .models import BotEvent


def _log_event_sync(user, event_type: str, payload: dict | None = None) -> BotEvent:
    """
    Синхронная версия — создаёт запись.
    """
    return BotEvent.objects.create(
        user=user,
        event_type=event_type,
        payload=payload or {},
    )


# Асинхронный обёртка для использования в aiogram (вызов await log_event(...))
log_event = sync_to_async(_log_event_sync, thread_sensitive=True)
