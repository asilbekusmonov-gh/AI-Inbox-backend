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
    follow_up_stage = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Javobsiz qolgan mijozga yuborilgan avtomatik follow-up "
            "bosqichi: 0=hali yuborilmagan, 1=birinchi yuborilgan, "
            "2=ikkinchi (oxirgi) yuborilgan. Mijoz yangi xabar yozganda "
            "0'ga qaytariladi."
        )
    )
    follow_up_last_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text=(
            "Oxirgi follow-up bosqichi qachon yuborilgani — keyingi "
            "bosqich shundan buyon o'tgan vaqtga qarab hisoblanadi "
            "(mijozning ASL sukut vaqtiga emas), aks holda ancha oldin "
            "jim qolgan mijozga BIR XIL vazifa ishga tushganda ketma-ket "
            "ikkala bosqich birdaniga yuborilib ketishi mumkin edi."
        )
    )
    follow_up_declined = models.BooleanField(
        default=False,
        help_text=(
            "Mijoz follow-up eslatmasiga aniq rad javobi berganmi "
            "(masalan 'yo'q', 'kerak emas')? True bo'lsa: (1) keyingi "
            "avtomatik follow-up bosqichlari yuborilmaydi (spam bo'lmasin "
            "uchun), (2) mijoz keyingi bekorchi xabarlariga AI javob "
            "bermaydi (token tejash uchun) — TO'ki mijoz haqiqiy qiziqish "
            "bildirmaguncha (shunda avtomatik False'ga qaytadi va AI "
            "odatdagidek javob beradi). apps/webhooks/tasks.py'da "
            "boshqariladi."
        )
    )
    ai_active = models.BooleanField(
        default=True,
        help_text="Ushbu mijoz uchun AI bot faolmi? False bo'lsa operator qo'lda javob beradi"
    )
    is_blocked = models.BooleanField(
        default=False,
        help_text="Mijoz bloklanganmi? True bo'lsa bot va operator xabarlari to'xtatiladi"
    )
    # ⚠️ BUG FIX: avval "o'qildi" holati faqat FRONTEND xotirasida
    # (bir dumaloq JS Map, `readChatsRef`) saqlanardi — sahifa yopilib
    # qayta ochilganda (yoki reload qilinganda) bu xotira butunlay
    # yo'qolib, unread_count backend'dagi eski qiymatga qaytib ketardi
    # (jonli holatda aniqlandi: Inbox'da o'qib chiqilgan xabar reload
    # qilingandan keyin yana "o'qilmagan" bo'lib qolib ketardi). Endi
    # operator qachon o'qiganini BAZADA saqlaymiz — ChatThreadListView
    # unread_count'ni shu vaqtdan keyingi mijoz xabarlari soni sifatida
    # hisoblaydi (AI javobidan keyin ham, operator o'qishidan keyin ham).
    operator_last_read_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Operator ushbu mijoz bilan suhbatni oxirgi marta ochib o'qigan vaqti"
    )

    # ── Sotuv suhbati holati (AI'ning har bir javobi bilan yangilanadi) ──
    # ⚠️ AI endi shunchaki FAQ botga o'xshab savolga javob berib
    # qo'ymaydi — tajribali sotuv menejeri kabi suhbatni bosqichma-bosqich
    # (CONTACT → CONTEXT → DISCOVERY → QUALIFICATION → CTA) olib boradi.
    # Bu maydonlar AI'ning HAR bir javobida (apps/chat/ai_service.py'dagi
    # "suhbat_holati" JSON bloki orqali) yangilanadi va KEYINGI xabarda
    # system promptga qaytarib beriladi — shunda AI mijoz allaqachon
    # aytgan narsalarni (maqsad, daraja, byudjet tashvishi) qayta-qayta
    # so'ramaydi, va ro'yxatdan o'tish havolasini faqat mijoz haqiqatan
    # tayyor bo'lganda (yuqori "lead_score"da) taklif qiladi.
    class ConversationStage(models.TextChoices):
        CASUAL = "casual", "Oddiy muloqot"
        INFORMATION = "information", "Ma'lumot so'ramoqda"
        INTEREST = "interest", "Qiziqish bildirmoqda"
        DISCOVERY = "discovery", "Ehtiyoji aniqlanmoqda"
        QUALIFICATION = "qualification", "Malakalashtirilmoqda"
        HIGH_INTENT = "high_intent", "Yuqori xarid niyati"
        OBJECTION = "objection", "E'tiroz bildirmoqda"
        READY_TO_CONVERT = "ready_to_convert", "Ro'yxatdan o'tishga tayyor"
        REGISTERED = "registered", "Ro'yxatdan o'tgan (lead)"
        HUMAN_HANDOFF = "human_handoff", "Operatorga o'tkazilgan"

    conversation_stage = models.CharField(
        max_length=30,
        choices=ConversationStage.choices,
        default=ConversationStage.CASUAL,
        help_text="AI aniqlagan suhbat bosqichi — CTA (ro'yxatdan o'tish havolasi) shu asosida beriladi"
    )
    lead_score = models.PositiveSmallIntegerField(
        default=0,
        help_text="AI baholagan xarid niyati darajasi, 0-100 (0-20 oddiy, 21-40 qiziqish, 41-60 faol qiziqish, 61-80 malakali lid, 81-100 yuqori niyat)"
    )
    conversation_memory = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "AI suhbat davomida bilib olgan tafsilotlar (masalan: goal, "
            "experience_level, interested_product, budget_concern, "
            "preferred_schedule, objections) — keyingi xabarlarda AI'ga "
            "qaytarib beriladi, xuddi shu narsalarni QAYTA SO'RAMASLIGI uchun."
        )
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

    class EntryMode(models.TextChoices):
        REGISTER = "register", "Ro'yxatdan o'tish (tez yo'l)"

    # ⚠️ Guruhda "juda issiq" mijozga ko'rsatilgan "Ro'yxatdan o'tish"
    # havolasi (/start register_<uuid>) orqali kirganini belgilaydi —
    # shaxsiy chatda AI oddiy savol-javobni qaytadan boshlamay, darhol
    # ism+telefon so'rashga o'tishi uchun (apps/chat/ai_service.py).
    # Birinchi AI javobidan so'ng tozalanadi (bir martalik signal).
    entry_mode = models.CharField(
        max_length=20,
        choices=EntryMode.choices,
        blank=True,
        default="",
        help_text="Oxirgi deep-link qaysi maxsus kirish rejimini bildirgani (bo'sh — oddiy kirish)",
    )

    # ⚠️ Lid manbasini aniq kuzatish uchun (qaysi GURUH va qaysi MAVZU
    # bo'yicha "Ro'yxatdan o'tish" havolasi ko'rsatilgan) — mijoz hali
    # /start bosmasdan, guruhdagi AI javobi shu havolani yuborgan ZAHOTI
    # o'rnatiladi (apps/webhooks/tasks.py), keyinroq Lead yaratilganda
    # uning "notes" maydoniga qo'shiladi va shu yerdan tozalanadi.
    source_group_chat_id = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Qaysi Telegram guruhidan 'Ro'yxatdan o'tish' havolasi bosilgani",
    )
    source_context = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Guruhda qaysi mavzu/kurs haqida gap ketgani (qisqa, lid notes'iga qo'shish uchun)",
    )

    class Meta:
        verbose_name = "Mijoz Sessiyasi"
        verbose_name_plural = "Mijoz Sessiyalari"

    def __str__(self):
        return f"User {self.platform_user_id} → {self.active_store.name}"
