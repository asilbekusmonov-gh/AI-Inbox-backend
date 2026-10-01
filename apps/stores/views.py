"""
Store Views — DRF (Multi-tenant)
"""
import logging
from datetime import timedelta

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import (
    StoreSerializer,
    StoreConfigUpdateSerializer,
    StoreOnboardingSerializer,
    OnboardingItemSerializer,
    StoreStaffMemberSerializer,
    SuperAdminBusinessListSerializer,
    SuperAdminBusinessCreateSerializer,
    SuperAdminBusinessDetailSerializer,
    SuperAdminSubscriptionPlanUpdateSerializer,
    SuperAdminTokenConnectSerializer,
    SuperAdminDeleteReauthSerializer,
    validate_item_metadata,
)
from .models import Store, StoreStaffMember
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

        from django.utils import timezone as _timezone

        total_stores = Store.objects.filter(is_deleted=False).count()
        active_stores = Store.objects.filter(is_active=True, is_deleted=False).count()
        disabled_stores = total_stores - active_stores
        free_stores = Store.objects.filter(is_deleted=False, subscription_plan=Store.SubscriptionPlan.FREE).count()
        paid_stores = total_stores - free_stores
        # Davriy tekshiruv (apps/stores/tasks.py check_all_bot_health) oxirgi
        # marta XATO topgan bizneslar soni — "bot_health_ok=None" (hali
        # tekshirilmagan) bunga kirmaydi, faqat ANIQ False.
        stores_with_bot_errors = Store.objects.filter(is_deleted=False, bot_health_ok=False).count()
        now = _timezone.now()
        stores_subscription_expiring_soon = Store.objects.filter(
            is_deleted=False, is_active=True,
            subscription_ends_at__gte=now, subscription_ends_at__lte=now + timedelta(days=7),
        ).count()
        stores_subscription_expired = Store.objects.filter(
            is_deleted=False, is_active=True, subscription_ends_at__lt=now,
        ).count()
        total_leads = Lead.objects.filter(is_deleted=False).count()
        total_customers = Customer.objects.filter(is_deleted=False).count()
        # ⚠️ BUG FIX: `_timezone.now().date()` UTC sanasini beradi, mahalliy
        # (Asia/Tashkent, UTC+5) sanani emas — `apps/orders/views.py`dagi
        # xuddi shu xato bilan bir xil sabab (jonli tekshirishda aniqlandi,
        # u yerda ham tuzatilgan). `timezone.localtime()` to'g'ri sanani beradi.
        leads_today = Lead.objects.filter(
            is_deleted=False, created_at__date=_timezone.localtime(_timezone.now()).date(),
        ).count()

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
            "disabled_stores": disabled_stores,
            "free_stores": free_stores,
            "paid_stores": paid_stores,
            "stores_with_bot_errors": stores_with_bot_errors,
            "stores_subscription_expiring_soon": stores_subscription_expiring_soon,
            "stores_subscription_expired": stores_subscription_expired,
            "total_leads": total_leads,
            "total_customers": total_customers,
            "leads_today": leads_today,
            "bot_active": bot_active,
            "bot_username": f"@{bot_username}" if bot_username != "unknown" else None,
            "stores": stores_list
        }, status=status.HTTP_200_OK)


def _extract_tg_admin_chat_id(username: str) -> str | None:
    """`"tg_admin_<chat_id>"` formatidagi username'dan chat_id'ni ajratib oladi — bo'lmasa `None`."""
    prefix = "tg_admin_"
    if username.startswith(prefix):
        return username[len(prefix):]
    return None


