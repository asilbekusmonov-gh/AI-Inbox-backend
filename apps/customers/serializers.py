"""
Customer Serializers — DRF
"""
from rest_framework import serializers
from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    """
    Do'kon mijozlarini ko'rish serializeri.
    """
    class Meta:
        model = Customer
        fields = [
            "id",
            "platform",
            "platform_user_id",
            "full_name",
            "phone_number",
            "username",
            "total_orders",
            "last_message_at",
            "created_at",
        ]
        read_only_fields = ["id", "platform", "platform_user_id", "created_at"]
