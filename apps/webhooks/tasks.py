"""
Webhook Celery Tasks — To'liq implementatsiya (4-qadam).

Ishlash oqimi:
1. Do'konni DB'dan olish
2. Mijozni topish / yaratish
3. Xabarni DB'ga saqlash (idempotency)
4. Gemini AI'ga jo'natish → javob olish
5. AI javobini DB'ga saqlash
6. Javobni platforma orqali yuborish
7. Lid aniqlangan bo'lsa → Lead yaratish + egasiga xabarnoma

SaaS qoidalari:
- max_retries=3 + eksponensial backoff
- acks_late=True → task yo'qolmaydi
- Har bir do'kon alohida Celery queue'da
"""
import logging
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError

logger = logging.getLogger("apps.webhooks")


def _is_message_addressed_to_bot(raw_payload: dict, store) -> bool:
    """
    Guruh xabari botga aniq qaratilganmi (@mention yoki uning xabariga
    reply)? Faqat shu holatda botning o'zi "javob berish kerak" deb
    hisoblanadi — oddiy guruh suhbatiga (bot haqida bo'lmagan) aralashib
    ketmasligi uchun.
    """
    if not raw_payload or not isinstance(raw_payload, dict):
        return False
    inner = raw_payload.get("message", {}) or {}

    bot_username = (getattr(store, "tg_bot_username", "") or "").lstrip("@").lower()
    original_text = (inner.get("text") or "").strip()
    if bot_username and original_text.lower().startswith(f"@{bot_username}"):
        return True

    # Bot tokenining "<raqamli_id>:<hash>" formatidagi birinchi qismi —
    # botning o'z Telegram foydalanuvchi ID'si (alohida saqlash shart emas).
    bot_token = getattr(store, "tg_bot_token", "") or ""
    bot_id = bot_token.split(":")[0] if ":" in bot_token else ""
    reply_to = inner.get("reply_to_message")
    if bot_id and reply_to and str(reply_to.get("from", {}).get("id", "")) == bot_id:
        return True

    return False


def _send_command_reply(store, customer, platform, chat_id, text, parse_mode="HTML", reply_markup=None, is_group_message=False, reply_to_message_id=None):
    """
    Buyruq (/start, /dashboard, /help) javobini yuboradi VA uni
    ChatMessage sifatida (role=ASSISTANT) saqlaydi.

    ⚠️ BUG FIX: avval bu turdagi statik javoblar faqat Telegram'ga
    to'g'ridan-to'g'ri yuborilardi, bazaga HECH QACHON yozilmasdi.
    ChatThreadListView'dagi "unread_count" esa aynan "oxirgi ASSISTANT
    xabaridan keyingi USER xabarlari soni" formulasi bilan hisoblanadi —
    demak mijoz "/start" yozganda, bot chiroyli javob bergan bo'lsa ham,
    bazada bu ko'rinmagani uchun hisoblagich HECH QACHON nolga
    tushmasdi. Natijada TWA Inbox'da "N ta yangi" belgisi mijoz
    xabarini ochib o'qigandan keyin ham, hatto sahifani yangilagandan
    keyin ham DOIM qaytib chiqaverardi (jonli testda tasdiqlandi).
    """
    from apps.chat.senders import send_telegram_message
    from apps.chat.models import ChatMessage
    import uuid

    sent = send_telegram_message(
        bot_token=store.tg_bot_token,
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
    )
    if sent and customer is not None:
        ChatMessage.objects.create(
            store=store,
            customer=customer,
            message_id=f"cmd_reply_{uuid.uuid4().hex[:10]}",
            bot_token=store.tg_bot_token,
            chat_id=str(chat_id),
            platform=platform,
            role=ChatMessage.Role.ASSISTANT,
            content=text,
            processing_status=ChatMessage.ProcessingStatus.COMPLETED,
            is_group_message=is_group_message,
        )
    return sent