class SuperAdminTelegramLoginView(APIView):
    """
    Super Admin panelga LeadNode bot orqali (Telegram WebApp initData bilan)
    kirish — login+parol o'rniga QO'SHIMCHA (zaxira sifatida parol ham
    ishlaydi) qulay usul.
    POST /api/v1/superadmin/telegram-login/  body: {"init_data": "..."}

    Xavfsizlik: faqat `settings.SUPERADMIN_TG_CHAT_IDS` ro'yxatidagi
    Telegram chat_id'lar (imzosi MASTER bot tokeni bilan tasdiqlangan
    initData orqali) kira oladi — bu ro'yxat biror Store egaligidan
    MUSTAQIL, faqat platforma xodimlari uchun.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import json
        from urllib.parse import unquote

        from django.conf import settings
        from django.contrib.auth.models import User
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.core.authentication import TelegramInitDataAuthentication

        init_data = request.data.get("init_data", "")
        if not init_data:
            return Response({"error": "initData berilmagan"}, status=status.HTTP_400_BAD_REQUEST)

        parsed = {}
        for part in init_data.split("&"):
            if "=" in part:
                key, _, value = part.partition("=")
                parsed[key] = unquote(value)

        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return Response({"error": "initData'da 'hash' topilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        master_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not master_token or not TelegramInitDataAuthentication._check_hmac(
            master_token, data_check_string, received_hash
        ):
            return Response({"error": "initData imzosi noto'g'ri"}, status=status.HTTP_403_FORBIDDEN)

        try:
            user_data = json.loads(parsed.get("user", "{}"))
        except (json.JSONDecodeError, TypeError):
            return Response({"error": "initData.user formati noto'g'ri"}, status=status.HTTP_400_BAD_REQUEST)

        telegram_user_id = str(user_data.get("id", "")).strip()
        if not telegram_user_id or telegram_user_id not in settings.SUPERADMIN_TG_CHAT_IDS:
            return Response(
                {"error": "Bu Telegram akkaunt platforma xodimi sifatida ro'yxatdan o'tmagan."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ⚠️ Foydalanuvchi "Chiqish" bosgan bo'lsa, buni ESLAB QOLISH shart —
        # LEKIN faqat frontend `localStorage`iga ishonib bo'lmaydi: ba'zi
        # Telegram mini-app WebView'lari ilova yopilganda (masalan burchakdagi
        # "X" bilan) saytning localStorage'ini TOZALAB yuboradi (jonli
        # holatda aniqlandi — bu Telegram platformasining o'zi, bizning
        # kodimiz emas). Shu sabab "chiqib ketgan" holati SERVER tomonida
        # (keshda) saqlanadi — bu klient tomonidagi saqlash qanday
        # ishlashidan mustaqil, har doim ishonchli.
        from django.core.cache import cache

        logout_flag_key = f"superadmin_tg_logged_out:{telegram_user_id}"
        if cache.get(logout_flag_key):
            return Response(
                {"error": "Siz chiqib ketgansiz. Iltimos, login va parol bilan qayta kiring."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Shu chat_id uchun doimiy, Telegram orqali boshqariladigan staff
        # hisob — parol bilan kirib bo'lmaydi (unusable), faqat shu yo'l bilan.
        # ⚠️ `username` ("tg_admin_<chat_id>") ichki texnik identifikator —
        # frontendda HECH QACHON to'g'ridan-to'g'ri ko'rsatilmasligi kerak
        # (chat_id'ni ochib qo'yadi). Shuning uchun Telegram'dagi haqiqiy
        # ismni (`first_name`) alohida saqlaymiz — `SuperAdminMeView` shuni
        # qaytaradi, `username`ni emas.
        username = f"tg_admin_{telegram_user_id}"
        real_name = str(user_data.get("first_name", "")).strip()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True, "first_name": real_name},
        )
        if created:
            user.set_unusable_password()
            user.save()
        elif real_name and user.first_name != real_name:
            user.first_name = real_name
            user.save(update_fields=["first_name"])

        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=status.HTTP_200_OK)


class SuperAdminMeView(APIView):
    """
    Super Admin panelining login sahifasi shu endpointni JWT olingandan
    keyin DARHOL chaqiradi — token haqiqatan ham platforma xodimiga
    (is_staff) tegishli ekanini tasdiqlash uchun.

    ⚠️ `/api/v1/token/` o'zi FAQAT parolni tekshiradi, `is_staff`ni emas —
    ya'ni parolga ega har qanday oddiy foydalanuvchi ham token ola oladi.
    Shu sabab frontend token olgandan keyin BU endpointni chaqirib, 403
    kelsa "siz platforma xodimi emassiz" deb aniq xabar bera oladi —
    aks holda xato keyinroq, chalkash joyda chiqib qolardi.
    GET /api/v1/superadmin/me/
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        # ⚠️ `username` (Telegram orqali kirganlar uchun "tg_admin_<chat_id>"
        # bo'lishi mumkin — ichki, texnik format, chat_id'ni ochib qo'yadi)
        # frontendga ATAYLAB yuborilmaydi. `display_name` — foydalanuvchiga
        # ko'rsatish uchun xavfsiz qiymat: haqiqiy ism bo'lsa o'sha,
        # bo'lmasa (parol orqali kirgan, username'ni o'zi tanlagan holatlar
        # uchun) username'ning o'zi ko'rsatiladi.
        display_name = request.user.first_name.strip() or request.user.username

        # Muvaffaqiyatli autentifikatsiyadan o'tgan (istalgan usul —
        # Telegram YOKI parol) — demak foydalanuvchi ANIQ qayta kirmoqchi,
        # "chiqib ketgan" belgisi endi eskirgan, tozalaymiz.
        chat_id = _extract_tg_admin_chat_id(request.user.username)
        if chat_id:
            from django.core.cache import cache
            cache.delete(f"superadmin_tg_logged_out:{chat_id}")

        return Response({
            "display_name": display_name,
            "is_staff": True,
        }, status=status.HTTP_200_OK)


