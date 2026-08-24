"""
Chat URLs
"""
from rest_framework.routers import DefaultRouter
from .views import ChatMessageViewSet

router = DefaultRouter()
router.register(r"", ChatMessageViewSet, basename="chat-message")

urlpatterns = router.urls
