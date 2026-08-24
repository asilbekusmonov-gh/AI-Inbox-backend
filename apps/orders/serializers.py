"""
Order Serializers — DRF
"""
from rest_framework import serializers
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    """
    Buyurtmalarni ko'rish va statusini yangilash serializeri.
    """
    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "platform",
            "customer",
            "customer_full_name",
            "customer_phone",
            "delivery_address",
            "items",
            "notes",
            "total_amount",
            "delivery_fee",
            "status",
            "status_changed_at",
            "owner_notified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "order_number",
            "customer",
            "owner_notified",
            "created_at",
            "updated_at",
        ]


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    """
    Buyurtma holatini (status) yangilash uchun ixcham serializer.
    """
    class Meta:
        model = Order
        fields = ["status", "notes"]
