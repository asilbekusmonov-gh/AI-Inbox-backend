"""
Audit yozib borish uchun yordamchi funksiya.

Audit yozuvi doim BEST-EFFORT — agar log yozishda xatolik bo'lsa, bu
haqiqiy admin amalini (masalan, biznesni o'chirish) bloklamasligi kerak.
"""
import logging

from apps.audit.models import AuditLog, PlatformError

logger = logging.getLogger(__name__)


def log_action(
    *, actor, action: str, store=None, metadata: dict | None = None,
    actor_display: str | None = None,
) -> None:
    """
    `actor_display` — admin User bo'lmagan amallar uchun (masalan Telegram'da
    admin havolasini bosgan odam: `actor=None, actor_display="Telegram #123"`).
    """
    try:
        actor_display = (
            actor_display
            or getattr(actor, "first_name", "")
            or getattr(actor, "username", "")
            or "noma'lum"
        )
        AuditLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            actor_display=actor_display,
            action=action,
            target_store=store,
            target_store_name=getattr(store, "name", ""),
            metadata=metadata or {},
        )
    except Exception:
        logger.warning("[Audit] Audit yozuvini saqlab bo'lmadi: action=%s store=%s", action, store, exc_info=True)


def log_platform_error(*, source: str, message: str, store=None, metadata: dict | None = None) -> None:
    """Texnik xatoni `PlatformError`ga yozadi — best-effort, hech qachon chaqiruvchini to'xtatmaydi."""
    try:
        PlatformError.objects.create(
            source=source,
            message=message[:4000],
            store=store,
            store_name=getattr(store, "name", ""),
            metadata=metadata or {},
        )
    except Exception:
        logger.warning("[Audit] PlatformError yozuvini saqlab bo'lmadi: source=%s", source, exc_info=True)
