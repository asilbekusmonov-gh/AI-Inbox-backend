"""
Store Serializers — DRF
"""
from rest_framework import serializers
from .models import Store


class StoreSerializer(serializers.ModelSerializer):
    """
    Do'kon ma'lumotlari va AI prompt sozlamalari serializeri.
    Tokenlar va maxfiy ma'lumotlar read-only yoki yashirin saqlanadi.
    """
    has_instagram = serializers.BooleanField(read_only=True)
    has_telegram = serializers.BooleanField(read_only=True)

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "platform",
            "ai_system_prompt",
            "ai_model",
            "ai_temperature",
            "ai_max_tokens",
            "subscription_plan",
            "monthly_message_limit",
            "is_active",
            "has_instagram",
            "has_telegram",
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


class StoreConfigUpdateSerializer(serializers.ModelSerializer):
    """
    Do mezoniy AI Prompt va Bot sozlamalarini yangilash serializeri.
    """
    class Meta:
        model = Store
        fields = [
            "name",
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
