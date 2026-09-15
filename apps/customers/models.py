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
    total_leads = models.IntegerField(
        default=0,
        help_text="Jami lidlar soni (kesh — tez hisoblash uchun)"
    )
    last_message_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Oxirgi xabar vaqti"
    )
    ai_active = models.BooleanField(
        default=True,
        help_text="Ushbu mijoz uchun AI bot faolmi? False bo'lsa operator qo'lda javob beradi"
    )
    is_blocked = models.BooleanField(
        default=False,
        help_text="Mijoz bloklanganmi? True bo'lsa bot va operator xabarlari to'xtatiladi"
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
        display_name: str = None,
    ) -> tuple["Customer", bool]:
        """
        Platformadan kelgan mijozni topadi yoki yangi yaratadi.
        Multi-tenant xavfsizligini ta'minlaydi.

        Returns:
            (Customer, created: bool)
        """
        # ⚠️ BUG FIX: avval `full_name` yangi mijoz yaratilganda ham
        # hech qachon o'rnatilmasdi (faqat `username`) — shu sabab Inbox'da
        # ismi o'rniga @username chiqib qolardi. Endi profildagi ism
        # (display_name) mavjud bo'lsa, yangi mijoz uchun boshidanoq
        # `full_name`ga yoziladi.
        return cls.objects.get_or_create(
            store=store,
            platform=platform,
            platform_user_id=str(platform_user_id),
            defaults={"username": username, "full_name": display_name or None},
        )


class CustomerSession(BaseModel):
    """
    Single Master Bot Model uchun foydalanuvchining hozirgi aktiv do'kon sessiyasi.
    Deep-link /start store_123 bosilganida avtomatik yangilanadi va o'tkaziladi.
    """
    platform_user_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Foydalanuvchi Telegram ID"
    )
    active_store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="user_sessions",
        help_text="Hozirgi muloqot qilayotgan do'koni"
    )

    class Meta:
        verbose_name = "Mijoz Sessiyasi"
        verbose_name_plural = "Mijoz Sessiyalari"

    def __str__(self):
        return f"User {self.platform_user_id} → {self.active_store.name}"
