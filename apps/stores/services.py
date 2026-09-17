"""
Instagram / Meta Graph API Services — Token Management.

Bu modul Meta OAuth 2.0 token almashinuvi va Instagram akkauntini
do'konga ulash/uzish logikasini o'z ichiga oladi.

Meta Graph API versiyasi: v18.0

Token hayot davri:
  Short-lived user token  → ~1-2 soat
  Long-lived user token   → ~60 kun
  Long-lived page token   → hech qachon tugamaydi (token yangilangunicha)

Celery task (apps/stores/tasks.py) har kunda ishlab,
tugashiga 15 kun qolgan tokenlarni avtomatik yangilaydi.
"""
import logging
from datetime import timedelta
from typing import Optional

import httpx
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.stores")

META_GRAPH_VERSION = "v18.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"

# Token tugashiga necha kun qolganda yangilash boshlanadi
TOKEN_REFRESH_THRESHOLD_DAYS = 15


# ─────────────────────────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────────────────────

def _get_app_credentials() -> tuple[str, str]:
    """
    settings'dan META_APP_ID va META_APP_SECRET'ni oladi.
    Agar sozlanmagan bo'lsa — xato chiqaradi.
    """
    app_id = getattr(settings, "META_APP_ID", "")
    app_secret = getattr(settings, "META_APP_SECRET", "")
    if not app_id or not app_secret:
        raise ValueError(
            "META_APP_ID va META_APP_SECRET sozlanmagan! "
            ".env faylini tekshiring."
        )
    return app_id, app_secret


# ─────────────────────────────────────────────────────────────
# TASK 1A — Short-Lived → Long-Lived Token Exchange
# ─────────────────────────────────────────────────────────────

def exchange_short_to_long_lived_token(short_lived_token: str) -> dict:
    """
    Frontenddan kelgan short-lived user access token'ni
    Meta Graph API orqali 60 kunlik Long-Lived User Token'ga almashtiradi.

    Meta API: GET /oauth/access_token
      ?grant_type=fb_exchange_token
      &client_id={APP_ID}
      &client_secret={APP_SECRET}
      &fb_exchange_token={SHORT_LIVED_TOKEN}

    Args:
        short_lived_token: Frontend'dan kelgan qisqa muddatli token

    Returns:
        {
            "access_token": "...",
            "token_type": "bearer",
            "expires_in": 5183944   # sekund (~60 kun)
        }

    Raises:
        ValueError: Token almashtirish muvaffaqiyatsiz bo'lsa
    """
    app_id, app_secret = _get_app_credentials()

    url = f"{META_GRAPH_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_lived_token,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)

        data = response.json()

        if response.status_code != 200:
            error = data.get("error", {})
            logger.error(
                f"Meta token exchange xatosi: "
                f"code={error.get('code')} | "
                f"msg={error.get('message')}"
            )
            raise ValueError(
                f"Meta token almashtirish muvaffaqiyatsiz: "
                f"{error.get('message', 'Noma`lum xato')}"
            )

        if "access_token" not in data:
            logger.error(f"Meta token exchange: access_token yo'q | {data}")
            raise ValueError("Meta API'dan access_token kelmadi.")

        logger.info("Short-lived → Long-lived token almashinuvi muvaffaqiyatli.")
        return data

    except httpx.TimeoutException:
        logger.error("Meta token exchange: timeout (15s)")
        raise ValueError("Meta API bilan ulanish vaqti o'tdi. Qayta urinib ko'ring.")
    except httpx.RequestError as e:
        logger.error(f"Meta token exchange: so'rov xatosi: {e}", exc_info=True)
        raise ValueError(f"Meta API bilan ulanishda tarmoq xatosi: {e}")


# ─────────────────────────────────────────────────────────────
# TASK 1B — Facebook Sahifalar va IG Akkaunt Ma'lumotlarini Olish
# ─────────────────────────────────────────────────────────────

