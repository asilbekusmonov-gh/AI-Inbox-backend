"""
Store Celery Tasks — Instagram Token Yangilash.

Har kunda bir marta ishlab tugashiga 15 kun qolgan
Instagram tokenlarni avtomatik yangilaydi.

Celery Beat settings.py'da sozlangan:
  CELERY_BEAT_SCHEDULE["refresh-expiring-instagram-tokens"]
"""
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger("apps.stores")


@shared_task(
    name="apps.stores.tasks.refresh_expiring_instagram_tokens",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    ignore_result=False,
)
def refresh_expiring_instagram_tokens(self):
    """
    Tugashiga 15 kun qolgan Instagram tokenlarni avtomatik yangilaydi.

    Ishlash oqimi:
    1. DB'dan tugashiga 15 kun qolgan aktiv do'konlarni topadi
    2. Har biri uchun refresh_token_for_store() chaqiradi
    3. Natijalarni log'ga yozadi

    Bu task Celery Beat orqali har kunda bir marta ishga tushadi.
    settings.py'da CELERY_BEAT_SCHEDULE'ga qo'shish kerak.
    """
    from apps.stores.models import Store
    from apps.stores.services import refresh_token_for_store

    now = timezone.now()
    threshold = now + timedelta(days=15)

    # Tugashiga 15 kun qolgan tokenli aktiv do'konlar
    stores_to_refresh = Store.objects.filter(
        is_active=True,
        is_deleted=False,
        ig_access_token__isnull=False,
        ig_token_expires_at__isnull=False,
        ig_token_expires_at__lte=threshold,
    ).exclude(ig_access_token="")

    total = stores_to_refresh.count()

    if total == 0:
        logger.info("[Token Refresh Task] Yangilash kerak bo'lgan token topilmadi.")
        return {"refreshed": 0, "failed": 0}

    logger.info(
        f"[Token Refresh Task] {total} ta do'konning tokeni "
        f"yangilanishi kerak."
    )

    refreshed = 0
    failed = 0

    for store in stores_to_refresh:
        try:
            success = refresh_token_for_store(store)
            if success:
                refreshed += 1
                logger.info(
                    f"[Token Refresh Task] ✓ {store.name} | "
                    f"Yangi muddati: {store.ig_token_expires_at.date()}"
                )
            else:
                failed += 1
                logger.warning(
                    f"[Token Refresh Task] ✗ {store.name} — "
                    f"yangilashda xato (servis logi'ni tekshiring)"
                )
        except Exception as e:
            failed += 1
            logger.error(
                f"[Token Refresh Task] Kutilmagan xato: "
                f"store={store.name} | {e}",
                exc_info=True,
            )

    logger.info(
        f"[Token Refresh Task] Yakunlandi: "
        f"✓ {refreshed} yangilandi | ✗ {failed} xato"
    )

    return {"refreshed": refreshed, "failed": failed, "total": total}
