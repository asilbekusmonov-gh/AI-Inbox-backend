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

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("apps.chat")


def _log_crm_sync_failure(provider: str, store, lead, error: str) -> None:
    from apps.audit.services import log_platform_error
    from apps.audit.models import PlatformError
    log_platform_error(
        source=PlatformError.Source.CRM_SYNC,
        message=f"{provider}'ga lid yuborilmadi ({lead.lead_number}): {error}",
        store=store,
        metadata={"provider": provider, "lead_number": lead.lead_number},
    )


def _log_owner_notification_failure(store, lead, error: str) -> None:
    from apps.audit.services import log_platform_error
    from apps.audit.models import PlatformError
    log_platform_error(
        source=PlatformError.Source.OWNER_NOTIFICATION,
        message=f"Egaga lid haqida xabar yuborilmadi ({lead.lead_number}): {error}",
        store=store,
        metadata={"lead_number": lead.lead_number},
    )

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


# ⚠️ Telefon raqami uchun qabul qilinadigan xona chegaralari:
# O'zbekiston milliy raqami 9 xonali ("901234567"), xalqaro kod bilan
# 12 xonali ("998901234567"). Boshqa davlat raqamlari ham kelishi
# mumkinligi uchun yuqori chegara E.164 standartidagi 15 xona qilib
# olingan — ya'ni qoida "faqat O'zbekiston" emas, lekin telefon
# raqami BO'LA OLMAYDIGAN qiymatlarni aniq rad etadi.
_PHONE_MIN_DIGITS = 9
_PHONE_MAX_DIGITS = 15

# Telefon raqamida uchrashi mumkin bo'lgan ajratuvchilar (bular
# normallashtirishda olib tashlanadi): bo'shliq, qavs, chiziqcha, nuqta.
_PHONE_ALLOWED_NON_DIGITS = re.compile(r"^[\d\s()+\-.]+$")


def _normalize_phone(raw_phone: str) -> tuple[Optional[str], Optional[str]]:
    """
    Telefon raqamini DETERMINISTIK tekshiradi va normallashtiradi.

    ⚠️ Nega bu AI promptiga tashlab qo'yilmaydi: AI mijozning xabaridan
    raqamni noto'g'ri ajratib olishi mumkin — jonli holatda aniqlangan
    misol: mijoz "ali 987654" deb yozganda, AI buni ism="ali",
    telefon="987654" deb ajratib yuborgan. "987654" — telefon raqami
    emas (atigi 6 xona), lekin avval bu qiymat shunchaki "shubhali" deb
    belgilanib, lid BARIBIR yaratilardi: do'kon egasiga soxta kontaktli
    "YANGI LID" xabarnomasi borardi, CRM'ga ham o'sha yaroqsiz raqam
    yuborilardi, mijozga esa "ma'lumotlaringiz qabul qilindi" deyilardi.
    Endi bunday qiymat lid yaratilishini TO'XTATADI (chaqiruvchi tomon
    mijozdan raqamni qayta so'raydi).

    Returns:
        (normallashtirilgan_raqam, None) — raqam yaroqli
        (None, sabab) — raqam yaroqsiz, lid yaratilmasligi kerak
    """
    raw = (raw_phone or "").strip()
    if not raw:
        return None, "bo'sh"

    # Harf yoki boshqa begona belgi bo'lsa — bu toza telefon raqami emas
    # (masalan "ali 987654", "раqam yo'q", "+998 90 ... (ish raqami)").
    if not _PHONE_ALLOWED_NON_DIGITS.match(raw):
        return None, "raqamdan tashqari belgilar bor"

    digits = re.sub(r"\D", "", raw)
    has_plus = raw.startswith("+")

    # ⚠️ Jonli aniqlangan xato (2026-10-18): avval shunchaki "9-15 xona"
    # deb tekshirilardi va mijoz bitta ortiqcha raqam qo'shib yuborganda
    # ("9345678690" — 10 xona) tizim uni YAROQLI deb qabul qilgan edi.
    # Natijada egaga qo'ng'iroq qilib bo'lmaydigan raqam borardi.
    # Endi O'zbekiston formatlari ANIQ tekshiriladi:
    #   • 9 xona            → milliy raqam (901234567)
    #   • 12 xona, 998 bilan → xalqaro kod bilan (998901234567)
    # Boshqa davlat raqami kiritilsa, u "+" bilan boshlanishi kerak —
    # bu mijozning xalqaro raqam yozayotgani haqidagi ANIQ signali
    # (aks holda har qanday tasodifiy raqamlar ketma-ketligi o'tib
    # ketaverardi).
    if has_plus:
        if len(digits) < 10 or len(digits) > _PHONE_MAX_DIGITS:
            return None, f"xalqaro raqam uzunligi noto'g'ri ({len(digits)} xona)"
        return f"+{digits}", None

    if len(digits) == 9:
        return digits, None
    if len(digits) == 12 and digits.startswith("998"):
        return f"+{digits}", None

    # ⚠️ Do'kon egasi talabi (2026-10-28): Rossiya, Qozog'iston va Qirg'iziston raqamlari ham
    # qabul qilinadi (mijozlar shu davlatlardan ham yozadi). Bular "+"siz ham ANIQ formatda:
    #   • 11 xona, 7 yoki 8 bilan  → Rossiya/Qozog'iston ("89161234567", "79161234567");
    #                                8 — mahalliy "trunk" prefiksi, +7 ga aylantiriladi
    #   • 12 xona, 996 bilan       → Qirg'iziston ("996555123456")
    # Boshqa uzunliklar (masalan 10 xona "9345678729") avvalgidek RAD etiladi — ular
    # O'zbekistondagi "bitta ortiqcha raqam" xatosi.
    if len(digits) == 11 and digits[0] in "78":
        return f"+7{digits[1:]}", None
    if len(digits) == 12 and digits.startswith("996"):
        return f"+{digits}", None

    if len(digits) < _PHONE_MIN_DIGITS:
        return None, f"juda qisqa ({len(digits)} xona)"
    return None, f"noto'g'ri uzunlik ({len(digits)} xona)"


