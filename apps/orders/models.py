"""
Lead (Lid) modeli — Multi-tenant, Soft Delete.

AI mijozdan ism va telefon raqamini olgandan so'ng avtomatik yaratiladi,
do'kon egasiga xabar yuboriladi, va (keyingi bosqichda) Excel/Bitrix24'ga
eksport qilinadi. Bu loyiha ICHKI buyurtma/holat boshqaruv tizimi EMAS —
faqat lidni yig'ish va aniq/sovuq deb belgilash uchun.
"""
from django.db import models
from apps.core.models import BaseModel


class Lead(BaseModel):
    """
    Lid (potensial mijoz) modeli.

    Yaratilish jarayoni:
    1. AI mijozdan ism, telefon va (ixtiyoriy) qiziqqan kurs/xizmatni oladi
    2. JSON parse qilinadi
    3. Yangi Lead yaratiladi (lead_status=UNQUALIFIED, keyin AI baholaydi)
    4. Do'kon egasiga Telegram xabarnomasi yuboriladi
    5. (Keyingi bosqich) Excel yoki Bitrix24'ga eksport qilinadi

    ⚠️ Bu yerda ATAYLAB yo'q: buyurtma holati (yangi/tasdiqlangan/yakunlangan),
    summasi, yetkazib berish manzili — bular e-commerce/CRM tushunchalari,
    loyiha pivotidan keyin ATAYLAB olib tashlangan.
    """

    class LeadStatus(models.TextChoices):
        UNQUALIFIED = "unqualified", "Aniqlanmagan"
        HOT = "hot", "Issiq"
        WARM = "warm", "Iliq"
        COLD = "cold", "Sovuq"

    class Source(models.TextChoices):
        PRIVATE_CHAT = "private_chat", "Shaxsiy chat"
        GROUP = "group", "Telegram guruh"
        AD = "ad", "Reklama"

    class ExportStatus(models.TextChoices):
        NONE = "none", "Eksport qilinmagan"
        EXCEL = "excel", "Excel"
        BITRIX24 = "bitrix24", "Bitrix24"

    class Platform(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        TELEGRAM = "telegram", "Telegram"

    # ── Multi-tenant bog'lanish ─────────────────────────────────
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="leads",
        help_text="Qaysi do'konga tegishli lid"
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,   # Mijoz o'chirilsa lid yo'qolmasin
        related_name="leads",
        help_text="Lidni bergan mijoz"
    )

    # ── Lid raqami ─────────────────────────────────────────────
    lead_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Insonlarga qulay lid raqami (masalan: LEAD-20260915-00001)"
    )
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        help_text="Lid qaysi platforma orqali keldi"
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.PRIVATE_CHAT,
        help_text="Lid qaysi kanaldan kelgani (shaxsiy chat, guruh, reklama)"
    )

    # ── Mijoz ma'lumotlari (AI tomonidan olingan) ──────────────
    customer_full_name = models.CharField(
        max_length=255,
        help_text="Mijozning ism-familyasi"
    )
    customer_phone = models.CharField(
        max_length=20,
        help_text="Mijozning telefon raqami"
    )
    interested_course = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="interested_leads",
        help_text="Mijoz qiziqqan kurs/mahsulot/xizmat (aniqlangan bo'lsa)"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Qo'shimcha izoh (AI yoki egasi tomonidan)"
    )

    # ── Baholash (AI qiladi) ────────────────────────────────────
    lead_status = models.CharField(
        max_length=20,
        choices=LeadStatus.choices,
        default=LeadStatus.UNQUALIFIED,
        db_index=True,
        help_text="AI suhbat asosida baholagan lid holati"
    )

    # ── Tashqi CRM eksport ──────────────────────────────────────
    # ⚠️ BUG FIX: `exported_to` bitta qiymatli maydon ("none"/"excel"/
    # "bitrix24") — ya'ni "Excel'ga yuklab olindi" va "Bitrix24'ga
    # yuborildi" bir-birini USTIDAN YOZIB QO'YARDI. Jonli holatda
    # aniqlandi: ega avval "Excel'ni chatga yuborish" tugmasini bossa
    # (bu BARCHA lidlarni `exported_to="excel"` deb belgilaydi), keyin
    # Bitrix24 ulasa — pastdagi avtomatik "qayta urinish" vazifasi faqat
    # `exported_to="none"` lidlarni qidirgani uchun, bu lidlar Bitrix24'ga
    # UMUMAN yuborilmasdi, garchi haqiqatda hech qachon yuborilmagan
    # bo'lsa ham. `exported_to`/`exported_at` ko'rsatish (TWA'da "qayerga
    # eksport qilingan" degan umumiy ma'lumot) uchun saqlanib qolgan,
    # lekin Bitrix24'ning haqiqiy, MUSTAQIL holati endi pastdagi
    # `bitrix24_synced_at`da kuzatiladi (xuddi `google_sheets_synced_at`
    # kabi) — shu ikkisi bir-biriga butunlay bog'liq emas.
    exported_to = models.CharField(
        max_length=20,
        choices=ExportStatus.choices,
        default=ExportStatus.NONE,
        help_text="Lid oxirgi marta qayerga eksport qilingani (ko'rsatish uchun, retry mantig'i uchun emas)"
    )
    exported_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Oxirgi eksport vaqti"
    )
    bitrix24_synced_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Bitrix24'ga muvaffaqiyatli yuborilgan vaqt (bo'sh — hali yuborilmagan) — Excel eksportidan mustaqil"
    )

    # ── AI xabar bog'lanishi ───────────────────────────────────
    source_message = models.ForeignKey(
        "chat.ChatMessage",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="leads",
        help_text="Lidni yaratgan AI xabari"
    )

    # ── Xabarnoma ──────────────────────────────────────────────
    owner_notified = models.BooleanField(
        default=False,
        help_text="Do'kon egasiga Telegram xabarnomasi yuborilganmi"
    )
    owner_notified_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Xabarnoma yuborilgan vaqt"
    )

    # ⚠️ `exported_to`/`exported_at` Bitrix24'ning "so'nggi eksport"
    # holatini bildiradi (retry task shu maydonga qarab ishlaydi) — Google
    # Sheets shu bilan BIR VAQTDA, MUSTAQIL ravishda ham ulangan bo'lishi
    # mumkin (do'kon ikkalasini ham yoqib qo'yishi mumkin), shuning uchun
    # bitta umumiy enum o'rniga alohida, `owner_notified_at` bilan bir xil
    # uslubdagi maydon ishlatiladi: bo'sh — hali yuborilmagan/muvaffaqiyat-
    # siz, to'ldirilgan — muvaffaqiyatli yuborilgan vaqt.
    google_sheets_synced_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Google Sheets'ga muvaffaqiyatli yuborilgan vaqt (bo'sh — hali yuborilmagan)"
    )

    class Meta:
        verbose_name = "Lid"
        verbose_name_plural = "Lidlar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "lead_status"], name="lead_store_status_idx"),
            models.Index(fields=["store", "created_at"], name="lead_store_created_idx"),
            models.Index(fields=["store", "customer"], name="lead_store_customer_idx"),
            models.Index(fields=["lead_number"], name="lead_number_idx"),
            models.Index(fields=["owner_notified"], name="lead_notified_idx"),
        ]

    def __str__(self):
        return f"{self.lead_number} — {self.customer_full_name} [{self.get_lead_status_display()}]"

    def save(self, *args, **kwargs):
        """Lid raqamini avtomatik generatsiya qiladi"""
        if not self.lead_number:
            self.lead_number = self._generate_lead_number()
        super().save(*args, **kwargs)

    def _generate_lead_number(self) -> str:
        """
        Insonlarga qulay lid raqami hosil qiladi.
        Format: LEAD-YYYYMMDD-XXXXX
        """
        from django.utils import timezone
        import random
        import string
        date_str = timezone.now().strftime("%Y%m%d")
        random_part = "".join(random.choices(string.digits, k=5))
        return f"LEAD-{date_str}-{random_part}"
