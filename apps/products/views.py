"""
Product Views — DRF ModelViewSet (Multi-tenant).

Qoidalar:
- Faqat autentifikatsiyadan o'tgan foydalanuvchilar
- Queryset albatta `store = request.user.store` bo'yicha filterlanadi
- Yaratishda `store = request.user.store` avtomatik biriktiriladi
"""
from rest_framework import viewsets, permissions, filters
from .models import Product
from .serializers import ProductSerializer


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

    def get_queryset(self):
        """Multi-tenant xavfsizlik: faqat user'ning o'z store'iga tegishli mahsulotlar"""
        user = self.request.user
        if not hasattr(user, "store") or not user.store:
            return Product.objects.none()
        return Product.objects.filter(store=user.store, is_deleted=False)

    def perform_create(self, serializer):
        """Yangi mahsulot yaratilganda store avtomatik qo'shiladi"""
        serializer.save(store=self.request.user.store)

    def perform_destroy(self, instance):
        """Soft Delete: bazadan o'chirilmaydi, is_deleted=True bo'ladi"""
        instance.soft_delete()
