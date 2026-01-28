from __future__ import annotations

from django.db import models
from django.utils import timezone


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=64, blank=True, default="")
    first_name = models.CharField(max_length=128, blank=True, default="")
    last_name = models.CharField(max_length=128, blank=True, default="")

    premium_until = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram user"
        verbose_name_plural = "Telegram users"

    def __str__(self) -> str:
        return f"{self.telegram_id} @{self.username}".strip()

    @property
    def is_premium_active(self) -> bool:
        if not self.premium_until:
            return False
        return self.premium_until > timezone.now()


class StarPayment(models.Model):
    """
    Запись факта оплаты Stars.
    telegram_payment_charge_id — главный уникальный ключ для идемпотентности.
    """
    STATUS_SUCCEEDED = "succeeded"
    STATUS_REFUNDED = "refunded"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="star_payments",
    )

    telegram_payment_charge_id = models.CharField(max_length=128, unique=True, db_index=True)
    provider_payment_charge_id = models.CharField(max_length=128, blank=True, default="")

    currency = models.CharField(max_length=8, db_index=True)  # "XTR"
    total_amount = models.IntegerField()  # количество Stars

    invoice_payload = models.CharField(max_length=128, db_index=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SUCCEEDED, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Star payment"
        verbose_name_plural = "Star payments"

    def __str__(self) -> str:
        return f"{self.user.telegram_id} {self.total_amount} {self.currency} {self.status}"


class PremiumPlan(models.Model):
    """
    План можно держать в БД (удобно менять цену/дни без деплоя).
    Пока оставим 1 план: premium_30.
    """
    code = models.CharField(max_length=32, unique=True, db_index=True)  # например "premium_30"
    title = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True, default="")
    price_stars = models.IntegerField()
    duration_days = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Premium plan"
        verbose_name_plural = "Premium plans"

    def __str__(self) -> str:
        return f"{self.code} ({self.price_stars} XTR / {self.duration_days}d)"
