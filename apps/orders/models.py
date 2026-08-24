"""
Order (Buyurtma) modeli — Multi-tenant, Soft Delete.

AI mijozdan ism, raqam va manzil olgandan so'ng
avtomatik yaratiladi va do'kon egasiga xabar yuboriladi.
"""
from django.db import models
from apps.core.models import BaseModel


class Order(BaseModel):
    """
    Buyurtma modeli.

    Yaratilish jarayoni:
    1. AI mijozdan to'liq ma'lumot oladi
    2. JSON parse qilinadi
    3. Yangi Order yaratiladi (status=NEW)
    4. Do'kon egasiga Telegram xabarnomasi yuboriladi
    5. Egasi TWA'da buyurtmani ko'rib, holatini yangilaydi
    """

    class Status(models.TextChoices):
        NEW = "new", "Yangi"
        CONFIRMED = "confirmed", "Tasdiqlangan"
        PROCESSING = "processing", "Tayyorlanmoqda"
        SHIPPED = "shipped", "Yo'lda"
        DELIVERED = "delivered", "Yetkazildi"
        CANCELLED = "cancelled", "Bekor qilindi"
        REFUNDED = "refunded", "Qaytarildi"

    class Platform(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        TELEGRAM = "telegram", "Telegram"

    # ── Multi-tenant bog'lanish ─────────────────────────────────
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="orders",
        help_text="Qaysi do'konga tegishli buyurtma"
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,   # Mijoz o'chirilsa buyurtma yo'qolmasin
        related_name="orders",
        help_text="Buyurtma bergan mijoz"
    )

    # ── Buyurtma raqami ────────────────────────────────────────
    order_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Insonlarga qulay buyurtma raqami (masalan: ORD-2024-001)"
    )
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        help_text="Buyurtma qaysi platforma orqali keldi"
    )

    # ── Yetkazib berish ma'lumotlari (AI tomonidan olingan) ────
    customer_full_name = models.CharField(
        max_length=255,
        help_text="Buyurtmadagi ism-familya"
    )
    customer_phone = models.CharField(
        max_length=20,
        help_text="Buyurtmadagi telefon raqam"
    )
    delivery_address = models.TextField(
        help_text="Yetkazib berish manzili"
    )

    # ── Buyurtma detallari ─────────────────────────────────────
    items = models.JSONField(
        default=list,
        help_text=(
            "Buyurtma elementlari ro'yxati. "
            "Format: [{'name': 'Mahsulot', 'qty': 1, 'price': 50000}]"
        )
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Qo'shimcha izoh (mijoz yoki egasi tomonidan)"
    )

    # ── Moliyaviy ──────────────────────────────────────────────
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Jami summa (so'm)"
    )
    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Yetkazib berish narxi"
    )

    # ── Holat ──────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
        help_text="Buyurtma holati"
    )
    status_changed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Holat oxirgi o'zgargan vaqt"
    )

    # ── AI xabar bog'lanishi ───────────────────────────────────
    source_message = models.ForeignKey(
        "chat.ChatMessage",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="orders",
        help_text="Buyurtmani yaratgan AI xabari"
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

    class Meta:
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "status"], name="order_store_status_idx"),
            models.Index(fields=["store", "created_at"], name="order_store_created_idx"),
            models.Index(fields=["store", "customer"], name="order_store_customer_idx"),
            models.Index(fields=["order_number"], name="order_number_idx"),
            models.Index(fields=["owner_notified"], name="order_notified_idx"),
        ]

    def __str__(self):
        return f"{self.order_number} — {self.customer_full_name} [{self.status}]"

    def save(self, *args, **kwargs):
        """Buyurtma raqamini avtomatik generatsiya qiladi"""
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    def _generate_order_number(self) -> str:
        """
        Insonlarga qulay buyurtma raqami hosil qiladi.
        Format: ORD-YYYYMMDD-XXXXX
        """
        from django.utils import timezone
        import random
        import string
        date_str = timezone.now().strftime("%Y%m%d")
        random_part = "".join(random.choices(string.digits, k=5))
        return f"ORD-{date_str}-{random_part}"

    def update_status(self, new_status: str):
        """
        Buyurtma holatini yangilaydi va vaqtni qayd etadi.
        Bevosita .status = ... ga yozmang — bu metoddan foydalaning.
        """
        from django.utils import timezone
        self.status = new_status
        self.status_changed_at = timezone.now()
        self.save(update_fields=["status", "status_changed_at", "updated_at"])
