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


def analyze_product_file(
    file_bytes: bytes,
    mime_type: str,
    category_type: str,
    name: str = "",
    price=None,
) -> dict:
    """
    Egasi TWA'da "Tezkor qo'shish" rejimida biriktirgan faylni (kurs/xizmat
    haqidagi reklama posti, broshura, jadval yoki skrinshot — rasm/PDF/matn)
    AI orqali o'qib, "Yangi kurs/xizmat" formasining qolgan maydonlarini
    (tavsif, kategoriya, davomiyligi, manzil va qo'shimcha ustunlar)
    avtomatik to'ldirish uchun ma'lumot chiqaradi.

    ⚠️ parse_catalog_text kabi bu ham FAQAT qoralama tayyorlaydi — chaqiruvchi
    (frontend) natijani formaga to'ldirib ko'rsatadi, owner ko'rib chiqib
    "Saqlash"ni bosgandan keyingina haqiqiy Product yozuvi hosil bo'ladi.
    Shu sababli natijadagi maydon nomlari ONBOARDING importidagi
    (CATEGORY_METADATA_HINTS) strukturaviy metadata bilan EMAS, balki
    AddProductModal formasining o'z maydonlari (duration/location/
    custom_fields) bilan mos keladi.

    Returns:
        dict — {"name", "price", "description", "category", "stock",
        "duration", "location", "custom_fields": [{"key", "value"}, ...]}

    Raises:
        ValueError: Gemini bo'sh yoki JSON bo'lmagan javob qaytarsa
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY sozlanmagan!")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.6-flash")

    label = CATEGORY_LABELS.get(category_type, "mahsulot")

    context_lines = []
    if name:
        context_lines.append(f"Nomi: {name}")
    if price:
        context_lines.append(f"Narxi: {price} so'm")
    context = ("\n\nMa'lum bo'lgan ma'lumot (bu allaqachon berilgan, qayta ajratib olish shart emas):\n" + "\n".join(context_lines)) if context_lines else ""

    # ⚠️ Avval "Nomi"/"Narxi" frontendda majburiy maydon edi, shuning uchun
    # bu yerga har doim berilgan bo'lardi. Endi ular ixtiyoriy bo'lgani
    # uchun (egasi faylga ishonib, bo'sh qoldirishi mumkin) AI shularni ham
    # fayldan ajratib olishga harakat qiladi — agar `name`/`price` yuqorida
    # berilgan bo'lsa, bu ikki maydonni e'tiborsiz qoldirsa ham bo'ladi
    # (chaqiruvchi — view — baribir o'zi berganini ustun qo'yadi).
    prompt = (
        f"Biriktirilgan fayl — {label} haqida egasi yuklagan hujjat/rasm "
        f"(masalan reklama posti, broshura, dars jadvali yoki skrinshot). "
        f"Uning tarkibidagi ma'lumotlarni o'qib, quyidagi JSON formatda "
        f"strukturaviy ma'lumot chiqar:\n\n"
        '{"name": "...", "price": 0, "description": "...", "category": "...", "stock": 0, '
        '"duration": "...", "location": "...", "full_text": "...", '
        '"custom_fields": [{"key": "...", "value": "..."}]}\n\n'
        "Qoidalar:\n"
        "- FAQAT JSON obyekt qaytar — boshqa hech qanday matn, izoh yoki ```json belgisi qo'shma.\n"
        "- \"name\" — agar yuqorida 'Ma'lum bo'lgan ma'lumot'da nomi berilmagan bo'lsa, faylda aniq ko'rsatilgan "
        "kurs/xizmat nomini (sarlavha yoki eng aniq mavzu nomi) chiqar, aks holda bo'sh qator.\n"
        "- \"price\" — agar yuqorida narxi berilmagan bo'lsa va faylda aniq narx (so'mda) ko'rsatilgan bo'lsa, "
        "FAQAT sonni (valyuta belgisi/so'z qo'shmasdan) chiqar, aks holda 0.\n"
        "- \"description\" — AI sotuv boti mijozlarga ko'rsatadigan QISQA "
        "(bitta yoki ikkita gap, 40 so'zdan oshmasin), ishonarli va sotuvga undovchi tavsif.\n"
        "- \"category\" — faylda aniq mavzu/yo'nalish ko'rsatilgan bo'lsa shu (masalan \"Dasturlash\", \"Chet tillari\"), aks holda bo'sh qatr.\n"
        "- \"stock\" — bo'sh joy/dona soni faylda aniq aytilgan bo'lsa shu son, aks holda 0.\n"
        "- \"duration\" — davomiyligi (masalan \"3 oy\", \"1 soat\") faylda aytilgan bo'lsa shu, aks holda bo'sh qatr.\n"
        "- \"location\" — manzil/joylashuv faylda aytilgan bo'lsa shu, aks holda bo'sh qatr.\n"
        "- \"full_text\" — fayldagi BARCHA matnni asl ketma-ketligi, qator "
        "bo'linishlari va emojilari bilan AYNAN ko'chir. Bu — qisqartma yoki "
        "xulosa EMAS: mijozga keyinchalik aynan shu matn ko'rsatiladi, "
        "shuning uchun hech narsani tashlab ketma, qayta yozma va o'zingdan "
        "hech narsa qo'shma. Matn umuman bo'lmasa (masalan faqat rasm), "
        "bo'sh qator qaytar.\n"
        "- \"custom_fields\" — yuqoridagilarga sig'magan, lekin faylda aniq aytilgan boshqa foydali ma'lumotlar "
        "(masalan o'qituvchi ismi, dars jadvali, format, sertifikat) — har biri qisqa o'zbekcha nom bilan, "
        "ko'pi bilan 5 ta juftlik. Faylda yo'q narsani o'zing to'qib chiqarma.\n"
        "- Faylda umuman o'qib bo'lmaydigan yoki aloqasiz tarkib bo'lsa, barcha maydonlarni bo'sh/0 qaytar.\n"
        f"{context}"
    )

    # ⚠️ BUG FIX (jonli holatda aniqlangan): `{"mime_type": ..., "data":
    # file_bytes}` (xom lug'at/dict) ko'rinishidagi "inline blob" bu SDK
    # versiyasida SUDRALIB ishlar edi — xato bermasdan, lekin har safar
    # 40+ soniya osilib, `DeadlineExceeded` bilan qulardi (matnli so'rovlar
    # esa ~10 soniyada tugaydi). Rasm uchun to'g'ri, tezkor yo'l — `PIL.Image`
    # ob'ektining o'zini yuborish (tasdiqlandi: ~11 soniyada, to'g'ri natija
    # bilan). Matn uchun esa umuman "blob" kerak emas — to'g'ridan-to'g'ri
    # promptga qo'shiladi, bu ham tezroq va ishonchliroq.
    # ⚠️ Matnli fayllar uchun to'liq matn AI'dan EMAS, to'g'ridan-to'g'ri
    # fayldan olinadi (pastda natijaga yoziladi) — AI uni qayta terib
    # chiqishiga yo'l qo'ymaymiz: matn mijozga AYNAN shu holatda
    # ko'rsatiladi, shuning uchun 100% asl bo'lishi SHART (va bu token
    # ham tejaydi).
    raw_file_text = ""

    if mime_type.startswith("image/"):
        from PIL import Image
        import io as _io

        contents = [Image.open(_io.BytesIO(file_bytes)), prompt]
    elif mime_type in ("text/plain", "text/markdown"):
        try:
            file_text = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            file_text = ""
        raw_file_text = file_text.strip()
        contents = [f"{prompt}\n\nFayl matni:\n{file_text}"]
    else:
        # application/pdf — so'rovning ichiga to'g'ridan-to'g'ri (inline) joylanadi.
        # ⚠️ Jonli aniqlangan xato (2026-10-24): avval PDF Gemini "File API"
        # (`genai.upload_file`) orqali yuklanardi. Bu yo'l alohida
        # `$discovery` so'rovi yuboradi va joriy API kalitini "API key not
        # valid" deb RAD ETADI — garchi oddiy suhbat so'rovlari shu kalit
        # bilan ishlasa ham. Natijada PDF bilan kurs qo'shish 502 berardi.
        # Inline yo'l esa shu kalit bilan ishlaydi (jonli sinaldi: ~3 soniya)
        # va vaqtinchalik fayl yuklab/o'chirib o'tirmaslikni ham talab qilmaydi.
        # Cheklov: so'rov 20 MB dan oshmasligi kerak (view'da fayl 10 MB bilan
        # cheklangan, shuning uchun xavfsiz).
        contents = [
            genai.protos.Part(
                inline_data=genai.protos.Blob(mime_type=mime_type, data=file_bytes)
            ),
            prompt,
        ]

    # ⚠️ Rasm/PDF tahlili matnli so'rovlarga qaraganda sezilarli sekinroq
    # va vaqti beqaror (jonli testda 11s dan 40s gacha o'zgardi) — shu
    # sabab boshqa Gemini chaqiruvlaridan (odatda 25s) kattaroq muhlat.
    response = model.generate_content(contents, request_options={"timeout": 60})

    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini bo'sh javob qaytardi")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"AI javobi to'g'ri JSON emas: {e}")

    if not isinstance(data, dict):
        raise ValueError("AI javobi JSON obyekt emas")

    # Matnli fayl bo'lsa — AI terib bergan "full_text" o'rniga faylning
    # O'ZIDAN o'qilgan asl matnni qo'yamiz (yuqoridagi izohga qarang).
    if raw_file_text:
        data["full_text"] = raw_file_text

    return data
