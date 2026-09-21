"""
Store (Do'kon) modeli — Multi-tenant tizimning asosi.

Har bir do'kon egasi o'zining Store obyektiga ega.
Barcha boshqa modellar (Customer, ChatMessage, Lead)
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
        help_text="Do'kon nomi (masalan: 'Najot Ta'lim')"
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
        default=CategoryType.EDUCATION,
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
        help_text="Bot username (masalan: @NajotTalimBot)"
    )
    tg_owner_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        # ⚠️ XAVFSIZLIK: bu maydonda avval unique cheklov yo'q edi — ikki
        # do'kon bir xil qiymatga ega bo'lsa, TelegramInitDataAuthentication
        # (apps/core/authentication.py) `.get(tg_owner_chat_id=...)` chaqirib,
        # `MultipleObjectsReturned` bilan qulab, haqiqiy do'kon egasini o'z
        # paneliga kira olmay qolishiga (cross-tenant DoS) sabab bo'lardi.
        # NULL qiymatlar (hali hech kim ulanmagan do'konlar) bundan
        # mustasno — faqat haqiqiy (bo'sh bo'lmagan) qiymatlar orasida
        # takrorlanishning oldi olinadi.
        help_text="Do'kon egasining shaxsiy Telegram chat_id (xabarnoma uchun)"
    )
    tg_group_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        # ⚠️ tg_owner_chat_id bilan bir xil xavfsizlik sababi: unique
        # cheklovsiz, ikki do'kon bir xil guruhga bog'lansa,
        # `Store.objects.get(tg_group_chat_id=...)` chaqirilganda
        # `MultipleObjectsReturned` bilan qulashi mumkin edi.
        help_text="Ushbu do'konga bog'langan Telegram guruh chat_id (agar bog'langan bo'lsa)"
    )
    group_spam_cleanup_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Guruhdagi reklama/spam xabarlarni (o'zga kanal havolasi, "
            "ko'plab tashqi havola, kanaldan forward, pul ishlash "
            "firibgarligi kabi) avtomatik o'chirish. ⚠️ Bot GURUHDA ADMIN "
            "va 'Xabarlarni o'chirish' huquqiga ega bo'lishi SHART — aks "
            "holda Telegram o'chirishga ruxsat bermaydi."
        )
    )

    # ── Bitrix24 integratsiyasi ─────────────────────────────────
    bitrix24_webhook_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Bitrix24 inbound webhook manzili (masalan: https://company.bitrix24.com/rest/1/xxxxxxxx/) — yangi lidlar avtomatik shu yerga yuboriladi"
    )

    # ── Google Sheets integratsiyasi ─────────────────────────────
    # ⚠️ Rasmiy Google Sheets API OAuth oqimi (Google Cloud loyihasi,
    # consent screen tasdiqlanishi) kichik SMB mijozlari uchun ortiqcha
    # murakkab — shu sabab Bitrix24 bilan BIR XIL, oddiy "webhook URL"
    # yondashuvi qo'llanildi: do'kon egasi o'z jadvalida kichik Apps
    # Script joylashtirib, uni Web App sifatida deploy qiladi va olingan
    # URL'ni shu yerga qo'yadi (apps/integrations/google_sheets.py'da
    # to'liq Apps Script namunasi bor).
    google_sheets_webhook_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Google Sheets Apps Script Web App manzili — yangi lidlar avtomatik shu yerga (qator sifatida) yuboriladi"
    )

    # ── AI sozlamalari ─────────────────────────────────────────
    ai_active = models.BooleanField(
        default=True,
        help_text="AI bot faolmi? False bo'lsa operator qo'lda javob beradi"
    )
    ai_system_prompt = models.TextField(
        default="",
        blank=True,
        help_text=(
            "AI uchun tizim prompti — do'kon egasi bu yerga o'z ko'rsatmalarini "
            "yozadi. Yangi biznes uchun ATAYLAB bo'sh boshlanadi (avval bu yerda "
            "e-commerce davridan qolgan 'onlayn do'kon ... yetkazib berish "
            "manzili' degan default matn bor edi — bu Education/Services "
            "pivotidan keyin ham hamon yangi har bir bizneste sukut bo'yicha "
            "ishlab turgan, mos kelmaydigan qoldiq edi)."
        )
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
        # ⚠️ BUG FIX: 1000 token bilan uzun sotuv matni + oxiridagi lid/buyurtma
        # JSON bloki ba'zan sig'may qolib, javob JSON o'rtasida kesilib ketardi —
        # bu esa kesilgan JSON mijozga xom (tozalanmagan) holda ko'rinishiga
        # olib kelgan edi (jonli testda kuzatildi). 1500 token qo'shimcha
        # zaxira beradi.
        default=1500,
        help_text="AI javobining maksimal uzunligi (token)"
    )

    # ── Follow-up (javobsiz qolgan mijozlarga avtomatik eslatma) ─
    follow_up_enabled = models.BooleanField(
        default=True,
        help_text="Javobsiz qolgan mijozlarga avtomatik follow-up eslatma yuborilsinmi?"
    )
    follow_up_delay_1_hours = models.PositiveIntegerField(
        default=6,
        help_text="Mijoz oxirgi xabaridan necha soat o'tgach BIRINCHI follow-up yuborilsin"
    )
    follow_up_delay_2_hours = models.PositiveIntegerField(
        default=18,
        help_text=(
            "BIRINCHI follow-up yuborilgandan necha soat o'tgach IKKINCHI "
            "(oxirgi) follow-up yuborilsin (mijozning asl sukutidan emas — "
            "standart 6+18=24 soat, ya'ni asl xabaridan taxminan 24 soat "
            "o'tib ikkinchi eslatma boradi)"
        )
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

    @property
    def has_bitrix24(self) -> bool:
        """Bitrix24 webhook ulangan"""
        return bool(self.bitrix24_webhook_url)

    @property
    def has_google_sheets(self) -> bool:
        """Google Sheets webhook ulangan"""
        return bool(self.google_sheets_webhook_url)

    @property
    def has_telegram_group(self) -> bool:
        """Telegram guruh bog'langan"""
        return bool(self.tg_group_chat_id)


