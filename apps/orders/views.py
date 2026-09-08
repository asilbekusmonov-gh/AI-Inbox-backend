"""
Order Views — DRF ModelViewSet (Multi-tenant)
"""
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Order
from .serializers import OrderSerializer, OrderStatusUpdateSerializer
from apps.core.authentication import get_store_from_request


class OrderViewSet(viewsets.ModelViewSet):
    """
    Buyurtmalarni ko'rish, qidirish va holatini yangilash.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["order_number", "customer_full_name", "customer_phone", "delivery_address"]
    ordering_fields = ["created_at", "total_amount", "status"]
    ordering = ["-created_at"]

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
        return get_store_from_request(self.request)

    def get_queryset(self):
        """Multi-tenant: Faqat tegishli store buyurtmalari va o'chirilmaganlari"""
        target_store = self._get_target_store()
        if not target_store:
            return Order.objects.none()

        qs = Order.objects.filter(store=target_store, is_deleted=False)

        # Status bo'yicha qo'shimcha filtr: "all" bo'lsa faqat faol (new va confirmed) ko'rsatiladi
        status_param = self.request.query_params.get("status")
        if status_param == "all":
            qs = qs.filter(status__in=["new", "confirmed"])
        elif status_param:
            qs = qs.filter(status=status_param)

        # Qidiruv yoki show_all bo'lmasa: default sifatida oxirgi 30 kunlik (kamida 50 ta) buyurtmalar beriladi (Shopify style)
        search_param = self.request.query_params.get("search")
        show_all = self.request.query_params.get("show_all")
        if not search_param and not show_all:
            from django.utils import timezone
            from datetime import timedelta
            thirty_days_ago = timezone.now() - timedelta(days=30)
            recent_ids = list(qs.filter(created_at__gte=thirty_days_ago).values_list("id", flat=True))
            if len(recent_ids) < 50:
                recent_ids = list(qs.order_by("-created_at")[:50].values_list("id", flat=True))
            qs = qs.filter(id__in=recent_ids)

        return qs.order_by("-created_at")

    def perform_destroy(self, instance):
        """Soft delete"""
        instance.soft_delete()

    @action(detail=True, methods=["patch"], url_path="update-status")
    def update_status(self, request, pk=None):
        """Buyurtma holatini yangilash endpointi: PATCH /api/v1/orders/<id>/update-status/"""
        order = self.get_object()
        serializer = OrderStatusUpdateSerializer(order, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        new_status = serializer.validated_data.get("status")
        if new_status:
            order.update_status(new_status)

        if "notes" in serializer.validated_data:
            order.notes = serializer.validated_data["notes"]
            order.save(update_fields=["notes", "updated_at"])

        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
