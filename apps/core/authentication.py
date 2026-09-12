"""
Telegram Web App (TWA) initData Autentifikatsiya klassi.

Ishlash mantig'i:
1. Frontend 'X-Telegram-Init-Data' header'idan initData string oladi
2. HMAC-SHA256 imzosini tekshiradi (bot_token orqali)
3. Telegram user.id ni topadi
4. Shu user.id ga ega 'tg_owner_chat_id' li Store'ni qaytaradi
5. request.user = store.owner, request.auth = store (Store obyekti)

Foydalanish:
  settings.py → DEFAULT_AUTHENTICATION_CLASSES ga qo'shing
  yoki per-view: authentication_classes = [TelegramInitDataAuthentication]
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import cache
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger("apps.core")


class TelegramInitDataAuthentication(BaseAuthentication):
    """
    Telegram Mini App (TWA) üçün DRF Authentication klassi.

    Muvaffaqiyatli autentifikatsiyada qaytaradi:
        (store.owner, store)  →  request.user = store.owner,  request.auth = store

    initData yo'q bo'lsa None qaytaradi (keyingi auth klassi urinadi).
    initData noto'g'ri/muddati tugagan bo'lsa AuthenticationFailed ko'taradi.
    """

    def authenticate(self, request):
        init_data = request.headers.get("X-Telegram-Init-Data", "").strip()

        if not init_data:
            # Bu authentication klassi emas — JWT auth urinadi
            return None

        try:
            return self._validate_init_data(init_data)
        except AuthenticationFailed:
            raise
        except Exception as e:
            logger.warning(f"TelegramInitDataAuthentication kutilmagan xato: {e}", exc_info=True)
            raise AuthenticationFailed("Telegram autentifikatsiya xatosi")

    def _validate_init_data(self, init_data: str):
        """initData string ni tekshirib (user, store) tuple'ini qaytaradi."""
        from apps.stores.models import Store

        # 1. URL-encoded initData ni parse qilish
        parsed = {}
        for part in init_data.split("&"):
            if "=" in part:
                key, _, value = part.partition("=")
                parsed[key] = unquote(value)

        received_hash = parsed.pop("hash", None)
        if not received_hash:
            raise AuthenticationFailed("initData da 'hash' maydoni topilmadi")

        # 2. data-check-string yasash (kalitlarni alifbo tartibida saralash)
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # 3. HMAC imzosini tekshirish
        verified = False

        # Avval master bot token bilan sinash
        master_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if master_token and self._check_hmac(master_token, data_check_string, received_hash):
            verified = True

        # Master bot mos kelmasa — barcha aktiv do'kon bot tokenlari bilan sinash
        if not verified:
            store_tokens = Store.objects.filter(
                is_active=True,
                is_deleted=False,
                tg_bot_token__isnull=False,
            ).exclude(tg_bot_token__exact="").values_list("tg_bot_token", flat=True)

            for token in store_tokens:
                if self._check_hmac(token, data_check_string, received_hash):
                    verified = True
                    break

        if not verified:
            logger.warning("TelegramInitData: HMAC imzosi noto'g'ri — buzilgan yoki noto'g'ri token")
            raise AuthenticationFailed("Telegram initData imzosi noto'g'ri")

        # 4. auth_date muddatini tekshirish (maksimal 24 soat)
        auth_date = int(parsed.get("auth_date", 0))
        if auth_date and (time.time() - auth_date) > 86400:
            raise AuthenticationFailed("Telegram initData muddati tugagan (24 soatdan oshdi)")

        # 5. Telegram foydalanuvchi ID ni olish
        user_data_str = parsed.get("user", "{}")
        try:
            user_data = json.loads(user_data_str)
        except (json.JSONDecodeError, TypeError):
            raise AuthenticationFailed("initData.user JSON formati noto'g'ri")

        telegram_user_id = str(user_data.get("id", "")).strip()
        if not telegram_user_id:
            raise AuthenticationFailed("initData da user.id topilmadi")

        # 6. Bu Telegram ID ga ega do'konni topish (do'kon egasi)
        #
        # ⚠️ OPTIMIZATION: TWA dashboard har 3 soniyada poll qiladi va har
        # bir amal (buyurtma ochish, xabar yozish va h.k.) ham shu auth
        # klassidan o'tadi — ya'ni bu DB so'rovi HAR BIR TWA so'rovida
        # bajarilardi. Do'kon ma'lumotlari kamdan-kam o'zgargani uchun
        # (ega, tg_owner_chat_id, is_active) qisqa muddatli Redis kesh
        # bilan bu so'rovni deyarli butunlay bazadan olib tashlaymiz.
        cache_key = f"store_by_tgowner:{telegram_user_id}"
        store = cache.get(cache_key)

        if store is None:
            try:
                store = Store.objects.select_related("owner").get(
                    tg_owner_chat_id=telegram_user_id,
                    is_active=True,
                    is_deleted=False,
                )
                cache.set(cache_key, store, timeout=20)
            except Store.DoesNotExist:
                logger.warning(
                    f"TelegramInitData: Telegram ID={telegram_user_id} ga do'kon bog'lanmagan. "
                    f"Avval do'konni ro'yxatdan o'tkazing va tg_owner_chat_id ni to'ldiring."
                )
                raise AuthenticationFailed(
                    f"Bu Telegram akkaunt ({telegram_user_id}) hech qanday do'konga bog'lanmagan. "
                    "Iltimos, admin bilan bog'laning."
                )

        logger.debug(f"TelegramInitData auth OK: store='{store.name}', tg_id={telegram_user_id}")
        # request.user = store.owner (Django User)
        # request.auth = store (Store instance — _get_target_store() uchun)
        return (store.owner, store)

    @staticmethod
    def _check_hmac(bot_token: str, data_check_string: str, received_hash: str) -> bool:
        """
        Telegram HMAC-SHA256 imzosini tekshiradi.
        Algoritm: secret = HMAC(b'WebAppData', bot_token); hash = HMAC(secret, data_str)
        """
        try:
            secret_key = hmac.new(
                b"WebAppData",
                bot_token.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            computed = hmac.new(
                secret_key,
                data_check_string.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(computed, received_hash)
        except Exception as e:
            logger.debug(f"HMAC tekshiruv xatosi: {e}")
            return False

    def authenticate_header(self, request):
        return "TelegramInitData"


def get_store_from_request(request):
    """
    Helper funksiya: request dan joriy Store ni qaytaradi.

    Ustuvorlik tartibi:
    1. request.auth — TelegramInitDataAuthentication o'rnatgan Store
    2. request.user.store — JWT orqali autentifikatsiya bo'lgan egasi
    3. Hech narsa topilmasa — None qaytaradi (view 401/bo'sh natija qaytarishi kerak!)

    ⚠️  .first() fallback ataylab o'chirilgan — xavfsizlik uchun!

    ⚠️ XAVFSIZLIK TUZATISHI (KRITIK): avval bu yerda 3-fallback sifatida
    "X-Store-ID" header/`store_id` query param qabul qilinardi — va u
    berilgan store_id egasi so'rov yuborayotgan foydalanuvchi ekanini
    HECH QACHON tekshirmasdi. Natijada: `.store`ga ega bo'lmagan (masalan
    `createsuperuser` orqali yaratilgan admin akkaunt, yoki do'koni
    soft-delete qilingan sobiq ega) HAR QANDAY haqiqiy JWT bilan
    autentifikatsiyadan o'tgan foydalanuvchi shunchaki
    `X-Store-ID: <istalgan-do'kon-uuid>` header qo'shib, O'SHA DO'KONNING
    buyurtmalari, mahsulotlari, mijozlari, sozlamalari va suhbatlariga
    TO'LIQ CRUD huquqi bilan kira olardi — chunki bu header faqat
    "shu ID'li do'kon mavjudmi" ni tekshirardi, "so'rovchi shu do'konga
    tegishlimi" ni emas. Bu authentifikatsiyani chetlab o'tish (bypass)
    edi, shuning uchun butunlay olib tashlandi. Hech qanday joyda
    (frontend, ichki xizmatlar) bu headerga tayanilmagani tasdiqlandi.
    """
    from apps.stores.models import Store

    # 1. Telegram initData auth orqali o'rnatilgan store
    if hasattr(request, "auth") and isinstance(request.auth, Store):
        return request.auth

    # 2. JWT orqali autentifikatsiya bo'lgan foydalanuvchi
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        store = getattr(user, "store", None)
        if store and not store.is_deleted:
            return store

    # ❌ Hech narsa topilmadi — None qaytaradi (FALLBACK .first() YO'Q,
    # X-Store-ID FALLBACK ham YO'Q!)
    return None
