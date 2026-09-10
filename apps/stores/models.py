"""
Store (Do'kon) modeli — Multi-tenant tizimning asosi.

Har bir do'kon egasi o'zining Store obyektiga ega.
Barcha boshqa modellar (Customer, ChatMessage, Order)
shu Store'ga Foreign Key orqali bog'lanadi.
"""
from django.db import models
from django.contrib.auth.models import User
from apps.core.models import BaseModel


class Store(BaseModel):
    """
    Do'kon modeli — B2B SaaS tizimidagi har bir mijoz (tenant).

    Bir foydalanuvchi (User) faqat bitta do'konga ega bo'lishi kerak.
    Do'kon Instagram yoki Telegram orqali ishlashi mumkin.
    """

    class Platform(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        TELEGRAM = "telegram", "Telegram"
        BOTH = "both", "Instagram & Telegram"

    class SubscriptionPlan(models.TextChoices):
        FREE = "free", "Bepul"
        BASIC = "basic", "Asosiy"
        PRO = "pro", "Professional"
        ENTERPRISE = "enterprise", "Korporativ"

    class CategoryType(models.TextChoices):
        E_COMMERCE = "e_commerce", "E-commerce (Kiyim-kechak, kosmetika, do'konlar)"
        EDUCATION = "education", "Ta'lim (O'quv markazlari, kurslar)"
        SERVICES = "services", "Xizmat ko'rsatish (Go'zallik salonlari, klinikalar, va h.k.)"

    # ── Asosiy ma'lumotlar ──────────────────────────────────────
    owner = models.OneToOneField(
        User,
        on_delete=models.PROTECT,   # User o'chirilsa do'kon ham o'chmasin
        related_name="store",
        help_text="Do'kon egasi (Django User)"
    )
    name = models.CharField(
        max_length=255,
        help_text="Do'kon nomi (masalan: 'Zulfiya Fashion')"
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Do'kon tavsifi (frontend va AI uchun)"
    )
    phone_number = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="Operator telefon raqami (frontend Sozlamalar bo'limida ko'rsatiladi)"
    )
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        default=Platform.TELEGRAM,
        help_text="Qaysi platformada ishlaydi"
    )
    category_type = models.CharField(
        max_length=30,
        choices=CategoryType.choices,
        default=CategoryType.E_COMMERCE,
        help_text="Biznes sohasi/kategoriyasi"
    )

    # ── Instagram sozlamalari ──────────────────────────────────
    ig_page_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Instagram Page ID (Meta Graph API)"
    )
    ig_access_token = models.TextField(
        blank=True,
        null=True,
        help_text="Instagram long-lived access token (shifrlangan saqlash tavsiya etiladi)"
    )
    ig_token_expires_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Token muddati tugash vaqti"
    )

    # ── Telegram sozlamalari ───────────────────────────────────
    tg_bot_token = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Telegram Bot Token (@BotFather'dan olingan)"
    )
    tg_bot_username = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Bot username (masalan: @ZulfiyaShopBot)"
    )
    tg_owner_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Do'kon egasining shaxsiy Telegram chat_id (xabarnoma uchun)"
    )

    # ── AI sozlamalari ─────────────────────────────────────────
    ai_active = models.BooleanField(
        default=True,
        help_text="AI bot faolmi? False bo'lsa operator qo'lda javob beradi"
    )
    ai_system_prompt = models.TextField(
        default=(
            "Siz onlayn do'konning yordamchi botisiz. "
            "Mijozlarga do'rtona va professional tarzda javob bering. "
            "Buyurtma olishda mijozdan to'liq ism, telefon raqam va "
            "yetkazib berish manzilini so'rang."
        ),
        help_text="AI uchun tizim prompti — do'kon egasi bu yerga o'z ko'rsatmalarini yozadi"
    )
    ai_model = models.CharField(
        max_length=50,
        default="gemini-3.6-flash",
        help_text="Qaysi AI modeli ishlatilsin (gemini-3.6-flash va h.k.)"
    )
    ai_temperature = models.FloatField(
        default=0.7,
        help_text="AI kreativlik darajasi (0.0 — aniq, 1.0 — ijodiy)"
    )
    ai_max_tokens = models.IntegerField(
        default=1000,
        help_text="AI javobining maksimal uzunligi (token)"
    )

    # ── Obuna va limit ─────────────────────────────────────────
    subscription_plan = models.CharField(
        max_length=20,
        choices=SubscriptionPlan.choices,
        default=SubscriptionPlan.FREE,
        help_text="Obuna rejasi"
    )
    monthly_message_limit = models.IntegerField(
        default=500,
        help_text="Oylik maksimal xabar soni (tarif chegarasi)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Do'kon aktiv yoki to'xtatilgan"
    )

    class Meta:
        verbose_name = "Do'kon"
        verbose_name_plural = "Do'konlar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner"], name="store_owner_idx"),
            models.Index(fields=["is_active"], name="store_is_active_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.owner.username})"

    @property
    def has_instagram(self) -> bool:
        """Instagram ulangan va aktiv"""
        return bool(self.ig_page_id and self.ig_access_token)

    @property
    def has_telegram(self) -> bool:
        """Telegram ulangan va aktiv"""
        return bool(self.tg_bot_token)
