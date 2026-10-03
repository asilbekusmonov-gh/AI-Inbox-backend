"""
Store Serializers — DRF

Frontend ↔ Backend field mapping:
  - telegram_connected  ← has_telegram (property)
  - instagram_connected ← has_instagram (property)
  - phone_number        ← phone_number (new field)
  - ai_active           ← ai_active (new field)
  - description         ← description (new field)
"""
from rest_framework import serializers
from .models import Store, StoreStaffMember


class StoreSerializer(serializers.ModelSerializer):
    """
    Do'kon ma'lumotlari va AI prompt sozlamalari serializeri.
    Frontend ChatThread va KPI komponentlari kutadigan formatda qaytaradi.
    """
    # Frontend "telegram_connected" / "instagram_connected" nomlarini kutadi
    telegram_connected = serializers.SerializerMethodField()
    instagram_connected = serializers.SerializerMethodField()
    bitrix24_connected = serializers.SerializerMethodField()
    google_sheets_connected = serializers.SerializerMethodField()
    telegram_group_connected = serializers.SerializerMethodField()
    own_bot_connected = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "description",
            "phone_number",
            "platform",
            "category_type",
            "cta_type",
            "ai_active",
            "ai_system_prompt",
            "ai_model",
            "ai_temperature",
            "ai_max_tokens",
            "working_hours",
            "faq_items",
            "subscription_plan",
            "monthly_message_limit",
            "is_active",
            "telegram_connected",
            "instagram_connected",
            "bitrix24_connected",
            "google_sheets_connected",
            "telegram_group_connected",
            "group_spam_cleanup_enabled",
            "tg_bot_username",
            "own_bot_connected",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "subscription_plan",
            "monthly_message_limit",
            "created_at",
            "updated_at",
        ]

    def get_telegram_connected(self, obj) -> bool:
        return obj.has_telegram

    def get_telegram_group_connected(self, obj) -> bool:
        return obj.has_telegram_group

    def get_instagram_connected(self, obj) -> bool:
        return obj.has_instagram

    def get_bitrix24_connected(self, obj) -> bool:
        return obj.has_bitrix24

    def get_google_sheets_connected(self, obj) -> bool:
        return obj.has_google_sheets

    def get_own_bot_connected(self, obj) -> bool:
        return obj.has_own_bot


# ── Biznes ma'lumotlari (FAQ/Ish vaqti) — strukturaviy JSON
# validatsiyasi, xuddi `validate_item_metadata` kabi: xom,
# tekshirilmagan JSON to'g'ridan-to'g'ri bazaga yozilmasligi uchun. ──

WORKING_HOURS_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class FAQItemSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500)
    answer = serializers.CharField(max_length=2000)


class WorkingHoursDaySerializer(serializers.Serializer):
    closed = serializers.BooleanField(default=False)
    open = serializers.CharField(max_length=5, required=False, allow_blank=True, default="")
    close = serializers.CharField(max_length=5, required=False, allow_blank=True, default="")


def validate_faq_items(items: list) -> list:
    if len(items) > 50:
        raise serializers.ValidationError("Ko'pi bilan 50 ta savol-javob qo'shish mumkin.")
    serializer = FAQItemSerializer(data=items, many=True)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def validate_working_hours(working_hours: dict) -> dict:
    unknown_keys = set(working_hours.keys()) - set(WORKING_HOURS_DAY_KEYS)
    if unknown_keys:
        raise serializers.ValidationError(f"Noma'lum kun kaliti: {', '.join(unknown_keys)}")
    validated = {}
    for day in WORKING_HOURS_DAY_KEYS:
        if day not in working_hours:
            continue
        serializer = WorkingHoursDaySerializer(data=working_hours[day])
        serializer.is_valid(raise_exception=True)
        validated[day] = serializer.validated_data
    return validated


