"""
Webhook Views — Telegram va Instagram webhook endpointlari.

Ishlash mantig'i:
1. So'rov imzosini tekshir (xavfsizlik)
2. Payload'ni parse qil
3. Idempotency tekshir (Redis orqali tez, DB orqali ishonchli)
4. Celery navbatiga jo'nat (webhook qotmasin!)
5. Darhol 200 OK qaytart

⚠️ Webhook view'lari HECH QACHON AI yoki DB ga to'g'ridan-to'g'ri
   so'rov yubormasligi kerak — bu Celery task'lar ishi!
"""
import json
import logging
import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.stores.models import Store
from apps.chat.models import ChatMessage

from .security import (
    verify_telegram_webhook,
    verify_instagram_signature,
    verify_instagram_challenge,
)
from .parsers import (
    parse_telegram_payload,
    parse_instagram_payload,
    IncomingMessage,
)
from .tasks import process_incoming_message

logger = logging.getLogger("apps.webhooks")


# ─────────────────────────────────────────────────────────────
# TELEGRAM WEBHOOK
# ─────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class TelegramWebhookView(View):
    """
    Telegram Bot webhook endpoint.

    URL: /webhook/telegram/<bot_token>/
    Method: POST

    Har bir do'konning boti o'ziga xos token bilan keladi.
    URL'dagi bot_token orqali qaysi do'kon ekanini aniqlaymiz.
    """

    def post(self, request, bot_token: str):
        """Telegram'dan kelgan yangi xabarni qabul qiladi"""

        # 1. Imzo tekshiruvi
        if not verify_telegram_webhook(request):
            logger.warning(f"Telegram: ruxsatsiz so'rov | token: {bot_token[:10]}...")
            return HttpResponse(status=403)

        # 2. JSON parse
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Telegram: noto'g'ri JSON | {e}")
            # Telegram'ga 200 qaytaramiz — aks holda qayta-qayta yuboradi!
            return HttpResponse(status=200)

        # 2.5 Super Admin (platforma egasi) — LeadNode bot orqali `/ops`
        # buyrug'i bilan `/ops/` paneliga kirish tugmasini so'raydi. Bu —
        # HECH QANDAY do'konga bog'liq emas, shuning uchun pastdagi
        # do'kon-topish (3-qadam) dan OLDIN, alohida tekshiriladi. Faqat
        # MASTER bot tokenida va faqat `SUPERADMIN_TG_CHAT_IDS` ro'yxatidagi
        # chat_id'lar uchun ishlaydi — boshqa hamma uchun bu oddiy,
        # tanimaydigan matn sifatida pastdagi odatdagi oqimga tushib ketadi.
        if bot_token == getattr(settings, "TELEGRAM_BOT_TOKEN", ""):
            _msg = payload.get("message") or {}
            _text = (_msg.get("text") or "").strip()
            _sender_id = str(_msg.get("from", {}).get("id", ""))
            _is_private = _msg.get("chat", {}).get("type") == "private"
            if (
                _is_private and _text.startswith("/ops")
                and _sender_id in getattr(settings, "SUPERADMIN_TG_CHAT_IDS", [])
            ):
                # ⚠️ Faqat shaxsiy (1:1) chatda — aks holda, agar ruxsat
                # etilgan admin shu buyruqni GURUHDA yozsa, tugma o'sha
                # guruhga chiqib ketardi (haqiqiy xavfsizlik teshigi emas,
                # chunki bosilganda baribir faqat SHU chat_id'ning o'zi
                # kira oladi — lekin quruq/chalkash holat, kerak emas).
                self._send_superadmin_ops_button(bot_token, _msg["chat"]["id"])
                return HttpResponse(status=200)

        # 3. Do'konni bot_token orqali topamiz (bot haqiqiy va faolligini tekshirish uchun)
        token_store = self._get_store_by_token(bot_token)
        if not token_store:
            # ⚠️ Do'kon egasi shaxsiy botini ulagandan keyin (Sozlamalar →
            # "Bot ulash"), bu umumiy bot endi o'sha do'konga UMUMAN
            # tegishli emas. Lekin agar do'kon egasi ULASHDAN OLDIN
            # bio/target'da ushbu umumiy botga yo'naltiruvchi eski havolani
            # (masalan "?start=store_<uuid>") allaqachon tarqatgan bo'lsa,
            # o'sha eski havola bosilganda mijoz hech qanday javobsiz
            # (sukut) qolib ketardi — foydalanuvchi buni aniq ta'kidladi.
            # Shu sabab: bu FAQAT umumiy (master) bot bo'lsa, xabar ichidan
            # deep-link'ni sinab ko'ramiz — agar u ANIQ shu do'konga tegishli
            # bo'lib, do'kon ENDI o'z botiga o'tgan bo'lsa, mijozni
            # avtomatik yangi botga yo'naltiramiz (havola singan bo'lib
            # qolmaydi).
            if bot_token == getattr(settings, "TELEGRAM_BOT_TOKEN", ""):
                if self._redirect_to_own_bot_if_moved(bot_token, payload):
                    return HttpResponse(status=200)
            logger.warning(
                f"Telegram: do'kon topilmadi | token: {bot_token[:10]}..."
            )
            return HttpResponse(status=200)

        # 3.5 Bot guruhga/superguruhga QO'SHILGANDA Telegram doim shu
        # update turini yuboradi ("message" kaliti bo'lmaydi, shuning
        # uchun pastdagi parse_telegram_payload buni tushunmaydi — alohida,
        # oldindan ushlanadi). Guruhni avtomatik bog'lash shu yerda
        # amalga oshadi (qarang: _handle_my_chat_member).
        if "my_chat_member" in payload:
            self._handle_my_chat_member(payload, bot_token)
            return HttpResponse(status=200)

        # 4. Payload'ni parse qilamiz
        message = parse_telegram_payload(payload)
        if not message:
            # Qo'llab-quvvatlanmaydigan update turi — OK qaytaramiz
            return HttpResponse(status=200)

        # 4.4 Guruhda qo'lda yuborilgan "/start store_<uuid>" — masalan
        # egasi botni startgroup havolasisiz, oddiy "Add member" orqali
        # qo'shgan bo'lsa, shu buyruq bilan ham qo'lda bog'lay oladi
        # (3.5-qadamdagi avtomatik bog'lashning zaxira/qo'lda varianti).
        if message.chat_type in ("group", "supergroup") and message.text.strip().startswith("/start"):
            self._handle_group_binding(message, bot_token)
            return HttpResponse(status=200)

        # 4.5 Single Master Bot Multi-Tenant Routing (Deep-link & Session Router)
        store = self._resolve_store_for_message(message, bot_token)

        # ⚠️ XAVFSIZLIK: hech qanday do'konga aniq bog'lanmagan (havolasiz/
        # sessiyasiz kirgan BEGONA) foydalanuvchini ENDI hech qanday real
        # do'konning "mijozi" sifatida ro'yxatga olmaymiz — buning o'rniga
        # muloyim yo'naltiruvchi xabar yuboramiz va to'xtaymiz.
        if store is None:
            # Guruhda: bog'lanmagan (yoki hali botga tanish bo'lmagan) guruhga
            # bu umumiy "havolasiz" xabarni yubormaymiz — begona/tasodifiy
            # guruhda botning o'zini reklama qilishi noqulay va keraksiz.
            # Shaxsiy chatda esa yo'naltiruvchi xabar avvalgidek yuboriladi.
            if message.chat_type not in ("group", "supergroup"):
                from apps.chat.senders import send_telegram_message
                send_telegram_message(
                    bot_token=bot_token,
                    chat_id=message.chat_id,
                    text=(
                        "Assalomu alaykum! 😊 Bu bot faqat maxsus taklif havolasi orqali ishlaydi. "
                        "Agar sizni biror do'kon/kurs markazi shu botga yo'naltirgan bo'lsa, "
                        "ular yuborgan havoladan (link) qayta foydalaning."
                    ),
                )
            logger.info(
                f"Telegram: begona foydalanuvchi/guruh (bog'lanmagan) — hech qaysi do'konga biriktirilmadi | "
                f"sender_id={message.sender_id} | chat_type={message.chat_type}"
            )
            return HttpResponse(status=200)

        # 4.6 Idempotency: Telegram bir xil update'ni bir necha marta qayta
        # yuborishi mumkin (webhook sekin javob bersa yoki tarmoq xatosida).
        #
        # ⚠️ BUG FIX: bu tekshiruv (`_is_duplicate`) allaqachon yozilgan va
        # Instagram oqimida ishlatilgan edi, lekin Telegram oqimida HECH
        # QACHON chaqirilmagan (o'lik kod) — ya'ni har bir qayta yuborilgan
        # (retry) xabar navbatga qayta-qayta qo'shilib, keyingi bosqichda
        # (process_incoming_message) poyga sharoiti (race condition)
        # orqali ikkilangan javob/Gemini chaqiruvlariga olib kelishi mumkin
        # edi. Endi Instagram bilan bir xil, navbatga qo'shishdan OLDIN
        # tekshiriladi.
        if self._is_duplicate(store.id, message, bot_token):
            logger.info(f"Telegram: dublikat xabar, o'tkazib yuborildi | msg_id={message.message_id}")
            return HttpResponse(status=200)

        # 4.9 Ketma-ket yozilgan xabarlarni birlashtirish: shaxsiy chatdagi oddiy
        # matn bir necha soniya kutib qayta ishlanadi (apps/webhooks/burst.py).
        from . import burst as _burst

        _extra = {}
        if _burst.is_candidate(chat_type=message.chat_type, text=message.text) and _burst.register(
            store_id=store.id, sender_id=message.sender_id,
            message_id=message.message_id, text=message.text,
        ):
            _extra["countdown"] = _burst.window_seconds()

        # 5. Celery navbatiga jo'natamiz (ASYNCHRONOUS!)
        try:
            task = process_incoming_message.apply_async(
                **_extra,
                args=[],
                kwargs={
                    "store_id": str(store.id),
                    "platform": "telegram",
                    "message_id": message.message_id,
                    "sender_id": message.sender_id,
                    "sender_username": message.sender_username,
                    "sender_display_name": message.sender_display_name,
                    "text": message.text,
                    "chat_id": message.chat_id,
                    "raw_payload": message.raw_payload,
                    "chat_type": message.chat_type,
                    "received_at": timezone.now().isoformat(),
                },
                queue="messages",
                routing_key="messages",
            )
            logger.info(
                f"Telegram xabari navbatga qo'yildi | "
                f"task_id={task.id} | store={store.name} | "
                f"message_id={message.message_id}"
            )
        except Exception as e:
            logger.error(
                f"Celery navbatga qo'shishda xato: {e}",
                exc_info=True,
            )
            # ⚠️ BUG FIX: avval bu yerda ham Telegram'ga 200 qaytarilardi —
            # ya'ni Redis/Celery broker vaqtincha ishlamay qolsa (masalan
            # qisqa muddatli tarmoq uzilishi), xabar HECH QAYERDA
            # saqlanmasdan, Telegram esa "muvaffaqiyatli yetkazildi" deb
            # HECH QACHON qayta urinib ko'rmasdan, butunlay yo'qolib
            # ketardi. Endi 500 qaytariladi — Telegram buni ko'rib, keyingi
            # daqiqalarda avtomatik qayta yuboradi (broker tiklanguncha).
            return HttpResponse(status=500)

        # 7. Telegram 200 kutadi — muvaffaqiyatli navbatga qo'yilgach 200 qaytaramiz
        return HttpResponse(status=200)

    def _resolve_store_for_message(self, message, bot_token: str = "") -> Store | None:
        """
        Single Master Bot Model uchun:
        /start store_123 deep-linki yoki foydalanuvchining aktiv do'kon sessiyasi bo'yicha dinamik yo'naltiradi.

        Returns:
            Store — deep-link yoki mavjud sessiya orqali aniq topildi
            None  — hech qanday havola/sessiya yo'q (begona/tasodifiy kirgan foydalanuvchi)
        """
        from apps.customers.models import CustomerSession
        from django.db.models import Q

        text = (message.text or "").strip()
        sender_id = str(message.sender_id)

        # ── Guruh xabari: bog'lash (/start) allaqachon post()'da alohida
        # ushlangan — bu yerga faqat ODDIY guruh xabarlari yetib keladi.
        # Yo'nalish oddiy: guruhning chat_id'si qaysi Store'ga
        # bog'langan bo'lsa, o'sha Store qaytariladi (bog'lanmagan bo'lsa
        # None — bot indamaydi).
        if message.chat_type in ("group", "supergroup"):
            return Store.objects.filter(
                tg_group_chat_id=str(message.chat_id),
                is_active=True,
                is_deleted=False,
            ).first()

        # 1. Deep-link /start store_<uuid> yoki /start admin_<uuid>
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                param = parts[1].strip()
                # admin_ / store_ / register_ prefixini olib tashlab, faqat UUID qoldiramiz.
                # ⚠️ "register_" — guruhda "juda issiq" (yuqori xarid niyatli) mijozga
                # ko'rsatiladigan "Ro'yxatdan o'tish" havolasi uchun maxsus prefiks
                # (qarang: apps/chat/ai_service.py dm_link_register_display) — bu
                # mijoz ANIQ ro'yxatdan o'tish niyati bilan kirganini bildiradi, shunda
                # shaxsiy chatda AI oddiy savol-javobni qaytadan boshlamay, darhol
                # ism+telefon so'rashga o'tadi. "store_" — "Batafsil ma'lumot olish"
                # havolasi: bu ham ANIQ qiziqish signali (shunchaki kuzatuvchi emas,
                # maxsus shu yerga kirib kelgan), lekin yumshoqroq — AI savolga javob
                # berib, SO'NG ism+telefonni taklif qiladi (pastga, CustomerSession.
                # entry_mode va apps/chat/ai_service.py'ga qarang). "admin_" — do'kon
                # EGASINING o'z paneliga kirish havolasi, mijoz emas — fast-path TEGISHLI EMAS.
                is_register_entry = param.startswith("register_")
                is_store_info_entry = param.startswith("store_")
                target_key = param
                for prefix in ("admin_", "store_", "register_"):
                    if param.startswith(prefix):
                        target_key = param[len(prefix):]
                        break

                # UUID bo'lmagan qiymat kiritilsa crash bo'lmasligi uchun try/except
                #
                # ⚠️ BUG FIX: Store modelida "slug" degan maydon UMUMAN YO'Q
                # (apps/stores/models.py'ni tekshiring). Shu sababli quyidagi
                # so'rov HAR DOIM django.core.exceptions.FieldError bilan
                # portlar edi va pastdagi keng `except Exception: pass` uni
                # jimgina yutib yuborardi — natijada target_store doim None
                # bo'lib qolar, ya'ni /start admin_<uuid> va /start store_<uuid>
                # deep-link orqali do'konga yo'naltirish funksiyasi UMUMAN
                # ishlamas edi (Single Master Bot Model buzilgan edi).
                target_store = None
                try:
                    target_store = Store.objects.filter(
                        Q(id=target_key) | Q(tg_owner_chat_id=target_key),
                        is_active=True,
                        is_deleted=False
                    ).first()
                except Exception:
                    pass

                if target_store:
                    # ⚠️ "Qaysi biznes bilan gaplashyapman?" belgisi
                    # (CustomerSession.active_store) — BIR ODAM uchun
                    # GLOBAL, bot token'dan MUSTAQIL (shaxsiy bot bo'lsa
                    # ham). Agar shu odam avval BOSHQA (haqiqiy, boshqa)
                    # biznesning havolasini bosgan bo'lsa-yu, endi shu
                    # havolani bossa — belgisi almashadi. Agar u keyin
                    # avvalgi biznesga QAYTIB, havolani QAYTA bosmasdan
                    # oddiy xabar yozsa, xabari ENDI yangi (noto'g'ri)
                    # biznesga yo'naltirilib qolishi mumkin edi (jonli
                    # muhokamada aniqlandi). Shu sabab, agar bu HAQIQIY
                    # almashish bo'lsa (avval boshqa biznes bo'lgan),
                    # mijozga qisqa eslatma yuboramiz — shunda u tasodifan
                    # noto'g'ri biznesga yozib qolsa, buni darhol sezadi.
                    previous_session = CustomerSession.objects.filter(platform_user_id=sender_id).first()
                    is_store_switch = bool(
                        previous_session and previous_session.active_store_id
                        and previous_session.active_store_id != target_store.id
                    )

                    if is_register_entry:
                        resolved_entry_mode = CustomerSession.EntryMode.REGISTER
                    elif is_store_info_entry:
                        resolved_entry_mode = CustomerSession.EntryMode.INFO
                    else:
                        resolved_entry_mode = ""

                    CustomerSession.objects.update_or_create(
                        platform_user_id=sender_id,
                        defaults={
                            "active_store": target_store,
                            "entry_mode": resolved_entry_mode,
                        }
                    )

                    if is_store_switch and bot_token:
                        from apps.chat.senders import send_telegram_message
                        send_telegram_message(
                            bot_token=bot_token,
                            chat_id=message.chat_id,
                            text=f"📍 Endi siz <b>{target_store.name}</b> bilan gaplashyapsiz.",
                        )

                    return target_store

        # 1.5. ⚠️ BUG FIX: do'kon egasi, PARAMETRSIZ oddiy "/start" yoki
        # "/dashboard" yozganda — bu "meni o'zimning boshqaruv panelimga
        # olib bor" degan aniq signal. Lekin agar shu egasi ILGARI
        # (masalan sinov uchun) BOSHQA bir do'konning mijoz havolasini
        # bosgan bo'lsa, uning YAGONA umumiy `CustomerSession.active_store`
        # o'sha BOSHQA do'konga almashib qolgan bo'ladi — natijada
        # pastdagi 2-bosqich (sessiya bo'yicha) uni NOTO'G'RI ravishda
        # boshqa do'konning oddiy mijozi deb aniqlab, egasi o'zining
        # ASL do'koniga umuman kira olmay qolardi (jonli holatda
        # aniqlandi: egasi boshqa loyihaning mijoz havolasini bosgach,
        # keyin oddiy "/start" bilan o'zining boshqaruv paneliga kira
        # olmay qoldi). Shu sabab: agar bu odam biror do'konning HAQIQIY
        # egasi bo'lsa, oddiy "/start"/"/dashboard" har doim ANIQ O'ZINING
        # do'koniga olib boradi — sessiyadagi boshqa do'kon nima bo'lishidan
        # qat'i nazar.
        if text.strip().lower() in ("/start", "/dashboard", "start", "dashboard"):
            owned_store = Store.objects.filter(
                tg_owner_chat_id=sender_id, is_active=True, is_deleted=False,
            ).first()
            if owned_store:
                return owned_store

        # 2. Mavjud active user session
        sess = CustomerSession.objects.select_related("active_store").filter(
            platform_user_id=sender_id,
            active_store__is_active=True,
            active_store__is_deleted=False
        ).first()

        if sess:
            return sess.active_store

        # ⚠️ XAVFSIZLIK/IZOLYATSIYA TUZATISHI: avval bu yerda hech qanday
        # havola yoki sessiyasi bo'lmagan (masalan botni tasodifan yoki
        # username orqali topib kirgan BEGONA) foydalanuvchi jimgina
        # `default_store`ga (bot_token bo'yicha topilgan — Single Master
        # Bot arxitekturasida BARCHA do'konlar bitta tokenni ishlatgani
        # uchun bu amalda "eng so'nggi yangilangan do'kon" degani)
        # biriktirilib qo'yilardi. Ya'ni tasodifiy kishi hech narsa
        # so'ramasdan turib biror REAL do'konning "mijozi" bo'lib qolardi
        # — bu do'konning AI byudjetini isrof qilardi va uning Inbox'ini
        # keraksiz suhbatlar bilan to'ldirardi. Endi bunday holatda HECH
        # QANDAY do'konga biriktirilmaydi (None qaytariladi).
        #
        # ⚠️ LEKIN BU FAQAT UMUMIY (MASTER) BOTGA TEGISHLI. Do'konning
        # O'Z SHAXSIY boti (alohida @username va alohida token) bo'lsa,
        # token BITTA do'konga tegishli — noaniqlik umuman yo'q, demak
        # yuqoridagi xavf ham yo'q. Bunday botda mijoz Telegram qidiruvi
        # orqali topib "/start" bossa ham, u aniq o'sha do'konning mijozi.
        #
        # Jonli aniqlangan xato (2026-10-21): @pdpacademy96bot'ga to'g'ridan
        # kirgan mijoz "Bu bot faqat maxsus taklif havolasi orqali ishlaydi"
        # degan xabarni olib, umuman javob ololmay qolgan.
        master_token = (getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()
        if bot_token and bot_token.strip() != master_token:
            dedicated_store = self._get_store_by_token(bot_token)
            if dedicated_store:
                logger.info(
                    "Telegram: do'konning shaxsiy boti orqali kirildi — "
                    f"do'kon avtomatik aniqlandi | store={dedicated_store.name}"
                )
                return dedicated_store

        return None

    def _bind_group_to_store(self, store: Store, chat_id: str, bot_token: str) -> None:
        """Guruhni berilgan do'konga bog'laydi va (kerak bo'lsa) tasdiqlash xabarini yuboradi."""
        from django.db import transaction
        from apps.chat.senders import send_telegram_message

        # Allaqachon aynan shu guruhga bog'langan bo'lsa — hech narsa
        # o'zgarmaydi, qayta tasdiqlash xabarini yuborishning hojati yo'q
        # (yuqoridagi update_id himoyasiga qo'shimcha ikkinchi himoya qatlami).
        if str(store.tg_group_chat_id or "") == chat_id:
            return

        # ⚠️ BUG FIX: oddiy Telegram guruhi ba'zan (masalan admin
        # huquqlari/sozlamalar o'zgarganda) Telegram tomonidan avtomatik
        # SUPERGURUHGA ko'tariladi — bu guruhning chat_id'sini BUTUNLAY
        # YANGI qiymatga almashtiradi va Telegram buni bot uchun "yana
        # guruhga qo'shildim" (`my_chat_member` "joined") hodisasi
        # sifatida qayta yuboradi. Natijada bir necha soniya ichida BIR
        # XIL (foydalanuvchi nazarida) guruh uchun ikkinchi marta
        # bog'lanish sodir bo'lib, "muvaffaqiyatli ulandi" tabriknomasi
        # IKKI MARTA ketardi (jonli holatda aniqlandi, foydalanuvchi buni
        # chalkash deb topdi). Bunday holatni shu do'kon uchun YAQINDA
        # (10 daqiqa ichida) allaqachon tasdiqlash xabari yuborilganidan
        # bilib olamiz — ID baribir jimgina yangilanadi, lekin xabar
        # QAYTA yuborilmaydi.
        confirm_cooldown_key = f"group_bind_confirmed:{store.id}"
        should_notify = cache.add(confirm_cooldown_key, True, timeout=60 * 10)

        with transaction.atomic():
            # Boshqa do'kon avval shu guruhga bog'langan bo'lsa — unique
            # cheklovga urilmaslik uchun avval bo'shatib olamiz.
            Store.objects.filter(tg_group_chat_id=chat_id).exclude(id=store.id).update(tg_group_chat_id=None)
            Store.objects.filter(id=store.id).update(tg_group_chat_id=chat_id)

        logger.info(
            f"Telegram: guruh bog'landi | store={store.name} | chat_id={chat_id} | "
            f"tasdiqlash_xabari_yuborildi={should_notify}"
        )
        if not should_notify:
            return

        # ⚠️ Avval bu yerda botning xom @username'i ("@LeadNodeBot")
        # ko'rsatilardi — bu bir nechta do'konga xizmat qiladigan UMUMIY
        # botning ichki texnik nomini ochib qo'yardi (do'kon egasi buni
        # o'z-o'ziga tegishli, "oq nishonli" yechim sifatida ko'rsatishni
        # xohlaydi). Endi shunchaki umumiy "botni" so'zi ishlatiladi.
        # ⚠️ BUG FIX: matn "@LeadNodeBot" o'rniga "LeadNode" so'zini qattiq
        # yozib qo'ygan edi — bu ham xuddi shu muammo: do'kon egasi O'Z
        # shaxsiy botini (white-label, "Sozlamalar → Bot ulash") ulagan
        # bo'lsa ham, tasdiqlash xabari hamon "LeadNode ulandi" deb
        # yozardi — bu uning O'Z boti emas, uchinchi tomon mahsuloti
        # qo'shilgandek taassurot qoldirardi (foydalanuvchi aniq
        # ta'kidladi). Endi bu yerda ham faqat umumiy "Bot" so'zi.
        # ⚠️ BUG FIX: avval bu yerda "A'zolar botni belgilab yoki
        # xabariga javob (reply) berib savol bersa..." deyilardi — bu
        # do'kon egasi/menejerlarda "bot FAQAT belgilansa ishlaydi" degan
        # noto'g'ri tushuncha hosil qilardi. Aslida mijozlar uchun bunday
        # shart YO'Q (@mention/reply talabi faqat do'kon egasi/xodimni
        # oddiy mijozdan ajratish uchun ichkarida ishlatiladi, qarang:
        # apps/webhooks/tasks.py `_is_message_addressed_to_bot`) — har
        # qanday mijoz botni belgilamasdan ham kurs/xizmat haqida savol
        # yozsa, AI baribir avtomatik javob beradi. Foydalanuvchi buni
        # jonli holatda aniqladi ("mijoz botni belgilamasaham javob
        # beradiku"), shuning uchun matn haqiqiy xatti-harakatga mos
        # qilib tuzatildi.
        send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=f"✅ <b>Bot</b> ushbu guruhga muvaffaqiyatli ulandi — endi <b>{store.name}</b> uchun ishlaydi!",
            parse_mode="HTML",
        )

        # ⚠️ Telegram "Group Privacy Mode" (BotFather sozlamasi, API orqali
        # o'zgartirib bo'lmaydi) standart holatda YOQILGAN bo'ladi — bunda
        # bot guruhda FAQAT o'ziga @mention/reply qilingan xabarlarni
        # ko'radi, oddiy mijoz savoli ("kurs qancha turadi?") botga
        # UMUMAN YETIB BORMAYDI (jonli holatda aniqlandi: bizning kodimiz
        # mention talab qilmasa ham, Telegram'ning o'zi xabarni yubormagan
        # edi). Buni har bir do'kon egasi @BotFather orqali BIR MARTA
        # qo'lda o'chirishi kerak — shuni aynan guruhga ulangan ONDA,
        # ega buni eslab qolishi ehtimoli eng yuqori bo'lgan paytda,
        # shaxsiy chatga (guruhga emas — bu ichki texnik ko'rsatma,
        # mijozlar ko'rmasligi kerak) eslatib qo'yamiz.
        if store.tg_owner_chat_id:
            bot_username = store.tg_bot_username or ""
            send_telegram_message(
                bot_token=bot_token,
                chat_id=store.tg_owner_chat_id,
                text=(
                    f"⚠️ <b>Muhim, bir martalik sozlash</b>\n\n"
                    f"Guruhdagi mijozlar botni <b>belgilamasdan</b> ("
                    f"@{bot_username or 'bot'} deb yozmasdan) ham savol bersa, "
                    f"bot javob berishi uchun Telegram'ning o'z sozlamasini "
                    f"o'chirish kerak:\n\n"
                    f"1. <b>@BotFather</b>ni oching\n"
                    f"2. <code>/setprivacy</code> buyrug'ini yuboring\n"
                    f"3. Botingizni tanlang: @{bot_username}\n"
                    f"4. <b>Disable</b> tugmasini bosing\n\n"
                    f"Shuni bir marta qilib qo'ysangiz, bot guruhdagi barcha "
                    f"savollarni ko'ra oladigan bo'ladi."
                ),
                parse_mode="HTML",
            )

    def _handle_group_binding(self, message, bot_token: str) -> None:
        """
        Guruhda qo'lda yuborilgan "/start store_<uuid>" (yoki admin_<uuid>)
        buyrug'ini ushlaydi va guruhni shu Store'ga bog'laydi.

        ⚠️ XAVFSIZLIK: faqat do'kon EGASI (tg_owner_chat_id mos keladigan
        Telegram foydalanuvchi) guruhni bog'lay oladi — aks holda istalgan
        kishi (masalan raqobatchi) boshqa birovning do'koniga tasodifiy
        yoki qasddan begona/spam guruhni bog'lab qo'yishi mumkin edi.
        """
        from django.db.models import Q
        from apps.chat.senders import send_telegram_message

        text = message.text.strip()
        parts = text.split()
        if len(parts) < 2:
            return

        param = parts[1].strip()
        target_key = param
        for prefix in ("admin_", "store_"):
            if param.startswith(prefix):
                target_key = param[len(prefix):]
                break

        target_store = None
        try:
            target_store = Store.objects.filter(
                Q(id=target_key) | Q(tg_owner_chat_id=target_key),
                is_active=True,
                is_deleted=False,
            ).first()
        except Exception:
            pass

        if not target_store:
            return

        sender_id = str(message.sender_id)
        if not target_store.tg_owner_chat_id or str(target_store.tg_owner_chat_id) != sender_id:
            logger.warning(
                f"Telegram: guruh bog'lash rad etildi (ega emas) | "
                f"store={target_store.name} | sender={sender_id}"
            )
            send_telegram_message(
                bot_token=bot_token,
                chat_id=message.chat_id,
                text="🚫 Faqat do'konning haqiqiy egasi guruhni ulashi mumkin.",
            )
            return

        self._bind_group_to_store(target_store, str(message.chat_id), bot_token)

    def _handle_my_chat_member(self, payload: dict, bot_token: str) -> None:
        """
        Bot biror guruh/superguruhga QO'SHILGANDA Telegram doim yuboradigan
        `my_chat_member` hodisasini ushlab, guruhni avtomatik bog'laydi.

        ⚠️ BUG FIX: "Guruhga qo'shish" (?startgroup=store_<uuid>) havolasi
        ishlatilganda Telegram guruhga avtomatik "/start store_<uuid>"
        xabarini yuboradi deb kutilgan edi (_handle_group_binding shunga
        mo'ljallangan) — lekin jonli testda bu xabar HECH QACHON kelmadi
        (faqat `my_chat_member` va matnsiz "a'zo qo'shildi" xizmat xabari
        keldi). Natijada do'kon egasi tugmani bosib botni guruhga qo'shsa
        ham, guruh hech qachon bog'lanmasdi — egadan qo'lda buyruq yozishni
        talab qilish tushunarsiz/ortiqcha UX edi. Endi buning o'rniga
        Telegram ISHONCHLI yuboradigan `my_chat_member.from` (botni KIM
        qo'shgani) ma'lumotidan foydalanamiz: agar o'sha odam tizimda
        aynan BITTA do'konning egasi bo'lsa, guruh hech qanday qo'shimcha
        buyruqsiz o'sha do'konga avtomatik bog'lanadi.
        """
        try:
            event = payload.get("my_chat_member")
            if not event:
                return

            # ⚠️ BUG FIX: Telegram ba'zan bitta hodisani (masalan tarmoq
            # kechikishi yoki webhook javobi sekin bo'lganda) bir necha
            # marta qayta yuborishi mumkin — bu oddiy xabarlar uchun
            # `_is_duplicate` orqali ushlanadi, lekin `my_chat_member`
            # alohida yo'l bo'lgani uchun bunday himoya yo'q edi. Natijada
            # bitta "guruhga qo'shildi" hodisasi ikki marta qayta
            # ishlanib, guruhga IKKITA bir xil tasdiqlash xabari ketardi
            # (jonli testda aniqlandi). `update_id` — Telegram'ning har bir
            # update uchun berilgan, takrorlanmaydigan raqami — shu orqali
            # qisqa muddatli (10 daqiqa) idempotency ta'minlanadi.
            update_id = payload.get("update_id")
            if update_id is not None:
                cache_key = f"my_chat_member_processed:{update_id}"
                if not cache.add(cache_key, True, timeout=600):
                    return

            chat = event.get("chat", {})
            if chat.get("type") not in ("group", "supergroup"):
                return

            new_status = event.get("new_chat_member", {}).get("status", "")
            old_status = event.get("old_chat_member", {}).get("status", "")
            chat_id = str(chat.get("id", ""))
            if not chat_id:
                return

            joined_now = (
                new_status in ("member", "administrator")
                and old_status not in ("member", "administrator")
            )
            removed_now = (
                new_status in ("left", "kicked")
                and old_status in ("member", "administrator")
            )

            # ⚠️ Xavfsizlik to'ri: egasi BILMASDAN/ADASHIB botni noto'g'ri
            # (masalan shaxsiy do'stlar) guruhga qo'shib yuborishi mumkin —
            # bunday holatda botni o'sha guruhdan olib tashlash yetarli
            # bo'lishi kerak, aks holda noto'g'ri bog'lanish "osilib"
            # qolib, bot begona guruhda ishlashda davom etardi. Bot
            # chiqarilganda/haydalganda, unga bog'langan do'kon bo'lsa —
            # avtomatik bo'shatiladi.
            if removed_now:
                unbound = Store.objects.filter(tg_group_chat_id=chat_id).update(tg_group_chat_id=None)
                if unbound:
                    logger.info(f"Telegram: bot guruhdan olib tashlandi, bog'lanish bekor qilindi | chat_id={chat_id}")
                return

            if not joined_now:
                return

            adder_id = str(event.get("from", {}).get("id", ""))
            if not adder_id:
                return

            matches = list(Store.objects.filter(
                tg_owner_chat_id=adder_id,
                is_active=True,
                is_deleted=False,
            ))
            if not matches:
                logger.info(
                    f"Telegram: guruhga bot qo'shildi, lekin qo'shgan foydalanuvchi "
                    f"({adder_id}) hech qanday do'kon egasi sifatida tanilmadi — "
                    f"avtomatik bog'lanmadi | chat_id={chat_id}"
                )
                return
            if len(matches) > 1:
                logger.warning(
                    f"Telegram: guruhga bot qo'shildi, lekin qo'shgan foydalanuvchi "
                    f"({adder_id}) bir nechta do'konga ega — avtomatik bog'lash "
                    f"noaniq, o'tkazib yuborildi | chat_id={chat_id}"
                )
                return

            self._bind_group_to_store(matches[0], chat_id, bot_token)
        except Exception as e:
            logger.error(f"my_chat_member qayta ishlashda xato: {e}", exc_info=True)

    def _send_superadmin_ops_button(self, bot_token: str, chat_id) -> None:
        """Ruxsat etilgan platforma egasiga `/ops/` panelni ochuvchi Telegram WebApp tugmasini yuboradi."""
        from apps.chat.senders import send_telegram_message

        public_url = getattr(settings, "PUBLIC_URL", "").rstrip("/")
        if not public_url:
            logger.error("PUBLIC_URL sozlanmagan! Super Admin tugmasi yuborilmadi.")
            return

        send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="👑 <b>Super Admin panel</b>\n\nPlatformani boshqarish uchun pastdagi tugmani bosing.",
            parse_mode="HTML",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "🚀 Ops panelni ochish", "web_app": {"url": f"{public_url}/ops/"}}
                ]]
            },
        )

    def _get_store_by_token(self, bot_token: str) -> Store | None:
        """Bot token bo'yicha aktiv do'konni topadi"""
        # ⚠️ OPTIMIZATION: bu DB so'rovi HAR BIR kelgan Telegram xabarida
        # bajarilardi. Do'konlar ro'yxati kamdan-kam o'zgargani uchun
        # qisqa muddatli kesh bilan xabarlar ko'payib ketganda ham
        # bazaga ortiqcha yuk tushmaydi.
        cache_key = f"store_by_bottoken:{bot_token}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # ⚠️ tg_bot_token endi shifrlangan — to'g'ridan-to'g'ri qidirib
            # bo'lmaydi, shuning uchun hash ustuni orqali qidiramiz
            # (apps/core/fields.py, apps/stores/models.py Store.save()).
            from apps.core.fields import sha256_hex

            store = Store.objects.select_related("owner").filter(
                tg_bot_token_hash=sha256_hex(bot_token),
                is_active=True,
                is_deleted=False,
            ).order_by("-updated_at", "-created_at").first()
            if store:
                cache.set(cache_key, store, timeout=20)
            return store
        except Exception as e:
            logger.error(f"Do'konni topishda xato: {e}", exc_info=True)
            return None

    def _redirect_to_own_bot_if_moved(self, master_bot_token: str, payload: dict) -> bool:
        """
        Umumiy (master) botga "/start store_<uuid>" yoki "/start admin_<uuid>"
        deep-link bilan kirilgan, lekin o'sha do'kon ALLAQACHON o'z shaxsiy
        botiga o'tgan bo'lsa — mijozni yangi botga yo'naltiruvchi xabar
        yuboradi (eski, bio/target'da tarqatilgan havola "singan" bo'lib
        qolmasligi uchun).

        Returns:
            True — yo'naltirish xabari yuborildi (chaqiruvchi shu bilan to'xtaydi)
            False — bu holat emas (odatdagi "begona foydalanuvchi" oqimi davom etadi)
        """
        try:
            message_data = payload.get("message") or payload.get("edited_message") or {}
            text = (message_data.get("text") or "").strip()
            chat = message_data.get("chat") or {}
            chat_id = chat.get("id")
            if not text.startswith("/start") or not chat_id:
                return False

            parts = text.split()
            if len(parts) < 2:
                return False
            param = parts[1].strip()

            target_key = param
            for prefix in ("admin_", "store_", "register_"):
                if param.startswith(prefix):
                    target_key = param[len(prefix):]
                    break

            try:
                target_store = Store.objects.filter(
                    id=target_key, is_active=True, is_deleted=False,
                ).first()
            except Exception:
                return False

            if not target_store or not target_store.has_own_bot or not target_store.tg_bot_username:
                return False

            new_link = f"https://t.me/{target_store.tg_bot_username}?start={param}"
            from apps.chat.senders import send_telegram_message

            send_telegram_message(
                bot_token=master_bot_token,
                chat_id=chat_id,
                text=(
                    f"👋 Salom! <b>{target_store.name}</b> endi yangi bot orqali ishlaydi. "
                    f"Iltimos, quyidagi havola orqali davom eting:\n\n"
                    f'<a href="{new_link}">{target_store.name} botiga o\'tish</a>'
                ),
            )
            logger.info(
                f"Telegram: eski umumiy bot havolasi yangi shaxsiy botga yo'naltirildi | "
                f"store={target_store.name} | chat_id={chat_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Eski havolani yangi botga yo'naltirishda xato: {e}", exc_info=True)
            return False

    def _is_duplicate(self, store_id, message: IncomingMessage, bot_token: str) -> bool:
        """Idempotency: bu xabar avval qayta ishlanganmi?"""
        try:
            return ChatMessage.is_duplicate(
                store_id=store_id,
                message_id=message.message_id,
                platform=message.platform,
                sender_id=message.sender_id,
                bot_token=bot_token,
                chat_id=str(message.chat_id),
            )
        except Exception as e:
            logger.error(f"Idempotency tekshirishda xato: {e}", exc_info=True)
            # Xato bo'lsa — dublikat deb hisoblamay, davom etamiz
            return False


