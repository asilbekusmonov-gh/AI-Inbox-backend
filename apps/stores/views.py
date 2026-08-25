"""
Store Views — DRF (Multi-tenant)
"""
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from .models import Store
from .serializers import StoreSerializer, StoreConfigUpdateSerializer


class StoreDetailUpdateView(generics.RetrieveUpdateAPIView):
    """
    Do'kon egasi uchun o'z profil va AI prompt sozlamalarini olish/yangilash endpointi.
    GET/PATCH /api/v1/store/
    """
    permission_classes = [permissions.AllowAny]

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return StoreConfigUpdateSerializer
        return StoreSerializer

    def get_object(self):
        user = self.request.user
        store = getattr(user, "store", None)
        if not store or store.is_deleted:
            store = Store.objects.filter(is_active=True, is_deleted=False).first()
            if not store:
                from django.contrib.auth.models import User
                admin_user, _ = User.objects.get_or_create(username="default_admin")
                store, _ = Store.objects.get_or_create(
                    owner=admin_user,
                    defaults={"name": "Zulfiya Fashion Demo"}
                )
        return store

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(StoreSerializer(instance).data, status=status.HTTP_200_OK)
