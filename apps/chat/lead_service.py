"""
Lid Yaratuvchisi — AI javobidan Lead yaratadi.

AI suhbatdan ism, telefon va (ixtiyoriy) qiziqqan kurs/xizmat nomini
aniqlagach, bu modul Lead yozuvini yaratadi va egasiga xabar beradi.

Iliq/issiq baholash (lead_status) AI'ning system prompt darajasida
qilinadi (apps/chat/ai_service.py, CATEGORY_PROMPTS) — bu yerda faqat
`lead_data` ichidan tayyor "lead_status" (warm/hot) o'qib olinadi, aks
holda yoki qiymat noto'g'ri bo'lsa "unqualified" (aniqlanmagan) qilib
qo'yiladi.
"""
import logging
import re
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger("apps.chat")

# ⚠️ BUG FIX: AI bitta suhbat davomida lid JSON blokini ketma-ket bir
# necha xabarda qaytarib yuborishi mumkin (masalan mijoz ketma-ket ikkita
# qisqa xabar yozsa, AI ikkalasida ham "ro'yxatdan o'tkazaman" deb hisoblab,
# lid blokini takrorlashi mumkin) — bu avval HAR SAFAR yangi Lead yaratardi,
# jonli holatda bitta mijoz uchun bir daqiqa ichida ikkita bir xil "YANGI
# LID!" xabarnomasi kelib, do'kon egasini chalg'itgan va ikki marta
# qo'ng'iroq qilish xavfini tug'dirgan edi. Shu sabab shu mijoz uchun
# so'nggi bir necha daqiqa ichida allaqachon lid yaratilgan bo'lsa, qayta
# yaratilmaydi.
_DUPLICATE_LEAD_WINDOW_MINUTES = 10


def _find_interested_course(store, name: str):
    """
    Mijoz qiziqqan kurs/mahsulot/xizmatni nomi bo'yicha katalogdan topadi.

    Bu — ixtiyoriy teglash: topilmasa ham lid baribir yaratiladi, faqat
    `interested_course` bo'sh qoladi. Avval ANIQ (katta-kichik harfga
    sezgir bo'lmagan) mos kelishni qidiramiz; topilmasa, qisman mos
    keluvchilar orasidan ENG QISQA nomlisi tanlanadi (so'ralgan nomga eng
    yaqin, kamroq qo'shimcha so'z qo'shilgan variant) — bir nomi
    ikkinchisining ichida bo'lgan holatlar uchun (masalan "Ingliz tili" va
    "Ingliz tili Intensiv").
    """
    if not name:
        return None

    from apps.products.models import Product

    exact = Product.objects.filter(
        store=store, is_deleted=False, is_active=True, name__iexact=name
    ).first()
    if exact:
        return exact

    candidates = list(Product.objects.filter(
        store=store, is_deleted=False, is_active=True, name__icontains=name
    ))
    if not candidates:
        return None
    candidates.sort(key=lambda p: len(p.name))
    return candidates[0]


def _clean_and_check_phone(raw_phone: str) -> tuple[str, bool]:
    """
    Telefon raqamini tozalaydi va shubhali (harf aralashgan, juda qisqa/
    uzun) qiymatlarni aniqlaydi. AI ba'zan raqamga harf qo'shib qo'yishi
    yoki noto'g'ri formatda yozishi mumkin — bunday holatlarni jimgina
    o'tkazib yubormasdan, keyinroq do'kon egasi tekshirishi uchun
    belgilaymiz.

    Returns:
        (tozalangan_raqam, shubhalimi)
    """
    has_letters = bool(re.search(r"[a-zA-Zа-яА-ЯЎўҚқҲҳ]", raw_phone))
    plus_prefix = "+" if raw_phone.strip().startswith("+") else ""
    digits_only = re.sub(r"\D", "", raw_phone)
    cleaned = f"{plus_prefix}{digits_only}" if digits_only else raw_phone.strip()
    is_suspicious = has_letters or len(digits_only) < 9 or len(digits_only) > 15
    return cleaned, is_suspicious


