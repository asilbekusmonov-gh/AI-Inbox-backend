"""
Lead Views — DRF (Multi-tenant, faqat o'qish)

⚠️ ATAYLAB faqat List/Retrieve: lidlarga holat/CRM boshqaruvi bu loyihada
yo'q — AI lead_status'ni belgilaydi, egasi TWA'dan qo'lda o'zgartirmaydi.
"""
from django.core import signing
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, mixins, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead
from .serializers import LeadSerializer
from apps.core.authentication import get_store_from_request

_UZ_MONTHS_SHORT = ["", "Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"]

# ⚠️ Telegram Mini App'ning O'ZI fayl yuklab olishi uchun (tg.downloadFile —
# Telegram klientining o'z native "Saqlash" dialogi orqali, JS blob/anchor
# klik hiyla-nayranglaridan farqli o'laroq HAR DOIM ishlaydigan yagona usul)
# oddiy HTTPS manzil kerak — Telegram o'zi shu manzilga so'rov yuboradi va
# bizning odatdagi Authorization/X-Telegram-Init-Data sarlavhalarimizni
# BIRIKTIRA OLMAYDI. Shu sabab qisqa muddatli (2 daqiqa) imzolangan token
# — oddiy JWT/initData o'rniga, faqat shu bitta eksport uchun, faqat shu
# muddatga — URL query parametri sifatida ishlatiladi.
EXPORT_TOKEN_SALT = "orders.export_excel"
EXPORT_TOKEN_MAX_AGE = 120  # sekund


class LeadViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Lidlarni ko'rish va qidirish.
    """
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["lead_number", "customer_full_name", "customer_phone"]
    ordering_fields = ["created_at", "lead_status"]
    ordering = ["-created_at"]

    def get_permissions(self):
        # `export_excel`ga imzolangan tokeni bilan kelingan bo'lsa — bu
        # so'rov Telegram klientining O'ZIDAN kelayapti (auth
        # sarlavhalarisiz), shuning uchun standart IsAuthenticated'ni
        # o'tkazib yuboramiz — pastdagi `_get_target_store` tokenning
        # o'zini tekshirib, faqat unga mos do'konni qaytaradi (boshqa
        # do'konga hech qanday kirish imkoni yo'q).
        if self.action == "export_excel" and self.request.query_params.get("token"):
            return [permissions.AllowAny()]
        return super().get_permissions()

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
        token = self.request.query_params.get("token")
        if token:
            try:
                store_id = signing.loads(token, salt=EXPORT_TOKEN_SALT, max_age=EXPORT_TOKEN_MAX_AGE)
            except signing.BadSignature:
                return None
            from apps.stores.models import Store
            return Store.objects.filter(id=store_id, is_deleted=False).first()
        return get_store_from_request(self.request)

    def get_queryset(self):
        """Multi-tenant: Faqat tegishli store lidlari va o'chirilmaganlari"""
        target_store = self._get_target_store()
        if not target_store:
            return Lead.objects.none()
        return Lead.objects.filter(store=target_store, is_deleted=False).order_by("-created_at")

    @action(detail=False, methods=["get"], url_path="export-excel")
    def export_excel(self, request):
        """
        Hozirgi (filtrlangan) lidlar ro'yxatini .xlsx fayl sifatida yuklab beradi:
        GET /api/v1/orders/export-excel/?search=...&ordering=...
        """
        from .excel_export import build_leads_workbook

        queryset = self.filter_queryset(self.get_queryset()).select_related("interested_course")
        buffer = build_leads_workbook(queryset)

        # Eksport qilingan lidlarni belgilaymiz — TWA'da "eksport qilingan"
        # holatini ko'rsatish uchun (Lead.exported_to/exported_at Step 1'da
        # aynan shu maqsadda qo'shilgan edi).
        Lead.objects.filter(id__in=queryset.values_list("id", flat=True)).update(
            exported_to=Lead.ExportStatus.EXCEL,
            exported_at=timezone.now(),
        )

        filename = f"lidlar_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
        response = HttpResponse(
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=["post"], url_path="send-excel-to-chat")
    def send_excel_to_chat(self, request):
        """
        Excel faylni Mini App orqali "yuklab olish"ga urinish o'rniga,
        botning o'zi do'kon egasining shaxsiy Telegram chatiga oddiy
        HUJJAT xabari sifatida yuboradi:
        POST /api/v1/orders/send-excel-to-chat/

        ⚠️ Mini App'ning JS/native "yuklab olish" ko'prigi (blob/anchor
        klik yoki Telegram'ning o'z `downloadFile()` metodi) turli
        klient/versiyalarda beqaror ishlashi jonli testda aniqlandi —
        oddiy chat hujjati esa Telegram'ning eng asosiy, har doim bir
        xilda ishlaydigan funksiyasi.
        """
        from .excel_export import build_leads_workbook
        from apps.chat.senders import send_telegram_document

        target_store = self._get_target_store()
        if not target_store:
            return Response(
                {"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND
            )
        if not target_store.tg_owner_chat_id or not target_store.tg_bot_token:
            return Response(
                {"error": "Telegram bot hali ulanmagan yoki do'kon egasi aniqlanmagan"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = Lead.objects.filter(
            store=target_store, is_deleted=False
        ).select_related("interested_course").order_by("-created_at")
        buffer = build_leads_workbook(queryset)

        Lead.objects.filter(id__in=queryset.values_list("id", flat=True)).update(
            exported_to=Lead.ExportStatus.EXCEL,
            exported_at=timezone.now(),
        )

        filename = f"lidlar_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
        sent = send_telegram_document(
            bot_token=target_store.tg_bot_token,
            chat_id=target_store.tg_owner_chat_id,
            file_bytes=buffer.read(),
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            caption=f"📊 Leadlar ro'yxati — {queryset.count()} ta lead",
        )
        if not sent:
            return Response(
                {"error": "Telegram'ga yuborib bo'lmadi, birozdan so'ng qayta urinib ko'ring"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"success": True})

    @action(detail=False, methods=["get"], url_path="export-excel-link")
    def export_excel_link(self, request):
        """
        Telegram Mini App'ning native `downloadFile()` metodi uchun
        qisqa muddatli (2 daqiqa) imzolangan token bilan to'liq URL beradi:
        GET /api/v1/orders/export-excel-link/ (odatdagi auth bilan)

        Frontend bu URL'ni to'g'ridan-to'g'ri `tg.downloadFile()`ga
        beradi — Telegram klienti o'zi shu manzilga (auth sarlavhasiz)
        so'rov yuboradi, shuning uchun autentifikatsiya normal so'rov
        oqimida TEKSHIRILADI, keyin token ICHIGA "muhrlanadi".
        """
        target_store = self._get_target_store()
        if not target_store:
            return Response(
                {"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND
            )

        from django.conf import settings as dj_settings

        token = signing.dumps(str(target_store.id), salt=EXPORT_TOKEN_SALT)
        public_url = getattr(dj_settings, "PUBLIC_URL", "").rstrip("/")
        filename = f"lidlar_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return Response({
            "url": f"{public_url}/api/v1/orders/export-excel/?token={token}",
            "filename": filename,
        })

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """
        TWA "Statistika" ekrani uchun umumiy ko'rsatkichlar:
        GET /api/v1/orders/stats/

        - interactions_total: bot bilan yozishgan (o'ziga xos) mijozlar soni
        - conversed_total: haqiqiy AI muloqoti bo'lgan (o'ziga xos) mijozlar soni
        - leads_total/leads_today: lid soni (jami / bugun)
        - conversion_rate: leads_total / interactions_total (%)
        - warm/hot/unqualified_count: AI baholagan lid holatlari bo'yicha son
        - monthly_trend: do'kon yaratilgan oydan hozirgi oygacha, har oy uchun
          {month, label, interactions, conversed, leads} — voronkaning HAR
          UCHALA bosqichi bo'yicha oylik dinamika
        """
        from apps.customers.models import Customer
        from apps.chat.models import ChatMessage
        from django.db.models import Avg

        target_store = self._get_target_store()
        if not target_store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        leads_qs = Lead.objects.filter(store=target_store, is_deleted=False)

        # Requirement 9 (latency monitoring): so'nggi 7 kunlik AI javob
        # tezligi o'rtacha ko'rsatkichi — egasi "AI sekinlashib qolmadimi"
        # degan savolga TWA'ning o'zidan javob topishi uchun.
        avg_latency_ms = ChatMessage.objects.filter(
            store=target_store,
            role=ChatMessage.Role.ASSISTANT,
            latency_ms__isnull=False,
            created_at__gte=timezone.now() - timezone.timedelta(days=7),
        ).aggregate(avg=Avg("latency_ms"))["avg"]
        avg_response_time_seconds = round(avg_latency_ms / 1000, 1) if avg_latency_ms else None

        # ⚠️ BUG FIX (jonli holatda aniqlangan): do'kon egasi o'z botini
        # sinab ko'rish uchun unga yozganda (masalan /start), bu ham oddiy
        # Customer yozuvi sifatida saqlanadi — natijada "Qiziqish
        # bildirganlar" sonida EGANING O'ZI "mijoz" sifatida hisoblanib
        # qolgan edi (egasi "hali hech kim yozmagan-ku, nega 1 ta
        # ko'rsatilyapti" deb aniq ta'kidladi). Statistika FAQAT haqiqiy
        # mijozlarni aks ettirishi kerak, shuning uchun egasining
        # `tg_owner_chat_id`siga mos Customer voronkaning HAR bosqichidan
        # (jami, oylik) chetlab o'tiladi.
        owner_chat_id = target_store.tg_owner_chat_id
        customers_qs = Customer.objects.filter(store=target_store, is_deleted=False)
        if owner_chat_id:
            customers_qs = customers_qs.exclude(platform_user_id=owner_chat_id)

        interactions_total = customers_qs.count()

        # ⚠️ Do'kon egasi aniq voronka (funnel) so'radi: "nechta kishi
        # /start bosdi (=interactions_total), nechtasi HAQIQIY muloqot
        # qildi, nechtasi lidga aylandi" — avval faqat 2 chetki nuqta
        # (interactions_total, leads_total) bor edi, "haqiqiy muloqot"
        # bosqichi umuman ko'rsatilmasdi. "Haqiqiy muloqot" — mijoz
        # shunchaki /start bosib (statik shablon javob, message_id=
        # "cmd_reply_...") jim qolmasdan, AI bilan haqiqiy javob-savob
        # (message_id="ai_resp_...", qarang: apps/webhooks/tasks.py)
        # almashgani bilan aniqlanadi.
        # ⚠️ BUG FIX: bu yerda ATAYLAB `messages__is_deleted=False` filtri
        # QO'SHILMAYDI. Sabab: Inbox'da "suhbatni o'chirish" — bu faqat
        # UI/gigiena tozalashi (masalan sinov yozishmalarini olib
        # tashlash), lekin mantiqiy jihatdan agar mijoz LID bo'lgan bo'lsa,
        # u albatta avval "muloqot" bosqichidan o'tgan — buni keyinchalik
        # suhbat o'chirilgani INKOR ETA OLMAYDI. Agar bu yerda
        # `is_deleted=False` qo'shilsa, ba'zi eski lidlarning suhbati
        # tozalangan bo'lsa, "Lidga aylanganlar" soni "Muloqot qilganlar"
        # sonidan KATTA bo'lib qolib, voronka yana mantiqsiz ko'rinardi
        # (jonli holatda aniqlandi). Shu sabab bu yerda ATAYLAB xom SQL
        # JOIN (Django `messages__` — `ChatMessage`ning soft-delete
        # menejerini chetlab o'tib, BARCHA — hatto o'chirilgan — xabarlarni
        # ham hisobga oladi) ishlatiladi; pastdagi oylik taqsimot ham
        # muvofiqlik uchun xuddi shunday `ChatMessage.all_objects`dan
        # foydalanadi.
        conversed_total = customers_qs.filter(
            messages__role=ChatMessage.Role.ASSISTANT,
            messages__message_id__startswith="ai_resp_",
        ).distinct().count()

        leads_total = leads_qs.count()

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        leads_today = leads_qs.filter(created_at__gte=today_start).count()

        warm_count = leads_qs.filter(lead_status=Lead.LeadStatus.WARM).count()
        hot_count = leads_qs.filter(lead_status=Lead.LeadStatus.HOT).count()
        unqualified_count = leads_qs.filter(lead_status=Lead.LeadStatus.UNQUALIFIED).count()

        conversion_rate = round((leads_total / interactions_total) * 100, 1) if interactions_total else 0.0

        # ── Oylik trend: do'kon yaratilgan oydan hozirgi oygacha ──
        # (avval qattiq "oxirgi 6 oy" bo'lgan — endi butun tarix ko'rsatiladi,
        # MAX_MONTHS esa faqat juda eski do'konlar uchun javobni cheksiz
        # katta qilib yubormaslik uchun xavfsizlik chegarasi)
        store_start = target_store.created_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly_counts = (
            leads_qs.filter(created_at__gte=store_start)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
        )
        monthly_map = {row["month"].strftime("%Y-%m"): row["count"] for row in monthly_counts}

        # ⚠️ Do'kon egasi voronkaning HAR BIR bosqichi (qiziqish, batafsil
        # ma'lumot, lid) uchun ham OYLIK dinamikani so'radi — avval faqat
        # lidlar uchun oylik trend bor edi, "qiziqish bildirganlar" va
        # "batafsil ma'lumot olganlar" umuman oy bo'yicha ko'rsatilmasdi
        # (masalan "1 oyda 8000 qiziqish, 7600 batafsil, 4000 lid" kabi
        # hisobot berish imkonsiz edi). "Qiziqish" — mijoz (Customer)
        # birinchi marta QAChON yaratilgani (created_at) bo'yicha oyga
        # bo'linadi. "Batafsil ma'lumot" — har bir mijozning ENG BIRINCHI
        # haqiqiy AI javobi (ai_resp_) qaysi oyda bo'lganiga qarab
        # (Min("created_at")) — shu orqali bitta mijoz ikki oyda yozgan
        # bo'lsa ham faqat BIRINCHI oyida hisoblanadi, ikkala metrikada
        # ham (interactions_total/conversed_total) ishlatilgan "o'ziga
        # xos mijozlar soni" mantig'iga mos kelishi uchun.
        interactions_monthly_counts = (
            customers_qs.filter(created_at__gte=store_start)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
        )
        interactions_monthly_map = {row["month"].strftime("%Y-%m"): row["count"] for row in interactions_monthly_counts}

        from django.db.models import Min as _Min
        conversed_first_dates_qs = ChatMessage.all_objects.filter(
            store=target_store, role=ChatMessage.Role.ASSISTANT, message_id__startswith="ai_resp_",
        )
        if owner_chat_id:
            conversed_first_dates_qs = conversed_first_dates_qs.exclude(customer__platform_user_id=owner_chat_id)
        conversed_first_dates = (
            conversed_first_dates_qs
            .values("customer_id")
            .annotate(first_conversed=_Min("created_at"))
        )
        conversed_monthly_map: dict[str, int] = {}
        for row in conversed_first_dates:
            first_conversed = row["first_conversed"]
            if first_conversed and first_conversed >= store_start:
                key = first_conversed.strftime("%Y-%m")
                conversed_monthly_map[key] = conversed_monthly_map.get(key, 0) + 1

        MAX_MONTHS = 36
        months_spanned = (
            (current_month_start.year - store_start.year) * 12
            + (current_month_start.month - store_start.month)
            + 1
        )

        cursor = store_start
        if months_spanned > MAX_MONTHS:
            skip = months_spanned - MAX_MONTHS
            for _ in range(skip):
                cursor = (cursor + timezone.timedelta(days=32)).replace(day=1)
            months_spanned = MAX_MONTHS

        show_year = store_start.year != current_month_start.year

        monthly_trend = []
        for _ in range(months_spanned):
            key = cursor.strftime("%Y-%m")
            label = _UZ_MONTHS_SHORT[cursor.month]
            if show_year:
                label = f"{label} {cursor.strftime('%y')}"
            monthly_trend.append({
                "month": key,
                "label": label,
                "interactions": interactions_monthly_map.get(key, 0),
                "conversed": conversed_monthly_map.get(key, 0),
                "leads": monthly_map.get(key, 0),
            })
            cursor = (cursor + timezone.timedelta(days=32)).replace(day=1)

        return Response({
            "interactions_total": interactions_total,
            "conversed_total": conversed_total,
            "leads_total": leads_total,
            "leads_today": leads_today,
            "conversion_rate": conversion_rate,
            "warm_count": warm_count,
            "hot_count": hot_count,
            "unqualified_count": unqualified_count,
            "avg_response_time_seconds": avg_response_time_seconds,
            "monthly_trend": monthly_trend,
        })
