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
from django.core.cache import cache
from django.utils import timezone

from .models import Store
from apps.core.fields import sha256_hex

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
# Do'kon egasining shaxsiy Telegram botini ulash (white-label)
# ─────────────────────────────────────────────────────────────

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def connect_telegram_bot_to_store(store, bot_token: str) -> dict:
    """
    Do'kon egasi @BotFather'dan olgan O'Z shaxsiy bot tokenini ulaydi —
    shundan keyin mijozlar, guruh va TWA autentifikatsiyasi umumiy demo
    bot o'rniga to'liq EGASINING O'Z boti orqali ishlaydi (webhook
    marshrutlash — apps/webhooks/urls.py'dagi `telegram/<bot_token>/`
    yo'li — allaqachon bot-token asosida ishlaydi, shuning uchun bu
    yerda faqat: tokenni tekshirish, webhook o'rnatish va saqlash kifoya).

    Dashboard Menyu tugmasi bu yerda ATAYLAB o'rnatilmaydi — egasi o'z
    botiga birinchi marta /start bosganda avtomatik o'rnatiladi
    (apps/webhooks/tasks.py, mavjud kod, o'zgarishsiz ishlayveradi).

    Args:
        store: Store obyekti (ulanadigan do'kon)
        bot_token: @BotFather bergan token (masalan "123456:ABC-DEF...")

    Returns:
        {"success": True, "bot_username": "MeningBotim"}

    Raises:
        ValueError: token bo'sh/noto'g'ri, allaqachon boshqa do'konga
                    ulangan, yoki Telegram API bilan bog'lanib bo'lmasa
    """
    bot_token = (bot_token or "").strip()
    if not bot_token:
        raise ValueError("Bot token kiritilmagan")

    master_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if master_token and bot_token == master_token:
        raise ValueError(
            "Bu tizimning umumiy (demo) boti — shaxsiy bot sifatida ulab bo'lmaydi. "
            "@BotFather orqali YANGI bot yarating."
        )

    # ⚠️ Boshqa do'kon allaqachon shu tokendan foydalanayotgan bo'lishi
    # mumkin (masalan tasodifan boshqa egadan nusxa olingan) — bunday
    # holatda ikkala do'kon ham bir-birining xabarlarini ola boshlaydi.
    # tg_bot_token endi shifrlangan — hash orqali qidiramiz (yuqoridagi
    # apps/webhooks/views.py::_get_store_by_token bilan bir xil sabab).
    already_used = (
        Store.objects.exclude(pk=store.pk)
        .filter(tg_bot_token_hash=sha256_hex(bot_token), is_active=True, is_deleted=False)
        .exists()
    )
    if already_used:
        raise ValueError(
            "Bu bot tokeni allaqachon boshqa do'konga ulangan. "
            "Har bir do'kon uchun ALOHIDA (@BotFather'da yangi) bot yarating."
        )

    public_url = getattr(settings, "PUBLIC_URL", "")
    if not public_url:
        raise ValueError("Server hali ochiq manzilga (PUBLIC_URL) ega emas — administratorga murojaat qiling.")

    # ── 1. Tokenni tekshirish (getMe) ─────────────────────────
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(f"{TELEGRAM_API_BASE}{bot_token}/getMe")
        data = res.json()
    except httpx.TimeoutException:
        raise ValueError("Telegram API bilan bog'lanish vaqti o'tdi. Qayta urinib ko'ring.")
    except httpx.RequestError as e:
        raise ValueError(f"Telegram API bilan bog'lanishda tarmoq xatosi: {e}")

    if not data.get("ok"):
        raise ValueError(
            "Bot tokeni noto'g'ri. @BotFather'dan olgan tokenni to'g'ri nusxalaganingizga ishonch hosil qiling."
        )

    bot_username = data["result"].get("username", "")

    # ── 2. Webhook o'rnatish ───────────────────────────────────
    webhook_url = f"{public_url}/webhook/telegram/{bot_token}/"
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(
                f"{TELEGRAM_API_BASE}{bot_token}/setWebhook",
                json={
                    "url": webhook_url,
                    "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
                },
            )
        res_data = res.json()
    except httpx.TimeoutException:
        raise ValueError("Telegram webhook o'rnatishda ulanish vaqti o'tdi. Qayta urinib ko'ring.")
    except httpx.RequestError as e:
        raise ValueError(f"Telegram webhook o'rnatishda tarmoq xatosi: {e}")

    if not res_data.get("ok"):
        raise ValueError(f"Telegram webhook o'rnatib bo'lmadi: {res_data.get('description', 'noma`lum xato')}")

    # ── 2.5. Buyruqlar menyusi (/ bosganda chiqadigan "/start", "/help") ──
    # ⚠️ `setup_bot` management command bu menyuni faqat UMUMIY (master)
    # bot uchun o'rnatardi — har bir do'konning o'z shaxsiy boti bu yerda,
    # ulanish paytida hech qachon o'rnatilmagan edi, shuning uchun "/"
    # bossa hech narsa taklif qilinmasdi (jonli holatda aniqlandi). Xato
    # bo'lsa ham ulanishni butunlay bekor qilmaymiz — webhook allaqachon
    # muvaffaqiyatli, bu shunchaki qulaylik.
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"{TELEGRAM_API_BASE}{bot_token}/setMyCommands",
                json={"commands": [
                    {"command": "start", "description": "Botni ishga tushirish"},
                    {"command": "help", "description": "Yordam va ko'rsatmalar"},
                ]},
            )
    except httpx.RequestError as e:
        logger.warning(f"[Telegram Bot Connect] Buyruqlar menyusini o'rnatib bo'lmadi: store={store.name} | {e}")

    # ── 3. Store'ga saqlash ────────────────────────────────────
    # ⚠️ BUG FIX (jonli qo'lda testda topildi): `update_fields`ga
    # `tg_bot_token_hash` kiritilmagani uchun, `Store.save()` uni
    # xotirada hisoblasa ham, Django buni HAQIQIY UPDATE so'roviga
    # umuman qo'shmasdi — natijada baza ustunida hamon eski/bo'sh
    # qiymat qolib, webhook marshrutlash (`_get_store_by_token`) va
    # "bu token band" tekshiruvi ISHLAMAY qolgan edi.
    store.tg_bot_token = bot_token
    store.tg_bot_username = bot_username
    store.save(update_fields=["tg_bot_token", "tg_bot_token_hash", "tg_bot_username", "updated_at"])

    logger.info(f"[Telegram Bot Connect] Muvaffaqiyatli ulandi: store={store.name} | bot=@{bot_username}")

    return {"success": True, "bot_username": bot_username}