# ─────────────────────────────────────────────────────────────
# INSTAGRAM WEBHOOK
# ─────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class InstagramWebhookView(View):
    """
    Instagram / Meta webhook endpoint.

    URL: /webhook/instagram/
    GET  — Meta webhook verification (bir martalik)
    POST — Yangi xabarlar

    ⚠️ Barcha Meta do'konlari bir URL'ga keladi!
       page_id orqali qaysi do'kon ekanini aniqlaymiz.
    """

    def get(self, request):
        """Meta webhook tasdiqlash so'rovi (bir martalik)"""
        challenge = verify_instagram_challenge(request)
        if challenge:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponse(status=403)

    def post(self, request):
        """Instagram'dan kelgan yangi xabarlarni qabul qiladi"""

        # 1. HMAC imzo tekshiruvi
        if not verify_instagram_signature(request):
            logger.warning("Instagram: ruxsatsiz so'rov (imzo xato)")
            return HttpResponse(status=403)

        # 2. JSON parse
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Instagram: noto'g'ri JSON | {e}")
            return HttpResponse(status=200)

        # 3. Barcha xabarlarni parse qilamiz
        messages = parse_instagram_payload(payload)
        if not messages:
            return HttpResponse(status=200)

        # 4. Har bir xabarni navbatga qo'yamiz
        for message in messages:
            try:
                store = self._get_store_by_page_id(message.bot_token_hint)
                if not store:
                    logger.warning(
                        f"Instagram: do'kon topilmadi | "
                        f"page_id={message.bot_token_hint}"
                    )
                    continue

                # Idempotency tekshiruvi
                if ChatMessage.is_duplicate(
                    store_id=store.id,
                    message_id=message.message_id,
                    platform="instagram",
                    sender_id=message.sender_id,
                ):
                    logger.info(
                        f"Instagram: dublikat xabar skip | "
                        f"message_id={message.message_id}"
                    )
                    continue

                # Celery navbatiga
                task = process_incoming_message.apply_async(
                    kwargs={
                        "store_id": str(store.id),
                        "platform": "instagram",
                        "message_id": message.message_id,
                        "sender_id": message.sender_id,
                        "sender_username": message.sender_username,
                        "sender_display_name": message.sender_display_name,
                        "text": message.text,
                        "chat_id": message.chat_id,
                        "raw_payload": message.raw_payload,
                        "received_at": timezone.now().isoformat(),
                    },
                    queue="messages",
                    routing_key="messages",
                )
                logger.info(
                    f"Instagram xabari navbatga qo'yildi | "
                    f"task_id={task.id} | store={store.name}"
                )

            except Exception as e:
                logger.error(
                    f"Instagram xabarni navbatga qo'shishda xato: {e}",
                    exc_info=True,
                )
                continue

        return HttpResponse(status=200)

    def _get_store_by_page_id(self, page_id: str) -> Store | None:
        """Instagram Page ID bo'yicha aktiv do'konni topadi"""
        if not page_id:
            return None
        try:
            return Store.objects.select_related("owner").get(
                ig_page_id=page_id,
                is_active=True,
                is_deleted=False,
            )
        except Store.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Do'konni topishda xato: {e}", exc_info=True)
            return None


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────