@shared_task(
    bind=True,
    name="apps.webhooks.tasks.process_incoming_message",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=300,        # 5 daqiqa hard limit
    soft_time_limit=240,   # 4 daqiqa soft limit
)
def process_incoming_message(
    self,
    store_id: str,
    platform: str,
    message_id: str,
    sender_id: str,
    sender_username: str,
    text: str,
    chat_id: str,
    raw_payload: dict,
    sender_display_name: str = "",
    chat_type: str = "private",
):
    """
    Webhook'dan qabul qilingan xabarni qayta ishlaydi.

    Bu task webhook view'dan chaqiriladi va:
    - AI dan javob oladi (Gemini)
    - Javobni platforma orqali yuboradi
    - Lid aniqlansa — Lead yaratadi va egasiga xabar yuboradi
    """
    from apps.stores.models import Store
    from apps.customers.models import Customer
    from apps.chat.models import ChatMessage
    from apps.chat.ai_service import get_ai_response
    from apps.chat.senders import send_reply
    from apps.chat.lead_service import create_lead_from_ai_data, notify_store_owner, sync_lead_to_bitrix24, sync_lead_to_google_sheets

    logger.info(
        f"[Task] Boshlandi | store={store_id[:8]} | "
        f"platform={platform} | msg_id={message_id} | "
        f"task={self.request.id}"
    )

    is_group = chat_type in ("group", "supergroup")

    try:
        # ── 1. Do'konni olish ────────────────────────────────────────
        try:
            store = Store.objects.select_related("owner").get(
                id=store_id,
                is_active=True,
                is_deleted=False,
            )
        except Store.DoesNotExist:
            logger.error(f"[Task] Do'kon topilmadi: store_id={store_id}")
            return  # Retry qilmaymiz

        # ── 2. Mijozni topish / yaratish ──────────────────────────────
        customer, is_new_customer = Customer.get_or_create_from_platform(
            store=store,
            platform=platform,
            platform_user_id=sender_id,
            username=sender_username,
            display_name=sender_display_name,
        )
        if is_new_customer:
            logger.info(f"[Task] Yangi mijoz: {customer}")

        # ⚠️ BUG FIX: avval mijozning haqiqiy ismi (Telegram profilidagi
        # first_name+last_name) HECH QACHON alohida saqlanmasdi — faqat
        # @username `Customer.username`ga yozilardi, `full_name` esa faqat
        # (agar umuman ishlasa ham) buyurtma yaratilgandan keyingina
        # to'ldirilardi. Natijada Inbox'da ismi o'rniga @username (masalan
        # "f6jbq") chiqib qolardi. Endi profildagi ism mavjud bo'lsa va
        # `full_name` hali bo'sh bo'lsa, HAR BIR xabarda (buyurtma kutmasdan)
        # darhol to'ldiriladi.
        if sender_display_name and not customer.full_name:
            customer.full_name = sender_display_name
            customer.save(update_fields=["full_name", "updated_at"])

        # ── 3. Xabarni DB'ga saqlash (idempotency) ────────────────────
        # ⚠️ `customer` lookup'ning bir qismi bo'lishi SHART — message_id
        # faqat bitta suhbat ichida unikal, `customer`siz qidiruv boshqa
        # mijozning (bir xil store+platform'dagi) xabarini xato ushlab
        # olib, dublikat deb hisoblab qo'yardi (ChatMessage.Meta'ga qarang).
        chat_message, msg_created = ChatMessage.all_objects.get_or_create(
            store=store,
            customer=customer,
            message_id=message_id,
            platform=platform,
            bot_token=store.tg_bot_token,
            chat_id=str(chat_id),
            defaults={
                "role": ChatMessage.Role.USER,
                "content": text,
                "raw_payload": raw_payload,
                "processing_status": ChatMessage.ProcessingStatus.PROCESSING,
                "celery_task_id": self.request.id,
                "is_group_message": is_group,
            },
        )

        if not msg_created and chat_message.processing_status == ChatMessage.ProcessingStatus.COMPLETED:
            # Allaqachon muvaffaqiyatli yakunlangan — dublikat
            logger.info(
                f"[Task] Dublikat xabar, skip: msg_id={message_id}"
            )
            return

        # ── 4. Admin (Do'kon Egasi) vs Mijozni tekshirish va ajratish ──────
        is_admin = False
        cmd_text = text.strip().lower()

        # ⚠️ Do'kon egasi rejimi (Dashboard tugmasi, Biznes Analitika
        # Assistenti) FAQAT shaxsiy chatda ishlaydi. Agar buni guruhda ham
        # yoqib qo'ysak, ega o'zining bog'langan (ommaviy) guruhida oddiy
        # xabar yozganida bot uni "xo'jayin" deb bilib, o'sha yerga ichki
        # analitika/dashboard havolasini ochiq yuborib yuborishi mumkin edi.
        # Do'kon egasi ID allaqachon biriktirilgan va xuddi o'sha odam yozayapti → admin
        if not is_group and store.tg_owner_chat_id and str(store.tg_owner_chat_id) == str(sender_id):
            is_admin = True

        # admin_ deep-link: /start admin_<store_uuid> — yangi egani biriktirish
        # (guruh xabarlari uchun bu allaqachon views.py'da ushlanadi, bu yerga
        # yetib kelmasligi kerak — `not is_group` qo'shimcha himoya sifatida)
        elif not is_group and cmd_text.startswith("/start"):
            parts = text.strip().split()
            if len(parts) > 1 and parts[1].startswith("admin_"):
                if store.tg_owner_chat_id:
                    # Boshqa egaga biriktirilgan — bloklash
                    logger.warning(f"[Security] Begona foydalanuvchi ({sender_id}) admin havolasini ishlatishga urindi: store={store.name}")
                    _send_command_reply(
                        store, customer, platform, chat_id,
                        text="🚫 <b>Xavfsizlik ogohlantirishi:</b> Ushbu do'kon allaqachon o'z egasiga biriktirilgan! Siz ushbu do'kon paneliga kira olmaysiz.",
                    )
                    ChatMessage.objects.filter(id=chat_message.id).update(
                        processing_status=ChatMessage.ProcessingStatus.COMPLETED
                    )
                    return
                else:
                    # ⚠️ BUG FIX: avval bu yerda faqat "TARGET do'konning
                    # egasi bormi" tekshirilardi — "bu foydalanuvchi
                    # allaqachon BOSHQA bir do'konning egasimi" tekshirilmasdi.
                    # `tg_owner_chat_id` maydonida unique cheklov borligi
                    # uchun (bitta Telegram akkount faqat bitta do'konga ega
                    # bo'lishi kerak), bunday holatda `.save()` IntegrityError
                    # bilan qulab, task butunlay muvaffaqiyatsiz tugardi va
                    # foydalanuvchi HECH QANDAY javob ololmasdi (jonli testda
                    # aniqlandi). Endi oldindan tekshirilib, tushunarli xabar
                    # bilan rad etiladi.
                    from apps.stores.models import Store as _Store

                    existing_owned_store = _Store.objects.filter(
                        tg_owner_chat_id=str(sender_id)
                    ).exclude(id=store.id).first()

                    if existing_owned_store:
                        logger.warning(
                            f"[Task] Foydalanuvchi ({sender_id}) allaqachon "
                            f"'{existing_owned_store.name}' do'konining egasi — "
                            f"'{store.name}'ga biriktirib bo'lmadi"
                        )
                        _send_command_reply(
                            store, customer, platform, chat_id,
                            text=(
                                f"🚫 Siz allaqachon <b>{existing_owned_store.name}</b> do'konining "
                                f"egasisiz. Bitta Telegram akkount faqat bitta do'konga ega bo'la oladi."
                            ),
                        )
                        ChatMessage.objects.filter(id=chat_message.id).update(
                            processing_status=ChatMessage.ProcessingStatus.COMPLETED
                        )
                        return

                    try:
                        store.tg_owner_chat_id = str(sender_id)
                        store.save(update_fields=["tg_owner_chat_id"])
                    except IntegrityError:
                        # Poyga holati: ikkita so'rov bir vaqtda yuqoridagi
                        # tekshiruvdan o'tib qolishi mumkin — himoya sifatida.
                        logger.warning(
                            f"[Task] Egani biriktirishda poyga holati: "
                            f"store={store.name}, sender={sender_id}"
                        )
                        _send_command_reply(
                            store, customer, platform, chat_id,
                            text="🚫 Siz allaqachon boshqa do'konning egasisiz. Bitta akkount faqat bitta do'konga ega bo'la oladi.",
                        )
                        ChatMessage.objects.filter(id=chat_message.id).update(
                            processing_status=ChatMessage.ProcessingStatus.COMPLETED
                        )
                        return

                    logger.info(f"[Task] Do'kon egasi biriktirildi: store={store.name}, owner_tg_id={sender_id}")
                    is_admin = True


        if cmd_text.startswith("/start") or cmd_text.startswith("/dashboard") or cmd_text in ["start", "dashboard"]:
            if is_admin:
                logger.info("[Task] Admin /start keldi -> Dashboard TWA tugmasi yuborilmoqda")
                welcome_text = (
                    f"<b>Assalomu alaykum, Xurmatli {store.name} Admini! 👑</b>\n\n"
                    f"Boshqaruv paneli orqali kelgan buyurtmalarni ko'rish, katalogingizni boshqarish hamda "
                    f"AI bot yo'riqnomalarini sozlash uchun pastdagi tugmani bosing 👇"
                )
                # TWA URL: PUBLIC_URL .env dan olinadi (ngrok yoki production domain)
                public_url = getattr(settings, "PUBLIC_URL", "").rstrip("/")
                if not public_url:
                    logger.error("PUBLIC_URL sozlanmagan! TWA havolasi yaratilmaydi.")
                    ChatMessage.objects.filter(id=chat_message.id).update(
                        processing_status=ChatMessage.ProcessingStatus.COMPLETED
                    )
                    return
                twa_url = f"{public_url}/app/"
                # NOTE: on a free ngrok tunnel, Telegram's Mini App webview will
                # hit ngrok's browser-warning interstitial instead of the real
                # dashboard — there's no header/query-param workaround for a
                # webview we don't control. Switch tunnel providers or upgrade
                # ngrok to remove that interstitial; this button itself is fine.
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {
                                "text": "📊 Boshqaruv Paneli",
                                "web_app": {"url": twa_url}
                            }
                        ]
                    ]
                }
                logger.info(f"[Task] TWA URL: {twa_url}")
                _send_command_reply(
                    store, customer, platform, chat_id,
                    text=welcome_text,
                    reply_markup=reply_markup,
                    is_group_message=is_group,
                    reply_to_message_id=message_id if is_group else None,
                )

                # Chat menu tugmasini ham shu Do'kon Egasi uchun "Dashboard"
                # Web App tugmasiga almashtiramiz — shunda pastdagi umumiy
                # "Menu" yozuvi o'rniga to'g'ridan-to'g'ri dashboardni ochadigan
                # tugma chiqadi (faqat shu ega uchun, chat_id bilan cheklangan —
                # oddiy mijozlar hali ham standart "Menu"ni ko'radi).
                try:
                    import httpx as _httpx
                    with _httpx.Client(timeout=10.0) as _client:
                        _res = _client.post(
                            f"https://api.telegram.org/bot{store.tg_bot_token}/setChatMenuButton",
                            json={
                                "chat_id": int(chat_id),
                                "menu_button": {
                                    "type": "web_app",
                                    "text": "Dashboard",
                                    "web_app": {"url": twa_url},
                                },
                            },
                        )
                        if not _res.json().get("ok"):
                            logger.warning(f"[Task] Menu button o'rnatilmadi: {_res.json()}")
                except Exception as e:
                    logger.warning(f"[Task] Menu button o'rnatishda xato: {e}")
            else:
                logger.info("[Task] Mijoz /start keldi -> TWA tugmasiz do'rtona qutlov yuborilmoqda")

                # ⚠️ BUG FIX: avval bu matn har doim e-commerce'ga xos
                # ("mahsulotlar, razmerlar, yetkazib berish") so'zlar bilan
                # qattiq yozilgan edi — Education yoki Services turidagi
                # do'konlarda ham xuddi shu matn chiqib, mos kelmasdi
                # (masalan o'quv markazi uchun "razmer" ma'nosiz). Endi
                # do'konning category_type'iga qarab mos matn tanlanadi.
                category = getattr(store, "category_type", "education") or "education"
                category_intros = {
                    "education": "Kurslarimiz, dars jadvali, narxlar va Bepul Sinov Darsi bo'yicha savolingiz bo'lsa",
                    "services": "Xizmatlarimiz, ustalarimiz, narxlar va vaqt band qilish bo'yicha savolingiz bo'lsa",
                }
                intro = category_intros.get(category, category_intros["education"])

                customer_text = (
                    f"<b>Assalomu alaykum! {store.name} rasmiy sotuv botiga xush kelibsiz! 😊</b>\n\n"
                    f"{intro}, shunchaki xabaringizni yozing. AI sotuvchimiz yordam beradi."
                )
                _send_command_reply(
                    store, customer, platform, chat_id,
                    text=customer_text,
                    is_group_message=is_group,
                    reply_to_message_id=message_id if is_group else None,
                )

            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        if cmd_text.startswith("/help") or cmd_text in ["help", "yordam"]:
            logger.info("[Task] /help buyrug'i keldi -> Yordam ko'rsatmasi yuborilmoqda")
            help_text = (
                f"<b>❓ Yordam va Ko'rsatmalar — {store.name}</b>\n\n"
                f"1. 💬 <b>Savol berish</b>: Shunchaki xabaringizni yozing, AI sotuvchimiz darhol javob beradi.\n"
                f"2. 🛍️ <b>Buyurtma berish</b>: Mahsulot nomini, ismingiz, telefon va manzilingizni yozsangiz AI avtomatik buyurtma oladi.\n"
                f"3. 📊 <b>Dashboard</b>: Pastdagi tugma orqali do'kon boshqaruv paneliga kiring."
            )
            _send_command_reply(
                store, customer, platform, chat_id,
                text=help_text,
                is_group_message=is_group,
                reply_to_message_id=message_id if is_group else None,
            )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ── 4.5. Media Persistence (Rasm/Audio Saqlash Pipeline) ────────
        # Webhook payload'da media url yoki Telegram voice bo'lsa fonda
        # saqlash taskini chaqiramiz
        has_voice = False
        if raw_payload and isinstance(raw_payload, dict):
            inner_message = raw_payload.get("message", {})
            has_attachments = bool(inner_message.get("attachments"))
            has_voice = bool(inner_message.get("voice"))
            if has_attachments or has_voice or raw_payload.get("media_url"):
                try:
                    download_and_store_chat_media.delay(str(chat_message.id))
                except Exception as e:
                    logger.warning(f"Media download task chaqirishda xato: {e}")

        # ── 4.55. Ovozli xabar — AI'ga yubormasdan, aniq javob beramiz ──
        # ⚠️ AI hozircha ovozni tushunmaydi — bu bosqichgacha `text` faqat
        # "🎙️ Ovozli xabar (Ns)" degan belgi matni (parsers.py'da
        # yaratiladi), haqiqiy gap emas. Buni Gemini'ga yuborish AI'ni
        # eshitmagan narsasiga ishonch bilan javob berishga (hallucination)
        # majbur qilardi — bu esa loyihaning "AI hech qachon o'ylab
        # topmaydi" qoidasiga zid. Fayl baribir yuqorida saqlanadi,
        # operator dashboard'da eshitib qo'lda javob bera oladi.
        if has_voice:
            logger.info(f"[Task] Ovozli xabar keldi -> AI'ga yuborilmadi, matn bilan yozishni so'radik | store={store.name}")
            voice_reply_text = (
                "Kechirasiz, hozircha ovozli xabarlarni tushunmayman 🙏\n"
                "Iltimos, savolingizni matn bilan yozib yuboring."
            )
            _send_command_reply(
                store, customer, platform, chat_id,
                text=voice_reply_text,
                is_group_message=is_group,
                reply_to_message_id=message_id if is_group else None,
            )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ── 4.56. Guruhda do'kon egasi YOKI ro'yxatdagi xodimi (sotuv
        # menejeri) o'zi yozganda — AI sotuv javobi bermasin ────────────
        # ⚠️ `is_admin` guruhda ATAYLAB yoqilmagan (yuqoridagi izohga
        # qarang — ichki boshqaruv havolasi guruhda ochiq ko'rinib
        # qolmasligi uchun). Lekin bu degani egasi (yoki uning xodimi)
        # guruhda oddiy mijoz sifatida to'liq AI sotuv taklifini olishi
        # kerak degani emas — foydalanuvchi buni to'g'ridan-to'g'ri
        # ta'kidladi ("nega men guruhda owner'man lekin bot menga malumot
        # beryabdi", "gurpada 3-4 ta sotuv menejeri bolsa ularga ham
        # sotishga urinadimi?"). Xodimlar ro'yxati — StoreStaffMember
        # (apps/stores/models.py); bu TO'LIQ rol/TWA-ruxsat tizimi emas,
        # faqat AI'dan ajratish uchun.
        #
        # ⚠️ Qisqa "tanidim" tasdiqi ham FAQAT botga aniq murojaat
        # qilganda (@mention yoki reply) yuboriladi — aks holda egasi/
        # xodim guruhda mijozlar bilan oddiy gaplashganda bot har safar
        # aralashib, suhbatni bezovta qilardi.
        is_recognized_owner = bool(store.tg_owner_chat_id) and str(store.tg_owner_chat_id) == str(sender_id)
        is_staff = False
        if is_group and not is_recognized_owner and sender_username:
            from apps.stores.models import StoreStaffMember
            is_staff = StoreStaffMember.objects.filter(
                store=store, tg_username__iexact=sender_username
            ).exists()

        if is_group and (is_recognized_owner or is_staff):
            addressed_to_bot = _is_message_addressed_to_bot(raw_payload, store)
            who = "do'kon egasi" if is_recognized_owner else "xodim"
            logger.info(
                f"[Task] Guruhda {who}ning o'zi yozdi — AI sotuv "
                f"javobi berilmadi | store={store.name} | botga qaratilganmi={addressed_to_bot}"
            )
            if addressed_to_bot:
                ack_text = (
                    "👋 Sizni do'kon egasi sifatida taniyman, shuning uchun savdo taklifi qilmayman — bu yerda faqat mijozlaringiz yozganda AI ishga tushadi."
                    if is_recognized_owner else
                    "👋 Sizni jamoa xodimi sifatida taniyman, shuning uchun savdo taklifi qilmayman — bu yerda faqat mijozlar yozganda AI ishga tushadi."
                )
                _send_command_reply(
                    store, customer, platform, chat_id,
                    text=ack_text,
                    is_group_message=is_group,
                    reply_to_message_id=message_id,
                )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ⚠️ Qasddan MENTION/REPLY talab qilinmaydi — mijoz botni
        # belgilashni unutsa ham, haqiqiy savoliga javob olishi kerak
        # (foydalanuvchi buni ANIQ tanladi: qulaylik xavfsizlikdan
        # ustun). Kimga qaratilganini AI o'zi (system prompt'dagi (a)
        # qoidasi orqali) hal qiladi. O'rniga, pastda AI javobini
        # YUBORISHDAN OLDIN — inson (ega/xodim) ALLAQACHON shu mijozga
        # javob berib ulgurgan bo'lsa, tekshirib, AI javobini bekor
        # qilamiz (pastdagi 5.6-band, "insonning tuzatishiga hurmat" tekshiruvi).

        # ── 4.6. Operator Handoff Trigger (Mijoz Insoniy Operator So'raganda) ─
        HANDOFF_KEYWORDS = ["operator", "odam bilan", "insonga", "call center", "menejer", "human"]
        is_handoff_requested = any(kw in cmd_text for kw in HANDOFF_KEYWORDS)

        if is_handoff_requested:
            logger.info(f"[Task] Mijoz operator so'radi! Handoff rejimiga o'tilmoqda: customer={customer}")
            customer.ai_active = False
            customer.save(update_fields=["ai_active", "updated_at"])

            # Egasiga Telegram xabarnomasi yuboramiz
            if store.tg_owner_chat_id:
                from apps.chat.senders import send_telegram_message
                public_url = getattr(settings, "PUBLIC_URL", "").rstrip("/")
                if not public_url:
                    logger.error("PUBLIC_URL sozlanmagan! Operator xabarnomasi TWA havolasisiz yuboriladi.")
                twa_url = f"{public_url}/app/" if public_url else ""
                owner_alert = (
                    f"🚨 <b>OPERATOR ARALASHUVI KERAK!</b>\n\n"
                    f"🏪 Do'kon: <b>{store.name}</b>\n"
                    f"👤 Mijoz: <b>{customer.full_name or customer.username or customer.platform_user_id}</b>\n"
                    f"📲 Platforma: <b>{platform.upper()}</b>\n"
                    f"💬 Xabar: <i>\"{text}\"</i>\n\n"
                    f"<i>AI bot vaqtincha to'xtatildi. Operator javob berishi kutilmoqda.</i>"
                )
                reply_markup = None
                if twa_url:
                    reply_markup = {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "💬 Chatni Ochish (Dashboard)",
                                    "web_app": {"url": twa_url}
                                }
                            ]
                        ]
                    }
                send_telegram_message(
                    bot_token=store.tg_bot_token,
                    chat_id=store.tg_owner_chat_id,
                    text=owner_alert,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )

            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ── 4.7. AI bot faolligini tekshirish (Global yoki Handoff) ─────
        if not store.ai_active or not getattr(customer, "ai_active", True):
            logger.info(
                f"[Task] AI bot nofaol (handoff holati) | store={store.name} | "
                f"customer={customer.full_name or customer.username or customer.platform_user_id} | "
                f"store_ai_active={store.ai_active} | "
                f"customer_ai_active={getattr(customer, 'ai_active', True)}"
            )
            # Dastlabki xabarni COMPLETED deb belgilaymiz va javob qaytarmaymiz
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ── 5. Gemini AI'ga jo'natish ──────────────────────────────────
        logger.info(
            f"[Task] AI chaqirilmoqda | store={store.name} | "
            f"model={store.ai_model}"
        )

        ai_response = get_ai_response(
            store=store,
            customer=customer,
            user_message=text,
            is_group=is_group,
        )

        logger.info(
            f"[Task] AI javob olindi | "
            f"tokens={ai_response.tokens_used} | "
            f"has_lead={ai_response.has_lead}"
        )

        # ── 5.2. AI umuman javob berolmagan holat (masalan Gemini kvotasi
        # tugagan) — mijozga "texnik muammo" xabarini HECH KIMGA (ayniqsa
        # guruhda — bir nechta odam ko'radi) yubormaymiz. Buning o'rniga
        # xabarni "FAILED" deb belgilab (TWA Inbox'da ko'rinib, qo'lda
        # javob berish mumkin bo'lishi uchun), do'kon egasiga BIR MARTA
        # (soatiga bir marta cooldown bilan — takror-takror bezovta
        # qilmaslik uchun) ogohlantirish yuboramiz.
        # ⚠️ GEMINI_API_KEY barcha do'konlar uchun UMUMIY (Single Master
        # Bot bilan bir xil model) — demak bitta do'kon uchun kvota
        # tugashi ODATDA hammasiga birdan ta'sir qiladi.
        if ai_response.is_error:
            logger.warning(
                f"[Task] AI xato holatida — mijozga javob yuborilmadi | "
                f"store={store.name} | error_type={ai_response.error_type}"
            )
            error_reason = ai_response.error_type or "nomalum xato"
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.FAILED,
                error_message=f"AI javob berolmadi ({error_reason})",
            )
            if store.tg_owner_chat_id and store.tg_bot_token:
                cooldown_key = f"ai_error_alert_sent:{store.id}:{ai_response.error_type}"
                if cache.add(cooldown_key, True, timeout=60 * 60):
                    from apps.chat.senders import send_telegram_message as _send_owner_alert
                    if ai_response.error_type == "quota":
                        owner_text = (
                            "🚨 <b>AI TO'XTAB QOLDI — kunlik so'rov limiti tugadi!</b>\n\n"
                            "Gemini AI'ning bepul kunlik limiti tugagani sabab, bot hozir "
                            "mijozlarga AVTOMATIK javob berolmayapti. Mijozlarning xabarlari "
                            "TWA Inbox'da saqlanmoqda — hozircha qo'lda javob bering.\n\n"
                            "Doimiy hal qilish uchun: Google AI Studio'da pulli rejaga o'ting."
                        )
                    else:
                        owner_text = (
                            "🚨 <b>AI vaqtincha javob berolmayapti (texnik xato)!</b>\n\n"
                            "Mijozlarning xabarlari TWA Inbox'da saqlanmoqda — hozircha "
                            "qo'lda javob bering. Muammo davom etsa, birozdan so'ng qayta tekshiring."
                        )
                    _send_owner_alert(
                        bot_token=store.tg_bot_token,
                        chat_id=store.tg_owner_chat_id,
                        text=owner_text,
                        parse_mode="HTML",
                    )
            return

        # ── 5.3. Guruhda AI ataylab "javob yozish shart emas" deb tanladi
        # (mijoz shunchaki reaksiya/izoh yozgan, haqiqiy savol emas) —
        # hech narsa yubormasdan, xabarni COMPLETED deb belgilab chiqamiz.
        if ai_response.is_silent:
            logger.info(
                f"[Task] AI reaksiyaga javob yozmaslikni tanladi (NO_REPLY) | "
                f"store={store.name} | msg_id={message_id}"
            )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
            return

        # ── 5.5. AI javobini DB'ga saqlash ─────────────────────────────
        #
        # ⚠️ BUG FIX (poyga holati / race condition): avval bu yerda oddiy
        # `.create()` ishlatilardi. Telegram bir xil update'ni ba'zan qayta
        # yuborishi (yoki Celery'ning `acks_late=True` sozlamasi worker
        # o'lib qolganda taskni qayta ishga tushirishi) natijasida IKKI
        # worker BIR XIL xabarni parallel qayta ishlashi mumkin edi.
        # `message_id=f"ai_resp_{message_id}"` — har doim bir xil, statik
        # qiymat bo'lgani uchun, ikkinchi (yutqazgan) worker bazadagi
        # unique cheklovga (store, message_id, platform) urilib
        # `IntegrityError` bilan qulardi — bu esa uni 3 marta qayta urinib
        # ko'rishga (har birida qimmat Gemini so'rovi bilan!) va oxir-
        # oqibat ALLAQACHON MUVAFFAQIYATLI yakunlangan xabarni FAILED deb
        # belgilab qo'yishga olib kelardi. Endi `get_or_create` — ikkinchi
        # worker jimgina "allaqachon bor" deb bilib, hech narsa qilmay
        # to'xtaydi.
        ai_message, ai_message_created = ChatMessage.objects.get_or_create(
            store=store,
            customer=customer,
            message_id=f"ai_resp_{message_id}",
            platform=platform,
            bot_token=store.tg_bot_token,
            chat_id=str(chat_id),
            defaults={
                "role": ChatMessage.Role.ASSISTANT,
                "content": ai_response.text,
                "processing_status": ChatMessage.ProcessingStatus.COMPLETED,
                "celery_task_id": self.request.id,
                "tokens_used": ai_response.tokens_used,
                "ai_model_used": ai_response.model_used,
                "is_group_message": is_group,
            },
        )

        if not ai_message_created:
            # Boshqa worker bu xabarga ALLAQACHON muvaffaqiyatli javob
            # bergan (poyga holati) — takroriy javob yubormaymiz, takroriy
            # buyurtma yaratmaymiz, faqat asl xabarni COMPLETED deb
            # belgilab, jimgina to'xtaymiz.
            logger.info(
                f"[Task] AI javobi allaqachon mavjud (poyga holati/retry) — "
                f"qayta ishlanmadi | msg_id={message_id}"
            )
            ChatMessage.objects.filter(id=chat_message.id).update(
                processing_status=ChatMessage.ProcessingStatus.COMPLETED,
            )
            return

        # ── 5.6. Guruhda: AI javob tayyorlanayotgan bir necha soniya
        # ichida inson (do'kon egasi/xodim) ALLAQACHON shu mijozga qo'lda
        # javob yozib ulgurgan bo'lsa — AI javobini ENDI yubormaymiz.
        # ⚠️ Mention/reply talabini olib tashlaganimiz uchun (mijoz
        # botni belgilamasa ham javob olishi uchun), bot admin bilan
        # "ustma-ust tushib qolish" xavfi qaytadi — buni shu tekshiruv
        # bilan qoplaymiz: ega/xodim mijozning xabaridan KEYIN o'sha
        # guruhga (istalgan) xabar yozgan bo'lsa, demak allaqachon
        # o'zi javob berayapti — bot ikkinchi, ehtimol qarama-qarshi
        # javob bilan aralashmasin.
        if is_group:
            human_ids = set()
            if store.tg_owner_chat_id:
                human_ids.add(str(store.tg_owner_chat_id))
            from apps.stores.models import StoreStaffMember as _StoreStaffMember
            from apps.customers.models import Customer as _Customer
            staff_usernames = list(
                _StoreStaffMember.objects.filter(store=store).values_list("tg_username", flat=True)
            )
            if staff_usernames:
                human_ids.update(
                    str(pid) for pid in _Customer.objects.filter(
                        store=store, username__in=staff_usernames
                    ).values_list("platform_user_id", flat=True)
                )
            if human_ids and ChatMessage.objects.filter(
                store=store, chat_id=str(chat_id), is_group_message=True,
                customer__platform_user_id__in=human_ids,
                created_at__gt=chat_message.created_at,
            ).exists():
                logger.info(
                    f"[Task] Guruhda ega/xodim allaqachon javob bergan — AI javobi yuborilmadi | store={store.name}"
                )
                return

        # ── 6. Javobni platforma orqali yuborish ──────────────────────
        # ⚠️ Guruhda bir nechta odam yozib turishi mumkin — javobni oddiy
        # xabar sifatida yuborsak, kim so'ragani va botning kimga javob
        # berayotgani chalkashib qolardi. Shaxsiy chatda esa reply shart
        # emas (faqat 1 kishi bilan suhbat).
        sent = send_reply(
            store=store,
            platform=platform,
            chat_id=chat_id,
            text=ai_response.text,
            customer=customer,
            reply_to_message_id=message_id if is_group else None,
        )

        if not sent:
            logger.warning(
                f"[Task] Javob yuborilmadi! "
                f"platform={platform} | chat_id={chat_id}"
            )
            # Yuborilmagan bo'lsa ham davom etamiz (buyurtma saqlash kerak)

        # ── 7. Lid aniqlangan bo'lsa ──────────────────────────────────
        if ai_response.has_lead and ai_response.lead_data:
            logger.info(
                f"[Task] Lid aniqlandi! "
                f"mijoz={ai_response.lead_data.get('full_name')} | "
                f"lead_status={ai_response.lead_data.get('lead_status')}"
            )

            lead = create_lead_from_ai_data(
                store=store,
                customer=customer,
                lead_data=ai_response.lead_data,
                platform=platform,
                source="group" if is_group else "private_chat",
                source_message=ai_message,
            )

            if lead:
                # Egasiga Telegram xabarnomasi
                notify_store_owner(store=store, lead=lead)
                # Bitrix24 ulangan bo'lsa — avtomatik sinxronizatsiya
                sync_lead_to_bitrix24(store=store, lead=lead)
                # Google Sheets ulangan bo'lsa — avtomatik sinxronizatsiya
                # (Bitrix24'dan mustaqil, ikkalasi ham bir vaqtda ishlashi mumkin)
                sync_lead_to_google_sheets(store=store, lead=lead)
            else:
                logger.warning(
                    f"[Task] Lid aniqlandi lekin saqlanmadi! "
                    f"data={ai_response.lead_data}"
                )

        # ── 8. Dastlabki xabarni COMPLETED deb belgilash ──────────────
        ChatMessage.objects.filter(id=chat_message.id).update(
            processing_status=ChatMessage.ProcessingStatus.COMPLETED,
        )

        # ── 9. Mijozning oxirgi faollik vaqtini yangilash ─────────────
        from django.utils import timezone
        Customer.objects.filter(id=customer.id).update(
            last_message_at=timezone.now()
        )

        logger.info(
            f"[Task] MUVAFFAQIYATLI | store={store.name} | "
            f"msg_id={message_id}"
        )

    except SoftTimeLimitExceeded:
        # Task juda uzoq ishladi
        logger.error(
            f"[Task] Vaqt limitini oshdi (soft) | "
            f"store_id={store_id} | msg_id={message_id}"
        )
        _mark_message_failed(store_id, message_id, platform, "SoftTimeLimitExceeded", sender_id=sender_id)

    except MaxRetriesExceededError:
        logger.error(
            f"[Task] Max retry oshdi | store_id={store_id} | msg_id={message_id}"
        )
        _mark_message_failed(store_id, message_id, platform, "MaxRetriesExceeded", sender_id=sender_id)

    except Exception as e:
        logger.error(
            f"[Task] XATO | store_id={store_id} | msg_id={message_id} | "
            f"retry={self.request.retries}/{self.max_retries} | {e}",
            exc_info=True,
        )

        # DB'da retry sonini yangilash
        _update_retry_count(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
            retry_count=self.request.retries + 1,
            error=str(e),
            sender_id=sender_id,
        )

        # Eksponensial backoff: 5s → 25s → 125s
        countdown = 5 ** (self.request.retries + 1)

        try:
            raise self.retry(exc=e, countdown=countdown)
        except MaxRetriesExceededError:
            _mark_message_failed(store_id, message_id, platform, str(e), sender_id=sender_id)


