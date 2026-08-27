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
    # Bosh sahifa (http://localhost:8000/) kirilganda Swagger UI ga yo'naltiradi
    path("", RedirectView.as_view(url="/api/v1/docs/", permanent=False)),

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

# Development rejimida media va static fayllarni serve qilish
if settings.DEBUG:
    import os
    from django.views.static import serve
    from django.urls import re_path

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # Next.js static build fayllari uchun: /app/_next/... va /app/favicon.ico
    TWA_STATIC_DIR = os.path.join(settings.BASE_DIR, "static", "twa")
    urlpatterns += [
        re_path(r"^app/(?P<path>.+)$", serve, {"document_root": TWA_STATIC_DIR}),
    ]
