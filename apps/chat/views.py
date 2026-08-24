"""
Chat Views — DRF ReadOnlyModelViewSet (Multi-tenant)
"""
from rest_framework import viewsets, permissions, filters
from .models import ChatMessage
from .serializers import ChatMessageSerializer


class ChatMessageViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Do'kon xabarlar tarixini ko'rish (Live Inbox).
    Mijoz ID si bo'yicha filter qilish mumkin: /api/v1/chat/?customer=<customer_id>
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        user = self.request.user
        if not hasattr(user, "store") or not user.store:
            return ChatMessage.objects.none()

        qs = ChatMessage.objects.filter(store=user.store, is_deleted=False)

        customer_id = self.request.query_params.get("customer")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        return qs