def get_facebook_pages(long_lived_token: str) -> list[dict]:
    """
    Long-lived user token orqali foydalanuvchining Facebook
    sahifalarini va ularga bog'langan Instagram Business
    akkauntlarini Meta API'dan tortib oladi.

    Meta API: GET /me/accounts
      ?fields=id,name,access_token,instagram_business_account
      &access_token={LONG_LIVED_TOKEN}

    Returns:
        [
            {
                "id": "PAGE_ID",
                "name": "Sahifa nomi",
                "access_token": "PAGE_ACCESS_TOKEN",
                "instagram_business_account": {
                    "id": "INSTAGRAM_BUSINESS_ACCOUNT_ID"
                }
            },
            ...
        ]
        Instagram ulanmagan sahifalar ham qaytadi lekin
        instagram_business_account maydoni bo'lmaydi.

    Raises:
        ValueError: API so'rov muvaffaqiyatsiz bo'lsa
    """
    url = f"{META_GRAPH_BASE}/me/accounts"
    params = {
        "fields": "id,name,access_token,instagram_business_account",
        "access_token": long_lived_token,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)

        data = response.json()

        if response.status_code != 200:
            error = data.get("error", {})
            logger.error(
                f"Meta sahifalar olishda xato: "
                f"code={error.get('code')} | "
                f"msg={error.get('message')}"
            )
            raise ValueError(
                f"Facebook sahifalarini olishda xato: "
                f"{error.get('message', 'Noma`lum xato')}"
            )

        pages = data.get("data", [])
        logger.info(f"Meta API: {len(pages)} ta Facebook sahifasi topildi.")
        return pages

    except httpx.TimeoutException:
        logger.error("Meta sahifalar: timeout (15s)")
        raise ValueError("Meta API bilan ulanish vaqti o'tdi.")
    except httpx.RequestError as e:
        logger.error(f"Meta sahifalar: so'rov xatosi: {e}", exc_info=True)
        raise ValueError(f"Meta API bilan ulanishda tarmoq xatosi: {e}")


