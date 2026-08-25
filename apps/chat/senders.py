"""
Platform Senders — Telegram va Instagram orqali javob yuborish.

Har bir sender:
- Xatolarni try/except bilan ushlab qoladi
- Tarmoq uzilishida retry qiladi
- Uzoq xabarlarni bo'lib yuboradi
"""
import logging
import time
from typing import Optional

import httpx
from django.conf import settings

logger = logging.getLogger("apps.chat")

# Telegram matn uzunlik chegarasi
TELEGRAM_MAX_LENGTH = 4096
# Instagram matn uzunlik chegarasi
INSTAGRAM_MAX_LENGTH = 1000


# ─────────────────────────────────────────────────────────────
# TELEGRAM SENDER
# ─────────────────────────────────────────────────────────────

def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: Optional[str] = "HTML",
    reply_markup: Optional[dict] = None,
) -> bool:
    """
    Telegram bot orqali xabar yuboradi.
    Uzoq xabarlarni bo'lib yuboradi.
    """
    if not bot_token or not chat_id or not text:
        logger.warning(
            f"Telegram: bo'sh parametr | "
            f"bot_token={'yes' if bot_token else 'NO'} | "
            f"chat_id={chat_id!r} | text={'yes' if text else 'NO'}"
        )
        return False

    # Uzoq xabarlarni bo'lib yuboramiz
    chunks = _split_text(text, TELEGRAM_MAX_LENGTH)

    all_success = True
    for i, chunk in enumerate(chunks):
        # Reply markup tugmalarini oxirgi bo'lakka biriktiramiz
        current_markup = reply_markup if i == len(chunks) - 1 else None
        success = _send_telegram_chunk(
            bot_token=bot_token,
            chat_id=chat_id,
            text=chunk,
            parse_mode=parse_mode,
            reply_markup=current_markup,
        )
        if not success:
            all_success = False
        # Bir necha bo'lak bo'lsa, oraliqda kutamiz
        if i < len(chunks) - 1:
            time.sleep(0.3)

    return all_success


