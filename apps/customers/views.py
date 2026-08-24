"""
Customer Views — DRF ReadOnlyModelViewSet (Multi-tenant)
"""
from rest_framework import viewsets, permissions, filters
from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Do'kon mijozlarini ko'rish va qidirish.
    """
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["full_name", "phone_number", "username", "platform_user_id"]
    ordering_fields = ["last_message_at", "total_orders", "created_at"]
    ordering = ["-last_message_at"]

    def get_queryset(self):
        user = self.request.user
        if not hasattr(user, "store") or not user.store:
            return Customer.objects.none()
        return Customer.objects.filter(store=user.store, is_deleted=False)
