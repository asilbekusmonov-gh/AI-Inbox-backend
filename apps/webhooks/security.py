"""
Webhook Xavfsizligi — Imzo tekshiruvi moduli.

Instagram va Telegram'dan kelgan so'rovlarning
haqiqiyligini tekshiradi. Soxta so'rovlarni rad etadi.
"""
import hashlib
import hmac
import logging

from django.conf import settings

logger = logging.getLogger("apps.webhooks")


# ─────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────

def verify_telegram_webhook(request) -> bool:
    """
    Telegram webhook so'rovining haqiqiyligini tekshiradi.
    DEV (DEBUG=True) rejimida doim True qaytaradi.
    """
    if getattr(settings, "DEBUG", False):
        return True

    try:
        secret_token = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)
        if not secret_token:
            logger.error(
                "TELEGRAM_WEBHOOK_SECRET sozlanmagan! "
                "Production muhitda webhook tekshiruvi o'tkazilmaydi."
            )
            return False

        incoming_token = (
            request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            or request.META.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
        )
        if not incoming_token:
            logger.warning("Telegram webhook: secret token header topilmadi")
            return False

        return hmac.compare_digest(
            incoming_token.encode("utf-8"),
            secret_token.encode("utf-8"),
        )
    except Exception as e:
        logger.error(f"Telegram imzo tekshirishda xato: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# INSTAGRAM / META
# ─────────────────────────────────────────────────────────────

def verify_instagram_signature(request) -> bool:
    """
    Meta/Instagram webhook imzosini tekshiradi (HMAC-SHA256).

    Meta har bir webhook so'rovida X-Hub-Signature-256 header'ini
    qo'shadi: sha256=<HMAC(APP_SECRET, body)>

    Returns:
        True — haqiqiy Meta so'rovi
        False — soxta yoki buzilgan so'rov
    """
    try:
        app_secret = settings.META_APP_SECRET
        if not app_secret:
            logger.warning("META_APP_SECRET sozlanmagan! Dev rejimi.")
            return True

        signature_header = request.headers.get("X-Hub-Signature-256", "")
        if not signature_header.startswith("sha256="):
            logger.warning("Instagram: X-Hub-Signature-256 header topilmadi.")
            return False

        expected_signature = signature_header[len("sha256="):]

        # Request body'dan HMAC hisoblash
        body = request.body
        mac = hmac.new(
            app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        )
        computed_signature = mac.hexdigest()

        # Constant-time taqqoslash
        is_valid = hmac.compare_digest(expected_signature, computed_signature)

        if not is_valid:
            logger.warning(
                f"Instagram webhook imzo xatosi! "
                f"IP: {_get_client_ip(request)}"
            )

        return is_valid

    except Exception as e:
        logger.error(f"Instagram imzo tekshirishda xato: {e}", exc_info=True)
        return False


def verify_instagram_challenge(request) -> str | None:
    """
    Instagram webhook verification (GET so'rovi).

    Meta webhook ro'yxatga olganda GET so'rov yuboradi:
    ?hub.mode=subscribe&hub.verify_token=TOKEN&hub.challenge=CHALLENGE

    Verify token to'g'ri bo'lsa — challenge qaytariladi.

    Returns:
        challenge string — muvaffaqiyatli
        None — tekshiruv muvaffaqiyatsiz
    """
    try:
        mode = request.GET.get("hub.mode", "")
        verify_token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")

        if mode != "subscribe":
            logger.warning(f"Instagram: noto'g'ri hub.mode = {mode!r}")
            return None

        expected_token = settings.META_VERIFY_TOKEN
        if not expected_token:
            logger.warning("META_VERIFY_TOKEN sozlanmagan!")
            return None

        # Constant-time taqqoslash
        if hmac.compare_digest(verify_token, expected_token):
            logger.info("Instagram webhook muvaffaqiyatli tasdiqlandi.")
            return challenge

        logger.warning("Instagram: verify_token noto'g'ri!")
        return None

    except Exception as e:
        logger.error(f"Instagram challenge tekshirishda xato: {e}", exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────
# YORDAMCHI
# ─────────────────────────────────────────────────────────────

def _get_client_ip(request) -> str:
    """Mijoz real IP manzilini oladi (proxy orqali ham)"""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