def disconnect_telegram_bot_from_store(store) -> dict:
    """
    Do'kon egasining shaxsiy Telegram botini uzadi — do'kon umumiy demo
    botga qaytadi (mijozlar/TWA yana `TELEGRAM_BOT_TOKEN` orqali ishlaydi).

    Bot O'ZI (Telegram tomonida) o'chirilmaydi/o'zgartirilmaydi — faqat
    shu do'kon bilan bog'lanishi uziladi, va o'sha bot tokenining
    webhook'i tozalanadi (aks holda o'sha botga yozgan haqiqiy odamlar
    endi hech kimga tegishli bo'lmagan "jim" botga xabar yuborishda
    davom etib, hech qanday javob ololmay qolardi — ular buni tushunishi
    qiyin bo'lardi).

    Args:
        store: Store obyekti (uzadigan do'kon)

    Returns:
        {"success": True}
    """
    old_token = store.tg_bot_token
    if not old_token:
        return {"success": True}

    # ⚠️ Webhook'ni tozalash — xato bo'lsa ham uzishning o'zini
    # to'xtatmaydi (masalan bot allaqachon o'chirilgan/bloklangan bo'lsa
    # ham, do'kon bazada baribir muvaffaqiyatli uzilishi kerak).
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(f"{TELEGRAM_API_BASE}{old_token}/deleteWebhook")
    except httpx.RequestError as e:
        logger.warning(f"[Telegram Bot Disconnect] Webhook tozalab bo'lmadi (davom etiladi): {e}")

    # ⚠️ BUG FIX: bu yerda avval `tg_bot_token`/`tg_bot_username` ikkisi
    # ham `None`ga o'rnatilardi — docstring va frontend "umumiy demo botga
    # qaytadi" deb va'da qilsa-da, HAQIQATDA do'kon HECH QANDAY botsiz
    # qolib ketardi: `tg_bot_username` bo'sh bo'lgani uchun admin/mijoz
    # havolalari (`get_admin_link`/`get_customer_link`) hisoblanmay,
    # Super Admin ro'yxatida "Havolalar" tugmasi butunlay yo'qolib
    # qolardi (jonli holatda aniqlandi). Endi haqiqatan ham MASTER
    # tokenga qaytariladi va uning HAQIQIY username'i `getMe` orqali
    # olinadi (xuddi `connect_telegram_bot_to_store`dagi kabi) — bu
    # `provision_store` yangi do'kon yaratganda o'rnatadigan AYNAN shu
    # holatga teng.
    master_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or None
    master_username = None
    if master_token:
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{TELEGRAM_API_BASE}{master_token}/getMe")
                data = res.json()
                if data.get("ok"):
                    master_username = data["result"].get("username")
        except httpx.RequestError as e:
            logger.warning(f"[Telegram Bot Disconnect] Umumiy bot nomini olib bo'lmadi (davom etiladi): {e}")

    store.tg_bot_token = master_token
    store.tg_bot_username = master_username
    store.save(update_fields=["tg_bot_token", "tg_bot_token_hash", "tg_bot_username", "updated_at"])

    logger.info(f"[Telegram Bot Disconnect] Uzildi: store={store.name}")

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


