"""
Customer Celery Tasks — Javobsiz qolgan mijozlarga avtomatik follow-up.

⚠️ Muammo: mijoz AI bilan gaplashib, narx/kurs haqida so'rab, keyin hech
qanday javob bermay "yo'qolib" ketishi mumkin (masalan faqat "👍" deb
qo'yib, ism/telefon qoldirmasdan). Bunday mijoz hech qachon Lead
bo'lmagani uchun operator ham undan bexabar qoladi — potensial mijoz
butunlay yo'qolib ketadi. Bu task shunday mijozlarga do'kon sozlagan
kechikish bilan (standart: 6 soat, keyin 24 soat) qisqa, spam bo'lmagan
eslatma yuboradi, so'ng to'xtaydi.

Celery Beat settings.py'da sozlangan:
  CELERY_BEAT_SCHEDULE["send-followup-messages"]
"""
import logging
import re
import uuid
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("apps.customers")

# Juda eski (masalan oylar oldingi) suhbatlarni bu funksiya UMUMAN
# "ko'rmaydi" — aks holda bu funksiya birinchi marta deploy qilinganda,
# ko'p oy oldin jim qolgan yuzlab eski mijozga birdaniga follow-up
# "portlashi" mumkin edi.
_MAX_LOOKBACK_DAYS = 7

# ⚠️ Mijozning suhbatga qanchalik chuqur kirishiga qarab UCHTA turdagi
# follow-up matni ishlatiladi — avval hammasi UMUMIY ("savollaringiz
# bo'lsa yozing" kabi) bo'lgani uchun "juda oddiy"/sun'iy tuyulardi.
# Tur AI'ning `Customer.conversation_stage`ini (har bir javobda
# yangilanadigan, allaqachon mavjud maydon) asos qilib aniqlanadi —
# yangi maydon/AI so'rovi kerak emas.
#
#  - "never_wrote"       — /start bosdi (yoki umuman yo'q), lekin AI bilan
#                           birorta ham shaxsiy xabar almashmagan.
#  - "engaged_no_contact" — suhbatlashdi, biror narsaga qiziqdi, lekin
#                           hali ro'yxatdan o'tishga "tayyor" darajasiga
#                           yetmadi.
#  - "high_intent"        — AI mijozni yuqori xarid niyatli deb baholagan
#                           (HIGH_INTENT/READY_TO_CONVERT/QUALIFICATION),
#                           lekin hali ro'yxatdan o'tmagan — bu yerda CTA
#                           tugmasi bilan ANIQROQ taklif beriladi.
_HIGH_INTENT_STAGES = {
    "qualification", "high_intent", "ready_to_convert",
}


def _determine_followup_tier(store, customer) -> str:
    """
    Mijozning follow-up "turi"ni aniqlaydi — pastdagi `_build_followup_text`
    shunga qarab mos matnni tanlaydi (qarang: yuqoridagi izoh).
    """
    from apps.chat.models import ChatMessage

    has_written = ChatMessage.objects.filter(
        store=store, customer=customer,
        role=ChatMessage.Role.USER, is_group_message=False,
    ).exists()
    if not has_written:
        return "never_wrote"

    if customer.conversation_stage in _HIGH_INTENT_STAGES:
        return "high_intent"

    return "engaged_no_contact"


def _guess_discussed_course(store, customer) -> str | None:
    """
    Mijozning so'nggi shaxsiy xabarlarida do'konning aktiv
    mahsulot/kurs nomlaridan biri tilga olinganmi — bo'lsa, follow-up
    xabarini o'sha kursga moslab shaxsiylashtirish uchun.

    ⚠️ ATAYLAB oddiy (regex/substring) qidiruv — bu yerda yangi Gemini
    so'rovi qo'shish (AI orqali aniqlash) davriy vazifaga qo'shimcha
    tashqi API bog'liqligi va xarajat qo'shган bo'lardi, holbuki bu
    shunchaki "iliqroq" xabar matni uchun ixtiyoriy bezak — muvaffaqiyatsiz
    bo'lsa ham (kurs topilmasa) umumiy shablon bilan davom etaveradi.
    """
    from apps.chat.models import ChatMessage
    from apps.products.models import Product

    recent_texts = list(
        ChatMessage.objects.filter(
            store=store, customer=customer,
            role=ChatMessage.Role.USER, is_group_message=False,
        ).order_by("-created_at").values_list("content", flat=True)[:5]
    )
    if not recent_texts:
        return None
    haystack = " ".join(recent_texts).lower()

    product_names = Product.objects.filter(
        store=store, is_active=True
    ).values_list("name", flat=True)

    for name in product_names:
        if name and re.search(re.escape(name.lower()), haystack):
            return name
    return None


