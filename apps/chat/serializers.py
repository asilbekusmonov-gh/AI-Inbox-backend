"""
Chat Serializers — DRF
"""
from rest_framework import serializers
from .models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    """
    Chat xabarlarini ko'rish va live-inbox uchun serializer.
    """
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    customer_username = serializers.CharField(source="customer.username", read_only=True)

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "customer",
            "customer_name",
            "customer_username",
            "message_id",
            "platform",
            "role",
            "content",
            "processing_status",
            "tokens_used",
            "ai_model_used",
            "created_at",
        ]
        read_only_fields = fields
