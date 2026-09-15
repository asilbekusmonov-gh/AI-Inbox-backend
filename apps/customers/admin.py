from django.contrib import admin
from .models import Customer, CustomerSession


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = [
        "full_name", "phone_number", "platform",
        "store", "total_leads", "last_message_at",
    ]
    list_filter = ["platform", "store"]
    search_fields = ["full_name", "phone_number", "username", "platform_user_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["-last_message_at"]


@admin.register(CustomerSession)
class CustomerSessionAdmin(admin.ModelAdmin):
    list_display = ["platform_user_id", "active_store", "updated_at"]
    search_fields = ["platform_user_id", "active_store__name"]