def _sample_product_names(store, limit: int = 2) -> list[str]:
    """Follow-up matnida misol sifatida ko'rsatiladigan haqiqiy kurs/xizmat nomlari."""
    from apps.products.models import Product

    names = Product.objects.filter(store=store, is_active=True).values_list("name", flat=True)[:limit]
    # Uzun nomlar ("Python Backend Development: Professional Dasturlash Kursi") misolda xunuk
    # chiqadi — ikki nuqta yoki tire'gacha bo'lgan asosiy qismi olinadi.
    return [re.split(r"\s*[:–—]\s*", name, maxsplit=1)[0].strip() or name for name in names]


def _build_followup_text(tier: str, stage: int, store, course: str | None) -> str:
    """
    Mijozning follow-up "turi"ga (`_determine_followup_tier`) va nechanchi
    eslatma ekaniga (1 yoki 2) qarab tabiiy, shaxsiylashtirilgan matn
    quradi. Bitta katta .format() shablon o'rniga qismlarga bo'lib
    quriladi — chunki ixtiyoriy qismlar (kurs nomi, misollar) bo'lmasa
    ham grammatik jihatdan tabiiy chiqishi kerak.

    ⚠️ Matnlar botning HOZIRGI qoidalariga mos (2026-10-28):
      • "Kecha yozgandingiz" EMAS — eslatma 6 soatdan keyin ketadi, ya'ni ko'pincha o'sha
        kunning o'zida, shuning uchun vaqtga bog'liq bo'lmagan "Yaqinda" ishlatiladi
      • narx/ma'lumot VA'DA QILINMAYDI — bot kontaktsiz narx bermaydi
      • "administrator/operator" emas, "mutaxassislarimiz"
      • o'ylab topilgan da'volar ("joylar tez to'lib qoladi") yo'q
    """
    label = "kurs" if getattr(store, "category_type", "education") == "education" else "xizmat"

    if tier == "never_wrote":
        if stage == 1:
            examples = _sample_product_names(store)
            examples_str = f" (masalan, {', '.join(examples)})" if examples else ""
            return (
                f"Salom 😊 Botimizga kirgandingiz. "
                f"Sizni qaysi {label}imiz qiziqtirgandi{examples_str}? "
                f"Yozib yuborsangiz, yordam beraman."
            )
        return (
            f"Salom yana bir bor 🙂 Agar hali ham {label} tanlashda "
            f"qiynalayotgan bo'lsangiz, shunchaki nima kerakligini yozing — "
            f"men yordam beraman."
        )

    course_ref = f" {course} bo'yicha" if course else ""
    about = f" {course} haqida" if course else ""

    if tier == "engaged_no_contact":
        if stage == 1:
            return (
                f"Salom 😊 Yaqinda{course_ref} yozgandingiz. Agar hali ham "
                f"qiziqayotgan bo'lsangiz, ism-familiyangiz va telefon raqamingizni "
                f"qoldiring — mutaxassislarimiz sizga{about} batafsil ma'lumot berishadi."
            )
        return (
            f"Salom!{course_ref} savolingiz hali ham dolzarbmi? "
            f"Bemalol yozing, yordam beraman 🙌"
        )

    # tier == "high_intent" — mijoz allaqachon aniq qiziqish bildirgan,
    # shuning uchun CTA ochiqroq. Mijoz ALLAQACHON shaxsiy chatda bo'lgani
    # uchun tashqi havola shart emas — to'g'ridan-to'g'ri ism/raqam
    # so'raladi (AI keyingi javobda buni odatdagidek lidga aylantiradi).
    if stage == 1:
        return (
            f"Salom! 😊 Yaqinda{course_ref} gaplashgandik. Agar xohlasangiz, "
            f"sizga mos guruhni aniqlab berishimiz uchun ism-familiyangiz va "
            f"telefon raqamingizni qoldiring — mutaxassislarimiz siz bilan bog'lanadi."
        )
    return (
        f"Yana bir bor salom! Agar hali ham qiziqsangiz, ism-familiyangiz va "
        f"telefon raqamingizni qoldiring — mutaxassislarimiz bog'lanadi 🙌"
    )


