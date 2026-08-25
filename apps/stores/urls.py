"""
Store URLs
"""
from django.urls import path
from .views import StoreDetailUpdateView, StoreOnboardingView

app_name = "stores"

urlpatterns = [
    path("", StoreDetailUpdateView.as_view(), name="store-detail-update"),
    path("onboarding/", StoreOnboardingView.as_view(), name="store-onboarding"),
]