def foreign_phone_label(phone: str) -> Optional[str]:
    """
    Raqam O'zbekiston raqami EMAS bo'lsa — davlat nomi bilan qisqa yorliq, aks holda None.
    ("+79161234567" → "Rossiya, +7 916…", "+77011234567" → "Qozog'iston, +7 701…")
    """
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    # O'zbekiston: 9 xonali milliy yoki 998 bilan
    if (len(digits) == 9 and not raw.startswith("+")) or digits.startswith("998"):
        return None

    shown = f"+{digits}"
    if digits.startswith("7") and len(digits) == 11:
        # Qozog'iston mobil/shahar kodlari 6xx va 7xx; Rossiya — qolganlari
        country = "Qozog'iston" if digits[1] in "67" else "Rossiya"
        return f"{country}, {shown}"
    if digits.startswith("996"):
        return f"Qirg'iziston, {shown}"
    return f"xorijiy raqam, {shown}"


def foreign_contact_note(*, phone: str, customer) -> str:
    """
    O'zbekiston raqami bo'lmagan mijoz uchun operatorga izoh: qo'ng'iroq o'rniga mijozning
    Telegram shaxsiy akkaunti orqali bog'lanish (Bitrix24/Sheets/Excel izohiga qo'shiladi).
    """
    label = foreign_phone_label(phone)
    if not label:
        return ""

    username = (getattr(customer, "username", "") or "").lstrip("@")
    platform = getattr(customer, "platform", "")
    user_id = getattr(customer, "platform_user_id", "")
    if platform == "telegram" and username:
        contact = f"@{username} (https://t.me/{username})"
    elif platform == "telegram" and user_id:
        contact = f"Telegram ID {user_id} (tg://user?id={user_id})"
    elif username:
        contact = f"@{username}"
    else:
        contact = "mijozning o'sha platformadagi suhbati"
    return (
        f"⚠️ O'zbekiston raqami emas ({label}) — qo'ng'iroq o'rniga Telegram orqali "
        f"bog'laning: {contact}."
    )


# ⚠️ Yaroqsiz raqam yuborilganda mijozga ko'rsatiladigan YAGONA matn
# (avval apps/webhooks/tasks.py ichida alohida yozilgan edi).
INVALID_PHONE_TEXT = (
    "Telefon raqami noto'g'ri ko'rinmoqda. Iltimos, qaytadan "
    "tekshirib yuboring (masalan: +998 90 123 45 67)."
)

# Telefonga o'xshash raqamlar ketma-ketligi (bo'shliq, tire, qavs bilan).
_PHONE_CANDIDATE_RE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")
# Narx/yil kabi oddiy sonlar ("1 800 000") telefon deb olinmasligi uchun
# kamida shuncha xona bo'lishi kerak (eng qisqa yaroqli raqam — 9 xona).
_PHONE_CANDIDATE_MIN_DIGITS = 9


