from django.db import models


class GlassGroup(models.Model):
    external_id = models.CharField(
        "ID из Excel",
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Не менять. Используется для обновления группы при импорте из Excel. Например: G0001",
    )

    name = models.CharField("Название группы", max_length=255, unique=True)

    description = models.TextField("Описание", blank=True, default="")
    brands = models.CharField(
        "Бренды/линейки (через запятую)",
        max_length=255,
        blank=True,
        default="",
        help_text="Например: HOCO, Profit, Baseus",
    )

    is_active = models.BooleanField("Активна", default=True, db_index=True)

    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        verbose_name = "Группа стёкол"
        verbose_name_plural = "Группы стёкол"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Glass(models.Model):
    group = models.ForeignKey(
        GlassGroup,
        on_delete=models.CASCADE,
        related_name="glasses",
        verbose_name="Группа",
    )

    name = models.CharField("Название стекла", max_length=255, db_index=True)

    aliases_text = models.CharField(
        "Алиасы (через ; или |)",
        max_length=512,
        blank=True,
        default="",
        help_text="Например: a13; a13 5g; samsung a13",
    )

    is_active = models.BooleanField("Активно", default=True, db_index=True)

    class Meta:
        verbose_name = "Стекло"
        verbose_name_plural = "Стёкла"
        ordering = ["name"]
        unique_together = [("group", "name")]

    def __str__(self) -> str:
        return self.name


class GlassAlias(models.Model):
    glass = models.ForeignKey(
        Glass,
        on_delete=models.CASCADE,
        related_name="aliases",
        verbose_name="Стекло",
    )

    alias = models.CharField("Алиас", max_length=255, db_index=True)
    normalized_alias = models.CharField(
        "Нормализованный алиас",
        max_length=255,
        db_index=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Алиас стекла"
        verbose_name_plural = "Алиасы стёкол"
        ordering = ["alias"]
        unique_together = [("glass", "alias")]

    def save(self, *args, **kwargs):
        self.normalized_alias = " ".join((self.alias or "").strip().lower().split())
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.alias
