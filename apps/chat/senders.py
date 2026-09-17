"""
Platform Senders — Telegram va Instagram orqali javob yuborish.

Har bir sender:
- Xatolarni try/except bilan ushlab qoladi
- Tarmoq uzilishida retry qiladi
- Uzoq xabarlarni bo'lib yuboradi
"""
import logging
import time
from datetime import timedelta
from typing import Optional

import httpx
from django.utils import timezone

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
    reply_to_message_id: Optional[str] = None,
) -> bool:
    """
    Telegram bot orqali xabar yuboradi.
    Uzoq xabarlarni bo'lib yuboradi.

    ⚠️ `reply_to_message_id` — guruhlarda MUHIM: bir nechta odam yozib
    turgan guruhda bot javobni oddiy (thread'siz) xabar sifatida yuborsa,
    kim SO'RAGANI va kimga JAVOB berilayotgani chalkashib qolardi
    (foydalanuvchi to'g'ridan-to'g'ri shu muammoni ta'kidladi). Shu
    parametr berilsa, javob Telegram'ning "reply" (iqtibos) funksiyasi
    orqali aynan o'sha xabarga bog'lab yuboriladi.
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
        # Faqat BIRINCHI bo'lak asl xabarga "reply" qilinadi — keyingi
        # bo'laklar shu birinchisining davomi, ularni ham alohida-alohida
        # asl xabarga bog'lash ortiqcha va chalkash bo'lardi.
        current_reply_to = reply_to_message_id if i == 0 else None
        success = _send_telegram_chunk(
            bot_token=bot_token,
            chat_id=chat_id,
            text=chunk,
            parse_mode=parse_mode,
            reply_markup=current_markup,
            reply_to_message_id=current_reply_to,
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
    reply_to_message_id: Optional[str] = None,
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
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
        # Asl xabar biror sabab bilan o'chirilgan/topilmasa ham, javob
        # baribir (oddiy xabar sifatida) yuborilishi uchun — aks holda
        # Telegram butun so'rovni rad etib, mijoz umuman javob olmay qolardi.
        payload["allow_sending_without_reply"] = True

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)

            try:
                data = response.json()
            except Exception:
                logger.error(
                    f"Telegram API JSON parse xatosi: "
                    f"status={response.status_code} | body={response.text[:200]}"
                )
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False

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



def send_telegram_lead_notification(
    bot_token: str,
    owner_chat_id: str,
    lead,
) -> bool:
    """
    Do'kon egasiga yangi lid haqida chiroyli xabar yuboradi.
    """
    if not owner_chat_id:
        logger.warning("Egaga xabarnoma: tg_owner_chat_id yo'q!")
        return False

    text = _format_lead_notification(lead)
    return send_telegram_message(
        bot_token=bot_token,
        chat_id=owner_chat_id,
        text=text,
        parse_mode="HTML",
    )


def _format_lead_notification(lead) -> str:
    """Lid xabarnoma matnini formatlaydi"""
    from django.utils import timezone

    status_labels = {
        "warm": "🔥 Iliq",
        "cold": "❄️ Sovuq",
        "unqualified": "❓ Aniqlanmagan",
    }
    status_text = status_labels.get(lead.lead_status, lead.lead_status)

    course_text = (
        f"📚 <b>Qiziqqan:</b> {lead.interested_course.name}\n"
        if lead.interested_course else ""
    )

    # Mijozning Telegram @username'i (bo'lsa) — egasi mijozning shaxsiy
    # profiliga tezroq o'tishi uchun.
    username_text = ""
    customer = getattr(lead, "customer", None)
    if customer and getattr(customer, "username", None):
        username_text = f"🔗 <b>Telegram:</b> @{customer.username}\n"

    return (
        f"🆕 <b>YANGI LID!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Raqam:</b> {lead.lead_number}\n"
        f"👤 <b>Ism:</b> {lead.customer_full_name}\n"
        f"{username_text}"
        f"📞 <b>Tel:</b> {lead.customer_phone}\n"
        f"{course_text}"
        f"🌡 <b>Holat:</b> {status_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {timezone.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"📲 Platforma: {lead.platform.upper()}"
    )


# ─────────────────────────────────────────────────────────────
# INSTAGRAM SENDER (24-hour window bilan yangi versiyalar pastda)
# ─────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────
# UNIVERSAL SENDER
# ─────────────────────────────────────────────────────────────

def send_reply(
    store,
    platform: str,
    chat_id: str,
    text: str,
    customer=None,
    reply_to_message_id: Optional[str] = None,
) -> bool:
    """
    Platforma turini avtomatik aniqlaydi va javob yuboradi.

    Args:
        store: Store obyekti (tokenlar uchun)
        platform: "telegram" | "instagram"
        chat_id: Javob yuboriladigan chat/user ID
        text: Yuborilinadigan matn
        customer: Customer obyekti (ixtiyoriy — Instagram 24h window uchun)
        reply_to_message_id: Telegram guruhlarida javobni aynan qaysi
            xabarga "reply" qilib bog'lash kerakligi (shaxsiy chatda kerak
            emas — faqat guruhda bir nechta kishi yozganda kim kimga
            javob berilayotganini aniq qilish uchun ishlatiladi).

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
                reply_to_message_id=reply_to_message_id,
            )

        elif platform == "instagram":
            if not store.ig_access_token:
                logger.error(
                    f"Instagram token yo'q: store={store.name}"
                )
                return False

            # Meta 24-Hour Messaging Window tekshiruvi
            within_24h = _check_24h_window(customer)

            return send_instagram_message(
                access_token=store.ig_access_token,
                recipient_id=chat_id,
                text=text,
                within_24h_window=within_24h,
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


# ─────────────────────────────────────────────────────────────
# INSTAGRAM — 24-HOUR MESSAGING WINDOW (META POLICY)
# ─────────────────────────────────────────────────────────────

def _check_24h_window(customer=None) -> bool:
    """
    Meta Instagram Messaging Policy tekshiruvi.

    Instagram faqat mijoz yozganidan keyin 24 soat ichida
    'RESPONSE' messaging_type bilan javob yuborishga ruxsat beradi.
    24 soatdan keyin 'MESSAGE_TAG' + 'HUMAN_AGENT' tegi ishlatilishi kerak.

    Args:
        customer: Customer obyekti (last_message_at tekshiruv uchun)

    Returns:
        True  — 24 soat ichida (RESPONSE ishlatish mumkin)
        False — 24 soatdan o'tgan (MESSAGE_TAG kerak)
    """
    if customer is None:
        # Customer ma'lumoti yo'q — ehtiyot bo'lib RESPONSE ishlatamiz
        return True

    last_msg_at = getattr(customer, "last_message_at", None)
    if not last_msg_at:
        # Mijozdan hech qachon xabar kelmagan — ehtiyot bo'lib RESPONSE
        return True

    elapsed = timezone.now() - last_msg_at
    within_window = elapsed <= timedelta(hours=24)

    if not within_window:
        logger.info(
            f"[24h Window] O'tgan: customer={customer.platform_user_id} | "
            f"oxirgi xabar={last_msg_at} | "
            f"o'tgan vaqt={elapsed}"
        )

    return within_window


# ─────────────────────────────────────────────────────────────
# INSTAGRAM — MEDIA ATTACHMENT SENDER
# ─────────────────────────────────────────────────────────────

def send_instagram_media(
    access_token: str,
    recipient_id: str,
    media_url: str,
    media_type: str = "image",
    caption: str = "",
    within_24h_window: bool = True,
) -> bool:
    """
    Instagram DM orqali media fayl (rasm, video) yuboradi.

    Meta Graph API: POST /me/messages
    Format:
      {
        "recipient": {"id": IGSID},
        "message": {
          "attachment": {
            "type": "image",
            "payload": {"url": "https://...", "is_reusable": true}
          }
        }
      }

    Args:
        access_token: Do'konning ig_access_token
        recipient_id: Mijozning IGSID
        media_url: Media faylining public URL
        media_type: "image" | "video" | "audio" | "file"
        caption: Rasm ostidagi izoh (ixtiyoriy, text sifatida alohida yuboriladi)
        within_24h_window: 24 soatlik oynada ekanligini bildiradi

    Returns:
        True — muvaffaqiyatli
        False — xato
    """
    if not access_token or not recipient_id or not media_url:
        logger.warning(
            f"[IG Media] Bo'sh parametr | recipient={recipient_id!r}"
        )
        return False

    url = "https://graph.facebook.com/v18.0/me/messages"

    # 24 soatlik oynaga qarab messaging_type tanlash
    if within_24h_window:
        messaging_type = "RESPONSE"
        tag_field = {}
    else:
        messaging_type = "MESSAGE_TAG"
        tag_field = {"tag": "HUMAN_AGENT"}

    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": media_type,
                "payload": {
                    "url": media_url,
                    "is_reusable": True,
                },
            }
        },
        "messaging_type": messaging_type,
        "access_token": access_token,
        **tag_field,
    }

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, json=payload)

            data = response.json()

            if response.status_code == 200 and "message_id" in data:
                logger.info(
                    f"[IG Media] Yuborildi: recipient={recipient_id} | "
                    f"type={media_type}"
                )
                # Caption bo'lsa — alohida text xabar sifatida yuboramiz
                if caption:
                    send_instagram_message(
                        access_token=access_token,
                        recipient_id=recipient_id,
                        text=caption,
                        within_24h_window=within_24h_window,
                    )
                return True

            error = data.get("error", {})
            error_code = error.get("code", 0)

            # Token eskirgan
            if error_code in (190, 102):
                logger.error(
                    f"[IG Media] Token eskirgan! code={error_code}"
                )
                return False

            # Rate limit
            if response.status_code == 429:
                logger.warning("[IG Media] Rate limit! 30s kutilmoqda...")
                time.sleep(30)
                continue

            logger.error(
                f"[IG Media] API xatosi: "
                f"status={response.status_code} | {data}"
            )

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        except httpx.TimeoutException:
            logger.warning(f"[IG Media] Timeout (urinish {attempt})")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"[IG Media] Kutilmagan xato: {e}", exc_info=True)
            return False

    return False


