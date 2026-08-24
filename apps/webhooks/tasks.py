"""
Webhook Celery Tasks — To'liq implementatsiya (4-qadam).

Ishlash oqimi:
1. Do'konni DB'dan olish
2. Mijozni topish / yaratish
3. Xabarni DB'ga saqlash (idempotency)
4. Gemini AI'ga jo'natish → javob olish
5. AI javobini DB'ga saqlash
6. Javobni platforma orqali yuborish
7. Buyurtma aniqlangan bo'lsa → Order yaratish + egasiga xabarnoma

SaaS qoidalari:
- max_retries=3 + eksponensial backoff
- acks_late=True → task yo'qolmaydi
- Har bir do'kon alohida Celery queue'da
"""
import logging
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded

logger = logging.getLogger("apps.webhooks")


@shared_task(
    bind=True,
    name="apps.webhooks.tasks.process_incoming_message",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=300,        # 5 daqiqa hard limit
    soft_time_limit=240,   # 4 daqiqa soft limit
)
def process_incoming_message(
    self,
    store_id: str,
    platform: str,
    message_id: str,
    sender_id: str,
    sender_username: str,
    text: str,
    chat_id: str,
    raw_payload: dict,
):
    """
    Webhook'dan qabul qilingan xabarni qayta ishlaydi.

    Bu task webhook view'dan chaqiriladi va:
    - AI dan javob oladi (Gemini)
    - Javobni platforma orqali yuboradi
    - Buyurtma aniqlansa — Order yaratadi va egasiga xabar yuboradi
    """
    from apps.stores.models import Store
    from apps.customers.models import Customer
    from apps.chat.models import ChatMessage
    from apps.chat.ai_service import get_ai_response
    from apps.chat.senders import send_reply
    from apps.chat.order_service import create_order_from_ai_data, notify_store_owner

    logger.info(
        f"[Task] Boshlandi | store={store_id[:8]} | "
        f"platform={platform} | msg_id={message_id} | "
        f"task={self.request.id}"
    )

    try:
        # ── 1. Do'konni olish ────────────────────────────────────────
        try:
            store = Store.objects.select_related("owner").get(
                id=store_id,
                is_active=True,
                is_deleted=False,
            )
        except Store.DoesNotExist:
            logger.error(f"[Task] Do'kon topilmadi: store_id={store_id}")
            return  # Retry qilmaymiz

        # ── 2. Mijozni topish / yaratish ──────────────────────────────
        customer, is_new_customer = Customer.get_or_create_from_platform(
            store=store,
            platform=platform,
            platform_user_id=sender_id,
            username=sender_username,
        )
        if is_new_customer:
            logger.info(f"[Task] Yangi mijoz: {customer}")

        # ── 3. Xabarni DB'ga saqlash (idempotency) ────────────────────
        chat_message, msg_created = ChatMessage.all_objects.get_or_create(
            store=store,
            message_id=message_id,
            platform=platform,
            defaults={
                "customer": customer,
                "role": ChatMessage.Role.USER,
                "content": text,
                "raw_payload": raw_payload,
                "processing_status": ChatMessage.ProcessingStatus.PROCESSING,
                "celery_task_id": self.request.id,
            },
        )

        if not msg_created and chat_message.processing_status == ChatMessage.ProcessingStatus.COMPLETED:
            # Allaqachon muvaffaqiyatli yakunlangan — dublikat
            logger.info(
                f"[Task] Dublikat xabar, skip: msg_id={message_id}"
            )
            return

        # ── 4. Slash buyruqlarni (/start, /dashboard, /help) maxsus qayta ishlash ──
        cmd_text = text.strip().lower()
        if cmd_text.startswith("/start") or cmd_text.startswith("/dashboard") or cmd_text in ["start", "dashboard"]:
            logger.info(f"[Task] /start buyrug'i keldi -> AI'ga borolmaydi, bevosita Ilovaga Kirish tugmasi yuborilmoqda")
            welcome_text = (
                f"<b>Assalomu alaykum! {store.name} botiga xush kelibsiz! 😊</b>\n\n"
                f"Ilovani ochish va do'kon paneliga kirish uchun pastdagi tugmani bosing 👇"
            )
            twa_url = f"https://granddad-upstage-reflector.ngrok-free.dev/app/"
            reply_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "🚀 Ilovaga kirish",
                            "web_app": {"url": twa_url}
                        }
                    ]
                ]
            }
            from apps.chat.senders import send_telegram_message
            send_telegram_message(
                bot_token=store.tg_bot_token,
                chat_id=chat_id,
                text=welcome_text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        if cmd_text.startswith("/help") or cmd_text in ["help", "yordam"]:
            logger.info(f"[Task] /help buyrug'i keldi -> Yordam ko'rsatmasi yuborilmoqda")
            help_text = (
                f"<b>❓ Yordam va Ko'rsatmalar — {store.name}</b>\n\n"
                f"1. 💬 <b>Savol berish</b>: Shunchaki xabaringizni yozing, AI sotuvchimiz darhol javob beradi.\n"
                f"2. 🛍️ <b>Buyurtma berish</b>: Mahsulot nomini, ismingiz, telefon va manzilingizni yozsangiz AI avtomatik buyurtma oladi.\n"
                f"3. 📊 <b>Dashboard</b>: Pastdagi tugma orqali do'kon boshqaruv paneliga kiring."
            )
            from apps.chat.senders import send_telegram_message
            send_telegram_message(
                bot_token=store.tg_bot_token,
                chat_id=chat_id,
                text=help_text,
                parse_mode="HTML",
            )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ── 5. Gemini AI'ga jo'natish ──────────────────────────────────
        logger.info(
            f"[Task] AI chaqirilmoqda | store={store.name} | "
            f"model={store.ai_model}"
        )

        ai_response = get_ai_response(
            store=store,
            customer=customer,
            user_message=text,
        )

        logger.info(
            f"[Task] AI javob olindi | "
            f"tokens={ai_response.tokens_used} | "
            f"has_order={ai_response.has_order}"
        )

        # ── 5. AI javobini DB'ga saqlash ──────────────────────────────
        ai_message = ChatMessage.objects.create(
            store=store,
            customer=customer,
            message_id=f"ai_resp_{message_id}",
            platform=platform,
            role=ChatMessage.Role.ASSISTANT,
            content=ai_response.text,
            processing_status=ChatMessage.ProcessingStatus.COMPLETED,
            celery_task_id=self.request.id,
            tokens_used=ai_response.tokens_used,
            ai_model_used=ai_response.model_used,
        )

        # ── 6. Javobni platforma orqali yuborish ──────────────────────
        sent = send_reply(
            store=store,
            platform=platform,
            chat_id=chat_id,
            text=ai_response.text,
        )

        if not sent:
            logger.warning(
                f"[Task] Javob yuborilmadi! "
                f"platform={platform} | chat_id={chat_id}"
            )
            # Yuborilmagan bo'lsa ham davom etamiz (buyurtma saqlash kerak)

        # ── 7. Buyurtma aniqlangan bo'lsa ──────────────────────────────
        if ai_response.has_order and ai_response.order_data:
            logger.info(
                f"[Task] Buyurtma aniqlandi! "
                f"mijoz={ai_response.order_data.get('full_name')}"
            )

            order = create_order_from_ai_data(
                store=store,
                customer=customer,
                order_data=ai_response.order_data,
                platform=platform,
                source_message=ai_message,
            )

            if order:
                # Egasiga Telegram xabarnomasi
                notify_store_owner(store=store, order=order)
            else:
                logger.warning(
                    f"[Task] Buyurtma aniqlandi lekin saqlanmadi! "
                    f"data={ai_response.order_data}"
                )

        # ── 8. Dastlabki xabarni COMPLETED deb belgilash ──────────────
        ChatMessage.objects.filter(id=chat_message.id).update(
            processing_status=ChatMessage.ProcessingStatus.COMPLETED,
        )

        # ── 9. Mijozning oxirgi faollik vaqtini yangilash ─────────────
        from django.utils import timezone
        Customer.objects.filter(id=customer.id).update(
            last_message_at=timezone.now()
        )

        logger.info(
            f"[Task] MUVAFFAQIYATLI | store={store.name} | "
            f"msg_id={message_id}"
        )

    except SoftTimeLimitExceeded:
        # Task juda uzoq ishladi
        logger.error(
            f"[Task] Vaqt limitini oshdi (soft) | "
            f"store_id={store_id} | msg_id={message_id}"
        )
        _mark_message_failed(store_id, message_id, platform, "SoftTimeLimitExceeded")

    except MaxRetriesExceededError:
        logger.error(
            f"[Task] Max retry oshdi | store_id={store_id} | msg_id={message_id}"
        )
        _mark_message_failed(store_id, message_id, platform, "MaxRetriesExceeded")

    except Exception as e:
        logger.error(
            f"[Task] XATO | store_id={store_id} | msg_id={message_id} | "
            f"retry={self.request.retries}/{self.max_retries} | {e}",
            exc_info=True,
        )

        # DB'da retry sonini yangilash
        _update_retry_count(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
            retry_count=self.request.retries + 1,
            error=str(e),
        )

        # Eksponensial backoff: 5s → 25s → 125s
        countdown = 5 ** (self.request.retries + 1)

        try:
            raise self.retry(exc=e, countdown=countdown)
        except MaxRetriesExceededError:
            _mark_message_failed(store_id, message_id, platform, str(e))


# ─────────────────────────────────────────────────────────────
# DATA RETENTION TASK — Eski xabarlarni tozalash
# ─────────────────────────────────────────────────────────────

@shared_task(
    name="apps.webhooks.tasks.cleanup_old_messages",
    ignore_result=True,
)
def cleanup_old_messages():
    """
    Eski ChatMessage'larni soft-delete qiladi.
    Celery Beat orqali har kech ishga tushadi.

    CHAT_MESSAGE_RETENTION_DAYS (default: 90 kun) dan
    eski xabarlar o'chiriladi.
    """
    from django.conf import settings
    from django.utils import timezone
    from datetime import timedelta
    from apps.chat.models import ChatMessage

    retention_days = getattr(settings, "CHAT_MESSAGE_RETENTION_DAYS", 90)
    cutoff_date = timezone.now() - timedelta(days=retention_days)

    try:
        count = ChatMessage.objects.filter(
            created_at__lt=cutoff_date,
            is_deleted=False,
        ).update(is_deleted=True)

        logger.info(
            f"[Data Retention] {count} ta xabar soft-delete qilindi "
            f"(>{retention_days} kun)"
        )
        return count

    except Exception as e:
        logger.error(f"[Data Retention] Xato: {e}", exc_info=True)
        return 0


# ─────────────────────────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────────────────────

def _mark_message_failed(store_id, message_id, platform, error_msg):
    """ChatMessage'ni FAILED deb belgilaydi"""
    try:
        from apps.chat.models import ChatMessage
        ChatMessage.all_objects.filter(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
        ).update(
            processing_status=ChatMessage.ProcessingStatus.FAILED,
            error_message=error_msg[:500],
        )
    except Exception as e:
        logger.error(f"_mark_message_failed xatosi: {e}")


def _update_retry_count(store_id, message_id, platform, retry_count, error):
    """ChatMessage'da retry sonini yangilaydi"""
    try:
        from apps.chat.models import ChatMessage
        ChatMessage.all_objects.filter(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
        ).update(
            retry_count=retry_count,
            error_message=str(error)[:500],
        )
    except Exception as e:
        logger.error(f"_update_retry_count xatosi: {e}")
