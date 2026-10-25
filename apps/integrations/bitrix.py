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


def validate_bitrix24_webhook(webhook_url: str) -> tuple[bool, str]:
    """
    Webhook manzilini SAQLASHDAN OLDIN haqiqatan ishlashini tekshiradi.

    ⚠️ BUG FIX: avval TWA Sozlamalar'da webhook manzili hech qanday
    tekshiruvsiz saqlanardi — "ULANGAN" belgisi shunchaki "biror matn
    kiritilganmi" degan tekshiruv edi, "bu manzil HAQIQATAN Bitrix24'ga
    yoza oladimi" emas. Jonli holatda ikki xil yashirin xato aniqlandi:
    (1) noto'g'ri/eskirgan token (INVALID_CREDENTIALS), (2) webhook
    yaratilganda "CRM" huquqi (scope) belgilanmagan (insufficient_scope)
    — ikkalasida ham "ULANGAN" ko'rinardi, lekin lidlar jimgina hech
    qachon yetib bormasdi. `crm.status.list` — CRM huquqi talab
    qiladigan, lekin hech narsani o'zgartirmaydigan (xavfsiz) so'rov,
    shu sabab ikkala xatoni ham BIR so'rovda aniqlaydi.

    Returns:
        (True, "") — webhook to'g'ri va CRM huquqiga ega
        (False, tushunarli_xabar) — saqlashdan oldin foydalanuvchiga
                                     ko'rsatiladigan aniq sabab
    """
    # ⚠️ SSRF himoyasi: ichki/ommaviy bo'lmagan manzilga umuman so'rov YUBORILMAYDI.
    from apps.core.url_safety import validate_outbound_url

    is_safe, reason = validate_outbound_url(webhook_url)
    if not is_safe:
        return False, reason

    url = webhook_url.rstrip("/") + "/crm.status.list.json"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
        data = response.json()
    except Exception as e:
        # ⚠️ Xato matni ({e}) foydalanuvchiga QAYTARILMAYDI — u manzil ortidagi xizmat haqida
        # tafsilot (masalan "Server disconnected", "Expecting value") ochib berardi.
        logger.warning(f"[Bitrix24] Webhook tekshiruvida tarmoq xatosi: {e}")
        return False, "Bitrix24'ga ulanib bo'lmadi — manzilni tekshiring."

    error = data.get("error")
    if not error:
        return True, ""

    if error in ("INVALID_CREDENTIALS", "invalid_token", "NO_AUTH_FOUND"):
        return False, (
            "Bitrix24 bu webhook manzilini tanimadi (noto'g'ri yoki eskirgan). "
            "Bitrix24'da webhook manzilini qayta tekshiring yoki yangisini yarating."
        )
    if error == "insufficient_scope":
        return False, (
            "Bu webhookda CRM huquqi yo'q. Bitrix24'da: Ilovalar → Ishlab chiquvchi "
            "resurslari → Boshqa → shu webhookni tahrirlab, \"CRM\" huquqini yoqing."
        )
    return False, f"Bitrix24 xato qaytardi: {data.get('error_description', error)}"


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
    "warm": "🟡",
    "hot": "🔥",
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

    # ⚠️ SSRF himoyasi: manzil saqlanganidan keyin DNS o'zgargan yoki eski (tekshiruvsiz)
    # yozuv bo'lishi mumkin — har yuborishdan oldin QAYTA tekshiriladi.
    from apps.core.url_safety import is_safe_outbound_url

    if not is_safe_outbound_url(webhook_url):
        logger.error(f"[Bitrix24] Xavfsiz bo'lmagan webhook manzili — yuborilmadi | lid={lead.lead_number}")
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
    #
    # ⚠️ BUG FIX 2: avval bu yerga qo'shimcha ravishda xom "Mijoz: .../
    # AI: ..." suhbat tarixi ham to'liq qo'shilardi — foydalanuvchi buni
    # keraksiz deb, o'rniga `lead.notes`ning o'zi (endi 2-4 gapli, batafsil
    # yozilgan — apps/chat/ai_service.py, _LEAD_QUALIFICATION_RULE'ga
    # qarang) operator uchun yetarli ekanini ta'kidladi. Xom tarixni
    # qayta o'qishga operator vaqti yo'q, tayyor xulosa kerak.
    comment_lines = []
    if lead.notes:
        comment_lines.append(f"Nima uchun yozildi: {lead.notes}")
    comment_lines.append(
        f"Lid raqami: {lead.lead_number} | Holat: {lead.get_lead_status_display()} | Manba: LeadNode bot"
    )
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
    status_tag = {"warm": "[ILIQ]", "hot": "[ISSIQ]"}.get(lead.lead_status, "")
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