def create_lead_from_ai_data(
    store,
    customer,
    lead_data: dict,
    platform: str,
    source: str = "private_chat",
    source_message=None,
) -> Optional[object]:
    """
    AI'dan kelgan lid ma'lumotlaridan Lead yaratadi.

    `lead_data` turli toifadan kelishi mumkin bo'lgan kalitlarni qabul
    qiladi (hozircha AI extraction formati o'zgarmagan, shu sababli eski
    kalit nomlari bilan ham ishlaydi):
      - {"full_name", "phone", "course_name"/"service_name", ...}
      - Ixtiyoriy: "lead_status" ("warm"/"hot") — kelmasa "unqualified"

    Args:
        store: Store obyekti
        customer: Customer obyekti
        lead_data: AI'dan olingan dict
        platform: "telegram" | "instagram"
        source: "private_chat" | "group" | "ad"
        source_message: Bu lidni yaratgan ChatMessage (ixtiyoriy)

    Returns:
        Lead — muvaffaqiyatli yaratildi
        None — xato yuz berdi (majburiy maydon yo'q) YOKI shu mijoz uchun
               so'nggi bir necha daqiqa ichida allaqachon lid yaratilgan
               (takroriy AI chiqishi — pastga qarang), shuning uchun
               chaqiruvchi (webhooks/tasks.py) qayta egaga xabar/CRM
               eksportini yubormaydi.
    """
    from apps.orders.models import Lead

    try:
        full_name = str(lead_data.get("full_name", "")).strip()
        phone = str(lead_data.get("phone", "")).strip()
        notes = str(lead_data.get("notes", "")).strip()

        if not full_name:
            logger.warning("Lid yaratish: full_name bo'sh!")
            return None
        if not phone:
            logger.warning("Lid yaratish: phone bo'sh!")
            return None

        phone, phone_suspicious = _clean_and_check_phone(phone)
        if phone_suspicious:
            notes = (notes + " | " if notes else "") + f"⚠️ Telefon raqami shubhali ko'rinadi, tekshiring: {phone}"

        # Qiziqqan kurs/mahsulot/xizmat nomi — toifaga qarab turli kalitdan kelishi mumkin
        interest_name = (
            str(lead_data.get("course_name", "")).strip()
            or str(lead_data.get("service_name", "")).strip()
            or str(lead_data.get("product_name", "")).strip()
        )
        interested_course = _find_interested_course(store, interest_name) if interest_name else None

        preferred_time = str(lead_data.get("preferred_time", "")).strip()
        booking_time = str(lead_data.get("booking_time", "")).strip()
        specialist = str(lead_data.get("specialist", "")).strip()
        if preferred_time:
            notes = (notes + " | " if notes else "") + f"Sinov darsi vaqti: {preferred_time}"
        if booking_time:
            notes = (notes + " | " if notes else "") + f"Band qilingan vaqt: {booking_time}"
        if specialist:
            notes = (notes + " | " if notes else "") + f"Mutaxassis: {specialist}"

        lead_status = str(lead_data.get("lead_status", "")).strip().lower()
        if lead_status == "cold":
            # ⚠️ BUG FIX: avval bu yerda "hot" darajasi "olib tashlangan"
            # deb pastga (warm) tushirilardi — foydalanuvchi buni TESKARI
            # o'zgartirdi: endi "cold" (sovuq) darajasi kerak emas (har
            # qanday Lead — ism/telefon qoldirgan real qiziqish, "sovuq"
            # emas), "hot" (issiq) esa haqiqiy, YUQORI daraja sifatida
            # QAYTARILDI. AI eski yo'riqnoma ta'siri/inertsiya bilan hali
            # ham "cold" qaytarib yuborishi mumkin — bunday holatda ENG
            # YAQIN, endi mavjud bo'lgan bazaviy darajaga (warm) tushiriladi.
            lead_status = Lead.LeadStatus.WARM
        elif lead_status not in (Lead.LeadStatus.WARM, Lead.LeadStatus.HOT):
            lead_status = Lead.LeadStatus.UNQUALIFIED

        recent_duplicate = Lead.objects.filter(
            store=store, customer=customer, is_deleted=False,
            created_at__gte=timezone.now() - timedelta(minutes=_DUPLICATE_LEAD_WINDOW_MINUTES),
        ).order_by("-created_at").first()
        if recent_duplicate:
            logger.info(
                f"Lid yaratish o'tkazib yuborildi (takroriy, {_DUPLICATE_LEAD_WINDOW_MINUTES} daqiqa "
                f"ichida allaqachon bor) — mavjud lid: {recent_duplicate.lead_number} | "
                f"do'kon={store.name} | mijoz={full_name}"
            )
            return None

        lead = Lead.objects.create(
            store=store,
            customer=customer,
            platform=platform,
            source=source,
            customer_full_name=full_name,
            customer_phone=phone,
            interested_course=interested_course,
            lead_status=lead_status,
            notes=notes,
            source_message=source_message,
        )

        # ── Mijoz ma'lumotlarini yangilash ─────────────────────────
        # Agar birinchi marta ism/raqam olingan bo'lsa — Customer'ga ham yozamiz
        update_fields = []
        if not customer.full_name and full_name:
            customer.full_name = full_name
            update_fields.append("full_name")
        if not customer.phone_number and phone:
            customer.phone_number = phone
            update_fields.append("phone_number")
        if update_fields:
            update_fields.append("updated_at")
            customer.save(update_fields=update_fields)

        # Lid sonini yangilash
        from django.db.models import F
        from apps.customers.models import Customer as CustomerModel
        CustomerModel.objects.filter(id=customer.id).update(
            total_leads=F('total_leads') + 1
        )

        logger.info(
            f"Yangi lid yaratildi: {lead.lead_number} | "
            f"do'kon={store.name} | mijoz={full_name}"
        )

        return lead

    except Exception as e:
        logger.error(
            f"Lid yaratishda xato: {e} | store={store.name}",
            exc_info=True,
        )
        return None


