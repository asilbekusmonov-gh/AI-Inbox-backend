"""
Google Sheets integratsiyasi — lidlarni do'kon egasining o'z Google
Sheets jadvaliga (Apps Script Web App orqali) yuboradi.

⚠️ Google Sheets API'ning rasmiy OAuth oqimi (Google Cloud loyihasi,
consent screen, har bir do'kon uchun tokenlarni saqlash/yangilash) bu
loyiha uchun ortiqcha murakkab va ko'p hollarda Google tomonidan
tasdiqlanishni talab qiladi — kichik SMB mijozlari (til markazlari,
salonlar) uchun amaliy emas. Buning o'rniga Bitrix24 bilan BIR XIL,
ancha sodda yondashuv qo'llanildi: do'kon egasi o'z Google Sheets
jadvalida bitta kichik Apps Script joylashtirib, uni "Web App" sifatida
deploy qiladi va olingan URL'ni Sozlamalar bo'limiga qo'yadi — bizning
tomonimizda hech qanday Google API kaliti yoki OAuth kerak emas,
shunchaki oddiy HTTP POST (xuddi Bitrix24 webhook'i kabi).

Do'kon egasi uchun Apps Script namunasi (Google Sheets > Kengaytmalar >
Apps Script > shu kodni joylashtirish > Joylashtirish > Yangi joylashtirish
> Veb-ilova > Kim sifatida ishga tushirilsin: Men > Kimga ruxsat: Hamma >
Joylashtirish > URL'ni nusxalab Sozlamalarga qo'yish):

    function doPost(e) {
      var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
      var data = JSON.parse(e.postData.contents);
      sheet.appendRow([
        data.created_at || new Date(),
        data.lead_number || '',
        data.full_name || '',
        data.phone || '',
        data.interested_in || '',
        data.status || '',
        data.notes || '',
        data.conversation_summary || ''
      ]);
      return ContentService.createTextOutput(JSON.stringify({ok: true}))
        .setMimeType(ContentService.MimeType.JSON);
    }
"""
import logging

import httpx

logger = logging.getLogger("apps.integrations.google_sheets")

def push_lead_to_google_sheets(webhook_url: str, lead) -> bool:
    """
    Bitta lidni do'kon egasining Google Sheets Apps Script Web App'iga
    (yangi qator sifatida) yuboradi.

    Args:
        webhook_url: Do'konning Apps Script Web App manzili
                     (masalan: "https://script.google.com/macros/s/xxxxx/exec")
        lead: Lead obyekti (apps.orders.models.Lead)

    Returns:
        True — muvaffaqiyatli yuborildi
        False — webhook sozlanmagan, tarmoq xatosi yoki skript xato qaytardi
    """
    if not webhook_url:
        return False

    status_label = {"warm": "Iliq", "cold": "Sovuq"}.get(lead.lead_status, "Aniqlanmagan")
    interested_in = lead.interested_course.name if lead.interested_course_id else ""

    payload = {
        "lead_number": lead.lead_number,
        "full_name": lead.customer_full_name,
        "phone": lead.customer_phone,
        "interested_in": interested_in,
        "status": status_label,
        # ⚠️ Avval bu yerda alohida "conversation_summary" (xom "Mijoz:
        # .../AI: ..." suhbat tarixi) ham yuborilardi — foydalanuvchi
        # buni keraksiz deb, "notes"ning o'zi (endi 2-4 gapli, batafsil —
        # apps/chat/ai_service.py, _LEAD_QUALIFICATION_RULE'ga qarang)
        # operator uchun yetarli ekanini ta'kidladi.
        "notes": lead.notes or "",
        "source": "LeadNode",
        "created_at": lead.created_at.strftime("%Y-%m-%d %H:%M"),
    }

    try:
        # ⚠️ Google Apps Script Web App'lari ko'pincha yakuniy javobdan
        # oldin 302 redirect (script.googleusercontent.com'ga) qaytaradi —
        # `follow_redirects=True` bo'lmasa, bu holat xato deb hisoblanib
        # qolardi (httpx standart bo'yicha redirect'ga ergashmaydi).
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.post(webhook_url, json=payload)
    except Exception as e:
        logger.error(f"[GoogleSheets] So'rov xatosi: {e} | lid={lead.lead_number}", exc_info=True)
        return False

    if response.status_code != 200:
        logger.warning(f"[GoogleSheets] Xato javob: {response.status_code} | lid={lead.lead_number}")
        return False

    try:
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            logger.warning(f"[GoogleSheets] Skript xato qaytardi: {data} | lid={lead.lead_number}")
            return False
    except ValueError:
        # Apps Script ba'zan oddiy matn qaytarishi mumkin — 200 status
        # bo'lsa yetarli, JSON bo'lmasligi o'zi xato emas.
        pass

    logger.info(f"[GoogleSheets] Lid yuborildi: {lead.lead_number}")
    return True
