"""
Product Serializers — DRF.
Multi-tenant: `store` har doim request.user.store dan olinadi.
"""
from rest_framework import serializers
from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    """
    Mahsulotlarni ko'rish va boshqarish serializeri.
    """
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "stock",
            "sku",
            "category",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
