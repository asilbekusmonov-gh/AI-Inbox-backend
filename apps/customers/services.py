"""
Instagram User Profile Fetcher Service — apps/customers/services.py

Instagram webhook'dan faqat sender IGSID (sender_id) keladi.
Bu servis Meta Graph API'ga so'rov yuborib, mijozning:
  - username (@handle)
  - name (to'liq ismi)
  - profile_pic (profil rasmi URL)
ma'lumotlarini olib, Customer modeliga saqlaydi.

Meta Graph API: GET /{IGSID}?fields=name,username,profile_pic
"""
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger("apps.customers")

META_GRAPH_VERSION = "v18.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"

# Rate-limit holatida qayta urinishlar orasidagi kutish (sekund)
RATE_LIMIT_BACKOFF = [5, 15, 30]


# ─────────────────────────────────────────────────────────────
# ASOSIY SERVIS FUNKSIYASI
# ─────────────────────────────────────────────────────────────

def fetch_instagram_profile(
    igsid: str,
    access_token: str,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    Meta Graph API orqali Instagram foydalanuvchi profilini tortib oladi.

    Meta API:
      GET https://graph.facebook.com/v18.0/{IGSID}
        ?fields=name,username,profile_pic
        &access_token={PAGE_ACCESS_TOKEN}

    Instagram API cheklovlari:
      - name: Foydalanuvchining to'liq ismi (Privacy sozlamalariga qarab kelmasligi mumkin)
      - username: @handle (odatda keladi)
      - profile_pic: Profil rasm URL (vaqtinchalik CDN URL, tez o'tadi)

    Args:
        igsid: Instagram Scoped User ID (webhook'dagi sender.id)
        access_token: Do'konning Page Access Token (ig_access_token)
        max_retries: Rate-limit yoki timeout holatida qayta urinish soni

    Returns:
        {
            "username": "user123",
            "name": "Asilbek Usmonov",
            "profile_pic": "https://..."  # ixtiyoriy
        }
        yoki None — API xatosi yoki ma'lumot yo'q bo'lsa
    """
    if not igsid or not access_token:
        logger.warning(
            f"[IG Profile] Bo'sh parametr: "
            f"igsid={igsid!r} | token={'✓' if access_token else '✗'}"
        )
        return None

    url = f"{META_GRAPH_BASE}/{igsid}"
    params = {
        "fields": "name,username,profile_pic",
        "access_token": access_token,
    }

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params)

            data = response.json()

            # Muvaffaqiyatli javob
            if response.status_code == 200:
                profile = {
                    "username": data.get("username", ""),
                    "name": data.get("name", ""),
                    "profile_pic": data.get("profile_pic", ""),
                }
                logger.info(
                    f"[IG Profile] Topildi: igsid={igsid} | "
                    f"username=@{profile['username']} | "
                    f"name={profile['name']}"
                )
                return profile

            error = data.get("error", {})
            error_code = error.get("code", 0)
            error_msg = error.get("message", "Noma'lum xato")

            # Token eskirgan — qayta urinish foydasi yo'q
            if error_code in (190, 102, 104):
                logger.error(
                    f"[IG Profile] Access token eskirgan: "
                    f"igsid={igsid} | code={error_code}"
                )
                return None

            # Foydalanuvchi topilmadi
            if response.status_code == 404:
                logger.warning(
                    f"[IG Profile] Foydalanuvchi topilmadi: igsid={igsid}"
                )
                return None

            # Rate limit — kutib qayta urinish
            if response.status_code == 429:
                wait_time = RATE_LIMIT_BACKOFF[min(attempt - 1, len(RATE_LIMIT_BACKOFF) - 1)]
                logger.warning(
                    f"[IG Profile] Rate limit! "
                    f"{wait_time}s kutilmoqda... (urinish {attempt}/{max_retries})"
                )
                time.sleep(wait_time)
                continue

            logger.warning(
                f"[IG Profile] API xatosi: "
                f"status={response.status_code} | "
                f"code={error_code} | msg={error_msg} | "
                f"igsid={igsid} (urinish {attempt}/{max_retries})"
            )

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except httpx.TimeoutException:
            logger.warning(
                f"[IG Profile] Timeout: igsid={igsid} "
                f"(urinish {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except httpx.RequestError as e:
            logger.error(
                f"[IG Profile] So'rov xatosi: {e} | igsid={igsid}",
                exc_info=True,
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except Exception as e:
            logger.error(
                f"[IG Profile] Kutilmagan xato: {e} | igsid={igsid}",
                exc_info=True,
            )
            return None

    logger.warning(
        f"[IG Profile] Barcha {max_retries} urinish muvaffaqiyatsiz: "
        f"igsid={igsid}"
    )
    return None


# ─────────────────────────────────────────────────────────────
# CUSTOMER BOYITUVCHI
# ─────────────────────────────────────────────────────────────

def enrich_instagram_customer(customer, store) -> bool:
    """
    Instagram mijozining profil ma'lumotlarini Meta API'dan olib,
    Customer modeliga saqlaydi.

    Faqat quyidagi holatlarda yangilaydi:
      - username bo'lmasa
      - full_name bo'lmasa

    Agar ikkisi ham allaqachon to'ldirilgan bo'lsa — API'ga so'rov
    yuborilmaydi (gereksiz chaqiruvdan saqlanadi).

    Args:
        customer: Customer obyekti (platform="instagram" bo'lishi kerak)
        store: Store obyekti (ig_access_token mavjud bo'lishi kerak)

    Returns:
        True — yangilanish amalga oshirildi
        False — yangilanmadi (allaqachon to'ldirilgan yoki xato)
    """
    # Faqat Instagram mijozlari uchun
    if customer.platform != "instagram":
        return False

    # Token mavjudligini tekshiramiz
    if not store.ig_access_token:
        logger.warning(
            f"[IG Enrich] ig_access_token yo'q: store={store.name}"
        )
        return False

    # Agar ikkisi ham to'ldirilgan bo'lsa — qo'shimcha API so'rov shart emas
    if customer.username and customer.full_name:
        return False

    # Meta API'dan profil olish
    profile = fetch_instagram_profile(
        igsid=customer.platform_user_id,
        access_token=store.ig_access_token,
    )

    if not profile:
        return False

    # Faqat bo'sh maydonlarni yangilaydi (mavjud ma'lumotni ezmaydi)
    update_fields = []

    if not customer.username and profile.get("username"):
        customer.username = profile["username"]
        update_fields.append("username")

    if not customer.full_name and profile.get("name"):
        customer.full_name = profile["name"]
        update_fields.append("full_name")

    if update_fields:
        update_fields.append("updated_at")
        customer.save(update_fields=update_fields)
        logger.info(
            f"[IG Enrich] Customer yangilandi: "
            f"igsid={customer.platform_user_id} | "
            f"yangilangan={update_fields}"
        )
        return True

    return False
