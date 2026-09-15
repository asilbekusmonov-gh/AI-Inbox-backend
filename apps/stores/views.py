"""
Store Views — DRF (Multi-tenant)
"""
import logging

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import (
    StoreSerializer,
    StoreConfigUpdateSerializer,
    StoreOnboardingSerializer,
    OnboardingItemSerializer,
    validate_item_metadata,
)
from apps.core.authentication import get_store_from_request

logger = logging.getLogger("apps.stores")


class StoreDetailUpdateView(generics.RetrieveUpdateAPIView):
    """
    Do'kon egasi uchun o'z profil va AI prompt sozlamalarini olish/yangilash endpointi.
    GET/PATCH /api/v1/store/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return StoreConfigUpdateSerializer
        return StoreSerializer

    def get_object(self):
        store = get_store_from_request(self.request)
        if not store:
            from rest_framework.exceptions import NotFound
            raise NotFound("Do'kon topilmadi. Telegram yoki JWT orqali kiring.")
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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreOnboardingSerializer

    def get_object(self):
        store = get_store_from_request(self.request)
        if not store:
            from rest_framework.exceptions import NotFound
            raise NotFound("Do'kon topilmadi. Telegram yoki JWT orqali kiring.")
        return store

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(StoreSerializer(instance).data, status=status.HTTP_200_OK)


class CatalogParseView(APIView):
    """
    Egasi bir martalik yozgan erkin matndagi katalog tavsifini (barcha
    kurs/mahsulot/xizmatlar) AI orqali onboarding "items" formatiga mos
    strukturaviy ro'yxatga aylantiradi.

    ⚠️ Bu FAQAT bir martalik qoralama tayyorlash vositasi — natija
    saqlanmaydi. Frontend qaytgan ro'yxatni owner'ga ko'rsatib,
    tahrirlatib, keyin StoreOnboardingView (PUT/PATCH /store/onboarding/)
    orqali saqlashi kerak. Shu sababli bu yerdagi AI xatosi hech qachon
    to'g'ridan-to'g'ri bazaga yoki mijozga yetib bormaydi.

    POST /api/v1/store/parse-catalog/
    Body: {"text": "...", "category_type": "education"}  # category_type ixtiyoriy
    Response: {"items": [...]}  # OnboardingItemSerializer formatida
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        store = get_store_from_request(request)
        if not store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        text = (request.data.get("text") or "").strip()
        if not text:
            return Response({"error": "Matn kiritilmagan"}, status=status.HTTP_400_BAD_REQUEST)

        category_type = request.data.get("category_type") or getattr(store, "category_type", "education")

        from apps.products.ai_service import parse_catalog_text

        try:
            raw_items = parse_catalog_text(text, category_type)
        except Exception as e:
            logger.error(f"[Catalog Parse] AI tahlil xatosi: {e} | store={store.name}", exc_info=True)
            return Response(
                {"error": "AI katalogni tahlil qila olmadi. Birozdan so'ng qayta urinib ko'ring."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not raw_items:
            return Response({"items": []}, status=status.HTTP_200_OK)

        # AI ba'zan bitta elementda xato qilishi mumkin — butun natijani
        # rad etish o'rniga, faqat noto'g'ri elementlarni tashlab, qolgan
        # to'g'rilarini qaytaramiz (owner baribir hammasini ko'rib chiqadi).
        valid_items = []
        for item in raw_items:
            item_serializer = OnboardingItemSerializer(data=item)
            if not item_serializer.is_valid():
                logger.warning(f"[Catalog Parse] Noto'g'ri element tashlab yuborildi: {item} | xato={item_serializer.errors}")
                continue
            try:
                validate_item_metadata(category_type, item_serializer.validated_data.get("metadata", {}))
            except Exception as e:
                logger.warning(f"[Catalog Parse] Noto'g'ri metadata tashlab yuborildi: {item} | xato={e}")
                continue
            valid_items.append(item_serializer.validated_data)

        return Response({"items": valid_items}, status=status.HTTP_200_OK)


from django.conf import settings
import httpx

class SuperAdminStatsView(APIView):
    """
    SaaS Platforma Egasi (Super Admin) uchun barcha platforma ko'rsatkichlari endpointi:
    GET /api/v1/superadmin/stats/

    ⚠️ BUG FIX: Avval faqat IsAuthenticated tekshirilardi — bu shuni
    anglatardiki, HAR QANDAY oddiy do'kon egasi (tenant) o'z JWT tokeni
    bilan ushbu endpointga kirib, BARCHA do'konlarning daromadi, bot
    holati va boshqa maxfiy statistikasini ko'ra olardi. Bu multi-tenant
    izolyatsiya qoidasini buzadigan jiddiy xavfsizlik zaifligi edi.
    Endi faqat is_staff/is_superuser bo'lgan platforma xodimlari kira oladi.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from apps.stores.models import Store
        from apps.orders.models import Lead
        from apps.customers.models import Customer

        total_stores = Store.objects.filter(is_deleted=False).count()
        active_stores = Store.objects.filter(is_active=True, is_deleted=False).count()
        total_leads = Lead.objects.filter(is_deleted=False).count()
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
            st_leads = Lead.objects.filter(store=s, is_deleted=False).count()
            stores_list.append({
                "id": str(s.id),
                "name": s.name,
                "category_type": getattr(s, "category_type", "education"),
                "is_active": s.is_active,
                "ai_active": s.ai_active,
                "tg_owner_chat_id": s.tg_owner_chat_id or "Nokalit",
                "total_leads": st_leads,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M")
            })

        return Response({
            "total_stores": total_stores,
            "active_stores": active_stores,
            "total_leads": total_leads,
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
    permission_classes = [permissions.IsAuthenticated]

    def _get_store(self):
        return get_store_from_request(self.request)

    def post(self, request):
        store = self._get_store()
        if not store:
            return Response(
                {"error": "Do'kon topilmadi"},
                status=status.HTTP_404_NOT_FOUND,
            )

        short_lived_token = (request.data.get("short_lived_token") or "").strip()
        selected_page_id = (request.data.get("selected_page_id") or "").strip() or None

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
    permission_classes = [permissions.IsAuthenticated]

    def _get_store(self):
        return get_store_from_request(self.request)

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
