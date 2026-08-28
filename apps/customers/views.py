"""
Customer Views — DRF ReadOnlyModelViewSet (Multi-tenant)
"""
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Do'kon mijozlarini ko'rish va qidirish.
    """
    serializer_class = CustomerSerializer
    permission_classes = [permissions.AllowAny]  # TWA JWT'siz ishlaydi
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["full_name", "phone_number", "username", "platform_user_id"]
    ordering_fields = ["last_message_at", "total_orders", "created_at"]
    ordering = ["-last_message_at"]

    def _get_target_store(self):
        user = self.request.user
        if hasattr(user, "store") and user.store:
            return user.store
        from apps.stores.models import Store
        return Store.objects.filter(is_active=True, is_deleted=False).first()

    def get_queryset(self):
        target_store = self._get_target_store()
        if not target_store:
            return Customer.objects.none()
        return Customer.objects.filter(store=target_store, is_deleted=False)

    @action(detail=True, methods=["post"], url_path="toggle-ai")
    def toggle_ai(self, request, pk=None):
        """Mijoz uchun AI faolligini o'chirish/yoqish (Handoff)"""
        customer = self.get_object()
        ai_active = request.data.get("ai_active")
        if ai_active is not None:
            customer.ai_active = bool(ai_active)
        else:
            customer.ai_active = not customer.ai_active
        customer.save(update_fields=["ai_active", "updated_at"])
        return Response({
            "success": True,
            "customer_id": str(customer.id),
            "ai_active": customer.ai_active
        }, status=status.HTTP_200_OK)

