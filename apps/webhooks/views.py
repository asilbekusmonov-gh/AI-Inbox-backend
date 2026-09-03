"""
Webhook Views — Telegram va Instagram webhook endpointlari.

Ishlash mantig'i:
1. So'rov imzosini tekshir (xavfsizlik)
2. Payload'ni parse qil
3. Idempotency tekshir (Redis orqali tez, DB orqali ishonchli)
4. Celery navbatiga jo'nat (webhook qotmasin!)
5. Darhol 200 OK qaytart

⚠️ Webhook view'lari HECH QACHON AI yoki DB ga to'g'ridan-to'g'ri
   so'rov yubormasligi kerak — bu Celery task'lar ishi!
"""
import json
import logging
import httpx
from django.conf import settings

from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.stores.models import Store
from apps.chat.models import ChatMessage

from .security import (
    verify_telegram_webhook,
    verify_instagram_signature,
    verify_instagram_challenge,
)
from .parsers import (
    parse_telegram_payload,
    parse_instagram_payload,
    IncomingMessage,
)
from .tasks import process_incoming_message

logger = logging.getLogger("apps.webhooks")


# ─────────────────────────────────────────────────────────────
# TELEGRAM WEBHOOK
# ─────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class TelegramWebhookView(View):
    """
    Telegram Bot webhook endpoint.

    URL: /webhook/telegram/<bot_token>/
    Method: POST

    Har bir do'konning boti o'ziga xos token bilan keladi.
    URL'dagi bot_token orqali qaysi do'kon ekanini aniqlaymiz.
    """

    def post(self, request, bot_token: str):
        """Telegram'dan kelgan yangi xabarni qabul qiladi"""

        # 1. Imzo tekshiruvi
        if not verify_telegram_webhook(request):
            logger.warning(f"Telegram: ruxsatsiz so'rov | token: {bot_token[:10]}...")
            return HttpResponse(status=403)

        # 2. JSON parse
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Telegram: noto'g'ri JSON | {e}")
            # Telegram'ga 200 qaytaramiz — aks holda qayta-qayta yuboradi!
            return HttpResponse(status=200)

        # 3. Do'konni bot_token orqali topamiz
        store = self._get_store_by_token(bot_token)
        if not store:
            logger.warning(
                f"Telegram: do'kon topilmadi | token: {bot_token[:10]}..."
            )
            return HttpResponse(status=200)

        # 4. Payload'ni parse qilamiz
        message = parse_telegram_payload(payload)
        if not message:
            # Qo'llab-quvvatlanmaydigan update turi — OK qaytaramiz
            return HttpResponse(status=200)

        # 4.5 Single Master Bot Multi-Tenant Routing (Deep-link & Session Router)
        store = self._resolve_store_for_message(store, message)

        # 5. Celery navbatiga jo'natamiz (ASYNCHRONOUS!)
        try:
            task = process_incoming_message.apply_async(
                args=[],
                kwargs={
                    "store_id": str(store.id),
                    "platform": "telegram",
                    "message_id": message.message_id,
                    "sender_id": message.sender_id,
                    "sender_username": message.sender_username,
                    "text": message.text,
                    "chat_id": message.chat_id,
                    "raw_payload": message.raw_payload,
                },
                queue="messages",
                routing_key="messages",
            )
            logger.info(
                f"Telegram xabari navbatga qo'yildi | "
                f"task_id={task.id} | store={store.name} | "
                f"message_id={message.message_id}"
            )
        except Exception as e:
            logger.error(
                f"Celery navbatga qo'shishda xato: {e}",
                exc_info=True,
            )
            # Celery ishlamasa ham Telegram'ga 200 qaytaramiz
            # (Sentry bu xatoni ushlab qoladi)

        # 7. Telegram 200 kutadi — doim 200 qaytaramiz
        return HttpResponse(status=200)

    def _resolve_store_for_message(self, default_store: Store, message) -> Store:
        """
        Single Master Bot Model uchun:
        /start store_123 deep-linki yoki foydalanuvchining aktiv do'kon sessiyasi bo'yicha dinamik yo'naltiradi.
        """
        from apps.customers.models import CustomerSession
        from django.db.models import Q

        text = (message.text or "").strip()
        sender_id = str(message.sender_id)

        # 1. Deep-link /start store_<uuid> yoki /start admin_<uuid>
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                param = parts[1].strip()
                # admin_ yoki store_ prefixini olib tashlab, faqat UUID qoldiramiz
                target_key = param
                for prefix in ("admin_", "store_"):
                    if param.startswith(prefix):
                        target_key = param[len(prefix):]
                        break

                # UUID bo'lmagan qiymat kiritilsa crash bo'lmasligi uchun try/except
                #
                # ⚠️ BUG FIX: Store modelida "slug" degan maydon UMUMAN YO'Q
                # (apps/stores/models.py'ni tekshiring). Shu sababli quyidagi
                # so'rov HAR DOIM django.core.exceptions.FieldError bilan
                # portlar edi va pastdagi keng `except Exception: pass` uni
                # jimgina yutib yuborardi — natijada target_store doim None
                # bo'lib qolar, ya'ni /start admin_<uuid> va /start store_<uuid>
                # deep-link orqali do'konga yo'naltirish funksiyasi UMUMAN
                # ishlamas edi (Single Master Bot Model buzilgan edi).
                target_store = None
                try:
                    target_store = Store.objects.filter(
                        Q(id=target_key) | Q(tg_owner_chat_id=target_key),
                        is_active=True,
                        is_deleted=False
                    ).first()
                except Exception:
                    pass

                if target_store:
                    CustomerSession.objects.update_or_create(
                        platform_user_id=sender_id,
                        defaults={"active_store": target_store}
                    )
                    return target_store

        # 2. Mavjud active user session
        sess = CustomerSession.objects.select_related("active_store").filter(
            platform_user_id=sender_id,
            active_store__is_active=True,
            active_store__is_deleted=False
        ).first()

        if sess:
            return sess.active_store

        return default_store

    def _get_store_by_token(self, bot_token: str) -> Store | None:
        """Bot token bo'yicha aktiv do'konni topadi"""
        try:
            return Store.objects.select_related("owner").filter(
                tg_bot_token=bot_token,
                is_active=True,
                is_deleted=False,
            ).order_by("-updated_at", "-created_at").first()
        except Exception as e:
            logger.error(f"Do'konni topishda xato: {e}", exc_info=True)
            return None


    def _is_duplicate(self, store_id, message: IncomingMessage) -> bool:
        """Idempotency: bu xabar avval qayta ishlanganmi?"""
        try:
            return ChatMessage.is_duplicate(
                store_id=store_id,
                message_id=message.message_id,
                platform=message.platform,
            )
        except Exception as e:
            logger.error(f"Idempotency tekshirishda xato: {e}", exc_info=True)
            # Xato bo'lsa — dublikat deb hisoblamay, davom etamiz
            return False


