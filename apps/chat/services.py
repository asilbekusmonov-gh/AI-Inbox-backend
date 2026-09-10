"""
Chat Services — Media Yuklab Olish va Saqlash Servislari.

Meta CDN havolalari (cdn.fbsbx.com / fbcdn.net) 48-72 soatdan keyin o'chib ketadi.
Ushbu modul Instagram va Telegram'dan kelgan media birikmalarni (rasm, video, audio)
loyiha saqlash xotirasiga (Django default_storage) saqlaydi.
"""
import logging
import mimetypes
import uuid
from datetime import datetime
from typing import Optional

import httpx
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger("apps.chat")


def download_and_save_media_file(media_url: str, media_type: str = "image") -> Optional[str]:
    """
    Tashqi media URL'dan (masalan Meta CDN) faylni yuklab oladi va
    Django storage'ga saqlaydi.

    Args:
        media_url: Tashqi public URL (https://cdn.fbsbx.com/...)
        media_type: "image" | "video" | "audio" | "sticker" | "file"

    Returns:
        Saqlangan faylning nisbiy URL manzili (masalan: /media/chat_attachments/2026/08/25/abc123.jpg)
        yoki None (yuklab olishda xato bo'lsa)
    """
    if not media_url or not media_url.startswith("http"):
        logger.warning(f"[Media Storage] Noto'g'ri media_url: {media_url!r}")
        return None

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(media_url)

        if response.status_code != 200:
            logger.error(
                f"[Media Storage] HTTP xatosi {response.status_code} | URL: {media_url[:60]}..."
            )
            return None

        content_bytes = response.content
        content_type = response.headers.get("Content-Type", "")

        # Fayl kengaytmasini aniqlash
        ext = _determine_file_extension(media_type, content_type, media_url)

        # Bugungi sana bo'yicha papka yo'li
        now = datetime.now()
        relative_path = f"chat_attachments/{now.year}/{now.month:02d}/{now.day:02d}/{uuid.uuid4().hex}{ext}"

        # Django Storage'ga saqlash
        saved_path = default_storage.save(relative_path, ContentFile(content_bytes))
        saved_url = default_storage.url(saved_path)

        logger.info(
            f"[Media Storage] Fayl muvaffaqiyatli saqlandi: "
            f"{saved_path} ({len(content_bytes)} bytes)"
        )
        return saved_url

    except httpx.TimeoutException:
        logger.error(f"[Media Storage] Timeout URL: {media_url[:60]}...")
        return None
    except Exception as e:
        logger.error(f"[Media Storage] Media yuklashda kutilmagan xato: {e}", exc_info=True)
        return None


def _determine_file_extension(media_type: str, content_type: str, media_url: str) -> str:
    """Mime-type va media_type bo'yicha to'g'ri fayl kengaytmasini topadi"""
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else None

    if ext:
        return ext

    # Standart zaxira kengaytmalar
    TYPE_MAP = {
        "image": ".jpg",
        "video": ".mp4",
        "audio": ".ogg",  # Telegram ovozli xabarlari OGG/Opus formatida keladi
        "sticker": ".png",
        "file": ".bin",
    }
    return TYPE_MAP.get(media_type, ".jpg")


def resolve_telegram_file_url(bot_token: str, file_id: str) -> Optional[str]:
    """
    Telegram getFile API orqali file_id'ni yuklab olinadigan to'liq URL'ga aylantiradi.

    Telegram ovozli xabarlarida (voice) faqat file_id keladi — haqiqiy audio
    ma'lumotini olish uchun avval getFile chaqirib file_path topish, so'ng
    https://api.telegram.org/file/bot<TOKEN>/<file_path> orqali yuklab olish kerak.

    Returns:
        To'liq yuklab olish URL'i yoki None (xato bo'lsa)
    """
    if not bot_token or not file_id:
        return None

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": file_id},
            )

        data = response.json()
        if not data.get("ok"):
            logger.warning(f"[Telegram getFile] xato: {data}")
            return None

        file_path = data.get("result", {}).get("file_path")
        if not file_path:
            logger.warning(f"[Telegram getFile] file_path topilmadi: {data}")
            return None

        return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    except httpx.TimeoutException:
        logger.error("[Telegram getFile] Timeout (15s)")
        return None
    except Exception as e:
        logger.error(f"[Telegram getFile] Kutilmagan xato: {e}", exc_info=True)
        return None
