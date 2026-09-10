"""
Product Serializers — DRF.
Robust Image URL handling with fallback metadata parsing.
"""
from rest_framework import serializers
from .models import Product
import re


class ProductSerializer(serializers.ModelSerializer):
    """
    Mahsulotlarni ko'rish va boshqarish serializeri.
    `image_url` qiymati description tarkibidagi [IMG: ...] tegidan va default qiymatdan avtomatik o'qiladi.
    """
    image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)

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
            "category_type",
            "metadata",
            "image_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        desc = instance.description or ""

        # Extract image URL from [IMG: ...] tag if present in description
        img_match = re.search(r"\[IMG:\s*(https?://[^\s\]]+|data:image/[^\s\]]+)\]", desc)
        if img_match:
            ret["image_url"] = img_match.group(1)
            # Clean description for display
            ret["description"] = re.sub(r"\[IMG:\s*(https?://[^\s\]]+|data:image/[^\s\]]+)\]\s*", "", desc).strip()
        else:
            # ⚠️ BUG FIX: avval bu yerda rasm bo'lmagan HAR BIR mahsulot uchun
            # bir xil hardcode qilingan (kategoriyaga mos kelmaydigan) krossovka
            # rasmi qaytarilardi — hatto egasi rasmni frontend'da o'chirib,
            # saqlagandan keyin ham, keyingi GET so'rovida yana o'sha rasm
            # qaytib chiqardi (o'chirish hech qachon "ushlanmagan" ko'rinardi).
            # Endi rasm yo'qligi haqiqatan ham yo'q deb qaytariladi.
            ret["image_url"] = None

        return ret

    def create(self, validated_data):
        img_url = validated_data.pop("image_url", None)
        desc = validated_data.get("description", "") or ""

        if img_url and str(img_url).strip():
            validated_data["description"] = f"[IMG: {str(img_url).strip()}]\n{desc}".strip()

        return Product.objects.create(**validated_data)

    def update(self, instance, validated_data):
        has_img_key = "image_url" in validated_data
        img_url = validated_data.pop("image_url", None)

        if "description" in validated_data:
            desc = validated_data["description"] or ""
            desc = re.sub(r"\[IMG:\s*(https?://[^\s\]]+|data:image/[^\s\]]+)\]\s*", "", desc).strip()
        else:
            desc = instance.description or ""
            desc = re.sub(r"\[IMG:\s*(https?://[^\s\]]+|data:image/[^\s\]]+)\]\s*", "", desc).strip()

        if has_img_key:
            if img_url and str(img_url).strip():
                validated_data["description"] = f"[IMG: {str(img_url).strip()}]\n{desc}".strip()
            else:
                validated_data["description"] = desc.strip()
        elif "description" in validated_data:
            old_img_match = re.search(r"\[IMG:\s*(https?://[^\s\]]+|data:image/[^\s\]]+)\]", instance.description or "")
            if old_img_match:
                old_img = old_img_match.group(1)
                validated_data["description"] = f"[IMG: {old_img}]\n{desc}".strip()

        return super().update(instance, validated_data)