# ─────────────────────────────────────────────────────────────
# Yangi Do'kon Yaratish (Provisioning)
# ─────────────────────────────────────────────────────────────

class StoreProvisioningError(Exception):
    """Yangi do'kon yaratishda foydalanuvchi xatosi (bo'sh nom, sozlanmagan token va h.k.)."""
    pass


def provision_store(name: str, category_type: str, bot_username: str = "LeadNodeBot", bot_token: str = "") -> dict:
    """
    Yangi do'kon (tenant) yaratadi va admin/mijoz Telegram havolalarini
    qaytaradi.

    ⚠️ Bu funksiya avval `apps/stores/management/commands/create_store.py`
    ichida qattiq yozilgan edi — endi Super Admin panel (API orqali) ham,
    terminal buyrug'i ham AYNAN shu logikani chaqiradi, ikki joyda
    takrorlanmasin.

    Args:
        name: Do'kon nomi
        category_type: Store.CategoryType qiymatlaridan biri
        bot_username: Telegram bot username (@ belgisisiz) — faqat
            `bot_token` berilmagan holatda havolalarni hisoblash uchun
            ishlatiladi
        bot_token: Agar biznes egasi BOSHIDANOQ o'z shaxsiy botini
            (@BotFather orqali yaratilgan) bergan bo'lsa — shu token
            darhol ulanadi (`connect_telegram_bot_to_store` orqali,
            umumiy MASTER bot bosqichi butunlay o'tkazib yuboriladi)

    Returns:
        {"store": Store, "admin_link": str, "customer_link": str}

    Raises:
        StoreProvisioningError: nom bo'sh, TELEGRAM_BOT_TOKEN sozlanmagan,
            yoki (bot_token berilgan bo'lsa) token yaroqsiz/band — bu holda
            HECH NARSA yaratilmaydi (owner+store butunlay ortga qaytariladi)
    """
    import uuid as _uuid

    from django.contrib.auth.models import User
    from django.db import transaction
    from django.utils.text import slugify

    from .models import Store

    name = (name or "").strip()
    bot_username = (bot_username or "LeadNodeBot").replace("@", "").strip()
    bot_token = (bot_token or "").strip()

    if not name:
        raise StoreProvisioningError("Do'kon nomi bo'sh bo'lishi mumkin emas.")

    if not getattr(settings, "TELEGRAM_BOT_TOKEN", ""):
        raise StoreProvisioningError(
            "TELEGRAM_BOT_TOKEN .env faylida sozlanmagan! Master bot tokenisiz do'kon yaratib bo'lmaydi."
        )

    base_username = slugify(name).replace("-", "_")[:20] or "store"
    username = f"{base_username}_{_uuid.uuid4().hex[:6]}"

    try:
        with transaction.atomic():
            owner = User.objects.create(
                username=username,
                email=f"{username}@placeholder.local",
            )
            # ⚠️ Bu akkaunt FAQAT texnik "egasi" yozuvi — unga hech kim
            # parol bilan kirmaydi (kirish Telegram initData orqali).
            # Parol maydoni bo'sh qolsa Django uni "yaroqli" deb ko'rsatadi;
            # yaroqsiz qilib belgilash egalik o'tkazilgandan keyin sobiq
            # eganing parol/JWT orqali kirish yo'lini butunlay yopadi.
            owner.set_unusable_password()
            owner.save(update_fields=["password"])

            store = Store.objects.create(
                owner=owner,
                name=name,
                category_type=category_type,
                platform=Store.Platform.TELEGRAM,
                tg_bot_token=settings.TELEGRAM_BOT_TOKEN,
                tg_bot_username=bot_username,
            )

            if bot_token:
                # Muvaffaqiyatli bo'lsa, `store.tg_bot_username` Telegram
                # `getMe`dan kelgan HAQIQIY qiymat bilan yangilanadi (pastda
                # havolalar shu yangilangan qiymatdan hisoblanadi).
                connect_telegram_bot_to_store(store, bot_token)
    except ValueError as e:
        # Token yaroqsiz/band — butun yaratish bekor qilindi, yarim-tayyor
        # (noto'g'ri holatdagi) biznes bazada qolib ketmaydi.
        raise StoreProvisioningError(str(e))

    admin_link = f"https://t.me/{store.tg_bot_username}?start=admin_{store.id}"
    customer_link = f"https://t.me/{store.tg_bot_username}?start=store_{store.id}"

    logger.info(f"[Store Provisioning] Yangi do'kon yaratildi: {store.name} (ID: {store.id})")

    return {"store": store, "admin_link": admin_link, "customer_link": customer_link}


