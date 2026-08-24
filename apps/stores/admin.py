from django.contrib import admin
from .models import Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = [
        "name", "owner", "platform",
        "subscription_plan", "is_active",
        "has_instagram", "has_telegram", "created_at",
    ]
    list_filter = ["platform", "subscription_plan", "is_active"]
    search_fields = ["name", "owner__username", "owner__email"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["-created_at"]

    fieldsets = (
        ("Asosiy ma'lumotlar", {
            "fields": ("id", "owner", "name", "platform", "is_active")
        }),
        ("Instagram sozlamalari", {
            "fields": ("ig_page_id", "ig_access_token", "ig_token_expires_at"),
            "classes": ("collapse",),
        }),
        ("Telegram sozlamalari", {
            "fields": ("tg_bot_token", "tg_bot_username", "tg_owner_chat_id"),
            "classes": ("collapse",),
        }),
        ("AI sozlamalari", {
            "fields": ("ai_system_prompt", "ai_model", "ai_temperature", "ai_max_tokens"),
            "classes": ("collapse",),
        }),
        ("Obuna", {
            "fields": ("subscription_plan", "monthly_message_limit"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at", "is_deleted"),
            "classes": ("collapse",),
        }),
    )
