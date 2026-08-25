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
        fields = [
            "name",
            "description",
            "phone_number",
            "ai_active",
            "ai_system_prompt",
            "ai_model",
            "ai_temperature",
            "tg_bot_token",
            "tg_owner_chat_id",
            "ig_page_id",
            "ig_access_token",
        ]
        extra_kwargs = {
            "tg_bot_token": {"write_only": True},
            "ig_access_token": {"write_only": True},
        }
