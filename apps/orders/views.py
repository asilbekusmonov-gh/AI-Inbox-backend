"""
Lead Views — DRF (Multi-tenant, faqat o'qish)

⚠️ ATAYLAB faqat List/Retrieve: lidlarga holat/CRM boshqaruvi bu loyihada
yo'q — AI lead_status'ni belgilaydi, egasi TWA'dan qo'lda o'zgartirmaydi.
"""
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

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
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

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """
        TWA "Statistika" ekrani uchun umumiy ko'rsatkichlar:
        GET /api/v1/orders/stats/

        - interactions_total: bot bilan yozishgan (o'ziga xos) mijozlar soni
        - leads_total/leads_today: lid soni (jami / bugun)
        - conversion_rate: leads_total / interactions_total (%)
        - warm/cold/unqualified_count: AI baholagan lid holatlari bo'yicha son
        - monthly_trend: do'kon yaratilgan oydan hozirgi oygacha, oylik lid dinamikasi
        """
        from apps.customers.models import Customer

        target_store = self._get_target_store()
        if not target_store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        leads_qs = Lead.objects.filter(store=target_store, is_deleted=False)
        interactions_total = Customer.objects.filter(store=target_store, is_deleted=False).count()
        leads_total = leads_qs.count()

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        leads_today = leads_qs.filter(created_at__gte=today_start).count()

        warm_count = leads_qs.filter(lead_status=Lead.LeadStatus.WARM).count()
        cold_count = leads_qs.filter(lead_status=Lead.LeadStatus.COLD).count()
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
                "leads": monthly_map.get(key, 0),
            })
            cursor = (cursor + timezone.timedelta(days=32)).replace(day=1)

        return Response({
            "interactions_total": interactions_total,
            "leads_total": leads_total,
            "leads_today": leads_today,
            "conversion_rate": conversion_rate,
            "warm_count": warm_count,
            "cold_count": cold_count,
            "unqualified_count": unqualified_count,
            "monthly_trend": monthly_trend,
        })
