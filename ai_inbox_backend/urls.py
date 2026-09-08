"""
AI-Inbox Backend — Asosiy URL konfiguratsiyasi
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from apps.core.views import (
    twa_dashboard_view,
    privacy_policy_view,
    meta_data_deletion_callback,
    deletion_status_view,
)

urlpatterns = [
    # Bosh sahifa (http://localhost:8000/) kirilganda Admin Dashboard (TWA) ga yo'naltiradi
    # Swagger docs hali ham to'g'ridan-to'g'ri /api/v1/docs/ manzilida ochiladi
    path("", RedirectView.as_view(url="/app/", permanent=False)),

    # Admin panel
    path("admin/", admin.site.urls),

    # Webhook endpointlar (Telegram + Instagram)
    path("webhook/", include("apps.webhooks.urls", namespace="webhooks")),

    # Telegram Mini App (TWA) Dashboard — Next.js static build
    path("app/", twa_dashboard_view, name="twa-dashboard"),

    # Meta Verification & Legal Pages
    path("privacy-policy/", privacy_policy_view, name="privacy-policy"),
    path("deletion-status/", deletion_status_view, name="deletion-status"),
    path("api/v1/meta/data-deletion/", meta_data_deletion_callback, name="meta-data-deletion"),

    # API endpointlar v1
    path("api/v1/", include("apps.api.urls", namespace="v1")),
]

# Next.js (TWA) static build fayllari: /app/_next/... va /app/favicon.ico
#
# ⚠️ BUG FIX: bu urlpattern avval faqat `if settings.DEBUG:` blokida edi.
# Production'da DEBUG=False bo'lishi SHART (aks holda SECRET_KEY, stack
# trace va boshqa nozik ma'lumotlar hamma uchun ochiq bo'lib qoladi!) —
# lekin DEBUG=False bo'lgan zahoti bu urlpattern butunlay yo'qolib,
# nginx.conf'da ham /app/_next/ uchun alohida location yo'qligi sababli
# dashboardning barcha JS/CSS fayllari 404 bo'lib qolar edi (index.html
# ochiladi, lekin bo'sh/uslubsiz sahifa ko'rinadi). Shu sababli bu
# urlpattern endi DEBUG holatidan qat'iy nazar doim ro'yxatga olinadi.
#
# Eslatma: katta trafikli production uchun bu fayllarni Django o'rniga
# to'g'ridan-to'g'ri nginx orqali serve qilish tavsiya etiladi (tezroq va
# Django worker'larini band qilmaydi) — nginx.conf'ga mos `location`
# qo'shib, TWA_STATIC_DIR'ni nginx konteyneriga volume sifatida ulash orqali.
import os
from django.views.static import serve
from django.urls import re_path

TWA_STATIC_DIR = os.path.join(settings.BASE_DIR, "static", "twa")
urlpatterns += [
    re_path(r"^app/(?P<path>.+)$", serve, {"document_root": TWA_STATIC_DIR}),
]

# Development rejimida Django'ning o'zi media va static fayllarni serve qiladi.
# Production'da bularni nginx.conf'dagi /static/ va /media/ location'lari
# to'g'ridan-to'g'ri serve qiladi (static_volume / media_volume orqali),
# shuning uchun bu ikkalasi hali ham faqat DEBUG=True'da kerak.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
