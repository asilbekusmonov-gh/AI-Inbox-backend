"""
Orders Celery Tasks — Bitrix24'ga eksport qilinmagan lidlarni qayta urinish.

⚠️ Muammo: lid aniqlangan zahoti Bitrix24'ga sinxron yuborilishga urinadi
(apps/webhooks/tasks.py), lekin o'sha payt Bitrix24 vaqtincha ishlamasa
yoki tarmoq xatosi bo'lsa — lid O'ZIMIZNING bazamizda xavfsiz saqlanib
qoladi (hech qachon yo'qolmaydi), lekin Bitrix24'ga HECH QACHON qayta
yuborilmasdi — buni faqat egasi TWA'da qo'lda payqab, qo'lda qayta
yuborishi kerak edi. Bu task shu bo'shliqni to'ldiradi: muntazam
(Celery Beat orqali) eksport qilinmagan lidlarni topib, qayta yuborishga
urinadi.

Celery Beat settings.py'da sozlangan:
  CELERY_BEAT_SCHEDULE["retry-failed-bitrix-exports"]
"""
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger("apps.orders")


@shared_task(
    name="apps.orders.tasks.retry_failed_bitrix_exports",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    ignore_result=False,
)
def retry_failed_bitrix_exports(self):
    """
    Bitrix24 ulangan, lekin hali eksport qilinmagan lidlarni topib,
    qayta yuborishga urinadi.

    ⚠️ Faqat so'nggi 7 kun ichidagi lidlar tekshiriladi — juda eski
    (masalan oylar oldingi) muvaffaqiyatsiz urinishlarni abadiy qayta
    urinaverish ma'nosiz, ehtimol Bitrix24 sozlamasi o'sha vaqtda
    noto'g'ri bo'lgan yoki lid endi dolzarb emas.

    ⚠️ BUG FIX: avval bu yerda `exported_to=NONE` bo'yicha filtrlanardi —
    ya'ni agar ega Bitrix24 ulashdan OLDIN "Excel'ni chatga yuborish"
    tugmasini bir marta bossa (bu BARCHA lidlarni `exported_to="excel"`
    deb belgilaydi), o'sha lidlar bu yerda "allaqachon eksport qilingan"
    deb hisoblanib, Bitrix24 keyinroq ulansa ham HECH QACHON avtomatik
    yuborilmasdi (jonli holatda aniqlandi). Endi Excel holatidan mustaqil
    `bitrix24_synced_at` maydoniga qaraladi.
    """
    from apps.orders.models import Lead
    from apps.chat.lead_service import sync_lead_to_bitrix24

    cutoff = timezone.now() - timedelta(days=7)

    pending_leads = Lead.objects.filter(
        bitrix24_synced_at__isnull=True,
        is_deleted=False,
        created_at__gte=cutoff,
        store__bitrix24_webhook_url__isnull=False,
        store__is_active=True,
        store__is_deleted=False,
    ).exclude(store__bitrix24_webhook_url="").select_related("store")

    total = pending_leads.count()
    if total == 0:
        logger.info("[Bitrix Retry Task] Qayta yuborish kerak bo'lgan lid topilmadi.")
        return {"retried": 0, "succeeded": 0, "failed": 0}

    logger.info(f"[Bitrix Retry Task] {total} ta eksport qilinmagan lid topildi — qayta urinilmoqda.")

    succeeded = 0
    failed = 0

    for lead in pending_leads:
        try:
            if sync_lead_to_bitrix24(store=lead.store, lead=lead):
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error(
                f"[Bitrix Retry Task] Kutilmagan xato: lead={lead.lead_number} | {e}",
                exc_info=True,
            )

    logger.info(
        f"[Bitrix Retry Task] Yakunlandi: ✓ {succeeded} yuborildi | ✗ {failed} hali muvaffaqiyatsiz"
    )
    return {"retried": total, "succeeded": succeeded, "failed": failed}


@shared_task(
    name="apps.orders.tasks.retry_failed_google_sheets_exports",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    ignore_result=False,
)
def retry_failed_google_sheets_exports(self):
    """
    Google Sheets ulangan, lekin hali yuborilmagan lidlarni topib, qayta
    yuborishga urinadi — yuqoridagi `retry_failed_bitrix_exports` bilan
    bir xil mantiq, faqat `google_sheets_synced_at` maydoniga qarab
    (bu Bitrix24'ning `exported_to`sidan MUSTAQIL, chunki bitta lid
    ikkalasiga ham yuborilishi mumkin).
    """
    from apps.orders.models import Lead
    from apps.chat.lead_service import sync_lead_to_google_sheets

    cutoff = timezone.now() - timedelta(days=7)

    pending_leads = Lead.objects.filter(
        google_sheets_synced_at__isnull=True,
        is_deleted=False,
        created_at__gte=cutoff,
        store__google_sheets_webhook_url__isnull=False,
        store__is_active=True,
        store__is_deleted=False,
    ).exclude(store__google_sheets_webhook_url="").select_related("store")

    total = pending_leads.count()
    if total == 0:
        logger.info("[GoogleSheets Retry Task] Qayta yuborish kerak bo'lgan lid topilmadi.")
        return {"retried": 0, "succeeded": 0, "failed": 0}

    logger.info(f"[GoogleSheets Retry Task] {total} ta eksport qilinmagan lid topildi — qayta urinilmoqda.")

    succeeded = 0
    failed = 0

    for lead in pending_leads:
        try:
            if sync_lead_to_google_sheets(store=lead.store, lead=lead):
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error(
                f"[GoogleSheets Retry Task] Kutilmagan xato: lead={lead.lead_number} | {e}",
                exc_info=True,
            )

    logger.info(
        f"[GoogleSheets Retry Task] Yakunlandi: ✓ {succeeded} yuborildi | ✗ {failed} hali muvaffaqiyatsiz"
    )
    return {"retried": total, "succeeded": succeeded, "failed": failed}