# ─────────────────────────────────────────────────────────────
# INSTAGRAM WEBHOOK
# ─────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class InstagramWebhookView(View):
    """
    Instagram / Meta webhook endpoint.

    URL: /webhook/instagram/
    GET  — Meta webhook verification (bir martalik)
    POST — Yangi xabarlar

    ⚠️ Barcha Meta do'konlari bir URL'ga keladi!
       page_id orqali qaysi do'kon ekanini aniqlaymiz.
    """

    def get(self, request):
        """Meta webhook tasdiqlash so'rovi (bir martalik)"""
        challenge = verify_instagram_challenge(request)
        if challenge:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponse(status=403)

    def post(self, request):
        """Instagram'dan kelgan yangi xabarlarni qabul qiladi"""

        # 1. HMAC imzo tekshiruvi
        if not verify_instagram_signature(request):
            logger.warning("Instagram: ruxsatsiz so'rov (imzo xato)")
            return HttpResponse(status=403)

        # 2. JSON parse
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Instagram: noto'g'ri JSON | {e}")
            return HttpResponse(status=200)

        # 3. Barcha xabarlarni parse qilamiz
        messages = parse_instagram_payload(payload)
        if not messages:
            return HttpResponse(status=200)

        # 4. Har bir xabarni navbatga qo'yamiz
        for message in messages:
            try:
                store = self._get_store_by_page_id(message.bot_token_hint)
                if not store:
                    logger.warning(
                        f"Instagram: do'kon topilmadi | "
                        f"page_id={message.bot_token_hint}"
                    )
                    continue

                # Idempotency tekshiruvi
                if ChatMessage.is_duplicate(
                    store_id=store.id,
                    message_id=message.message_id,
                    platform="instagram",
                ):
                    logger.info(
                        f"Instagram: dublikat xabar skip | "
                        f"message_id={message.message_id}"
                    )
                    continue

                # Celery navbatiga
                task = process_incoming_message.apply_async(
                    kwargs={
                        "store_id": str(store.id),
                        "platform": "instagram",
                        "message_id": message.message_id,
                        "sender_id": message.sender_id,
                        "sender_username": message.sender_username,
                        "text": message.text,
                        "chat_id": message.chat_id,
                        "raw_payload": message.raw_payload,
                    },
                    queue="messages",
                    routing_key="messages",
                )
                logger.info(
                    f"Instagram xabari navbatga qo'yildi | "
                    f"task_id={task.id} | store={store.name}"
                )

            except Exception as e:
                logger.error(
                    f"Instagram xabarni navbatga qo'shishda xato: {e}",
                    exc_info=True,
                )
                continue

        return HttpResponse(status=200)

    def _get_store_by_page_id(self, page_id: str) -> Store | None:
        """Instagram Page ID bo'yicha aktiv do'konni topadi"""
        if not page_id:
            return None
        try:
            return Store.objects.select_related("owner").get(
                ig_page_id=page_id,
                is_active=True,
                is_deleted=False,
            )
        except Store.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Do'konni topishda xato: {e}", exc_info=True)
            return None


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────

def webhook_health(request):
    """
    Master SaaS Bot Gateway va Webhook serverining sog'lig'ini Telegram API /getMe orqali tekshirish.
    """
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    bot_username = "unknown"
    bot_active = False

    if bot_token:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)  # /getMe is a GET endpoint
                data = resp.json()
                if resp.status_code == 200 and data.get("ok"):
                    bot_active = True
                    bot_username = data.get("result", {}).get("username", "unknown")
                else:
                    # Bot token yaroqsiz bo'lsa — do'kon egasiga zudlik bilan Telegram xabarnomasi
                    from apps.stores.models import Store
                    from apps.chat.senders import send_telegram_message
                    stores = Store.objects.filter(is_active=True, is_deleted=False)
                    for store in stores:
                        if store.tg_owner_chat_id:
                            send_telegram_message(
                                bot_token=bot_token,
                                chat_id=store.tg_owner_chat_id,
                                text="🚨 DIQQAT! PLATFORMA TELEGRAM BOTI ALOQADAN UZILDI!\n\nBot tokeni yaroqsiz bo'ldi yoki Telegram API ishlamayapti. Iltimos, sozlamalarni tekshiring!"
                            )
        except Exception as e:
            logger.error(f"Master Bot Health Check Exception: {e}")

    return JsonResponse({
        "status": "ok" if bot_active else "degraded",
        "service": "AI-Inbox Master SaaS Gateway",
        "bot_active": bot_active,
        "bot_username": f"@{bot_username}" if bot_username != "unknown" else None,
        "master_bot_model": True
    })
