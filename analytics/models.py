from typing import Any, Dict
from django.db import models
from django.utils import timezone
from billing.models import TelegramUser


class BotEvent(models.Model):
    class EventType(models.TextChoices):
        START = "start", "Start"
        HELP = "help", "Help"
        INFO = "info", "Info"  # <-- добавлено

        SEARCH = "search", "Search query"
        SEARCH_RESULT = "search_result", "Search result shown"

        PREMIUM_OPEN = "premium_open", "Premium opened"
        PREMIUM_CLICK = "premium_click", "Premium plan clicked"

        INVOICE_SENT = "invoice_sent", "Invoice sent"
        PRECHECKOUT_OK = "precheckout_ok", "PreCheckout OK"
        PRECHECKOUT_FAIL = "precheckout_fail", "PreCheckout FAIL"

        PAYMENT_SUCCESS = "payment_success", "Payment success"
        PAYMENT_FAIL = "payment_fail", "Payment fail"

    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="bot_events",
        verbose_name="Пользователь",
    )

    event_type = models.CharField(
        "Тип события",
        max_length=32,
        choices=EventType.choices,
        db_index=True,
    )

    payload = models.JSONField(
        "Дополнительные данные",
        blank=True,
        null=True,
        help_text="Произвольные данные: query, plan_code, amount, errors и т.д.",
    )

    created_at = models.DateTimeField(
        "Дата события",
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name = "Событие бота"
        verbose_name_plural = "События бота"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} — {self.get_event_label_ru()}"

    # ---- human friendly helpers ----
    EVENT_LABELS_RU = {
        "start": "Старт бота",
        "help": "Помощь",
        "info": "Информация",  # <-- добавлено
        "search": "Поиск (запрос)",
        "search_result": "Показ результата поиска",
        "premium_open": "Открытие меню Premium",
        "premium_click": "Клик по тарифу",
        "invoice_sent": "Отправлен инвойс",
        "precheckout_ok": "PreCheckout — ОК",
        "precheckout_fail": "PreCheckout — ошибка",
        "payment_success": "Успешная оплата",
        "payment_fail": "Ошибка оплаты",
    }

    def get_event_label_ru(self) -> str:
        return self.EVENT_LABELS_RU.get(self.event_type, self.event_type)

    def payload_summary(self) -> str:
        p: Dict[str, Any] = self.payload or {}

        if p.get("query"):
            q = str(p.get("query")).strip()
            return f'Запрос: "{q}"' if q else "Запрос"

        if "found" in p:
            found = p.get("found")
            cnt = p.get("results_count")
            if cnt is not None:
                return f'Результат: {"Да" if found else "Нет"}, вариантов: {cnt}'
            return f'Результат: {"Да" if found else "Нет"}'

        if p.get("plan_code"):
            code = p.get("plan_code")
            price = p.get("price") or p.get("amount")
            if price is not None:
                return f"План: {code} — {price} ⭐"
            return f"План: {code}"

        if p.get("amount") is not None:
            return f"Оплата: {p.get('amount')}"

        if p.get("error"):
            err = p.get("error")
            return f"Ошибка: {err}"

        if p:
            s = str(p)
            if len(s) > 200:
                return s[:197] + "…"
            return s

        return ""

    def payload_pretty(self) -> str:
        import json
        p = self.payload or {}
        try:
            return json.dumps(p, ensure_ascii=False, indent=2)
        except Exception:
            return str(p)

    def short_created(self) -> str:
        return timezone.localtime(self.created_at).strftime("%Y-%m-%d %H:%M")

    short_created.short_description = "Дата"