def find_phone_candidate(message: str) -> Optional[str]:
    """Xabar ichidan telefon raqamiga o'xshash qismni topadi (topilmasa None)."""
    for match in _PHONE_CANDIDATE_RE.finditer(message or ""):
        candidate = match.group(0).strip()
        if len(re.sub(r"\D", "", candidate)) >= _PHONE_CANDIDATE_MIN_DIGITS:
            return candidate
    return None


# Mijoz kontaktini o'zi yozganda (AI buni lid deb ajratmagan bo'lsa ham)
# kod o'zi qabul qiladigan holat uchun — qisqa tasdiq matni.
CONTACT_RECEIVED_TEXT = "Rahmat, {name}! Ma'lumotlaringizni qabul qildim — mutaxassisimiz tez orada siz bilan bog'lanadi 😊"

# Ismni ajratishda tashlab yuboriladigan so'zlar ("ismim Ali, raqamim ...").
_NAME_FILLER_WORDS = {
    "ismim", "ism", "familiyam", "familiya", "raqamim", "raqam", "nomerim", "nomer",
    "telefonim", "telefon", "tel", "men", "mening", "meniki", "bu", "mana", "my", "name", "phone",
}


def extract_contact_from_message(message: str) -> Optional[dict]:
    """
    Mijoz xabaridan DETERMINISTIK tarzda (AI'siz) ism + yaroqli telefon raqamini ajratadi.

    ⚠️ Jonli aniqlangan xato (2026-10-24): mijoz "Asilbek Usmonov 998787653"
    deb yozdi. Bu — haqiqiy raqam (99 878 76 53), bizning tekshiruvimiz ham
    uni qabul qiladi, lekin AI uni "998 bilan boshlanadigan to'liq bo'lmagan
    xalqaro raqam" deb o'ylab, o'zi "Telefon raqami noto'g'ri" deb javob
    berdi va lid yaratilmadi.

    Returns:
        {"full_name": ..., "phone": ...} — ikkalasi ham yaroqli bo'lsa, aks holda None.
    """
    text = message or ""
    if "?" in text:
        return None  # savol — kontakt emas

    candidate = find_phone_candidate(text)
    if not candidate:
        return None
    phone, _reason = _normalize_phone(candidate)
    if not phone:
        return None

    rest = text.replace(candidate, " ")
    rest = re.sub(r"[^\w\s'’`-]", " ", rest, flags=re.UNICODE)
    tokens = [
        t for t in rest.split()
        if t.lower() not in _NAME_FILLER_WORDS and not t.isdigit()
    ]
    if not 1 <= len(tokens) <= 4:
        return None
    name, _name_reason = _validate_full_name(" ".join(tokens))
    if not name:
        return None
    return {"full_name": name, "phone": phone}


# Mijoz xotirasidagi (AI kuzatgan) maydonlar -> operator uchun tushunarli yorliqlar
_NOTE_MEMORY_LABELS = (
    ("goal", "Maqsadi"),
    ("experience_level", "Hozirgi darajasi"),
    ("preferred_schedule", "Qulay vaqt"),
    ("preferred_day", "Qulay kun"),
    ("budget_concern", "Narx haqida"),
    ("objections", "E'tirozi"),
)
_NOTE_MAX_CUSTOMER_MESSAGES = 3
_NOTE_MESSAGE_MAX_LEN = 110


def compose_lead_notes(*, customer, memory: Optional[dict] = None, product_name: str = "",
                       exclude_text: str = "") -> str:
    """
    Operator uchun izohni AI'siz, mijozning O'Z ma'lumotlaridan tuzadi:
    qiziqqan kurs, maqsad/daraja/vaqt (AI kuzatgan xotira) va mijozning o'z so'zlari.

    ⚠️ Nega kerak: AI lid blokida `notes` ni bo'sh qoldirsa yoki lidni KOD o'zi
    tuzgan bo'lsa (AI blokni qaytarmaganda), izohga "kod orqali aniqlandi" kabi ichki
    texnik matn tushardi — operator uchun foydasiz. Bu yerda HECH NARSA o'ylab
    topilmaydi: faqat mijoz aytgan yoki AI xotirasiga yozgan narsa ishlatiladi.
    """
    parts = []
    if product_name:
        parts.append(f"Qiziqqan kurs: {product_name}.")

    merged_memory = {**(getattr(customer, "conversation_memory", None) or {}), **(memory or {})}
    for key, label in _NOTE_MEMORY_LABELS:
        value = merged_memory.get(key)
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value if v)
        value = str(value or "").strip()
        if value:
            parts.append(f"{label}: {value}.")

    # Mijozning o'z so'zlari (buyruqlar, qisqa tasdiqlar va kontakt xabarining o'zi chiqarib tashlanadi)
    try:
        from apps.chat.models import ChatMessage

        recent = ChatMessage.all_objects.filter(
            customer=customer, role=ChatMessage.Role.USER,
        ).order_by("-created_at")[:12]
        said = []
        for msg in reversed(list(recent)):
            text = " ".join((msg.content or "").split())
            if (
                not text or text.startswith("/") or len(text) < 8
                or (exclude_text and text == " ".join(exclude_text.split()))
                or find_phone_candidate(text)
            ):
                continue
            said.append(text[:_NOTE_MESSAGE_MAX_LEN].rstrip() + ("…" if len(text) > _NOTE_MESSAGE_MAX_LEN else ""))
        said = said[-_NOTE_MAX_CUSTOMER_MESSAGES:]
        if said:
            parts.append("Mijoz yozgan: " + "; ".join(f"«{s}»" for s in said) + ".")
    except Exception:
        logger.warning("Lid izohi uchun mijoz xabarlarini o'qib bo'lmadi", exc_info=True)

    return " ".join(parts) if parts else "Aniq sabab aytilmadi."


