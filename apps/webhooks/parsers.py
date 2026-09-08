"""
Webhook Parserlari — Instagram va Telegram payload'larini
tizim ichki formatiga o'giradi.

Har doim try/except bilan ishlaydi — noto'g'ri JSON kelsa
tizim qulamasligi kerak.

Instagram xabar turlari (Task 2):
  - text          : Oddiy matn xabari
  - image         : Rasm (attachment.type = image)
  - audio         : Audio/voice xabar
  - video         : Video xabar
  - sticker       : Sticker
  - share         : Post/Reel ulashish
  - story_mention : Foydalanuvchi sizning post'ingizni story'sida eslatdi
  - story_reply   : Story'ga javob
  - quick_reply   : Quick Reply tugmasini bosish
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
    text: str               # Xabar matni (media bo'lsa — tavsif)
    chat_id: str            # Javob yuborish uchun chat ID
    raw_payload: dict       # To'liq original payload (debug uchun)

    # ── Media ma'lumotlari (Instagram media xabarlari uchun) ──
    media_url: Optional[str] = None        # Media faylining URL'i (rasm, video, audio)
    media_type: Optional[str] = None       # "image" | "audio" | "video" | "sticker" | "file"
    attachment_type: Optional[str] = None  # Instagram attachment turi: "image", "audio", "share", "story_mention" va h.k.

    # ── Bot token (qaysi do'konning boti ekanini aniqlash uchun) ──
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

        # Matn bo'lmasa, ovozli xabarlar (voice) mavjudligini tekshiramiz
        text = message.get("text", "").strip()
        voice = message.get("voice")
        if not text and voice:
            duration = voice.get("duration", 0)
            text = f"🎙️ Ovozli xabar ({duration}s)"
        elif not text:
            logger.debug("Telegram: Matn yoki ovoz bo'sh, o'tkazib yuborildi.")
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
# INSTAGRAM PARSER (Advanced — Task 2)
# ─────────────────────────────────────────────────────────────

def parse_instagram_payload(payload: dict) -> list[IncomingMessage]:
    """
    Instagram webhook payload'ini IncomingMessage ro'yxatiga o'giradi.

    Instagram bir payload'da bir nechta xabar yuborishi mumkin!
    Shuning uchun list qaytaradi.

    Qo'llab-quvvatlanadigan xabar turlari:
      1. text           — Oddiy matn xabari
      2. image          — Rasm (attachment.type = "image")
      3. audio          — Audio/voice xabar
      4. video          — Video xabar
      5. sticker        — Sticker
      6. share          — Post/Reel ulashish
      7. story_mention  — Story'da eslatish (messaging_referrals)
      8. story_reply    — Story'ga javob
      9. quick_reply    — Quick Reply tugmasini bosish

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

            # ── messaging events (DM, quick_reply, attachments) ──
            messaging_events = entry.get("messaging", [])
            for event in messaging_events:
                parsed = _parse_instagram_messaging_event(event, page_id)
                if parsed:
                    messages.append(parsed)

            # ── changes events (story_mention, postback va h.k.) ──
            changes = entry.get("changes", [])
            for change in changes:
                parsed = _parse_instagram_change_event(change, page_id)
                if parsed:
                    messages.extend(parsed)

    except Exception as e:
        logger.error(
            f"Instagram payload parse xatosi: {e} | Payload: {payload}",
            exc_info=True,
        )

    return messages


