from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponse
import csv
from typing import Iterable

from .models import BotEvent


@admin.register(BotEvent)
class BotEventAdmin(admin.ModelAdmin):
    # --- список ---
    list_display = (
        "short_created",
        "user_link",
        "event_label_ru",
        "payload_summary_col",
    )
    list_filter = ("event_type", "created_at")
    search_fields = ("user__telegram_id", "user__username", "payload")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    # --- форма просмотра ---
    readonly_fields = (
        "created_at",
        "user_link",
        "event_label_ru",
        "payload_pretty_display",
    )

    fieldsets = (
        ("Основное", {
            "fields": (
                "user",
                "event_type",
                "created_at",
            )
        }),
        ("Пользователь (удобно)", {
            "fields": (
                "user_link",
            )
        }),
        ("Payload", {
            "fields": (
                "payload_pretty_display",
            )
        }),
    )

    # ======================
    # Helpers для admin
    # ======================

    def short_created(self, obj: BotEvent) -> str:
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    short_created.short_description = "Дата"
    short_created.admin_order_field = "created_at"

    def user_link(self, obj: BotEvent) -> str:
        if not obj.user_id:
            return "-"

        try:
            url = reverse("admin:billing_telegramuser_change", args=[obj.user_id])
            title = f"{obj.user.username or '—'} ({obj.user.telegram_id})"
            return format_html('<a href="{}">{}</a>', url, title)
        except Exception:
            return f"{obj.user.username} ({obj.user.telegram_id})"

    user_link.short_description = "Пользователь"

    def event_label_ru(self, obj: BotEvent) -> str:
        return obj.get_event_label_ru()

    event_label_ru.short_description = "Событие"
    event_label_ru.admin_order_field = "event_type"

    def payload_summary_col(self, obj: BotEvent) -> str:
        s = obj.payload_summary()
        if not s:
            return "—"
        if len(s) > 80:
            return format_html('<span title="{}">{}…</span>', s, s[:77])
        return s

    payload_summary_col.short_description = "Детали"

    def payload_pretty_display(self, obj: BotEvent) -> str:
        txt = obj.payload_pretty()
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", txt)

    payload_pretty_display.short_description = "Payload (подробно)"

    # ======================
    # Actions
    # ======================

    actions = ["export_selected_events_csv"]

    def export_selected_events_csv(self, request, queryset: Iterable[BotEvent]):
        qs = queryset.order_by("created_at")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="bot_events.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Дата",
            "Telegram ID",
            "Username",
            "Событие",
            "Описание",
            "Payload",
        ])

        for e in qs:
            writer.writerow([
                e.created_at.isoformat(),
                e.user.telegram_id if e.user else "",
                e.user.username if e.user else "",
                e.get_event_label_ru(),
                e.payload_summary(),
                e.payload_pretty(),
            ])
        return response

    export_selected_events_csv.short_description = "Экспортировать выбранные события в CSV"