def webhook_health(request):
    """
    Master SaaS Bot Gateway va Webhook serverining sog'lig'ini Telegram API /getMe orqali tekshirish.
    """
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    bot_username = "unknown"
    bot_active = False

    if bot_token:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)  # /getMe is a GET endpoint
                data = resp.json()
                if resp.status_code == 200 and data.get("ok"):
                    bot_active = True
                    bot_username = data.get("result", {}).get("username", "unknown")
                else:
                    # Bot token yaroqsiz bo'lsa — do'kon egasiga zudlik bilan Telegram xabarnomasi
                    #
                    # ⚠️ BUG FIX: /health endpoint uptime-monitor tomonidan har
                    # daqiqada chaqirilishi mumkin. Cache-based cooldown bo'lmasa,
                    # bot tokeni buzilgan har safar BARCHA do'kon egalariga
                    # qayta-qayta (masalan daqiqada bir marta) xabar ketardi —
                    # bu ham Telegram rate-limitga tegib botni bloklatib qo'yishi,
                    # ham egalarni spam bilan bezovta qilishi mumkin edi.
                    # Endi bu xabarnoma har bir bot uchun 1 soatda faqat bir marta yuboriladi.
                    from django.core.cache import cache
                    cooldown_key = f"webhook_health_alert_sent:{bot_token}"
                    if cache.add(cooldown_key, True, timeout=60 * 60):
                        from apps.stores.models import Store
                        from apps.chat.senders import send_telegram_message
                        stores = Store.objects.filter(is_active=True, is_deleted=False)
                        for store in stores:
                            if store.tg_owner_chat_id:
                                send_telegram_message(
                                    bot_token=bot_token,
                                    chat_id=store.tg_owner_chat_id,
                                    text="🚨 DIQQAT! PLATFORMA TELEGRAM BOTI ALOQADAN UZILDI!\n\nBot tokeni yaroqsiz bo'ldi yoki Telegram API ishlamayapti. Iltimos, sozlamalarni tekshiring!"
                                )
        except Exception as e:
            logger.error(f"Master Bot Health Check Exception: {e}")

    return JsonResponse({
        "status": "ok" if bot_active else "degraded",
        "service": "LeadNode Master SaaS Gateway",
        "bot_active": bot_active,
        "bot_username": f"@{bot_username}" if bot_username != "unknown" else None,
        "master_bot_model": True
    })
