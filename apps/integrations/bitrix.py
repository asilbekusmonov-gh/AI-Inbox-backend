"""
Bitrix24 CRM integratsiyasi — lidlarni do'kon egasining Bitrix24
akkauntiga (inbound webhook orqali) yuboradi.

Bu — loyihaning "ichki CRM emas" tamoyiliga mos, TASHQI tizimga ko'chirish
vositasi: do'kon egasi allaqachon Bitrix24'dan foydalansa, har bir yangi
lid avtomatik o'sha yerga ham tushadi.

Universal `crm.item.add` metodidan foydalaniladi (entityTypeId=1 — Lead) —
eski `crm.lead.add` o'rniga, Bitrix24'ning joriy hujjatlari yangi
integratsiyalar uchun shu universal metodni tavsiya qiladi.
"""
import hashlib
import logging

import httpx

logger = logging.getLogger("apps.integrations.bitrix")

# Bitrix24 CRM'dagi "Lead" obyektining entityTypeId'si (universal crm.item.* metodlari uchun)
BITRIX_LEAD_ENTITY_TYPE_ID = 1

# ⚠️ Bitrix24'da standart bo'yicha UZS (so'm) valyutasi YO'Q (faqat
# USD/EUR/CNY/BRL/INR) — jonli testda aniqlandi. Narxni shunchaki
# "opportunity" maydoniga yozib yuborsak, u standart valyutada (masalan
# USD) ko'rsatilib, mutlaqo noto'g'ri summa chiqib qolardi (masalan
# "250 000 so'm" o'rniga "$250,000"). Shu sabab har bir DO'KONNING
# Bitrix24 hisobida (webhook manzili bo'yicha, chunki har bir do'kon —
# ALOHIDA Bitrix24 akkaunt) UZS mavjudligini tekshirib, yo'q bo'lsa
# avtomatik qo'shamiz. Natija keshda saqlanadi — har bir lidda qayta-
# qayta so'ramaslik uchun (bitta qo'shimcha Bitrix24 so'rovi = sekinlik).
_UZS_ENSURED_CACHE_TIMEOUT = 60 * 60 * 24 * 30  # 30 kun


def _ensure_uzs_currency(webhook_url: str) -> None:
    from django.core.cache import cache

    cache_key = f"bitrix24_uzs_ensured:{hashlib.sha256(webhook_url.encode()).hexdigest()}"
    if cache.get(cache_key):
        return

    try:
        with httpx.Client(timeout=10.0) as client:
            list_resp = client.get(webhook_url.rstrip("/") + "/crm.currency.list.json")
            currencies = (list_resp.json().get("result") or [])
            if any(c.get("CURRENCY") == "UZS" for c in currencies):
                cache.set(cache_key, True, timeout=_UZS_ENSURED_CACHE_TIMEOUT)
                return

            add_resp = client.post(
                webhook_url.rstrip("/") + "/crm.currency.add.json",
                json={
                    "fields": {
                        "CURRENCY": "UZS",
                        "AMOUNT_CNT": 1,
                        "AMOUNT": 1,
                        "SORT": 500,
                        "LANG": [
                            {
                                "LID": "en",
                                "FULL_NAME": "Uzbekistan Som",
                                "FORMAT_STRING": "# so'm",
                                "DEC_POINT": ".",
                                "THOUSANDS_SEP": " ",
                                "DECIMALS": 0,
                            }
                        ],
                    }
                },
            )
            add_data = add_resp.json()
            if add_data.get("error"):
                logger.warning(f"[Bitrix24] UZS valyuta qo'shilmadi: {add_data}")
            else:
                logger.info("[Bitrix24] UZS valyuta muvaffaqiyatli qo'shildi")
            # Xato bo'lsa ham keshlaymiz — har bir lidda qayta urinib,
            # sekinlashtirmasin; muammo saqlansa xabar loglarda ko'rinadi.
            cache.set(cache_key, True, timeout=_UZS_ENSURED_CACHE_TIMEOUT)
    except Exception as e:
        logger.error(f"[Bitrix24] UZS valyutasini tekshirishda xato: {e}", exc_info=True)

