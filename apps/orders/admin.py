from django.contrib import admin
from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "order_number", "store", "customer_full_name",
        "customer_phone", "status", "total_amount",
        "owner_notified", "created_at",
    ]
    list_filter = ["status", "platform", "owner_notified", "store"]
    search_fields = [
        "order_number", "customer_full_name",
        "customer_phone", "delivery_address",
    ]
    readonly_fields = [
        "id", "order_number", "created_at", "updated_at",
        "status_changed_at", "owner_notified_at",
    ]
    ordering = ["-created_at"]

    actions = ["mark_as_confirmed", "mark_as_cancelled"]

    @admin.action(description="Tasdiqlangan deb belgilash")
    def mark_as_confirmed(self, request, queryset):
        for order in queryset:
            order.update_status(Order.Status.CONFIRMED)

    @admin.action(description="Bekor qilindi deb belgilash")
    def mark_as_cancelled(self, request, queryset):
        for order in queryset:
            order.update_status(Order.Status.CANCELLED)

    def get_queryset(self, request):
        """Admin barcha yozuvlarni ko'rsin (o'chirilganlar ham)"""
        return self.model.all_objects.all()
