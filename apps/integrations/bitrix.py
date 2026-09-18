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
import logging

import httpx

logger = logging.getLogger("apps.integrations.bitrix")

# Bitrix24 CRM'dagi "Lead" obyektining entityTypeId'si (universal crm.item.* metodlari uchun)
BITRIX_LEAD_ENTITY_TYPE_ID = 1

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

    url = webhook_url.rstrip("/") + "/crm.item.add.json"

    status_emoji = STATUS_EMOJI.get(lead.lead_status, "")
    title = f"{status_emoji} {lead.customer_full_name}".strip()
    if lead.interested_course_id:
        title = f"{title} — {lead.interested_course.name}"

    comments = f"Lid raqami: {lead.lead_number} | Holat: {lead.get_lead_status_display()} | Manba: LeadNode bot"
    if lead.notes:
        comments += f"\nIzoh: {lead.notes}"

    payload = {
        "entityTypeId": BITRIX_LEAD_ENTITY_TYPE_ID,
        "fields": {
            "title": title,
            "name": lead.customer_full_name,
            "fm": [
                {"typeId": "PHONE", "valueType": "WORK", "value": lead.customer_phone},
            ],
            "comments": comments,
            "sourceDescription": "LeadNode",
        },
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
