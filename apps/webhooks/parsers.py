"""
Webhook Parserlari — Instagram va Telegram payload'larini
tizim ichki formatiga o'giradi.

Har doim try/except bilan ishlaydi — noto'g'ri JSON kelsa
tizim qulamasligi kerak.
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("apps.webhooks")


@dataclass
class IncomingMessage:
    """
    Platformadan kelgan xabarning normallashtirilgan ko'rinishi.
    Instagram ham, Telegram ham shu formatga o'giriladi.
    """
    platform: str           # "instagram" | "telegram"
    message_id: str         # Idempotency uchun platformadagi xabar ID
    sender_id: str          # Platformadagi foydalanuvchi ID
    sender_username: str    # @username (bo'lsa)
    text: str               # Xabar matni
    chat_id: str            # Javob yuborish uchun chat ID
    raw_payload: dict       # To'liq original payload (debug uchun)
    # Bot token (qaysi do'konning boti ekanini aniqlash uchun)
    bot_token_hint: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# TELEGRAM PARSER
# ─────────────────────────────────────────────────────────────

def parse_telegram_payload(payload: dict) -> Optional[IncomingMessage]:
    """
    Telegram webhook payload'ini IncomingMessage'ga o'giradi.

    Telegram payload formati:
    {
        "update_id": 123456789,
        "message": {
            "message_id": 42,
            "from": {"id": 111, "username": "user123"},
            "chat": {"id": 111},
            "text": "Salom, mahsulot bormi?"
        }
    }

    Returns:
        IncomingMessage — muvaffaqiyatli parse qilindi
        None — noto'g'ri yoki qo'llab-quvvatlanmaydigan payload
    """
    try:
        # Telegram turli xil update turlari yuboradi
        # Biz faqat oddiy "message" turidagilari bilan ishlaymiz
        message = payload.get("message") or payload.get("edited_message")

        if not message:
            # Callback query, inline va h.k. — hozircha o'tkazib yuboramiz
            logger.debug(
                f"Telegram: message maydoni yo'q. "
                f"Update turi: {list(payload.keys())}"
            )
            return None

        # Matn bo'lmasa (rasm, sticker va h.k.) — hozircha o'tkazamiz
        text = message.get("text", "").strip()
        if not text:
            logger.debug("Telegram: Matn bo'sh, o'tkazib yuborildi.")
            return None

        sender = message.get("from", {})
        sender_id = str(sender.get("id", ""))
        if not sender_id:
            logger.warning("Telegram: sender.id topilmadi.")
            return None

        message_id = str(message.get("message_id", ""))
        chat_id = str(message.get("chat", {}).get("id", sender_id))
        username = sender.get("username", "") or sender.get("first_name", "")

        return IncomingMessage(
            platform="telegram",
            message_id=message_id,
            sender_id=sender_id,
            sender_username=username,
            text=text,
            chat_id=chat_id,
            raw_payload=payload,
        )

    except (KeyError, TypeError, AttributeError) as e:
        logger.error(
            f"Telegram payload parse xatosi: {e} | Payload: {payload}",
            exc_info=True,
        )
        return None


# ─────────────────────────────────────────────────────────────
# INSTAGRAM PARSER
# ─────────────────────────────────────────────────────────────

def parse_instagram_payload(payload: dict) -> list[IncomingMessage]:
    """
    Instagram webhook payload'ini IncomingMessage ro'yxatiga o'giradi.

    Instagram bir payload'da bir nechta xabar yuborishi mumkin!
    Shuning uchun list qaytaradi.

    Instagram payload formati:
    {
        "object": "instagram",
        "entry": [{
            "id": "PAGE_ID",
            "messaging": [{
                "sender": {"id": "USER_ID"},
                "recipient": {"id": "PAGE_ID"},
                "timestamp": 1234567890,
                "message": {
                    "mid": "MESSAGE_ID",
                    "text": "Salom!"
                }
            }]
        }]
    }

    Returns:
        List[IncomingMessage] — parse qilingan xabarlar
        [] — xato yoki bo'sh payload
    """
    messages = []

    try:
        if payload.get("object") not in ("instagram", "page"):
            logger.warning(
                f"Instagram: noto'g'ri object turi: {payload.get('object')}"
            )
            return []

        entries = payload.get("entry", [])
        if not entries:
            return []

        for entry in entries:
            page_id = entry.get("id", "")
            messaging_events = entry.get("messaging", [])

            for event in messaging_events:
                try:
                    msg_data = event.get("message", {})

                    # Echo xabarlarni o'tkazib yuboramiz
                    # (bot o'z xabarini webhook orqali qayta ololishi mumkin)
                    if msg_data.get("is_echo"):
                        continue

                    text = msg_data.get("text", "").strip()
                    if not text:
                        continue

                    message_id = msg_data.get("mid", "")
                    sender_id = str(event.get("sender", {}).get("id", ""))

                    if not message_id or not sender_id:
                        continue

                    messages.append(
                        IncomingMessage(
                            platform="instagram",
                            message_id=message_id,
                            sender_id=sender_id,
                            sender_username="",   # Instagram username API'da alohida so'raladi
                            text=text,
                            chat_id=sender_id,    # IG'da chat_id = sender_id
                            raw_payload=event,
                            bot_token_hint=page_id,
                        )
                    )

                except (KeyError, TypeError) as e:
                    logger.warning(
                        f"Instagram: bitta event parse xatosi: {e}",
                        exc_info=True,
                    )
                    continue

    except Exception as e:
        logger.error(
            f"Instagram payload parse xatosi: {e} | Payload: {payload}",
            exc_info=True,
        )

    return messages
