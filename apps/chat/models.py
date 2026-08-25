"""
ChatMessage modeli — AI va mijoz o'rtasidagi dialog tarixi.

Edge-case qoidalari:
1. Idempotency: message_id + store kombinatsiyasi unique — dublikat yo'q
2. Data Retention: created_at asosida eski xabarlar tozalanadi
3. Soft Delete: is_deleted = True (BaseModel'dan)
4. Multi-tenant: store FK majburiy
"""
from django.db import models
from apps.core.models import BaseModel


class ChatMessage(BaseModel):
    """
    Bitta xabar (mijoz yoki AI tomonidan).

    Har bir xabar uchun:
    - message_id: platformadagi original ID (idempotency uchun)
    - role: kim yozgan (user/assistant/system)
    - content: xabar matni
    - is_processed: Celery task ishlov berdimi
    """

    class Role(models.TextChoices):
        USER = "user", "Mijoz"
        ASSISTANT = "assistant", "AI Javob"
        SYSTEM = "system", "Tizim"

    class Platform(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        TELEGRAM = "telegram", "Telegram"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        PROCESSING = "processing", "Qayta ishlanmoqda"
        COMPLETED = "completed", "Bajarildi"
        FAILED = "failed", "Xato"
        SKIPPED = "skipped", "O'tkazib yuborildi (dublikat)"

    # ── Multi-tenant bog'lanish ─────────────────────────────────
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="chat_messages",
        help_text="Qaysi do'konga tegishli xabar"
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="Xabar kimdan/kimga"
    )

    # ── Idempotency ────────────────────────────────────────────
    message_id = models.CharField(
        max_length=255,
        help_text="Platformadagi original xabar ID (idempotency kafolati)"
    )
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        help_text="Xabar qaysi platforma orqali keldi"
    )

    # ── Xabar mazmuni ──────────────────────────────────────────
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.USER,
        help_text="Xabar muallifi: user (mijoz) yoki assistant (AI)"
    )
    content = models.TextField(
        help_text="Xabar matni"
    )
    raw_payload = models.JSONField(
        blank=True,
        null=True,
        help_text="Platformadan kelgan to'liq JSON payload (debug uchun)"
    )

    # ── Qayta ishlash holati ───────────────────────────────────
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
        help_text="Celery task holati"
    )
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Celery task UUID (monitoring uchun)"
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Xato bo'lsa — xato xabari"
    )
    retry_count = models.IntegerField(
        default=0,
        help_text="Necha marta qayta urinilgan"
    )

    # ── AI metadata ─────────────────────────────────────────────
    tokens_used = models.IntegerField(
        blank=True,
        null=True,
        help_text="AI tomonidan sarflangan tokenlar soni"
    )
    ai_model_used = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Javob bergan AI modeli nomi"
    )

    class Meta:
        verbose_name = "Chat xabari"
        verbose_name_plural = "Chat xabarlari"
        ordering = ["created_at"]
        # Idempotency kafolati: bir xil xabar ikki marta saqlanmaydi
        unique_together = [("store", "message_id", "platform")]
        indexes = [
            models.Index(fields=["store", "customer"], name="msg_store_customer_idx"),
            models.Index(fields=["store", "created_at"], name="msg_store_created_idx"),
            models.Index(fields=["processing_status"], name="msg_status_idx"),
            models.Index(fields=["message_id", "platform"], name="msg_idempotency_idx"),
            # Data Retention uchun — eskirgan xabarlarni tezkor topish
            models.Index(fields=["created_at", "is_deleted"], name="msg_retention_idx"),
        ]

    def __str__(self):
        return (
            f"[{self.platform}] {self.role}: "
            f"{self.content[:50]}... → {self.store.name}"
        )

    @classmethod
    def is_duplicate(cls, store_id, message_id: str, platform: str) -> bool:
        """
        Idempotency tekshiruvi.
        Bu message_id ushbu platformada allaqachon mavjudmi?

        Returns:
            True — dublikat (skip kerak)
            False — yangi xabar (davom etish mumkin)
        """
        return cls.all_objects.filter(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
        ).exists()


class BroadcastCampaign(BaseModel):
    """
    Ommaviy Reklama / Xabarnoma Kampaniyasi modeli.
    Telegram SPAM Protection (rate_limit='25/s') bilan Celery orqali yuboriladi.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Qoralama"
        SENDING = "sending", "Yuborilmoqda"
        COMPLETED = "completed", "Yakunlandi"
        FAILED = "failed", "Xatolik"

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="broadcasts",
        help_text="Qaysi do'konning reklamasi"
    )
    title = models.CharField(
        max_length=255,
        help_text="Kampaniya nomi (masalan: Bahor Chegirmasi)"
    )
    message_text = models.TextField(
        help_text="Mijozlarga ommaviy yuboriladigan xabar matni"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text="Kampaniya holati"
    )
    total_recipients = models.IntegerField(default=0, help_text="Jami yuborilishi kerak bo'lgan mijozlar soni")
    sent_count = models.IntegerField(default=0, help_text="Muvaffaqiyatli yetib borgan xabarlar")
    failed_count = models.IntegerField(default=0, help_text="Yetib bormagan xabarlar")
    completed_at = models.DateTimeField(blank=True, null=True, help_text="Yakunlangan vaqti")

    class Meta:
        verbose_name = "Ommaviy Reklama Kampaniyasi"
        verbose_name_plural = "Ommaviy Reklama Kampaniyalari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} [{self.store.name}] → {self.sent_count}/{self.total_recipients}"