def _send_followup_to_customer(store, customer, stage: int) -> bool:
    """Bitta mijozga follow-up yuboradi, muvaffaqiyatli bo'lsa True qaytaradi."""
    from apps.chat.models import ChatMessage
    from apps.chat.senders import send_reply

    tier = _determine_followup_tier(store, customer)
    course = _guess_discussed_course(store, customer)
    text = _build_followup_text(tier, stage, store, course)

    sent = send_reply(
        store=store,
        platform=customer.platform,
        chat_id=customer.platform_user_id,
        text=text,
        customer=customer,
    )
    if not sent:
        return False

    ChatMessage.objects.create(
        store=store,
        customer=customer,
        message_id=f"followup_{stage}_{uuid.uuid4().hex[:10]}",
        platform=customer.platform,
        role=ChatMessage.Role.ASSISTANT,
        content=text,
        processing_status=ChatMessage.ProcessingStatus.COMPLETED,
    )
    return True


def _process_stage(store, stage: int, delay_hours: int, now, lookback_cutoff) -> tuple[int, int]:
    from apps.customers.models import Customer

    threshold = now - timedelta(hours=delay_hours)
    prev_stage = stage - 1

    # ⚠️ Faqat: (a) hali Lead bermagan mijozlar — Lead allaqachon bergan
    # mijoz bilan operator o'zi bog'lanadi, ikkinchi marta avtomatik
    # xabar yuborish ortiqcha va spam bo'lardi; (b) AI hali faol (inson
    # operatorga o'tkazilmagan); (c) bloklanmagan; (d) avvalgi follow-up'ga
    # ANIQ rad javobi bermagan — "yo'q" degan mijozga яна eslatma yuborish
    # spam bo'lardi (apps/webhooks/tasks.py'da aniqlanadi/belgilanadi).
    candidates = Customer.objects.filter(
        store=store,
        follow_up_stage=prev_stage,
        follow_up_declined=False,
        ai_active=True,
        is_blocked=False,
        last_message_at__gte=lookback_cutoff,
    ).exclude(leads__isnull=False)

    # ⚠️ Do'kon egasi o'z botini sinab ko'rish uchun yozib qo'yishi mumkin —
    # bu "mijoz" emas, shuning uchun unga avtomatik follow-up yuborilmasligi
    # kerak (xuddi shu bug klassi apps/orders/views.py'da LeadViewSet.stats'da
    # ham topilgan va tuzatilgan edi).
    if store.tg_owner_chat_id:
        candidates = candidates.exclude(platform_user_id=store.tg_owner_chat_id)

    if stage == 1:
        # 1-bosqich — mijozning ASL sukut vaqtidan (oxirgi xabaridan) hisoblanadi.
        candidates = candidates.filter(last_message_at__lte=threshold)
    else:
        # ⚠️ BUG FIX: 2-bosqich (va undan keyingisi) avval ham
        # `last_message_at`dan hisoblanardi — bu esa mijoz ANCHA OLDIN
        # (masalan 2 kun) jim qolgan bo'lsa (masalan bu vazifa birinchi
        # marta deploy qilinganda), bitta ishga tushishning O'ZIDA:
        # 1-bosqich yuborilib `follow_up_stage`ni yangilashi bilanoq,
        # xuddi shu ishga tushishda 2-bosqich sharti ham (last_message_at
        # 24 soatdan eski) allaqachon bajarilgan bo'lib, ikkala xabar
        # BIR NECHA SONIYA farq bilan ketib qolishiga sabab bo'lgan
        # (jonli holatda aniqlandi). Endi 2-bosqich mijozning asl sukut
        # vaqtidan emas, 1-BOSQICH HAQIQATDA YUBORILGAN vaqtdan
        # hisoblanadi — bu haqiqiy vaqt o'tishini kafolatlaydi.
        candidates = candidates.filter(
            follow_up_last_sent_at__isnull=False,
            follow_up_last_sent_at__lte=threshold,
        )

    sent_count = 0
    failed_count = 0

    for customer in candidates:
        try:
            if _send_followup_to_customer(store, customer, stage):
                sent_count += 1
            else:
                failed_count += 1
                logger.warning(
                    f"[Follow-up Task] Yuborilmadi (platforma xatosi) | "
                    f"store={store.name} | customer={customer.id} | stage={stage}"
                )
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[Follow-up Task] Kutilmagan xato | store={store.name} | "
                f"customer={customer.id} | stage={stage} | {e}",
                exc_info=True,
            )
        else:
            # ⚠️ Muvaffaqiyatsiz (platforma xatosi) bo'lsa ham bosqichni
            # oshiramiz — aks holda doimiy xato beradigan mijoz (masalan
            # botni bloklagan) HAR safar qayta-qayta urinilaverib,
            # hisoblagich abadiy shu joyda tiqilib qolardi. `follow_up_last_sent_at`
            # ham har doim yangilanadi — keyingi bosqich shundan hisoblanadi.
            Customer.objects.filter(id=customer.id).update(
                follow_up_stage=stage, follow_up_last_sent_at=now,
            )

    return sent_count, failed_count


