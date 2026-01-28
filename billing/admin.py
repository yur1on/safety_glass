from django.contrib import admin
from .models import TelegramUser, StarPayment, PremiumPlan


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username", "premium_until", "created_at", "updated_at")
    search_fields = ("telegram_id", "username", "first_name", "last_name")
    ordering = ("-updated_at",)


@admin.register(StarPayment)
class StarPaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "total_amount", "currency", "status", "telegram_payment_charge_id", "created_at")
    search_fields = ("telegram_payment_charge_id", "invoice_payload", "user__telegram_id", "user__username")
    ordering = ("-created_at",)


@admin.register(PremiumPlan)
class PremiumPlanAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "price_stars", "duration_days", "is_active", "created_at")
    search_fields = ("code", "title")
    ordering = ("code",)