def get_page_instagram_account_id(page_id: str, page_access_token: str) -> Optional[str]:
    """
    Facebook sahifa ID'si va uning access_token'i yordamida
    bog'langan Instagram Business Account ID'sini oladi.

    Meta API: GET /{PAGE_ID}?fields=instagram_business_account

    Returns:
        Instagram Business Account ID yoki None
    """
    url = f"{META_GRAPH_BASE}/{page_id}"
    params = {
        "fields": "instagram_business_account",
        "access_token": page_access_token,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)

        if response.status_code != 200:
            return None

        data = response.json()
        ig_account = data.get("instagram_business_account", {})
        return ig_account.get("id") if ig_account else None

    except Exception as e:
        logger.error(f"IG account ID olishda xato: {e}", exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────
# TASK 1C — Store'ga Instagram ulash (asosiy servis)
# ─────────────────────────────────────────────────────────────

def connect_instagram_to_store(store, short_lived_token: str, selected_page_id: str = None) -> dict:
    """
    Do'konga Instagram akkauntini ulashning to'liq jarayoni:

    1. Short-lived → Long-lived token almashtirish
    2. Foydalanuvchining Facebook sahifalarini olish
    3. Instagram Business Account ID'sini aniqlash
    4. Store modeliga saqlash

    Args:
        store: Store obyekti
        short_lived_token: Meta Login'dan kelgan qisqa muddatli token
        selected_page_id: Agar foydalanuvchida bir nechta sahifa bo'lsa,
                          frontend qaysi sahifani tanlashini yuboradi.
                          None bo'lsa — Instagram akkauntga ulanganini avtomatik topadi.

    Returns:
        {
            "success": True,
            "ig_page_id": "...",
            "ig_username": "...",   # ixtiyoriy, agar Meta bersa
            "pages_count": 2,       # Foydalanuvchidagi jami sahifalar soni
            "pages": [...]          # Frontend'ga sahifalar ro'yxati (foydalanuvchi tanlashi uchun)
        }

    Raises:
        ValueError: Agar Instagram akkaunt topilmasa yoki xato bo'lsa
    """

    # ── 1. Token almashtirish ─────────────────────────────────
    try:
        token_data = exchange_short_to_long_lived_token(short_lived_token)
    except ValueError as e:
        raise ValueError(f"Token almashtirish xatosi: {e}")

    long_lived_token = token_data["access_token"]
    expires_in_seconds = token_data.get("expires_in", 5183944)  # default ~60 kun
    token_expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)

    # ── 2. Facebook sahifalarni olish ─────────────────────────
    try:
        pages = get_facebook_pages(long_lived_token)
    except ValueError as e:
        raise ValueError(f"Facebook sahifalarini olishda xato: {e}")

    if not pages:
        raise ValueError(
            "Bu Facebook akkauntga biriktirilgan sahifa topilmadi. "
            "Instagram Business Account'ni Facebook sahifasiga ulang."
        )

    # ── 3. Instagram ulanganini topish ────────────────────────
    # Instagram Business akkauntiga ega sahifani topamiz
    instagram_pages = [
        p for p in pages
        if p.get("instagram_business_account")
    ]

    if not instagram_pages:
        raise ValueError(
            "Facebook sahifangizga ulanган Instagram Business "
            "akkaunt topilmadi. Instagram profilingizni Business "
            "yoki Creator'ga o'tkazing va Facebook sahifangizga ulang."
        )

    # Agar frontend ma'lum bir sahifani tanlagan bo'lsa
    if selected_page_id:
        chosen_page = next(
            (p for p in instagram_pages if p["id"] == selected_page_id),
            None
        )
        if not chosen_page:
            raise ValueError(
                f"Tanlangan sahifa (ID: {selected_page_id}) "
                f"Instagram akkauntga ulanmagan."
            )
    else:
        # Birinchi Instagram'ga ulanganini oladi
        chosen_page = instagram_pages[0]

    page_id = chosen_page["id"]
    page_access_token = chosen_page.get("access_token", long_lived_token)
    ig_account_id = chosen_page["instagram_business_account"]["id"]

    # ── 4. Store'ga saqlash ───────────────────────────────────
    store.ig_page_id = ig_account_id         # Instagram Business Account ID
    store.ig_access_token = page_access_token
    store.ig_token_expires_at = token_expires_at
    store.save(update_fields=[
        "ig_page_id",
        "ig_access_token",
        "ig_token_expires_at",
        "updated_at",
    ])

    logger.info(
        f"[Instagram Connect] Muvaffaqiyatli ulandi: "
        f"store={store.name} | ig_id={ig_account_id} | "
        f"page_id={page_id} | expires={token_expires_at.date()}"
    )

    result = {
        "success": True,
        "ig_page_id": ig_account_id,
        "facebook_page_id": page_id,
        "facebook_page_name": chosen_page.get("name", ""),
        "token_expires_at": token_expires_at.isoformat(),
        "pages_count": len(pages),
    }

    # Agar bir nechta sahifa bo'lsa va hali tanlanmagan bo'lsa —
    # frontendga sahifalar ro'yxatini ham yuboramiz
    if len(instagram_pages) > 1 and not selected_page_id:
        result["pages"] = [
            {
                "page_id": p["id"],
                "page_name": p.get("name", ""),
                "ig_account_id": p["instagram_business_account"]["id"],
            }
            for p in instagram_pages
        ]
        result["requires_page_selection"] = True

    return result


# ─────────────────────────────────────────────────────────────
# TASK 1D — Store'dan Instagram uzish
# ─────────────────────────────────────────────────────────────

def disconnect_instagram_from_store(store) -> dict:
    """
    Do'kondan Instagram akkauntini uzadi.
    Store modelidagi ig_* maydonlarni tozalaydi.

    Args:
        store: Store obyekti

    Returns:
        {"success": True}
    """
    store.ig_page_id = None
    store.ig_access_token = None
    store.ig_token_expires_at = None
    store.save(update_fields=[
        "ig_page_id",
        "ig_access_token",
        "ig_token_expires_at",
        "updated_at",
    ])

    logger.info(
        f"[Instagram Disconnect] Uzildi: store={store.name}"
    )
    return {"success": True}