def _parse_instagram_messaging_event(
    event: dict, page_id: str
) -> Optional[IncomingMessage]:
    """
    Instagram messaging event'ini parse qiladi.
    Bu funksiya barcha DM xabar turlarini qabul qiladi.
    """
    try:
        sender_id = str(event.get("sender", {}).get("id", ""))
        recipient_id = str(event.get("recipient", {}).get("id", ""))

        if not sender_id:
            return None

        # ── Botning o'z xabarlari (echo) — o'tkazib yuboramiz ──
        # recipient_id == page_id bo'lganda bu bot yuborgan xabar
        if sender_id == page_id or sender_id == recipient_id:
            logger.debug(f"Instagram: Echo xabar o'tkazildi (sender={sender_id})")
            return None

        msg_data = event.get("message", {})
        if not msg_data:
            # postback yoki referral — alohida parse
            return None

        # is_echo flag tekshiruvi
        if msg_data.get("is_echo"):
            logger.debug("Instagram: is_echo=True, o'tkazildi.")
            return None

        message_id = msg_data.get("mid", "")
        if not message_id:
            return None

        # ── 1. Quick Reply ──
        quick_reply = msg_data.get("quick_reply", {})
        if quick_reply:
            qr_payload = quick_reply.get("payload", "")
            text = msg_data.get("text", qr_payload or "Quick reply")
            logger.debug(f"Instagram: quick_reply={qr_payload}")
            return IncomingMessage(
                platform="instagram",
                message_id=message_id,
                sender_id=sender_id,
                sender_username="",
                text=text,
                chat_id=sender_id,
                raw_payload=event,
                attachment_type="quick_reply",
                bot_token_hint=page_id,
            )

        # ── 2. Oddiy matn xabari ──
        text = msg_data.get("text", "").strip()
        if text and not msg_data.get("attachments"):
            return IncomingMessage(
                platform="instagram",
                message_id=message_id,
                sender_id=sender_id,
                sender_username="",
                text=text,
                chat_id=sender_id,
                raw_payload=event,
                attachment_type="text",
                bot_token_hint=page_id,
            )

        # ── 3. Attachment xabarlar (rasm, audio, video, sticker, share) ──
        attachments = msg_data.get("attachments", [])
        if attachments:
            # Birinchi attachment'ni asosiy deb olamiz
            attachment = attachments[0]
            att_type = attachment.get("type", "")
            att_payload = attachment.get("payload", {})
            media_url = att_payload.get("url", "")

            # ── Story Reply (story'ga javob) ──
            if att_type == "story_reply":
                story_url = att_payload.get("url", "")
                base_text = text or "📖 Story'ga javob"
                return IncomingMessage(
                    platform="instagram",
                    message_id=message_id,
                    sender_id=sender_id,
                    sender_username="",
                    text=base_text,
                    chat_id=sender_id,
                    raw_payload=event,
                    media_url=story_url or None,
                    media_type="image",
                    attachment_type="story_reply",
                    bot_token_hint=page_id,
                )

            # ── Post/Reel ulashish (share) ──
            if att_type == "share":
                shared_link = att_payload.get("link", "")
                description = att_payload.get("title", "Post/Reel ulashdi")
                display_text = text or f"📤 {description}"
                if shared_link:
                    display_text += f"\n🔗 {shared_link}"
                return IncomingMessage(
                    platform="instagram",
                    message_id=message_id,
                    sender_id=sender_id,
                    sender_username="",
                    text=display_text,
                    chat_id=sender_id,
                    raw_payload=event,
                    media_url=shared_link or None,
                    attachment_type="share",
                    bot_token_hint=page_id,
                )

            # ── Media xabarlar (image, audio, video, sticker, file) ──
            MEDIA_DESCRIPTIONS = {
                "image":   "📷 Rasm yubordi",
                "audio":   "🎵 Audio yubordi",
                "video":   "🎬 Video yubordi",
                "sticker": "😊 Sticker yubordi",
                "file":    "📎 Fayl yubordi",
            }
            if att_type in MEDIA_DESCRIPTIONS:
                display_text = text or MEDIA_DESCRIPTIONS[att_type]
                return IncomingMessage(
                    platform="instagram",
                    message_id=message_id,
                    sender_id=sender_id,
                    sender_username="",
                    text=display_text,
                    chat_id=sender_id,
                    raw_payload=event,
                    media_url=media_url or None,
                    media_type=att_type,
                    attachment_type=att_type,
                    bot_token_hint=page_id,
                )

            # ── Noma'lum attachment turi ──
            display_text = text or f"📎 {att_type} xabari"
            logger.debug(
                f"Instagram: noma'lum attachment turi={att_type!r}, "
                f"oddiy matn sifatida qaytarilmoqda."
            )
            return IncomingMessage(
                platform="instagram",
                message_id=message_id,
                sender_id=sender_id,
                sender_username="",
                text=display_text,
                chat_id=sender_id,
                raw_payload=event,
                attachment_type=att_type,
                bot_token_hint=page_id,
            )

        # ── 4. Story Mention (messaging_referrals bilan keladi, bu yerda text ham bo'lishi mumkin) ──
        # Ba'zan story_mention faqat text sifatida keladi
        if text:
            return IncomingMessage(
                platform="instagram",
                message_id=message_id,
                sender_id=sender_id,
                sender_username="",
                text=text,
                chat_id=sender_id,
                raw_payload=event,
                attachment_type="text",
                bot_token_hint=page_id,
            )

        logger.debug(
            f"Instagram: bo'sh xabar, o'tkazildi | "
            f"sender={sender_id} | mid={message_id}"
        )
        return None

    except (KeyError, TypeError) as e:
        logger.warning(
            f"Instagram messaging event parse xatosi: {e}",
            exc_info=True,
        )
        return None


def _parse_instagram_change_event(
    change: dict, page_id: str
) -> list[IncomingMessage]:
    """
    Instagram 'changes' event'larini parse qiladi.

    Story Mention (messaging_referrals) bu orqali keladi:
    {
        "field": "mentions",
        "value": {
            "media_id": "...",
            "comment_id": "..."  # ixtiyoriy
        }
    }
    """
    results = []
    try:
        field = change.get("field", "")
        value = change.get("value", {})

        # ── Story Mention ──
        if field in ("mentions", "messaging_referrals", "story_mention"):
            sender_id = str(value.get("sender_id", value.get("from", {}).get("id", "")))
            media_id = value.get("media_id", "")

            if not sender_id:
                logger.debug("Instagram story_mention: sender_id topilmadi.")
                return []

            message_id = f"story_mention_{media_id or sender_id}"
            text = "📸 Story'da eslatib o'tdi"

            results.append(IncomingMessage(
                platform="instagram",
                message_id=message_id,
                sender_id=sender_id,
                sender_username="",
                text=text,
                chat_id=sender_id,
                raw_payload=change,
                attachment_type="story_mention",
                bot_token_hint=page_id,
            ))
            logger.info(
                f"Instagram: story_mention aniqlandi | "
                f"sender={sender_id} | media_id={media_id}"
            )

    except (KeyError, TypeError) as e:
        logger.warning(
            f"Instagram change event parse xatosi: {e}",
            exc_info=True,
        )

    return results
