from django.contrib import admin
from .models import ChatMessage, BroadcastCampaign


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = [
        "store", "customer", "role", "platform",
        "processing_status", "retry_count",
        "tokens_used", "created_at",
    ]
    list_filter = ["role", "platform", "processing_status", "store"]
    search_fields = ["content", "message_id", "customer__full_name"]
    readonly_fields = [
        "id", "message_id", "raw_payload",
        "celery_task_id", "created_at", "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self, request):
        """Admin barcha yozuvlarni ko'rsin (o'chirilganlar ham)"""
        return self.model.all_objects.all()


@admin.register(BroadcastCampaign)
class BroadcastCampaignAdmin(admin.ModelAdmin):
    list_display = ["title", "store", "status", "total_recipients", "sent_count", "failed_count", "created_at"]
    list_filter = ["status", "store"]
    search_fields = ["title", "message_text"]
