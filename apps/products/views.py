"""
Product Views — DRF ModelViewSet (Multi-tenant).

Qoidalar:
- Telegram initData yoki JWT bilan autentifikatsiya bo'lgan
  do'kon egasi o'z do'konining mahsulotlarini boshqaradi.
- Autentifikatsiya bo'lmagan so'rovlar 401 bilan rad etiladi.
"""
import logging

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Product
from .serializers import ProductSerializer
from .ai_service import generate_product_description
from apps.core.authentication import get_store_from_request

logger = logging.getLogger("apps.products")


class ProductViewSet(viewsets.ModelViewSet):
    """
    Do'kon mahsulotlarini CRUD qilish uchun ViewSet.
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description", "sku", "category"]
    ordering_fields = ["created_at", "price", "stock", "name"]
    ordering = ["-created_at"]

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
        return get_store_from_request(self.request)

    def get_queryset(self):
        """Store va active category_type bo'yicha filterlangan mahsulotlar ro'yxati"""
        target_store = self._get_target_store()
        if not target_store:
            return Product.objects.none()

        cat_type = self.request.query_params.get("category_type") or getattr(target_store, "category_type", "e_commerce")
        return Product.objects.filter(store=target_store, category_type=cat_type, is_deleted=False)

    def perform_create(self, serializer):
        """Yangi mahsulot yaratilganda target store va uning category_type biriktiriladi"""
        target_store = self._get_target_store()
        if not target_store:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Do'kon topilmadi")
        cat_type = self.request.data.get("category_type") or getattr(target_store, "category_type", "e_commerce")
        serializer.save(store=target_store, category_type=cat_type)

    def perform_destroy(self, instance):
        """Soft Delete: bazadan o'chirilmaydi, is_deleted=True bo'ladi"""
        instance.soft_delete()

    @action(detail=False, methods=["post"], url_path="generate-description")
    def generate_description(self, request):
        """
        AI orqali mahsulot/kurs/xizmat tavsifini generatsiya qiladi:
        POST /api/v1/products/generate-description/
        Body: {"name": "...", "category": "...", "price": ..., "stock": ...}
        """
        target_store = self._get_target_store()
        if not target_store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "Nomi kiritilmagan"}, status=status.HTTP_400_BAD_REQUEST)

        category = (request.data.get("category") or "").strip()
        category_type = request.data.get("category_type") or getattr(target_store, "category_type", "e_commerce")
        price = request.data.get("price")
        stock = request.data.get("stock")

        try:
            description = generate_product_description(
                name=name,
                category_type=category_type,
                category=category,
                price=price,
                stock=stock,
            )
        except Exception as e:
            logger.error(f"[AI Description] Generatsiya xatosi: {e} | store={target_store.name}", exc_info=True)
            return Response(
                {"error": "AI tavsif yaratib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"description": description}, status=status.HTTP_200_OK)