# ─────────────────────────────────────────────────────────────
# Do'kon Hayot Sikli (Lifecycle) — Ega Boshqaruvi va Active/Suspend
# ─────────────────────────────────────────────────────────────

def set_store_active(store: "Store", is_active: bool) -> dict:
    """
    Do'konni to'liq faollashtiradi yoki to'xtatadi (TWA + AI bot, ikkalasi
    ham) — `apps/stores/management/commands/set_store_access.py`'dan
    ko'chirilgan, endi terminal buyrug'i ham, Super Admin API ham shu
    AYNAN logikani chaqiradi.

    Returns: {"changed": bool, "is_active": bool}
    """
    if store.is_active == is_active:
        return {"changed": False, "is_active": store.is_active}

    store.is_active = is_active
    store.save(update_fields=["is_active", "updated_at"])
    return {"changed": True, "is_active": store.is_active}


def revoke_store_owner(store: "Store") -> dict:
    """
    Do'kon egasini bo'shatadi — faqat `tg_owner_chat_id`ni tozalaydi,
    do'konning o'zi, ma'lumotlari va sozlamalari o'zgarmaydi.
    `apps/stores/management/commands/revoke_store_owner.py`'dan ko'chirilgan.

    Bo'shatilgandan so'ng, avval generatsiya qilingan admin havolasi qayta
    ishlatilishi mumkin — u do'kon ID'siga bog'langan, egaga emas.

    Returns: {"changed": bool, "old_chat_id": str | None}
    """
    if not store.tg_owner_chat_id:
        return {"changed": False, "old_chat_id": None}

    old_chat_id = store.tg_owner_chat_id
    store.tg_owner_chat_id = None
    store.save(update_fields=["tg_owner_chat_id", "updated_at"])
    # Auth keshi (20s) eski egani darrov chiqarib tashlashi uchun
    cache.delete(f"store_by_tgowner:{old_chat_id}")
    _reset_owner_menu_button(store, old_chat_id)
    return {"changed": True, "old_chat_id": old_chat_id}


