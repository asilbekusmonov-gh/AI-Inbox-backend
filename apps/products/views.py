"""
Product Views — DRF ModelViewSet (Multi-tenant).

Qoidalar:
- Authenticated user'lar uchun: `store = request.user.store`
- Development / Test rejimida (unauthenticated): avtomatik birinchi mavjud `Store` biriktiriladi.
"""
from rest_framework import viewsets, permissions, filters
from .models import Product
from .serializers import ProductSerializer
from apps.stores.models import Store


class ProductViewSet(viewsets.ModelViewSet):
    """
    Do'kon mahsulotlarini CRUD qilish uchun ViewSet.
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]  # Dev va TWA test rejimi uchun AllowAny
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description", "sku", "category"]
    ordering_fields = ["created_at", "price", "stock", "name"]
    ordering = ["-created_at"]

    def _get_target_store(self):
        """Request yuborgan user store'ini oladi, bo'lmasa 1-do'konni biriktiradi."""
        user = self.request.user
        if hasattr(user, "store") and user.store:
            return user.store
        
        # Dev / Local browser test rejimi uchun birinchi mavjud do'kon
        first_store = Store.objects.filter(is_active=True, is_deleted=False).first()
        if not first_store:
            # Do'kon yo'q bo'lsa avtomatik yaratamiz
            from django.contrib.auth.models import User
            admin_user, _ = User.objects.get_or_create(username="default_admin")
            first_store, _ = Store.objects.get_or_create(
                owner=admin_user,
                defaults={"name": "AI Store Demo"}
            )
        return first_store

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
        cat_type = self.request.data.get("category_type") or getattr(target_store, "category_type", "e_commerce")
        serializer.save(store=target_store, category_type=cat_type)

    def perform_destroy(self, instance):
        """Soft Delete: bazadan o'chirilmaydi, is_deleted=True bo'ladi"""
        instance.soft_delete()