# ⚠️ Bitrix24'da "iliq/sovuq" uchun standart/tayyor maydon YO'Q — buni har
# bir do'kon o'zi (agar xohlasa) custom field sifatida qo'shishi kerak,
# va bu ixtiyoriy, hech kim majburlanmaydi. Shu sabab standart yechim
# sifatida statusni "title"ga belgi qilib qo'shamiz — bu HECH QANDAY
# oldindan sozlashni talab qilmaydi, Bitrix24'ning har qanday ro'yxat
# ko'rinishida (list view) title har doim ko'rinadi.
STATUS_EMOJI = {
    "warm": "🔥",
    "cold": "❄️",
    "unqualified": "❓",
}


def _split_full_name(full_name: str) -> tuple[str, str]:
    """
    "Asilbek Usmonov" → ("Asilbek", "Usmonov"). Bitrix24'da ism va familiya
    ALOHIDA maydonlar ("name"/"lastName") — avval ikkalasi ham bitta "name"
    maydoniga tiqilib ketardi (familiya bo'sh qolardi), bu esa Bitrix24'ning
    standart ro'yxat/kontakt ko'rinishlarida chala/tartibsiz ko'rinishga
    olib kelardi (jonli testda foydalanuvchi buni aniqladi).
    """
    parts = (full_name or "").strip().split(maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return (parts[0] if parts else ""), ""


# Suhbat tarixidan operatorga ko'rsatiladigan har bir xabar shu uzunlikdan
# oshsa qisqartiriladi (Bitrix24 izoh maydonini haddan tashqari uzun
# qilib yubormaslik uchun)
_MAX_SUMMARY_MESSAGE_CHARS = 300
_MAX_SUMMARY_MESSAGES = 12


def _build_conversation_summary(lead) -> str:
    """
    Mijoz bilan AI o'rtasidagi (shaxsiy chatdagi) so'nggi suhbatni o'qishga
    qulay ko'rinishda tuzadi — operator qo'ng'iroq qilganda mijozdan
    HAMMA narsani qaytadan so'ramasligi uchun (foydalanuvchi buni aniq
    ta'kidladi: "operator qaytadan hamma narsani so'ramasligi kerak").
    """
    from apps.chat.models import ChatMessage

    messages = list(
        ChatMessage.objects.filter(
            store=lead.store,
            customer=lead.customer,
            is_group_message=False,
            role__in=[ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT],
        )
        .exclude(content="")
        .order_by("-created_at")[:_MAX_SUMMARY_MESSAGES]
    )
    if not messages:
        return ""
    messages.reverse()

    lines = []
    for m in messages:
        speaker = "Mijoz" if m.role == ChatMessage.Role.USER else "AI"
        text = m.content.strip()
        if len(text) > _MAX_SUMMARY_MESSAGE_CHARS:
            text = text[:_MAX_SUMMARY_MESSAGE_CHARS] + "..."
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def push_lead_to_bitrix24(webhook_url: str, lead) -> bool:
    """
    Bitta lidni Bitrix24'ga Lead (CRM obyekti) sifatida yuboradi.

    Args:
        webhook_url: Do'konning Bitrix24 inbound webhook manzili
                     (masalan: "https://company.bitrix24.com/rest/1/xxxxxxxx/")
        lead: Lead obyekti (apps.orders.models.Lead)

    Returns:
        True — muvaffaqiyatli yuborildi
        False — webhook sozlanmagan, tarmoq xatosi yoki Bitrix xato qaytardi
    """
    if not webhook_url:
        return False

    _ensure_uzs_currency(webhook_url)

    url = webhook_url.rstrip("/") + "/crm.item.add.json"

    status_emoji = STATUS_EMOJI.get(lead.lead_status, "")
    title = f"{status_emoji} {lead.customer_full_name}".strip()
    if lead.interested_course_id:
        title = f"{title} — {lead.interested_course.name}"

    # ⚠️ BUG FIX: mijoz ANIQ nima uchun yozilgani (qaysi kurs/xizmat)
    # avval izohning OXIRIDA (Lid raqami/Holat/Manba'dan KEYIN) turardi —
    # foydalanuvchi buni "eng muhim narsa pastda qolib ketyapti" deb
    # to'g'ri ta'kidladi. Endi eng muhim (qaysi kursga yozilgani) birinchi
    # qatorda, texnik ma'lumotlar (lid raqami, manba) keyin turadi.
    comment_lines = []
    if lead.notes:
        comment_lines.append(f"Nima uchun yozildi: {lead.notes}")
    comment_lines.append(
        f"Lid raqami: {lead.lead_number} | Holat: {lead.get_lead_status_display()} | Manba: LeadNode bot"
    )
    # ⚠️ Operator mijozga qo'ng'iroq qilganda HAMMA narsani qaytadan
    # so'ramasligi uchun — mijoz bilan AI o'rtasidagi so'nggi suhbat
    # to'liq shu yerga qo'shiladi (foydalanuvchi aniq shu muammoni
    # ta'kidladi: "unaqa boladigon bolsa loyihamni educationlarg nima
    # keragi bor" — ya'ni bu loyihaning ASOSIY qiymati, ixtiyoriy qo'shimcha
    # emas).
    conversation_summary = _build_conversation_summary(lead)
    if conversation_summary:
        comment_lines.append("")
        comment_lines.append("--- Suhbat tarixi (operator uchun, qayta so'ramaslik uchun) ---")
        comment_lines.append(conversation_summary)
    comments = "\n".join(comment_lines)

    # ⚠️ BUG FIX: Bitrix24 portali "title"ni avtomatik "Lead #N" bilan
    # almashtirib qo'yishi mumkin (portal sozlamasi, bizning nazoratimizda
    # emas — jonli testda aniqlandi). "name"/"lastName" (Mijoz ismi) esa
    # hech qachon shunday almashtirilmaydi va "Client" blokida DARHOL, hech
    # qanday qo'shimcha sozlamasiz ko'rinadi — shu sabab status belgisi
    # BU YERGA (ismning oldiga) qo'shiladi.
    # ⚠️ BUG FIX 2: bu yerda avval emoji (🔥/❄️) ishlatilgan edi, lekin
    # Bitrix24'ning "name" (ism) maydoni emoji'ni QABUL QILMAY, butunlay
    # BO'SHATIB qo'yishi jonli testda aniqlandi (oddiy matn esa to'g'ri
    # saqlanadi). Shu sabab bu yerda faqat oddiy matnli belgi ishlatiladi.
    # ⚠️ BUG FIX 3: avval ism VA familiya ikkalasi ham birgalikda "name"
    # maydoniga yozilardi ("lastName" bo'sh qolardi) — endi to'g'ri
    # ajratilgan (_split_full_name).
    status_tag = {"warm": "[ILIQ]", "cold": "[SOVUQ]"}.get(lead.lead_status, "")
    first_name, last_name = _split_full_name(lead.customer_full_name)
    name_with_status = f"{status_tag} {first_name}".strip()

    fields = {
        "title": title,
        "name": name_with_status,
        "lastName": last_name,
        "fm": [
            {"typeId": "PHONE", "valueType": "WORK", "value": lead.customer_phone},
        ],
        "comments": comments,
        "sourceDescription": "LeadNode",
    }
    # Qiziqqan kursning narxi bo'lsa — UZS'da ko'rsatamiz (yuqorida
    # _ensure_uzs_currency orqali portalga UZS avvaldan qo'shib qo'yilgan).
    if lead.interested_course_id and lead.interested_course.price:
        fields["opportunity"] = float(lead.interested_course.price)
        fields["currencyId"] = "UZS"

    payload = {
        "entityTypeId": BITRIX_LEAD_ENTITY_TYPE_ID,
        "fields": fields,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
        data = response.json()
    except Exception as e:
        logger.error(f"[Bitrix24] So'rov xatosi: {e} | lid={lead.lead_number}", exc_info=True)
        return False

    if response.status_code != 200 or data.get("error"):
        logger.warning(f"[Bitrix24] Xato javob: {data} | lid={lead.lead_number}")
        return False

    item_id = (data.get("result") or {}).get("item", {}).get("id")
    logger.info(f"[Bitrix24] Lid yuborildi: {lead.lead_number} → item_id={item_id}")
    return True