class StoreConfigUpdateSerializer(serializers.ModelSerializer):
    """
    AI Prompt, Bot sozlamalari va do'kon ma'lumotlarini yangilash serializeri.
    Frontend SettingsView'dan PATCH /api/v1/store/ keladi.
    """

    def validate_faq_items(self, value):
        return validate_faq_items(value)

    def validate_working_hours(self, value):
        return validate_working_hours(value)

    class Meta:
        model = Store
        # ⚠️ XAVFSIZLIK TUZATISHI: "tg_bot_token" va "tg_owner_chat_id"
        # avval shu ro'yxatda edi — ya'ni istalgan do'kon egasi PATCH
        # /api/v1/store/ orqali BEVOSITA bu maydonlarni o'zgartira olardi.
        # "tg_owner_chat_id"da unique cheklov yo'q edi, shuning uchun
        # bitta do'kon ega ataylab BOSHQA (haqiqiy) do'kon egasining
        # Telegram ID'sini kiritsa, o'sha haqiqiy ega TelegramInitData
        # autentifikatsiyasida "MultipleObjectsReturned" xatosi bilan
        # o'z paneliga kira olmay qolar edi (cross-tenant DoS). Bu ikki
        # maydon faqat tizim ichki oqimlari orqali (masalan admin_<uuid>
        # havolasini bosish) o'rnatilishi kerak — do'kon egasi tomonidan
        # ochiq API orqali ozgartirilmasligi kerak, shuning uchun
        # butunlay ro'yxatdan olib tashlandi.
        fields = [
            "name",
            "description",
            "phone_number",
            "category_type",
            "cta_type",
            "ai_active",
            "ai_system_prompt",
            "ai_model",
            "ai_temperature",
            "working_hours",
            "faq_items",
            "group_spam_cleanup_enabled",
            "ig_page_id",
            "ig_access_token",
            "bitrix24_webhook_url",
            "google_sheets_webhook_url",
        ]
        extra_kwargs = {
            "ig_access_token": {"write_only": True},
            # ⚠️ Webhook manzili maxfiy token'ni o'z ichiga oladi (masalan
            # https://company.bitrix24.com/rest/1/xxxxxxxx/) — ig_access_token
            # kabi write_only qilib qo'yildi, GET so'rovida qaytmaydi.
            # Ulanganligini tekshirish uchun StoreSerializer'dagi
            # "bitrix24_connected" (bool) dan foydalaniladi.
            "bitrix24_webhook_url": {"write_only": True},
            # Xuddi shu sabab bilan Google Sheets Apps Script URL'i ham
            # write_only — "google_sheets_connected" (bool) orqali tekshiriladi.
            "google_sheets_webhook_url": {"write_only": True},
        }

    def validate_bitrix24_webhook_url(self, value):
        """
        ⚠️ BUG FIX: avval bu maydon hech qanday tekshiruvsiz saqlanardi —
        noto'g'ri yoki CRM huquqisiz webhook ham "ULANGAN" deb ko'rsatilib,
        lidlar jimgina hech qachon Bitrix24'ga yetib bormasdi (jonli
        holatda aniqlandi). Endi saqlashdan OLDIN haqiqiy so'rov bilan
        tekshiriladi — noto'g'ri bo'lsa, aniq sabab bilan rad etiladi.
        """
        value = (value or "").strip()
        if not value:
            return value
        from apps.integrations.bitrix import validate_bitrix24_webhook
        is_valid, error_message = validate_bitrix24_webhook(value)
        if not is_valid:
            raise serializers.ValidationError(error_message)
        return value


# ── METADATA VALIDATORLAR ────────────────────────────────────

class EducationMetadataSerializer(serializers.Serializer):
    duration_months = serializers.IntegerField(min_value=1, required=False)
    lessons_per_week = serializers.IntegerField(min_value=1, required=False)
    lesson_duration_minutes = serializers.IntegerField(default=90, required=False)
    format = serializers.ChoiceField(choices=["online", "offline", "hybrid"], default="offline", required=False)
    teacher_name = serializers.CharField(required=False, allow_blank=True)
    trial_lesson_days = serializers.ListField(child=serializers.CharField(), required=False)


class ServicesMetadataSerializer(serializers.Serializer):
    duration_minutes = serializers.IntegerField(min_value=1, required=False)
    specialists = serializers.ListField(child=serializers.CharField(), required=False)
    available_hours = serializers.ListField(child=serializers.CharField(), required=False)
    location = serializers.CharField(required=False, allow_blank=True)


