"""
Product AI Service — Mahsulot/kurs/xizmat tavsifini AI orqali yozib berish.

Do'kon egasi TWA'da "Yangi mahsulot" formasini to'ldirganda, tavsif
maydonini qo'lda yozish o'rniga, forma ustidagi maydonlar (nomi,
kategoriya, narxi) asosida Gemini orqali qisqa, sotuvga yo'naltirilgan
tavsif generatsiya qilinadi.
"""
import json
import logging
import re

import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger("apps.products")

CATEGORY_LABELS = {
    "education": "kurs",
    "services": "xizmat",
}

# Har bir toifa uchun ruxsat etilgan metadata kalitlari — bu ro'yxat
# apps/stores/serializers.py'dagi Education/Services Metadata
# serializerlaridagi maydonlar bilan AYNAN mos kelishi kerak,
# aks holda AI to'plagan qoralama keyinroq (owner saqlaganda) o'sha
# serializerlarda validatsiyadan o'tolmay qoladi.
CATEGORY_METADATA_HINTS = {
    "education": '"metadata": {"duration_months": 3, "lessons_per_week": 3, "lesson_duration_minutes": 90, "format": "offline (FAQAT shu uchtadan biri: \\"online\\", \\"offline\\", \\"hybrid\\" — ikkalasi ham bo‘lsa \\"hybrid\\" yoz)", "teacher_name": "...", "trial_lesson_days": ["Dushanba", "Chorshanba"]}',
    "services": '"metadata": {"duration_minutes": 60, "specialists": ["Dilnoza"], "available_hours": ["10:00-18:00"], "location": "..."}',
}