def _reset_owner_menu_button(store: "Store", chat_id) -> None:
    """
    Sobiq eganing chatidagi "Dashboard" tugmasini standart holatga qaytaradi.

    ⚠️ Jonli aniqlangan xato (2026-10-21): ega almashtirilgandan keyin
    sobiq ega botga oddiy mijoz sifatida kirsa ham, Telegram menyusida
    eski "Dashboard" tugmasi turib qolgan edi. Bu tugma Telegram
    serverida (bizning bazada EMAS), chat bo'yicha saqlanadi va faqat
    biz uni aniq o'zgartirsak o'chadi. Ma'lumotlar baribir ko'rinmasdi
    (API 401 qaytaradi), lekin bo'sh boshqaruv paneli ochilib qolardi.

    Best-effort: Telegram javob bermasa, egalikni bo'shatish baribir
    muvaffaqiyatli tugaydi.
    """
    token = getattr(store, "tg_bot_token", "") or ""
    if not token or not chat_id:
        return
    try:
        res = httpx.post(
            f"{TELEGRAM_API_BASE}{token}/setChatMenuButton",
            json={"chat_id": int(chat_id), "menu_button": {"type": "default"}},
            timeout=10.0,
        )
        if not res.json().get("ok"):
            logger.warning(f"Sobiq ega menyu tugmasi tiklanmadi: {res.json()}")
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"Sobiq ega menyu tugmasi tiklanmadi: {e}")


# ─────────────────────────────────────────────────────────────
# Bot / Webhook Sog'ligini Tekshirish (Health Check)
# ─────────────────────────────────────────────────────────────

def check_store_bot_health(store: "Store") -> dict:
    """
    Do'konning shaxsiy botining webhook holatini Telegram'dan so'raydi
    (`getWebhookInfo`) va natijani bazaga (`bot_health_ok`,
    `bot_health_checked_at`, `bot_health_error`) yozadi.

    ⚠️ FAQAT shaxsiy bot (store.has_own_bot) uchun ma'noga ega — umumiy
    (master) bot ishlatuvchi do'konlar uchun chaqirilmasligi kerak
    (umumiy botning holati platforma darajasida, `SuperAdminStatsView`
    orqali bitta marta tekshiriladi — har bir do'kon uchun alohida
    tekshirish shart emas, chunki token bir xil).

    "Sog'lom" mezoni:
    - Telegram token'ni tanishi kerak (`getWebhookInfo` muvaffaqiyatli).
    - Webhook URL aniq BIZNING kutilgan manzilimizga ko'rsatilgan bo'lishi kerak.
    - So'nggi 1 soat ichida yetkazib berish xatosi (`last_error_date`)
      bo'lmasligi kerak — ESKI, allaqachon o'z-o'zidan tuzalgan xatoni
      abadiy "xato" deb ko'rsatib yurmaslik uchun (masalan vaqtinchalik
      tunnel uzilishi keyin tiklangan bo'lsa).

    Returns: {"healthy": bool, "error": str}
    """
    import time

    now = timezone.now()

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(f"{TELEGRAM_API_BASE}{store.tg_bot_token}/getWebhookInfo")
        data = res.json()
    except httpx.RequestError as e:
        healthy, error = False, f"Tarmoq xatosi: {e}"
        store.bot_health_ok = healthy
        store.bot_health_error = error[:255]
        store.bot_health_checked_at = now
        store.save(update_fields=["bot_health_ok", "bot_health_error", "bot_health_checked_at"])
        return {"healthy": healthy, "error": error}

    if not data.get("ok"):
        healthy, error = False, data.get("description", "Noma'lum xato")
    else:
        result = data.get("result", {})
        public_url = (getattr(settings, "PUBLIC_URL", "") or "").rstrip("/")
        expected_webhook = f"{public_url}/webhook/telegram/{store.tg_bot_token}/"
        actual_url = result.get("url", "")
        last_error_message = result.get("last_error_message")
        last_error_date = result.get("last_error_date")

        if not actual_url:
            healthy, error = False, "Webhook o'rnatilmagan"
        elif public_url and actual_url != expected_webhook:
            healthy, error = False, f"Webhook boshqa manzilga ko'rsatilgan: {actual_url}"
        elif last_error_message and last_error_date and (time.time() - last_error_date) < 3600:
            healthy, error = False, last_error_message
        else:
            healthy, error = True, ""

    store.bot_health_ok = healthy
    store.bot_health_error = error[:255]
    store.bot_health_checked_at = now
    store.save(update_fields=["bot_health_ok", "bot_health_error", "bot_health_checked_at"])
    return {"healthy": healthy, "error": error}


