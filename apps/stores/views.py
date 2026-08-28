"""
Store Views — DRF (Multi-tenant)
"""
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from .models import Store
from .serializers import StoreSerializer, StoreConfigUpdateSerializer, StoreOnboardingSerializer


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


class StoreOnboardingView(generics.UpdateAPIView):
    """
    Telegram Web App (TWA) orqali onboarding jarayoni.
    Merchant soha turini va boshlang'ich mahsulot/xizmatlarini yuboradi.
    PUT/PATCH /api/v1/store/onboarding/
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = StoreOnboardingSerializer

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
                    defaults={"name": "Demo Merchant"}
                )
        return store

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(StoreSerializer(instance).data, status=status.HTTP_200_OK)


from rest_framework.views import APIView
from django.conf import settings
import httpx

class SuperAdminStatsView(APIView):
    """
    SaaS Platforma Egasi (Super Admin) uchun barcha platforma ko'rsatkichlari endpointi:
    GET /api/v1/superadmin/stats/
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from apps.stores.models import Store
        from apps.orders.models import Order
        from apps.customers.models import Customer
        from django.db.models import Sum

        total_stores = Store.objects.filter(is_deleted=False).count()
        active_stores = Store.objects.filter(is_active=True, is_deleted=False).count()
        total_orders = Order.objects.filter(is_deleted=False).count()
        total_revenue = Order.objects.filter(is_deleted=False, status__in=["confirmed", "completed"]).aggregate(s=Sum("total_amount"))["s"] or 0
        total_customers = Customer.objects.filter(is_deleted=False).count()

        # Bot health check
        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        bot_active = False
        bot_username = "unknown"
        if bot_token:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/getMe"
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(url)  # /getMe is a GET endpoint
                    data = resp.json()
                    if resp.status_code == 200 and data.get("ok"):
                        bot_active = True
                        bot_username = data.get("result", {}).get("username", "unknown")
            except Exception:
                pass

        stores_qs = Store.objects.filter(is_deleted=False).order_by("-created_at")
        stores_list = []
        for s in stores_qs:
            st_orders = Order.objects.filter(store=s, is_deleted=False).count()
            st_rev = Order.objects.filter(store=s, is_deleted=False, status__in=["confirmed", "completed"]).aggregate(s=Sum("total_amount"))["s"] or 0
            stores_list.append({
                "id": str(s.id),
                "name": s.name,
                "category_type": getattr(s, "category_type", "e_commerce"),
                "is_active": s.is_active,
                "ai_active": s.ai_active,
                "tg_owner_chat_id": s.tg_owner_chat_id or "Nokalit",
                "total_orders": st_orders,
                "total_revenue": st_rev,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M")
            })

        return Response({
            "total_stores": total_stores,
            "active_stores": active_stores,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_customers": total_customers,
            "bot_active": bot_active,
            "bot_username": f"@{bot_username}" if bot_username != "unknown" else None,
            "stores": stores_list
        }, status=status.HTTP_200_OK)


class InstagramConnectView(APIView):
    """
    Do'konga Instagram Business Akkauntini ulash.

    POST /api/v1/store/instagram/connect/

    Request Body:
        {
            "short_lived_token": "EAABw...",   # Meta Login'dan kelgan token
            "selected_page_id": "123456"        # Ixtiyoriy — bir nechta sahifa bo'lsa
        }

    Response (muvaffaqiyatli):
        {
            "success": true,
            "ig_page_id": "17841400...",
            "facebook_page_name": "My Store",
            "token_expires_at": "2026-10-25T12:00:00+05:00",
            "pages": [...]  # faqat bir nechta sahifa bo'lsa va tanlanmagan bo'lsa
        }

    Xatoliklar:
        400 — token noto'g'ri, Instagram akkaunt ulanmagan
        502 — Meta API ishlamayapti
    """
    permission_classes = [permissions.AllowAny]

    def _get_store(self):
        user = self.request.user
        store = getattr(user, "store", None)
        if not store or store.is_deleted:
            store = Store.objects.filter(is_active=True, is_deleted=False).first()
        return store

    def post(self, request):
        store = self._get_store()
        if not store:
            return Response(
                {"error": "Do'kon topilmadi"},
                status=status.HTTP_404_NOT_FOUND,
            )

        short_lived_token = request.data.get("short_lived_token", "").strip()
        selected_page_id = request.data.get("selected_page_id", "").strip() or None

        if not short_lived_token:
            return Response(
                {"error": "short_lived_token maydoni majburiy"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.stores.services import connect_instagram_to_store

        try:
            result = connect_instagram_to_store(
                store=store,
                short_lived_token=short_lived_token,
                selected_page_id=selected_page_id,
            )
            return Response(result, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            import logging
            logging.getLogger("apps.stores").error(
                f"Instagram connect kutilmagan xato: {e}",
                exc_info=True,
            )
            return Response(
                {"error": "Meta API bilan ulanishda kutilmagan xato yuz berdi"},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class InstagramDisconnectView(APIView):
    """
    Do'kondan Instagram akkauntini uzish.

    DELETE /api/v1/store/instagram/disconnect/

    Response:
        {"success": true}
    """
    permission_classes = [permissions.AllowAny]

    def _get_store(self):
        user = self.request.user
        store = getattr(user, "store", None)
        if not store or store.is_deleted:
            store = Store.objects.filter(is_active=True, is_deleted=False).first()
        return store

    def delete(self, request):
        store = self._get_store()
        if not store:
            return Response(
                {"error": "Do'kon topilmadi"},
                status=status.HTTP_404_NOT_FOUND,
            )

        from apps.stores.services import disconnect_instagram_from_store

        result = disconnect_instagram_from_store(store)
        return Response(result, status=status.HTTP_200_OK)