class StoreStaffMember(BaseModel):
    """
    Do'kon egasi Telegram guruhida ishlaydigan xodimlar (masalan sotuv
    menejerlari) ro'yxati.

    ⚠️ Bu TO'LIQ jamoa/rol tizimi (TWA'ga kirish, ruxsatlar va h.k.) EMAS —
    faqat bitta aniq maqsad uchun: guruhda ishlaydigan xodimlarni AI'dan
    ajratish, shunda bot ularga ham (do'kon egasiga o'xshab) mijoz kabi
    sotuv taklifi/ma'lumot berishga urinmaydi. To'liq StoreMember/rol
    tizimi hali qurilmagan — real ehtiyoj chiqqanda alohida ishlanadi.
    """
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="staff_members",
        help_text="Qaysi do'konning xodimi"
    )
    tg_username = models.CharField(
        max_length=64,
        help_text="Xodimning Telegram @username'i (@ belgisisiz, kichik harflarda saqlanadi)"
    )
    full_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Xodimning ismi (ixtiyoriy, faqat ro'yxatda ko'rsatish uchun)"
    )

    class Meta:
        verbose_name = "Do'kon Xodimi"
        verbose_name_plural = "Do'kon Xodimlari"
        ordering = ["-created_at"]
        unique_together = [("store", "tg_username")]

    def __str__(self):
        return f"@{self.tg_username} ({self.store.name})"

    def save(self, *args, **kwargs):
        self.tg_username = self.tg_username.lstrip("@").strip().lower()
        super().save(*args, **kwargs)
