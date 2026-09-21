import hashlib
import json
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger("apps.core")


@xframe_options_exempt
def twa_dashboard_view(request):
    """Telegram Mini App (TWA) — Next.js static build'dan to'g'ridan-to'g'ri serve qiladi.

    static/twa/index.html dan to'g'ridan-to'g'ri FileResponse orqali serve qilinadi.
    @xframe_options_exempt — Telegram iframe ichida ochishi uchun zarur.
    """
    import os
    from django.http import FileResponse, HttpResponseNotFound
    from django.conf import settings

    html_path = os.path.join(settings.BASE_DIR, "static", "twa", "index.html")
    if not os.path.exists(html_path):
        return HttpResponseNotFound("TWA not deployed yet. Run: ./deploy_twa.sh")
    response = FileResponse(open(html_path, "rb"), content_type="text/html; charset=utf-8")
    # ⚠️ BUG FIX: bu javobda hech qanday Cache-Control sarlavhasi yo'q edi —
    # Telegram'ning mobil WebView'i (va ba'zi brauzerlar) shu "qobiq"
    # (shell) HTML'ni o'zi xohlagancha, hatto YANGI deploy qilingandan
    # keyin ham, uzoq vaqt keshlab qo'yishi mumkin edi (jonli holatda
    # aniqlandi: yangi deploydan keyin ham mobil TWA eski, olib
    # tashlangan bo'limni ko'rsatishda davom etardi). `index.html`
    # o'zi HAR DOIM eng yangisi bo'lishi SHART — u ICHIDAGI JS/CSS
    # fayllar nomi build har safar o'zgarganda (content hash) o'zgaradi,
    # shuning uchun ular xavfsiz uzoq keshlanaveradi (bu yerga tegilmadi).
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def privacy_policy_view(request):
    """
    Meta App Review talabiga mos Mahfiylik Siyosati sahifasi.

    GET /privacy-policy/

    Meta App Review'dan o'tish uchun bu URL ochiq va
    ommaga ko'rinadigan bo'lishi shart.
    """
    return render(request, "privacy_policy.html")


