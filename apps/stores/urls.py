"""
Store URLs
"""
from django.urls import path
from .views import (
    StoreDetailUpdateView,
    StoreOnboardingView,
    InstagramConnectView,
    InstagramDisconnectView,
    TelegramBotConnectView,
    TelegramBotDisconnectView,
    TelegramGroupDisconnectView,
    StoreStaffMemberListCreateView,
    StoreStaffMemberDeleteView,
    CatalogParseView,
)

app_name = "stores"

urlpatterns = [
    path("", StoreDetailUpdateView.as_view(), name="store-detail-update"),
    path("onboarding/", StoreOnboardingView.as_view(), name="store-onboarding"),
    path("parse-catalog/", CatalogParseView.as_view(), name="store-parse-catalog"),
    path("instagram/connect/", InstagramConnectView.as_view(), name="instagram-connect"),
    path("instagram/disconnect/", InstagramDisconnectView.as_view(), name="instagram-disconnect"),
    path("telegram/connect-bot/", TelegramBotConnectView.as_view(), name="telegram-bot-connect"),
    path("telegram/disconnect-bot/", TelegramBotDisconnectView.as_view(), name="telegram-bot-disconnect"),
    path("telegram/group/disconnect/", TelegramGroupDisconnectView.as_view(), name="telegram-group-disconnect"),
    path("staff/", StoreStaffMemberListCreateView.as_view(), name="staff-list-create"),
    path("staff/<uuid:pk>/", StoreStaffMemberDeleteView.as_view(), name="staff-delete"),
]