def _is_quiet_hours(now) -> bool:
    """
    Hozir tungi (eslatma yuborilmaydigan) soatlarmi? (Asia/Tashkent vaqti bilan)

    ⚠️ Avval tungi cheklov yo'q edi: mijoz kechqurun 21:00 da jim qolsa, 1-eslatma
    6 soatdan keyin, ya'ni soat 03:00 da ketardi. Endi shu oraliqda hech narsa
    yuborilmaydi — eslatma ertalab (09:00 dan keyin) ketadi, chunki mijozning jim
    qolgani (last_message_at) o'sha vaqtgacha o'zgarmaydi.
    """
    from django.conf import settings

    start = int(getattr(settings, "FOLLOW_UP_QUIET_START_HOUR", 21))
    end = int(getattr(settings, "FOLLOW_UP_QUIET_END_HOUR", 9))
    if start == end:
        return False
    hour = timezone.localtime(now).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end     # yarim tundan o'tadigan oraliq (21 -> 09)


@shared_task(
    name="apps.customers.tasks.send_followup_messages",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    ignore_result=False,
)
def send_followup_messages(self):
    """
    Do'kon sozlagan kechikish bilan (standart 6 soat / 24 soat),
    javobsiz qolgan mijozlarga navbatma-navbat (1-bosqich, keyin
    2-bosqich) avtomatik eslatma yuboradi, so'ng to'xtaydi (spam yo'q).

    Celery Beat orqali har 15 daqiqada ishga tushadi.
    """
    from apps.stores.models import Store

    now = timezone.now()
    if _is_quiet_hours(now):
        return {"sent": 0, "failed": 0, "skipped": "quiet_hours"}
    lookback_cutoff = now - timedelta(days=_MAX_LOOKBACK_DAYS)

    stores = Store.objects.filter(
        is_active=True, is_deleted=False, ai_active=True, follow_up_enabled=True,
    )

    total_sent = 0
    total_failed = 0

    for store in stores:
        for stage, delay_hours in (
            (1, store.follow_up_delay_1_hours),
            (2, store.follow_up_delay_2_hours),
        ):
            sent, failed = _process_stage(store, stage, delay_hours, now, lookback_cutoff)
            total_sent += sent
            total_failed += failed

    if total_sent or total_failed:
        logger.info(
            f"[Follow-up Task] Yakunlandi: ✓ {total_sent} yuborildi | ✗ {total_failed} xato"
        )

    return {"sent": total_sent, "failed": total_failed}