# ─────────────────────────────────────────────────────────────
# Telegram Guruhini Store'dan Uzish
# ─────────────────────────────────────────────────────────────

def disconnect_telegram_group_from_store(store) -> dict:
    """
    Do'kondan bog'langan Telegram guruhini uzadi (bog'lanishni bekor
    qiladi — bot guruhning o'zidan chiqarilmaydi, faqat endi u guruhdagi
    xabarlarga AI sifatida javob bermay qo'yadi).

    ⚠️ Egasi botni tasodifan/adashib NOTO'G'RI guruhga qo'shib yuborishi
    mumkin — bunday holatda avval yagona chora bot'ni Telegram'ning o'zida
    guruhdan qo'lda olib tashlash edi. Endi TWA Sozlamalar sahifasida
    to'g'ridan-to'g'ri "Uzib qo'yish" tugmasi bilan ham bajarish mumkin —
    foydalanuvchi buni aniq so'radi.

    Args:
        store: Store obyekti

    Returns:
        {"success": True}
    """
    store.tg_group_chat_id = None
    store.save(update_fields=["tg_group_chat_id", "updated_at"])

    logger.info(
        f"[Telegram Guruh Disconnect] Uzildi: store={store.name}"
    )
    return {"success": True}


# ─────────────────────────────────────────────────────────────
# TASK 1E — Token Yangilash (Refresh)
# ─────────────────────────────────────────────────────────────

def refresh_token_for_store(store) -> bool:
    """
    Store'ning Instagram access token'ini Meta Graph API orqali yangilaydi.

    Meta Graph API: GET /oauth/access_token
      ?grant_type=fb_exchange_token
      &client_id={APP_ID}
      &client_secret={APP_SECRET}
      &fb_exchange_token={EXISTING_LONG_LIVED_TOKEN}

    Faqat Long-Lived tokenlarni yangilash mumkin.

    Args:
        store: Store obyekti (ig_access_token mavjud bo'lishi kerak)

    Returns:
        True — muvaffaqiyatli yangilandi
        False — xato (log yoziladi)
    """
    if not store.ig_access_token:
        logger.warning(
            f"[Token Refresh] Token yo'q: store={store.name}"
        )
        return False

    app_id, app_secret = _get_app_credentials()
    url = f"{META_GRAPH_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": store.ig_access_token,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)

        data = response.json()

        if response.status_code != 200:
            error = data.get("error", {})
            error_code = error.get("code", 0)
            logger.error(
                f"[Token Refresh] Xato: store={store.name} | "
                f"code={error_code} | msg={error.get('message')}"
            )
            # Token o'lgan bo'lsa (190, 102) — ig_access_token'ni tozalaymiz
            if error_code in (190, 102, 104):
                store.ig_access_token = None
                store.ig_token_expires_at = None
                store.save(update_fields=["ig_access_token", "ig_token_expires_at", "updated_at"])
                logger.error(
                    f"[Token Refresh] Token o'lgan, tozalandi: store={store.name}. "
                    f"Do'kon egasi qayta ulashi kerak."
                )
            return False

        new_token = data.get("access_token")
        expires_in = data.get("expires_in", 5183944)

        if not new_token:
            logger.error(
                f"[Token Refresh] Yangi token kelmadi: store={store.name}"
            )
            return False

        store.ig_access_token = new_token
        store.ig_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        store.save(update_fields=["ig_access_token", "ig_token_expires_at", "updated_at"])

        logger.info(
            f"[Token Refresh] Muvaffaqiyatli yangilandi: store={store.name} | "
            f"expires={store.ig_token_expires_at.date()}"
        )
        return True

    except httpx.TimeoutException:
        logger.error(f"[Token Refresh] Timeout: store={store.name}")
        return False
    except Exception as e:
        logger.error(
            f"[Token Refresh] Kutilmagan xato: store={store.name} | {e}",
            exc_info=True,
        )
        return False