def _validate_full_name(raw_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Ism-familiyani DETERMINISTIK tekshiradi va ortiqcha bo'shliqlardan
    tozalaydi.

    ⚠️ Ataylab YUMSHOQ qoida: faqat ism BO'LA OLMAYDIGAN qiymatlar rad
    etiladi (raqamdan iborat, umuman harfsiz, bitta belgili). Lotin,
    kirill, apostrof ("G'ulom"), chiziqcha ("Abdulla-bek") va bitta
    so'zli ismlar — hammasi YAROQLI. Sabab: haddan tashqari qattiq
    qoida haqiqiy mijozni yo'qotadi, bu esa lid yig'ish maqsadiga zid.

    Returns:
        (tozalangan_ism, None) — ism yaroqli
        (None, sabab) — ism yaroqsiz, lid yaratilmasligi kerak
    """
    name = " ".join((raw_name or "").split())
    if not name:
        return None, "bo'sh"
    if len(name) < 2:
        return None, "juda qisqa"
    # Kamida bitta harf bo'lishi SHART — "+998901234567", "123", "???",
    # faqat emoji kabi qiymatlar ism emas (ko'pincha AI maydonlarni
    # almashtirib yuborgan holat: telefon raqami ism maydoniga tushgan).
    if not re.search(r"[^\W\d_]", name, re.UNICODE):
        return None, "harf yo'q (ism emas)"
    return name, None


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

        # ⚠️ DETERMINISTIK validatsiya — AI javobiga ishonib qolmaymiz.
        # Yaroqsiz kontakt bilan lid YARATILMAYDI: chaqiruvchi (webhooks/
        # tasks.py) `None` javobini ko'rib, mijozdan ma'lumotni qayta
        # so'raydi — shunda do'kon egasiga soxta kontakt ham bormaydi,
        # CRM'ga ham yaroqsiz raqam yuborilmaydi.
        full_name, name_error = _validate_full_name(full_name)
        if name_error:
            logger.warning(f"Lid yaratish rad etildi: ism yaroqsiz ({name_error})")
            return None

        phone, phone_error = _normalize_phone(phone)
        if phone_error:
            logger.warning(f"Lid yaratish rad etildi: telefon yaroqsiz ({phone_error})")
            return None

        # Qiziqqan kurs/mahsulot/xizmat nomi — toifaga qarab turli kalitdan kelishi mumkin
        interest_name = (
            str(lead_data.get("course_name", "")).strip()
            or str(lead_data.get("service_name", "")).strip()
            or str(lead_data.get("product_name", "")).strip()
        )
        interested_course = _find_interested_course(store, interest_name) if interest_name else None

        booking_time = str(lead_data.get("booking_time", "")).strip()
        specialist = str(lead_data.get("specialist", "")).strip()
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

        # ⚠️ Izoh HECH QACHON bo'sh yoki ichki-texnik matn bo'lmasligi kerak (qarang:
        # `compose_lead_notes`). AI yozgan izoh bor bo'lsa — o'sha qoladi.
        if not notes:
            notes = compose_lead_notes(
                customer=customer, memory=None,
                product_name=getattr(interested_course, "name", "") or "",
                exclude_text="",
            )

        # Xorijiy (O'zbekistonniki bo'lmagan) raqam — operatorga Telegram orqali bog'lanishni eslatamiz.
        # Izoh Bitrix24, Google Sheets va Excel'ga AYNAN shu matn bilan boradi.
        foreign_note = foreign_contact_note(phone=phone, customer=customer)
        if foreign_note:
            notes = f"{notes}\n{foreign_note}".strip()

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

        # ⚠️ Uchta yozuv (Lead yaratish, Customer'ga ism/telefonni
        # ko'chirish, total_leads sanog'i) BITTA tranzaksiyada bajariladi
        # — aks holda oradagi xato/uzilish "yarim yozilgan" holat
        # qoldirardi (masalan lid bor, lekin mijoz kartochkasida telefon
        # yo'q yoki sanoq noto'g'ri). Bu yerda tashqi chaqiruv (Telegram/
        # CRM) YO'Q — ular yuqori qatlamda, tranzaksiyadan TASHQARIDA
        # bajariladi, shuning uchun tranzaksiya qisqa va xavfsiz.
        with transaction.atomic():
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
            # ⚠️ Ega TWA'dan bog'lanmagan bo'lsa (masalan Super Admin
            # "Kirishni bekor qilish" bosgandan keyin, yangi ega hali
            # bog'lanmagan) — lid baribir bazaga saqlanadi, lekin hech
            # kimga DARHOL xabar bormasdi, ya'ni platforma egasi buni
            # o'zi TWA'ni tekshirmaguncha bilmasdi. Endi shu holatda
            # zaxira sifatida platforma superadminlariga (master bot
            # orqali) ogohlantirish yuboriladi.
            logger.warning(
                f"Egaga xabarnoma: {store.name} do'konida tg_owner_chat_id yo'q! "
                f"Platforma superadminlariga zaxira xabar yuborilmoqda."
            )
            return _notify_platform_superadmins_fallback(store, lead)

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
            _log_owner_notification_failure(store, lead, "noma'lum xato")

        return success

    except Exception as e:
        logger.error(
            f"Egaga xabarnoma yuborishda xato: {e}",
            exc_info=True,
        )
        _log_owner_notification_failure(store, lead, str(e))
        return False


def _notify_platform_superadmins_fallback(store, lead) -> bool:
    """
    `store.tg_owner_chat_id` bo'sh bo'lganda (TWA egasi bog'lanmagan)
    chaqiriladigan zaxira yo'l — yangi lid haqidagi xabar MASTER bot
    orqali `settings.SUPERADMIN_TG_CHAT_IDS` ro'yxatidagi har bir
    platforma administratoriga yuboriladi, shunda lid "hech kim
    bilmasdan" qolib ketmaydi.

    ⚠️ ATAYLAB `Lead.owner_notified`ni `True`ga o'rnatmaydi — bu maydon
    "HAQIQIY do'kon egasi xabardor qilindi" degan ma'noni bildiradi;
    zaxira xabar administratorga bo'lgani uchun, yangi ega keyinchalik
    bog'langanda ham bu HALI xabardor qilinmagan hisoblanadi.
    """
    from django.conf import settings

    from apps.chat.senders import send_telegram_message, _format_lead_notification

    master_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    superadmin_ids = getattr(settings, "SUPERADMIN_TG_CHAT_IDS", [])
    if not master_token or not superadmin_ids:
        logger.warning(
            f"Egaga xabarnoma: zaxira ham yuborilmadi — MASTER token yoki "
            f"SUPERADMIN_TG_CHAT_IDS sozlanmagan ({store.name})."
        )
        return False

    text = (
        f"⚠️ <b>Diqqat: TWA egasi bog'lanmagan!</b>\n"
        f"🏬 <b>Biznes:</b> {store.name}\n\n"
        f"{_format_lead_notification(lead)}"
    )

    any_success = False
    for chat_id in superadmin_ids:
        if send_telegram_message(bot_token=master_token, chat_id=chat_id, text=text, parse_mode="HTML"):
            any_success = True

    if any_success:
        logger.info(f"Egaga xabarnoma: zaxira xabar platforma superadminlariga yuborildi ({store.name}).")
    return any_success


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
            _log_crm_sync_failure("Bitrix24", store, lead, "noma'lum xato")

        return success

    except Exception as e:
        logger.error(
            f"Bitrix24'ga yuborishda xato: {e}",
            exc_info=True,
        )
        _log_crm_sync_failure("Bitrix24", store, lead, str(e))
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
            _log_crm_sync_failure("Google Sheets", store, lead, "noma'lum xato")

        return success

    except Exception as e:
        logger.error(
            f"Google Sheets'ga yuborishda xato: {e}",
            exc_info=True,
        )
        _log_crm_sync_failure("Google Sheets", store, lead, str(e))
        return False