def _get_master_bot_live_status() -> dict:
    """
    Umumiy (master) bot ishlatuvchi BARCHA do'konlar bitta jonli
    natijani ulashadi — shuning uchun 60 soniyaga keshlanadi (har bir
    TWA sahifa yuklanishida Telegram'ga alohida so'rov yubormaslik
    uchun). ⚠️ `apps.webhooks.views.webhook_health`dan ATAYLAB
    MUSTAQIL — u yerda egalarga ogohlantirish yuborish side-effect'i
    bor, bu yerga tegmaslik uchun bu funksiya shunchaki o'qish uchun,
    hech qanday xabar yubormaydi.
    """
    cache_key = "master_bot_live_status"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    healthy, error = False, "Bot sozlanmagan"
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if bot_token:
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{TELEGRAM_API_BASE}{bot_token}/getMe")
            data = res.json()
            healthy = res.status_code == 200 and bool(data.get("ok"))
            error = "" if healthy else "Umumiy bot bilan aloqa yo'q"
        except httpx.RequestError:
            healthy, error = False, "Umumiy bot bilan aloqa yo'q"

    result = {"healthy": healthy, "error": error}
    cache.set(cache_key, result, timeout=60)
    return result


def get_store_ai_status(store: "Store") -> dict:
    """
    Biznes egasi TWA dashboardidagi "AI Assistant" kartasi uchun — bu
    do'kon HAQIQATDA ishlatayotgan botning holati (shaxsiy bot bo'lsa
    o'zining 20-daqiqalik davriy tekshiruvi, `check_all_bot_health`
    Celery Beat vazifasi orqali allaqachon bazaga yozilgan; umumiy bot
    bo'lsa — qisqa keshlangan jonli tekshiruv).

    Returns: {"healthy": bool|None, "error": str|None, "checked_at": datetime|None,
              "last_activity_at": datetime|None, "uses_own_bot": bool}
    """
    from apps.chat.models import ChatMessage

    last_activity_at = (
        ChatMessage.objects.filter(store=store, is_deleted=False)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )

    if store.has_own_bot:
        return {
            "healthy": store.bot_health_ok,
            "error": store.bot_health_error or None,
            "checked_at": store.bot_health_checked_at,
            "last_activity_at": last_activity_at,
            "uses_own_bot": True,
        }

    live = _get_master_bot_live_status()
    return {
        "healthy": live["healthy"],
        "error": live["error"] or None,
        "checked_at": timezone.now(),
        "last_activity_at": last_activity_at,
        "uses_own_bot": False,
    }
