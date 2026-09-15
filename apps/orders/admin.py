from django.contrib import admin
from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = [
        "lead_number", "store", "customer_full_name",
        "customer_phone", "lead_status", "source",
        "owner_notified", "created_at",
    ]
    list_filter = ["lead_status", "source", "platform", "owner_notified", "store"]
    search_fields = [
        "lead_number", "customer_full_name", "customer_phone",
    ]
    readonly_fields = [
        "id", "lead_number", "created_at", "updated_at",
        "owner_notified_at", "exported_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self, request):
        """Admin barcha yozuvlarni ko'rsin (o'chirilganlar ham)"""
        return self.model.all_objects.all()