@csrf_exempt
def meta_data_deletion_callback(request):
    """
    Meta (Facebook/Instagram) Ma'lumotlarni O'chirish So'rovi (Data Deletion Callback).

    POST /api/v1/meta/data-deletion/

    Meta foydalanuvchi ma'lumotlarini o'chirish so'rovi yuborganda
    ushbu endpointga signed_request yuboradi. Biz:
      1. Signed request'ni tekshiramiz
      2. Tegishli mijoz ma'lumotlarini o'chiramiz (soft delete)
      3. Confirmation URL qaytaramiz

    Meta Documentation:
    https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback

    Response:
        {
            "url": "https://yourdomain.com/deletion-status/?id=abc123",
            "confirmation_code": "abc123"
        }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from django.conf import settings

    app_secret = getattr(settings, "META_APP_SECRET", "")
    signed_request_raw = request.POST.get("signed_request", "")

    if not signed_request_raw:
        # JSON body bo'lishi ham mumkin
        try:
            body = json.loads(request.body)
            signed_request_raw = body.get("signed_request", "")
        except (json.JSONDecodeError, Exception):
            pass

    if not signed_request_raw:
        logger.warning("[Meta Data Deletion] signed_request yo'q")
        return JsonResponse({"error": "signed_request required"}, status=400)

    # ── Signed Request Tekshiruvi ─────────────────────────────
    user_id = _verify_and_parse_signed_request(
        signed_request_raw, app_secret
    )

    if user_id is None:
        logger.warning("[Meta Data Deletion] Noto'g'ri signed_request")
        return JsonResponse({"error": "Invalid signed_request"}, status=400)

    # ── Mijoz ma'lumotlarini Soft Delete qilish ───────────────
    confirmation_code = _handle_deletion_request(user_id)

    # ── Meta'ga javob qaytarish ───────────────────────────────
    # Meta confirmation URL va code kutadi
    base_url = request.build_absolute_uri("/")
    deletion_status_url = f"{base_url}deletion-status/?id={confirmation_code}"

    logger.info(
        f"[Meta Data Deletion] Muvaffaqiyatli: "
        f"user_id={user_id} | code={confirmation_code}"
    )

    return JsonResponse({
        "url": deletion_status_url,
        "confirmation_code": confirmation_code,
    })


def deletion_status_view(request):
    """
    O'chirish tasdiqlash holati sahifasi.

    GET /deletion-status/?id=abc123

    Meta foydalanuvchilarga ushbu sahifani ko'rsatishi mumkin.
    """
    confirmation_code = request.GET.get("id", "")
    return render(request, "deletion_status.html", {
        "confirmation_code": confirmation_code,
    })


# ─────────────────────────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────────────────────

def _verify_and_parse_signed_request(
    signed_request: str, app_secret: str
) -> str | None:
    """
    Meta signed_request'ni tekshiradi va user_id'ni ajratib oladi.

    Format: BASE64(HMAC-SHA256) + '.' + BASE64(payload_json)

    Returns:
        user_id (str) — muvaffaqiyatli
        None — imzo noto'g'ri
    """
    import base64
    import hmac

    try:
        parts = signed_request.split(".", 1)
        if len(parts) != 2:
            return None

        encoded_sig, payload_raw = parts

        # Base64url decode signature (padding qo'shib)
        padding = 4 - len(encoded_sig) % 4
        encoded_sig_padded = encoded_sig + ("=" * padding if padding != 4 else "")
        sig = base64.urlsafe_b64decode(encoded_sig_padded)

        # HMAC-SHA256 tekshiruvi (original xam payload_raw bo'yicha)
        expected_sig = hmac.new(
            app_secret.encode("utf-8"),
            payload_raw.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(sig, expected_sig):
            logger.error("[Meta Signed Request] Imzo noto'g'ri!")
            return None

        # Base64url decode payload (padding qo'shib)
        padding = 4 - len(payload_raw) % 4
        payload_padded = payload_raw + ("=" * padding if padding != 4 else "")
        data = json.loads(base64.urlsafe_b64decode(payload_padded))

        if data.get("algorithm", "").upper() != "HMAC-SHA256":
            logger.error("[Meta Signed Request] Noto'g'ri algorithm")
            return None

        return str(data.get("user_id", ""))

    except Exception as e:
        logger.error(
            f"[Meta Signed Request] Parse xatosi: {e}",
            exc_info=True,
        )
        return None


def _handle_deletion_request(instagram_user_id: str) -> str:
    """
    Instagram User ID asosida barcha mijoz ma'lumotlarini soft delete qiladi.

    Args:
        instagram_user_id: Meta'dan kelgan foydalanuvchi ID

    Returns:
        confirmation_code: Tasdiqlash kodi (log/audit uchun)
    """
    import uuid
    from apps.customers.models import Customer
    from apps.chat.models import ChatMessage

    confirmation_code = uuid.uuid4().hex[:16]

    try:
        customers = Customer.objects.filter(
            platform="instagram",
            platform_user_id=instagram_user_id,
        )

        deleted_count = 0
        for customer in customers:
            # Chat xabarlarini soft delete
            ChatMessage.objects.filter(
                customer=customer,
            ).update(is_deleted=True)

            # Customer'ni soft delete
            customer.soft_delete()
            deleted_count += 1

        logger.info(
            f"[Data Deletion] Instagram user_id={instagram_user_id} | "
            f"o'chirilgan mijozlar={deleted_count} | "
            f"code={confirmation_code}"
        )

    except Exception as e:
        logger.error(
            f"[Data Deletion] Xato: {e} | user_id={instagram_user_id}",
            exc_info=True,
        )

    return confirmation_code
