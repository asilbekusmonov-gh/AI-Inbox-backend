"""
Product AI Service — Mahsulot/kurs/xizmat tavsifini AI orqali yozib berish.

Do'kon egasi TWA'da "Yangi mahsulot" formasini to'ldirganda, tavsif
maydonini qo'lda yozish o'rniga, forma ustidagi maydonlar (nomi,
kategoriya, narxi) asosida Gemini orqali qisqa, sotuvga yo'naltirilgan
tavsif generatsiya qilinadi.
"""
import logging

import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger("apps.products")

CATEGORY_LABELS = {
    "e_commerce": "mahsulot",
    "education": "kurs",
    "services": "xizmat",
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

    response = model.generate_content(prompt)
    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini bo'sh javob qaytardi")

    # Model ba'zan javobni tirnoq ichida yoki "Tavsif:" prefiksi bilan
    # qaytarishi mumkin — tozalab beramiz.
    text = text.strip('"“”\'').strip()
    if text.lower().startswith("tavsif:"):
        text = text[len("tavsif:"):].strip()

    return text