# ─────────────────────────────────────────────────────────────
# DATA RETENTION TASK — Eski xabarlarni tozalash
# ─────────────────────────────────────────────────────────────

@shared_task(
    name="apps.webhooks.tasks.cleanup_old_messages",
    ignore_result=True,
)
def cleanup_old_messages():
    """
    Eski ChatMessage'larni soft-delete qiladi.
    Celery Beat orqali har kech ishga tushadi.

    CHAT_MESSAGE_RETENTION_DAYS (default: 90 kun) dan
    eski xabarlar o'chiriladi.
    """
    from django.conf import settings
    from django.utils import timezone
    from datetime import timedelta
    from apps.chat.models import ChatMessage

    retention_days = getattr(settings, "CHAT_MESSAGE_RETENTION_DAYS", 90)
    cutoff_date = timezone.now() - timedelta(days=retention_days)

    try:
        count = ChatMessage.objects.filter(
            created_at__lt=cutoff_date,
            is_deleted=False,
        ).update(is_deleted=True)

        logger.info(
            f"[Data Retention] {count} ta xabar soft-delete qilindi "
            f"(>{retention_days} kun)"
        )
        return count

    except Exception as e:
        logger.error(f"[Data Retention] Xato: {e}", exc_info=True)
        return 0


# ─────────────────────────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────────────────────