METADATA_SERIALIZERS = {
    Store.CategoryType.EDUCATION: EducationMetadataSerializer,
    Store.CategoryType.SERVICES: ServicesMetadataSerializer,
}


def validate_item_metadata(category_type: str, metadata: dict) -> dict:
    """
    Berilgan `metadata` dict'ini `category_type`ga mos metadata
    serializeri orqali tekshiradi va tozalangan (validated) qiymatni
    qaytaradi. Noma'lum category_type yoki noto'g'ri metadata uchun
    `serializers.ValidationError` ko'taradi.
    """
    serializer_cls = METADATA_SERIALIZERS.get(category_type)
    if serializer_cls is None:
        raise serializers.ValidationError({"category_type": "Noma'lum biznes kategoriyasi."})
    serializer = serializer_cls(data=metadata or {})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class OnboardingItemSerializer(serializers.Serializer):
    """Onboarding jarayonida keladigan mahsulot/kurs/xizmat modeli"""
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock = serializers.IntegerField(default=0)
    category = serializers.CharField(max_length=100, required=False, allow_blank=True)
    metadata = serializers.JSONField(default=dict, required=False)


class StoreOnboardingSerializer(serializers.ModelSerializer):
    """
    TWA Onboarding jarayoni uchun serializer.
    Merchant profilini to'ldiradi va birinchi mahsulot/xizmatlarini yaratadi.
    """
    items = OnboardingItemSerializer(many=True, required=False, write_only=True)

    class Meta:
        model = Store
        fields = [
            "name",
            "description",
            "phone_number",
            "category_type",
            "tg_bot_token",
            "items"
        ]

    def validate(self, attrs):
        category_type = attrs.get("category_type") or getattr(self.instance, "category_type", Store.CategoryType.EDUCATION)
        items = attrs.get("items", [])

        for idx, item in enumerate(items):
            try:
                validate_item_metadata(category_type, item.get("metadata", {}))
            except serializers.ValidationError as e:
                raise serializers.ValidationError({f"items[{idx}].metadata": e.detail})

        return attrs

    def update(self, instance, validated_data):
        from django.db import transaction
        from apps.products.models import Product

        items_data = validated_data.pop("items", None)

        with transaction.atomic():
            instance = super().update(instance, validated_data)

            if items_data is not None:
                # ⚠️ BUG FIX: `.delete()` bazadan HARD DELETE qiladi, bu esa
                # apps/core/models.py'dagi loyiha qoidasini buzadi:
                # "Hech qachon hard DELETE yo'q / Hech qachon .delete() chaqirmang!"
                # Har doim soft_delete() ishlatilishi kerak.
                for old_product in Product.objects.filter(store=instance):
                    old_product.soft_delete()
                for item in items_data:
                    Product.objects.create(
                        store=instance,
                        name=item["name"],
                        description=item.get("description", ""),
                        price=item.get("price", 0),
                        stock=item.get("stock", 0),
                        category=item.get("category", ""),
                        metadata=item.get("metadata", {})
                    )

        return instance