def generate_product_description(
    name: str,
    category_type: str,
    category: str = "",
    price=None,
    stock=None,
) -> str:
    """
    Berilgan mahsulot/kurs/xizmat ma'lumotlari asosida AI orqali
    qisqa (1-2 gap) tavsif matni generatsiya qiladi.

    Raises:
        ValueError: Gemini bo'sh javob qaytarsa
        Exception: API xatosi (chaqiruvchi ushlab, foydalanuvchiga
                   moslashtirilgan xato xabarini ko'rsatishi kerak)
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY sozlanmagan!")
    genai.configure(api_key=api_key)
    # ⚠️ "gemini-2.5-flash" VA "gemini-2.0-flash" ikkalasi ham bu loyihaning
    # Gemini API kaliti uchun o'chirilgan ("no longer available" xatosi).
    # "gemini-3.6-flash" jonli tekshirilib, ishlashi tasdiqlangan — xuddi
    # shu model apps/chat/ai_service.py'da ham fallback sifatida ishlatiladi.
    model = genai.GenerativeModel("gemini-3.6-flash")

    label = CATEGORY_LABELS.get(category_type, "mahsulot")
    details = [f"Nomi: {name}"]
    if category:
        details.append(f"Kategoriya: {category}")
    if price:
        details.append(f"Narxi: {price} so'm")
    if stock:
        details.append(f"Miqdori/bo'sh o'rinlar: {stock}")

    prompt = (
        f"Sen {label} tavsifi yozuvchi yordamchisan. Quyidagi ma'lumotlar "
        f"asosida, AI sotuv boti mijozlarga ko'rsatadigan QISQA "
        f"(bitta yoki ikkita gap, 40 so'zdan oshmasin), ishonarli va "
        f"sotuvga undovchi tavsif yoz. Faqat tavsif matnining o'zini "
        f"qaytar — kirish so'zlari, tirnoq belgilari, izohlar kerak emas.\n\n"
        + "\n".join(details)
        + "\n\nTavsif:"
    )

    # ⚠️ BUG FIX: timeout berilmagan bo'lsa, bu so'rov tarmoq/API muammosi
    # bo'lganda cheksiz osilib qolishi mumkin edi — TWA'da "Yozilmoqda..."
    # tugmasi abadiy aylanib qolgan holat jonli aniqlandi (backend loglarida
    # Gunicorn worker 120+ soniyadan keyin majburan o'ldirilgani ko'rindi).
    # Endi 25 soniyadan keyin aniq xato ko'tariladi — view.py buni ushlab,
    # foydalanuvchiga tushunarli xabar bilan qaytaradi.
    response = model.generate_content(prompt, request_options={"timeout": 25})
    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini bo'sh javob qaytardi")

    # Model ba'zan javobni tirnoq ichida yoki "Tavsif:" prefiksi bilan
    # qaytarishi mumkin — tozalab beramiz.
    text = text.strip('"“”\'').strip()
    if text.lower().startswith("tavsif:"):
        text = text[len("tavsif:"):].strip()

    return text


def parse_catalog_text(raw_text: str, category_type: str) -> list[dict]:
    """
    Do'kon/markaz egasi bir martalik yozgan erkin matndagi butun
    katalog tavsifini (barcha kurs/mahsulot/xizmatlar) AI orqali
    strukturaviy ro'yxatga (onboarding "items" formatiga mos) ajratadi.

    Bu — FAQAT bir martalik import vositasi: natija owner tomonidan
    ko'rib chiqilib (frontend'da tahrirlanib), keyin oddiy Product
    yozuvlari sifatida saqlanadi. AI'ning mijoz bilan JONLI suhbat
    vaqtidagi "xotirasi"/manbasi sifatida hech qachon ishlatilmaydi —
    suhbat vaqtida AI doim faqat bazadagi (saqlangan) Product'larni
    o'qiydi (apps/chat/ai_service.py, Product.search_for_ai). Shu
    sababli bu yerdagi AI xatosi mijozga noto'g'ri narx/ma'lumot
    sifatida yetib bormaydi — faqat egasi tahrirlashi kerak bo'lgan
    qoralama hosil qiladi.

    Returns:
        list[dict] — har biri {"name", "description", "price", "stock",
        "category", "metadata"} kalitlariga ega bo'lishi mumkin (owner
        tomonidan ko'rib chiqilgach, chaqiruvchi tomon to'liq validatsiya
        qiladi — OnboardingItemSerializer orqali)

    Raises:
        ValueError: Gemini bo'sh yoki JSON bo'lmagan javob qaytarsa
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY sozlanmagan!")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.6-flash")

    label = CATEGORY_LABELS.get(category_type, "mahsulot")
    metadata_hint = CATEGORY_METADATA_HINTS.get(category_type, CATEGORY_METADATA_HINTS["education"])

    prompt = (
        f"Quyida do'kon/markaz egasi o'z {label}lari haqida erkin shaklda yozgan "
        f"matn berilgan. Shu matndagi HAR BIR alohida {label}ni JSON massiviga "
        f"ajratib chiqar.\n\n"
        f"Har bir element quyidagi formatda bo'lsin:\n"
        f'{{"name": "...", "description": "...", "price": 0, "stock": 0, '
        f'"category": "...", {metadata_hint}}}\n\n'
        "Qoidalar:\n"
        "- FAQAT JSON massiv qaytar — boshqa hech qanday matn, izoh yoki ```json belgisi qo'shma.\n"
        "- \"name\" har doim bo'lishi shart, matnda aniq nomi yo'q elementni o'tkazib yubor.\n"
        "- \"price\" — so'mda, faqat raqam (masalan 1200000), agar aytilmagan bo'lsa 0.\n"
        "- \"stock\" — bo'sh joy/dona soni aytilgan bo'lsa shu son, aks holda 0.\n"
        "- \"metadata\" ichiga FAQAT yuqorida ko'rsatilgan kalitlarni qo'sh, matnda aytilmagan kalitni qo'shma.\n"
        "- Matnda umuman narsa topilmasa, bo'sh massiv [] qaytar.\n\n"
        f"Matn:\n{raw_text}"
    )

    response = model.generate_content(prompt, request_options={"timeout": 25})
    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini bo'sh javob qaytardi")

    # Model ba'zan ```json ... ``` bilan o'rab qaytarishi mumkin
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"AI javobi to'g'ri JSON emas: {e}")

    if not isinstance(data, list):
        raise ValueError("AI javobi JSON massiv emas")

    return [
        item for item in data
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