# ─────────────────────────────────────────────────────────────
# INSTAGRAM — send_instagram_message 24h YANGILASH
# ─────────────────────────────────────────────────────────────

def send_instagram_message(
    access_token: str,
    recipient_id: str,
    text: str,
    within_24h_window: bool = True,
) -> bool:
    """
    Instagram Messaging API orqali xabar yuboradi.
    (24-Hour Window Policy bilan yangilangan versiya)

    Meta Graph API: POST /me/messages

    Args:
        access_token: Do'konning Instagram long-lived access token
        recipient_id: Mijozning Instagram ID (IGSID)
        text: Xabar matni
        within_24h_window: True — RESPONSE, False — MESSAGE_TAG + HUMAN_AGENT

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
            within_24h_window=within_24h_window,
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
    within_24h_window: bool = True,
) -> bool:
    """
    Bitta Instagram xabar bo'lagini yuboradi.
    24-Hour Window Policy'ga mos messaging_type tanlaydi.
    """
    url = "https://graph.facebook.com/v18.0/me/messages"

    # Meta 24-Hour Messaging Window Policy
    # Agar 24 soat ichida bo'lsa: RESPONSE
    # Agar o'tib ketgan bo'lsa: MESSAGE_TAG + HUMAN_AGENT
    if within_24h_window:
        messaging_type = "RESPONSE"
        tag_field = {}
    else:
        messaging_type = "MESSAGE_TAG"
        tag_field = {"tag": "HUMAN_AGENT"}
        logger.info(
            f"[IG Sender] 24h oynadan tashqari — "
            f"MESSAGE_TAG/HUMAN_AGENT ishlatilmoqda | "
            f"recipient={recipient_id}"
        )

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": messaging_type,
        "access_token": access_token,
        **tag_field,
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
                        "Instagram: access token eskirgan! "
                        "Do'kon egasi token yangilashi kerak."
                    )
                    return False  # Retry foydasi yo'q

                # Foydalanuvchi bot bilan muloqotni yopgan
                error_subcode = error.get("error_subcode", 0)
                if error_subcode in (2018108, 2018047):
                    logger.warning(
                        f"Instagram: foydalanuvchi xabar qabul qilishni "
                        f"to'xtatgan | recipient={recipient_id}"
                    )
                    return False

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
# VOICE MESSAGE SENDER (Telegram + placeholder Instagram)
# ─────────────────────────────────────────────────────────────

def send_voice_reply(
    store,
    platform: str,
    chat_id: str,
    voice_bytes: bytes,
    caption: str = "",
    customer=None,
) -> bool:
    """
    Operator TWA orqali mijozga ovozli xabar yuboradi.

    Telegram: sendVoice API orqali
    Instagram: Hozircha matn placeholder (Instagram DM'da voice API cheklangan)

    Args:
        store: Store obyekti
        platform: "telegram" | "instagram"
        chat_id: Mijoz chat/user ID
        voice_bytes: Ovozli xabar bajt ma'lumoti
        caption: Izoh matni (ixtiyoriy)
        customer: Customer obyekti (ixtiyoriy — Instagram 24h window uchun)

    Returns:
        True — yuborildi
        False — xato
    """
    if platform == "telegram":
        if not store.tg_bot_token:
            logger.error(f"[Voice] Telegram token yo'q: store={store.name}")
            return False

        url = f"https://api.telegram.org/bot{store.tg_bot_token}/sendVoice"
        try:
            with httpx.Client(timeout=30.0) as client:
                files = {"voice": ("voice.ogg", voice_bytes, "audio/ogg")}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption

                response = client.post(url, data=data, files=files)

            result = response.json()
            if response.status_code == 200 and result.get("ok"):
                logger.info(
                    f"[Voice] Telegram ovozli xabar yuborildi: "
                    f"chat_id={chat_id}"
                )
                return True
            else:
                logger.error(
                    f"[Voice] Telegram sendVoice xatosi: {result}"
                )
                return False

        except Exception as e:
            logger.error(
                f"[Voice] Telegram sendVoice kutilmagan xato: {e}",
                exc_info=True,
            )
            return False

    elif platform == "instagram":
        # Instagram DM API voice xabar yuborishni to'g'ridan-to'g'ri qo'llab-quvvatlamaydi.
        # Operatorga text placeholder yuboramiz.
        logger.info(
            "[Voice] Instagram: voice to'g'ridan-to'g'ri qo'llab-quvvatlanmaydi, "
            "matn placeholder yuborilmoqda."
        )
        if not store.ig_access_token:
            return False
        placeholder = caption or "🎙️ Operator tomonidan ovozli xabar"
        return send_instagram_message(
            access_token=store.ig_access_token,
            recipient_id=chat_id,
            text=placeholder,
            within_24h_window=_check_24h_window(customer),
        )

    else:
        logger.error(f"[Voice] Noto'g'ri platforma: {platform!r}")
        return False