def _mark_message_failed(store_id, message_id, platform, error_msg, sender_id=None):
    """ChatMessage'ni FAILED deb belgilaydi"""
    try:
        from apps.chat.models import ChatMessage
        # ⚠️ BUG FIX: avval bu yerda HAR DOIM FAILED deb belgilanardi —
        # hatto boshqa (parallel) worker o'sha xabarga ALLAQACHON
        # muvaffaqiyatli javob berib, COMPLETED deb belgilagan bo'lsa
        # ham! Bu haqiqiy muvaffaqiyatli xabarni FAILED holatga
        # "qaytarib" (regressiya) qo'yib, egasining dashboard/loglarida
        # yolg'on xato ko'rsatardi. Endi allaqachon COMPLETED bo'lgan
        # xabar hech qachon qayta yozilmaydi.
        #
        # ⚠️ `sender_id` (customer__platform_user_id) ham SHART — message_id
        # faqat bitta suhbat ichida unikal, shusiz boshqa mijozning bir xil
        # message_id'ga ega xabari xato FAILED deb belgilanib qolar edi.
        qs = ChatMessage.all_objects.filter(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
        )
        if sender_id is not None:
            qs = qs.filter(customer__platform_user_id=sender_id)
        qs.exclude(
            processing_status=ChatMessage.ProcessingStatus.COMPLETED,
        ).update(
            processing_status=ChatMessage.ProcessingStatus.FAILED,
            error_message=error_msg[:500],
        )
    except Exception as e:
        logger.error(f"_mark_message_failed xatosi: {e}")


