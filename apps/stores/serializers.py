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
from .models import Store


class StoreSerializer(serializers.ModelSerializer):
    """
    Do'kon ma'lumotlari va AI prompt sozlamalari serializeri.
    Frontend ChatThread va KPI komponentlari kutadigan formatda qaytaradi.
    """
    # Frontend "telegram_connected" / "instagram_connected" nomlarini kutadi
    telegram_connected = serializers.SerializerMethodField()
    instagram_connected = serializers.SerializerMethodField()

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
            "tg_bot_username",
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

    def get_instagram_connected(self, obj) -> bool:
        return obj.has_instagram


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
            "ig_page_id",
            "ig_access_token",
        ]
        extra_kwargs = {
            "ig_access_token": {"write_only": True},
        }


# ── METADATA VALIDATORLAR ────────────────────────────────────

class ECommerceMetadataSerializer(serializers.Serializer):
    sizes = serializers.ListField(child=serializers.CharField(), required=False)
    colors = serializers.ListField(child=serializers.CharField(), required=False)
    brand = serializers.CharField(required=False, allow_blank=True)
    delivery_available = serializers.BooleanField(default=True)


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
        category_type = attrs.get("category_type") or getattr(self.instance, "category_type", Store.CategoryType.E_COMMERCE)
        items = attrs.get("items", [])

        for idx, item in enumerate(items):
            meta_data = item.get("metadata", {})
            
            if category_type == Store.CategoryType.E_COMMERCE:
                serializer = ECommerceMetadataSerializer(data=meta_data)
            elif category_type == Store.CategoryType.EDUCATION:
                serializer = EducationMetadataSerializer(data=meta_data)
            elif category_type == Store.CategoryType.SERVICES:
                serializer = ServicesMetadataSerializer(data=meta_data)
            else:
                raise serializers.ValidationError({"category_type": "Noma'lum biznes kategoriyasi."})

            if not serializer.is_valid():
                raise serializers.ValidationError({
                    f"items[{idx}].metadata": serializer.errors
                })

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

