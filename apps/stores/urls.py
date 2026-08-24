"""
Store URLs
"""
from django.urls import path
from .views import StoreDetailUpdateView

app_name = "stores"

urlpatterns = [
    path("", StoreDetailUpdateView.as_view(), name="store-detail-update"),
]
