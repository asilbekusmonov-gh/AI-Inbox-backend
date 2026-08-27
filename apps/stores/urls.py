"""
Store URLs
"""
from django.urls import path
from .views import StoreDetailUpdateView, StoreOnboardingView, InstagramConnectView, InstagramDisconnectView

app_name = "stores"

urlpatterns = [
    path("", StoreDetailUpdateView.as_view(), name="store-detail-update"),
    path("onboarding/", StoreOnboardingView.as_view(), name="store-onboarding"),
    path("instagram/connect/", InstagramConnectView.as_view(), name="instagram-connect"),
    path("instagram/disconnect/", InstagramDisconnectView.as_view(), name="instagram-disconnect"),
]