def _update_retry_count(store_id, message_id, platform, retry_count, error, sender_id=None):
    """ChatMessage'da retry sonini yangilaydi"""
    try:
        from apps.chat.models import ChatMessage
        qs = ChatMessage.all_objects.filter(
            store_id=store_id,
            message_id=message_id,
            platform=platform,
        )
        if sender_id is not None:
            qs = qs.filter(customer__platform_user_id=sender_id)
        qs.update(
            retry_count=retry_count,
            error_message=str(error)[:500],
        )
    except Exception as e:
        logger.error(f"_update_retry_count xatosi: {e}")


# ─────────────────────────────────────────────────────────────
# MEDIA PERSISTENCE TASK — Media fayllarni serverga saqlash
# ─────────────────────────────────────────────────────────────

@shared_task(
    name="apps.webhooks.tasks.download_and_store_chat_media",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    ignore_result=True,
)
def download_and_store_chat_media(self, chat_message_id: str):
    """
    Instagram/Telegram birikmalarining media havolalarini (Meta CDN) yuklab olib,
    mahalliy storage'ga saqlaydi va ChatMessage.media_url (yoki Telegram ovozli
    xabarlar uchun audio_url) maydonini yangilaydi.
    """
    from apps.chat.models import ChatMessage
    from apps.chat.services import download_and_save_media_file, resolve_telegram_file_url

    try:
        msg = ChatMessage.objects.select_related("store").filter(id=chat_message_id).first()
        if not msg:
            logger.warning(f"[Media Task] Xabar topilmadi: {chat_message_id}")
            return

        raw = msg.raw_payload if isinstance(msg.raw_payload, dict) else {}
        inner_message = raw.get("message", {})

        # ── Telegram ovozli xabar (voice) ───────────────────────────
        # ⚠️ BUG FIX: Avval Telegram voice xabarlarining file_id'si
        # parsers.py'da o'qib olinib DARHOL TASHLAB YUBORILARDI — hech
        # qachon haqiqiy audio fayl yuklab olinmas, ChatMessage.audio_url
        # doim bo'sh qolardi. Operator faqat "🎙️ Ovozli xabar (Ns)" matn
        # placeholder'ini ko'rar, mijozning haqiqiy ovozli xabarini
        # eshita olmasdi. Endi getFile API orqali haqiqiy fayl yuklanadi.
        voice = inner_message.get("voice")
        if msg.platform == "telegram" and voice and voice.get("file_id"):
            file_url = resolve_telegram_file_url(msg.store.tg_bot_token, voice["file_id"])
            if not file_url:
                logger.warning(
                    f"[Media Task] Telegram voice file URL topilmadi: msg_id={chat_message_id}"
                )
                return

            saved_url = download_and_save_media_file(media_url=file_url, media_type="audio")
            if saved_url:
                duration = voice.get("duration", 0)
                msg.audio_url = saved_url
                msg.audio_duration = f"{duration // 60}:{duration % 60:02d}"
                msg.save(update_fields=["audio_url", "audio_duration", "updated_at"])
                logger.info(
                    f"[Media Task] Telegram ovozli xabar saqlandi va "
                    f"ChatMessage.audio_url yangilandi: msg_id={chat_message_id} | url={saved_url}"
                )
            return

        # ── Instagram media (rasm/video/audio attachment) ───────────
        media_url = None
        media_type = "image"

        attachments = inner_message.get("attachments", [])
        if attachments:
            att = attachments[0]
            media_type = att.get("type", "image")
            media_url = att.get("payload", {}).get("url")

        if not media_url and msg.content and msg.content.startswith("http"):
            media_url = msg.content

        if not media_url:
            logger.debug(f"[Media Task] Media URL topilmadi, skip: msg_id={chat_message_id}")
            return

        # Faylni yuklab olamiz
        saved_url = download_and_save_media_file(media_url=media_url, media_type=media_type)
        if saved_url:
            msg.media_url = saved_url
            msg.save(update_fields=["media_url", "updated_at"])
            logger.info(
                f"[Media Task] Muvaffaqiyatli saqlandi va ChatMessage.media_url yangilandi: "
                f"msg_id={chat_message_id} | url={saved_url}"
            )
    except Exception as e:
        logger.error(
            f"[Media Task] Media saqlashda xato: msg_id={chat_message_id} | {e}",
            exc_info=True,
        )

