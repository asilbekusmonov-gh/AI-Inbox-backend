"""
Lead Views — DRF (Multi-tenant, faqat o'qish)

⚠️ ATAYLAB faqat List/Retrieve: lidlarga holat/CRM boshqaruvi bu loyihada
yo'q — AI lead_status'ni belgilaydi, egasi TWA'dan qo'lda o'zgartirmaydi.
"""
from django.core import signing
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, mixins, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead
from .serializers import LeadSerializer
from apps.core.authentication import get_store_from_request

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
        from .services import compute_store_funnel_stats

        target_store = self._get_target_store()
        if not target_store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        return Response(compute_store_funnel_stats(target_store))