def notify_store_owner(store, lead) -> bool:
    """
    Do'kon egasiga yangi lid haqida Telegram xabari yuboradi.

    Returns:
        True — xabar yuborildi
        False — yuborilmadi (token yo'q yoki xato)
    """
    from apps.chat.senders import send_telegram_lead_notification
    from django.utils import timezone

    try:
        if not store.tg_bot_token:
            logger.warning(
                f"Egaga xabarnoma: {store.name} do'konida tg_bot_token yo'q!"
            )
            return False

        if not store.tg_owner_chat_id:
            logger.warning(
                f"Egaga xabarnoma: {store.name} do'konida tg_owner_chat_id yo'q!"
            )
            return False

        success = send_telegram_lead_notification(
            bot_token=store.tg_bot_token,
            owner_chat_id=store.tg_owner_chat_id,
            lead=lead,
        )

        if success:
            from apps.orders.models import Lead
            Lead.objects.filter(id=lead.id).update(
                owner_notified=True,
                owner_notified_at=timezone.now(),
            )
            logger.info(
                f"Egaga xabarnoma yuborildi: {lead.lead_number} → "
                f"{store.tg_owner_chat_id}"
            )
        else:
            logger.warning(
                f"Egaga xabarnoma yuborilmadi: {lead.lead_number}"
            )

        return success

    except Exception as e:
        logger.error(
            f"Egaga xabarnoma yuborishda xato: {e}",
            exc_info=True,
        )
        return False


def sync_lead_to_bitrix24(store, lead) -> bool:
    """
    Do'konda Bitrix24 webhook ulangan bo'lsa, yangi lidni avtomatik
    o'sha yerga ham yuboradi (real vaqtda, lid yaratilishi bilan).

    Returns:
        True — muvaffaqiyatli yuborildi
        False — webhook sozlanmagan yoki yuborishda xato
    """
    from django.utils import timezone
    from apps.integrations.bitrix import push_lead_to_bitrix24

    if not store.bitrix24_webhook_url:
        return False

    try:
        success = push_lead_to_bitrix24(webhook_url=store.bitrix24_webhook_url, lead=lead)

        if success:
            from apps.orders.models import Lead
            # ⚠️ `exported_to`/`exported_at` — faqat ko'rsatish uchun
            # (oxirgi eksport qaysi kanal ekanini bildiradi). Retry
            # vazifasi esa `bitrix24_synced_at`ga qaraydi — bu Excel
            # eksportidan MUSTAQIL, shuning uchun avval Excel'ga
            # yuklab olingan lid ham endi to'g'ri "sinxronlangan" deb
            # belgilanadi.
            Lead.objects.filter(id=lead.id).update(
                exported_to=Lead.ExportStatus.BITRIX24,
                exported_at=timezone.now(),
                bitrix24_synced_at=timezone.now(),
            )
            logger.info(f"Bitrix24'ga yuborildi: {lead.lead_number}")
        else:
            logger.warning(f"Bitrix24'ga yuborilmadi: {lead.lead_number}")

        return success

    except Exception as e:
        logger.error(
            f"Bitrix24'ga yuborishda xato: {e}",
            exc_info=True,
        )
        return False


def sync_lead_to_google_sheets(store, lead) -> bool:
    """
    Do'konda Google Sheets webhook ulangan bo'lsa, yangi lidni avtomatik
    o'sha yerga ham yuboradi (real vaqtda, lid yaratilishi bilan).

    Bitrix24'dan mustaqil ishlaydi — bitta do'kon ikkalasini ham
    (yoki faqat bittasini) yoqib qo'yishi mumkin.

    Returns:
        True — muvaffaqiyatli yuborildi
        False — webhook sozlanmagan yoki yuborishda xato
    """
    from django.utils import timezone
    from apps.integrations.google_sheets import push_lead_to_google_sheets

    if not store.google_sheets_webhook_url:
        return False

    try:
        success = push_lead_to_google_sheets(webhook_url=store.google_sheets_webhook_url, lead=lead)

        if success:
            from apps.orders.models import Lead
            Lead.objects.filter(id=lead.id).update(
                google_sheets_synced_at=timezone.now(),
            )
            logger.info(f"Google Sheets'ga yuborildi: {lead.lead_number}")
        else:
            logger.warning(f"Google Sheets'ga yuborilmadi: {lead.lead_number}")

        return success

    except Exception as e:
        logger.error(
            f"Google Sheets'ga yuborishda xato: {e}",
            exc_info=True,
        )
        return False