class StoreStaffMemberSerializer(serializers.ModelSerializer):
    """
    Guruhda ishlaydigan xodim (masalan sotuv menejeri) — AI bunday
    odamlarga do'kon egasiga o'xshab sotuv taklifi qilmaydi.
    """
    class Meta:
        model = StoreStaffMember
        fields = ["id", "tg_username", "full_name", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_tg_username(self, value: str) -> str:
        cleaned = value.lstrip("@").strip()
        if not cleaned:
            raise serializers.ValidationError("Telegram username kiritilishi shart.")
        return cleaned


# ─────────────────────────────────────────────────────────────
# Super Admin (Platforma Egasi) Serializerlari
# ─────────────────────────────────────────────────────────────

class SuperAdminBusinessListSerializer(serializers.ModelSerializer):
    """Platforma darajasidagi bizneslar ro'yxati uchun — ro'yxat sahifasida ko'rsatiladigan qisqa ma'lumot."""
    total_leads = serializers.IntegerField(read_only=True)  # .annotate() orqali queryset'ga qo'shiladi
    admin_link = serializers.SerializerMethodField()
    customer_link = serializers.SerializerMethodField()
    own_bot_connected = serializers.BooleanField(source="has_own_bot", read_only=True)

    class Meta:
        model = Store
        fields = [
            "id", "name", "category_type", "subscription_plan",
            "is_active", "ai_active", "tg_owner_chat_id", "total_leads", "created_at",
            "admin_link", "customer_link", "own_bot_connected",
            "bot_health_ok", "bot_health_checked_at", "subscription_ends_at",
        ]

    # ⚠️ Yaratilish paytida ko'rsatilgan havolalar bir martalik "Biznes
    # yaratildi" oynasi yopilgach BUTUNLAY yo'qolib qolardi — foydalanuvchi
    # buni "qayerga saqlab qo'yishim kerak" deb to'g'ri tashvishlandi.
    # Haqiqatda bu havolalar HECH QANDAY maxfiy narsa emas, faqat
    # `do'kon_id + bot_username`dan hisoblangan oddiy formula — shuning
    # uchun ularni istalgan vaqt QAYTA hisoblab berish mumkin (xuddi
    # `provision_store`dagi bilan AYNAN bir xil formula).
    def get_admin_link(self, obj):
        if not obj.tg_bot_username:
            return None
        return f"https://t.me/{obj.tg_bot_username}?start=admin_{obj.id}"

    def get_customer_link(self, obj):
        if not obj.tg_bot_username:
            return None
        return f"https://t.me/{obj.tg_bot_username}?start=store_{obj.id}"


class SuperAdminBusinessCreateSerializer(serializers.Serializer):
    """Super Admin panelidan yangi biznes (do'kon) yaratish uchun kiruvchi ma'lumotlar."""
    name = serializers.CharField(max_length=255)
    category_type = serializers.ChoiceField(choices=Store.CategoryType.choices)
    bot_username = serializers.CharField(max_length=64, required=False, default="LeadNodeBot")
    # Ixtiyoriy — biznes egasi boshidanoq o'z shaxsiy bot tokenini bergan
    # bo'lsa, shu yerga kiritiladi va darhol ulanadi (`provision_store`).
    bot_token = serializers.CharField(required=False, allow_blank=True, default="")


class SuperAdminBusinessDetailSerializer(serializers.ModelSerializer):
    """Super Admin — bitta biznesning to'liq operatsion holati (Biznes tafsilotlari sahifasi)."""
    admin_link = serializers.SerializerMethodField()
    customer_link = serializers.SerializerMethodField()
    twa_access = serializers.SerializerMethodField()
    token_status = serializers.SerializerMethodField()
    operational_summary = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id", "name", "description", "phone_number", "platform", "category_type",
            "is_active", "subscription_plan", "monthly_message_limit", "subscription_ends_at", "created_at",
            "admin_link", "customer_link", "twa_access", "token_status", "operational_summary",
        ]

    def get_admin_link(self, obj):
        if not obj.tg_bot_username:
            return None
        return f"https://t.me/{obj.tg_bot_username}?start=admin_{obj.id}"

    def get_customer_link(self, obj):
        if not obj.tg_bot_username:
            return None
        return f"https://t.me/{obj.tg_bot_username}?start=store_{obj.id}"

    def get_twa_access(self, obj):
        # Xom `tg_owner_chat_id` frontendga ATAYLAB yuborilmaydi (ichki
        # texnik identifikator) — faqat bog'langan/bog'lanmaganligi va
        # oxirgi 4 raqami (tasdiqlash uchun, to'liq ID'ni ochmagan holda).
        chat_id = obj.tg_owner_chat_id

        # ⚠️ Biriktirilgan ega Telegram'da @username o'rnatgan bo'lsa
        # (majburiy emas), shuni Super Admin ko'rishi va to'g'ridan-to'g'ri
        # o'sha odam bilan Telegram'da bog'lanishi uchun — YANGI maydon
        # qo'shish shart emas: ega bot bilan yozganda `Customer` yozuvi
        # ALLAQACHON shu username'ni saqlagan bo'ladi
        # (`apps/webhooks/tasks.py::process_incoming_message`).
        telegram_username = None
        if chat_id:
            from apps.customers.models import Customer

            owner_customer = Customer.objects.filter(
                store=obj, platform_user_id=chat_id,
            ).exclude(username="").exclude(username__isnull=True).first()
            if owner_customer:
                telegram_username = owner_customer.username

        return {
            "bound": bool(chat_id),
            "masked_chat_id": f"••••{chat_id[-4:]}" if chat_id else None,
            "telegram_username": telegram_username,
            "telegram_link": f"https://t.me/{telegram_username}" if telegram_username else None,
        }

    def get_token_status(self, obj):
        from django.conf import settings
        return {
            "connected": obj.has_own_bot,
            "is_master_bot": bool(obj.tg_bot_token) and obj.tg_bot_token == getattr(settings, "TELEGRAM_BOT_TOKEN", ""),
            "bot_username": obj.tg_bot_username or None,
            "masked_hash": f"••••{obj.tg_bot_token_hash[-4:]}" if obj.tg_bot_token_hash else None,
            # ⚠️ Faqat shaxsiy botlar uchun ma'noga ega (apps/stores/tasks.py
            # check_all_bot_health umumiy botni o'tkazib yuboradi) — umumiy
            # bot uchun doim None (hali tekshirilmagan) qaytadi.
            "health_ok": obj.bot_health_ok,
            "health_checked_at": obj.bot_health_checked_at,
            "health_error": obj.bot_health_error or None,
        }

    def get_operational_summary(self, obj):
        # ⚠️ ATAYLAB `apps/orders/views.py::LeadViewSet.stats`dagi bilan
        # bir xil so'rov naqshi (query pattern) — lekin hozircha alohida.
        # Bu tez-tez ishlaydigan, jonli mijozlar hozir ishlatayotgan
        # endpointni (Phase 1'da) tegmasdan qoldirish uchun ataylab
        # qilingan vaqtinchalik xolislik. Statistika sahifasi (Phase 3)
        # qurilganda ikkisi BIR umumiy `apps/orders/services.py`
        # funksiyasiga birlashtiriladi.
        from apps.customers.models import Customer
        from apps.chat.models import ChatMessage
        from apps.orders.models import Lead

        customers_qs = Customer.objects.filter(store=obj, is_deleted=False)
        if obj.tg_owner_chat_id:
            customers_qs = customers_qs.exclude(platform_user_id=obj.tg_owner_chat_id)

        interactions_total = customers_qs.count()
        conversed_total = customers_qs.filter(
            messages__role=ChatMessage.Role.ASSISTANT,
            messages__message_id__startswith="ai_resp_",
        ).distinct().count()
        leads_total = Lead.objects.filter(store=obj, is_deleted=False).count()
        conversion_rate = round((leads_total / interactions_total) * 100, 1) if interactions_total else 0.0

        return {
            "interactions_total": interactions_total,
            "conversed_total": conversed_total,
            "leads_total": leads_total,
            "conversion_rate": conversion_rate,
        }


class SuperAdminSubscriptionPlanUpdateSerializer(serializers.Serializer):
    """Super Admin — biznesning obuna rejasini va/yoki tugash sanasini o'zgartirish uchun kiruvchi ma'lumotlar."""
    subscription_plan = serializers.ChoiceField(choices=Store.SubscriptionPlan.choices, required=False)
    monthly_message_limit = serializers.IntegerField(required=False, min_value=1)
    subscription_ends_at = serializers.DateTimeField(required=False, allow_null=True)


class SuperAdminTokenConnectSerializer(serializers.Serializer):
    """Super Admin — biznesga shaxsiy Telegram bot tokenini ulash uchun kiruvchi ma'lumot."""
    bot_token = serializers.CharField()


class SuperAdminDeleteReauthSerializer(serializers.Serializer):
    """
    Super Admin — biznesni BUTUNLAY o'chirish uchun qayta tasdiqlash
    ma'lumotlari. ⚠️ Bu HOZIRGI (Telegram orqali kirgan bo'lishi mumkin
    bo'lgan) sessiyadan MUSTAQIL — parolga ega istalgan platforma xodimi
    hisobi bilan tasdiqlash mumkin (Telegram orqali kirganlarda parol
    umuman yo'q — unusable password).
    """
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

