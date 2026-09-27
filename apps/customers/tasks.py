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

_FOLLOWUP_TEMPLATES = {
    1: {
        "with_course": "Assalomu alaykum! {course} kursi bo'yicha savollaringiz hali ham dolzarbmi? Yordam bera olsam, mamnuniyat bilan javob beraman 😊",
        "generic": "Assalomu alaykum! Savollaringiz bo'lsa, bemalol yozing — yordam berishdan mamnunmiz 😊",
    },
    2: {
        "with_course": "Salom! {course} kursimiz hali ham qiziqtiradimi? Ro'yxatdan o'tish yoki qo'shimcha ma'lumot uchun istalgan vaqtda yozishingiz mumkin 🙌",
        "generic": "Salom! Bizning xizmatlarimiz haligacha qiziqtiradimi? Savollaringiz bo'lsa yozing, albatta yordam beramiz 🙌",
    },
}


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


def _build_followup_text(stage: int, course: str | None) -> str:
    templates = _FOLLOWUP_TEMPLATES[stage]
    if course:
        return templates["with_course"].format(course=course)
    return templates["generic"]


def _send_followup_to_customer(store, customer, stage: int) -> bool:
    """Bitta mijozga follow-up yuboradi, muvaffaqiyatli bo'lsa True qaytaradi."""
    from apps.chat.models import ChatMessage
    from apps.chat.senders import send_reply

    course = _guess_discussed_course(store, customer)
    text = _build_followup_text(stage, course)

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
    # operatorga o'tkazilmagan); (c) bloklanmagan.
    candidates = Customer.objects.filter(
        store=store,
        follow_up_stage=prev_stage,
        ai_active=True,
        is_blocked=False,
        last_message_at__gte=lookback_cutoff,
    ).exclude(leads__isnull=False)

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