def _send_telegram_chunk(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str,
    reply_markup: dict = None,
    max_retries: int = 3,
) -> bool:
    """Bitta Telegram xabar bo'lagini yuboradi (retry bilan)"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)

            data = response.json()

            if response.status_code == 200 and data.get("ok"):
                return True

            # Rate limit (429) — kutib, qayta urinamiz
            if response.status_code == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 5)
                logger.warning(
                    f"Telegram rate limit! {retry_after}s kutilmoqda..."
                )
                time.sleep(retry_after)
                continue

            if response.status_code == 400 and "parse_mode" in payload:
                logger.warning("Telegram parse xatosi! Matnni parse_mode'siz qayta yuboramiz.")
                payload.pop("parse_mode", None)
                continue

            logger.error(
                f"Telegram API xatosi: {response.status_code} | {data}"
            )
            return False

        except httpx.TimeoutException:
            logger.warning(
                f"Telegram timeout (urinish {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except httpx.RequestError as e:
            logger.error(
                f"Telegram so'rov xatosi (urinish {attempt}/{max_retries}): {e}"
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except Exception as e:
            logger.error(
                f"Telegram kutilmagan xato: {e}",
                exc_info=True,
            )
    return False


def send_telegram_voice(
    bot_token: str,
    chat_id: str,
    voice_bytes: bytes,
    caption: str = "",
) -> bool:
    """
    Telegram bot API /sendVoice orqali ovozli xabarni foydalanuvchiga yuboradi.
    """
    if not bot_token or not chat_id or not voice_bytes:
        logger.warning(f"send_telegram_voice: bo'sh parametr | chat_id={chat_id}")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendVoice"
    files = {
        "voice": ("voice.ogg", voice_bytes, "audio/ogg")
    }
    data = {
        "chat_id": chat_id,
    }
    if caption:
        data["caption"] = caption

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=data, files=files)
            res_data = resp.json()
            if resp.status_code == 200 and res_data.get("ok"):
                logger.info(f"Ovozli xabar Telegram chat_id={chat_id}'ga muvaffaqiyatli yuborildi!")
                return True
            logger.error(f"Telegram sendVoice Error: {resp.status_code} | {res_data}")
            return False
    except Exception as e:
        logger.error(f"Telegram voice sending exception: {e}", exc_info=True)
        return False


def send_voice_reply(
    store,
    platform: str,
    chat_id: str,
    voice_bytes: bytes,
    caption: str = "",
) -> bool:
    """
    Platformaga mos ravishda ovozli xabarni foydalanuvchiga yetkazadi.
    """
    bot_token = store.tg_bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if platform.lower() == "telegram":
        return send_telegram_voice(bot_token, chat_id, voice_bytes, caption)
    return False


def send_telegram_order_notification(
    bot_token: str,
    owner_chat_id: str,
    order,
) -> bool:
    """
    Do'kon egasiga yangi buyurtma haqida chiroyli xabar yuboradi.
    """
    if not owner_chat_id:
        logger.warning("Egaga xabarnoma: tg_owner_chat_id yo'q!")
        return False

    text = _format_order_notification(order)
    return send_telegram_message(
        bot_token=bot_token,
        chat_id=owner_chat_id,
        text=text,
        parse_mode="HTML",
    )


def _format_order_notification(order) -> str:
    """Buyurtma xabarnoma matnini formatlaydi"""
    from django.utils import timezone

    items_text = ""
    if order.items:
        for item in order.items:
            name = item.get("name", "Noma'lum")
            qty = item.get("qty", 1)
            price = item.get("price", 0)
            items_text += f"  • {name} × {qty}"
            if price:
                items_text += f" — {price:,} so'm"
            items_text += "\n"
    else:
        items_text = "  • (ma'lumot yo'q)\n"

    total_text = ""
    if order.total_amount:
        total_text = f"\n💰 <b>Jami:</b> {order.total_amount:,} so'm"

    return (
        f"🛍 <b>YANGI BUYURTMA!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Raqam:</b> {order.order_number}\n"
        f"👤 <b>Mijoz:</b> {order.customer_full_name}\n"
        f"📞 <b>Tel:</b> {order.customer_phone}\n"
        f"📍 <b>Manzil:</b> {order.delivery_address}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 <b>Mahsulotlar:</b>\n{items_text}"
        f"{total_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {timezone.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"📲 Platforma: {order.platform.upper()}"
    )


# ─────────────────────────────────────────────────────────────
# INSTAGRAM SENDER
# ─────────────────────────────────────────────────────────────

def send_instagram_message(
    access_token: str,
    recipient_id: str,
    text: str,
) -> bool:
    """
    Instagram Messaging API orqali xabar yuboradi.

    Meta Graph API: POST /me/messages

    Args:
        access_token: Do'konning Instagram long-lived access token
        recipient_id: Mijozning Instagram ID (IGSID)
        text: Xabar matni

    Returns:
        True — muvaffaqiyatli
        False — xato
    """
    if not access_token or not recipient_id or not text:
        logger.warning(
            f"Instagram: bo'sh parametr | "
            f"recipient={recipient_id!r}"
        )
        return False

    # Uzoq xabarlarni bo'lib yuboramiz
    chunks = _split_text(text, INSTAGRAM_MAX_LENGTH)

    all_success = True
    for i, chunk in enumerate(chunks):
        success = _send_instagram_chunk(
            access_token=access_token,
            recipient_id=recipient_id,
            text=chunk,
        )
        if not success:
            all_success = False
        if i < len(chunks) - 1:
            time.sleep(0.5)

    return all_success


def _send_instagram_chunk(
    access_token: str,
    recipient_id: str,
    text: str,
    max_retries: int = 3,
) -> bool:
    """Bitta Instagram xabar bo'lagini yuboradi"""
    url = "https://graph.facebook.com/v18.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
        "access_token": access_token,
    }

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, json=payload)

            data = response.json()

            if response.status_code == 200 and "message_id" in data:
                return True

            # Token eskirgan
            if response.status_code == 400:
                error = data.get("error", {})
                error_code = error.get("code", 0)
                if error_code in (190, 102):
                    logger.error(
                        f"Instagram: access token eskirgan! "
                        f"Do'kon egasi token yangilashi kerak."
                    )
                    return False  # Retry foydasi yo'q

            # Rate limit
            if response.status_code == 429:
                logger.warning("Instagram rate limit! 30s kutilmoqda...")
                time.sleep(30)
                continue

            logger.error(
                f"Instagram API xatosi: {response.status_code} | {data}"
            )

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except httpx.TimeoutException:
            logger.warning(
                f"Instagram timeout (urinish {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except httpx.RequestError as e:
            logger.error(
                f"Instagram so'rov xatosi: {e}",
                exc_info=True,
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except Exception as e:
            logger.error(f"Instagram kutilmagan xato: {e}", exc_info=True)
            return False

    return False


# ─────────────────────────────────────────────────────────────
# UNIVERSAL SENDER
# ─────────────────────────────────────────────────────────────

def send_reply(store, platform: str, chat_id: str, text: str) -> bool:
    """
    Platforma turini avtomatik aniqlaydi va javob yuboradi.

    Args:
        store: Store obyekti (tokenlar uchun)
        platform: "telegram" | "instagram"
        chat_id: Javob yuboriladigan chat/user ID
        text: Yuborilinadigan matn

    Returns:
        True — yuborildi
        False — xato
    """
    if not text or not text.strip():
        logger.warning("send_reply: bo'sh matn, yuborilmadi.")
        return False

    try:
        if platform == "telegram":
            if not store.tg_bot_token:
                logger.error(
                    f"Telegram token yo'q: store={store.name}"
                )
                return False
            return send_telegram_message(
                bot_token=store.tg_bot_token,
                chat_id=chat_id,
                text=text,
            )

        elif platform == "instagram":
            if not store.ig_access_token:
                logger.error(
                    f"Instagram token yo'q: store={store.name}"
                )
                return False
            return send_instagram_message(
                access_token=store.ig_access_token,
                recipient_id=chat_id,
                text=text,
            )

        else:
            logger.error(f"Noto'g'ri platforma: {platform!r}")
            return False

    except Exception as e:
        logger.error(
            f"send_reply xatosi: {e} | platform={platform} | "
            f"store={store.name}",
            exc_info=True,
        )
        return False


# ─────────────────────────────────────────────────────────────
# YORDAMCHI
# ─────────────────────────────────────────────────────────────

def _split_text(text: str, max_length: int) -> list[str]:
    """
    Uzun matnni platformaning chegarasiga mos bo'laklarga ajratadi.
    So'z o'rtasida emas, jumla oxirida ajratadi.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # max_length ichida oxirgi yangi qatorni topamiz
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            # Yangi qator yo'q — so'z bo'yicha ajratamiz
            split_pos = text.rfind(" ", 0, max_length)
        if split_pos == -1:
            # Bo'sh joy ham yo'q — majburiy kesamiz
            split_pos = max_length

        chunks.append(text[:split_pos].strip())
        text = text[split_pos:].strip()

    return [c for c in chunks if c]
