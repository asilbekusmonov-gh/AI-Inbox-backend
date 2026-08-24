"""
Customer (Mijoz) modeli — Multi-tenant.

Har bir mijoz bitta do'konga tegishli.
Bir xil platform_user_id ham turli do'konlarda
turli Customer bo'lishi mumkin (multi-tenant).
"""
from django.db import models
from apps.core.models import BaseModel


class Customer(BaseModel):
    """
    Do'kon mijozi.

    Bir mijoz Instagram yoki Telegram orqali yozganda,
    avval platformadagi user_id bo'yicha qidiriladi.
    Topilmasa yangi Customer yaratiladi.

    Multi-tenant: unique_together = (store, platform, platform_user_id)
    Ya'ni bir xil Telegram user bitta do'konning mijozi bo'ladi,
    boshqa do'kondagi xuddi shunday user_id — boshqa Customer.
    """

    class Platform(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        TELEGRAM = "telegram", "Telegram"

    # ── Multi-tenant bog'lanish ─────────────────────────────────
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="customers",
        help_text="Qaysi do'konning mijozi"
    )

    # ── Platform identifikatsiya ───────────────────────────────
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        help_text="Qaysi platforma orqali kelgan"
    )
    platform_user_id = models.CharField(
        max_length=100,
        help_text="Platformadagi foydalanuvchi ID (TG user_id yoki IG sender_id)"
    )

    # ── Shaxsiy ma'lumotlar (buyurtma jarayonida to'ldiriladi) ─
    full_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="To'liq ism-familya (AI orqali olingan)"
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Telefon raqam (+998901234567 formatida)"
    )
    username = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Platformadagi @username (ixtiyoriy)"
    )

    # ── Statistika ─────────────────────────────────────────────
    total_orders = models.IntegerField(
        default=0,
        help_text="Jami buyurtmalar soni (kesh — tez hisoblash uchun)"
    )
    last_message_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Oxirgi xabar vaqti"
    )

    class Meta:
        verbose_name = "Mijoz"
        verbose_name_plural = "Mijozlar"
        # Bir platformada bir xil user_id faqat bitta do'konda bitta Customer
        unique_together = [("store", "platform", "platform_user_id")]
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(fields=["store", "platform"], name="customer_store_platform_idx"),
            models.Index(fields=["store", "platform_user_id"], name="customer_store_user_idx"),
            models.Index(fields=["phone_number"], name="customer_phone_idx"),
        ]

    def __str__(self):
        name = self.full_name or self.username or f"ID:{self.platform_user_id}"
        return f"{name} [{self.platform}] → {self.store.name}"

    @classmethod
    def get_or_create_from_platform(
        cls,
        store,
        platform: str,
        platform_user_id: str,
        username: str = None,
    ) -> tuple["Customer", bool]:
        """
        Platformadan kelgan mijozni topadi yoki yangi yaratadi.
        Multi-tenant xavfsizligini ta'minlaydi.

        Returns:
            (Customer, created: bool)
        """
        return cls.objects.get_or_create(
            store=store,
            platform=platform,
            platform_user_id=str(platform_user_id),
            defaults={"username": username},
        )
