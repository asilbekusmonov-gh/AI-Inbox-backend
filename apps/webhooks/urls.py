"""
Webhook URL'lari
"""
from django.urls import path
from .views import TelegramWebhookView, InstagramWebhookView, webhook_health

app_name = "webhooks"

urlpatterns = [
    # Telegram — har bir do'konning boti o'ziga xos token bilan
    path(
        "telegram/<str:bot_token>/",
        TelegramWebhookView.as_view(),
        name="telegram",
    ),

    # Instagram — barcha do'konlar bir URL (page_id orqali farqlanadi)
    path(
        "instagram/",
        InstagramWebhookView.as_view(),
        name="instagram",
    ),

    # Health check
    path(
        "health/",
        webhook_health,
        name="health",
    ),
]
