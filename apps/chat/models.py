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
    bot_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Xabar qaysi bot tokeni orqali kelgan (idempotency kafolati). "
            "Bot almashtirilganda (masalan WarmixAi_bot → LeadNodeBot) "
            "Telegram har bir bot uchun message_id'ni 1'dan qaytadan "
            "boshlaydi — shu bayroqsiz eski botdagi kichik ID'lar yangi "
            "botdagi xabarlarga xato ravishda 'dublikat' deb urib qolardi."
        )
    )
    chat_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Xabar qaysi Telegram chat/guruhdan kelgan (idempotency "
            "kafolati). Telegram'da message_id faqat (bot, chat) juftligi "
            "ichida unikal — masalan guruh o'chirilib qayta yaratilganda "
            "yangi guruhning xabar-ID hisoblagichi yana 1'dan boshlanadi, "
            "shu bayroqsiz eski (o'chirilgan) guruhdagi kichik ID'lar "
            "yangi guruhdagi xabarlarga xato ravishda 'dublikat' deb "
            "urib, javobsiz qoldirardi (jonli testda aniqlandi)."
        )
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
    media_url = models.TextField(
        blank=True,
        default='',
        help_text="Media fayl URL adresi"
    )
    audio_url = models.TextField(
        blank=True,
        default='',
        help_text="Ovozli xabar URL adresi"
    )
    audio_duration = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Ovozli xabar davomiyligi (masalan: 0:15)"
    )
    is_group_message = models.BooleanField(
        default=False,
        db_index=True,
        # ⚠️ Bir xil Customer shaxsiy chatda ham, do'konning bog'langan
        # Telegram guruhida ham yozishi mumkin — suhbat tarixi (AI
        # kontekst uchun) ikkalasini ARALASHTIRMASLIGI kerak, aks holda
        # shaxsiy chatdagi maxfiy tafsilotlar AI orqali ommaviy guruhga
        # "sizib chiqishi" mumkin edi. Shu bayroq ikkalasini ajratadi.
        help_text="Ushbu xabar do'konga bog'langan Telegram guruhidan keldimi (shaxsiy chat emas)"
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
    latency_ms = models.IntegerField(
        blank=True,
        null=True,
        help_text=(
            "Mijoz xabari qabul qilingandan (webhook) AI javobi tayyor "
            "bo'lgunga qadar o'tgan vaqt (millisekund) — faqat AI javob "
            "xabarlarida to'ldiriladi"
        )
    )

    class Meta:
        verbose_name = "Chat xabari"
        verbose_name_plural = "Chat xabarlari"
        ordering = ["created_at"]
        # Idempotency kafolati: bir xil xabar ikki marta saqlanmaydi.
        # ⚠️ `customer` shart — Telegram/Instagram'da message_id faqat BITTA
        # suhbat ichida unikal, turli mijozlarning suhbatlarida bir xil
        # kichik raqamlar (1, 2, 3...) tabiiy qaytarilaveradi. Faqat
        # (store, message_id, platform) bo'yicha tekshirish boshqa mijozning
        # xabarini yolg'on dublikat deb hisoblab, javobsiz qoldirar edi.
        # `bot_token` va `chat_id` ham shart — sabab yuqoridagi maydon izohlarida.
        unique_together = [("store", "customer", "message_id", "platform", "bot_token", "chat_id")]
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
    def is_duplicate(cls, store_id, message_id: str, platform: str, sender_id: str, bot_token: str = "", chat_id: str = "") -> bool:
        """
        Idempotency tekshiruvi.
        Bu message_id ushbu (do'kon, mijoz, platforma, bot, chat) uchun allaqachon mavjudmi?

        ⚠️ `sender_id` (customer__platform_user_id) shart — message_id faqat
        bitta suhbat ichida unikal, shuning uchun turli mijozlarni ajratish
        kerak (yuqoridagi Meta.unique_together izohiga qarang).

        ⚠️ `bot_token` ham shart (Telegram uchun) — bot almashtirilganda
        Telegram message_id'ni yangi botning suhbati uchun 1'dan qaytadan
        boshlaydi, shuning uchun tokenlarni ajratmasak eski botdagi past
        raqamli xabarlar yangi botdagi haqiqiy yangi xabarlarga urilib,
        ularni xato "dublikat" deb bloklab qo'yishi mumkin edi.

        ⚠️ `chat_id` ham shart — xuddi shu sababga o'xshab, Telegram
        guruh o'chirilib qayta yaratilganda ham (yoki mijoz turli
        guruhlarda yozganda) message_id qaytadan 1'dan boshlanadi. Bu
        holat jonli testda aynan shu tarzda aniqlandi: eski (o'chirilgan)
        guruhdagi past raqamli xabar yangi guruhdagi haqiqiy yangi
        xabarga urilib, uni xato "dublikat" deb bloklab qo'ygan edi.

        Returns:
            True — dublikat (skip kerak)
            False — yangi xabar (davom etish mumkin)
        """
        return cls.all_objects.filter(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
            customer__platform_user_id=sender_id,
            bot_token=bot_token,
            chat_id=chat_id,
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
