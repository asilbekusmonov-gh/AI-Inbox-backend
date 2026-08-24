"""
AI-Inbox Backend — Asosiy URL konfiguratsiyasi
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from apps.core.views import twa_dashboard_view

urlpatterns = [
    # Bosh sahifa (http://localhost:8000/) kirilganda Swagger UI ga yo'naltiradi
    path("", RedirectView.as_view(url="/api/v1/docs/", permanent=False)),

    # Admin panel
    path("admin/", admin.site.urls),

    # Webhook endpointlar (Telegram + Instagram)
    path("webhook/", include("apps.webhooks.urls", namespace="webhooks")),

    # Telegram Mini App (TWA) Dashboard
    path("app/", twa_dashboard_view, name="twa-dashboard"),

    # API endpointlar v1
    path("api/v1/", include("apps.api.urls", namespace="v1")),
]

# Development rejimida media fayllarni serve qilish
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
