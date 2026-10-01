"""
Lead/Voronka Statistikasi Xizmati.

⚠️ `compute_store_funnel_stats` — avval `apps/orders/views.py::LeadViewSet.stats`
ichida qattiq yozilgan edi. Endi Super Admin panel (bizneslar bo'yicha
statistika, `apps/stores/views.py::SuperAdminBusinessStatisticsView`) ham,
do'kon egasining o'z TWA'si ham AYNAN shu logikani chaqiradi — ikki joyda
takrorlanmasin (va ikkisida ham AYNAN bir xil, allaqachon bir necha marta
tuzatilgan timezone/voronka hisob-kitoblari ishlatiladi).
"""
from django.db.models import Avg, Count, Min
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Lead

_UZ_MONTHS_SHORT = ["", "Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"]


def compute_store_funnel_stats(store) -> dict:
    """
    Berilgan do'kon uchun to'liq voronka statistikasini hisoblaydi:

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

    leads_qs = Lead.objects.filter(store=store, is_deleted=False)

    avg_latency_ms = ChatMessage.objects.filter(
        store=store,
        role=ChatMessage.Role.ASSISTANT,
        latency_ms__isnull=False,
        created_at__gte=timezone.now() - timezone.timedelta(days=7),
    ).aggregate(avg=Avg("latency_ms"))["avg"]
    avg_response_time_seconds = round(avg_latency_ms / 1000, 1) if avg_latency_ms else None

    owner_chat_id = store.tg_owner_chat_id
    customers_qs = Customer.objects.filter(store=store, is_deleted=False)
    if owner_chat_id:
        customers_qs = customers_qs.exclude(platform_user_id=owner_chat_id)

    interactions_total = customers_qs.count()

    conversed_total = customers_qs.filter(
        messages__role=ChatMessage.Role.ASSISTANT,
        messages__message_id__startswith="ai_resp_",
    ).distinct().count()

    leads_total = leads_qs.count()

    today_start = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    leads_today = leads_qs.filter(created_at__gte=today_start).count()

    warm_count = leads_qs.filter(lead_status=Lead.LeadStatus.WARM).count()
    hot_count = leads_qs.filter(lead_status=Lead.LeadStatus.HOT).count()
    unqualified_count = leads_qs.filter(lead_status=Lead.LeadStatus.UNQUALIFIED).count()

    conversion_rate = round((leads_total / interactions_total) * 100, 1) if interactions_total else 0.0

    # ── Oylik trend: do'kon yaratilgan oydan hozirgi oygacha ──
    store_start = timezone.localtime(store.created_at).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    now = timezone.localtime(timezone.now())
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    monthly_counts = (
        leads_qs.filter(created_at__gte=store_start)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
    )
    monthly_map = {row["month"].strftime("%Y-%m"): row["count"] for row in monthly_counts}

    interactions_monthly_counts = (
        customers_qs.filter(created_at__gte=store_start)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
    )
    interactions_monthly_map = {row["month"].strftime("%Y-%m"): row["count"] for row in interactions_monthly_counts}

    conversed_first_dates_qs = ChatMessage.all_objects.filter(
        store=store, role=ChatMessage.Role.ASSISTANT, message_id__startswith="ai_resp_",
    )
    if owner_chat_id:
        conversed_first_dates_qs = conversed_first_dates_qs.exclude(customer__platform_user_id=owner_chat_id)
    conversed_first_dates = (
        conversed_first_dates_qs
        .values("customer_id")
        .annotate(first_conversed=Min("created_at"))
    )
    conversed_monthly_map: dict[str, int] = {}
    for row in conversed_first_dates:
        first_conversed = row["first_conversed"]
        if first_conversed and first_conversed >= store_start:
            key = timezone.localtime(first_conversed).strftime("%Y-%m")
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

    return {
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
    }