class SuperAdminTelegramLogoutView(APIView):
    """
    "Chiqish" bosilganda chaqiriladi (faqat Telegram orqali — `tg_admin_`
    hisoblar uchun) — SERVER tomonida "chiqib ketgan" belgisini qo'yadi.
    POST /api/v1/superadmin/telegram-logout/

    ⚠️ Nega SERVER tomonida (faqat `localStorage`da emas): ba'zi Telegram
    mini-app WebView'lari ilova yopilganda (masalan burchakdagi "X")
    saytning `localStorage`sini tozalab yuboradi — bu holda mahalliy
    belgi yo'qolib, keyingi ochilishda avtomatik Telegram-kirish yana
    ishlab ketardi (jonli holatda aynan shu holat aniqlandi).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        chat_id = _extract_tg_admin_chat_id(request.user.username)
        if chat_id:
            from django.core.cache import cache
            # 30 kun — "REFRESH_TOKEN_LIFETIME" bilan bir xil muddat: shu
            # vaqt ichida qayta avtomatik Telegram-kirish bloklanadi.
            cache.set(f"superadmin_tg_logged_out:{chat_id}", True, timeout=60 * 60 * 24 * 30)
        return Response({"success": True}, status=status.HTTP_200_OK)


class SuperAdminBusinessListCreateView(generics.ListCreateAPIView):
    """
    Super Admin — barcha bizneslar ro'yxati (qidiruv/filtr/pagination
    bilan) va yangi biznes yaratish.
    GET  /api/v1/superadmin/businesses/  — ro'yxat
    POST /api/v1/superadmin/businesses/  — yangi do'kon yaratish

    ⚠️ `SuperAdminStatsView`dan ATAYLAB alohida — u yerdagi statistika
    javobi (barcha do'konlarni sahifasiz qaytaradi) o'zgarishsiz qoladi,
    bu yerda esa haqiqiy pagination/qidiruv/filtr bilan mustaqil rivojlanadi.
    """
    permission_classes = [permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SuperAdminBusinessCreateSerializer
        return SuperAdminBusinessListSerializer

    def get_queryset(self):
        from django.db.models import Count, Q

        from .models import Store

        qs = Store.objects.filter(is_deleted=False).annotate(
            total_leads=Count("leads", filter=Q(leads__is_deleted=False))
        ).order_by("-created_at")

        search = self.request.query_params.get("search", "").strip()
        if search:
            # ⚠️ Faqat biznes nomi emas — egasining Telegram @username'i
            # (Customer.username, xuddi SuperAdminBusinessDetailSerializer
            # TWA kirish bo'limida qilgani kabi) va raw chat_id bo'yicha
            # ham qidirish mumkin bo'lishi kerak (spec: "Business name,
            # Username, TWA owner, Other useful identifiers").
            from apps.customers.models import Customer

            owner_chat_ids_by_username = Customer.objects.filter(
                username__icontains=search,
            ).values_list("platform_user_id", flat=True)

            qs = qs.filter(
                Q(name__icontains=search)
                | Q(tg_owner_chat_id__icontains=search)
                | Q(tg_owner_chat_id__in=list(owner_chat_ids_by_username))
            )

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")

        # "has_token=false" — shaxsiy bot tokeni ulanmagan (hali ham
        # umumiy MASTER tokendan foydalanayotgan) bizneslarni ajratadi.
        # ⚠️ `tg_bot_token` shifrlangan (Fernet) — shu sabab ORM'da
        # to'g'ridan-to'g'ri tenglikni solishtirib bo'lmaydi (har safar
        # boshqa shifrlangan natija). Shu uchun deterministik
        # `tg_bot_token_hash` ustuni ishlatiladi (xuddi
        # `_get_store_by_token`dagi kabi).
        has_token = self.request.query_params.get("has_token")
        if has_token is not None:
            from apps.core.fields import sha256_hex

            master_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
            master_hash = sha256_hex(master_token) if master_token else None
            if has_token.lower() == "false":
                qs = qs.filter(Q(tg_bot_token_hash__isnull=True) | Q(tg_bot_token_hash="") | Q(tg_bot_token_hash=master_hash))
            else:
                qs = qs.exclude(Q(tg_bot_token_hash__isnull=True) | Q(tg_bot_token_hash="") | Q(tg_bot_token_hash=master_hash))

        # "bot_error=true" — davriy tekshiruv (apps/stores/tasks.py
        # check_all_bot_health) oxirgi marta XATO topgan bizneslarni
        # ajratadi. `bot_health_ok=None` (hali tekshirilmagan — masalan
        # umumiy bot ishlatadigan) bunga kirmaydi, faqat ANIQ `False`.
        if self.request.query_params.get("bot_error", "").lower() == "true":
            qs = qs.filter(bot_health_ok=False)

        return qs

    def create(self, request, *args, **kwargs):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import StoreProvisioningError, provision_store

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = provision_store(**serializer.validated_data)
        except StoreProvisioningError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        store = result["store"]
        log_action(
            actor=request.user, action=AuditLog.Action.BUSINESS_CREATED, store=store,
            metadata={"category_type": store.category_type, "has_own_bot": store.has_own_bot},
        )
        return Response({
            "id": str(store.id),
            "name": store.name,
            "admin_link": result["admin_link"],
            "customer_link": result["customer_link"],
        }, status=status.HTTP_201_CREATED)


def _get_active_store_or_none(pk):
    try:
        return Store.objects.get(pk=pk, is_deleted=False)
    except (Store.DoesNotExist, ValueError, TypeError):
        return None


class SuperAdminBusinessDetailView(APIView):
    """
    Super Admin — bitta biznesning to'liq tafsilotlari.
    GET /api/v1/superadmin/businesses/<uuid:pk>/
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, pk):
        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)
        return Response(SuperAdminBusinessDetailSerializer(store).data, status=status.HTTP_200_OK)


