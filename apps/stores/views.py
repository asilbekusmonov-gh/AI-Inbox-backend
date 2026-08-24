"""
Store Views — DRF (Multi-tenant)
"""
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from .models import Store
from .serializers import StoreSerializer, StoreConfigUpdateSerializer


class StoreDetailUpdateView(generics.RetrieveUpdateAPIView):
    """
    Do'kon egasi uchun o'z do mezoniy profil va AI prompt sozlamalarini olish/yangilash endpointi.
    GET/PATCH /api/v1/store/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return StoreConfigUpdateSerializer
        return StoreSerializer

    def get_object(self):
        # Qat'iy Multi-tenancy: Faqat foydalanuvchining o'z store obyekti
        store = getattr(self.request.user, "store", None)
        if not store or store.is_deleted:
            from rest_framework.exceptions import NotFound
            raise NotFound("Foydalanuvchiga tegishli aktiv do'kon topilmadi.")
        return store
