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
            "ai_active",
            "ai_system_prompt",
            "ai_model",
            "ai_temperature",
            "ai_max_tokens",
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


class StoreConfigUpdateSerializer(serializers.ModelSerializer):
    """
    AI Prompt, Bot sozlamalari va do'kon ma'lumotlarini yangilash serializeri.
    Frontend SettingsView'dan PATCH /api/v1/store/ keladi.
    """
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
            "ai_active",
            "ai_system_prompt",
            "ai_model",
            "ai_temperature",
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

    class Meta:
        model = Store
        fields = [
            "id", "name", "category_type", "subscription_plan",
            "is_active", "ai_active", "tg_owner_chat_id", "total_leads", "created_at",
        ]


class SuperAdminBusinessCreateSerializer(serializers.Serializer):
    """Super Admin panelidan yangi biznes (do'kon) yaratish uchun kiruvchi ma'lumotlar."""
    name = serializers.CharField(max_length=255)
    category_type = serializers.ChoiceField(choices=Store.CategoryType.choices)
    bot_username = serializers.CharField(max_length=64, required=False, default="LeadNodeBot")