class SuperAdminBusinessDisableView(APIView):
    """Super Admin — biznesni vaqtincha to'xtatish (TWA + AI bot). POST .../disable/"""
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import set_store_active

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        result = set_store_active(store, False)
        if result["changed"]:
            log_action(actor=request.user, action=AuditLog.Action.BUSINESS_DISABLED, store=store)
        return Response({"success": True, "is_active": result["is_active"]}, status=status.HTTP_200_OK)


class SuperAdminBusinessReactivateView(APIView):
    """Super Admin — vaqtincha to'xtatilgan biznesni qayta faollashtirish. POST .../reactivate/"""
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import set_store_active

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        result = set_store_active(store, True)
        if result["changed"]:
            log_action(actor=request.user, action=AuditLog.Action.BUSINESS_REACTIVATED, store=store)
        return Response({"success": True, "is_active": result["is_active"]}, status=status.HTTP_200_OK)


def _compute_admin_link(store) -> str | None:
    if not store.tg_bot_username:
        return None
    return f"https://t.me/{store.tg_bot_username}?start=admin_{store.id}"


class SuperAdminTWAAccessRevokeView(APIView):
    """
    Super Admin — hozirgi TWA egasini bo'shatish (`tg_owner_chat_id`ni
    tozalash). Do'konning o'zi, ma'lumotlari va sozlamalari o'zgarmaydi.
    POST .../access/revoke/
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import revoke_store_owner

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        result = revoke_store_owner(store)
        if not result["changed"]:
            return Response({"error": "Bu biznesda hozir ega biriktirilmagan."}, status=status.HTTP_400_BAD_REQUEST)

        log_action(actor=request.user, action=AuditLog.Action.TWA_ACCESS_REVOKED, store=store)
        return Response({"success": True, "admin_link": _compute_admin_link(store)}, status=status.HTTP_200_OK)


class SuperAdminTWAAccessRestoreView(APIView):
    """
    Super Admin — bo'shatilgan TWA kirish huquqini "tiklash": yangi
    (yoki eski) foydalanuvchi admin havolasini qayta bosishi uchun uni
    qayta ko'rsatadi. Haqiqiy DB o'zgarishi yo'q — chunki bog'lash
    Telegram tomonidan `/start admin_<uuid>` bosilganda avtomatik sodir
    bo'ladi (`apps/webhooks/tasks.py`). Faqat biznes HOZIR egasiz
    bo'lgandagina ma'noga ega.
    POST .../access/restore/
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        if store.tg_owner_chat_id:
            return Response(
                {"error": "Bu biznesda hozir ega bor — avval 'Bekor qilish' (revoke) qiling."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        log_action(actor=request.user, action=AuditLog.Action.TWA_ACCESS_RESTORED, store=store)
        return Response({"success": True, "admin_link": _compute_admin_link(store)}, status=status.HTTP_200_OK)


class SuperAdminTWAAccessChangeOwnerView(APIView):
    """
    Super Admin — TWA foydalanuvchisini majburan almashtirish: hozirgi
    egani (agar bor bo'lsa) bo'shatadi va admin havolasini qaytaradi —
    yangi foydalanuvchi shu havolani bosganda avtomatik bog'lanadi.
    POST .../access/change-owner/
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import revoke_store_owner

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        revoke_store_owner(store)  # unconditional — o'zgarish bo'lmasa ham davom etadi
        log_action(actor=request.user, action=AuditLog.Action.TWA_ACCESS_CHANGED, store=store)
        return Response({"success": True, "admin_link": _compute_admin_link(store)}, status=status.HTTP_200_OK)


class SuperAdminTokenConnectView(APIView):
    """
    Super Admin — biznesga shaxsiy Telegram bot tokenini ulash (egasi
    o'rniga administrator tomonidan). Mavjud `connect_telegram_bot_to_store`
    xizmat funksiyasini o'zgarishsiz chaqiradi.
    POST .../token/connect/  body: {"bot_token": "..."}
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import connect_telegram_bot_to_store

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        serializer = SuperAdminTokenConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = connect_telegram_bot_to_store(store, serializer.validated_data["bot_token"])
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[SuperAdmin] Token ulashda kutilmagan xato: {e}", exc_info=True)
            return Response({"error": "Telegram bilan ulanishda kutilmagan xato yuz berdi"}, status=status.HTTP_502_BAD_GATEWAY)

        log_action(
            actor=request.user, action=AuditLog.Action.TOKEN_CONNECTED, store=store,
            metadata={"bot_username": result.get("bot_username")},
        )
        return Response(result, status=status.HTTP_200_OK)


class SuperAdminTokenDisconnectView(APIView):
    """
    Super Admin — biznesning shaxsiy bot tokenini uzish (umumiy demo
    botga qaytaradi). POST .../token/disconnect/
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action
        from apps.stores.services import disconnect_telegram_bot_from_store

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        result = disconnect_telegram_bot_from_store(store)
        log_action(actor=request.user, action=AuditLog.Action.TOKEN_DISCONNECTED, store=store)
        return Response(result, status=status.HTTP_200_OK)


class SuperAdminSubscriptionPlanView(APIView):
    """Super Admin — biznesning obuna rejasini o'zgartirish. PATCH .../subscription/"""
    permission_classes = [permissions.IsAdminUser]

    def patch(self, request, pk):
        from apps.audit.models import AuditLog
        from apps.audit.services import log_action

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        serializer = SuperAdminSubscriptionPlanUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = ["updated_at"]
        old_plan = store.subscription_plan
        if "subscription_plan" in data:
            store.subscription_plan = data["subscription_plan"]
            update_fields.append("subscription_plan")
        if "monthly_message_limit" in data:
            store.monthly_message_limit = data["monthly_message_limit"]
            update_fields.append("monthly_message_limit")

        old_ends_at = store.subscription_ends_at
        if "subscription_ends_at" in data:
            store.subscription_ends_at = data["subscription_ends_at"]
            update_fields.append("subscription_ends_at")
        store.save(update_fields=update_fields)

        if "subscription_plan" in data:
            log_action(
                actor=request.user, action=AuditLog.Action.SUBSCRIPTION_PLAN_CHANGED, store=store,
                metadata={"old_plan": old_plan, "new_plan": store.subscription_plan},
            )
        if "subscription_ends_at" in data:
            log_action(
                actor=request.user, action=AuditLog.Action.SUBSCRIPTION_DATE_CHANGED, store=store,
                metadata={
                    "old_ends_at": old_ends_at.isoformat() if old_ends_at else None,
                    "new_ends_at": store.subscription_ends_at.isoformat() if store.subscription_ends_at else None,
                },
            )
        return Response(
            {
                "subscription_plan": store.subscription_plan,
                "monthly_message_limit": store.monthly_message_limit,
                "subscription_ends_at": store.subscription_ends_at,
            },
            status=status.HTTP_200_OK,
        )


class SuperAdminBusinessStatisticsView(APIView):
    """
    Super Admin — bitta biznesning to'liq voronka statistikasi (oylik
    dinamika bilan) — "Statistika" sahifasi uchun.
    GET /api/v1/superadmin/businesses/<uuid:pk>/statistics/

    ⚠️ Javob shakli `LeadViewSet.stats` (do'kon egasining o'z TWA'si)
    bilan AYNAN bir xil — ikkisi ham `apps.orders.services.compute_store_funnel_stats`
    AYNAN shu funksiyasini chaqiradi, mantiq takrorlanmaydi.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, pk):
        from apps.orders.services import compute_store_funnel_stats

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        stats = compute_store_funnel_stats(store)
        return Response({"store_id": str(store.id), "store_name": store.name, **stats})


class SuperAdminBusinessDeleteView(APIView):
    """
    Super Admin — biznesni BUTUNLAY o'chirish (soft-delete, hech qanday
    "qayta tiklash" tugmasi UI'da yo'q — amalda qaytarib bo'lmaydigan).
    POST /api/v1/superadmin/businesses/<uuid:pk>/delete/
    Body: {"username": "...", "password": "..."}

    ⚠️ ENG XAVFLI amal — shuning uchun ikki qatlamli himoya:
    1. `IsAdminUser` — chaqiruvchi sessiya allaqachon platforma xodimi
       bo'lishi kerak (boshqa barcha SuperAdmin view'lar bilan bir xil).
    2. Qo'shimcha parol bilan qayta tasdiqlash — HOZIRGI sessiyadan
       MUSTAQIL (`request.user`ga emas, faqat `authenticate()`ga
       tayanadi), chunki Telegram orqali kirgan sessiyalarda parol
       UMUMAN yo'q (unusable password) — ular ham shu amalni, boshqa
       (parolga ega) xodim hisobi bilan tasdiqlab, bajara olishi kerak.
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from django.contrib.auth import authenticate

        from apps.audit.models import AuditLog
        from apps.audit.services import log_action

        store = _get_active_store_or_none(pk)
        if not store:
            return Response({"error": "Biznes topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        serializer = SuperAdminDeleteReauthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reauth_user = authenticate(
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if reauth_user is None or not reauth_user.is_staff:
            return Response(
                {"error": "Login yoki parol noto'g'ri, yoki bu hisob platforma xodimi emas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        store_name = store.name
        store.soft_delete()

        log_action(
            actor=request.user, action=AuditLog.Action.BUSINESS_DELETED, store=store,
            metadata={"deleted_business_name": store_name, "reauth_username": reauth_user.username},
        )
        return Response({"success": True}, status=status.HTTP_200_OK)


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


class TelegramBotConnectView(APIView):
    """
    Do'kon egasining O'Z shaxsiy Telegram botini (@BotFather orqali
    yaratilgan) ulash — white-label: shundan keyin mijozlar, guruh va
    TWA autentifikatsiyasi umumiy demo bot o'rniga egasining o'z boti
    orqali ishlaydi.

    POST /api/v1/store/telegram/connect-bot/
    Body: {"bot_token": "123456:ABC-DEF..."}
    Response: {"success": true, "bot_username": "MeningBotim"}
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        store = get_store_from_request(request)
        if not store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        bot_token = (request.data.get("bot_token") or "").strip()
        if not bot_token:
            return Response({"error": "Bot token kiritilmagan"}, status=status.HTTP_400_BAD_REQUEST)

        from apps.stores.services import connect_telegram_bot_to_store

        try:
            result = connect_telegram_bot_to_store(store, bot_token)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Telegram bot connect kutilmagan xato: {e}", exc_info=True)
            return Response(
                {"error": "Telegram bilan ulanishda kutilmagan xato yuz berdi"},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class TelegramBotDisconnectView(APIView):
    """
    Do'kon egasining shaxsiy Telegram botini uzish — do'kon umumiy demo
    botga qaytadi.

    DELETE /api/v1/store/telegram/disconnect-bot/
    Response: {"success": true}
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request):
        store = get_store_from_request(request)
        if not store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        from apps.stores.services import disconnect_telegram_bot_from_store

        result = disconnect_telegram_bot_from_store(store)
        return Response(result, status=status.HTTP_200_OK)


class StoreAIStatusView(APIView):
    """
    Biznes egasi TWA dashboardidagi "AI Assistant" holat kartasi uchun —
    "Mening AI'im ishlayaptimi? Telegram ulanishim sog'lommi?" savoliga
    bitta aniq javob.

    GET /api/v1/store/ai-status/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        store = get_store_from_request(request)
        if not store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        from .services import get_store_ai_status
        return Response(get_store_ai_status(store), status=status.HTTP_200_OK)


class TelegramGroupDisconnectView(APIView):
    """
    Do'kondan bog'langan Telegram guruhini uzish (egasi tasodifan
    noto'g'ri guruh qo'shib yuborgan bo'lsa, TWA'dan to'g'ridan-to'g'ri
    tuzatishi uchun).

    DELETE /api/v1/store/telegram/group/disconnect/

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

        from apps.stores.services import disconnect_telegram_group_from_store

        result = disconnect_telegram_group_from_store(store)
        return Response(result, status=status.HTTP_200_OK)


class StoreStaffMemberListCreateView(generics.ListCreateAPIView):
    """
    Do'kon egasi guruhda ishlaydigan xodimlarini (sotuv menejerlari)
    ro'yxatga oladi — bot ularga ham (egasiga o'xshab) mijoz kabi sotuv
    taklifi qilmasligi uchun.

    GET  /api/v1/store/staff/  -> ro'yxat
    POST /api/v1/store/staff/  -> yangi xodim qo'shish ({"tg_username": "...", "full_name": "..."})
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreStaffMemberSerializer

    def get_queryset(self):
        store = get_store_from_request(self.request)
        if not store:
            return StoreStaffMember.objects.none()
        return StoreStaffMember.objects.filter(store=store)

    def perform_create(self, serializer):
        store = get_store_from_request(self.request)
        if not store:
            from rest_framework.exceptions import NotFound
            raise NotFound("Do'kon topilmadi. Telegram yoki JWT orqali kiring.")
        serializer.save(store=store)


class StoreStaffMemberDeleteView(generics.DestroyAPIView):
    """
    DELETE /api/v1/store/staff/<id>/  -> xodimni ro'yxatdan o'chirish
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreStaffMemberSerializer

    def get_queryset(self):
        store = get_store_from_request(self.request)
        if not store:
            return StoreStaffMember.objects.none()
        return StoreStaffMember.objects.filter(store=store)

    def perform_destroy(self, instance):
        instance.soft_delete()
