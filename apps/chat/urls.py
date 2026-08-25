"""
Chat URLs — /api/v1/chat/
"""
from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import ChatMessageViewSet, ChatThreadListView

router = DefaultRouter()
router.register(r"", ChatMessageViewSet, basename="chat-message")

urlpatterns = [
    # Frontend ChatThread grouped endpoint
    path("threads/", ChatThreadListView.as_view(), name="chat-threads"),
] + router.urls
