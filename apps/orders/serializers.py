"""
Order Serializers — DRF

Frontend ↔ Backend field mapping:
  - channel     ← platform (aliased via SerializerMethodField)
  - items       ← items JSONField (normalized to frontend OrderItem format)
    Backend stores: [{'name': ..., 'qty': ..., 'price': ...}]
    Frontend needs: [{id, product_name, quantity, unit_price, total_price}]
"""
from rest_framework import serializers
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    """
    Buyurtmalarni ko'rish va statusini yangilash serializeri.
    Frontend Order type bilan to'liq mos keladi.
    """
    # Frontend 'channel' kutadi, model 'platform' saqlaydi
    channel = serializers.CharField(source='platform', read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "platform",
            "channel",
            "is_voice_order",
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
            "channel",
            "customer",
            "owner_notified",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        # Normalize items JSONField to frontend OrderItem format
        # Backend may store: [{'name': 'Nike', 'qty': 1, 'price': 250000}]
        # Frontend needs:    [{id, product_name, quantity, unit_price, total_price}]
        raw_items = ret.get('items') or []
        normalized = []
        for idx, item in enumerate(raw_items):
            if isinstance(item, dict):
                # Already in frontend format?
                if 'product_name' in item:
                    normalized.append(item)
                else:
                    # Convert from backend format
                    qty = item.get('qty', item.get('quantity', 1))
                    price = item.get('price', item.get('unit_price', 0))
                    normalized.append({
                        'id': item.get('id', f'item-{idx}'),
                        'product_name': item.get('name', item.get('product_name', 'Noma\'lum mahsulot')),
                        'quantity': qty,
                        'unit_price': price,
                        'total_price': item.get('total_price', qty * price),
                    })
        ret['items'] = normalized
        return ret


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    """
    Buyurtma holatini (status) yangilash uchun ixcham serializer.
    """
    class Meta:
        model = Order
        fields = ["status", "notes"]
